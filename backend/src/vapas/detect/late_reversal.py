import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from vapas.classify.channel_rules import Channel
from vapas.classify.payee import PayeeType, classify_payee
from vapas.detect.compensation import already_paid, compensation_for
from vapas.detect.confidence import rupees
from vapas.detect.matching import Match
from vapas.detect.model import Confidence, Detector, Finding, Level, Question, Txn, TxnKey, UserAnswers
from vapas.rules.loader import RuleBook, TatRule

CLAIM_ROUTES: dict[Channel, str] = {
    Channel.ATM: "rbi.tat.atm_cash_not_dispensed",
    Channel.POS: "rbi.tat.card_pos",
    Channel.ECOM: "rbi.tat.card_cnp",
}
ASK_ROUTES: dict[Channel, tuple[str, str]] = {
    Channel.UPI: ("rbi.tat.upi_merchant", "rbi.tat.upi_p2p_not_credited"),
    Channel.AEPS: ("rbi.tat.aeps_merchant", "rbi.tat.aeps_not_credited"),
}
CREDIT_PUSH_ROUTES: dict[Channel, str] = {Channel.IMPS: "rbi.tat.imps_not_credited"}
CARD_CHANNELS = frozenset({Channel.POS, Channel.ECOM})
CARD_TO_CARD = re.compile(r"(?i)\b(CARD\s*TO\s*CARD|C2C|VISA\s*DIRECT|MONEY\s*SEND)\b")
CARD_TO_CARD_RULE = "rbi.tat.card_to_card"
INTERNATIONAL = re.compile(r"(?i)\b(INTL|INTERNATIONAL|FOREIGN|CROSS\s*BORDER|USD|EUR|GBP|AED|SGD)\b")
VALUE_DATE_TOLERANCE_DAYS = 1
AEPS_CASH_WITHDRAWAL = re.compile(r"(?i)\b(CASH\s+(WITHDRAWAL|WDL|WD)|CW)\b")
AEPS_CASH_WITHDRAWAL_RULE = "rbi.tat.atm_cash_not_dispensed"
CUSTOMER = "customer"


@dataclass(frozen=True)
class Context:
    rulebook: RuleBook
    as_of: date
    lookback_start: date
    answers: UserAnswers
    compensation_credits: Sequence[Txn]


@dataclass(frozen=True)
class Route:
    rule_id: str
    question: Question | None
    merchant_source: str | None = None


def merchant_note(chosen: Route) -> str:
    if chosen.merchant_source is None:
        return ""
    if chosen.merchant_source == CUSTOMER:
        return " The customer confirmed that this payment was made to a merchant."
    signal = chosen.merchant_source.removeprefix("statement:")
    return f" This was classified as a payment to a merchant from the statement description ({signal})."


def route(debit: Txn, answers: UserAnswers) -> Route | None:
    if debit.channel is Channel.AEPS and AEPS_CASH_WITHDRAWAL.search(debit.narration):
        return Route(AEPS_CASH_WITHDRAWAL_RULE, None)
    if debit.channel in CARD_CHANNELS and CARD_TO_CARD.search(debit.narration):
        return Route(CARD_TO_CARD_RULE, None)
    if debit.channel in CLAIM_ROUTES:
        return Route(CLAIM_ROUTES[debit.channel], None)
    if debit.channel in ASK_ROUTES:
        merchant_rule, transfer_rule = ASK_ROUTES[debit.channel]
        answer = answers.payee_was_merchant.get(debit.key)
        if answer is not None:
            return Route(merchant_rule if answer else transfer_rule, None, CUSTOMER if answer else None)
        auto = classify_payee(debit.narration, debit.channel)
        if auto.payee is PayeeType.MERCHANT:
            return Route(merchant_rule, None, f"statement:{auto.signal}")
        if auto.payee is PayeeType.PERSON:
            return Route(transfer_rule, None)
        return Route(merchant_rule, Question.PAYEE_WAS_MERCHANT)
    if debit.channel in CREDIT_PUSH_ROUTES:
        return Route(CREDIT_PUSH_ROUTES[debit.channel], None)
    return None


def transaction_day(debit: Txn) -> tuple[date, bool]:
    value = debit.value_date or debit.txn_date
    ambiguous = abs((value - debit.txn_date).days) > VALUE_DATE_TOLERANCE_DAYS
    return max(debit.txn_date, value), ambiguous


def months_before(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 - months
    year, month = divmod(index, 12)
    month += 1
    last_day = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(day.day, last_day))


def citation(rulebook: RuleBook, rule: TatRule) -> str:
    return f"{rule.clause} of RBI circular {rulebook.instrument_ref} (rule {rule.id})"


def blocked_reason(debit: Txn, day: date, ambiguous: bool, ctx: Context) -> str | None:
    if ambiguous:
        return "The value date and transaction date differ by more than one day, so the start date T is unclear."
    window = ctx.rulebook.override_window(day)
    if window is not None:
        return f"This date falls inside a temporary RBI relaxation ({window.id}) where working days may apply."
    return None


def assess(match: Match, ctx: Context) -> Finding | None:
    debit = match.debit
    if INTERNATIONAL.search(debit.narration):
        return None
    chosen = route(debit, ctx.answers)
    if chosen is None:
        return None
    day, ambiguous = transaction_day(debit)
    rule = ctx.rulebook.rule(chosen.rule_id, day)
    reversal_keys = tuple(r.key for r in match.reversals)
    if rule is None or rule.deadline_days is None:
        return _finding(
            Detector.LATE_REVERSAL,
            Level.NEEDS_REVIEW,
            Confidence.LOW,
            None,
            debit.key,
            reversal_keys,
            day,
            match.reversal_date,
            None,
            None,
            0,
            f"No verified rule is in force for {day.isoformat()}.",
        )
    if match.ambiguous:
        return _finding(
            Detector.LATE_REVERSAL,
            Level.NEEDS_REVIEW,
            Confidence.LOW,
            rule,
            debit.key,
            reversal_keys,
            day,
            match.reversal_date,
            None,
            None,
            0,
            f"A reversal of {rupees(debit.amount_paise)} arrived on {match.reversal_date.isoformat()}, but several "
            "payments of the same amount could belong to it and it carries no reference number to tell them apart.",
        )
    if not match.is_full:
        return _finding(
            Detector.PARTIAL_REVERSAL,
            Level.WORTH_CHECKING,
            Confidence.MEDIUM,
            rule,
            debit.key,
            reversal_keys,
            day,
            match.reversal_date,
            None,
            None,
            0,
            f"Only {rupees(match.reversed_paise)} of {rupees(debit.amount_paise)} came back. "
            "Ask the bank for the rest; a partial reversal is not counted as a late-reversal claim.",
            letter_scope="reversal_only",
        )
    due = day + timedelta(days=rule.deadline_days)
    received = match.reversal_date
    delay = (received - due).days
    if delay <= 0:
        return None
    timing = (
        f"{citation(ctx.rulebook, rule)}: the reversal was due by {due.isoformat()} (T + {rule.deadline_days} days, "
        f"T = {day.isoformat()}) and was credited on {received.isoformat()}, {delay} days late."
    )
    if rule.finding_policy == "worth_checking":
        return _finding(
            Detector.LATE_REVERSAL,
            Level.INFORMATIONAL,
            Confidence.MEDIUM,
            rule,
            debit.key,
            reversal_keys,
            day,
            received,
            delay,
            None,
            0,
            timing + " For transfers to another person the circular pays the compensation to the receiver "
            "(Annex General Instruction 1(a)), so nothing is owed to you.",
        )
    potential = compensation_for(rule.per_day_inr or 0, delay)
    pending_question = chosen.question is not None
    conditional = (
        " Compensation would apply only if this was a payment to a shop or business." if pending_question else ""
    )
    held_facts: dict[str, object] = {} if pending_question else {"potential_paise": potential}
    blocked = blocked_reason(debit, day, ambiguous, ctx)
    if blocked is not None:
        return _finding(
            Detector.LATE_REVERSAL,
            Level.NEEDS_REVIEW,
            Confidence.LOW,
            rule,
            debit.key,
            reversal_keys,
            day,
            received,
            delay,
            None,
            0,
            timing + " " + blocked + conditional,
            facts=held_facts,
        )
    if day < ctx.lookback_start:
        return _finding(
            Detector.LATE_REVERSAL,
            Level.HISTORICAL,
            Confidence.MEDIUM,
            rule,
            debit.key,
            reversal_keys,
            day,
            received,
            delay,
            None,
            0,
            timing
            + " This is older than the claim window VAPAS uses, so it is shown for information only."
            + conditional,
            facts=held_facts,
        )
    if chosen.question is not None:
        return _finding(
            Detector.LATE_REVERSAL,
            Level.NEEDS_USER_INPUT,
            Confidence.MEDIUM,
            rule,
            debit.key,
            reversal_keys,
            day,
            received,
            delay,
            None,
            0,
            timing + " Was this a payment to a shop or business? If yes, compensation applies; "
            "if it was a transfer to a person, it does not.",
            question=chosen.question,
            facts={"potential_paise": potential},
        )
    paid = already_paid(match, ctx.compensation_credits)
    owed = max(0, potential - paid.tied_paise)
    confidence = Confidence.HIGH if _shares_reference(match) else Confidence.MEDIUM
    why = timing + f" Compensation: ₹{rule.per_day_inr} x {delay} days = {rupees(potential)}."
    if paid.tied_paise:
        why += f" {rupees(paid.tied_paise)} already credited as compensation is subtracted."
    if paid.maybe_paid:
        confidence = Confidence.LOW
        why += (
            " A compensation credit appeared after the reversal that could not be linked to this payment;"
            " it may already be paid."
        )
    if owed == 0:
        return _finding(
            Detector.LATE_REVERSAL,
            Level.INFORMATIONAL,
            confidence,
            rule,
            debit.key,
            reversal_keys,
            day,
            received,
            delay,
            0,
            paid.tied_paise,
            why + " Nothing is left to claim.",
        )
    facts = {"merchant_source": chosen.merchant_source} if chosen.merchant_source else {}
    why += merchant_note(chosen)
    return _finding(
        Detector.LATE_REVERSAL,
        Level.CLAIM,
        confidence,
        rule,
        debit.key,
        reversal_keys,
        day,
        received,
        delay,
        owed,
        paid.tied_paise,
        why,
        facts=facts,
    )


def _shares_reference(match: Match) -> bool:
    return all(match.debit.references & r.references for r in match.reversals)


def _finding(
    detector: Detector,
    level: Level,
    confidence: Confidence,
    rule: TatRule | None,
    debit: TxnKey,
    reversals: tuple[TxnKey, ...],
    t_date: date | None,
    r_date: date | None,
    delay: int | None,
    owed: int | None,
    paid: int,
    why: str,
    question: Question | None = None,
    letter_scope: str | None = None,
    facts: Mapping[str, object] | None = None,
) -> Finding:
    return Finding(
        detector=detector,
        level=level,
        confidence=confidence,
        rule_id=rule.id if rule else None,
        finding_policy=rule.finding_policy if rule else None,
        letter_scope=letter_scope or (rule.letter_scope if rule else None),
        debit=debit,
        reversals=reversals,
        t_date=t_date,
        r_date=r_date,
        delay_days=delay,
        amount_owed_paise=owed,
        already_paid_paise=paid,
        why=why,
        question=question,
        facts=dict(facts or {}),
    )
