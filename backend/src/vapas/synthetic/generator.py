from __future__ import annotations

import csv
import io
import random
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from vapas.ingest.layouts import AXIS, HDFC, ICICI, KOTAK, SBI, Layout
from vapas.ingest.model import Direction, Field, ParsedRow

if TYPE_CHECKING:
    from fpdf import FPDF

FIXED_CREATION = datetime(2026, 1, 1, 0, 0, 0)
NAMES = ("RAVI KUMAR", "PRIYA SHARMA", "ANIL MEHTA", "SUNITA DEVI", "ARJUN NAIR", "FATIMA KHAN")
MERCHANTS = ("AMAZON PAY", "SWIGGY", "BIGBASKET", "IRCTC", "JIO RECHARGE", "APOLLO PHARMACY")
POINTS_PER_CHAR = 5.0


@dataclass(frozen=True)
class Column:
    name: Field | None
    label: str
    width: float
    numeric: bool = False


@dataclass(frozen=True)
class Style:
    layout: Layout
    bank_title: str
    columns: tuple[Column, ...]
    date_format: str
    indian_grouping: bool
    balance_suffix: bool
    opening_row: bool


def _cols(*spec: tuple[Field | None, str, float]) -> tuple[Column, ...]:
    numeric = {Field.DEBIT, Field.CREDIT, Field.BALANCE}
    return tuple(Column(name, label, width, name in numeric) for name, label, width in spec)


STYLES: dict[str, Style] = {
    "SBI": Style(
        SBI,
        "State Bank of India",
        _cols(
            (Field.DATE, "Txn Date", 58),
            (Field.VALUE_DATE, "Value Date", 58),
            (Field.NARRATION, "Description", 150),
            (Field.REF, "Ref No./Cheque No.", 85),
            (Field.DEBIT, "Debit", 60),
            (Field.CREDIT, "Credit", 60),
            (Field.BALANCE, "Balance", 70),
        ),
        "%d %b %Y",
        True,
        False,
        True,
    ),
    "HDFC": Style(
        HDFC,
        "HDFC BANK Ltd.",
        _cols(
            (Field.DATE, "Date", 45),
            (Field.NARRATION, "Narration", 150),
            (Field.REF, "Chq./Ref.No.", 80),
            (Field.VALUE_DATE, "Value Dt", 45),
            (Field.DEBIT, "Withdrawal Amt.", 70),
            (Field.CREDIT, "Deposit Amt.", 70),
            (Field.BALANCE, "Closing Balance", 75),
        ),
        "%d/%m/%y",
        True,
        False,
        False,
    ),
    "ICICI": Style(
        ICICI,
        "ICICI Bank Limited",
        _cols(
            (None, "S No.", 22),
            (Field.VALUE_DATE, "Value Date", 45),
            (Field.DATE, "Transaction Date", 60),
            (Field.REF, "Cheque Number", 58),
            (Field.NARRATION, "Transaction Remarks", 102),
            (Field.DEBIT, "Withdrawal Amount (INR )", 90),
            (Field.CREDIT, "Deposit Amount (INR )", 80),
            (Field.BALANCE, "Balance (INR )", 70),
        ),
        "%d/%m/%Y",
        True,
        False,
        False,
    ),
    "AXIS": Style(
        AXIS,
        "Axis Bank Ltd",
        _cols(
            (Field.DATE, "Tran Date", 55),
            (Field.REF, "CHQNO", 50),
            (Field.NARRATION, "PARTICULARS", 170),
            (Field.DEBIT, "DR", 60),
            (Field.CREDIT, "CR", 60),
            (Field.BALANCE, "BAL", 70),
            (None, "SOL", 30),
        ),
        "%d-%m-%Y",
        False,
        False,
        True,
    ),
    "KOTAK": Style(
        KOTAK,
        "Kotak Mahindra Bank",
        _cols(
            (Field.DATE, "Date", 55),
            (Field.NARRATION, "Narration", 170),
            (Field.REF, "Chq/Ref No", 75),
            (Field.DEBIT, "Withdrawal (Dr)", 65),
            (Field.CREDIT, "Deposit (Cr)", 65),
            (Field.BALANCE, "Balance", 80),
        ),
        "%d-%m-%Y",
        True,
        True,
        False,
    ),
}


@dataclass(frozen=True)
class SyntheticStatement:
    bank: str
    opening_balance_paise: int
    rows: tuple[ParsedRow, ...]
    wrapped: tuple[tuple[str, ...], ...]


def _narration(rng: random.Random, direction: Direction, reversal: bool) -> str:
    name = rng.choice(NAMES)
    utr = rng.randrange(10**11, 10**12)
    handle = name.split()[0].lower() + "@ok" + rng.choice(("sbi", "hdfc", "axis"))
    if reversal:
        return f"REV UPI/{utr}/{rng.choice(MERCHANTS)}/FAILED TXN REVERSAL"
    if direction is Direction.CREDIT:
        return rng.choice(
            (f"UPI/CR/{utr}/{name}/{handle}/Payment", f"NEFT CR-HDFC0001234-{name}-SALARY", f"IMPS/P2A/{utr}/{name}")
        )
    return rng.choice(
        (
            f"UPI/DR/{utr}/{name}/{handle}/Payment",
            f"POS 4321XXXXXXXX{rng.randrange(1000, 9999)} {rng.choice(MERCHANTS)}",
            f"ATM WDL/{rng.randrange(100000, 999999)}/MUMBAI",
            f"ACH D- {rng.choice(MERCHANTS)} MANDATE",
        )
    )


def wrap_chars(bank: str) -> int:
    narration = next(c for c in STYLES[bank].columns if c.name is Field.NARRATION)
    return max(12, int((narration.width - 8) / POINTS_PER_CHAR))


def _wrap(text: str, width: int) -> tuple[str, ...]:
    return tuple(text[i : i + width] for i in range(0, len(text), width))


def generate(bank: str, seed: int, count: int = 40, start: date = date(2025, 4, 1)) -> SyntheticStatement:
    rng = random.Random(f"{bank}-{seed}")
    balance = rng.randrange(5_000_00, 2_00_000_00)
    opening = balance
    rows: list[ParsedRow] = []
    wrapped: list[tuple[str, ...]] = []
    day = start
    for index in range(count):
        day += timedelta(days=rng.choice((0, 0, 1, 1, 2, 3)))
        reversal = bool(rows) and rng.random() < 0.08
        direction = Direction.CREDIT if reversal or rng.random() < 0.35 else Direction.DEBIT
        amount = rows[-1].amount_paise if reversal else rng.choice((rng.randrange(1_00, 5_000_00), 1_00_000_00))
        if direction is Direction.DEBIT and amount > balance:
            direction = Direction.CREDIT
        balance += amount if direction is Direction.CREDIT else -amount
        lines = _wrap(_narration(rng, direction, reversal), wrap_chars(bank))
        ref = f"{rng.randrange(10**9, 10**10)}" if rng.random() < 0.6 else None
        value_date = day + timedelta(days=rng.choice((0, 0, 0, 1)))
        rows.append(
            ParsedRow(index, day, value_date, " ".join(" ".join(lines).split()), ref, direction, amount, balance)
        )
        wrapped.append(lines)
    return SyntheticStatement(bank, opening, tuple(rows), tuple(wrapped))


def expected_rows(statement: SyntheticStatement) -> tuple[ParsedRow, ...]:
    style = STYLES[statement.bank]
    names = {c.name for c in style.columns}
    return tuple(
        replace(
            row,
            value_date=row.value_date if Field.VALUE_DATE in names else None,
            ref_no=row.ref_no if Field.REF in names else None,
        )
        for row in statement.rows
    )


def _money(paise: int, indian: bool) -> str:
    rupees, fraction = divmod(abs(paise), 100)
    digits = str(rupees)
    if indian and len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = [head[max(0, i - 2) : i] for i in range(len(head), 0, -2)][::-1]
        digits = ",".join([*groups, tail])
    elif not indian:
        digits = f"{rupees:,}"
    return f"{'-' if paise < 0 else ''}{digits}.{fraction:02d}"


def _row_cells(style: Style, row: ParsedRow, serial: int) -> list[str]:
    cells: dict[Field | None, str] = {
        Field.DATE: row.txn_date.strftime(style.date_format),
        Field.VALUE_DATE: row.value_date.strftime(style.date_format) if row.value_date else "",
        Field.REF: row.ref_no or "",
        Field.DEBIT: _money(row.amount_paise, style.indian_grouping) if row.direction is Direction.DEBIT else "",
        Field.CREDIT: _money(row.amount_paise, style.indian_grouping) if row.direction is Direction.CREDIT else "",
        Field.BALANCE: _balance(style, row.balance_paise or 0),
    }
    return [cells.get(c.name, str(serial) if c.label == "S No." else "") for c in style.columns]


def _balance(style: Style, paise: int) -> str:
    text = _money(paise, style.indian_grouping)
    return f"{text}(Cr)" if style.balance_suffix else text


def table_rows(statement: SyntheticStatement, newest_first: bool = False) -> list[list[str]]:
    style = STYLES[statement.bank]
    out: list[list[str]] = []
    if style.opening_row:
        cells = ["" for _ in style.columns]
        for i, column in enumerate(style.columns):
            if column.name is Field.NARRATION:
                cells[i] = "Opening Balance"
            if column.name is Field.BALANCE:
                cells[i] = _balance(style, statement.opening_balance_paise)
        out.append(cells)
    entries = list(zip(statement.rows, statement.wrapped, strict=True))
    if newest_first:
        entries.reverse()
    for serial, (row, lines) in enumerate(entries, 1):
        first = _row_cells(style, row, serial)
        narration_at = next(i for i, c in enumerate(style.columns) if c.name is Field.NARRATION)
        first[narration_at] = lines[0]
        out.append(first)
        for extra in lines[1:]:
            continuation = ["" for _ in style.columns]
            continuation[narration_at] = extra
            out.append(continuation)
    return out


def preamble(statement: SyntheticStatement) -> list[str]:
    style = STYLES[statement.bank]
    return [
        style.bank_title,
        "Statement of Account",
        "Account Holder: SYNTHETIC TEST USER",
        "Account Number: XXXXXXXX1234",
    ]


def render_csv(statement: SyntheticStatement, newest_first: bool = False) -> bytes:
    style = STYLES[statement.bank]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for line in preamble(statement):
        writer.writerow([line])
    writer.writerow([c.label for c in style.columns])
    joined = _joined_rows(statement, newest_first)
    writer.writerows(joined)
    return buffer.getvalue().encode("utf-8")


def _joined_rows(statement: SyntheticStatement, newest_first: bool) -> list[list[str]]:
    style = STYLES[statement.bank]
    narration_at = next(i for i, c in enumerate(style.columns) if c.name is Field.NARRATION)
    rows: list[list[str]] = []
    for cells in table_rows(statement, newest_first):
        if rows and not any(cells[i] for i in range(len(cells)) if i != narration_at):
            rows[-1][narration_at] += " " + cells[narration_at]
        else:
            rows.append(list(cells))
    return rows


def render_xlsx(statement: SyntheticStatement) -> bytes:
    from openpyxl import Workbook

    style = STYLES[statement.bank]
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    for line in preamble(statement):
        sheet.append([line])
    sheet.append([c.label for c in style.columns])
    for cells in _joined_rows(statement, newest_first=False):
        sheet.append(cells)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def render_xls(statement: SyntheticStatement) -> bytes:
    import xlwt

    style = STYLES[statement.bank]
    book = xlwt.Workbook()
    sheet = book.add_sheet("Statement")
    rows = [[line] for line in preamble(statement)]
    rows.append([c.label for c in style.columns])
    rows.extend(_joined_rows(statement, newest_first=False))
    for r, cells in enumerate(rows):
        for c, value in enumerate(cells):
            sheet.write(r, c, value)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


ROWS_PER_PAGE = 38
LINE_HEIGHT = 12.0
LEFT = 30.0


def render_pdf(statement: SyntheticStatement, password: str | None = None, newest_first: bool = False) -> bytes:
    from fpdf import FPDF

    style = STYLES[statement.bank]
    pdf = FPDF(unit="pt", format="A4")
    pdf.set_creation_date(FIXED_CREATION)
    pdf.set_font("Helvetica", size=7)
    if password:
        pdf.set_encryption(owner_password=password + "-owner", user_password=password)
    lines = table_rows(statement, newest_first)
    for start in range(0, len(lines), ROWS_PER_PAGE):
        pdf.add_page()
        y = 40.0
        if start == 0:
            for text in preamble(statement):
                pdf.text(LEFT, y, text)
                y += LINE_HEIGHT
            y += LINE_HEIGHT
        _pdf_line(pdf, style, [c.label for c in style.columns], y, header=True)
        y += LINE_HEIGHT * 1.5
        for cells in lines[start : start + ROWS_PER_PAGE]:
            _pdf_line(pdf, style, cells, y, header=False)
            y += LINE_HEIGHT
        pdf.text(LEFT, 810, f"Page {start // ROWS_PER_PAGE + 1}")
    return bytes(pdf.output())


def _pdf_line(pdf: FPDF, style: Style, cells: Sequence[str], y: float, header: bool) -> None:
    x = LEFT
    for column, text in zip(style.columns, cells, strict=True):
        if text:
            width = pdf.get_string_width(text)
            if header and width > column.width - 4:
                raise ValueError(f"header label {text!r} is wider than its column")
            right_align = column.numeric and not header
            pdf.text(x + column.width - width - 4 if right_align else x, y, text)
        x += column.width
