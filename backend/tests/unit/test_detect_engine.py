import itertools
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vapas.classify.channel_rules import Channel, Kind
from vapas.detect.engine import detect
from vapas.detect.model import Confidence, Detector, Finding, Level, Question, Txn, TxnKey, UserAnswers
from vapas.ingest.model import Direction
from vapas.rules.loader import default_rules_dir, load_rulebook

AS_OF = date(2026, 11, 20)
RULES = load_rulebook()
_ids = itertools.count(1)
D, C = Direction.DEBIT, Direction.CREDIT


def txn(
    day: date,
    direction: Direction,
    amount: int,
    channel: Channel,
    kind: Kind,
    narration: str = "PAYMENT",
    refs: tuple[bytes, ...] = (),
    value_date: date | None = None,
    balance: int | None = None,
    statement: str = "s1",
) -> Txn:
    number = next(_ids)
    return Txn(
        key=TxnKey(number, day),
        statement_id=statement,
        row_index=number,
        txn_date=day,
        value_date=value_date,
        direction=direction,
        amount_paise=amount,
        balance_paise=balance,
        channel=channel,
        kind=kind,
        narration=narration,
        references=frozenset(refs),
    )


def run(txns: list[Txn], answers: UserAnswers | None = None) -> list[Finding]:
    return detect(txns, answers or UserAnswers(), RULES, AS_OF, 12, lambda name: f"g:{name}")


def only(findings: list[Finding], detector: Detector = Detector.LATE_REVERSAL) -> Finding:
    matching = [f for f in findings if f.detector is detector]
    assert len(matching) == 1, findings
    return matching[0]


def pair(
    channel: Channel,
    debit_day: date,
    credit_day: date,
    amount: int = 200_000,
    ref: bytes = b"r1",
    narration: str = "ATM WDL PUNE",
) -> tuple[Txn, Txn]:
    debit = txn(debit_day, D, amount, channel, Kind.PAYMENT, narration, (ref,))
    credit = txn(credit_day, C, amount, channel, Kind.REVERSAL, "REV " + narration, (ref,))
    return debit, credit


def test_atm_reversal_six_days_late_is_a_claim_of_600() -> None:
    debit, credit = pair(Channel.ATM, date(2026, 3, 1), date(2026, 3, 12))
    finding = only(run([debit, credit]))
    assert (finding.level, finding.rule_id) == (Level.CLAIM, "rbi.tat.atm_cash_not_dispensed")
    assert (finding.t_date, finding.r_date, finding.delay_days) == (date(2026, 3, 1), date(2026, 3, 12), 6)
    assert finding.amount_owed_paise == 60_000
    assert finding.confidence is Confidence.HIGH
    assert "Annex Sl. 1(a)" in finding.why
    assert "T + 5 days" in finding.why


@pytest.mark.parametrize("days_after", [0, 3, 5])
def test_reversal_on_or_before_the_deadline_is_not_a_finding(days_after: int) -> None:
    debit, credit = pair(Channel.ATM, date(2026, 3, 1), date(2026, 3, 1) + timedelta(days=days_after))
    assert run([debit, credit]) == []


@pytest.mark.parametrize(
    ("channel", "rule_id"), [(Channel.POS, "rbi.tat.card_pos"), (Channel.ECOM, "rbi.tat.card_cnp")]
)
def test_card_claims(channel: Channel, rule_id: str) -> None:
    debit, credit = pair(channel, date(2026, 5, 10), date(2026, 5, 17), narration="POS AMAZON")
    finding = only(run([debit, credit]))
    assert (finding.level, finding.rule_id, finding.delay_days, finding.amount_owed_paise) == (
        Level.CLAIM,
        rule_id,
        2,
        20_000,
    )


def test_upi_without_answer_asks_whether_the_payee_was_a_merchant() -> None:
    debit, credit = pair(Channel.UPI, date(2026, 6, 1), date(2026, 6, 10), narration="UPI/DR/SWIGGY")
    finding = only(run([debit, credit]))
    assert (finding.level, finding.question, finding.amount_owed_paise) == (
        Level.NEEDS_USER_INPUT,
        Question.PAYEE_WAS_MERCHANT,
        None,
    )
    assert finding.facts["potential_paise"] == 40_000


def test_upi_merchant_answer_turns_it_into_a_4b_claim() -> None:
    debit, credit = pair(Channel.UPI, date(2026, 6, 1), date(2026, 6, 10), narration="UPI/DR/SWIGGY")
    answers = UserAnswers(payee_was_merchant={debit.key: True})
    finding = only(run([debit, credit], answers))
    assert (finding.level, finding.rule_id, finding.amount_owed_paise) == (Level.CLAIM, "rbi.tat.upi_merchant", 40_000)


def test_upi_transfer_answer_is_informational_without_amount() -> None:
    debit, credit = pair(Channel.UPI, date(2026, 6, 1), date(2026, 6, 10), narration="UPI/DR/RAVI")
    finding = only(run([debit, credit], UserAnswers(payee_was_merchant={debit.key: False})))
    assert (finding.level, finding.rule_id, finding.amount_owed_paise) == (
        Level.INFORMATIONAL,
        "rbi.tat.upi_p2p_not_credited",
        None,
    )
    assert "General Instruction 1(a)" in finding.why


def test_imps_late_reversal_never_carries_an_amount() -> None:
    debit, credit = pair(Channel.IMPS, date(2026, 6, 1), date(2026, 6, 20), narration="IMPS/P2A/RAVI")
    finding = only(run([debit, credit]))
    assert finding.level is Level.INFORMATIONAL
    assert finding.amount_owed_paise is None


def test_merchant_refund_is_never_matched_as_a_reversal() -> None:
    debit = txn(date(2026, 6, 1), D, 99_900, Channel.UPI, Kind.PAYMENT, "UPI/DR/AMAZON", (b"o1",))
    refund = txn(date(2026, 6, 25), C, 99_900, Channel.UPI, Kind.MERCHANT_REFUND, "UPI/REFUND/AMAZON", (b"o1",))
    assert [f for f in run([debit, refund]) if f.detector is Detector.LATE_REVERSAL] == []


def test_partial_reversal_is_worth_checking_without_amount() -> None:
    debit = txn(date(2026, 7, 1), D, 100_000, Channel.ATM, Kind.PAYMENT, "ATM WDL", (b"p",))
    part = txn(date(2026, 7, 15), C, 40_000, Channel.ATM, Kind.REVERSAL, "ATM REV", (b"p",))
    finding = only(run([debit, part]), Detector.PARTIAL_REVERSAL)
    assert (finding.level, finding.letter_scope, finding.amount_owed_paise) == (
        Level.WORTH_CHECKING,
        "reversal_only",
        None,
    )


def test_split_reversal_that_adds_up_uses_the_last_part_date() -> None:
    debit = txn(date(2026, 7, 1), D, 100_000, Channel.ATM, Kind.PAYMENT, "ATM WDL", (b"s",))
    first = txn(date(2026, 7, 4), C, 60_000, Channel.ATM, Kind.REVERSAL, "ATM REV", (b"s",))
    second = txn(date(2026, 7, 9), C, 40_000, Channel.ATM, Kind.REVERSAL, "ATM REV", (b"s",))
    finding = only(run([debit, first, second]))
    assert (finding.r_date, finding.delay_days, finding.amount_owed_paise) == (date(2026, 7, 9), 3, 30_000)
    assert len(finding.reversals) == 2


def test_value_date_far_from_transaction_date_needs_review() -> None:
    debit = txn(date(2026, 3, 1), D, 50_000, Channel.ATM, Kind.PAYMENT, "ATM WDL", (b"v",), value_date=date(2026, 3, 4))
    credit = txn(date(2026, 3, 20), C, 50_000, Channel.ATM, Kind.REVERSAL, "ATM REV", (b"v",))
    finding = only(run([debit, credit]))
    assert (finding.level, finding.amount_owed_paise) == (Level.NEEDS_REVIEW, None)
    assert finding.t_date == date(2026, 3, 4)


def test_one_day_value_date_shift_moves_t_but_is_allowed() -> None:
    debit = txn(date(2026, 3, 1), D, 50_000, Channel.ATM, Kind.PAYMENT, "ATM WDL", (b"w",), value_date=date(2026, 3, 2))
    credit = txn(date(2026, 3, 12), C, 50_000, Channel.ATM, Kind.REVERSAL, "ATM REV", (b"w",))
    finding = only(run([debit, credit]))
    assert (finding.level, finding.t_date, finding.delay_days) == (Level.CLAIM, date(2026, 3, 2), 5)


@pytest.mark.parametrize("day", [date(2020, 6, 1), date(2021, 6, 1)])
def test_relaxation_windows_need_review(day: date) -> None:
    debit, credit = pair(Channel.ATM, day, day + timedelta(days=15))
    finding = only(run([debit, credit]))
    assert finding.level is Level.NEEDS_REVIEW
    assert "relaxation" in finding.why


def test_older_than_lookback_is_historical_without_amount() -> None:
    debit, credit = pair(Channel.ATM, date(2025, 8, 1), date(2025, 8, 20))
    finding = only(run([debit, credit]))
    assert (finding.level, finding.amount_owed_paise) == (Level.HISTORICAL, None)


def test_compensation_already_credited_is_subtracted() -> None:
    debit, credit = pair(Channel.ATM, date(2026, 3, 1), date(2026, 3, 12))
    paid = txn(date(2026, 3, 20), C, 30_000, Channel.UNCLASSIFIED, Kind.COMPENSATION, "TAT COMP", (b"r1",))
    finding = only(run([debit, credit, paid]))
    assert (finding.amount_owed_paise, finding.already_paid_paise) == (30_000, 30_000)


def test_compensation_fully_paid_leaves_nothing_to_claim() -> None:
    debit, credit = pair(Channel.ATM, date(2026, 3, 1), date(2026, 3, 12))
    paid = txn(date(2026, 3, 20), C, 60_000, Channel.UNCLASSIFIED, Kind.COMPENSATION, "TAT COMP", (b"r1",))
    finding = only(run([debit, credit, paid]))
    assert (finding.level, finding.amount_owed_paise) == (Level.INFORMATIONAL, 0)


def test_unlinked_compensation_lowers_confidence() -> None:
    debit, credit = pair(Channel.ATM, date(2026, 3, 1), date(2026, 3, 12))
    other = txn(date(2026, 3, 25), C, 10_000, Channel.UNCLASSIFIED, Kind.COMPENSATION, "COMPENSATION")
    finding = only(run([debit, credit, other]))
    assert (finding.level, finding.confidence) == (Level.CLAIM, Confidence.LOW)
    assert "may already be paid" in finding.why


def test_international_transactions_are_out_of_scope() -> None:
    debit, credit = pair(Channel.ECOM, date(2026, 3, 1), date(2026, 3, 30), narration="ECOM INTL USD NETFLIX")
    assert [f for f in run([debit, credit]) if f.detector is Detector.LATE_REVERSAL] == []


def test_failed_looking_debit_without_reversal_asks_and_then_claims() -> None:
    debit = txn(date(2026, 10, 1), D, 150_000, Channel.ATM, Kind.PAYMENT, "ATM WDL FAILED NOT DISPENSED", (b"f",))
    asked = only(run([debit]), Detector.UNREVERSED_FAILED)
    assert (asked.level, asked.question, asked.amount_owed_paise) == (
        Level.NEEDS_USER_INPUT,
        Question.PAYMENT_FAILED,
        None,
    )
    claim = only(run([debit], UserAnswers(payment_failed={debit.key: True})), Detector.UNREVERSED_FAILED)
    expected_delay = (AS_OF - date(2026, 10, 6)).days
    assert (claim.level, claim.delay_days, claim.amount_owed_paise, claim.accruing) == (
        Level.CLAIM,
        expected_delay,
        expected_delay * 10_000,
        True,
    )
    assert run([debit], UserAnswers(payment_failed={debit.key: False})) == []


def test_ordinary_debits_are_not_flagged_as_unreversed() -> None:
    assert run([txn(date(2026, 10, 1), D, 150_000, Channel.ATM, Kind.PAYMENT, "ATM WDL PUNE")]) == []


def test_same_day_identical_payments_are_worth_checking() -> None:
    first = txn(date(2026, 9, 3), D, 45_000, Channel.POS, Kind.PAYMENT, "POS 4321XXXX1234 BIGBASKET")
    second = txn(date(2026, 9, 3), D, 45_000, Channel.POS, Kind.PAYMENT, "POS 4321XXXX1234 BIGBASKET")
    finding = only(run([first, second]), Detector.DUPLICATE)
    assert (finding.level, finding.debit, finding.amount_owed_paise) == (Level.WORTH_CHECKING, second.key, None)


def test_duplicate_that_was_reversed_is_not_flagged() -> None:
    first = txn(date(2026, 9, 3), D, 45_000, Channel.POS, Kind.PAYMENT, "POS BIGBASKET", (b"d1",))
    second = txn(date(2026, 9, 3), D, 45_000, Channel.POS, Kind.PAYMENT, "POS BIGBASKET", (b"d2",))
    back = txn(date(2026, 9, 5), C, 45_000, Channel.POS, Kind.REVERSAL, "POS REV BIGBASKET", (b"d2",))
    assert [f for f in run([first, second, back]) if f.detector is Detector.DUPLICATE] == []


def test_duplicate_charges() -> None:
    charges = [txn(date(2026, 9, 30), D, 1_770, Channel.CHARGES, Kind.CHARGE, "SMS ALERT CHGS QTR") for _ in range(2)]
    assert only(run(charges), Detector.DUPLICATE_CHARGE).level is Level.WORTH_CHECKING


def test_monthly_emis_are_not_duplicates() -> None:
    emis = [
        txn(date(2026, month, 5), D, 1_200_000, Channel.NACH, Kind.PAYMENT, "NACH DR TATA CAPITAL")
        for month in (6, 7, 8)
    ]
    assert [f for f in run(emis) if f.detector is Detector.DUPLICATE] == []


def test_nach_needs_revocation_date_and_proof_before_claiming() -> None:
    debits = [
        txn(date(2026, month, 5), D, 59_900, Channel.NACH, Kind.PAYMENT, "ACH D- GYM MEMBERSHIP MANDATE")
        for month in (3, 4, 5)
    ]
    asked = only(run(debits), Detector.NACH_AFTER_REVOCATION)
    assert (asked.level, asked.question, asked.group_key) == (
        Level.NEEDS_USER_INPUT,
        Question.MANDATE_REVOKED,
        asked.group_key,
    )
    group = asked.group_key
    assert group is not None
    no_proof = UserAnswers(mandate_revoked_on={group: date(2026, 3, 20)}, mandate_proof={group: False})
    assert only(run(debits, no_proof), Detector.NACH_AFTER_REVOCATION).level is Level.NEEDS_USER_INPUT
    proven = UserAnswers(mandate_revoked_on={group: date(2026, 3, 20)}, mandate_proof={group: True})
    claims = [f for f in run(debits, proven) if f.detector is Detector.NACH_AFTER_REVOCATION]
    assert [f.t_date for f in claims] == [date(2026, 4, 5), date(2026, 5, 5)]
    assert all(f.level is Level.CLAIM and f.accruing for f in claims)
    assert claims[0].delay_days == (AS_OF - date(2026, 4, 6)).days
    assert "provided by the customer" in claims[0].why


def test_one_reversal_is_never_used_twice() -> None:
    first = txn(date(2026, 4, 1), D, 50_000, Channel.ATM, Kind.PAYMENT, "ATM WDL PUNE", (b"x1",))
    second = txn(date(2026, 4, 1), D, 50_000, Channel.ATM, Kind.PAYMENT, "ATM WDL PUNE", (b"x2",))
    back = txn(date(2026, 4, 15), C, 50_000, Channel.ATM, Kind.REVERSAL, "ATM REV PUNE", (b"x1",))
    late = [f for f in run([first, second, back]) if f.detector is Detector.LATE_REVERSAL]
    assert [f.debit for f in late] == [first.key]


def test_overlapping_statements_do_not_double_count() -> None:
    debit, credit = pair(Channel.ATM, date(2026, 3, 1), date(2026, 3, 12))
    debit = Txn(**{**debit.__dict__, "balance_paise": 1_000_000})
    copy = Txn(**{**debit.__dict__, "key": TxnKey(999_999, debit.txn_date), "statement_id": "s2"})
    assert len([f for f in run([debit, copy, credit]) if f.level is Level.CLAIM]) == 1


def test_finding_keys_are_stable() -> None:
    debit, credit = pair(Channel.ATM, date(2026, 3, 1), date(2026, 3, 12))
    a, b = only(run([debit, credit])), only(run([debit, credit]))
    assert a.key(b"r", b"p") == b.key(b"r", b"p")
    assert a.key(b"r", b"p") != a.key(b"r2", b"p")


CREDIT_PUSH = st.sampled_from([(Channel.IMPS, None), (Channel.UPI, False), (Channel.AEPS, False)])


@settings(max_examples=150, deadline=None)
@given(
    route=CREDIT_PUSH,
    start=st.dates(min_value=date(2019, 10, 15), max_value=date(2026, 11, 1)),
    gap=st.integers(min_value=0, max_value=119),
    amount=st.integers(min_value=100, max_value=10_000_000),
    failed=st.booleans(),
)
def test_credit_push_transfers_never_produce_an_amount(
    route: tuple[Channel, bool | None], start: date, gap: int, amount: int, failed: bool
) -> None:
    channel, merchant = route
    debit = txn(start, D, amount, channel, Kind.PAYMENT, f"{channel.value.upper()} TRANSFER FAILED", (b"cp",))
    credit = txn(start + timedelta(days=gap), C, amount, channel, Kind.REVERSAL, "REV TRANSFER", (b"cp",))
    answers = UserAnswers(
        payee_was_merchant={debit.key: merchant} if merchant is not None else {},
        payment_failed={debit.key: failed},
    )
    for scenario in ([debit, credit], [debit]):
        for finding in run(scenario, answers):
            if finding.detector in (Detector.LATE_REVERSAL, Detector.UNREVERSED_FAILED, Detector.PARTIAL_REVERSAL):
                assert not finding.amount_owed_paise, finding


def test_reference_less_reversal_with_several_candidate_debits_needs_review() -> None:
    older = txn(date(2026, 2, 1), D, 100_000, Channel.ATM, Kind.PAYMENT, "ATM WDL PUNE")
    newer = txn(date(2026, 2, 20), D, 100_000, Channel.ATM, Kind.PAYMENT, "ATM WDL PUNE")
    back = txn(date(2026, 3, 5), C, 100_000, Channel.ATM, Kind.REVERSAL, "REV ATM WDL PUNE")
    finding = only(run([older, newer, back]))
    assert (finding.level, finding.amount_owed_paise) == (Level.NEEDS_REVIEW, None)
    assert "several payments" in finding.why


def test_reference_less_reversal_with_a_single_candidate_is_still_a_claim() -> None:
    debit = txn(date(2026, 2, 20), D, 100_000, Channel.ATM, Kind.PAYMENT, "ATM WDL PUNE")
    back = txn(date(2026, 3, 5), C, 100_000, Channel.ATM, Kind.REVERSAL, "REV ATM WDL PUNE")
    finding = only(run([debit, back]))
    assert (finding.level, finding.confidence, finding.delay_days) == (Level.CLAIM, Confidence.MEDIUM, 8)


def test_aeps_cash_withdrawal_at_an_agent_is_a_1a_claim_without_a_question() -> None:
    debit, credit = pair(
        Channel.AEPS, date(2026, 5, 1), date(2026, 5, 9), narration="AEPS/412345678901/CASH WITHDRAWAL"
    )
    finding = only(run([debit, credit]))
    assert (finding.level, finding.rule_id, finding.question, finding.amount_owed_paise) == (
        Level.CLAIM,
        "rbi.tat.atm_cash_not_dispensed",
        None,
        30_000,
    )


def test_aeps_aadhaar_pay_is_a_5a_claim_from_the_statement() -> None:
    debit, credit = pair(Channel.AEPS, date(2026, 5, 1), date(2026, 5, 9), narration="AEPS/412345678901/AADHAAR PAY")
    finding = only(run([debit, credit]))
    assert (finding.level, finding.rule_id, finding.question) == (Level.CLAIM, "rbi.tat.aeps_merchant", None)


def test_aeps_without_a_clear_signal_still_asks() -> None:
    debit, credit = pair(Channel.AEPS, date(2026, 5, 1), date(2026, 5, 9), narration="AEPS/412345678901/AGENT 42")
    assert only(run([debit, credit])).question is Question.PAYEE_WAS_MERCHANT


def test_customer_confirmed_merchant_is_stated_on_the_claim() -> None:
    debit, credit = pair(Channel.UPI, date(2026, 6, 1), date(2026, 6, 10), narration="UPI/DR/SWIGGY")
    finding = only(run([debit, credit], UserAnswers(payee_was_merchant={debit.key: True})))
    assert "customer confirmed" in finding.why
    assert finding.facts["merchant_source"] == "customer"
    plain = only(run(list(pair(Channel.ATM, date(2026, 6, 1), date(2026, 6, 10)))))
    assert "customer confirmed" not in plain.why


@pytest.mark.parametrize("bank", ["SBI", "HDFC", "ICICI", "AXIS", "KOTAK", "UNKNOWN"])
def test_failure_words_apply_for_every_bank(bank: str) -> None:
    debit = txn(date(2026, 10, 1), D, 150_000, Channel.ATM, Kind.PAYMENT, "ATM WDL DECLINED", (b"f",))
    debit = Txn(**{**debit.__dict__, "bank_code": bank})
    assert only(run([debit]), Detector.UNREVERSED_FAILED).question is Question.PAYMENT_FAILED


def test_failure_word_lists_are_not_yet_verified_on_real_statements() -> None:
    from vapas.detect.unreversed import FAILURE_WORDS_VERIFIED_AGAINST_REAL_STATEMENTS

    assert frozenset() == FAILURE_WORDS_VERIFIED_AGAINST_REAL_STATEMENTS


def test_clear_merchant_signal_claims_without_asking() -> None:
    debit, credit = pair(Channel.UPI, date(2026, 6, 1), date(2026, 6, 10), narration="UPI/P2M/SWIGGY")
    finding = only(run([debit, credit]))
    assert (finding.level, finding.rule_id, finding.question, finding.amount_owed_paise) == (
        Level.CLAIM,
        "rbi.tat.upi_merchant",
        None,
        40_000,
    )
    assert finding.facts["merchant_source"] == "statement:p2m_marker"
    assert "classified as a payment to a merchant from the statement description" in finding.why
    assert "customer confirmed" not in finding.why


def test_clear_person_signal_is_informational_without_asking() -> None:
    debit, credit = pair(Channel.UPI, date(2026, 6, 1), date(2026, 6, 10), narration="UPI/P2P/RAVI KUMAR")
    finding = only(run([debit, credit]))
    assert (finding.level, finding.question, finding.amount_owed_paise) == (Level.INFORMATIONAL, None, None)


def test_customer_answer_overrides_the_statement_signal() -> None:
    debit, credit = pair(Channel.UPI, date(2026, 6, 1), date(2026, 6, 10), narration="UPI/P2M/SWIGGY")
    finding = only(run([debit, credit], UserAnswers(payee_was_merchant={debit.key: False})))
    assert (finding.level, finding.amount_owed_paise) == (Level.INFORMATIONAL, None)


def test_source_location_changes_do_not_change_the_rules_hash(tmp_path: Path) -> None:
    moved = tmp_path / "moved"
    shutil.copytree(default_rules_dir(), moved)
    target = moved / "rbi" / "integrated_ombudsman_2026.yaml"
    target.write_text(
        target.read_text(encoding="utf-8").replace("fetched_on: 2026-11-19", "fetched_on: 2026-11-20", 1),
        encoding="utf-8",
    )
    assert load_rulebook(moved).rules_sha256 == RULES.rules_sha256

    reworded = tmp_path / "reworded"
    shutil.copytree(default_rules_dir(), reworded)
    tat = reworded / "rbi" / "tat_failed_transactions.yaml"
    tat.write_text(
        tat.read_text(encoding="utf-8").replace("to the credit of the account holder", "to the account holder", 1),
        encoding="utf-8",
    )
    assert load_rulebook(reworded).rules_sha256 != RULES.rules_sha256
