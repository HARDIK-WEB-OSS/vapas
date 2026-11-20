import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection

from vapas.db.models import statements, transactions

AWAITING_UPLOAD = "awaiting_upload"
QUEUED = "queued"
PARSING = "parsing"
PARSED = "parsed"
NEEDS_PASSWORD = "needs_password"
NEEDS_REVIEW = "needs_review"
FAILED = "failed"
STATEMENT_UPLOADED = "statement_uploaded"
INSERT_OUTBOX = text(
    "INSERT INTO outbox (event_type, user_id, payload) VALUES (:event, :user_id, CAST(:payload AS jsonb))"
)


@dataclass(frozen=True)
class StatementRow:
    id: UUID
    user_id: UUID
    content_sha256: bytes
    file_kind: str
    size_bytes: int
    object_key: str
    status: str
    failure_code: str | None
    parse_requests: int
    bank_code: str | None
    rows_parsed: int | None
    reconciled: bool | None
    period_from: date | None
    period_to: date | None
    created_at: datetime
    raw_deleted_at: datetime | None


COLUMNS = (
    statements.c.id,
    statements.c.user_id,
    statements.c.content_sha256,
    statements.c.file_kind,
    statements.c.size_bytes,
    statements.c.object_key,
    statements.c.status,
    statements.c.failure_code,
    statements.c.parse_requests,
    statements.c.bank_code,
    statements.c.rows_parsed,
    statements.c.reconciled,
    statements.c.period_from,
    statements.c.period_to,
    statements.c.created_at,
    statements.c.raw_deleted_at,
)


def _row(row: Any) -> StatementRow:
    values = dict(row._mapping)
    values["content_sha256"] = bytes(values["content_sha256"])
    return StatementRow(**values)


async def by_hash(conn: AsyncConnection, user_id: UUID, sha256: bytes) -> StatementRow | None:
    statement = select(*COLUMNS).where(statements.c.user_id == user_id, statements.c.content_sha256 == sha256)
    row = (await conn.execute(statement)).first()
    return None if row is None else _row(row)


async def get(conn: AsyncConnection, statement_id: UUID) -> StatementRow | None:
    row = (await conn.execute(select(*COLUMNS).where(statements.c.id == statement_id))).first()
    return None if row is None else _row(row)


async def list_for_user(conn: AsyncConnection, user_id: UUID, limit: int = 100) -> list[StatementRow]:
    statement = (
        select(*COLUMNS).where(statements.c.user_id == user_id).order_by(statements.c.created_at.desc()).limit(limit)
    )
    return [_row(r) for r in await conn.execute(statement)]


async def create(
    conn: AsyncConnection,
    statement_id: UUID,
    user_id: UUID,
    sha256: bytes,
    file_kind: str,
    size_bytes: int,
    object_key: str,
) -> None:
    values = {
        "id": statement_id,
        "user_id": user_id,
        "content_sha256": sha256,
        "file_kind": file_kind,
        "size_bytes": size_bytes,
        "object_key": object_key,
        "status": AWAITING_UPLOAD,
    }
    await conn.execute(insert(statements).values(**values))


async def queue_for_parsing(conn: AsyncConnection, row: StatementRow) -> int:
    statement = (
        update(statements)
        .where(statements.c.id == row.id)
        .values(
            status=QUEUED,
            failure_code=None,
            parse_requests=statements.c.parse_requests + 1,
            confirmed_at=func.coalesce(statements.c.confirmed_at, func.now()),
        )
        .returning(statements.c.parse_requests)
    )
    request = int((await conn.execute(statement)).scalar_one())
    payload = {"statement_id": str(row.id), "sha256": row.content_sha256.hex(), "parse_request": request}
    await conn.execute(
        INSERT_OUTBOX, {"event": STATEMENT_UPLOADED, "user_id": row.user_id, "payload": json.dumps(payload)}
    )
    return request


async def set_status(conn: AsyncConnection, statement_id: UUID, status: str, failure_code: str | None = None) -> None:
    await conn.execute(
        update(statements).where(statements.c.id == statement_id).values(status=status, failure_code=failure_code)
    )


async def record_parse(conn: AsyncConnection, statement_id: UUID, values: dict[str, Any]) -> None:
    await conn.execute(update(statements).where(statements.c.id == statement_id).values(**values, parsed_at=func.now()))


async def mark_raw_deleted(conn: AsyncConnection, statement_id: UUID) -> None:
    statement = update(statements).where(statements.c.id == statement_id, statements.c.raw_deleted_at.is_(None))
    await conn.execute(statement.values(raw_deleted_at=func.now()))


async def ensure_partitions(conn: AsyncConnection, months: Sequence[date]) -> None:
    for month in sorted(set(months)):
        await conn.execute(text("SELECT ensure_transaction_partition(:m)"), {"m": month})


async def replace_transactions(conn: AsyncConnection, statement_id: UUID, rows: Sequence[dict[str, Any]]) -> None:
    await conn.execute(transactions.delete().where(transactions.c.statement_id == statement_id))
    if rows:
        await conn.execute(insert(transactions), list(rows))


async def transactions_for_statement(conn: AsyncConnection, statement_id: UUID) -> list[Any]:
    statement = (
        select(transactions).where(transactions.c.statement_id == statement_id).order_by(transactions.c.row_index)
    )
    return list(await conn.execute(statement))


async def transactions_for_user(conn: AsyncConnection, user_id: UUID) -> list[Any]:
    statement = (
        select(transactions)
        .where(transactions.c.user_id == user_id)
        .order_by(transactions.c.statement_id, transactions.c.row_index)
    )
    return list(await conn.execute(statement))
