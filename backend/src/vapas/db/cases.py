import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection

from vapas.cases.timeline import CaseFacts, Event
from vapas.db.models import cases, letters

OPEN_STATES = ("awaiting_reply", "escalation_eligible")


@dataclass(frozen=True)
class CaseRow:
    id: UUID
    user_id: UUID
    state: str
    bank_code: str
    language: str
    sent_on: date | None
    bank_received_on: date | None
    last_communication_on: date | None
    unsatisfied_reply_on: date | None
    escalated_on: date | None
    wait_days: int | None
    escalation_eligible_on: date | None
    filing_deadline_on: date | None
    closed_reason: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class LetterRow:
    id: UUID
    case_id: UUID
    kind: str
    language: str
    template_version: int
    body_enc: bytes
    polished: bool
    guardrail_note: str
    approved_at: datetime | None
    created_at: datetime


CASE_SELECT = select(*(cases.c[name] for name in CaseRow.__dataclass_fields__))
LETTER_SELECT = select(*(letters.c[name] for name in LetterRow.__dataclass_fields__))


def _case(row: Any) -> CaseRow:
    return CaseRow(**dict(row._mapping))


def _letter(row: Any) -> LetterRow:
    values = dict(row._mapping)
    values["body_enc"] = bytes(values["body_enc"])
    return LetterRow(**values)


async def create(
    conn: AsyncConnection, user_id: UUID, bank_code: str, language: str, finding_ids: Sequence[UUID]
) -> UUID:
    case_id = uuid4()
    await conn.execute(
        text("INSERT INTO cases (id, user_id, state, bank_code, language) VALUES (:id, :u, 'draft', :bank, :lang)"),
        {"id": case_id, "u": user_id, "bank": bank_code, "lang": language},
    )
    for finding_id in finding_ids:
        await conn.execute(
            text("INSERT INTO case_findings (case_id, finding_id, user_id) VALUES (:c, :f, :u)"),
            {"c": case_id, "f": finding_id, "u": user_id},
        )
    return case_id


async def get(conn: AsyncConnection, case_id: UUID) -> CaseRow | None:
    row = (await conn.execute(CASE_SELECT.where(cases.c.id == case_id))).first()
    return None if row is None else _case(row)


async def list_for_user(conn: AsyncConnection, user_id: UUID) -> list[CaseRow]:
    query = CASE_SELECT.where(cases.c.user_id == user_id).order_by(cases.c.created_at.desc())
    return [_case(r) for r in await conn.execute(query)]


async def open_timelines(conn: AsyncConnection, user_id: UUID) -> list[CaseRow]:
    query = CASE_SELECT.where(cases.c.user_id == user_id, cases.c.state.in_(OPEN_STATES))
    return [_case(r) for r in await conn.execute(query)]


async def finding_ids(conn: AsyncConnection, case_id: UUID) -> list[UUID]:
    rows = await conn.execute(text("SELECT finding_id FROM case_findings WHERE case_id = :c"), {"c": case_id})
    return [r.finding_id for r in rows]


async def findings_in_cases(conn: AsyncConnection, ids: Sequence[UUID]) -> set[UUID]:
    rows = await conn.execute(
        text("SELECT finding_id FROM case_findings WHERE finding_id = ANY(:ids)"), {"ids": list(ids)}
    )
    return {r.finding_id for r in rows}


async def save(conn: AsyncConnection, case_id: UUID, facts: CaseFacts, deadline_rule_version_id: int | None) -> None:
    deadlines = facts.deadlines
    await conn.execute(
        text(
            """
            UPDATE cases SET state = :state, sent_on = :sent, bank_received_on = :received,
                last_communication_on = :last, unsatisfied_reply_on = :unsatisfied, escalated_on = :escalated,
                wait_days = :wait, escalation_eligible_on = :eligible, filing_deadline_on = :deadline,
                deadline_rule_version_id = coalesce(:version, deadline_rule_version_id), updated_at = now()
            WHERE id = :id
            """
        ),
        {
            "id": case_id,
            "state": facts.state.value,
            "sent": facts.sent_on,
            "received": facts.received_on,
            "last": facts.last_communication_on,
            "unsatisfied": facts.unsatisfied_reply_on,
            "escalated": facts.escalated_on,
            "wait": deadlines.wait_days if deadlines else None,
            "eligible": deadlines.eligible_on if deadlines else None,
            "deadline": deadlines.filing_deadline_on if deadlines else None,
            "version": deadline_rule_version_id if deadlines else None,
        },
    )


async def set_closed_reason(conn: AsyncConnection, case_id: UUID, reason: str) -> None:
    await conn.execute(text("UPDATE cases SET closed_reason = :r WHERE id = :id"), {"r": reason, "id": case_id})


async def append_events(conn: AsyncConnection, case_id: UUID, user_id: UUID, events: Sequence[Event]) -> None:
    current = await conn.scalar(
        text("SELECT coalesce(max(seq), 0) FROM case_events WHERE case_id = :c"), {"c": case_id}
    )
    for offset, (kind, payload) in enumerate(events, 1):
        await conn.execute(
            text(
                "INSERT INTO case_events (case_id, user_id, seq, type, payload) "
                "VALUES (:c, :u, :seq, :type, CAST(:payload AS jsonb))"
            ),
            {
                "c": case_id,
                "u": user_id,
                "seq": int(current or 0) + offset,
                "type": kind,
                "payload": json.dumps(payload),
            },
        )


async def events(conn: AsyncConnection, case_id: UUID) -> list[dict[str, Any]]:
    rows = await conn.execute(
        text("SELECT seq, type, payload, at FROM case_events WHERE case_id = :c ORDER BY seq"), {"c": case_id}
    )
    return [dict(r._mapping) for r in rows]


async def insert_letter(
    conn: AsyncConnection,
    case_id: UUID,
    user_id: UUID,
    kind: str,
    language: str,
    template_version: int,
    body_enc: bytes,
    polished: bool,
    note: str,
) -> UUID:
    letter_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO letters (id, case_id, user_id, kind, language, template_version, body_enc, polished, "
            "guardrail_note) VALUES (:id, :c, :u, :kind, :lang, :tv, :body, :polished, :note)"
        ),
        {
            "id": letter_id,
            "c": case_id,
            "u": user_id,
            "kind": kind,
            "lang": language,
            "tv": template_version,
            "body": body_enc,
            "polished": polished,
            "note": note,
        },
    )
    return letter_id


async def get_letter(conn: AsyncConnection, letter_id: UUID) -> LetterRow | None:
    row = (await conn.execute(LETTER_SELECT.where(letters.c.id == letter_id))).first()
    return None if row is None else _letter(row)


async def approved_letter(conn: AsyncConnection, case_id: UUID, kind: str) -> LetterRow | None:
    query = (
        LETTER_SELECT.where(letters.c.case_id == case_id, letters.c.kind == kind, letters.c.approved_at.is_not(None))
        .order_by(letters.c.approved_at.desc())
        .limit(1)
    )
    row = (await conn.execute(query)).first()
    return None if row is None else _letter(row)


async def letters_for_case(conn: AsyncConnection, case_id: UUID) -> list[LetterRow]:
    query = LETTER_SELECT.where(letters.c.case_id == case_id).order_by(letters.c.created_at.desc())
    return [_letter(r) for r in await conn.execute(query)]


async def approve_letter(conn: AsyncConnection, letter_id: UUID, body_enc: bytes, note: str) -> None:
    await conn.execute(
        text("UPDATE letters SET body_enc = :body, guardrail_note = :note, approved_at = now() WHERE id = :id"),
        {"id": letter_id, "body": body_enc, "note": note},
    )


async def replace_reminders(
    conn: AsyncConnection, case_id: UUID, user_id: UUID, due: Sequence[tuple[str, date]]
) -> None:
    await conn.execute(text("DELETE FROM reminders WHERE case_id = :c AND sent_at IS NULL"), {"c": case_id})
    for kind, on in due:
        await conn.execute(
            text(
                "INSERT INTO reminders (id, case_id, user_id, kind, due_on) VALUES (:id, :c, :u, :k, :d) "
                "ON CONFLICT (case_id, kind) DO NOTHING"
            ),
            {"id": uuid4(), "c": case_id, "u": user_id, "k": kind, "d": on},
        )


async def due_reminders(conn: AsyncConnection, user_id: UUID, today: date) -> list[Any]:
    query = text(
        "SELECT r.id, r.case_id, r.kind, r.due_on, r.attempts FROM reminders r "
        "WHERE r.user_id = :u AND r.sent_at IS NULL AND r.due_on <= :today ORDER BY r.due_on"
    )
    return list(await conn.execute(query, {"u": user_id, "today": today}))


async def mark_reminder(conn: AsyncConnection, reminder_id: UUID, sent: bool) -> None:
    sql = (
        "UPDATE reminders SET sent_at = now(), attempts = attempts + 1 WHERE id = :id"
        if sent
        else "UPDATE reminders SET attempts = attempts + 1 WHERE id = :id"
    )
    await conn.execute(text(sql), {"id": reminder_id})


async def notify(conn: AsyncConnection, user_id: UUID, case_id: UUID | None, kind: str, message: str) -> None:
    await conn.execute(
        text("INSERT INTO notifications (id, user_id, case_id, kind, message) VALUES (:id, :u, :c, :k, :m)"),
        {"id": uuid4(), "u": user_id, "c": case_id, "k": kind, "m": message},
    )


async def notifications(conn: AsyncConnection, user_id: UUID, unread_only: bool) -> list[dict[str, Any]]:
    query = "SELECT id, case_id, kind, message, created_at, read_at FROM notifications WHERE user_id = :u"
    if unread_only:
        query += " AND read_at IS NULL"
    rows = await conn.execute(text(query + " ORDER BY created_at DESC LIMIT 100"), {"u": user_id})
    return [dict(r._mapping) for r in rows]


async def mark_read(conn: AsyncConnection, notification_id: UUID) -> int:
    result = await conn.execute(
        text("UPDATE notifications SET read_at = now() WHERE id = :id AND read_at IS NULL"), {"id": notification_id}
    )
    return result.rowcount


async def current_rule_version(conn: AsyncConnection, rules_sha256: bytes) -> int | None:
    value = await conn.scalar(
        text("SELECT id FROM rule_versions WHERE rules_sha256 = :s ORDER BY id DESC LIMIT 1"), {"s": rules_sha256}
    )
    return None if value is None else int(value)


async def user_email(conn: AsyncConnection, user_id: UUID) -> str | None:
    value = await conn.scalar(text("SELECT email FROM users WHERE id = :u"), {"u": user_id})
    return None if value is None else str(value)
