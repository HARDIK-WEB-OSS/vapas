import asyncio

import pytest
from fastapi.testclient import TestClient

from vapas import health
from vapas.health import Probe
from vapas.main import create_app


async def ok() -> bool:
    return True


async def down() -> bool:
    raise ConnectionError("refused")


async def says_no() -> bool:
    return False


async def hangs() -> bool:
    await asyncio.sleep(10)
    return True


def client(probes: dict[str, Probe]) -> TestClient:
    return TestClient(create_app(probes=probes))


def test_health_is_always_ok() -> None:
    with client({"postgres": down}) as c:
        response = c.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_when_every_dependency_answers() -> None:
    with client({"postgres": ok, "redis": ok, "object_store": ok}) as c:
        response = c.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"postgres": True, "redis": True, "object_store": True}}


@pytest.mark.parametrize("failing", [down, says_no])
def test_not_ready_when_one_dependency_fails(failing: Probe) -> None:
    with client({"postgres": ok, "redis": failing}) as c:
        response = c.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "checks": {"postgres": True, "redis": False}}


async def test_hanging_dependency_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health, "PROBE_TIMEOUT_SECONDS", 0.05)
    assert await health.run_probes({"postgres": hangs, "redis": ok}) == {"postgres": False, "redis": True}


async def test_failure_log_carries_no_error_message(caplog: pytest.LogCaptureFixture) -> None:
    async def leaks() -> bool:
        raise ConnectionError("postgresql://user:secret-db-password@host")

    await health.run_probes({"postgres": leaks})
    assert "secret-db-password" not in caplog.text
    assert any(getattr(r, "error_type", None) == "ConnectionError" for r in caplog.records)
