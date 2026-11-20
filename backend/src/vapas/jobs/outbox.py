from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from vapas.db.models import outbox
from vapas.db.statements import STATEMENT_UPLOADED
from vapas.jobs.queue import enqueue

PARSE_QUEUE = "parse"
RELAY_BATCH = 50

Route = Callable[[UUID | None, dict[str, Any]], tuple[str, str]]


def _parse_route(user_id: UUID | None, payload: dict[str, Any]) -> tuple[str, str]:
    return PARSE_QUEUE, f"parse:{user_id}:{payload['sha256']}:{payload['parse_request']}"


ROUTES: dict[str, Route] = {STATEMENT_UPLOADED: _parse_route}


async def relay(conn: AsyncConnection, batch: int = RELAY_BATCH) -> int:
    pending = (
        select(outbox.c.id, outbox.c.event_type, outbox.c.user_id, outbox.c.payload)
        .where(outbox.c.published_at.is_(None))
        .order_by(outbox.c.id)
        .limit(batch)
        .with_for_update(skip_locked=True)
    )
    rows = list(await conn.execute(pending))
    for row in rows:
        route = ROUTES.get(row.event_type)
        if route is not None:
            queue, key = route(row.user_id, row.payload)
            await enqueue(conn, queue, key, row.user_id, dict(row.payload))
    if rows:
        ids = [row.id for row in rows]
        await conn.execute(update(outbox).where(outbox.c.id.in_(ids)).values(published_at=func.now()))
    return len(rows)
