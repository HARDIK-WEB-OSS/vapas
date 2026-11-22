import argparse
import asyncio
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from vapas.analytics.impact import Window, compute_impact, render_markdown
from vapas.config import get_settings
from vapas.jobs.detection import IST


def last_monday() -> date:
    today = datetime.now(IST).date()
    return today - timedelta(days=today.weekday() + 7)


async def build(week_start: date, data_label: str) -> str:
    url = get_settings().migration_database_url
    if url is None:
        raise SystemExit("MIGRATION_DATABASE_URL is required")
    engine = create_async_engine(url.get_secret_value())
    week = Window.week_from(week_start)
    try:
        async with engine.connect() as conn:
            this_week = await compute_impact(conn, week)
            to_date = await compute_impact(conn, Window.to_date(week.end))
    finally:
        await engine.dispose()
    return render_markdown(this_week, to_date, data_label)


def main() -> int:
    parser = argparse.ArgumentParser(description="Weekly impact report with aggregate numbers only.")
    parser.add_argument("--week-start", type=date.fromisoformat, default=None, help="a Monday, YYYY-MM-DD")
    parser.add_argument("--data-label", required=True, help="for example 'synthetic staging data' or 'pilot'")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    week_start = args.week_start or last_monday()
    if week_start.weekday() != 0:
        raise SystemExit("--week-start must be a Monday")
    report = asyncio.run(build(week_start, args.data_label))
    if args.out:
        args.out.write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
