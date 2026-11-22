import asyncio
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from vapas.config import Settings
from vapas.jobs.context import WorkerContext
from vapas.jobs.maintenance import delete_unverified_accounts

from .conftest import owner_sql, signup, verified_user

pytestmark = pytest.mark.integration

USER_TABLES = ("consents", "user_keys", "email_tokens", "sessions")


def backdate(settings: Settings, email: str, hours: float) -> str:
    rows = owner_sql(
        settings,
        "UPDATE users SET created_at = now() - make_interval(secs => :s) WHERE email = :e RETURNING id",
        {"s": hours * 3600, "e": email},
    )
    return str(rows[0].id)


def sweep(worker_settings: Settings) -> int:
    async def run() -> int:
        ctx = WorkerContext.from_settings(worker_settings)
        try:
            return await delete_unverified_accounts(ctx, datetime.now(UTC))
        finally:
            await ctx.close()

    return asyncio.run(run())


def emails(settings: Settings) -> set[str]:
    return {r.email for r in owner_sql(settings, "SELECT email FROM users")}


def test_unverified_accounts_are_deleted_after_the_ttl(
    client: TestClient, live_settings: Settings, worker_settings: Settings
) -> None:
    signup(client, "stale@example.in")
    signup(client, "fresh@example.in")
    verified_user(client, "real@example.in")
    stale_id = backdate(live_settings, "stale@example.in", 49)
    backdate(live_settings, "fresh@example.in", 47)
    backdate(live_settings, "real@example.in", 72)

    assert sweep(worker_settings) == 1
    assert emails(live_settings) == {"fresh@example.in", "real@example.in"}
    for table in USER_TABLES:
        rows = owner_sql(live_settings, f"SELECT count(*) AS n FROM {table} WHERE user_id = :u", {"u": stale_id})
        assert rows[0].n == 0, table

    audit = owner_sql(
        live_settings,
        "SELECT user_id, actor, action, entity_type, entity_id::text AS entity, ip_hash FROM audit_log "
        "WHERE action = 'unverified_account_deleted'",
    )
    assert [(r.user_id, r.actor, r.entity_type, r.entity, r.ip_hash) for r in audit] == [
        (None, "system", "user", stale_id, None)
    ]
    everything = repr(owner_sql(live_settings, "SELECT * FROM audit_log"))
    assert "stale@example.in" not in everything
    assert sweep(worker_settings) == 0


def test_account_verified_at_47_hours_is_kept(
    client: TestClient, live_settings: Settings, worker_settings: Settings
) -> None:
    verified_user(client, "late@example.in")
    backdate(live_settings, "late@example.in", 47)
    signup(client, "waiting@example.in")
    backdate(live_settings, "waiting@example.in", 47.9)
    assert sweep(worker_settings) == 0
    assert emails(live_settings) == {"late@example.in", "waiting@example.in"}


def test_ttl_is_configurable(client: TestClient, live_settings: Settings, worker_settings: Settings) -> None:
    signup(client, "short@example.in")
    backdate(live_settings, "short@example.in", 3)
    assert sweep(worker_settings.model_copy(update={"unverified_account_ttl_hours": 4})) == 0
    assert sweep(worker_settings.model_copy(update={"unverified_account_ttl_hours": 2})) == 1
