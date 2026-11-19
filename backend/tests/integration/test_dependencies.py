import pytest
from fastapi.testclient import TestClient

from vapas.config import Settings
from vapas.health import Dependencies, run_probes
from vapas.main import create_app

pytestmark = pytest.mark.integration


async def test_every_dependency_answers() -> None:
    dependencies = Dependencies.from_settings(Settings())
    try:
        assert await run_probes(dependencies.probes()) == {"postgres": True, "redis": True, "object_store": True}
    finally:
        await dependencies.close()


def test_ready_endpoint_against_real_services() -> None:
    with TestClient(create_app(Settings())) as client:
        response = client.get("/ready")
    assert response.status_code == 200, response.json()
    assert response.json()["status"] == "ready"
