import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from vapas.config import get_settings
from vapas.ingest.model import FileKind, NeedsPasswordError, ParseError, UnknownLayoutError, WrongPasswordError
from vapas.ingest.parse import parse_document
from vapas.ingest.reconcile import reconcile
from vapas.security.private_path_guard import ensure_outside_code_root
from vapas.security.upload_guard import UploadRejectedError, check_upload

SUFFIXES = {".pdf": FileKind.PDF, ".csv": FileKind.CSV, ".xls": FileKind.XLS, ".xlsx": FileKind.XLSX}
Z_95 = 1.959964


@dataclass
class BankTally:
    files: int = 0
    parsed: int = 0
    reconciled: int = 0
    rows: int = 0
    rejected_rows: int = 0


def wilson(successes: int, total: int) -> str:
    if total == 0:
        return "n/a"
    p = successes / total
    denominator = 1 + Z_95**2 / total
    centre = (p + Z_95**2 / (2 * total)) / denominator
    margin = Z_95 * math.sqrt(p * (1 - p) / total + Z_95**2 / (4 * total**2)) / denominator
    return f"{100 * p:.1f}% (95% CI {100 * (centre - margin):.1f}-{100 * (centre + margin):.1f}%)"


def load_passwords(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in data.items()}


def evaluate(folder: Path, passwords: dict[str, str]) -> tuple[dict[str, BankTally], Counter[str]]:
    banks: dict[str, BankTally] = defaultdict(BankTally)
    outcomes: Counter[str] = Counter()
    for path in sorted(p for p in folder.rglob("*") if p.suffix.lower() in SUFFIXES):
        kind = SUFFIXES[path.suffix.lower()]
        data = path.read_bytes()
        try:
            check_upload(data, kind)
            parsed = parse_document(data, kind, passwords.get(path.name))
        except (NeedsPasswordError, WrongPasswordError):
            outcomes["needs_password"] += 1
            continue
        except UnknownLayoutError:
            outcomes["unknown_layout_needs_fallback"] += 1
            continue
        except UploadRejectedError as error:
            outcomes[f"rejected_{error.code}"] += 1
            continue
        except ParseError as error:
            outcomes[f"failed_{error.code}"] += 1
            continue
        outcomes["parsed"] += 1
        tally = banks[parsed.bank_code]
        tally.files += 1
        tally.parsed += bool(parsed.rows)
        tally.reconciled += reconcile(parsed.rows, parsed.opening_balance_paise).reconciled
        tally.rows += len(parsed.rows)
        tally.rejected_rows += parsed.rejected_rows
    return banks, outcomes


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate parser metrics on private real statements.")
    parser.add_argument("--passwords", type=Path, help="JSON file inside PRIVATE_FIXTURES_DIR: file name -> password")
    args = parser.parse_args()
    folder = get_settings().private_fixtures_dir
    if folder is None:
        print("PRIVATE_FIXTURES_DIR is not set", file=sys.stderr)
        return 2
    if args.passwords is not None:
        ensure_outside_code_root(args.passwords)
    banks, outcomes = evaluate(folder, load_passwords(args.passwords))
    total = sum(outcomes.values())
    print(f"files: {total}")
    for outcome, count in sorted(outcomes.items()):
        print(f"  {outcome}: {count}")
    print(f"parsed share: {wilson(outcomes['parsed'], total)}")
    for bank, t in sorted(banks.items()):
        print(
            f"{bank}: files={t.files} rows={t.rows} rejected_rows={t.rejected_rows} "
            f"reconciled={wilson(t.reconciled, t.files)}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
