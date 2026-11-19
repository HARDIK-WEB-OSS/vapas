import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from vapas.config import Settings

from .conftest import login, owner_sql, signup, user_id_of

pytestmark = pytest.mark.integration

USER_TABLES = {
    "users": "id",
    "user_keys": "user_id",
    "sessions": "user_id",
    "email_tokens": "user_id",
    "consents": "user_id",
    "audit_log": "user_id",
}
T = TypeVar("T")


def as_app_role(settings: Settings, user_id: str | None, work: Callable[[AsyncConnection], Awaitable[T]]) -> T:
    async def run() -> T:
        engine = create_async_engine(settings.database_url.get_secret_value())
        try:
            async with engine.begin() as conn:
                if user_id is not None:
                    await conn.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": user_id})
                return await work(conn)
        finally:
            await engine.dispose()

    return asyncio.run(run())


@pytest.fixture
def two_users(client: TestClient) -> tuple[str, str]:
    ids = []
    for email in ("asha@example.in", "bilal@example.in"):
        signup(client, email)
        ids.append(user_id_of(client, login(client, email)))
    return ids[0], ids[1]


def owners_seen(settings: Settings, user_id: str | None) -> dict[str, set[str]]:
    async def work(conn: AsyncConnection) -> dict[str, set[str]]:
        seen: dict[str, set[str]] = {}
        for table, column in USER_TABLES.items():
            rows = await conn.execute(text(f"SELECT {column}::text AS owner FROM {table}"))
            seen[table] = {r.owner for r in rows}
        return seen

    return as_app_role(settings, user_id, work)


def test_user_a_sees_only_own_rows_in_every_table(live_settings: Settings, two_users: tuple[str, str]) -> None:
    a, _ = two_users
    seen = owners_seen(live_settings, a)
    assert all(owners == {a} for owners in seen.values()), seen


def test_without_user_context_nothing_is_visible(live_settings: Settings, two_users: tuple[str, str]) -> None:
    seen = owners_seen(live_settings, None)
    assert all(owners == set() for owners in seen.values()), seen


def test_user_a_cannot_change_or_delete_user_b(live_settings: Settings, two_users: tuple[str, str]) -> None:
    a, b = two_users

    async def work(conn: AsyncConnection) -> list[int]:
        statements = [
            "UPDATE users SET locale = 'hi' WHERE id = :b",
            "UPDATE sessions SET revoked_at = now() WHERE user_id = :b",
            "DELETE FROM consents WHERE user_id = :b",
            "DELETE FROM user_keys WHERE user_id = :b",
            "DELETE FROM users WHERE id = :b",
        ]
        return [(await conn.execute(text(s), {"b": b})).rowcount for s in statements]

    assert as_app_role(live_settings, a, work) == [0, 0, 0, 0, 0]
    assert owner_sql(live_settings, "SELECT count(*) AS n FROM users")[0].n == 2


def attempt(settings: Settings, user_id: str | None, sql: str, params: dict[str, Any] | None = None) -> str:
    async def work(conn: AsyncConnection) -> str:
        try:
            await conn.execute(text(sql), params or {})
        except DBAPIError as error:
            return str(error.orig)
        return "succeeded"

    return as_app_role(settings, user_id, work)


def test_user_a_cannot_write_rows_owned_by_user_b(live_settings: Settings, two_users: tuple[str, str]) -> None:
    a, b = two_users
    sql = (
        "INSERT INTO consents (id, user_id, notice_version, purpose) "
        "VALUES (gen_random_uuid(), :b, '2026-11-v1', 'statement_analysis')"
    )
    assert "row-level security" in attempt(live_settings, a, sql, {"b": b})
    audit = "INSERT INTO audit_log (user_id, actor, action) VALUES (:b, 'user', 'forged')"
    assert "row-level security" in attempt(live_settings, a, audit, {"b": b})


def test_app_role_cannot_switch_off_row_security(live_settings: Settings, two_users: tuple[str, str]) -> None:
    a, _ = two_users

    async def work(conn: AsyncConnection) -> str:
        await conn.execute(text("SET LOCAL row_security = off"))
        try:
            await conn.execute(text("SELECT * FROM users"))
        except DBAPIError as error:
            return str(error.orig)
        return "succeeded"

    assert "row-level security" in as_app_role(live_settings, a, work)


def test_app_role_cannot_become_owner_or_rewrite_audit(live_settings: Settings, two_users: tuple[str, str]) -> None:
    a, _ = two_users
    assert "permission denied" in attempt(live_settings, a, "SET ROLE vapas")
    assert "permission denied" in attempt(live_settings, a, "UPDATE audit_log SET action = 'x'")
    assert "permission denied" in attempt(live_settings, a, "DELETE FROM audit_log")
    assert "permission denied" in attempt(live_settings, a, "SELECT * FROM alembic_version")


def test_every_user_table_forces_row_level_security(live_settings: Settings) -> None:
    rows = owner_sql(
        live_settings,
        """
        SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
          AND (c.relname = 'users' OR EXISTS (
              SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attname = 'user_id' AND NOT a.attisdropped))
        """,
    )
    assert {r.relname for r in rows} >= set(USER_TABLES)
    assert [r.relname for r in rows if not (r.relrowsecurity and r.relforcerowsecurity)] == []
