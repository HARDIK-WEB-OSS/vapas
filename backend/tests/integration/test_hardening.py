import hashlib
import math
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from vapas.config import Settings
from vapas.ingest.model import FileKind
from vapas.security.api_limits import API_PER_USER
from vapas.storage.object_store import create_s3_client, expire_raw_uploads, raw_lifecycle_days

from .conftest import bearer, verified_user

pytestmark = pytest.mark.integration


def test_general_limit_per_user_and_headers(client: TestClient) -> None:
    token = verified_user(client, "asha@example.in")
    started = time.monotonic()
    allowed_count = 0
    blocked = client.get("/notifications", headers=bearer(token))
    while blocked.status_code == 200 and allowed_count < 3 * API_PER_USER.capacity:
        allowed_count += 1
        blocked = client.get("/notifications", headers=bearer(token))
    refilled = math.ceil((time.monotonic() - started) * API_PER_USER.refill_per_second)
    assert API_PER_USER.capacity <= allowed_count <= API_PER_USER.capacity + refilled
    assert (blocked.status_code, blocked.json()["error"]) == (429, "rate_limited")
    assert blocked.headers["Retry-After"] == "1"

    other = verified_user(client, "bilal@example.in")
    allowed = client.get("/account/me", headers=bearer(other))
    assert allowed.status_code == 200
    assert allowed.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in allowed.headers["content-security-policy"]
    assert "strict-transport-security" not in allowed.headers
    assert client.get("/docs").status_code == 200


def test_oversized_json_is_refused(client: TestClient) -> None:
    response = client.post("/auth/login", json={"email": "a@example.in", "password": "p" * 70_000})
    assert (response.status_code, response.json()["error"]) == (413, "body_too_large")


def test_presigned_upload_is_bound_to_the_declared_size(client: TestClient) -> None:
    token = verified_user(client, "asha@example.in")
    declared = b"Txn Date,Description,Debit,Credit,Balance\n"
    body = {
        "sha256": hashlib.sha256(declared).hexdigest(),
        "size_bytes": len(declared),
        "file_kind": FileKind.CSV.value,
    }
    out = client.post("/statements/presign", headers=bearer(token), json=body).json()
    headers = {"Content-Type": out["content_type"]}
    bigger = httpx.put(out["upload_url"], content=declared + b"x" * 4096, headers=headers)
    assert bigger.status_code in (400, 403)
    assert httpx.put(out["upload_url"], content=declared, headers=headers).status_code == 200


def test_raw_uploads_have_a_lifecycle_backstop(live_settings: Settings) -> None:
    client = create_s3_client(live_settings)
    expire_raw_uploads(client, live_settings.s3_bucket_raw)
    assert raw_lifecycle_days(client, live_settings.s3_bucket_raw) == 1
