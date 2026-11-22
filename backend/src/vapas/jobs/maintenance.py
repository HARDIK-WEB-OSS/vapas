import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from vapas.jobs.context import WorkerContext
from vapas.storage.object_store import delete_keys, stale_raw_keys


async def sweep_raw_files(ctx: WorkerContext, now: datetime | None = None) -> int:
    cutoff = (now or datetime.now(UTC)) - timedelta(minutes=ctx.settings.raw_file_max_age_minutes)
    deps = ctx.dependencies
    keys = await asyncio.to_thread(stale_raw_keys, deps.s3, deps.bucket, cutoff)
    if not keys:
        return 0
    await asyncio.to_thread(delete_keys, deps.s3, deps.bucket, keys)
    async with ctx.db.anonymous() as conn:
        await conn.execute(text("SELECT mark_raw_deleted(:keys)"), {"keys": keys})
    return len(keys)


async def drop_expired_partitions(ctx: WorkerContext) -> int:
    async with ctx.db.anonymous() as conn:
        dropped = await conn.scalar(
            text("SELECT drop_expired_transaction_partitions(:months)"),
            {"months": ctx.settings.transaction_retention_months},
        )
    return int(dropped or 0)


async def delete_unverified_accounts(ctx: WorkerContext, now: datetime | None = None) -> int:
    cutoff = (now or datetime.now(UTC)) - timedelta(hours=ctx.settings.unverified_account_ttl_hours)
    async with ctx.db.anonymous() as conn:
        removed = await conn.scalar(text("SELECT delete_unverified_accounts(:cutoff)"), {"cutoff": cutoff})
    return int(removed or 0)
