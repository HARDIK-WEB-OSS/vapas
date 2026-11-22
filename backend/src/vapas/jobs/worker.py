import asyncio
import contextlib
import logging
import signal
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field

from vapas.config import Settings, get_settings
from vapas.health import Probe, run_probes
from vapas.jobs import queue
from vapas.jobs.case_work import process_case_work
from vapas.jobs.context import WorkerContext
from vapas.jobs.handlers import HANDLERS
from vapas.jobs.maintenance import delete_unverified_accounts, drop_expired_partitions, sweep_raw_files
from vapas.jobs.outbox import relay
from vapas.logging_setup import configure_logging
from vapas.observability import init_error_tracking

log = logging.getLogger(__name__)
SWEEP_EVERY_SECONDS = 300.0
RETENTION_EVERY_SECONDS = 86_400.0
CASE_WORK_EVERY_SECONDS = 3_600.0
UNVERIFIED_SWEEP_EVERY_SECONDS = 3_600.0


async def heartbeat_loop(probes: Mapping[str, Probe], interval_seconds: float, stop: asyncio.Event) -> int:
    beats = 0
    while not stop.is_set():
        checks = await run_probes(probes)
        beats += 1
        log.info("worker heartbeat", extra={"checks": checks, "beat": beats})
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
    return beats


@dataclass
class Periodic:
    every_seconds: float
    task: Callable[[WorkerContext], Awaitable[int]]
    name: str
    last_run: float = field(default=float("-inf"))

    async def maybe_run(self, ctx: WorkerContext, now: float) -> None:
        if now - self.last_run < self.every_seconds:
            return
        self.last_run = now
        try:
            count = await self.task(ctx)
            log.info("maintenance finished", extra={"task": self.name, "count": count})
        except Exception as error:
            log.warning("maintenance failed", extra={"task": self.name, "error_type": type(error).__name__})


async def process(ctx: WorkerContext, job: queue.Job) -> None:
    handlers = HANDLERS.get(job.queue)
    if handlers is None:
        async with ctx.db.anonymous() as conn:
            await queue.bury(conn, job.id, "unknown_queue")
        return
    handler, gave_up = handlers
    if job.exhausted:
        async with ctx.db.anonymous() as conn:
            await queue.bury(conn, job.id, "worker_crashed")
        await gave_up(ctx, job)
        return
    try:
        await handler(ctx, job)
    except Exception as error:
        log.warning("job failed", extra={"job_id": job.id, "queue": job.queue, "error_type": type(error).__name__})
        async with ctx.db.anonymous() as conn:
            state = await queue.fail(conn, job, type(error).__name__)
        if state == queue.DEAD:
            await gave_up(ctx, job)


async def run_once(ctx: WorkerContext) -> bool:
    async with ctx.db.anonymous() as conn:
        relayed = await relay(conn)
    async with ctx.db.anonymous() as conn:
        job = await queue.claim(conn, ctx.worker_id)
    if job is None:
        return relayed > 0
    await process(ctx, job)
    return True


async def work_loop(ctx: WorkerContext, stop: asyncio.Event) -> None:
    periodic = [
        Periodic(SWEEP_EVERY_SECONDS, sweep_raw_files, "sweep_raw_files"),
        Periodic(RETENTION_EVERY_SECONDS, drop_expired_partitions, "drop_expired_partitions"),
        Periodic(CASE_WORK_EVERY_SECONDS, process_case_work, "case_work"),
        Periodic(UNVERIFIED_SWEEP_EVERY_SECONDS, delete_unverified_accounts, "delete_unverified_accounts"),
    ]
    while not stop.is_set():
        did_work = False
        try:
            did_work = await run_once(ctx)
        except Exception as error:
            log.warning("worker iteration failed", extra={"error_type": type(error).__name__})
        for task in periodic:
            await task.maybe_run(ctx, time.monotonic())
        if not did_work:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=ctx.settings.worker_poll_seconds)


def _install_stop_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)


async def run_worker(settings: Settings) -> None:
    ctx = WorkerContext.from_settings(settings)
    stop = asyncio.Event()
    _install_stop_handlers(stop)
    log.info("worker started", extra={"worker_id": ctx.worker_id})
    try:
        await asyncio.gather(
            heartbeat_loop(ctx.dependencies.probes(), settings.worker_heartbeat_seconds, stop),
            work_loop(ctx, stop),
        )
    finally:
        await ctx.close()
        log.info("worker stopped")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    init_error_tracking(settings, "worker")
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run_worker(settings))


if __name__ == "__main__":
    main()
