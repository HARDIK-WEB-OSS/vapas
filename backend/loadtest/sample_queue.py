import argparse
import asyncio
import csv
import sys
import time
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from vapas.config import get_settings
from vapas.security.private_path_guard import ensure_outside_code_root

DEPTH_SQL = text(
    "SELECT queue, state, count(*) AS n, "
    "coalesce(extract(epoch FROM now() - min(run_after)) FILTER (WHERE state = 'queued'), 0) AS oldest "
    "FROM jobs GROUP BY queue, state"
)


async def sample(out: Path, seconds: float, every: float) -> None:
    url = get_settings().migration_database_url
    if url is None:
        raise SystemExit("MIGRATION_DATABASE_URL is required")
    engine = create_async_engine(url.get_secret_value())
    deadline = time.monotonic() + seconds
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["t_seconds", "queue", "state", "count", "oldest_queued_seconds"])
        started = time.monotonic()
        while time.monotonic() < deadline:
            async with engine.connect() as conn:
                for row in await conn.execute(DEPTH_SQL):
                    elapsed = round(time.monotonic() - started, 1)
                    writer.writerow([elapsed, row.queue, row.state, row.n, round(float(row.oldest), 1)])
            handle.flush()
            await asyncio.sleep(every)
    await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=600)
    parser.add_argument("--every", type=float, default=2.0)
    args = parser.parse_args()
    out = ensure_outside_code_root(args.out)
    asyncio.run(sample(out, args.seconds, args.every))
    return 0


if __name__ == "__main__":
    sys.exit(main())
