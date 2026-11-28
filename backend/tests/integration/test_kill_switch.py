from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from vapas.config import Settings
from vapas.ingest.model import FileKind
from vapas.main import create_app
from vapas.privacy.notices import CURRENT_NOTICE_VERSION

from .conftest import PASSWORD, bearer, confirm, fresh_client_address, login, upload, verified_user

pytestmark = pytest.mark.integration

PAUSED = (503, "service_paused")
CSV = b"Date,Narration,Debit,Credit,Balance\n01/04/2026,UPI/DR/1/SHOP,100.00,,900.00\n"


@pytest.fixture
def paused_client(live_settings: Settings) -> Iterator[TestClient]:
    with TestClient(
        create_app(live_settings.model_copy(update={"kill_switch": True})), client=fresh_client_address()
    ) as test_client:
        yield test_client


def outcome(response: httpx.Response) -> tuple[int, str | None]:
    error: str | None = response.json().get("error")
    return response.status_code, error


def test_kill_switch_blocks_signup_and_uploads_but_not_login(client: TestClient, paused_client: TestClient) -> None:
    verified_user(client, "asha@example.in")
    pending = upload(client, login(client, "asha@example.in"), CSV, FileKind.CSV)

    body = {"email": "bilal@example.in", "password": PASSWORD, "consent_notice_version": CURRENT_NOTICE_VERSION}
    assert outcome(paused_client.post("/auth/signup", json=body)) == PAUSED

    token = login(paused_client, "asha@example.in")
    presign = {"sha256": "ab" * 32, "size_bytes": 10, "file_kind": FileKind.CSV.value}
    assert outcome(paused_client.post("/statements/presign", headers=bearer(token), json=presign)) == PAUSED
    assert outcome(confirm(paused_client, token, pending["statement_id"])) == PAUSED
    password = paused_client.post(
        f"/statements/{pending['statement_id']}/password", headers=bearer(token), json={"password": "x"}
    )
    assert outcome(password) == PAUSED

    assert paused_client.get("/statements", headers=bearer(token)).status_code == 200
    assert paused_client.get("/intake").json() == {"intake": "paused"}


def test_without_the_kill_switch_intake_is_open(client: TestClient) -> None:
    assert client.get("/intake").json() == {"intake": "open"}
