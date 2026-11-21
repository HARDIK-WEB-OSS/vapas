import hashlib
import io
from collections.abc import Sequence
from pathlib import Path

import pdfplumber
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from vapas.knowledge.clauses import PDF, Clause, Instrument, instrument_of, rule_files
from vapas.knowledge.segment import segment

PDF_PREFIXES = {"rbi.dpss_629_2019": "Para", "rbi.rbios_2026": "Clause", "rbi.rbios_2021": "Clause"}

DELETE = text("DELETE FROM circular_clauses WHERE instrument_id = :instrument AND source = :source")
INSERT = text(
    """
    INSERT INTO circular_clauses (
        instrument_id, instrument_title, instrument_ref, clause, rule_id, body, search_hints, source,
        source_sha256, url, page, legal_status, verified
    ) VALUES (
        :instrument_id, :instrument_title, :instrument_ref, :clause, :rule_id, :body, :search_hints, :source,
        :source_sha256, :url, :page, :legal_status, :verified
    )
    """
)


class SourceRefusedError(ValueError):
    pass


def instrument(instrument_id: str, rules_dir: Path | None = None) -> Instrument:
    for content in rule_files(rules_dir).values():
        found = instrument_of(content)
        if found.id == instrument_id:
            return found
    raise SourceRefusedError(f"unknown instrument {instrument_id}")


def verified_pdf_bytes(path: Path, expected_sha256: str | None) -> bytes:
    if not expected_sha256:
        raise SourceRefusedError("no sha256 is recorded in the rule YAML for this PDF; record it first (P4)")
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_sha256.lower():
        raise SourceRefusedError(f"sha256 mismatch: file {actual[:12]}... vs YAML {expected_sha256[:12]}...")
    return data


def pdf_clauses(data: bytes, source: Instrument) -> list[Clause]:
    prefix = PDF_PREFIXES.get(source.id)
    if prefix is None or source.pdf_url is None:
        raise SourceRefusedError(f"no PDF ingestion is configured for {source.id}")
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    digest = hashlib.sha256(data).digest()
    return [
        Clause(
            instrument_id=source.id,
            instrument_title=source.title,
            instrument_ref=source.ref,
            clause=found.label,
            rule_id=None,
            body=found.text,
            search_hints="",
            source=PDF,
            source_sha256=digest,
            url=source.pdf_url,
            page=found.page,
            legal_status=source.legal_status,
            verified=False,
        )
        for found in segment(pages, prefix)
    ]


async def replace(conn: AsyncConnection, clauses: Sequence[Clause]) -> int:
    for instrument_id, source in sorted({(c.instrument_id, c.source) for c in clauses}):
        await conn.execute(DELETE, {"instrument": instrument_id, "source": source})
    for clause in clauses:
        await conn.execute(INSERT, clause.__dict__)
    return len(clauses)
