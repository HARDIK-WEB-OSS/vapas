import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml
from pydantic import ValidationError


@pytest.fixture(scope="module")
def schema() -> ModuleType:
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("vapas_rules_schema", root / "rules" / "schema.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def copy_rules(repo_root: Path, tmp_path: Path) -> Path:
    target = tmp_path / "rules"
    shutil.copytree(repo_root / "rules", target)
    return target


def edit_first_tat_rule(rules: Path, field: str, value: object) -> None:
    path = rules / "rbi" / "tat_failed_transactions.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["tat_rules"][0][field] = value
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_committed_rules_are_valid(schema: ModuleType, repo_root: Path) -> None:
    book = schema.load_rulebook(repo_root / "rules")
    assert "rbi/tat_failed_transactions.yaml" in {Path(name).as_posix() for name in book.files}


def test_unknown_field_is_rejected(schema: ModuleType, repo_root: Path, tmp_path: Path) -> None:
    rules = copy_rules(repo_root, tmp_path)
    edit_first_tat_rule(rules, "invented_field", 1)
    with pytest.raises(ValidationError):
        schema.load_rulebook(rules)


def test_non_numeric_deadline_is_rejected(schema: ModuleType, repo_root: Path, tmp_path: Path) -> None:
    rules = copy_rules(repo_root, tmp_path)
    edit_first_tat_rule(rules, "deadline_days", "five")
    with pytest.raises(ValidationError):
        schema.load_rulebook(rules)


def run_schema_cli(rules: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(rules / "schema.py")], capture_output=True, text=True, check=False)


def test_schema_cli_passes_on_committed_rules(repo_root: Path, tmp_path: Path) -> None:
    result = run_schema_cli(copy_rules(repo_root, tmp_path))
    assert result.returncode == 0, result.stderr


def test_invalid_rule_yaml_makes_cli_fail(repo_root: Path, tmp_path: Path) -> None:
    rules = copy_rules(repo_root, tmp_path)
    edit_first_tat_rule(rules, "deadline_days", "five")
    result = run_schema_cli(rules)
    assert result.returncode != 0
    assert "ValidationError" in result.stderr
