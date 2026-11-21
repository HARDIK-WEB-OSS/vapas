from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

from vapas.detect.matching import Match
from vapas.detect.model import Txn

UNLINKED_WINDOW = timedelta(days=60)


@dataclass(frozen=True)
class Paid:
    tied_paise: int
    maybe_paid: bool


def already_paid(match: Match, compensation_credits: Sequence[Txn]) -> Paid:
    after = [c for c in compensation_credits if c.txn_date >= match.reversal_date]
    tied = [c for c in after if c.references & match.debit.references]
    unlinked = [c for c in after if c not in tied and c.txn_date - match.reversal_date <= UNLINKED_WINDOW]
    return Paid(tied_paise=sum(c.amount_paise for c in tied), maybe_paid=bool(unlinked))


def compensation_for(per_day_inr: int, delay_days: int) -> int:
    return per_day_inr * 100 * max(delay_days, 0)
