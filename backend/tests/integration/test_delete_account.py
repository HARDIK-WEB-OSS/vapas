import pytest
from fastapi.testclient import TestClient

from vapas.config import Settings
from vapas.storage.object_store import create_s3_client

from .conftest import PASSWORD, bearer, login, owner_sql, signup, user_id_of

pytestmark = pytest.mark.integration


def object_keys(settings: Settings, prefix: str) -> list[str]:
    listing = create_s3_client(settings).list_objects_v2(Bucket=settings.s3_bucket_raw, Prefix=prefix)
    return [item["Key"] for item in listing.get("Contents", [])]


def test_delete_my_data_erases_everything_of_mine_and_nothing_else(client: TestClient, live_settings: Settings) -> None:
    signup(client, "asha@example.in")
    asha = login(client, "asha@example.in")
    asha_id = user_id_of(client, asha)
    signup(client, "bilal@example.in")
    bilal_id = user_id_of(client, login(client, "bilal@example.in"))

    s3 = create_s3_client(live_settings)
    for owner in (asha_id, bilal_id):
        s3.put_object(Bucket=live_settings.s3_bucket_raw, Key=f"raw/{owner}/statement.pdf", Body=b"%PDF-1.7 synthetic")

    wrong = client.request("DELETE", "/account", headers=bearer(asha), json={"password": "not-my-password"})
    assert wrong.status_code == 403
    assert object_keys(live_settings, f"raw/{asha_id}/") != []

    deleted = client.request("DELETE", "/account", headers=bearer(asha), json={"password": PASSWORD})
    assert deleted.status_code == 204

    for table, column in [
        ("users", "id"),
        ("user_keys", "user_id"),
        ("sessions", "user_id"),
        ("email_tokens", "user_id"),
        ("consents", "user_id"),
        ("audit_log", "user_id"),
    ]:
        count = owner_sql(live_settings, f"SELECT count(*) AS n FROM {table} WHERE {column} = :u", {"u": asha_id})
        assert count[0].n == 0, table
    assert object_keys(live_settings, f"raw/{asha_id}/") == []

    deletion = owner_sql(live_settings, "SELECT user_id FROM audit_log WHERE action = 'account_deleted'")
    assert [r.user_id for r in deletion] == [None]

    assert client.get("/account/me", headers=bearer(asha)).status_code == 401
    assert client.post("/auth/login", json={"email": "asha@example.in", "password": PASSWORD}).status_code == 401

    assert object_keys(live_settings, f"raw/{bilal_id}/") == [f"raw/{bilal_id}/statement.pdf"]
    assert client.get("/account/me", headers=bearer(login(client, "bilal@example.in"))).status_code == 200
    s3.delete_object(Bucket=live_settings.s3_bucket_raw, Key=f"raw/{bilal_id}/statement.pdf")


def test_deleted_email_can_sign_up_again_as_a_new_account(client: TestClient) -> None:
    signup(client, "asha@example.in")
    first = login(client, "asha@example.in")
    first_id = user_id_of(client, first)
    assert client.request("DELETE", "/account", headers=bearer(first), json={"password": PASSWORD}).status_code == 204
    signup(client, "asha@example.in")
    assert user_id_of(client, login(client, "asha@example.in")) != first_id
