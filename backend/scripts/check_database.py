import asyncio
import os
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text
from sqlalchemy import table as sql_table
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from vapas.analytics.impact import Window, compute_impact
from vapas.config import get_settings

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
ROLE_FLAGS = text("SELECT current_user AS name, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
EXPOSED_USER_TABLES = text(
    "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND NOT c.relispartition "
    "AND (c.relname = 'users' OR EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid "
    "AND a.attname = 'user_id' AND NOT a.attisdropped)) "
    "AND NOT (c.relrowsecurity AND c.relforcerowsecurity) "
    "AND has_table_privilege(:app_role, c.oid, 'SELECT, UPDATE, DELETE') ORDER BY 1"
)
RLS_TABLES = text(
    "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND NOT c.relispartition "
    "AND c.relrowsecurity AND has_table_privilege(:app_role, c.oid, 'SELECT') ORDER BY 1"
)
WEAK_DEFINERS = text(
    "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
    "JOIN pg_roles r ON r.oid = p.proowner WHERE n.nspname = 'public' AND p.prosecdef "
    "AND NOT (r.rolsuper OR r.rolbypassrls) ORDER BY 1"
)
LOGIN_LOOKUP = text("SELECT count(*) FROM auth_lookup('database-check@example.invalid')")


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


Check = Callable[[AsyncConnection], Awaitable[CheckResult]]


async def _role_restricted(name: str, conn: AsyncConnection) -> CheckResult:
    role = (await conn.execute(ROLE_FLAGS)).one()
    privileged = role.rolsuper or role.rolbypassrls
    return CheckResult(name, not privileged, f"role {role.name} is superuser or bypasses RLS" if privileged else "")


async def _owner_bypasses(conn: AsyncConnection) -> CheckResult:
    role = (await conn.execute(ROLE_FLAGS)).one()
    ok = bool(role.rolsuper or role.rolbypassrls)
    return CheckResult("owner_bypasses_rls", ok, "" if ok else f"role {role.name} has no BYPASSRLS; see needs_owner.md")


async def _definers(conn: AsyncConnection) -> CheckResult:
    weak = list((await conn.scalars(WEAK_DEFINERS)).all())
    return CheckResult("definer_functions_bypass_rls", not weak, f"functions: {', '.join(weak)}" if weak else "")


def _forced_rls(app_role: str) -> Check:
    async def check(conn: AsyncConnection) -> CheckResult:
        exposed = list((await conn.scalars(EXPOSED_USER_TABLES, {"app_role": app_role})).all())
        return CheckResult("user_tables_force_rls", not exposed, f"tables: {', '.join(exposed)}" if exposed else "")

    return check


async def _app_sees_nothing(conn: AsyncConnection, tables: list[str]) -> CheckResult:
    visible: list[str] = []
    for table in tables:
        try:
            async with conn.begin_nested():
                if await conn.scalar(select(func.count()).select_from(sql_table(table))):
                    visible.append(table)
        except DBAPIError:
            continue
    return CheckResult(
        "app_sees_no_rows_without_a_user", not visible, f"tables: {', '.join(visible)}" if visible else ""
    )


async def _login_lookup(conn: AsyncConnection) -> CheckResult:
    try:
        async with conn.begin_nested():
            await conn.scalar(LOGIN_LOOKUP)
    except DBAPIError as error:
        return CheckResult("app_can_call_login_lookup", False, type(error.orig).__name__)
    return CheckResult("app_can_call_login_lookup", True, "")


async def _impact(conn: AsyncConnection) -> CheckResult:
    end = datetime.now(UTC)
    try:
        async with conn.begin_nested():
            await compute_impact(conn, Window(end - timedelta(days=7), end))
    except DBAPIError as error:
        return CheckResult("owner_can_run_impact_report", False, type(error.orig).__name__)
    return CheckResult("owner_can_run_impact_report", True, "")


async def _migrations(conn: AsyncConnection) -> CheckResult:
    head = ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()
    current = await conn.scalar(text("SELECT version_num FROM alembic_version"))
    ok = current == head
    return CheckResult("migrations_at_head", ok, "" if ok else f"database at {current}, code at {head}")


async def _on(url: str, work: Callable[[AsyncConnection], Awaitable[list[CheckResult]]]) -> list[CheckResult]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            results = await work(conn)
            await conn.rollback()
            return results
    finally:
        await engine.dispose()


async def run_checks(app_url: str, owner_url: str, worker_url: str | None) -> list[CheckResult]:
    app_role: list[str] = []

    async def as_app(conn: AsyncConnection) -> list[CheckResult]:
        app_role.append(str(await conn.scalar(text("SELECT current_user"))))
        return [await _role_restricted("app_role_restricted", conn), await _login_lookup(conn)]

    async def as_owner(conn: AsyncConnection) -> list[CheckResult]:
        tables = list((await conn.scalars(RLS_TABLES, {"app_role": app_role[0]})).all())
        checks: list[Check] = [_owner_bypasses, _definers, _forced_rls(app_role[0]), _impact, _migrations]
        results = [await check(conn) for check in checks]
        return [*results, *(await _on(app_url, lambda app: _visible(app, tables)))]

    async def _visible(conn: AsyncConnection, tables: list[str]) -> list[CheckResult]:
        return [await _app_sees_nothing(conn, tables)]

    async def as_worker(conn: AsyncConnection) -> list[CheckResult]:
        return [await _role_restricted("worker_role_restricted", conn)]

    results = await _on(app_url, as_app)
    results += await _on(owner_url, as_owner)
    if worker_url is None:
        results.append(CheckResult("worker_role_restricted", False, "WORKER_DATABASE_URL is not set"))
    else:
        results += await _on(worker_url, as_worker)
    return results


def render(results: list[CheckResult]) -> list[str]:
    lines = [f"PASS {r.name}" if r.passed else f"FAIL {r.name}: {r.detail}" for r in results]
    failed = sum(not r.passed for r in results)
    lines.append(f"{failed} of {len(results)} checks failed" if failed else f"all {len(results)} checks passed")
    return lines


def main() -> int:
    settings = get_settings()
    if settings.migration_database_url is None:
        print("FAIL MIGRATION_DATABASE_URL is not set")
        return 1
    owner_url = settings.migration_database_url.get_secret_value()
    worker_url = os.environ.get("WORKER_DATABASE_URL") or None
    results = asyncio.run(run_checks(settings.database_url.get_secret_value(), owner_url, worker_url))
    for line in render(results):
        print(line)
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
