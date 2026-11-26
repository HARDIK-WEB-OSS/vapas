import argparse
import getpass
import io
import re
import sys
from collections import Counter
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

from vapas.ingest.pdf_reader import page_text_lines
from vapas.security.private_path_guard import ensure_outside_code_root

HEADER_WORDS = frozenset(
    {
        "date",
        "txn",
        "tran",
        "transaction",
        "value",
        "posting",
        "narration",
        "description",
        "particulars",
        "details",
        "remarks",
        "debit",
        "credit",
        "withdrawal",
        "withdrawals",
        "deposit",
        "deposits",
        "balance",
        "amount",
        "amt",
        "chq",
        "cheque",
        "ref",
        "reference",
        "no",
        "no.",
        "dr",
        "cr",
        "dr/cr",
        "mode",
        "type",
        "closing",
        "opening",
        "sl",
        "s.no",
        "branch",
        "code",
        "instrument",
        "id",
    }
)
MIN_HEADER_HITS = 3
MIN_HEADER_SHARE = 0.6
DATE_LIKE = re.compile(r"^(\d{1,2}[-/. ]?(\d{1,2}|[A-Za-z]{3})[-/. ]?\d{2,4})$")
MONEY_LIKE = re.compile(r"^-?[\d,]+\.\d{2}(Cr|Dr|CR|DR)?$")
MAX_SHOWN_HEADERS = 3


def mask_word(word: str) -> str:
    if word.lower().strip("()") in HEADER_WORDS:
        return word
    return "?"


def is_header(line: str) -> bool:
    tokens = line.lower().replace("(", " ").replace(")", " ").split()
    if not tokens or DATE_LIKE.match(tokens[0]) or any(MONEY_LIKE.match(t) for t in line.split()):
        return False
    hits = sum(1 for token in tokens if token in HEADER_WORDS)
    return hits >= MIN_HEADER_HITS and hits >= MIN_HEADER_SHARE * len(tokens)


def starts_with_date(line: str) -> bool:
    tokens = line.split()
    return bool(tokens) and DATE_LIKE.match(tokens[0]) is not None


def shape(token: str) -> str:
    return "".join("9" if ch.isdigit() else "A" if ch.isalpha() else ch for ch in token)


def open_lines(path: Path) -> tuple[list[list[str]], bool]:
    data = path.read_bytes()
    reader = PdfReader(io.BytesIO(data))
    password = ""
    if reader.is_encrypted:
        password = getpass.getpass(f"Password for {path.name} (not stored, not shown): ")
        if not reader.decrypt(password):
            raise SystemExit("wrong password")
    with pdfplumber.open(io.BytesIO(data), password=password) as pdf:
        return [page_text_lines(page) for page in pdf.pages], reader.is_encrypted


def describe(path: Path) -> None:
    pages, encrypted = open_lines(path)
    lines = [line for page in pages for line in page]
    headers = Counter(line for line in lines if is_header(line))
    date_shapes: Counter[str] = Counter()
    money_suffixes: Counter[str] = Counter()
    money_per_row: Counter[int] = Counter()
    dated_rows = 0
    for line in lines:
        tokens = line.split()
        if not tokens or not DATE_LIKE.match(tokens[0]):
            continue
        dated_rows += 1
        date_shapes[shape(tokens[0])] += 1
        amounts = [t for t in tokens if MONEY_LIKE.match(t)]
        money_per_row[len(amounts)] += 1
        for amount in amounts:
            money_suffixes[amount[-2:].upper() if amount[-2:].isalpha() else "none"] += 1
    print(f"file type: PDF | pages: {len(pages)} | password protected: {encrypted} | text lines: {len(lines)}")
    print(f"pages with no text layer (scanned): {sum(1 for page in pages if not page)}")
    print("table header lines (any word that is not a known header word shows as ?):")
    for header, count in headers.most_common(MAX_SHOWN_HEADERS):
        print(f"  [{count}x] " + " ".join(mask_word(w) for w in header.split()))
    if not headers:
        print("  none found")
    print(f"lines starting with a date: {dated_rows}")
    print(f"date shapes (9 = digit, A = letter): {dict(date_shapes.most_common(4))}")
    print(f"amounts per dated line: {dict(sorted(money_per_row.items()))}")
    print(f"amount suffixes: {dict(money_suffixes.most_common())}")
    per_page = [sum(1 for line in page if starts_with_date(line)) for page in pages[:3]]
    print(f"dated lines per page, first 3 pages: {per_page}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Print only the layout of a statement PDF, never rows or names.")
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()
    path = ensure_outside_code_root(args.pdf)
    if path.suffix.lower() != ".pdf":
        raise SystemExit("only PDF files are supported")
    describe(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
