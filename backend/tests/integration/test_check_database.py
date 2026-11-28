import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pydantic import SecretStr

from vapas.config import Settings

from .conftest import owner_sql

pytestmark = pytest.mark.integration

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_database.py"
EXPECTED_CHECKS = {
    "app_role_restricted",
    "worker_role_restricted",
    "owner_bypasses_rls",
    "definer_functions_bypass_rls",
    "user_tables_force_rls",
    "app_sees_no_rows_without_a_user",
    "app_can_call_login_lookup",
    "owner_can_run_impact_report",
    "migrations_at_head",
}


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_database", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def urls(live: Settings, worker: Settings) -> tuple[str, str, str]:
    owner = live.migration_database_url
    assert isinstance(owner, SecretStr)
    return live.database_url.get_secret_value(), owner.get_secret_value(), worker.database_url.get_secret_value()


def run(script: ModuleType, app: str, owner: str, worker: str | None) -> dict[str, Any]:
    results = asyncio.run(script.run_checks(app, owner, worker))
    return {result.name: result for result in results}


def test_every_check_passes_on_the_local_database(
    script: ModuleType, live_settings: Settings, worker_settings: Settings
) -> None:
    results = run(script, *urls(live_settings, worker_settings))
    assert set(results) == EXPECTED_CHECKS
    failed = [name for name, result in results.items() if not result.passed]
    assert failed == []


def test_a_user_table_without_forced_rls_fails_by_name(
    script: ModuleType, live_settings: Settings, worker_settings: Settings
) -> None:
    owner_sql(live_settings, "CREATE TABLE zz_rls_probe (id int, user_id uuid)")
    owner_sql(live_settings, "GRANT SELECT ON zz_rls_probe TO vapas_app")
    try:
        result = run(script, *urls(live_settings, worker_settings))["user_tables_force_rls"]
    finally:
        owner_sql(live_settings, "DROP TABLE zz_rls_probe")
    assert result.passed is False
    assert "zz_rls_probe" in result.detail


def test_a_privileged_app_role_fails(script: ModuleType, live_settings: Settings, worker_settings: Settings) -> None:
    _, owner, worker = urls(live_settings, worker_settings)
    results = run(script, owner, owner, worker)
    assert results["app_role_restricted"].passed is False


def test_a_missing_worker_url_fails(script: ModuleType, live_settings: Settings, worker_settings: Settings) -> None:
    app, owner, _ = urls(live_settings, worker_settings)
    result = run(script, app, owner, None)["worker_role_restricted"]
    assert result.passed is False
    assert "WORKER_DATABASE_URL" in result.detail


def test_report_shows_only_check_names_and_verdicts(script: ModuleType) -> None:
    lines = script.render([script.CheckResult("a", True, ""), script.CheckResult("b", False, "tables: x")])
    assert lines == ["PASS a", "FAIL b: tables: x", "1 of 2 checks failed"]
