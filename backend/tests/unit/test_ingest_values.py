from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from vapas.ingest.layouts import BANK_LAYOUTS, COMMON_DATE_FORMATS, GENERIC, is_complete, normalize_label
from vapas.ingest.model import Direction, ParsedRow
from vapas.ingest.reconcile import Order, reconcile
from vapas.ingest.values import InvalidAmountError, parse_amount, parse_date


@pytest.mark.parametrize(
    ("text", "paise"),
    [
        ("1,23,456.78", 12345678),
        ("123456.78", 12345678),
        ("1,234.5", 123450),
        ("500", 50000),
        ("INR 1,000.00", 100000),
        ("Rs. 99.99", 9999),
        ("₹ 10.00", 1000),
        ("1,18,949.79(Cr)", 11894979),
        ("1,18,949.79 Cr", 11894979),
        ("2,000.00 Dr", -200000),
        ("2,000.00DR", -200000),
        ("(150.00)", -15000),
        ("-75.25", -7525),
        ("0.00", 0),
    ],
)
def test_amounts(text: str, paise: int) -> None:
    assert parse_amount(text) == paise


@pytest.mark.parametrize("text", ["", " ", "-", "--"])
def test_blank_amounts(text: str) -> None:
    assert parse_amount(text) is None


@pytest.mark.parametrize("text", ["12.345", "abc", "1.2.3", "12,34.5x", "UPI/123"])
def test_invalid_amounts(text: str) -> None:
    with pytest.raises(InvalidAmountError):
        parse_amount(text)


@given(paise=st.integers(min_value=0, max_value=10**13))
def test_indian_grouping_round_trip(paise: int) -> None:
    rupees, fraction = divmod(paise, 100)
    digits = str(rupees)
    head, tail = digits[:-3], digits[-3:]
    groups = [head[max(0, i - 2) : i] for i in range(len(head), 0, -2)][::-1]
    text = ",".join([*groups, tail]) if head else tail
    assert parse_amount(f"{text}.{fraction:02d}") == paise


@pytest.mark.parametrize(
    "text", ["01/04/2025", "01/04/25", "01-04-2025", "1 Apr 2025", "01-Apr-2025", "01-Apr-25", "2025-04-01"]
)
def test_dates(text: str) -> None:
    assert parse_date(text, COMMON_DATE_FORMATS) == date(2025, 4, 1)


@pytest.mark.parametrize("text", ["", "Opening Balance", "Page 1", "31/02/2025"])
def test_non_dates(text: str) -> None:
    assert parse_date(text, COMMON_DATE_FORMATS) is None


@pytest.mark.parametrize("layout", [*BANK_LAYOUTS, GENERIC], ids=lambda layout: layout.code)
def test_no_alias_means_two_fields(layout: object) -> None:
    from vapas.ingest.layouts import Layout

    assert isinstance(layout, Layout)
    seen: dict[str, object] = {}
    for name, aliases in layout.aliases.items():
        for alias in aliases:
            key = normalize_label(alias)
            assert seen.setdefault(key, name) == name, f"{alias} maps to {seen[key]} and {name}"
    assert is_complete(set(layout.aliases))


def test_generic_layout_knows_every_bank_alias() -> None:
    for layout in BANK_LAYOUTS:
        for name, aliases in layout.aliases.items():
            for alias in aliases:
                assert GENERIC.field_for(alias) == name


def row(index: int, direction: Direction, amount: int, balance: int | None) -> ParsedRow:
    return ParsedRow(index, date(2025, 4, 1 + index), None, "x", None, direction, amount, balance)


def test_reconcile_as_printed() -> None:
    rows = [row(0, Direction.CREDIT, 500, 1500), row(1, Direction.DEBIT, 200, 1300)]
    result = reconcile(rows, 1000)
    assert (result.reconciled, result.order, result.breaks, result.checked_rows) == (True, Order.AS_PRINTED, (), 2)


def test_reconcile_without_opening_infers_it_from_the_first_row() -> None:
    assert reconcile([row(0, Direction.DEBIT, 200, 800), row(1, Direction.DEBIT, 300, 500)], None).reconciled


def test_reconcile_newest_first() -> None:
    oldest_first = [
        row(0, Direction.CREDIT, 500, 1500),
        row(1, Direction.DEBIT, 200, 1300),
        row(2, Direction.DEBIT, 100, 1200),
    ]
    newest_first = [row(i, r.direction, r.amount_paise, r.balance_paise) for i, r in enumerate(reversed(oldest_first))]
    result = reconcile(newest_first, None)
    assert result.reconciled
    assert result.order is Order.REVERSED


def test_reconcile_reports_the_breaking_row() -> None:
    rows = [row(0, Direction.CREDIT, 500, 1500), row(1, Direction.DEBIT, 200, 1299), row(2, Direction.DEBIT, 100, 1199)]
    result = reconcile(rows, 1000)
    assert not result.reconciled
    assert result.breaks == (1,)


def test_rows_without_any_balance_are_not_reconciled() -> None:
    assert not reconcile([row(0, Direction.CREDIT, 500, None)], 1000).reconciled
    assert not reconcile([], 1000).reconciled
