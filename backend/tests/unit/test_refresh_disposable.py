import importlib.util
import shutil
import sys
from pathlib import Path
from types import ModuleType

import httpx
import pytest

from vapas.rules.loader import default_rules_dir
from vapas.security.email_domains import load_domain_policy

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "refresh_disposable_domains.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("refresh_disposable_domains", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


refresh_script = load_script()


@pytest.fixture
def rules(tmp_path: Path) -> Path:
    shutil.copytree(default_rules_dir() / "email", tmp_path / "email")
    load_domain_policy.cache_clear()
    return tmp_path


def current_list(rules: Path) -> str:
    return (rules / "email" / "disposable_domains.txt").read_text(encoding="utf-8")


def serve(monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    monkeypatch.setattr(refresh_script, "fetch", lambda url: body)


def test_unreachable_source_fails_loudly_and_keeps_the_last_good_list(
    rules: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = current_list(rules)

    def down(url: str, **_: object) -> httpx.Response:
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(refresh_script.httpx, "get", down)
    monkeypatch.setattr(sys, "argv", ["refresh", "--rules-dir", str(rules)])
    assert refresh_script.main() == 1
    assert "REFRESH FAILED: source unreachable" in capsys.readouterr().err
    assert current_list(rules) == before
    assert "mailinator.com" in load_domain_policy(rules).blocked


def test_a_list_that_blocks_a_major_provider_is_refused(rules: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, current_list(rules) + "gmail.com\n")
    with pytest.raises(refresh_script.RefreshError, match=r"gmail\.com"):
        refresh_script.refresh(rules, "https://example.invalid/list", force=False)


def test_a_list_that_blocks_an_allowlisted_domain_is_refused(rules: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (rules / "email" / "allowlist_extra.txt").write_text("mailinator.com\n", encoding="utf-8")
    serve(monkeypatch, current_list(rules))
    with pytest.raises(refresh_script.RefreshError, match=r"mailinator\.com"):
        refresh_script.refresh(rules, "https://example.invalid/list", force=False)


def test_a_big_size_change_needs_force(rules: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    half = "\n".join(current_list(rules).splitlines()[:6000]) + "\n"
    serve(monkeypatch, half)
    with pytest.raises(refresh_script.RefreshError, match="--force"):
        refresh_script.refresh(rules, "https://example.invalid/list", force=False)
    assert refresh_script.refresh(rules, "https://example.invalid/list", force=True) == 0


def test_a_good_refresh_writes_a_list_the_app_accepts(rules: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, current_list(rules).upper() + "\n  New-Throwaway.Example \n")
    assert refresh_script.refresh(rules, "https://example.invalid/list", force=False) == 0
    load_domain_policy.cache_clear()
    policy = load_domain_policy(rules)
    assert "new-throwaway.example" in policy.blocked
    assert "mailinator.com" in policy.blocked


def test_an_unchanged_list_leaves_the_files_alone(rules: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    meta = (rules / "email" / "disposable_source.yaml").read_text(encoding="utf-8")
    serve(monkeypatch, current_list(rules))
    assert refresh_script.refresh(rules, "https://example.invalid/list", force=False) == 0
    assert (rules / "email" / "disposable_source.yaml").read_text(encoding="utf-8") == meta


def snapshot(rules: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted((rules / "email").iterdir())}


def run_check(rules: Path, monkeypatch: pytest.MonkeyPatch, summary: Path) -> int:
    monkeypatch.setattr(sys, "argv", ["refresh", "--check", "--rules-dir", str(rules), "--summary", str(summary)])
    result: int = refresh_script.main()
    return result


def test_check_with_an_unchanged_source_reports_nothing(
    rules: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    before = snapshot(rules)
    serve(monkeypatch, current_list(rules))
    assert run_check(rules, monkeypatch, tmp_path / "summary.md") == 0
    assert not (tmp_path / "summary.md").exists()
    assert snapshot(rules) == before


def test_check_with_a_changed_source_reports_and_writes_nothing_in_the_repo(
    rules: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    before = snapshot(rules)
    serve(monkeypatch, current_list(rules) + "new-throwaway.example\n")
    assert run_check(rules, monkeypatch, tmp_path / "summary.md") == refresh_script.UPDATE_AVAILABLE
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "Added: 1, removed: 0" in summary
    assert "passes the safety checks" in summary
    assert snapshot(rules) == before


def test_check_reports_a_list_the_safety_checks_would_refuse(
    rules: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    serve(monkeypatch, current_list(rules) + "gmail.com\n")
    assert run_check(rules, monkeypatch, tmp_path / "summary.md") == refresh_script.UPDATE_AVAILABLE
    assert "would be refused" in (tmp_path / "summary.md").read_text(encoding="utf-8")


def test_check_with_an_unreachable_source_fails(rules: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def down(url: str, **_: object) -> httpx.Response:
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(refresh_script.httpx, "get", down)
    assert run_check(rules, monkeypatch, tmp_path / "summary.md") == 1
