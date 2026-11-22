import asyncio
from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from vapas.analytics.impact import Impact, Window, compute_impact, render_markdown
from vapas.auth.invites import invite_code_hash
from vapas.config import Settings
from vapas.jobs.context import WorkerContext
from vapas.jobs.detection import today_ist
from vapas.main import create_app
from vapas.privacy.notices import CURRENT_NOTICE_VERSION

from .conftest import PASSWORD, bearer, fresh_client_address, last_token, owner_sql, verified_user
from .test_cases_flow import findings_for, post
from .test_rls_isolation import attempt

pytestmark = pytest.mark.integration

INVITE = "ABCD-EFGH-JKMN-PQRS"


@pytest.fixture
def invite_client(live_settings: Settings) -> Iterator[TestClient]:
    with TestClient(
        create_app(live_settings.model_copy(update={"invite_only": True})), client=fresh_client_address()
    ) as test_client:
        yield test_client


def add_invite(settings: Settings, code: str, max_uses: int = 1, expires_in_days: int = 30) -> None:
    owner_sql(
        settings,
        "INSERT INTO invite_codes (id, code_hash, cohort, max_uses, expires_at) "
        "VALUES (:id, :h, 'friends', :m, now() + make_interval(days => :d))",
        {"id": uuid4(), "h": invite_code_hash(code), "m": max_uses, "d": expires_in_days},
    )


def signup_with(client: TestClient, email: str, code: str | None) -> Any:
    body = {"email": email, "password": PASSWORD, "consent_notice_version": CURRENT_NOTICE_VERSION}
    if code is not None:
        body["invite_code"] = code
    return client.post("/auth/signup", json=body)


def test_invite_only_signup(invite_client: TestClient, live_settings: Settings) -> None:
    add_invite(live_settings, INVITE)
    add_invite(live_settings, "ZZZZ-ZZZZ-ZZZZ-ZZZZ", expires_in_days=-1)
    missing = signup_with(invite_client, "asha@example.in", None)
    assert (missing.status_code, missing.json()["error"]) == (400, "invalid_invite")
    assert signup_with(invite_client, "asha@example.in", "WRONG-CODE").status_code == 400
    assert signup_with(invite_client, "asha@example.in", "zzzz zzzz zzzz zzzz").status_code == 400

    assert signup_with(invite_client, "asha@example.in", "abcd efgh jkmn pqrs").status_code == 202
    verified = invite_client.post("/auth/verify-email", json={"token": last_token(invite_client, "verify_email")})
    assert verified.status_code == 200
    used_up = signup_with(invite_client, "bilal@example.in", INVITE)
    assert (used_up.status_code, used_up.json()["error"]) == (400, "invalid_invite")

    rows = owner_sql(
        live_settings, "SELECT u.email, i.cohort FROM users u JOIN invite_codes i ON i.id = u.invite_id ORDER BY 1"
    )
    assert [(r.email, r.cohort) for r in rows] == [("asha@example.in", "friends")]
    assert (
        owner_sql(
            live_settings, "SELECT used_count FROM invite_codes WHERE code_hash = :h", {"h": invite_code_hash(INVITE)}
        )[0].used_count
        == 1
    )


def test_open_signup_ignores_invite_codes(client: TestClient) -> None:
    assert signup_with(client, "asha@example.in", None).status_code == 202


def test_app_role_cannot_read_invite_codes(client: TestClient, live_settings: Settings) -> None:
    add_invite(live_settings, INVITE)
    token = verified_user(client, "asha@example.in")
    user_id = client.get("/account/me", headers=bearer(token)).json()["id"]
    assert "permission denied" in attempt(live_settings, user_id, "SELECT * FROM invite_codes")


def test_feedback_per_finding_export_and_isolation(
    client: TestClient, live_settings: Settings, worker: WorkerContext
) -> None:
    token = verified_user(client, "asha@example.in")
    found = findings_for(client, token, worker)
    claim = next(f for f in found if f["level"] == "claim")
    path = f"/findings/{claim['id']}/feedback"
    assert post(client, token, path, {"verdict": "maybe"}).status_code == 422
    assert post(client, token, path, {"verdict": "correct"}).json() == {"status": "correct"}
    assert post(client, token, path, {"verdict": "wrong"}).status_code == 200
    listed = {f["id"]: f["feedback"] for f in client.get("/findings", headers=bearer(token)).json()}
    assert listed[claim["id"]] == "wrong"
    assert sum(1 for value in listed.values() if value is not None) == 1

    bilal = verified_user(client, "bilal@example.in")
    assert post(client, bilal, path, {"verdict": "correct"}).status_code == 404
    bilal_id = client.get("/account/me", headers=bearer(bilal)).json()["id"]
    rows = owner_sql(live_settings, "SELECT count(*) AS n FROM finding_feedback")
    assert rows[0].n == 1
    assert "permission denied" in attempt(live_settings, bilal_id, "DELETE FROM finding_feedback")

    export = client.get("/account/export", headers=bearer(token)).json()
    assert export["format_version"] == 2
    assert export["finding_feedback"][0]["verdict"] == "wrong"
    exported_claim = next(f for f in export["findings"] if f["id"] == claim["id"])
    assert exported_claim["snapshot"]
    assert "snapshot_enc" not in exported_claim
    for key in ("cases", "letters", "case_events", "user_inputs", "reminders", "notifications"):
        assert key in export

    response = client.request("DELETE", "/account", headers=bearer(token), json={"password": PASSWORD})
    assert response.status_code == 204
    assert owner_sql(live_settings, "SELECT count(*) AS n FROM finding_feedback")[0].n == 0
    owner_sql(live_settings, "UPDATE jobs SET locked_by = NULL")


def impact_now(settings: Settings) -> tuple[Impact, Impact]:
    url = settings.migration_database_url
    assert url is not None
    monday = today_ist() - timedelta(days=today_ist().weekday())

    async def run() -> tuple[Impact, Impact]:
        engine = create_async_engine(url.get_secret_value())
        try:
            async with engine.connect() as conn:
                week = await compute_impact(conn, Window.week_from(monday))
                total = await compute_impact(conn, Window.to_date(Window.week_from(monday).end))
                return week, total
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_impact_report_on_synthetic_data(client: TestClient, live_settings: Settings, worker: WorkerContext) -> None:
    token = verified_user(client, "asha@example.in")
    verified_user(client, "bilal@example.in")
    found = findings_for(client, token, worker)
    claim = next(f for f in found if f["level"] == "claim")
    worth = next(f for f in found if f["level"] == "worth_checking")
    post(client, token, f"/findings/{claim['id']}/feedback", {"verdict": "correct"})
    post(client, token, f"/findings/{worth['id']}/feedback", {"verdict": "not_sure"})
    case = post(client, token, "/cases", {"finding_ids": [claim["id"]]}).json()
    letter = post(client, token, f"/cases/{case['id']}/letters", {"kind": "bank"}).json()
    fields = {"customer_name": "Asha Rao", "account_hint": "1234", "contact": "asha@example.in"}
    post(client, token, f"/cases/{case['id']}/letters/{letter['id']}/approve", fields)
    post(client, token, f"/cases/{case['id']}/sent", {"on": today_ist().isoformat()})
    post(client, token, f"/cases/{case['id']}/recovered", {"amount_paise": 70_000, "on": today_ist().isoformat()})

    week, total = impact_now(live_settings)
    assert (week.users_total, week.users_new, week.users_active) == (2, 2, 1)
    assert (week.statements_processed, week.statements_parsed, week.statements_reconciled) == (1, 1, 1)
    assert week.reconciled_share == 1.0
    assert week.findings_by_level["claim"] >= 1
    assert week.paise_found == sum(f["amount_owed_paise"] or 0 for f in found if f["level"] == "claim")
    assert week.paise_recovered == 70_000
    assert week.cases_created == 1
    assert (week.claim_precision.correct, week.claim_precision.wrong) == (1, 0)
    assert week.worth_checking_precision.not_sure == 1
    assert total.paise_recovered == 70_000

    report = render_markdown(week, total, "synthetic test data")
    assert "Rs 700" in report
    assert "synthetic test data" in report
    for secret in ("asha", "bilal", "Asha Rao", "1234"):
        assert secret not in report
    owner_sql(live_settings, "UPDATE jobs SET locked_by = NULL")
