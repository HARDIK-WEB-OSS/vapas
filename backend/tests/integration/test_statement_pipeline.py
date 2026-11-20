import asyncio
import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient

from vapas.classify.channel_rules import CLASSIFIER_VERSION, classify
from vapas.config import Settings
from vapas.ingest.model import FileKind
from vapas.jobs.context import WorkerContext
from vapas.jobs.maintenance import sweep_raw_files
from vapas.jobs.worker import run_once
from vapas.llm_gateway.gateway import LlmGateway
from vapas.security.crypto import FieldCipher, WrappedKey
from vapas.security.user_keys import NARRATION, take_pdf_password, user_cipher
from vapas.storage.object_store import create_s3_client
from vapas.synthetic.generator import expected_rows, generate, render_csv, render_pdf

from .conftest import bearer, foreign_job_claims, login, owner_sql, signup, verified_user

pytestmark = pytest.mark.integration


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


def statement(client: TestClient, token: str, statement_id: str) -> dict[str, Any]:
    response = client.get(f"/statements/{statement_id}", headers=bearer(token))
    assert response.status_code == 200
    result: dict[str, Any] = response.json()
    return result


def raw_exists(settings: Settings, statement_id: str) -> bool:
    key = owner_sql(settings, "SELECT object_key FROM statements WHERE id = :i", {"i": statement_id})[0].object_key
    listing = create_s3_client(settings).list_objects_v2(Bucket=settings.s3_bucket_raw, Prefix=key)
    return bool(listing.get("Contents"))


def decrypted_narrations(settings: Settings, user_id: str, statement_id: str) -> list[str]:
    key_row = owner_sql(settings, "SELECT wrapped_dek, kek_version FROM user_keys WHERE user_id = :u", {"u": user_id})[
        0
    ]
    user = UUID(user_id)
    dek = settings.key_ring().unwrap(WrappedKey(key_row.kek_version, bytes(key_row.wrapped_dek)), user)
    cipher = FieldCipher(dek, user)
    rows = owner_sql(
        settings,
        "SELECT narration_enc FROM transactions WHERE statement_id = :s ORDER BY row_index",
        {"s": statement_id},
    )
    return [cipher.decrypt(bytes(r.narration_enc), NARRATION) for r in rows]


def test_upload_parse_store_encrypted_and_delete_raw(
    client: TestClient, live_settings: Settings, worker: WorkerContext
) -> None:
    token = verified_user(client, "asha@example.in")
    synthetic = generate("HDFC", 11, count=45)
    data = render_pdf(synthetic)
    presigned = upload(client, token, data, FileKind.PDF)
    sid = presigned["statement_id"]
    assert presigned["duplicate"] is False
    assert confirm(client, token, sid).status_code == 202
    assert drain(worker) >= 1

    result = statement(client, token, sid)
    assert (result["status"], result["bank_code"], result["rows_parsed"], result["reconciled"]) == (
        "parsed",
        "HDFC",
        45,
        True,
    )
    assert not raw_exists(live_settings, sid)

    user_id = client.get("/account/me", headers=bearer(token)).json()["id"]
    stored = owner_sql(
        live_settings, "SELECT narration_enc, ref_hmac FROM transactions WHERE statement_id = :s", {"s": sid}
    )
    assert len(stored) == 45
    first_narration = synthetic.rows[0].narration.encode()
    assert all(first_narration not in bytes(r.narration_enc) for r in stored)
    assert decrypted_narrations(live_settings, user_id, sid) == [r.narration for r in expected_rows(synthetic)]

    export = client.get("/account/export", headers=bearer(token)).json()
    assert len(export["transactions"]) == 45
    assert export["statements"][0]["bank_code"] == "HDFC"


def test_duplicate_upload_returns_the_existing_statement(client: TestClient) -> None:
    token = verified_user(client, "asha@example.in")
    data = render_csv(generate("SBI", 2, count=10))
    first = upload(client, token, data, FileKind.CSV)
    second = upload(client, token, data, FileKind.CSV, put=False)
    assert second["duplicate"] is True
    assert second["statement_id"] == first["statement_id"]
    assert second["upload_url"] is None


def test_processing_needs_a_verified_email_and_consent(client: TestClient) -> None:
    signup(client, "asha@example.in")
    token = login(client, "asha@example.in")
    data = render_csv(generate("SBI", 2, count=5))
    body = {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data), "file_kind": "csv"}
    assert client.post("/statements/presign", headers=bearer(token), json=body).json()["detail"] == "email_not_verified"
    verified = verified_user(client, "bilal@example.in")
    client.post("/account/consent/withdraw", headers=bearer(verified))
    assert (
        client.post("/statements/presign", headers=bearer(verified), json=body).json()["detail"] == "consent_withdrawn"
    )


def test_confirm_before_upload_is_refused(client: TestClient) -> None:
    token = verified_user(client, "asha@example.in")
    presigned = upload(client, token, render_csv(generate("SBI", 3, count=5)), FileKind.CSV, put=False)
    response = confirm(client, token, presigned["statement_id"])
    assert response.status_code == 409
    assert response.json()["detail"] == "upload_incomplete"


def test_other_users_cannot_see_or_confirm_my_statement(client: TestClient) -> None:
    asha = verified_user(client, "asha@example.in")
    presigned = upload(client, asha, render_csv(generate("SBI", 4, count=5)), FileKind.CSV)
    bilal = verified_user(client, "bilal@example.in")
    assert client.get(f"/statements/{presigned['statement_id']}", headers=bearer(bilal)).status_code == 404
    assert confirm(client, bilal, presigned["statement_id"]).status_code == 404
    assert client.get("/statements", headers=bearer(bilal)).json() == []


def test_password_protected_pdf_flow(client: TestClient, worker: WorkerContext) -> None:
    token = verified_user(client, "asha@example.in")
    data = render_pdf(generate("KOTAK", 5, count=20), password="SECRET99")
    sid = upload(client, token, data, FileKind.PDF)["statement_id"]
    confirm(client, token, sid)
    drain(worker)
    assert (statement(client, token, sid)["status"], statement(client, token, sid)["failure_code"]) == (
        "needs_password",
        "needs_password",
    )

    client.post(f"/statements/{sid}/password", headers=bearer(token), json={"password": "wrong"})
    drain(worker)
    assert statement(client, token, sid)["failure_code"] == "wrong_password"

    assert (
        client.post(f"/statements/{sid}/password", headers=bearer(token), json={"password": "SECRET99"}).status_code
        == 202
    )
    drain(worker)
    assert statement(client, token, sid)["status"] == "parsed"


def test_worker_crash_after_reading_password_asks_again(
    client: TestClient, worker_settings: Settings, worker: WorkerContext
) -> None:
    token = verified_user(client, "asha@example.in")
    data = render_pdf(generate("KOTAK", 6, count=10), password="SECRET99")
    sid = upload(client, token, data, FileKind.PDF)["statement_id"]
    confirm(client, token, sid, password="SECRET99")
    user_id = UUID(client.get("/account/me", headers=bearer(token)).json()["id"])

    async def crash_after_reading() -> None:
        ctx = WorkerContext.from_settings(worker_settings)
        try:
            async with ctx.db.as_user(user_id) as conn:
                cipher = await user_cipher(conn, ctx.keys, user_id)
            assert await take_pdf_password(ctx.dependencies.redis, cipher, UUID(sid)) == "SECRET99"
        finally:
            await ctx.close()

    asyncio.run(crash_after_reading())
    drain(worker)
    assert statement(client, token, sid)["status"] == "needs_password"


def test_tampered_upload_is_rejected_by_hash(
    client: TestClient, live_settings: Settings, worker: WorkerContext
) -> None:
    token = verified_user(client, "asha@example.in")
    declared = render_csv(generate("SBI", 7, count=5))
    presigned = upload(client, token, declared, FileKind.CSV, put=False)
    other = render_csv(generate("SBI", 8, count=5))
    other = other + b" " * (len(declared) - len(other)) if len(other) < len(declared) else other[: len(declared)]
    httpx.put(presigned["upload_url"], content=other, headers={"Content-Type": presigned["content_type"]})
    confirm(client, token, presigned["statement_id"])
    drain(worker)
    result = statement(client, token, presigned["statement_id"])
    assert (result["status"], result["failure_code"]) == ("failed", "hash_mismatch")
    assert not raw_exists(live_settings, presigned["statement_id"])


def test_crashed_worker_lease_expires_and_the_redo_is_identical(
    client: TestClient, live_settings: Settings, worker: WorkerContext
) -> None:
    token = verified_user(client, "asha@example.in")
    synthetic = generate("AXIS", 9, count=30)
    sid = upload(client, token, render_csv(synthetic), FileKind.CSV)["statement_id"]
    confirm(client, token, sid)
    drain(worker)
    user_id = client.get("/account/me", headers=bearer(token)).json()["id"]
    first = decrypted_narrations(live_settings, user_id, sid)

    owner_sql(live_settings, "UPDATE statements SET status = 'queued', raw_deleted_at = NULL WHERE id = :s", {"s": sid})
    create_s3_client(live_settings).put_object(
        Bucket=live_settings.s3_bucket_raw,
        Key=owner_sql(live_settings, "SELECT object_key FROM statements WHERE id = :s", {"s": sid})[0].object_key,
        Body=render_csv(synthetic),
    )
    owner_sql(
        live_settings,
        "UPDATE jobs SET state = 'running', locked_by = 'dead-worker', "
        "locked_until = now() - interval '1 minute', attempts = 1",
    )
    drain(worker)
    assert statement(client, token, sid)["status"] == "parsed"
    assert decrypted_narrations(live_settings, user_id, sid) == first
    count = owner_sql(live_settings, "SELECT count(*) AS n FROM transactions WHERE statement_id = :s", {"s": sid})
    assert count[0].n == 30
    attempts = owner_sql(live_settings, "SELECT attempts, state FROM jobs")
    assert [(r.attempts, r.state) for r in attempts] == [(2, "done")]
    owner_sql(live_settings, "UPDATE jobs SET locked_by = NULL")


def test_unknown_layout_without_a_model_needs_review(client: TestClient, worker: WorkerContext) -> None:
    token = verified_user(client, "asha@example.in")
    data = b"When,What,Out,In,Left\n01/04/2025,SHOP,250.00,,750.00\n02/04/2025,PAY,,100.00,850.00\n"
    sid = upload(client, token, data, FileKind.CSV)["statement_id"]
    confirm(client, token, sid)
    drain(worker)
    result = statement(client, token, sid)
    assert (result["status"], result["failure_code"]) == ("needs_review", "unknown_layout")


def test_unknown_layout_with_the_model_fallback(
    client: TestClient, worker_settings: Settings, live_settings: Settings
) -> None:
    mapping = {
        "columns": [
            {"label": "When", "field": "date"},
            {"label": "What", "field": "narration"},
            {"label": "Out", "field": "debit"},
            {"label": "In", "field": "credit"},
            {"label": "Left", "field": "balance"},
        ],
        "date_format": "%d/%m/%Y",
    }
    model = FakeModel(json.dumps(mapping))
    ctx = WorkerContext.from_settings(worker_settings, gateway=LlmGateway(model, daily_limit=6))
    asyncio.run(ctx.close())
    token = verified_user(client, "asha@example.in")
    data = (
        b"Customer RAVI KUMAR ravik@okicici\n"
        b"When,What,Out,In,Left\n"
        b"01/04/2025,UPI/DR/412345678901/RAVI KUMAR,250.00,,750.00\n"
        b"02/04/2025,NEFT CR PRIYA SHARMA,,100.00,850.00\n"
    )
    sid = upload(client, token, data, FileKind.CSV)["statement_id"]
    confirm(client, token, sid)
    drain(ctx)
    result = statement(client, token, sid)
    assert (result["status"], result["rows_parsed"], result["reconciled"]) == ("parsed", 2, True)
    assert len(model.prompts) == 1
    for secret in ("RAVI", "PRIYA", "ravik", "412345678901"):
        assert secret not in model.prompts[0]
    usage = owner_sql(live_settings, "SELECT calls FROM llm_usage")
    assert [r.calls for r in usage] == [1]
    owner_sql(live_settings, "UPDATE jobs SET locked_by = NULL")


def test_sweeper_deletes_stale_raw_files_and_expires_unconfirmed_uploads(
    client: TestClient, live_settings: Settings, worker_settings: Settings
) -> None:
    token = verified_user(client, "asha@example.in")
    sid = upload(client, token, render_csv(generate("SBI", 10, count=5)), FileKind.CSV)["statement_id"]
    assert raw_exists(live_settings, sid)

    async def sweep(at: datetime) -> int:
        ctx = WorkerContext.from_settings(worker_settings)
        try:
            return await sweep_raw_files(ctx, now=at)
        finally:
            await ctx.close()

    assert asyncio.run(sweep(datetime.now(UTC))) == 0
    assert asyncio.run(sweep(datetime.now(UTC) + timedelta(hours=2))) >= 1
    assert not raw_exists(live_settings, sid)
    assert statement(client, token, sid)["status"] == "expired"


def test_worker_stores_channel_kind_and_reference(
    client: TestClient, live_settings: Settings, worker: WorkerContext
) -> None:
    token = verified_user(client, "asha@example.in")
    synthetic = generate("SBI", 12, count=60)
    sid = upload(client, token, render_csv(synthetic), FileKind.CSV)["statement_id"]
    confirm(client, token, sid)
    drain(worker)
    stored = owner_sql(
        live_settings,
        "SELECT row_index, channel, kind, classifier_version, ext_ref_hmac IS NOT NULL AS has_ref "
        "FROM transactions WHERE statement_id = :s ORDER BY row_index",
        {"s": sid},
    )
    expected = [classify(r.narration, r.direction) for r in expected_rows(synthetic)]
    assert [(r.channel, r.kind) for r in stored] == [(e.channel.value, e.kind.value) for e in expected]
    assert [r.has_ref for r in stored] == [e.reference is not None for e in expected]
    assert {r.classifier_version for r in stored} == {CLASSIFIER_VERSION}
    assert any(r.kind == "reversal" for r in stored)
    export = client.get("/account/export", headers=bearer(token)).json()
    assert {t["channel"] for t in export["transactions"]} >= {"upi"}
