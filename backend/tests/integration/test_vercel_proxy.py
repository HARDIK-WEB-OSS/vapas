from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from vapas.auth.routes import REFRESH_COOKIE
from vapas.config import Settings
from vapas.main import create_app
from vapas.privacy.notices import CURRENT_NOTICE_VERSION
from vapas.security.proxy_guard import PROXY_SECRET_HEADER

from .conftest import PASSWORD, bearer, fresh_client_address, last_token

pytestmark = pytest.mark.integration

PROXY_SECRET = "integration-proxy-secret-0123456789abcdef"
EMAIL = "asha@example.in"


@pytest.fixture
def proxied(live_settings: Settings) -> Iterator[TestClient]:
    settings = live_settings.model_copy(
        update={
            "proxy_shared_secret": SecretStr(PROXY_SECRET),
            "client_ip_header": "X-Vapas-Client-IP",
            "refresh_cookie_path": "/api/auth",
        }
    )
    with TestClient(create_app(settings), client=fresh_client_address()) as test_client:
        yield test_client


def test_direct_calls_without_the_proxy_secret_are_refused(proxied: TestClient) -> None:
    response = proxied.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert (response.status_code, response.json()["error"]) == (403, "forbidden")
    assert proxied.get("/ready").status_code in {200, 503}


def test_refresh_cookie_is_scoped_to_the_proxied_auth_path(proxied: TestClient) -> None:
    proxied.headers[PROXY_SECRET_HEADER] = PROXY_SECRET
    body = {"email": EMAIL, "password": PASSWORD, "consent_notice_version": CURRENT_NOTICE_VERSION}
    assert proxied.post("/auth/signup", json=body).status_code == 202
    assert proxied.post("/auth/verify-email", json={"token": last_token(proxied, "verify_email")}).status_code == 200
    login = proxied.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert login.status_code == 200
    cookie = login.headers["set-cookie"]
    assert f"{REFRESH_COOKIE}=" in cookie
    assert "Path=/api/auth" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie

    logout = proxied.post("/auth/logout", headers=bearer(login.json()["access_token"]))
    assert logout.status_code == 204
    assert "Path=/api/auth" in logout.headers["set-cookie"]
