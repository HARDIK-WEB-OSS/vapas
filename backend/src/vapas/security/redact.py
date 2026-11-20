import re
from collections.abc import Callable, Sequence

MAX_SKETCH_ROWS = 8
KEEP_WORDS = re.compile(
    r"(?i)^(\d{1,2}[-/ ]?)?(cr|dr|cr\.|dr\.|jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)([-/ ]?\d{2,4})?$"
)
LETTER = re.compile(r"[A-Za-z]")

PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[EMAIL]"),
    (re.compile(r"\b[\w.-]{2,}@[a-zA-Z]{2,}\b"), "[UPI]"),
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[PAN]"),
    (re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b"), "[IFSC]"),
    (re.compile(r"(?<!\d)(?:\d{4}[ -]){3}\d{1,7}(?!\d)"), "[CARD]"),
    (re.compile(r"(?<![\d.,])(?:\+91[ -]?)?[6-9]\d{9}(?![\d.])"), "[PHONE]"),
    (re.compile(r"(?<![\d.,])\d{9,}(?![\d.])"), "[NUMBER]"),
    (re.compile(r"(?i)\b[xX*]{2,}\d{3,6}\b"), "[NUMBER]"),
)


def redact(text: str) -> str:
    for pattern, replacement in PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def find_sensitive(text: str) -> list[str]:
    return [match.group(0) for pattern, _ in PATTERNS for match in pattern.finditer(text)]


def _mask_word(word: str) -> str:
    if KEEP_WORDS.match(word) or word.startswith("["):
        return word
    return LETTER.sub("x", word)


def _mask_line(line: str) -> str:
    return " ".join(_mask_word(word) for word in redact(line).split())


def sketch(lines: Sequence[str], starts_with_date: Callable[[str], bool]) -> tuple[str, ...]:
    first_data = next((i for i, line in enumerate(lines) if starts_with_date(line)), None)
    if first_data is None:
        return ()
    above = lines[first_data - 1] if first_data > 0 else ""
    header = [redact(above)] if above and not any(ch.isdigit() for ch in above) else []
    data = [_mask_line(line) for line in lines[first_data:] if starts_with_date(line)][:MAX_SKETCH_ROWS]
    return (*header, *data)
