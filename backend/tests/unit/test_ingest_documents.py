import csv
import io

import pytest

from vapas.ingest.model import FileKind, NeedsPasswordError, UnknownLayoutError, WrongPasswordError
from vapas.ingest.parse import parse_document
from vapas.ingest.reconcile import Order, reconcile
from vapas.security.redact import find_sensitive
from vapas.synthetic.generator import expected_rows, generate, render_csv, render_pdf


def test_password_protected_pdf_needs_the_right_password() -> None:
    statement = generate("HDFC", 7, count=20)
    data = render_pdf(statement, password="SYNTH1234")
    with pytest.raises(NeedsPasswordError):
        parse_document(data, FileKind.PDF)
    with pytest.raises(WrongPasswordError):
        parse_document(data, FileKind.PDF, password="wrong")
    assert parse_document(data, FileKind.PDF, password="SYNTH1234").rows == expected_rows(statement)


@pytest.mark.parametrize("bank", ["KOTAK", "AXIS"])
def test_newest_first_statements_reconcile_in_reverse(bank: str) -> None:
    statement = generate(bank, 3, count=30)
    for kind, data in (
        (FileKind.PDF, render_pdf(statement, newest_first=True)),
        (FileKind.CSV, render_csv(statement, newest_first=True)),
    ):
        parsed = parse_document(data, kind)
        assert len(parsed.rows) == 30
        result = reconcile(parsed.rows, None)
        assert result.reconciled, kind
        assert result.order is Order.REVERSED


def test_single_amount_column_with_dr_cr_marker_uses_the_generic_layout() -> None:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Some Small Bank"])
    writer.writerow(["Post Date", "Details", "Amount", "Dr/Cr", "Running Balance"])
    writer.writerow(["01/04/2025", "Opening Balance", "", "", "1,000.00"])
    writer.writerow(["02/04/2025", "UPI/DR/123456789012/SHOP", "250.00", "DR", "750.00"])
    writer.writerow(["03/04/2025", "NEFT CR SALARY", "1,000.00", "CR", "1,750.00"])
    parsed = parse_document(buffer.getvalue().encode(), FileKind.CSV)
    assert parsed.layout_code == "generic_v1"
    assert [(r.direction.value, r.amount_paise) for r in parsed.rows] == [("debit", 25000), ("credit", 100000)]
    assert parsed.opening_balance_paise == 100000
    assert reconcile(parsed.rows, parsed.opening_balance_paise).reconciled


def test_row_with_both_debit_and_credit_is_rejected_not_guessed() -> None:
    data = (
        b"Txn Date,Value Date,Description,Ref No./Cheque No.,Debit,Credit,Balance\n"
        b"01/04/2025,01/04/2025,ODD ROW,,10.00,20.00,110.00\n"
        b"02/04/2025,02/04/2025,NORMAL,,10.00,,100.00\n"
    )
    parsed = parse_document(data, FileKind.CSV)
    assert parsed.rejected_rows == 1
    assert len(parsed.rows) == 1


def test_unknown_layout_returns_a_sketch_without_personal_data() -> None:
    data = (
        b"Mystery Bank\n"
        b"Customer: RAVI KUMAR, ravi.kumar@example.in, +91 9876543210, PAN ABCDE1234F\n"
        b"When,What,Out,In,Left\n"
        b"01/04/2025,UPI/DR/412345678901/RAVI KUMAR/ravik@okicici,250.00,,750.00\n"
        b"02/04/2025,NEFT CR HDFC0001234 PRIYA SHARMA A/C 123456789012,,1000.00,1750.00\n"
    )
    with pytest.raises(UnknownLayoutError) as caught:
        parse_document(data, FileKind.CSV)
    sketch = "\n".join(caught.value.sketch)
    assert "When What Out In Left" in sketch
    assert find_sensitive(sketch) == []
    for secret in ("RAVI", "KUMAR", "PRIYA", "ravi", "9876543210", "ABCDE1234F", "412345678901", "HDFC0001234"):
        assert secret not in sketch


def test_unreadable_spreadsheet_is_a_parse_error() -> None:
    from vapas.ingest.model import ParseError

    with pytest.raises(ParseError):
        parse_document(b"PK\x03\x04not really a zip", FileKind.XLSX)
