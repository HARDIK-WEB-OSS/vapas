from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class Field(StrEnum):
    DATE = "date"
    VALUE_DATE = "value_date"
    NARRATION = "narration"
    REF = "ref"
    DEBIT = "debit"
    CREDIT = "credit"
    AMOUNT = "amount"
    DIRECTION = "direction"
    BALANCE = "balance"


class Direction(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


class FileKind(StrEnum):
    PDF = "pdf"
    CSV = "csv"
    XLS = "xls"
    XLSX = "xlsx"


@dataclass(frozen=True)
class ParsedRow:
    row_index: int
    txn_date: date
    value_date: date | None
    narration: str
    ref_no: str | None
    direction: Direction
    amount_paise: int
    balance_paise: int | None

    @property
    def signed_paise(self) -> int:
        return self.amount_paise if self.direction is Direction.CREDIT else -self.amount_paise


@dataclass(frozen=True)
class ParsedStatement:
    bank_code: str
    layout_code: str
    parser_version: int
    rows: tuple[ParsedRow, ...]
    opening_balance_paise: int | None
    skipped_lines: int
    rejected_rows: int
    pages: int

    @property
    def period(self) -> tuple[date, date] | None:
        if not self.rows:
            return None
        dates = [row.txn_date for row in self.rows]
        return min(dates), max(dates)


class ParseError(Exception):
    code = "parse_failed"


class NeedsPasswordError(ParseError):
    code = "needs_password"


class WrongPasswordError(ParseError):
    code = "wrong_password"


class UnknownLayoutError(ParseError):
    code = "unknown_layout"

    def __init__(self, sketch: tuple[str, ...]) -> None:
        super().__init__("no known statement layout matched")
        self.sketch = sketch

    def __reduce__(self) -> tuple[type, tuple[tuple[str, ...]]]:
        return (UnknownLayoutError, (self.sketch,))
