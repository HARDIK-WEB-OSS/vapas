import re
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

BLANKS = frozenset({"", "-", "--", "—"})
NOISE = re.compile(r"(?i)\binr\b|\brs\.?|₹|,|\s")
PLAIN_NUMBER = re.compile(r"\d+(\.\d{1,2})?")
CREDIT_SUFFIX = re.compile(r"(?i)\(?\s*cr\.?\s*\)?$")
DEBIT_SUFFIX = re.compile(r"(?i)\(?\s*dr\.?\s*\)?$")
SPACES = re.compile(r"\s+")


class InvalidAmountError(ValueError):
    pass


def parse_amount(text: str) -> int | None:
    value = text.strip()
    if value in BLANKS:
        return None
    negative = False
    if DEBIT_SUFFIX.search(value):
        negative = True
        value = DEBIT_SUFFIX.sub("", value)
    elif CREDIT_SUFFIX.search(value):
        value = CREDIT_SUFFIX.sub("", value)
    value = NOISE.sub("", value)
    if value.startswith("(") and value.endswith(")"):
        negative = True
        value = value[1:-1]
    if value.startswith("-"):
        negative = True
        value = value[1:]
    if value.startswith("+"):
        value = value[1:]
    if not PLAIN_NUMBER.fullmatch(value):
        raise InvalidAmountError(f"not an amount: {text!r}")
    try:
        paise = int((Decimal(value) * 100).to_integral_exact())
    except InvalidOperation as error:
        raise InvalidAmountError(f"not an amount: {text!r}") from error
    return -paise if negative else paise


def parse_date(text: str, formats: Sequence[str]) -> date | None:
    value = SPACES.sub(" ", text.strip())
    if not value or not value[0].isdigit():
        return None
    for date_format in formats:
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue
    return None
