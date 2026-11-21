import hashlib
import importlib.util
import json
import sys
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from vapas.security.private_path_guard import find_code_root

POLICY_FIELDS = frozenset({"finding_policy", "letter_scope", "user_inputs", "letter_disclosure"})
SCHEMA_MODULE = "vapas_rules_schema"


class RulesNotUsableError(RuntimeError):
    pass


@dataclass(frozen=True)
class TatRule:
    id: str
    clause: str
    payment_system: str
    scenario: str
    deadline_days: int | None
    per_day_inr: int | None
    finding_policy: str
    letter_scope: str
    effective_from: date
    effective_to: date | None
    verified: bool
    quote: str
    letter_disclosure: str | None
    escalation_wait_days: int | None

    def in_force_on(self, day: date) -> bool:
        return self.effective_from <= day and (self.effective_to is None or day <= self.effective_to)


@dataclass(frozen=True)
class DayTypeOverride:
    id: str
    applies_to: str
    effective_from: date
    effective_to: date | None

    def covers(self, day: date) -> bool:
        return self.effective_from <= day and (self.effective_to is None or day <= self.effective_to)


@dataclass(frozen=True)
class RuleBook:
    instrument_id: str
    instrument_ref: str
    tat_rules: dict[str, TatRule]
    overrides: tuple[DayTypeOverride, ...]
    rules_sha256: bytes
    legal_content: dict[str, Any]
    policy_content: dict[str, Any]

    def rule(self, rule_id: str, on: date) -> TatRule | None:
        found = self.tat_rules.get(rule_id)
        if found is None or not found.verified or not found.in_force_on(on):
            return None
        return found

    def override_window(self, on: date) -> DayTypeOverride | None:
        return next((o for o in self.overrides if o.applies_to == self.instrument_id and o.covers(on)), None)

    def policy_sha256(self, config: dict[str, Any]) -> bytes:
        return _digest({"rules": self.policy_content, "config": config})


def _digest(value: Any) -> bytes:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).digest()


def default_rules_dir() -> Path:
    return find_code_root(Path(__file__).parent) / "rules"


def _schema(rules_dir: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(SCHEMA_MODULE, rules_dir / "schema.py")
    if spec is None or spec.loader is None:
        raise RulesNotUsableError(f"no rules/schema.py in {rules_dir}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[SCHEMA_MODULE] = module
    spec.loader.exec_module(module)
    return module


def _split(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    legal = json.loads(json.dumps(raw, default=str))
    policy: dict[str, Any] = {}
    for rule in legal.get("tat_rules", []):
        policy[rule["id"]] = {key: rule.pop(key) for key in sorted(POLICY_FIELDS) if key in rule}
    return legal, policy


@lru_cache(maxsize=4)
def load_rulebook(rules_dir: Path | None = None) -> RuleBook:
    folder = rules_dir or default_rules_dir()
    _schema(folder).load_rulebook(folder)
    raw = yaml.safe_load((folder / "rbi" / "tat_failed_transactions.yaml").read_text(encoding="utf-8"))
    files = {p.name: yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted((folder / "rbi").glob("*.yaml"))}
    legal: dict[str, Any] = {}
    policy: dict[str, Any] = {}
    for name, content in files.items():
        legal[name], policy[name] = _split(content)
    rules = {
        r["id"]: TatRule(
            id=r["id"],
            clause=r["clause"],
            payment_system=r["payment_system"],
            scenario=r["scenario"],
            deadline_days=r.get("deadline_days"),
            per_day_inr=(r.get("compensation") or {}).get("per_day_inr"),
            finding_policy=r["finding_policy"],
            letter_scope=r.get("letter_scope", "claim"),
            effective_from=r["effective_from"],
            effective_to=r.get("effective_to"),
            verified=(r.get("review") or {}).get("status") == "verified",
            quote=r["quote"],
            letter_disclosure=r.get("letter_disclosure"),
            escalation_wait_days=r.get("escalation_wait_days"),
        )
        for r in raw["tat_rules"]
    }
    overrides = tuple(
        DayTypeOverride(o["id"], o["applies_to"], o["effective_from"], o.get("effective_to"))
        for content in files.values()
        for o in content.get("day_type_overrides", [])
    )
    instrument = raw["instrument"]
    reference = instrument.get("dept_ref") or instrument["ref_no"]
    return RuleBook(instrument["id"], reference, rules, overrides, _digest(legal), legal, policy)
