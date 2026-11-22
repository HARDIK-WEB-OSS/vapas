from dataclasses import dataclass, field
from datetime import date

from vapas.detect.model import Detector, Level
from vapas.ingest.model import Direction

D, C = Direction.DEBIT, Direction.CREDIT


@dataclass(frozen=True)
class Row:
    on: date
    direction: Direction
    amount_paise: int
    narration: str


@dataclass(frozen=True)
class Expected:
    detector: Detector
    level: Level
    amount_owed_paise: int | None


@dataclass(frozen=True)
class RegressionCase:
    case_id: str
    source: str
    pattern: str
    as_of: date
    rows: tuple[Row, ...]
    expected: tuple[Expected, ...] = ()
    forbidden_levels: frozenset[Level] = field(default_factory=lambda: frozenset({Level.CLAIM}))


CASES: tuple[RegressionCase, ...] = (
    RegressionCase(
        case_id="EXAMPLE-001",
        source="template example from product policy, not pilot feedback",
        pattern="merchant refund for a card purchase must never be treated as a late TAT reversal",
        as_of=date(2026, 11, 20),
        rows=(
            Row(date(2026, 8, 1), D, 249_900, "POS 4321XXXX1234 AMAZON PAY INDIA"),
            Row(date(2026, 8, 20), C, 249_900, "REFUND AMAZON PAY INDIA ORDER 4031"),
        ),
    ),
    RegressionCase(
        case_id="EXAMPLE-002",
        source="template example from product policy, not pilot feedback",
        pattern="a successful UPI transfer to a person with no reversal is not money owed",
        as_of=date(2026, 11, 20),
        rows=(Row(date(2026, 9, 3), D, 500_000, "UPI/DR/412345678901/RAMESH KUMAR/OKAXIS"),),
    ),
    RegressionCase(
        case_id="CONTROL-001",
        source="positive control proving the harness finds a real claim",
        pattern="ATM cash not dispensed, reversed 12 days later: claim under Annex 1(a)",
        as_of=date(2026, 11, 20),
        rows=(
            Row(date(2026, 8, 1), D, 200_000, "ATM WDL/412345678901/PUNE"),
            Row(date(2026, 8, 13), C, 200_000, "REV ATM WDL 412345678901 PUNE"),
        ),
        expected=(Expected(Detector.LATE_REVERSAL, Level.CLAIM, 70_000),),
        forbidden_levels=frozenset(),
    ),
)
