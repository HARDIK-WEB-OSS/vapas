import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from vapas.rules.loader import default_rules_dir, load_rulebook

RULE_YAML = "rule_yaml"
PDF = "pdf"


@dataclass(frozen=True)
class Clause:
    instrument_id: str
    instrument_title: str
    instrument_ref: str
    clause: str
    rule_id: str | None
    body: str
    search_hints: str
    source: str
    source_sha256: bytes
    url: str
    page: int | None
    legal_status: str
    verified: bool


@dataclass(frozen=True)
class Instrument:
    id: str
    title: str
    ref: str
    legal_status: str
    page_url: str
    pdf_url: str | None
    pdf_sha256: str | None


def instrument_of(content: dict[str, Any]) -> Instrument:
    raw = content["instrument"]
    pdf = raw.get("pdf") or {}
    return Instrument(
        id=raw["id"],
        title=raw["title"],
        ref=raw.get("ref_no") or raw.get("dept_ref") or raw["id"],
        legal_status=raw["legal_status"],
        page_url=str(raw["page"]["url"]),
        pdf_url=str(pdf["url"]) if pdf.get("url") else None,
        pdf_sha256=pdf.get("sha256"),
    )


def rule_files(rules_dir: Path | None = None) -> dict[Path, dict[str, Any]]:
    folder = rules_dir or default_rules_dir()
    load_rulebook(folder)
    return {p: yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted((folder / "rbi").glob("*.yaml"))}


def _verified(rule: dict[str, Any]) -> bool:
    return (rule.get("review") or {}).get("status") == "verified"


def _hints(*parts: Any) -> str:
    return " ".join(str(p) for p in parts if p)


def _make(instrument: Instrument, digest: bytes, rule: dict[str, Any], hints: str, url: str) -> Clause:
    return Clause(
        instrument_id=instrument.id,
        instrument_title=instrument.title,
        instrument_ref=instrument.ref,
        clause=rule["clause"],
        rule_id=rule["id"],
        body=rule["quote"],
        search_hints=hints,
        source=RULE_YAML,
        source_sha256=digest,
        url=url,
        page=None,
        legal_status=instrument.legal_status,
        verified=_verified(rule),
    )


def clauses_from_rules(rules_dir: Path | None = None) -> list[Clause]:
    clauses: list[Clause] = []
    for path, content in rule_files(rules_dir).items():
        instrument = instrument_of(content)
        digest = hashlib.sha256(path.read_bytes()).digest()
        url = instrument.pdf_url or instrument.page_url
        for rule in content.get("tat_rules", []):
            hints = _hints(rule["payment_system"], rule["scenario"], rule.get("merged_from"))
            clauses.append(_make(instrument, digest, rule, hints, url))
        for rule in content.get("ombudsman_rules", []):
            hints = _hints(rule["text"], rule["kind"].replace("_", " "))
            clauses.append(_make(instrument, digest, rule, hints, (rule.get("source") or {}).get("url") or url))
        for rule in content.get("day_type_overrides", []):
            hints = _hints("working days calendar days relaxation", rule.get("ambiguity"))
            clauses.append(_make(instrument, digest, rule, hints, url))
    return clauses
