from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import timedelta

from vapas.classify.channel_rules import Channel
from vapas.detect.compensation import compensation_for
from vapas.detect.confidence import rupees
from vapas.detect.late_reversal import Context, blocked_reason, citation
from vapas.detect.matching import Match, counterparty, is_matchable_debit
from vapas.detect.model import Confidence, Detector, Finding, Level, Question, Txn

NACH_RULE = "rbi.tat.nach_debit_after_revocation"


def _ask(group: str, debits: Sequence[Txn]) -> Finding:
    latest = max(debits, key=lambda t: t.txn_date)
    return Finding(
        detector=Detector.NACH_AFTER_REVOCATION,
        level=Level.NEEDS_USER_INPUT,
        confidence=Confidence.LOW,
        rule_id=NACH_RULE,
        finding_policy="needs_user_input",
        letter_scope="claim",
        debit=latest.key,
        reversals=(),
        t_date=latest.txn_date,
        r_date=None,
        delay_days=None,
        amount_owed_paise=None,
        already_paid_paise=0,
        why=(
            f"{len(debits)} automatic debit(s) of {rupees(latest.amount_paise)} through a mandate. Did you cancel this "
            "mandate with your bank before any of these debits? If yes, enter the cancellation date and confirm you "
            "have proof of it."
        ),
        question=Question.MANDATE_REVOKED,
        group_key=group,
    )


def _claim(debit: Txn, match: Match | None, group: str, ctx: Context) -> Finding | None:
    rule = ctx.rulebook.rule(NACH_RULE, debit.txn_date)
    if rule is None or rule.deadline_days is None:
        return None
    due = debit.txn_date + timedelta(days=rule.deadline_days)
    received = match.reversal_date if match and match.is_full else None
    delay = ((received or ctx.as_of) - due).days
    if delay <= 0:
        return None
    amount = compensation_for(rule.per_day_inr or 0, delay)
    why = (
        f"{citation(ctx.rulebook, rule)}: this debit on {debit.txn_date.isoformat()} came after the mandate "
        f"cancellation date you entered. It had to be resolved by {due.isoformat()}; "
        + (
            f"it was reversed on {received.isoformat()}, {delay} days late."
            if received
            else f"no reversal has arrived as of {ctx.as_of.isoformat()} ({delay} days)."
        )
        + f" Compensation: ₹{rule.per_day_inr} x {delay} days = {rupees(amount)}. {rule.letter_disclosure or ''}"
    )
    level = Level.CLAIM
    blocked = blocked_reason(debit, debit.txn_date, False, ctx)
    if blocked is not None:
        level, why = Level.NEEDS_REVIEW, why + " " + blocked
    elif debit.txn_date < ctx.lookback_start:
        level, why = Level.HISTORICAL, why + " This is older than the claim window, so it is for information only."
    return Finding(
        detector=Detector.NACH_AFTER_REVOCATION,
        level=level,
        confidence=Confidence.MEDIUM,
        rule_id=rule.id,
        finding_policy=rule.finding_policy,
        letter_scope=rule.letter_scope,
        debit=debit.key,
        reversals=tuple(r.key for r in match.reversals) if match and received else (),
        t_date=debit.txn_date,
        r_date=received,
        delay_days=delay,
        amount_owed_paise=amount if level is Level.CLAIM else None,
        already_paid_paise=0,
        why=why.strip(),
        group_key=group,
        accruing=received is None,
        facts={"potential_paise": amount},
    )


def find_mandate_findings(
    transactions: Sequence[Txn], matches: Sequence[Match], ctx: Context, group_key: Callable[[str], str]
) -> list[Finding]:
    groups: dict[str, list[Txn]] = defaultdict(list)
    for txn in transactions:
        if txn.channel is Channel.NACH and is_matchable_debit(txn):
            groups[group_key(counterparty(txn.narration))].append(txn)
    by_debit = {m.debit.key: m for m in matches}
    findings: list[Finding] = []
    for group, debits in groups.items():
        revoked = ctx.answers.mandate_revoked_on.get(group)
        if revoked is None or not ctx.answers.mandate_proof.get(group, False):
            findings.append(_ask(group, debits))
            continue
        for debit in debits:
            if debit.txn_date > revoked:
                claim = _claim(debit, by_debit.get(debit.key), group, ctx)
                if claim is not None:
                    findings.append(claim)
    return findings
