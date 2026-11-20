import pytest
from hypothesis import given
from hypothesis import strategies as st

from vapas.security.redact import find_sensitive, redact, sketch


@pytest.mark.parametrize(
    "secret",
    [
        "ravi.kumar@example.in",
        "ravik@okicici",
        "9876543210",
        "+91 9876543210",
        "ABCDE1234F",
        "HDFC0001234",
        "4321 5678 9012 3456",
        "412345678901",
        "XXXXXXXX1234",
    ],
)
def test_each_kind_of_identifier_is_redacted(secret: str) -> None:
    text = f"UPI/DR/{secret}/payment"
    cleaned = redact(text)
    assert secret not in cleaned
    assert find_sensitive(cleaned) == []


@pytest.mark.parametrize("keep", ["1,23,456.78", "500.00", "01/04/2025", "2025-04-01", "12345678.00"])
def test_amounts_and_dates_survive(keep: str) -> None:
    assert keep in redact(f"x {keep} y")


@given(digits=st.integers(min_value=10**9, max_value=10**17))
def test_any_long_number_is_redacted(digits: int) -> None:
    assert str(digits) not in redact(f"REF {digits} END")


def test_sketch_keeps_structure_and_masks_names() -> None:
    lines = [
        "Mystery Bank",
        "Account Holder: RAVI KUMAR",
        "When What Out In Left",
        "01 Apr 2025 UPI/DR/412345678901/RAVI KUMAR 250.00 750.00 Cr",
        "02/04/2025 NEFT PRIYA SHARMA 1,000.00 1,750.00",
        "Page 1",
    ]
    result = sketch(lines, lambda line: line[:1].isdigit())
    assert result[0] == "When What Out In Left"
    assert result[1].startswith("01 Apr 2025 xxx/xx/[xxxxxx]/xxxx xxxxx 250.00 750.00 Cr")
    assert result[2] == "02/04/2025 xxxx xxxxx xxxxxx 1,000.00 1,750.00"
    assert all("RAVI" not in line and "PRIYA" not in line for line in result)
    assert len(result) == 3
