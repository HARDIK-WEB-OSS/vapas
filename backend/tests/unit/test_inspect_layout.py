import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "inspect_layout.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("inspect_layout", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script() -> ModuleType:
    return load_script()


@pytest.mark.parametrize(
    "line",
    [
        "Date Narration Ref No. Value Dt Withdrawal Amt. Deposit Amt. Closing Balance",
        "Txn Date Value Date Description Ref No. Debit Credit Balance",
        "Tran Date Particulars Debit Credit Balance",
    ],
)
def test_header_lines_are_recognised(script: ModuleType, line: str) -> None:
    assert script.is_header(line)


@pytest.mark.parametrize(
    "line",
    [
        "01/04/2026 UPI/123456789012/SHOP 500.00 10,000.00",
        "Debit Credit 1,200.00",
        "Statement of account for the period",
    ],
)
def test_rows_and_prose_are_not_headers(script: ModuleType, line: str) -> None:
    assert not script.is_header(line)


def test_only_known_header_words_are_printed(script: ModuleType) -> None:
    header = "Date Narration Debit Credit Balance RAVI 50100123456789 ravi@bank"
    masked = " ".join(script.mask_word(word) for word in header.split())
    assert masked == "Date Narration Debit Credit Balance ? ? ?"


def test_shape_hides_digits_and_letters(script: ModuleType) -> None:
    assert script.shape("01-Apr-26") == "99-AAA-99"


def test_refuses_a_file_inside_the_repository(script: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["inspect_layout.py", str(SCRIPT)])
    with pytest.raises(ValueError, match="outside the repository"):
        script.main()
