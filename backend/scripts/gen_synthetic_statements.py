import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from vapas.ingest.model import ParsedRow
from vapas.synthetic.generator import (
    STYLES,
    SyntheticStatement,
    expected_rows,
    generate,
    render_csv,
    render_pdf,
    render_xls,
    render_xlsx,
)

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "tests" / "golden" / "synthetic"
GOLDEN_SEED = 2026
GOLDEN_ROWS = 60
RENDERERS: dict[str, Callable[[SyntheticStatement], bytes]] = {
    "pdf": render_pdf,
    "csv": render_csv,
    "xlsx": render_xlsx,
    "xls": render_xls,
}


def row_json(row: ParsedRow) -> dict[str, object]:
    data = asdict(row)
    data["txn_date"] = row.txn_date.isoformat()
    data["value_date"] = row.value_date.isoformat() if row.value_date else None
    data["direction"] = row.direction.value
    return data


def write_statement(statement: SyntheticStatement, out_dir: Path, stem: str, formats: list[str]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in formats:
        (out_dir / f"{stem}.{name}").write_bytes(RENDERERS[name](statement))
    truth = {
        "bank": statement.bank,
        "opening_balance_paise": statement.opening_balance_paise,
        "rows": [row_json(r) for r in expected_rows(statement)],
    }
    (out_dir / f"{stem}.expected.json").write_text(json.dumps(truth, indent=1) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Write synthetic bank statements with known ground truth.")
    parser.add_argument("--golden", action="store_true", help="rewrite the committed golden fixtures")
    parser.add_argument("--out", type=Path, help="output folder for a generated set")
    parser.add_argument("--count", type=int, default=5, help="statements per bank")
    parser.add_argument("--rows", type=int, default=60)
    parser.add_argument("--formats", default="pdf,csv,xlsx,xls")
    args = parser.parse_args()
    formats = args.formats.split(",")
    if args.golden:
        for bank in STYLES:
            write_statement(generate(bank, GOLDEN_SEED, GOLDEN_ROWS), GOLDEN_DIR, bank.lower(), formats)
        print(f"golden fixtures written to {GOLDEN_DIR}")
        return 0
    if args.out is None:
        parser.error("--out is required unless --golden is given")
    for bank in STYLES:
        for seed in range(args.count):
            write_statement(generate(bank, seed, args.rows), args.out, f"{bank.lower()}_{seed:03d}", formats)
    print(f"{args.count * len(STYLES)} statements written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
