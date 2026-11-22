from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from vapas.config import Settings
from vapas.ingest.model import FileKind
from vapas.jobs.context import WorkerContext
from vapas.jobs.detection import today_ist
from vapas.privacy.notices import CURRENT_NOTICE_VERSION

from .conftest import bearer, owner_sql, upload, verified_user
from .test_cases_flow import post, ready_case
from .test_findings_flow import statement_csv

pytestmark = pytest.mark.integration


def test_locale_is_saved_and_validated(client: TestClient) -> None:
    token = verified_user(client, "asha@example.in")
    assert client.post("/account/locale", headers=bearer(token), json={"locale": "hi"}).status_code == 200
    assert client.get("/account/me", headers=bearer(token)).json()["locale"] == "hi"
    assert client.post("/account/locale", headers=bearer(token), json={"locale": "fr"}).status_code == 422
    assert client.get("/account/me", headers=bearer(token)).json()["locale"] == "hi"
    assert client.post("/account/locale", json={"locale": "en"}).status_code == 401


def test_consent_can_be_given_again_after_withdrawal(client: TestClient, live_settings: Settings) -> None:
    token = verified_user(client, "asha@example.in")
    data = statement_csv([(today_ist() - timedelta(days=5), "UPI/123456789012/SHOP", 10_000, 0)])
    assert client.post("/account/consent/withdraw", headers=bearer(token)).status_code == 200
    body = {"sha256": "a" * 64, "size_bytes": len(data), "file_kind": FileKind.CSV.value}
    assert client.post("/statements/presign", headers=bearer(token), json=body).status_code == 403

    stale = client.post("/account/consent", headers=bearer(token), json={"notice_version": "2020-01-v0"})
    assert (stale.status_code, stale.json()["error"]) == (409, "consent_notice_changed")
    assert client.get("/account/me", headers=bearer(token)).json()["consent_active"] is False

    given = client.post("/account/consent", headers=bearer(token), json={"notice_version": CURRENT_NOTICE_VERSION})
    assert given.status_code == 200
    again = client.post("/account/consent", headers=bearer(token), json={"notice_version": CURRENT_NOTICE_VERSION})
    assert again.status_code == 200
    assert client.get("/account/me", headers=bearer(token)).json()["consent_active"] is True
    upload(client, token, data, FileKind.CSV)

    user_id = client.get("/account/me", headers=bearer(token)).json()["id"]
    active = owner_sql(
        live_settings,
        "SELECT count(*) AS n FROM consents WHERE user_id = :u AND withdrawn_at IS NULL",
        {"u": user_id},
    )
    assert active[0].n == 1
    actions = owner_sql(live_settings, "SELECT action FROM audit_log WHERE user_id = :u", {"u": user_id})
    assert [r.action for r in actions].count("consent_given") == 1


def test_recovered_amount_needs_a_sent_case_and_a_past_date(
    client: TestClient, live_settings: Settings, worker: WorkerContext
) -> None:
    token = verified_user(client, "asha@example.in")
    case_id, _ = ready_case(client, token, worker)
    path = f"/cases/{case_id}/recovered"
    today = today_ist().isoformat()

    early = post(client, token, path, {"amount_paise": 70_000, "on": today})
    assert (early.status_code, early.json()["detail"]["code"]) == (409, "invalid_state")

    sent_on = (today_ist() - timedelta(days=3)).isoformat()
    assert post(client, token, f"/cases/{case_id}/sent", {"on": sent_on}).status_code == 200
    future = post(client, token, path, {"amount_paise": 70_000, "on": (today_ist() + timedelta(days=1)).isoformat()})
    assert (future.status_code, future.json()["detail"]["code"]) == (422, "date_in_future")
    assert post(client, token, path, {"amount_paise": 0, "on": today}).status_code == 422

    done = post(client, token, path, {"amount_paise": 70_000, "on": today})
    assert done.status_code == 200, done.text
    assert (done.json()["recovered_paise"], done.json()["recovered_on"]) == (70_000, today)
    events = client.get(f"/cases/{case_id}", headers=bearer(token)).json()["events"]
    assert events[-1]["type"] == "recovered"
    listed = client.get("/cases", headers=bearer(token)).json()
    assert [c["recovered_paise"] for c in listed] == [70_000]

    bilal = verified_user(client, "bilal@example.in")
    assert post(client, bilal, path, {"amount_paise": 1, "on": today}).status_code == 404
    owner_sql(live_settings, "UPDATE jobs SET locked_by = NULL")


def test_cors_allows_only_the_app_origin(client: TestClient, live_settings: Settings) -> None:
    preflight = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization"}
    allowed = client.options("/auth/login", headers={"Origin": live_settings.public_app_url, **preflight})
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == live_settings.public_app_url
    assert allowed.headers["access-control-allow-credentials"] == "true"

    denied = client.options("/auth/login", headers={"Origin": "https://evil.example", **preflight})
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers
    plain = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in plain.headers
