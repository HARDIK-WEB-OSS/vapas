import asyncio
import hashlib
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from dotenv import dotenv_values
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from redis import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from vapas.config import Settings
from vapas.ingest.model import FileKind
from vapas.jobs.context import WorkerContext
from vapas.jobs.worker import run_once
from vapas.llm_gateway.gateway import LlmGateway
from vapas.mail.sender import CapturingEmailSender
from vapas.main import create_app
from vapas.privacy.notices import CURRENT_NOTICE_VERSION

TEST_REDIS_DB = 15
PASSWORD = "statement-audit-2026"
TOKEN_IN_LINK = re.compile(r"#token=(\S+)")


def _test_redis_url(url: str) -> str:
    return url.rsplit("/", 1)[0] + f"/{TEST_REDIS_DB}"


@pytest.fixture(scope="session")
def live_settings() -> Settings:
    settings = Settings()
    redis_url = SecretStr(_test_redis_url(settings.redis_url.get_secret_value()))
    return settings.model_copy(update={"redis_url": redis_url})


def owner_sql(settings: Settings, sql: str, params: dict[str, Any] | None = None) -> list[Any]:
    url = settings.migration_database_url
    assert url is not None
    owner_url = url.get_secret_value()

    async def run() -> list[Any]:
        engine = create_async_engine(owner_url)
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(sql), params or {})
                return list(result.fetchall()) if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(run())


@pytest.fixture(autouse=True)
def clean_state(live_settings: Settings) -> None:
    owner_sql(live_settings, "TRUNCATE users, audit_log, analytics_events, rule_versions RESTART IDENTITY CASCADE")
    Redis.from_url(live_settings.redis_url.get_secret_value()).flushdb()


@pytest.fixture
def client(live_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(live_settings)) as test_client:
        yield test_client


def mailbox(client: TestClient) -> CapturingEmailSender:
    sender = cast(FastAPI, client.app).state.services.mailer
    assert isinstance(sender, CapturingEmailSender)
    return sender


def last_token(client: TestClient, kind: str) -> str:
    message = next(m for m in reversed(mailbox(client).messages) if m.kind == kind)
    match = TOKEN_IN_LINK.search(message.body)
    assert match is not None
    return match.group(1)


def signup(client: TestClient, email: str, password: str = PASSWORD) -> None:
    body = {"email": email, "password": password, "consent_notice_version": CURRENT_NOTICE_VERSION}
    response = client.post("/auth/signup", json=body)
    assert response.status_code == 202, response.text


def login(client: TestClient, email: str, password: str = PASSWORD) -> str:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def user_id_of(client: TestClient, token: str) -> str:
    user_id: str = client.get("/account/me", headers=bearer(token)).json()["id"]
    return user_id


def _env_file() -> dict[str, str | None]:
    root = Path(__file__).resolve().parents[3]
    return dotenv_values(root / ".env")


@pytest.fixture(scope="session")
def worker_settings(live_settings: Settings) -> Settings:
    env = _env_file()
    app_url = live_settings.database_url.get_secret_value()
    worker_url = app_url.replace(f"vapas_app:{env['APP_DB_PASSWORD']}@", f"vapas_worker:{env['WORKER_DB_PASSWORD']}@")
    assert worker_url != app_url
    return live_settings.model_copy(update={"database_url": SecretStr(worker_url)})


def verified_user(client: TestClient, email: str) -> str:
    signup(client, email)
    assert client.post("/auth/verify-email", json={"token": last_token(client, "verify_email")}).status_code == 200
    return login(client, email)


def foreign_job_claims(settings: Settings, worker_id: str) -> list[str]:
    rows = owner_sql(settings, "SELECT DISTINCT locked_by FROM jobs WHERE locked_by IS NOT NULL")
    return [r.locked_by for r in rows if r.locked_by != worker_id]


class FakeModel:
    name = "fake"

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    async def complete_json(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.answer


@pytest.fixture
def worker(worker_settings: Settings, live_settings: Settings) -> Iterator[WorkerContext]:
    ctx = WorkerContext.from_settings(worker_settings, gateway=LlmGateway(None, daily_limit=6))
    yield ctx
    asyncio.run(ctx.close())
    assert foreign_job_claims(live_settings, ctx.worker_id) == [], "stop the compose worker: docker compose stop worker"


def drain(template: WorkerContext, limit: int = 20) -> int:
    async def run() -> int:
        ctx = WorkerContext.from_settings(template.settings, gateway=template.gateway)
        rounds = 0
        try:
            while rounds < limit and await run_once(ctx):
                rounds += 1
        finally:
            await ctx.close()
        return rounds

    return asyncio.run(run())


def upload(client: TestClient, token: str, data: bytes, kind: FileKind, put: bool = True) -> dict[str, Any]:
    body = {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data), "file_kind": kind.value}
    response = client.post("/statements/presign", headers=bearer(token), json=body)
    assert response.status_code == 200, response.text
    out: dict[str, Any] = response.json()
    if put and out["upload_url"]:
        put_response = httpx.put(out["upload_url"], content=data, headers={"Content-Type": out["content_type"]})
        assert put_response.status_code == 200, put_response.text
    return out


def confirm(client: TestClient, token: str, statement_id: str, password: str | None = None) -> httpx.Response:
    body = {"password": password} if password else {}
    response: httpx.Response = client.post(f"/statements/{statement_id}/confirm", headers=bearer(token), json=body)
    return response
