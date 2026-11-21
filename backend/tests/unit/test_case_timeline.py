from datetime import date, timedelta

import pytest

from vapas.cases.timeline import (
    CaseFacts,
    CaseState,
    EscalationChecks,
    TransitionError,
    close,
    compute_deadlines,
    days_left,
    escalate,
    mark_sent,
    record_communication,
    record_receipt,
    record_reply,
    tick,
)
from vapas.rules.loader import load_rulebook

RULES = load_rulebook()
CLEAN = EscalationChecks(already_with_ombudsman=False, in_court_or_other_forum=False)


def received(on: date, today: date, waits: tuple[int | None, ...] = (None,)) -> CaseFacts:
    facts, _ = mark_sent(CaseFacts(CaseState.DRAFT), on, today)
    facts, _ = record_receipt(facts, on, today, RULES, waits)
    return facts


def test_deadline_is_30_plus_90_days_without_any_reply() -> None:
    deadlines = compute_deadlines(RULES, date(2026, 8, 1), (None,), None, None)
    assert deadlines is not None
    assert (deadlines.eligible_on, deadlines.filing_deadline_on) == (date(2026, 8, 31), date(2026, 11, 29))
    assert (deadlines.wait_rule_id, deadlines.deadline_rule_id) == ("rbi.rbios26.wait", "rbi.rbios26.deadline")


def test_unsatisfactory_reply_makes_it_eligible_early_but_deadline_counts_from_the_later_date() -> None:
    deadlines = compute_deadlines(RULES, date(2026, 8, 1), (None,), date(2026, 8, 10), date(2026, 8, 10))
    assert deadlines is not None
    assert deadlines.eligible_on == date(2026, 8, 10)
    assert deadlines.filing_deadline_on == date(2026, 11, 29)


def test_last_communication_after_the_wait_moves_the_deadline() -> None:
    deadlines = compute_deadlines(RULES, date(2026, 8, 1), (None,), date(2026, 9, 20), None)
    assert deadlines is not None
    assert deadlines.filing_deadline_on == date(2026, 9, 20) + timedelta(days=90)


def test_a_longer_system_wait_from_a_tat_rule_wins() -> None:
    deadlines = compute_deadlines(RULES, date(2026, 8, 1), (None, 45), None, None)
    assert deadlines is not None
    assert (deadlines.wait_days, deadlines.eligible_on) == (45, date(2026, 9, 15))


def test_before_rbios_2026_there_is_no_computed_deadline() -> None:
    assert compute_deadlines(RULES, date(2026, 6, 15), (None,), None, None) is None
    facts = received(date(2026, 6, 15), date(2026, 6, 20))
    assert (facts.state, facts.deadlines, days_left(facts, date(2026, 6, 20))) == (CaseState.AWAITING_REPLY, None, None)


def test_full_lifecycle_to_escalation() -> None:
    today = date(2026, 8, 1)
    facts, events = mark_sent(CaseFacts(CaseState.DRAFT), today, today)
    assert (facts.state, events[0][0]) == (CaseState.SENT_TO_BANK, "sent_to_bank")
    facts, events = record_receipt(facts, today, today, RULES, (None,))
    assert facts.state is CaseState.AWAITING_REPLY
    assert [e[0] for e in events] == ["awaiting_reply", "deadline_set"]
    assert days_left(facts, today) == 120
    facts, events = tick(facts, date(2026, 8, 30))
    assert (facts.state, events) == (CaseState.AWAITING_REPLY, [])
    facts, events = tick(facts, date(2026, 8, 31))
    assert (facts.state, events[0][0]) == (CaseState.ESCALATION_ELIGIBLE, "escalation_eligible")
    with pytest.raises(TransitionError) as blocked:
        escalate(facts, date(2026, 9, 5), EscalationChecks(True, False), date(2026, 9, 5))
    assert blocked.value.code == "blocked_clause_10"
    facts, events = escalate(facts, date(2026, 9, 5), CLEAN, date(2026, 9, 5))
    assert (facts.state, facts.escalated_on) == (CaseState.ESCALATED, date(2026, 9, 5))
    facts, _ = close(facts, "award received")
    assert facts.state is CaseState.CLOSED


def test_resolved_by_the_bank() -> None:
    facts = received(date(2026, 8, 1), date(2026, 8, 1))
    facts, events = record_reply(facts, date(2026, 8, 12), True, date(2026, 8, 12), RULES, (None,))
    assert (facts.state, events[0][0]) == (CaseState.RESOLVED, "resolved")


def test_unsatisfactory_reply_makes_the_case_eligible_at_once() -> None:
    facts = received(date(2026, 8, 1), date(2026, 8, 1))
    facts, events = record_reply(facts, date(2026, 8, 10), False, date(2026, 8, 10), RULES, (None,))
    assert facts.state is CaseState.ESCALATION_ELIGIBLE
    assert [e[0] for e in events] == ["unsatisfactory_reply", "deadline_set", "escalation_eligible"]


def test_missing_the_window_expires_the_case() -> None:
    facts = received(date(2026, 8, 1), date(2026, 8, 1))
    still, _ = tick(facts, date(2026, 11, 29))
    assert still.state is CaseState.ESCALATION_ELIGIBLE
    facts, events = tick(still, date(2026, 11, 30))
    assert (facts.state, events[0][0]) == (CaseState.EXPIRED, "expired")
    with pytest.raises(TransitionError):
        close(facts, "too late")


def test_filing_after_the_deadline_is_refused() -> None:
    facts = received(date(2026, 8, 1), date(2026, 8, 1))
    facts, _ = tick(facts, date(2026, 9, 1))
    with pytest.raises(TransitionError) as late:
        escalate(facts, date(2026, 12, 1), CLEAN, date(2026, 12, 1))
    assert late.value.code == "deadline_passed"


def test_communication_extends_the_deadline_and_records_an_event() -> None:
    facts = received(date(2026, 8, 1), date(2026, 8, 1))
    facts, events = record_communication(facts, date(2026, 10, 1), date(2026, 10, 1), RULES, (None,))
    assert facts.deadlines is not None
    assert facts.deadlines.filing_deadline_on == date(2026, 12, 30)
    assert events[0] == ("bank_communication", {"on": "2026-10-01"})


@pytest.mark.parametrize(
    ("action", "code"),
    [
        (lambda f: mark_sent(f, date(2026, 9, 1), date(2026, 8, 1)), "date_in_future"),
        (lambda f: escalate(f, date(2026, 8, 1), CLEAN, date(2026, 8, 1)), "invalid_state"),
    ],
)
def test_invalid_transitions(action: object, code: str) -> None:
    assert callable(action)
    with pytest.raises(TransitionError) as error:
        action(CaseFacts(CaseState.DRAFT))
    assert error.value.code == code


def test_receipt_before_sending_is_refused() -> None:
    facts, _ = mark_sent(CaseFacts(CaseState.DRAFT), date(2026, 8, 5), date(2026, 8, 5))
    with pytest.raises(TransitionError) as error:
        record_receipt(facts, date(2026, 8, 4), date(2026, 8, 5), RULES, (None,))
    assert error.value.code == "date_order"


def test_reminders_cover_eligibility_and_the_last_30_7_1_days() -> None:
    from vapas.cases.service import reminders_for

    facts = received(date(2026, 8, 1), date(2026, 8, 1))
    due = dict(reminders_for(facts, date(2026, 8, 1)))
    assert due == {
        "eligible": date(2026, 8, 31),
        "d30": date(2026, 10, 30),
        "d7": date(2026, 11, 22),
        "d1": date(2026, 11, 28),
    }
    late = dict(reminders_for(facts, date(2026, 11, 25)))
    assert set(late) == {"eligible", "d1"}
    resolved, _ = record_reply(facts, date(2026, 8, 5), True, date(2026, 8, 5), RULES, (None,))
    assert reminders_for(resolved, date(2026, 8, 5)) == []


@pytest.mark.parametrize("language", ["en", "hi"])
def test_reminder_messages_give_the_deadline_and_cms_steps(language: str) -> None:
    from vapas.cases.reminders import message

    subject, body = message("d7", language, "SBI", date(2026, 11, 29), date(2026, 11, 22))
    assert "7" in subject
    assert "29/11/2026" in body
    assert "https://cms.rbi.org.in" in body
    assert "State Bank of India" in body
    _, expired_body = message("expired", language, "UNKNOWN", date(2026, 11, 29), date(2026, 12, 1))
    assert "cms.rbi.org.in" not in expired_body
    assert "10(1)(g)" in expired_body
