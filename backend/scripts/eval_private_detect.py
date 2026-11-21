import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

from eval_private import SUFFIXES, load_passwords, wilson

from vapas.classify.channel_rules import classify
from vapas.config import get_settings
from vapas.detect.engine import detect
from vapas.detect.model import Level, Txn, TxnKey, UserAnswers
from vapas.ingest.model import ParseError
from vapas.ingest.parse import parse_document
from vapas.ingest.reconcile import reconcile
from vapas.jobs.detection import today_ist
from vapas.rules.loader import load_rulebook
from vapas.security.private_path_guard import ensure_outside_code_root

SKIP_FOLDERS = frozenset({"labels", "consent"})
REVIEW_FILE = "labels/claims_review.csv"
REVIEW_FIELDS = ["person", "level", "rule", "why", "debit_narration", "correct"]


def person_transactions(folder: Path, passwords: dict[str, str]) -> tuple[list[Txn], int]:
    txns: list[Txn] = []
    statements = 0
    for path in sorted(p for p in folder.rglob("*") if p.suffix.lower() in SUFFIXES):
        try:
            parsed = parse_document(path.read_bytes(), SUFFIXES[path.suffix.lower()], passwords.get(path.name))
        except ParseError:
            continue
        if not reconcile(parsed.rows, parsed.opening_balance_paise).reconciled:
            continue
        statements += 1
        for row in parsed.rows:
            label = classify(row.narration, row.direction)
            refs = frozenset(r.encode() for r in (row.ref_no, label.reference) if r)
            txns.append(
                Txn(
                    TxnKey(len(txns) + 1, row.txn_date),
                    path.name,
                    row.row_index,
                    row.txn_date,
                    row.value_date,
                    row.direction,
                    row.amount_paise,
                    row.balance_paise,
                    label.channel,
                    label.kind,
                    row.narration,
                    refs,
                    parsed.bank_code,
                )
            )
    return txns, statements


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate detector results on private real statements.")
    parser.add_argument("--passwords", type=Path, help="JSON file inside PRIVATE_FIXTURES_DIR: file name -> password")
    args = parser.parse_args()
    settings = get_settings()
    root = settings.private_fixtures_dir
    if root is None:
        print("PRIVATE_FIXTURES_DIR is not set; put one subfolder per person inside it", file=sys.stderr)
        return 2
    if args.passwords is not None:
        ensure_outside_code_root(args.passwords)
    passwords = load_passwords(args.passwords)
    rulebook = load_rulebook(settings.rules_dir)
    people = [p for p in sorted(root.iterdir()) if p.is_dir() and p.name not in SKIP_FOLDERS]
    levels: Counter[str] = Counter()
    claim_paise = statements_used = people_with_claim = 0
    review: list[dict[str, object]] = []
    for number, person in enumerate(people):
        txns, statements = person_transactions(person, passwords)
        statements_used += statements
        found = detect(txns, UserAnswers(), rulebook, today_ist(), settings.claim_lookback_months, lambda n: n)
        levels.update(f"{f.detector.value}:{f.level.value}" for f in found)
        claims = [f for f in found if f.level is Level.CLAIM]
        people_with_claim += bool(claims)
        claim_paise += sum(f.amount_owed_paise or 0 for f in claims)
        by_key = {t.key: t for t in txns}
        for finding in found:
            if finding.level in (Level.CLAIM, Level.NEEDS_USER_INPUT):
                debit = by_key.get(finding.debit) if finding.debit else None
                review.append(
                    {
                        "person": number,
                        "level": finding.level.value,
                        "rule": finding.rule_id or "",
                        "why": finding.why,
                        "debit_narration": debit.narration if debit else "",
                        "correct": "",
                    }
                )
    print(f"people: {len(people)}; reconciled statements used: {statements_used}")
    for name, count in sorted(levels.items()):
        print(f"  {name}: {count}")
    print(f"claims before manual review: Rs {claim_paise // 100}")
    print(f"people with at least one claim: {wilson(people_with_claim, len(people))}")
    target = root / REVIEW_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(review)
    print(f"{len(review)} findings written to PRIVATE_FIXTURES_DIR/{REVIEW_FILE} for manual review")
    return 0


if __name__ == "__main__":
    sys.exit(main())
