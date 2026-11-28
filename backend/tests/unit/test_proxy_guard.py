import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vapas.security.proxy_guard import PROXY_SECRET_HEADER, ProxySecretMiddleware

SECRET = "proxy-secret-for-tests-0123456789abcdef"


def app_with(secret: str | None) -> TestClient:
    app = FastAPI()
    app.add_middleware(ProxySecretMiddleware, secret=secret)

    @app.get("/statements")
    async def statements() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> dict[str, str]:
        return {"status": "ready"}

    return TestClient(app)


@pytest.mark.parametrize("headers", [{}, {PROXY_SECRET_HEADER: "wrong"}, {PROXY_SECRET_HEADER: SECRET + "x"}])
def test_requests_without_the_proxy_secret_are_refused(headers: dict[str, str]) -> None:
    response = app_with(SECRET).get("/statements", headers=headers)
    assert (response.status_code, response.json()["error"]) == (403, "forbidden")


def test_requests_through_the_proxy_pass() -> None:
    assert app_with(SECRET).get("/statements", headers={PROXY_SECRET_HEADER: SECRET}).status_code == 200


@pytest.mark.parametrize("path", ["/health", "/ready"])
def test_platform_health_checks_need_no_secret(path: str) -> None:
    assert app_with(SECRET).get(path).status_code == 200


def test_without_a_configured_secret_nothing_is_checked() -> None:
    assert app_with(None).get("/statements").status_code == 200
