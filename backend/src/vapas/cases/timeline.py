from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from enum import StrEnum
from typing import Any

from vapas.rules.loader import RuleBook

WAIT_RULE = "wait_before_escalation"
DEADLINE_RULE = "escalation_deadline"


class CaseState(StrEnum):
    DRAFT = "draft"
    SENT_TO_BANK = "sent_to_bank"
    AWAITING_REPLY = "awaiting_reply"
    RESOLVED = "resolved"
    ESCALATION_ELIGIBLE = "escalation_eligible"
    ESCALATED = "escalated"
    CLOSED = "closed"
    EXPIRED = "expired"


OPEN_TIMELINE = frozenset({CaseState.AWAITING_REPLY, CaseState.ESCALATION_ELIGIBLE})
FINAL = frozenset({CaseState.CLOSED, CaseState.EXPIRED})


class TransitionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Deadlines:
    wait_days: int
    timeline_ends_on: date
    eligible_on: date
    filing_deadline_on: date
    wait_rule_id: str
    deadline_rule_id: str


@dataclass(frozen=True)
class CaseFacts:
    state: CaseState
    sent_on: date | None = None
    received_on: date | None = None
    last_communication_on: date | None = None
    unsatisfied_reply_on: date | None = None
    escalated_on: date | None = None
    deadlines: Deadlines | None = None


Event = tuple[str, dict[str, Any]]


def compute_deadlines(
    rulebook: RuleBook,
    received_on: date,
    rule_wait_days: Sequence[int | None],
    last_communication_on: date | None,
    unsatisfied_reply_on: date | None,
) -> Deadlines | None:
    wait = rulebook.ombudsman(WAIT_RULE, received_on)
    window = rulebook.ombudsman(DEADLINE_RULE, received_on)
    if wait is None or window is None or wait.days is None or window.days is None:
        return None
    wait_days = max([wait.days, *(d for d in rule_wait_days if d)])
    timeline_ends_on = received_on + timedelta(days=wait_days)
    eligible_on = min(timeline_ends_on, unsatisfied_reply_on) if unsatisfied_reply_on else timeline_ends_on
    start = max(timeline_ends_on, last_communication_on or timeline_ends_on)
    return Deadlines(
        wait_days=wait_days,
        timeline_ends_on=timeline_ends_on,
        eligible_on=eligible_on,
        filing_deadline_on=start + timedelta(days=window.days),
        wait_rule_id=wait.id,
        deadline_rule_id=window.id,
    )


def _deadline_event(deadlines: Deadlines | None) -> Event:
    if deadlines is None:
        return (
            "deadline_unknown",
            {"reason": "no verified RB-IOS 2026 rule is in force on the date the bank received it"},
        )
    return (
        "deadline_set",
        {
            "wait_days": deadlines.wait_days,
            "eligible_on": deadlines.eligible_on.isoformat(),
            "filing_deadline_on": deadlines.filing_deadline_on.isoformat(),
            "rules": [deadlines.wait_rule_id, deadlines.deadline_rule_id],
        },
    )


def _require(facts: CaseFacts, *allowed: CaseState) -> None:
    if facts.state not in allowed:
        raise TransitionError("invalid_state", f"not allowed while the case is {facts.state.value}")


def _not_future(day: date, today: date, name: str) -> None:
    if day > today:
        raise TransitionError("date_in_future", f"{name} cannot be in the future")


def _recompute(facts: CaseFacts, rulebook: RuleBook, rule_wait_days: Sequence[int | None]) -> CaseFacts:
    if facts.received_on is None:
        return facts
    deadlines = compute_deadlines(
        rulebook, facts.received_on, rule_wait_days, facts.last_communication_on, facts.unsatisfied_reply_on
    )
    return replace(facts, deadlines=deadlines)


def mark_sent(facts: CaseFacts, sent_on: date, today: date) -> tuple[CaseFacts, list[Event]]:
    _require(facts, CaseState.DRAFT)
    _not_future(sent_on, today, "sent date")
    return replace(facts, state=CaseState.SENT_TO_BANK, sent_on=sent_on), [
        ("sent_to_bank", {"sent_on": sent_on.isoformat()})
    ]


def record_receipt(
    facts: CaseFacts, received_on: date, today: date, rulebook: RuleBook, rule_wait_days: Sequence[int | None]
) -> tuple[CaseFacts, list[Event]]:
    _require(facts, CaseState.SENT_TO_BANK)
    _not_future(received_on, today, "received date")
    if facts.sent_on and received_on < facts.sent_on:
        raise TransitionError("date_order", "the bank cannot receive the complaint before it was sent")
    updated = _recompute(
        replace(facts, state=CaseState.AWAITING_REPLY, received_on=received_on), rulebook, rule_wait_days
    )
    events = [("awaiting_reply", {"received_on": received_on.isoformat()}), _deadline_event(updated.deadlines)]
    ticked, more = tick(updated, today)
    return ticked, events + more


def record_reply(
    facts: CaseFacts,
    reply_on: date,
    resolved: bool,
    today: date,
    rulebook: RuleBook,
    rule_wait_days: Sequence[int | None],
) -> tuple[CaseFacts, list[Event]]:
    _require(facts, *OPEN_TIMELINE)
    _not_future(reply_on, today, "reply date")
    if facts.received_on and reply_on < facts.received_on:
        raise TransitionError("date_order", "the reply cannot come before the bank received the complaint")
    last = max(reply_on, facts.last_communication_on or reply_on)
    if resolved:
        return replace(facts, state=CaseState.RESOLVED, last_communication_on=last), [
            ("resolved", {"reply_on": reply_on.isoformat()})
        ]
    unsatisfied = facts.unsatisfied_reply_on or reply_on
    updated = _recompute(
        replace(facts, last_communication_on=last, unsatisfied_reply_on=unsatisfied), rulebook, rule_wait_days
    )
    events = [("unsatisfactory_reply", {"reply_on": reply_on.isoformat()}), _deadline_event(updated.deadlines)]
    ticked, more = tick(updated, today)
    return ticked, events + more


def record_communication(
    facts: CaseFacts, on: date, today: date, rulebook: RuleBook, rule_wait_days: Sequence[int | None]
) -> tuple[CaseFacts, list[Event]]:
    _require(facts, *OPEN_TIMELINE)
    _not_future(on, today, "communication date")
    last = max(on, facts.last_communication_on or on)
    updated = _recompute(replace(facts, last_communication_on=last), rulebook, rule_wait_days)
    events = [("bank_communication", {"on": on.isoformat()}), _deadline_event(updated.deadlines)]
    ticked, more = tick(updated, today)
    return ticked, events + more


@dataclass(frozen=True)
class EscalationChecks:
    already_with_ombudsman: bool
    in_court_or_other_forum: bool


def escalate(facts: CaseFacts, filed_on: date, checks: EscalationChecks, today: date) -> tuple[CaseFacts, list[Event]]:
    _require(facts, CaseState.ESCALATION_ELIGIBLE)
    _not_future(filed_on, today, "filing date")
    if checks.already_with_ombudsman or checks.in_court_or_other_forum:
        raise TransitionError(
            "blocked_clause_10",
            "RB-IOS 2026 Clause 10(1)(h)-(k): a grievance already before the Ombudsman or a court or other forum "
            "cannot be filed again",
        )
    deadlines = facts.deadlines
    if deadlines is None:
        raise TransitionError("deadline_unknown", "the filing deadline could not be computed for this case")
    if filed_on < deadlines.eligible_on:
        raise TransitionError("too_early", f"escalation is possible from {deadlines.eligible_on.isoformat()}")
    if filed_on > deadlines.filing_deadline_on:
        raise TransitionError("deadline_passed", f"the filing deadline was {deadlines.filing_deadline_on.isoformat()}")
    return replace(facts, state=CaseState.ESCALATED, escalated_on=filed_on), [
        ("escalated", {"filed_on": filed_on.isoformat()})
    ]


def close(facts: CaseFacts, reason: str) -> tuple[CaseFacts, list[Event]]:
    if facts.state in FINAL:
        raise TransitionError("invalid_state", f"the case is already {facts.state.value}")
    return replace(facts, state=CaseState.CLOSED), [("closed", {"reason": reason})]


def tick(facts: CaseFacts, today: date) -> tuple[CaseFacts, list[Event]]:
    deadlines = facts.deadlines
    if facts.state not in OPEN_TIMELINE or deadlines is None:
        return facts, []
    if today > deadlines.filing_deadline_on:
        return replace(facts, state=CaseState.EXPIRED), [
            ("expired", {"filing_deadline_on": deadlines.filing_deadline_on.isoformat()})
        ]
    if facts.state is CaseState.AWAITING_REPLY and today >= deadlines.eligible_on:
        return replace(facts, state=CaseState.ESCALATION_ELIGIBLE), [
            ("escalation_eligible", {"eligible_on": deadlines.eligible_on.isoformat()})
        ]
    return facts, []


def days_left(facts: CaseFacts, today: date) -> int | None:
    if facts.deadlines is None or facts.state not in OPEN_TIMELINE:
        return None
    return (facts.deadlines.filing_deadline_on - today).days
