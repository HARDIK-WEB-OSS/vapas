import asyncio
import contextlib
import logging
import signal
from collections.abc import Mapping

from vapas.config import Settings, get_settings
from vapas.health import Dependencies, Probe, run_probes
from vapas.logging_setup import configure_logging

log = logging.getLogger(__name__)


async def heartbeat_loop(probes: Mapping[str, Probe], interval_seconds: float, stop: asyncio.Event) -> int:
    beats = 0
    while not stop.is_set():
        checks = await run_probes(probes)
        beats += 1
        log.info("worker heartbeat", extra={"checks": checks, "beat": beats})
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
    return beats


def _install_stop_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)


async def run_worker(settings: Settings) -> None:
    dependencies = Dependencies.from_settings(settings)
    stop = asyncio.Event()
    _install_stop_handlers(stop)
    log.info("worker started")
    try:
        await heartbeat_loop(dependencies.probes(), settings.worker_heartbeat_seconds, stop)
    finally:
        await dependencies.close()
        log.info("worker stopped")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run_worker(settings))


if __name__ == "__main__":
    main()
