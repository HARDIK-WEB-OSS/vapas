import hashlib
from pathlib import Path

import pytest
import yaml

from vapas.knowledge.clauses import RULE_YAML, clauses_from_rules
from vapas.knowledge.ingest import SourceRefusedError, verified_pdf_bytes
from vapas.knowledge.search import expand
from vapas.knowledge.segment import segment
from vapas.rules.loader import default_rules_dir

SCHEME_TEXT = """Reserve Bank - Integrated Ombudsman Scheme, 2026
10. Grounds for non-maintainability of a complaint
(1) No complaint for deficiency in service shall lie under the Scheme unless:
(a) the complaint is addressed to the RBI Ombudsman directly and not merely marked in copy;
(b) the complaint is lodged by the Complainant personally or through an authorised representative;
3
(2) No complaint shall lie under the Scheme in matters involving commercial judgement of a Regulated Entity.
11. Procedure for filing a complaint
(1) The complaint may be lodged online through the portal of the Reserve Bank.
"""


def test_segmenter_labels_every_numbered_clause() -> None:
    found = {s.label: s for s in segment([SCHEME_TEXT], "Clause")}
    assert list(found) == [
        "Clause 10",
        "Clause 10(1)",
        "Clause 10(1)(a)",
        "Clause 10(1)(b)",
        "Clause 10(2)",
        "Clause 11",
        "Clause 11(1)",
    ]
    assert found["Clause 10(1)(a)"].text.startswith("the complaint is addressed to the RBI Ombudsman directly")
    assert "3" not in found["Clause 10(1)(b)"].text.split()


def test_segmenter_keeps_the_page_where_a_clause_starts() -> None:
    pages = ["1. First paragraph of the circular text here.", "2. Second paragraph starts on page two of it."]
    assert [(s.label, s.page) for s in segment(pages, "Para")] == [("Para 1", 1), ("Para 2", 2)]


def test_text_before_the_first_number_is_ignored() -> None:
    assert segment(["Title only, no numbered clauses at all here"], "Para") == []


def test_rule_clauses_use_only_verified_source_text() -> None:
    clauses = clauses_from_rules()
    quotes = {}
    for path in sorted((default_rules_dir() / "rbi").glob("*.yaml")):
        content = yaml.safe_load(path.read_text(encoding="utf-8"))
        for key in ("tat_rules", "ombudsman_rules", "day_type_overrides"):
            quotes.update({r["id"]: r["quote"] for r in content.get(key, [])})
    assert len(clauses) == len(quotes) == 26
    assert all(c.source == RULE_YAML and c.body == quotes[c.rule_id] for c in clauses if c.rule_id)
    paraphrases = [c for c in clauses if c.instrument_id == "rbi.rbios_2026"]
    assert all(c.search_hints and c.search_hints not in c.body for c in paraphrases)


def test_pdf_without_a_recorded_hash_is_refused(tmp_path: Path) -> None:
    pdf = tmp_path / "scheme.pdf"
    pdf.write_bytes(b"%PDF-1.7 synthetic")
    with pytest.raises(SourceRefusedError, match="no sha256"):
        verified_pdf_bytes(pdf, None)


def test_pdf_with_a_different_hash_is_refused(tmp_path: Path) -> None:
    pdf = tmp_path / "scheme.pdf"
    pdf.write_bytes(b"%PDF-1.7 synthetic")
    with pytest.raises(SourceRefusedError, match="mismatch"):
        verified_pdf_bytes(pdf, "0" * 64)
    assert verified_pdf_bytes(pdf, hashlib.sha256(pdf.read_bytes()).hexdigest()) == pdf.read_bytes()


def test_everyday_words_are_expanded_to_legal_terms() -> None:
    words = expand("Money deducted, I want a refund from the shop")
    assert {"debited", "reversal", "merchant"} <= set(words.split())
    assert expand("!!!") == ""
