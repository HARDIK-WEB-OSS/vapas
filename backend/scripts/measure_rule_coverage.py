import argparse
import csv
import json
import random
import sys
from collections import Counter
from pathlib import Path

from eval_private import SUFFIXES, load_passwords, wilson

from vapas.classify.channel_rules import CLASSIFIER_VERSION, Channel, Kind, classify
from vapas.config import get_settings
from vapas.ingest.model import ParsedRow, ParseError
from vapas.ingest.parse import parse_document

LABEL_FILE = "labels/channel_sample.csv"
FIELDS = ["row", "direction", "narration", "predicted_channel", "predicted_kind", "true_channel", "true_kind"]


def private_rows(folder: Path, passwords: dict[str, str]) -> list[ParsedRow]:
    rows: list[ParsedRow] = []
    for path in sorted(p for p in folder.rglob("*") if p.suffix.lower() in SUFFIXES):
        try:
            rows.extend(parse_document(path.read_bytes(), SUFFIXES[path.suffix.lower()], passwords.get(path.name)).rows)
        except ParseError:
            continue
    return rows


def write_sample(folder: Path, rows: list[ParsedRow], size: int, seed: int) -> None:
    target = folder / LABEL_FILE
    if target.exists():
        print(f"{LABEL_FILE} already exists inside PRIVATE_FIXTURES_DIR; refusing to overwrite labels", file=sys.stderr)
        raise SystemExit(2)
    target.parent.mkdir(parents=True, exist_ok=True)
    sample = random.Random(seed).sample(rows, min(size, len(rows)))
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for index, row in enumerate(sample):
            result = classify(row.narration, row.direction)
            writer.writerow(
                {
                    "row": index,
                    "direction": row.direction.value,
                    "narration": row.narration,
                    "predicted_channel": result.channel.value,
                    "predicted_kind": result.kind.value,
                    "true_channel": "",
                    "true_kind": "",
                }
            )
    print(f"wrote {len(sample)} rows to PRIVATE_FIXTURES_DIR/{LABEL_FILE}; fill true_channel and true_kind")


def coverage(rows: list[ParsedRow]) -> None:
    channels = Counter(classify(r.narration, r.direction).channel for r in rows)
    covered = sum(n for channel, n in channels.items() if channel is not Channel.UNCLASSIFIED)
    print(f"classifier version {CLASSIFIER_VERSION}; rows: {len(rows)}")
    print(f"coverage: {wilson(covered, len(rows))}")
    for channel, count in channels.most_common():
        print(f"  {channel.value}: {count}")


def score(folder: Path) -> None:
    with (folder / LABEL_FILE).open(encoding="utf-8") as handle:
        labelled = [r for r in csv.DictReader(handle) if r["true_channel"]]
    valid_channels = {c.value for c in Channel}
    valid_kinds = {k.value for k in Kind}
    bad = [r["row"] for r in labelled if r["true_channel"] not in valid_channels or r["true_kind"] not in valid_kinds]
    if bad:
        print(f"rows with unknown labels: {len(bad)}; fix them first", file=sys.stderr)
        raise SystemExit(2)
    print(f"labelled rows: {len(labelled)}")
    print(
        f"channel accuracy: {wilson(sum(r['predicted_channel'] == r['true_channel'] for r in labelled), len(labelled))}"
    )
    print(f"kind accuracy: {wilson(sum(r['predicted_kind'] == r['true_kind'] for r in labelled), len(labelled))}")
    for channel in sorted(valid_channels):
        predicted = [r for r in labelled if r["predicted_channel"] == channel]
        if predicted:
            right = sum(r["true_channel"] == channel for r in predicted)
            print(f"  precision {channel}: {wilson(right, len(predicted))}")
    reversals = [r for r in labelled if r["predicted_kind"] == Kind.REVERSAL.value]
    if reversals:
        right = sum(r["true_kind"] == Kind.REVERSAL.value for r in reversals)
        print(f"  precision reversal kind: {wilson(right, len(reversals))}")
    confusion = Counter(
        (r["true_channel"], r["predicted_channel"]) for r in labelled if r["true_channel"] != r["predicted_channel"]
    )
    print("confusions: " + json.dumps({f"{a}->{p}": n for (a, p), n in confusion.most_common()}))


def main() -> int:
    parser = argparse.ArgumentParser(description="Channel rule coverage and precision on private real statements.")
    parser.add_argument("mode", choices=["coverage", "sample", "score"])
    parser.add_argument("--size", type=int, default=300)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--passwords", type=Path)
    args = parser.parse_args()
    folder = get_settings().private_fixtures_dir
    if folder is None:
        print("PRIVATE_FIXTURES_DIR is not set", file=sys.stderr)
        return 2
    if args.mode == "score":
        score(folder)
        return 0
    rows = private_rows(folder, load_passwords(args.passwords))
    if args.mode == "coverage":
        coverage(rows)
    else:
        write_sample(folder, rows, args.size, args.seed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
