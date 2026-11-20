from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from vapas.db.models import jobs

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
DEAD = "dead"
BACKOFF_BASE_SECONDS = 15
LEASE = timedelta(minutes=5)

CLAIM = text(
    """
    UPDATE jobs
    SET state = 'running', attempts = attempts + 1, locked_by = :worker, locked_until = now() + :lease
    WHERE id = (
        SELECT id FROM jobs
        WHERE (state = 'queued' AND run_after <= now()) OR (state = 'running' AND locked_until < now())
        ORDER BY id
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING id, queue, user_id, payload, attempts, max_attempts
    """
)


@dataclass(frozen=True)
class Job:
    id: int
    queue: str
    user_id: UUID | None
    payload: dict[str, Any]
    attempts: int
    max_attempts: int

    @property
    def exhausted(self) -> bool:
        return self.attempts > self.max_attempts


async def enqueue(conn: AsyncConnection, queue: str, key: str, user_id: UUID | None, payload: dict[str, Any]) -> bool:
    statement = (
        insert(jobs)
        .values(queue=queue, idempotency_key=key, user_id=user_id, payload=payload)
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    return (await conn.execute(statement)).rowcount == 1


async def claim(conn: AsyncConnection, worker_id: str, lease: timedelta = LEASE) -> Job | None:
    row = (await conn.execute(CLAIM, {"worker": worker_id, "lease": lease})).first()
    if row is None:
        return None
    return Job(row.id, row.queue, row.user_id, dict(row.payload), row.attempts, row.max_attempts)


async def complete(conn: AsyncConnection, job_id: int) -> None:
    statement = update(jobs).where(jobs.c.id == job_id)
    await conn.execute(statement.values(state=DONE, finished_at=func.now(), locked_until=None))


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=BACKOFF_BASE_SECONDS * 2 ** max(attempts - 1, 0))


async def fail(conn: AsyncConnection, job: Job, error_code: str) -> str:
    dead = job.attempts >= job.max_attempts
    values: dict[str, Any] = {"last_error_code": error_code, "locked_until": None}
    if dead:
        values |= {"state": DEAD, "finished_at": func.now()}
    else:
        values |= {"state": QUEUED, "run_after": func.now() + backoff(job.attempts)}
    await conn.execute(update(jobs).where(jobs.c.id == job.id).values(**values))
    return DEAD if dead else QUEUED


async def bury(conn: AsyncConnection, job_id: int, error_code: str) -> None:
    values = {"state": DEAD, "finished_at": func.now(), "locked_until": None, "last_error_code": error_code}
    await conn.execute(update(jobs).where(jobs.c.id == job_id).values(**values))
