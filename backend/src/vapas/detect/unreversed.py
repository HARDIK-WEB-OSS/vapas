import re
from collections.abc import Collection, Sequence
from datetime import timedelta

from vapas.detect.compensation import compensation_for
from vapas.detect.confidence import rupees
from vapas.detect.late_reversal import (
    INTERNATIONAL,
    Context,
    blocked_reason,
    citation,
    merchant_note,
    route,
    transaction_day,
)
from vapas.detect.matching import is_matchable_debit
from vapas.detect.model import Confidence, Detector, Finding, Level, Question, Txn, TxnKey

DEFAULT_FAILURE_WORDS = ("FAILED", "FAIL", "DECLINED", "TIMEOUT", "TIMED OUT", "NOT DISPENSED", "PENDING")
FAILURE_WORDS: dict[str, tuple[str, ...]] = {
    "SBI": DEFAULT_FAILURE_WORDS,
    "HDFC": DEFAULT_FAILURE_WORDS,
    "ICICI": DEFAULT_FAILURE_WORDS,
    "AXIS": DEFAULT_FAILURE_WORDS,
    "KOTAK": DEFAULT_FAILURE_WORDS,
}
FAILURE_WORDS_VERIFIED_AGAINST_REAL_STATEMENTS: frozenset[str] = frozenset()


def _pattern(words: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(r"(?i)\b(" + "|".join(w.replace(" ", r"\s+") for w in words) + r")\b")


PATTERNS = {bank: _pattern(words) for bank, words in FAILURE_WORDS.items()}
DEFAULT_PATTERN = _pattern(DEFAULT_FAILURE_WORDS)


def looks_failed(txn: Txn) -> bool:
    pattern = PATTERNS.get(txn.bank_code, DEFAULT_PATTERN)
    return is_matchable_debit(txn) and bool(pattern.search(txn.narration))


def _worth_checking(debit: Txn, why: str, question: Question | None, rule_id: str | None) -> Finding:
    return Finding(
        detector=Detector.UNREVERSED_FAILED,
        level=Level.WORTH_CHECKING if question is None else Level.NEEDS_USER_INPUT,
        confidence=Confidence.LOW,
        rule_id=rule_id,
        finding_policy="worth_checking",
        letter_scope="reversal_only",
        debit=debit.key,
        reversals=(),
        t_date=debit.txn_date,
        r_date=None,
        delay_days=None,
        amount_owed_paise=None,
        already_paid_paise=0,
        why=why,
        question=question,
    )


def assess_unreversed(debit: Txn, ctx: Context) -> Finding | None:
    if INTERNATIONAL.search(debit.narration):
        return None
    failed = ctx.answers.payment_failed.get(debit.key)
    if failed is False:
        return None
    chosen = route(debit, ctx.answers)
    lead = f"{rupees(debit.amount_paise)} left your account on {debit.txn_date.isoformat()} and no reversal was found."
    if failed is None:
        return _worth_checking(
            debit,
            lead + " The description suggests it may have failed. Did the payment fail?",
            Question.PAYMENT_FAILED,
            chosen.rule_id if chosen else None,
        )
    if chosen is None:
        return _worth_checking(debit, lead + " Ask your bank to reverse it.", None, None)
    day, ambiguous = transaction_day(debit)
    rule = ctx.rulebook.rule(chosen.rule_id, day)
    if rule is None or rule.deadline_days is None or rule.finding_policy != "late_reversal_claim":
        return _worth_checking(debit, lead + " Ask your bank to reverse it.", None, rule.id if rule else None)
    if chosen.question is not None:
        return _worth_checking(
            debit, lead + " Was this a payment to a shop or business?", chosen.question, chosen.rule_id
        )
    due = day + timedelta(days=rule.deadline_days)
    delay = (ctx.as_of - due).days
    why = (
        f"{citation(ctx.rulebook, rule)}: you confirmed the payment failed. The reversal was due by "
        f"{due.isoformat()} and has not arrived as of {ctx.as_of.isoformat()}."
    )
    blocked = blocked_reason(debit, day, ambiguous, ctx)
    level = Level.CLAIM
    if blocked is not None:
        level, why = Level.NEEDS_REVIEW, why + " " + blocked
    elif day < ctx.lookback_start:
        level, why = Level.HISTORICAL, why + " This is older than the claim window, so it is for information only."
    if delay <= 0:
        return _worth_checking(
            debit, lead + f" The bank still has until {due.isoformat()} to reverse it.", None, rule.id
        )
    amount = compensation_for(rule.per_day_inr or 0, delay)
    why += merchant_note(chosen)
    return Finding(
        detector=Detector.UNREVERSED_FAILED,
        level=level,
        confidence=Confidence.MEDIUM,
        rule_id=rule.id,
        finding_policy=rule.finding_policy,
        letter_scope=rule.letter_scope,
        debit=debit.key,
        reversals=(),
        t_date=day,
        r_date=None,
        delay_days=delay,
        amount_owed_paise=amount if level is Level.CLAIM else None,
        already_paid_paise=0,
        why=why + f" Compensation so far: ₹{rule.per_day_inr} x {delay} days = {rupees(amount)}, growing each day.",
        accruing=True,
        facts={"potential_paise": amount, "merchant_source": chosen.merchant_source or ""},
    )


def find_unreversed(transactions: Sequence[Txn], matched: Collection[TxnKey], ctx: Context) -> list[Finding]:
    candidates = [t for t in transactions if looks_failed(t) and t.key not in matched]
    return [f for t in candidates if (f := assess_unreversed(t, ctx)) is not None]
