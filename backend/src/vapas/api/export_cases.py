import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from vapas.cases.service import LETTER_BODY
from vapas.jobs.detection import SNAPSHOT
from vapas.security.crypto import FieldCipher

FINDINGS_SQL = (
    "SELECT id, detector, level, confidence, status, rule_id, rule_version_id, policy_version, finding_policy, "
    "letter_scope, question, statement_id, t_date, r_date, delay_days, amount_owed_paise, already_paid_paise, "
    "accruing, why, created_at, updated_at, superseded_at, snapshot_enc FROM findings WHERE user_id = :u"
)
PLAIN_QUERIES = {
    "finding_feedback": "SELECT finding_id, verdict, created_at, updated_at FROM finding_feedback WHERE user_id = :u",
    "user_inputs": "SELECT question, subject, answer, entered_at FROM user_inputs WHERE user_id = :u",
    "cases": "SELECT * FROM cases WHERE user_id = :u ORDER BY created_at",
    "case_findings": "SELECT case_id, finding_id FROM case_findings WHERE user_id = :u",
    "case_events": "SELECT case_id, seq, type, payload, at FROM case_events WHERE user_id = :u ORDER BY case_id, seq",
    "reminders": "SELECT case_id, kind, due_on, sent_at, attempts FROM reminders WHERE user_id = :u",
    "notifications": "SELECT case_id, kind, message, created_at, read_at FROM notifications WHERE user_id = :u",
}


async def _rows(conn: AsyncConnection, sql: str, user_id: UUID) -> list[dict[str, Any]]:
    return [dict(row) for row in (await conn.execute(text(sql), {"u": user_id})).mappings()]


async def finding_and_case_data(
    conn: AsyncConnection, user_id: UUID, cipher: FieldCipher
) -> dict[str, list[dict[str, Any]]]:
    findings = await _rows(conn, FINDINGS_SQL, user_id)
    letters = await _rows(
        conn,
        "SELECT id, case_id, kind, language, template_version, polished, approved_at, created_at, body_enc "
        "FROM letters WHERE user_id = :u ORDER BY created_at",
        user_id,
    )
    for finding in findings:
        sealed = bytes(finding.pop("snapshot_enc"))
        finding["snapshot"] = json.loads(cipher.decrypt(sealed, SNAPSHOT))
    for letter in letters:
        sealed = bytes(letter.pop("body_enc"))
        letter["text"] = cipher.decrypt(sealed, LETTER_BODY)
    plain = {name: await _rows(conn, sql, user_id) for name, sql in PLAIN_QUERIES.items()}
    return {"findings": findings, "letters": letters, **plain}
