import argparse
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from vapas.security.private_path_guard import ensure_outside_code_root

SCRATCH_DB = "vapas_restore_check"
COMPOSE = ["docker", "compose", "exec", "-T", "postgres"]
COUNT_SQL = (
    "SELECT n.nspname || '.' || c.relname, "
    "(xpath('/row/n/text()', query_to_xml(format('SELECT count(*) AS n FROM %I.%I', n.nspname, c.relname), "
    "false, true, '')))[1]::text::bigint "
    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE c.relkind IN ('r', 'p') AND NOT c.relispartition AND n.nspname = 'public' ORDER BY 1"
)


def psql(user: str, database: str, sql: str) -> str:
    command = [*COMPOSE, "psql", "-U", user, "-d", database, "-At", "-F", "|", "-c", sql]
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout


def table_counts(user: str, database: str) -> dict[str, int]:
    rows = [line.split("|") for line in psql(user, database, COUNT_SQL).splitlines() if line]
    return {name: int(count) for name, count in rows}


def dump(user: str, database: str, target: Path) -> None:
    command = [*COMPOSE, "pg_dump", "-U", user, "-d", database, "--format=custom", "--no-owner", "--no-privileges"]
    with target.open("wb") as handle:
        subprocess.run(command, check=True, stdout=handle)


def restore(user: str, source: Path) -> None:
    psql(user, "postgres", f"DROP DATABASE IF EXISTS {SCRATCH_DB}")
    psql(user, "postgres", f"CREATE DATABASE {SCRATCH_DB}")
    command = [*COMPOSE, "pg_restore", "-U", user, "-d", SCRATCH_DB, "--no-owner", "--no-privileges", "--exit-on-error"]
    with source.open("rb") as handle:
        subprocess.run(command, check=True, stdin=handle)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--user", default="vapas")
    parser.add_argument("--database", default="vapas")
    args = parser.parse_args()
    out_dir = ensure_outside_code_root(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"vapas-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.dump"
    dump(args.user, args.database, target)
    restore(args.user, target)
    source_counts = table_counts(args.user, args.database)
    restored_counts = table_counts(args.user, SCRATCH_DB)
    psql(args.user, "postgres", f"DROP DATABASE {SCRATCH_DB}")
    mismatched = sorted(name for name in source_counts if source_counts[name] != restored_counts.get(name))
    total = sum(source_counts.values())
    print(f"dump: {target.name}, {target.stat().st_size} bytes")
    print(f"tables: {len(source_counts)}, rows: {total}, mismatched tables: {len(mismatched)}")
    for name in mismatched:
        print(f"MISMATCH {name}: source {source_counts[name]}, restored {restored_counts.get(name)}")
    return 1 if mismatched or set(source_counts) != set(restored_counts) else 0


if __name__ == "__main__":
    sys.exit(main())
