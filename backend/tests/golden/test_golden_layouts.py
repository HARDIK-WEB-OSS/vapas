import json
from datetime import date
from pathlib import Path

import pytest

from vapas.ingest.layouts import BANK_LAYOUTS
from vapas.ingest.model import Direction, FileKind, ParsedRow
from vapas.ingest.parse import parse_document
from vapas.ingest.reconcile import reconcile
from vapas.synthetic.generator import STYLES, expected_rows, generate

GOLDEN = Path(__file__).parent / "synthetic"
GOLDEN_SEED = 2026
GOLDEN_ROWS = 60
BANKS = [bank.lower() for bank in STYLES]


def load_expected(bank: str) -> tuple[dict[str, object], tuple[ParsedRow, ...]]:
    truth = json.loads((GOLDEN / f"{bank}.expected.json").read_text(encoding="utf-8"))
    rows = tuple(
        ParsedRow(
            row_index=r["row_index"],
            txn_date=date.fromisoformat(r["txn_date"]),
            value_date=date.fromisoformat(r["value_date"]) if r["value_date"] else None,
            narration=r["narration"],
            ref_no=r["ref_no"],
            direction=Direction(r["direction"]),
            amount_paise=r["amount_paise"],
            balance_paise=r["balance_paise"],
        )
        for r in truth["rows"]
    )
    return truth, rows


@pytest.mark.parametrize("bank", BANKS)
@pytest.mark.parametrize("kind", list(FileKind))
def test_golden_fixture_parses_exactly(bank: str, kind: FileKind) -> None:
    truth, rows = load_expected(bank)
    parsed = parse_document((GOLDEN / f"{bank}.{kind.value}").read_bytes(), kind)
    assert parsed.bank_code == bank.upper()
    assert parsed.rows == rows
    assert parsed.rejected_rows == 0
    result = reconcile(parsed.rows, parsed.opening_balance_paise)
    assert result.reconciled
    assert result.breaks == ()
    if STYLES[bank.upper()].opening_row:
        assert parsed.opening_balance_paise == truth["opening_balance_paise"]


@pytest.mark.parametrize("bank", BANKS)
def test_generator_still_reproduces_the_golden_truth(bank: str) -> None:
    _, rows = load_expected(bank)
    assert expected_rows(generate(bank.upper(), GOLDEN_SEED, GOLDEN_ROWS)) == rows


def test_every_bank_layout_is_marked_unverified_until_checked_on_a_real_statement() -> None:
    assert [layout.code for layout in BANK_LAYOUTS if layout.verified_against_real_statement] == []
