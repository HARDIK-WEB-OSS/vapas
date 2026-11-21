import asyncio
import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from fpdf import FPDF
from sqlalchemy.ext.asyncio import create_async_engine

from vapas.config import Settings
from vapas.knowledge.clauses import Clause, Instrument, clauses_from_rules
from vapas.knowledge.ingest import pdf_clauses, replace
from vapas.knowledge.search import search

from .conftest import bearer, owner_sql, verified_user
from .test_rls_isolation import attempt

pytestmark = pytest.mark.integration

QUESTIONS = Path(__file__).resolve().parents[2] / "src" / "vapas" / "knowledge" / "eval_questions.yaml"
RECALL_AT_5_TARGET = 0.9


def load(settings: Settings, clauses: list[Clause]) -> None:
    url = settings.migration_database_url
    assert url is not None

    async def run() -> None:
        engine = create_async_engine(url.get_secret_value())
        try:
            async with engine.begin() as conn:
                await replace(conn, clauses)
        finally:
            await engine.dispose()

    asyncio.run(run())


@pytest.fixture(autouse=True)
def rule_clauses(live_settings: Settings) -> Iterator[None]:
    owner_sql(live_settings, "TRUNCATE circular_clauses")
    load(live_settings, clauses_from_rules())
    yield
    owner_sql(live_settings, "TRUNCATE circular_clauses")
    load(live_settings, clauses_from_rules())


def test_search_returns_exact_citations(client: TestClient) -> None:
    token = verified_user(client, "asha@example.in")
    response = client.get(
        "/knowledge/search", params={"q": "ATM debited but cash not dispensed"}, headers=bearer(token)
    )
    body = response.json()
    assert (response.status_code, body["result"]) == (200, "found")
    top = body["hits"][0]
    assert (top["instrument_id"], top["clause"], top["verified"]) == ("rbi.dpss_629_2019", "Annex Sl. 1(a)", True)
    assert top["source_text"].startswith("Pro-active reversal (R) of failed transaction within a maximum of T + 5 days")
    assert top["citation"] == "Annex Sl. 1(a), " + top["instrument_title"] + " (RBI/2019-20/67)"
    assert top["url"].startswith("https://rbidocs.rbi.org.in/")


def test_unanswerable_question_is_not_found(client: TestClient) -> None:
    token = verified_user(client, "asha@example.in")
    body = client.get("/knowledge/search", params={"q": "zzzqx wobblefrump"}, headers=bearer(token)).json()
    assert body == {"query": "zzzqx wobblefrump", "result": "not_found", "hits": []}


def test_search_needs_login(client: TestClient) -> None:
    assert client.get("/knowledge/search", params={"q": "ATM"}).status_code == 401


def test_recall_at_5_meets_the_target(live_settings: Settings) -> None:
    questions = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    assert len(questions) == 30

    async def run() -> float:
        engine = create_async_engine(live_settings.database_url.get_secret_value())
        try:
            async with engine.connect() as conn:
                found = 0
                for q in questions:
                    hits = await search(conn, q["question"])
                    found += any([h.instrument_id, h.clause] == q["expected"] for h in hits)
                return found / len(questions)
        finally:
            await engine.dispose()

    assert asyncio.run(run()) >= RECALL_AT_5_TARGET


def test_pdf_clauses_are_ingested_and_searchable(client: TestClient, live_settings: Settings) -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)
    for line in (
        "Reserve Bank - Integrated Ombudsman Scheme, 2026",
        "12. Procedure for redress of grievance",
        "(1) The RBI Ombudsman shall endeavour to promote a settlement of the complaint by facilitation.",
        "(2) The Ombudsman may pass an Award where the complaint is not settled by agreement.",
    ):
        pdf.cell(0, 8, line, new_x="LMARGIN", new_y="NEXT")
    data = bytes(pdf.output())
    source = Instrument(
        id="rbi.rbios_2026",
        title="Reserve Bank - Integrated Ombudsman Scheme, 2026",
        ref="Press Release 2025-2026/1936",
        legal_status="in_force",
        page_url="https://www.rbi.org.in/x",
        pdf_url="https://rbidocs.rbi.org.in/rdocs/content/pdfs/SCHEME16012026_A.pdf",
        pdf_sha256=hashlib.sha256(data).hexdigest(),
    )
    clauses = pdf_clauses(data, source)
    assert [c.clause for c in clauses] == ["Clause 12", "Clause 12(1)", "Clause 12(2)"]
    assert all(not c.verified and c.source == "pdf" for c in clauses)
    load(live_settings, clauses)
    token = verified_user(client, "asha@example.in")
    body = client.get("/knowledge/search", params={"q": "Ombudsman award settlement"}, headers=bearer(token)).json()
    assert "Clause 12(2)" in [h["clause"] for h in body["hits"]]
    rule_rows = owner_sql(live_settings, "SELECT count(*) AS n FROM circular_clauses WHERE source = 'rule_yaml'")
    assert rule_rows[0].n == 26


def test_app_role_cannot_change_the_clause_table(client: TestClient, live_settings: Settings) -> None:
    token = verified_user(client, "asha@example.in")
    user_id = client.get("/account/me", headers=bearer(token)).json()["id"]
    assert "permission denied" in attempt(live_settings, user_id, "UPDATE circular_clauses SET body = 'forged'")
    assert "permission denied" in attempt(live_settings, user_id, "DELETE FROM circular_clauses")
