from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from vapas.ingest.model import ParsedRow


class Order(StrEnum):
    AS_PRINTED = "as_printed"
    REVERSED = "reversed"


@dataclass(frozen=True)
class Reconciliation:
    reconciled: bool
    order: Order
    breaks: tuple[int, ...]
    checked_rows: int


def _walk(rows: Sequence[ParsedRow], opening: int | None) -> tuple[tuple[int, ...], int]:
    if not rows:
        return (), 0
    first = rows[0]
    if opening is not None:
        running = opening
    elif first.balance_paise is not None:
        running = first.balance_paise - first.signed_paise
    else:
        return tuple(r.row_index for r in rows), 0
    breaks: list[int] = []
    checked = 0
    for row in rows:
        running += row.signed_paise
        if row.balance_paise is None:
            continue
        checked += 1
        if running != row.balance_paise:
            breaks.append(row.row_index)
            running = row.balance_paise
    return tuple(breaks), checked


def reconcile(rows: Sequence[ParsedRow], opening_balance_paise: int | None) -> Reconciliation:
    breaks, checked = _walk(rows, opening_balance_paise)
    if breaks:
        reversed_breaks, reversed_checked = _walk(list(reversed(rows)), opening_balance_paise)
        if len(reversed_breaks) < len(breaks):
            return Reconciliation(
                not reversed_breaks and reversed_checked > 0, Order.REVERSED, reversed_breaks, reversed_checked
            )
    return Reconciliation(not breaks and checked > 0, Order.AS_PRINTED, breaks, checked)
