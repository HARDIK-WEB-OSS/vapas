import asyncio
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from vapas.config import Settings
from vapas.ingest.model import FileKind
from vapas.jobs.case_work import process_case_work
from vapas.jobs.context import WorkerContext
from vapas.jobs.detection import today_ist
from vapas.mail.sender import CapturingEmailSender

from .conftest import bearer, confirm, drain, owner_sql, upload, verified_user
from .test_findings_flow import statement_csv
from .test_rls_isolation import attempt

pytestmark = pytest.mark.integration

FIELDS = {"customer_name": "Asha Rao", "account_hint": "1234", "contact": "asha@example.in"}


def findings_for(client: TestClient, token: str, worker: WorkerContext) -> list[dict[str, Any]]:
    start = today_ist() - timedelta(days=90)
    data = statement_csv(
        [
            (start, "ATM WDL/412345678901/PUNE", 200_000, 0),
            (start + timedelta(days=12), "REV ATM WDL 412345678901 PUNE", 0, 200_000),
            (start + timedelta(days=20), "POS 4321XXXX1234 BIGBASKET", 45_000, 0),
            (start + timedelta(days=20), "POS 4321XXXX1234 BIGBASKET", 45_000, 0),
        ]
    )
    sid = upload(client, token, data, FileKind.CSV)["statement_id"]
    confirm(client, token, sid)
    drain(worker)
    items: list[dict[str, Any]] = client.get("/findings", headers=bearer(token)).json()
    return items


def post(client: TestClient, token: str, path: str, body: dict[str, Any]) -> Any:
    return client.post(path, headers=bearer(token), json=body)


def ready_case(client: TestClient, token: str, worker: WorkerContext) -> tuple[str, list[dict[str, Any]]]:
    found = findings_for(client, token, worker)
    ids = [f["id"] for f in found if f["level"] in ("claim", "worth_checking")]
    created = post(client, token, "/cases", {"finding_ids": ids})
    assert created.status_code == 201, created.text
    case_id: str = created.json()["id"]
    letter = post(client, token, f"/cases/{case_id}/letters", {"kind": "bank"}).json()
    assert post(client, token, f"/cases/{case_id}/letters/{letter['id']}/approve", FIELDS).status_code == 200
    return case_id, found


def test_case_lifecycle_letters_and_escalation(
    client: TestClient, live_settings: Settings, worker: WorkerContext
) -> None:
    token = verified_user(client, "asha@example.in")
    found = findings_for(client, token, worker)
    claim = next(f for f in found if f["level"] == "claim")
    duplicate = next(f for f in found if f["detector"] == "duplicate")
    created = post(client, token, "/cases", {"finding_ids": [claim["id"], duplicate["id"]]})
    assert created.status_code == 201, created.text
    case_id = created.json()["id"]
    assert (created.json()["state"], created.json()["bank_code"]) == ("draft", "SBI")
    again = post(client, token, "/cases", {"finding_ids": [claim["id"]]})
    assert (again.status_code, again.json()["detail"]["code"]) == (409, "already_in_case")

    assert post(client, token, f"/cases/{case_id}/sent", {"on": today_ist().isoformat()}).status_code == 409
    letter = post(client, token, f"/cases/{case_id}/letters", {"kind": "bank"}).json()
    assert "Annex Sl. 1(a) of RBI circular DPSS.CO.PD No.629/02.01.014/2019-20" in letter["text"]
    assert "comes to Rs 700" in letter["text"]
    assert "Please check this transaction" in letter["text"]
    assert "[YOUR FULL NAME]" in letter["text"]
    approved = post(client, token, f"/cases/{case_id}/letters/{letter['id']}/approve", FIELDS)
    assert approved.status_code == 200, approved.text
    assert "Asha Rao" in approved.json()["text"]

    received_on = today_ist() - timedelta(days=40)
    assert post(client, token, f"/cases/{case_id}/sent", {"on": received_on.isoformat()}).status_code == 200
    case = post(client, token, f"/cases/{case_id}/received", {"on": received_on.isoformat()}).json()
    assert case["state"] == "escalation_eligible"
    assert case["filing_deadline_on"] == (received_on + timedelta(days=120)).isoformat()
    assert case["days_left"] == 80

    assert (
        post(
            client,
            token,
            f"/cases/{case_id}/escalate",
            {"filed_on": today_ist().isoformat(), "already_with_ombudsman": False, "in_court_or_other_forum": False},
        ).status_code
        == 409
    )
    cms = post(client, token, f"/cases/{case_id}/letters", {"kind": "cms"}).json()
    assert "RBI Ombudsman" in cms["text"]
    assert post(client, token, f"/cases/{case_id}/letters/{cms['id']}/approve", FIELDS).status_code == 200
    blocked = post(
        client,
        token,
        f"/cases/{case_id}/escalate",
        {"filed_on": today_ist().isoformat(), "already_with_ombudsman": True, "in_court_or_other_forum": False},
    )
    assert (blocked.status_code, blocked.json()["detail"]["code"]) == (409, "blocked_clause_10")
    done = post(
        client,
        token,
        f"/cases/{case_id}/escalate",
        {"filed_on": today_ist().isoformat(), "already_with_ombudsman": False, "in_court_or_other_forum": False},
    )
    assert done.json()["state"] == "escalated"

    detail = client.get(f"/cases/{case_id}", headers=bearer(token)).json()
    assert [e["type"] for e in detail["events"]] == [
        "created",
        "letter_drafted",
        "letter_approved",
        "sent_to_bank",
        "awaiting_reply",
        "deadline_set",
        "escalation_eligible",
        "letter_drafted",
        "letter_approved",
        "escalated",
    ]
    pdf = client.get(f"/cases/{case_id}/evidence.pdf", headers=bearer(token))
    assert (pdf.status_code, pdf.headers["content-type"], pdf.content[:5]) == (200, "application/pdf", b"%PDF-")

    user_id = client.get("/account/me", headers=bearer(token)).json()["id"]
    assert "permission denied" in attempt(live_settings, user_id, "UPDATE case_events SET type = 'forged'")
    assert "permission denied" in attempt(live_settings, user_id, "DELETE FROM case_events")
    bilal = verified_user(client, "bilal@example.in")
    assert client.get(f"/cases/{case_id}", headers=bearer(bilal)).status_code == 404
    owner_sql(live_settings, "UPDATE jobs SET locked_by = NULL")


def test_missed_window_expires_the_case(client: TestClient, live_settings: Settings, worker: WorkerContext) -> None:
    token = verified_user(client, "asha@example.in")
    case_id, _ = ready_case(client, token, worker)
    received_on = today_ist() - timedelta(days=125)
    post(client, token, f"/cases/{case_id}/sent", {"on": received_on.isoformat()})
    case = post(client, token, f"/cases/{case_id}/received", {"on": received_on.isoformat()}).json()
    if received_on < date(2026, 7, 1):
        assert (case["state"], case["filing_deadline_on"]) == ("awaiting_reply", None)
    else:
        assert (case["state"], case["days_left"]) == ("expired", None)
    owner_sql(live_settings, "UPDATE jobs SET locked_by = NULL")


def test_worker_ticks_cases_and_sends_reminders(
    client: TestClient, live_settings: Settings, worker_settings: Settings, worker: WorkerContext
) -> None:
    token = verified_user(client, "asha@example.in")
    case_id, _ = ready_case(client, token, worker)
    received_on = today_ist() - timedelta(days=10)
    post(client, token, f"/cases/{case_id}/sent", {"on": received_on.isoformat()})
    case = post(client, token, f"/cases/{case_id}/received", {"on": received_on.isoformat()}).json()
    assert case["state"] == "awaiting_reply"
    kinds = {r.kind for r in owner_sql(live_settings, "SELECT kind FROM reminders WHERE case_id = :c", {"c": case_id})}
    assert kinds == {"eligible", "d30", "d7", "d1"}

    earlier = today_ist() - timedelta(days=35)
    owner_sql(
        live_settings,
        "UPDATE cases SET bank_received_on = :d, sent_on = :d WHERE id = :c",
        {"d": earlier, "c": case_id},
    )
    owner_sql(
        live_settings,
        "UPDATE reminders SET due_on = :d WHERE case_id = :c AND kind = 'eligible'",
        {"d": today_ist(), "c": case_id},
    )

    async def run() -> tuple[int, CapturingEmailSender]:
        ctx = WorkerContext.from_settings(worker_settings)
        try:
            count = await process_case_work(ctx)
            assert isinstance(ctx.mailer, CapturingEmailSender)
            return count, ctx.mailer
        finally:
            await ctx.close()

    handled, mailer = asyncio.run(run())
    assert handled >= 2
    assert client.get(f"/cases/{case_id}", headers=bearer(token)).json()["state"] == "escalation_eligible"
    assert any("cms.rbi.org.in" in m.body and m.to == "asha@example.in" for m in mailer.messages)
    banners = client.get("/notifications", params={"unread_only": True}, headers=bearer(token)).json()
    assert any(n["kind"] == "eligible" for n in banners)
    assert client.post(f"/notifications/{banners[0]['id']}/read", headers=bearer(token)).status_code == 204
    sent = owner_sql(
        live_settings, "SELECT sent_at FROM reminders WHERE case_id = :c AND kind = 'eligible'", {"c": case_id}
    )
    assert sent
    assert sent[0].sent_at is not None
    owner_sql(live_settings, "UPDATE jobs SET locked_by = NULL")
