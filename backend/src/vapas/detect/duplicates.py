from collections import defaultdict
from collections.abc import Collection, Sequence

from rapidfuzz import fuzz

from vapas.classify.channel_rules import Channel, Kind
from vapas.detect.confidence import rupees
from vapas.detect.matching import counterparty
from vapas.detect.model import Confidence, Detector, Finding, Level, Txn, TxnKey

SIMILARITY = 90
MAX_GAP_DAYS = 1


def _same_payment(a: Txn, b: Txn) -> bool:
    if a.channel is not b.channel or abs((b.txn_date - a.txn_date).days) > MAX_GAP_DAYS:
        return False
    if a.references and a.references & b.references:
        return True
    return fuzz.token_set_ratio(counterparty(a.narration), counterparty(b.narration)) >= SIMILARITY


def find_duplicates(transactions: Sequence[Txn], reversed_debits: Collection[TxnKey]) -> list[Finding]:
    groups: dict[tuple[int, Channel], list[Txn]] = defaultdict(list)
    for txn in transactions:
        if txn.is_debit and txn.kind in (Kind.PAYMENT, Kind.CHARGE) and txn.key not in reversed_debits:
            groups[(txn.amount_paise, txn.channel)].append(txn)
    findings: list[Finding] = []
    for group in groups.values():
        ordered = sorted(group, key=lambda t: (t.txn_date, t.statement_id, t.row_index))
        flagged: set[TxnKey] = set()
        for index, later in enumerate(ordered):
            original = next((e for e in ordered[:index] if e.key not in flagged and _same_payment(e, later)), None)
            if original is None:
                continue
            flagged.add(later.key)
            charge = later.kind is Kind.CHARGE
            findings.append(
                Finding(
                    detector=Detector.DUPLICATE_CHARGE if charge else Detector.DUPLICATE,
                    level=Level.WORTH_CHECKING,
                    confidence=Confidence.LOW,
                    rule_id=None,
                    finding_policy="worth_checking",
                    letter_scope="reversal_only",
                    debit=later.key,
                    reversals=(),
                    t_date=later.txn_date,
                    r_date=None,
                    delay_days=None,
                    amount_owed_paise=None,
                    already_paid_paise=0,
                    why=(
                        f"{'A bank charge' if charge else 'A payment'} of {rupees(later.amount_paise)} on "
                        f"{later.txn_date.isoformat()} looks the same as one on {original.txn_date.isoformat()}. "
                        "If you were charged twice for one thing, ask the bank to reverse the extra debit."
                    ),
                    facts={"original_txn": f"{original.key.id}:{original.key.txn_date.isoformat()}"},
                )
            )
    return findings
