import pytest
from fastapi.testclient import TestClient

from vapas.auth.routes import REFRESH_COOKIE
from vapas.config import Settings
from vapas.privacy.notices import CURRENT_NOTICE_VERSION
from vapas.security.ratelimit import LOGIN_FAILURES_PER_ACCOUNT, LOGIN_PER_IP

from .conftest import PASSWORD, bearer, last_token, login, mailbox, owner_sql, signup

pytestmark = pytest.mark.integration

EMAIL = "asha@example.in"


def test_full_signup_verify_login_refresh_flow(client: TestClient) -> None:
    notice = client.get("/consent/notice").json()
    assert notice["version"] == CURRENT_NOTICE_VERSION
    assert "VAPAS" in notice["text_hi"]

    signup(client, EMAIL)
    access = login(client, EMAIL)
    assert client.get("/account/me", headers=bearer(access)).json()["email_verified"] is False

    assert client.post("/auth/verify-email", json={"token": last_token(client, "verify_email")}).status_code == 200
    me = client.get("/account/me", headers=bearer(access)).json()
    assert me["email_verified"] is True
    assert me["consent_active"] is True

    first_refresh = client.cookies.get(REFRESH_COOKIE)
    refreshed = client.post("/auth/refresh")
    assert refreshed.status_code == 200
    assert client.cookies.get(REFRESH_COOKIE) != first_refresh
    new_access = refreshed.json()["access_token"]
    assert client.get("/account/me", headers=bearer(new_access)).status_code == 200
    assert client.get("/account/me", headers=bearer(access)).status_code == 401


def test_refresh_token_reuse_revokes_the_whole_family(client: TestClient, live_settings: Settings) -> None:
    signup(client, EMAIL)
    login(client, EMAIL)
    stolen = client.cookies.get(REFRESH_COOKIE)
    rotated = client.post("/auth/refresh")
    good_access = rotated.json()["access_token"]
    good_refresh = client.cookies.get(REFRESH_COOKIE)

    client.cookies.set(REFRESH_COOKIE, stolen or "", path="/auth")
    assert client.post("/auth/refresh").status_code == 400

    assert client.get("/account/me", headers=bearer(good_access)).status_code == 401
    client.cookies.set(REFRESH_COOKIE, good_refresh or "", path="/auth")
    assert client.post("/auth/refresh").status_code == 400
    actions = [r.action for r in owner_sql(live_settings, "SELECT action FROM audit_log")]
    assert "refresh_token_reuse_detected" in actions


def test_duplicate_signup_looks_identical_and_sends_one_email(client: TestClient) -> None:
    signup(client, EMAIL)
    signup(client, EMAIL)
    assert sum(m.kind == "verify_email" for m in mailbox(client).messages) == 1


def test_wrong_password_and_unknown_email_get_the_same_answer(client: TestClient) -> None:
    signup(client, EMAIL)
    wrong = client.post("/auth/login", json={"email": EMAIL, "password": "not-the-password"})
    unknown = client.post("/auth/login", json={"email": "nobody@example.in", "password": "not-the-password"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_email_is_case_insensitive(client: TestClient) -> None:
    signup(client, EMAIL)
    login(client, EMAIL.upper())


def test_old_consent_version_is_refused(client: TestClient) -> None:
    body = {"email": EMAIL, "password": PASSWORD, "consent_notice_version": "2020-01-v0"}
    assert client.post("/auth/signup", json=body).status_code == 409


def test_weak_password_is_refused(client: TestClient) -> None:
    body = {"email": EMAIL, "password": "short", "consent_notice_version": CURRENT_NOTICE_VERSION}
    response = client.post("/auth/signup", json=body)
    assert response.status_code == 422
    assert response.json()["error"] == "weak_password"


def test_account_locks_after_repeated_failures(client: TestClient) -> None:
    signup(client, EMAIL)
    for _ in range(LOGIN_FAILURES_PER_ACCOUNT.capacity):
        assert client.post("/auth/login", json={"email": EMAIL, "password": "wrong-password-x"}).status_code == 401
    locked = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) >= 1


def test_login_is_rate_limited_per_ip(client: TestClient) -> None:
    body = {"email": "nobody@example.in", "password": "whatever-password"}
    codes = [client.post("/auth/login", json=body).status_code for _ in range(LOGIN_PER_IP.capacity + 1)]
    assert codes[:-1] == [401] * LOGIN_PER_IP.capacity
    assert codes[-1] == 429


def test_password_reset_revokes_sessions_and_token_is_single_use(client: TestClient) -> None:
    signup(client, EMAIL)
    old_access = login(client, EMAIL)
    assert client.post("/auth/password-reset/request", json={"email": EMAIL}).status_code == 202
    token = last_token(client, "reset_password")
    body = {"token": token, "new_password": "a-brand-new-passphrase"}
    assert client.post("/auth/password-reset/confirm", json=body).status_code == 200
    assert client.get("/account/me", headers=bearer(old_access)).status_code == 401
    assert client.post("/auth/password-reset/confirm", json=body).status_code == 400
    assert client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 401
    login(client, EMAIL, "a-brand-new-passphrase")


def test_reset_request_for_unknown_email_is_silent(client: TestClient) -> None:
    assert client.post("/auth/password-reset/request", json={"email": "nobody@example.in"}).status_code == 202
    assert len(mailbox(client).messages) == 0


def test_verification_link_works_once(client: TestClient) -> None:
    signup(client, EMAIL)
    token = last_token(client, "verify_email")
    assert client.post("/auth/verify-email", json={"token": token}).status_code == 200
    assert client.post("/auth/verify-email", json={"token": token}).status_code == 400


def test_logout_kills_access_and_refresh(client: TestClient) -> None:
    signup(client, EMAIL)
    access = login(client, EMAIL)
    refresh_cookie = client.cookies.get(REFRESH_COOKIE)
    assert client.post("/auth/logout", headers=bearer(access)).status_code == 204
    assert client.get("/account/me", headers=bearer(access)).status_code == 401
    client.cookies.set(REFRESH_COOKIE, refresh_cookie or "", path="/auth")
    assert client.post("/auth/refresh").status_code == 400


@pytest.mark.parametrize("header", [{}, {"Authorization": "Bearer not-a-jwt"}, {"Authorization": "Basic abc"}])
def test_protected_routes_need_a_valid_token(client: TestClient, header: dict[str, str]) -> None:
    assert client.get("/account/me", headers=header).status_code == 401


def test_consent_can_be_withdrawn(client: TestClient) -> None:
    signup(client, EMAIL)
    access = login(client, EMAIL)
    assert client.post("/account/consent/withdraw", headers=bearer(access)).status_code == 200
    assert client.get("/account/me", headers=bearer(access)).json()["consent_active"] is False


def test_export_contains_my_data_and_no_secrets(client: TestClient) -> None:
    signup(client, EMAIL)
    access = login(client, EMAIL)
    response = client.get("/account/export", headers=bearer(access))
    assert response.status_code == 200
    assert "attachment" in response.headers["Content-Disposition"]
    data = response.json()
    assert data["format_version"] == 1
    assert data["profile"][0]["email"] == EMAIL
    assert data["consents"][0]["notice_version"] == CURRENT_NOTICE_VERSION
    assert len(data["sessions"]) == 1
    assert {"signup", "login"} <= {row["action"] for row in data["audit_log"]}
    assert "argon2" not in response.text
    assert "password_hash" not in response.text
    assert "refresh_token_hash" not in response.text
