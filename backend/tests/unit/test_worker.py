import asyncio

from vapas.jobs.worker import heartbeat_loop


async def test_heartbeat_stops_when_asked() -> None:
    stop = asyncio.Event()
    calls = 0

    async def probe() -> bool:
        nonlocal calls
        calls += 1
        if calls == 2:
            stop.set()
        return True

    beats = await asyncio.wait_for(heartbeat_loop({"postgres": probe}, 0.01, stop), timeout=2)
    assert beats == 2


async def test_heartbeat_survives_failing_dependency() -> None:
    stop = asyncio.Event()
    calls = 0

    async def probe() -> bool:
        nonlocal calls
        calls += 1
        if calls == 3:
            stop.set()
        raise ConnectionError("down")

    assert await asyncio.wait_for(heartbeat_loop({"redis": probe}, 0.01, stop), timeout=2) == 3


async def test_already_stopped_worker_does_nothing() -> None:
    stop = asyncio.Event()
    stop.set()
    assert await heartbeat_loop({}, 0.01, stop) == 0
