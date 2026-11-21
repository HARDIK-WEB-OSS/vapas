import json
from collections import Counter
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from vapas.detect.model import Finding, Txn

STATEMENT_ANALYSED = "statement_analysed"
INSERT_EVENT = text("INSERT INTO analytics_events (event_type, props) VALUES (:event, CAST(:props AS jsonb))")


def statement_question_counts(
    statement_id: str, bank_code: str, transactions: Sequence[Txn], findings: Sequence[Finding]
) -> dict[str, Any]:
    keys = {t.key for t in transactions if t.statement_id == statement_id}
    questions = Counter(f.question.value for f in findings if f.question is not None and f.debit in keys)
    levels = Counter(f.level.value for f in findings if f.debit in keys)
    return {
        "bank_code": bank_code,
        "rows": len(keys),
        "questions_total": sum(questions.values()),
        "questions_by_type": dict(sorted(questions.items())),
        "findings_by_level": dict(sorted(levels.items())),
    }


async def record(conn: AsyncConnection, event: str, props: dict[str, Any]) -> None:
    await conn.execute(INSERT_EVENT, {"event": event, "props": json.dumps(props, sort_keys=True)})
