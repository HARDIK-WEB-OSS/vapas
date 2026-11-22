import asyncio
import dataclasses
import logging
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from vapas.config import Settings
from vapas.ingest.model import FileKind
from vapas.jobs.case_work import REMINDER_ALERT_AFTER_ATTEMPTS, process_case_work
from vapas.jobs.context import WorkerContext
from vapas.jobs.detection import today_ist
from vapas.llm_gateway.gateway import LlmGateway
from vapas.mail.sender import EmailMessage, EmailSender, EmailSendError
from vapas.main import create_app
from vapas.synthetic.generator import expected_rows, generate, render_pdf

from .conftest import bearer, confirm, drain, login, owner_sql, upload, verified_user
from .test_cases_flow import post, ready_case
from .test_statement_pipeline import decrypted_narrations, statement

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[2]
CLOSED_PORT_URL = "redis://127.0.0.1:6390/0"
KILL_WAIT_SECONDS = 30.0


class DownMailer:
    async def send(self, message: EmailMessage) -> None:
        raise EmailSendError("email provider unreachable: ConnectError")


class DownModel:
    name = "down"

    def __init__(self) -> None:
        self.calls = 0

    async def complete_json(self, prompt: str) -> str:
        self.calls += 1
        raise ValueError("connection refused")


def _job_running(settings: Settings, statement_id: str) -> bool:
    rows = owner_sql(
        settings,
        "SELECT state, locked_by FROM jobs WHERE queue = 'parse' AND payload->>'statement_id' = :s",
        {"s": statement_id},
    )
    return bool(rows) and rows[0].state == "running" and rows[0].locked_by is not None


@pytest.fixture
def worker_process(worker_settings: Settings) -> Iterator[subprocess.Popen[bytes]]:
    env = {
        **os.environ,
        "DATABASE_URL": worker_settings.database_url.get_secret_value(),
        "REDIS_URL": worker_settings.redis_url.get_secret_value(),
        "WORKER_POLL_SECONDS": "0.1",
        "MAIL_BACKEND": "capture",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "vapas.jobs.worker"],
        cwd=BACKEND_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    yield process
    if process.poll() is None:
        process.kill()
        process.wait()


def test_worker_process_killed_mid_statement_is_redone_cleanly(
    client: TestClient,
    live_settings: Settings,
    worker: WorkerContext,
    worker_process: subprocess.Popen[bytes],
) -> None:
    token = verified_user(client, "asha@example.in")
    synthetic = generate("SBI", 77, count=400)
    sid = upload(client, token, render_pdf(synthetic), FileKind.PDF)["statement_id"]
    confirm(client, token, sid)
    deadline = time.monotonic() + KILL_WAIT_SECONDS
    while not _job_running(live_settings, sid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert _job_running(live_settings, sid), "the worker process never claimed the parse job"
    worker_process.kill()
    worker_process.wait()

    assert statement(client, token, sid)["status"] in ("queued", "parsing")
    rows = owner_sql(live_settings, "SELECT count(*) AS n FROM transactions WHERE statement_id = :s", {"s": sid})
    assert rows[0].n == 0
    owner_sql(live_settings, "UPDATE jobs SET locked_until = now() - interval '1 second' WHERE state = 'running'")
    drain(worker)

    assert statement(client, token, sid)["status"] == "parsed"
    user_id = client.get("/account/me", headers=bearer(token)).json()["id"]
    assert decrypted_narrations(live_settings, user_id, sid) == [r.narration for r in expected_rows(synthetic)]
    jobs = owner_sql(
        live_settings,
        "SELECT attempts, state FROM jobs WHERE queue = 'parse' AND payload->>'statement_id' = :s",
        {"s": sid},
    )
    assert [(r.attempts, r.state) for r in jobs] == [(2, "done")]
    owner_sql(live_settings, "UPDATE jobs SET locked_by = NULL")


def test_redis_down_auth_fails_closed_and_reads_keep_working(client: TestClient, live_settings: Settings) -> None:
    token = verified_user(client, "asha@example.in")
    broken = live_settings.model_copy(update={"redis_url": SecretStr(CLOSED_PORT_URL)})
    with TestClient(create_app(broken)) as degraded:
        refused = degraded.post("/auth/login", json={"email": "asha@example.in", "password": "x" * 12})
        assert (refused.status_code, refused.json()["error"]) == (503, "temporarily_unavailable")
        assert degraded.get("/account/me", headers=bearer(token)).status_code == 200
        assert degraded.get("/findings", headers=bearer(token)).status_code == 200
        ready = degraded.get("/ready")
        assert ready.status_code == 503
        assert ready.json()["checks"]["redis"] is False
    assert login(client, "asha@example.in")


def test_object_store_down_confirm_says_try_again(client: TestClient, live_settings: Settings) -> None:
    token = verified_user(client, "asha@example.in")
    data = b"Txn Date,Description,Debit,Credit,Balance\n"
    sid = upload(client, token, data, FileKind.CSV)["statement_id"]
    broken = live_settings.model_copy(update={"s3_endpoint_url": "http://127.0.0.1:8399"})
    with TestClient(create_app(broken)) as degraded:
        response = confirm(degraded, token, sid)
        assert (response.status_code, response.json()["detail"]) == (503, "temporarily_unavailable")
        assert degraded.get("/ready").json()["checks"]["object_store"] is False
    assert statement(client, token, sid)["status"] == "awaiting_upload"
    assert confirm(client, token, sid).status_code == 202


def test_llm_provider_down_sends_unknown_layouts_to_review(
    client: TestClient, worker_settings: Settings, live_settings: Settings
) -> None:
    model = DownModel()
    gateway = LlmGateway(model, daily_limit=6)
    ctx = WorkerContext.from_settings(worker_settings, gateway=gateway)
    asyncio.run(ctx.close())
    token = verified_user(client, "asha@example.in")
    codes = []
    for index in range(4):
        data = f"When,What,Out,In,Left\n0{index + 1}/04/2025,SHOP,250.00,,750.00\n".encode()
        sid = upload(client, token, data, FileKind.CSV)["statement_id"]
        confirm(client, token, sid)
        drain(ctx)
        result = statement(client, token, sid)
        codes.append((result["status"], result["failure_code"]))
    assert {status for status, _ in codes} == {"needs_review"}
    assert model.calls == 3
    assert not gateway.available
    owner_sql(live_settings, "UPDATE jobs SET locked_by = NULL")


def test_email_down_reminders_show_in_app_retry_and_alert(
    client: TestClient,
    live_settings: Settings,
    worker_settings: Settings,
    worker: WorkerContext,
    caplog: pytest.LogCaptureFixture,
) -> None:
    token = verified_user(client, "asha@example.in")
    case_id, _ = ready_case(client, token, worker)
    received_on = today_ist() - timedelta(days=35)
    post(client, token, f"/cases/{case_id}/sent", {"on": received_on.isoformat()})
    post(client, token, f"/cases/{case_id}/received", {"on": received_on.isoformat()})
    reminder = "SELECT attempts, sent_at FROM reminders WHERE case_id = :c AND kind = 'eligible'"

    def tick(mailer: EmailSender) -> None:
        async def run() -> None:
            ctx = dataclasses.replace(WorkerContext.from_settings(worker_settings), mailer=mailer)
            try:
                await process_case_work(ctx)
            finally:
                await ctx.close()

        asyncio.run(run())

    tick(DownMailer())
    banners = client.get("/notifications", params={"unread_only": True}, headers=bearer(token)).json()
    assert any(n["kind"] == "eligible" for n in banners)
    first = owner_sql(live_settings, reminder, {"c": case_id})[0]
    assert (first.attempts, first.sent_at) == (1, None)

    owner_sql(
        live_settings,
        "UPDATE reminders SET attempts = :a WHERE case_id = :c AND kind = 'eligible'",
        {"a": REMINDER_ALERT_AFTER_ATTEMPTS - 1, "c": case_id},
    )
    with caplog.at_level(logging.ERROR, logger="vapas.jobs.case_work"):
        tick(DownMailer())
    assert any(r.getMessage() == "reminder email still unsent" for r in caplog.records)
    banners_after = client.get("/notifications", params={"unread_only": True}, headers=bearer(token)).json()
    assert len([n for n in banners_after if n["kind"] == "eligible"]) == 1

    tick(worker.mailer)
    sent = owner_sql(live_settings, reminder, {"c": case_id})[0]
    assert sent.sent_at is not None
    owner_sql(live_settings, "UPDATE jobs SET locked_by = NULL")


def test_poison_statement_goes_to_dead_letter_after_max_attempts(
    client: TestClient, worker_settings: Settings, live_settings: Settings
) -> None:
    impatient = worker_settings.model_copy(update={"parse_timeout_seconds": 0.01})
    ctx = WorkerContext.from_settings(impatient, gateway=LlmGateway(None, daily_limit=6))
    asyncio.run(ctx.close())
    token = verified_user(client, "asha@example.in")
    sid = upload(client, token, render_pdf(generate("HDFC", 5, count=200)), FileKind.PDF)["statement_id"]
    confirm(client, token, sid)
    parse_job = "SELECT state, attempts FROM jobs WHERE queue = 'parse' AND payload->>'statement_id' = :s"
    for _ in range(5):
        drain(ctx)
        owner_sql(live_settings, "UPDATE jobs SET run_after = now() WHERE state = 'queued'")
    job = owner_sql(live_settings, parse_job, {"s": sid})[0]
    assert (job.state, job.attempts) == ("dead", 3)
    result = statement(client, token, sid)
    assert result["status"] == "failed"
    owner_sql(live_settings, "UPDATE jobs SET locked_by = NULL")


def test_postgres_down_is_a_clean_503(client: TestClient, live_settings: Settings) -> None:
    token = verified_user(client, "asha@example.in")
    url = live_settings.database_url.get_secret_value().replace(":55433/", ":55499/")
    broken = live_settings.model_copy(update={"database_url": SecretStr(url)})
    with TestClient(create_app(broken), raise_server_exceptions=False) as degraded:
        response = degraded.get("/account/me", headers=bearer(token))
        assert (response.status_code, response.json()["error"]) == (503, "temporarily_unavailable")
        ready = degraded.get("/ready")
        assert (ready.status_code, ready.json()["checks"]["postgres"]) == (503, False)
        assert degraded.get("/health").status_code == 200
