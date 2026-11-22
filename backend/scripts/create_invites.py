import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from vapas.auth.invites import invite_code_hash, new_invite_code
from vapas.config import get_settings

INSERT_INVITE = text(
    "INSERT INTO invite_codes (id, code_hash, cohort, max_uses, expires_at) VALUES (:id, :h, :cohort, :uses, :expires)"
)


async def create(count: int, cohort: str, max_uses: int, expires_days: int) -> list[str]:
    url = get_settings().migration_database_url
    if url is None:
        raise SystemExit("MIGRATION_DATABASE_URL is required")
    expires = datetime.now(UTC) + timedelta(days=expires_days)
    codes = [new_invite_code() for _ in range(count)]
    engine = create_async_engine(url.get_secret_value())
    try:
        async with engine.begin() as conn:
            for code in codes:
                values = {"id": uuid4(), "h": invite_code_hash(code), "cohort": cohort, "uses": max_uses}
                await conn.execute(INSERT_INVITE, {**values, "expires": expires})
    finally:
        await engine.dispose()
    return codes


def main() -> int:
    parser = argparse.ArgumentParser(description="Create pilot invite codes. Codes are shown once and stored hashed.")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--cohort", required=True)
    parser.add_argument("--max-uses", type=int, default=1)
    parser.add_argument("--expires-days", type=int, default=30)
    args = parser.parse_args()
    for code in asyncio.run(create(args.count, args.cohort, args.max_uses, args.expires_days)):
        print(code)
    return 0


if __name__ == "__main__":
    sys.exit(main())
