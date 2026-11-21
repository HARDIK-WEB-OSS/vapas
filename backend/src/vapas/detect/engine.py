from collections.abc import Callable, Sequence
from datetime import date

from vapas.classify.channel_rules import Kind
from vapas.detect.duplicates import find_duplicates
from vapas.detect.late_reversal import Context, assess, months_before
from vapas.detect.mandates import find_mandate_findings
from vapas.detect.matching import counterparty, match_reversals
from vapas.detect.model import Finding, Txn, UserAnswers
from vapas.detect.unreversed import find_unreversed
from vapas.rules.loader import RuleBook


def dedupe_overlaps(transactions: Sequence[Txn]) -> list[Txn]:
    kept: list[Txn] = []
    seen: set[tuple[object, ...]] = set()
    for txn in sorted(transactions, key=lambda t: (t.statement_id, t.row_index)):
        if txn.balance_paise is None:
            kept.append(txn)
            continue
        identity = (txn.txn_date, txn.direction, txn.amount_paise, txn.balance_paise, counterparty(txn.narration))
        if identity in seen:
            continue
        seen.add(identity)
        kept.append(txn)
    return kept


def detect(
    transactions: Sequence[Txn],
    answers: UserAnswers,
    rulebook: RuleBook,
    as_of: date,
    lookback_months: int,
    group_key: Callable[[str], str],
) -> list[Finding]:
    unique = dedupe_overlaps(transactions)
    matches = match_reversals(unique)
    ctx = Context(
        rulebook=rulebook,
        as_of=as_of,
        lookback_start=months_before(as_of, lookback_months),
        answers=answers,
        compensation_credits=[t for t in unique if t.is_credit and t.kind is Kind.COMPENSATION],
    )
    matched = {m.debit.key for m in matches}
    findings = [f for m in matches if (f := assess(m, ctx)) is not None]
    findings += find_unreversed(unique, matched, ctx)
    findings += find_duplicates(unique, matched)
    findings += find_mandate_findings(unique, matches, ctx, group_key)
    return findings
