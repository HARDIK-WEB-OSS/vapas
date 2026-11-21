import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from vapas.db.models import findings, rule_versions, user_inputs
from vapas.detect.model import DETECTOR_VERSION, Finding, Question, TxnKey, UserAnswers
from vapas.rules.loader import RuleBook


@dataclass(frozen=True)
class StoredFinding:
    id: UUID
    detector: str
    level: str
    confidence: str
    status: str
    rule_id: str | None
    letter_scope: str | None
    question: str | None
    group_key: str | None
    statement_id: UUID | None
    debit_txn_id: int | None
    debit_txn_date: date | None
    t_date: date | None
    r_date: date | None
    delay_days: int | None
    amount_owed_paise: int | None
    already_paid_paise: int
    accruing: bool
    why: str
    snapshot_enc: bytes
    created_at: datetime


COLUMNS = [findings.c[name] for name in StoredFinding.__dataclass_fields__]


def txn_subject(key: TxnKey) -> str:
    return f"txn:{key.id}:{key.txn_date.isoformat()}"


async def rule_version_id(conn: AsyncConnection, rulebook: RuleBook, policy_sha: bytes) -> int:
    lookup = select(rule_versions.c.id).where(
        rule_versions.c.rules_sha256 == rulebook.rules_sha256, rule_versions.c.policy_sha256 == policy_sha
    )
    found = await conn.scalar(lookup)
    if found is not None:
        return int(found)
    statement = (
        insert(rule_versions)
        .values(
            rules_sha256=rulebook.rules_sha256,
            policy_sha256=policy_sha,
            legal_content=rulebook.legal_content,
            policy_content=rulebook.policy_content,
        )
        .on_conflict_do_nothing(index_elements=["rules_sha256", "policy_sha256"])
        .returning(rule_versions.c.id)
    )
    inserted = await conn.scalar(statement)
    if inserted is None:
        inserted = await conn.scalar(lookup)
    if inserted is None:
        raise RuntimeError("rule version could not be stored")
    return int(inserted)


async def answers(conn: AsyncConnection, user_id: UUID) -> UserAnswers:
    rows = await conn.execute(
        select(user_inputs.c.question, user_inputs.c.subject, user_inputs.c.answer).where(
            user_inputs.c.user_id == user_id
        )
    )
    result = UserAnswers()
    for question, subject, answer in rows:
        if question in (Question.PAYEE_WAS_MERCHANT, Question.PAYMENT_FAILED):
            _, txn_id, txn_day = subject.split(":")
            target = result.payee_was_merchant if question == Question.PAYEE_WAS_MERCHANT else result.payment_failed
            target[TxnKey(int(txn_id), date.fromisoformat(txn_day))] = bool(answer["value"])
        elif question == Question.MANDATE_REVOKED and answer.get("revoked_on"):
            result.mandate_revoked_on[subject] = date.fromisoformat(answer["revoked_on"])
            result.mandate_proof[subject] = bool(answer.get("proof"))
    return result


async def save_answer(
    conn: AsyncConnection, user_id: UUID, question: str, subject: str, answer: dict[str, Any]
) -> None:
    statement = (
        insert(user_inputs)
        .values(id=uuid4(), user_id=user_id, question=question, subject=subject, answer=answer)
        .on_conflict_do_update(
            index_elements=["user_id", "question", "subject"], set_={"answer": answer, "entered_at": func.now()}
        )
    )
    await conn.execute(statement)


async def replace(
    conn: AsyncConnection,
    user_id: UUID,
    found: Sequence[tuple[Finding, bytes, UUID | None, bytes]],
    version_id: int,
    policy_version: str,
) -> int:
    keys = [key for _, key, _, _ in found]
    for finding, key, statement_id, snapshot in found:
        values = {
            "detector": finding.detector.value,
            "level": finding.level.value,
            "confidence": finding.confidence.value,
            "rule_id": finding.rule_id,
            "rule_version_id": version_id,
            "policy_version": policy_version,
            "detector_version": DETECTOR_VERSION,
            "finding_policy": finding.finding_policy,
            "letter_scope": finding.letter_scope,
            "question": finding.question.value if finding.question else None,
            "group_key": finding.group_key,
            "statement_id": statement_id,
            "debit_txn_id": finding.debit.id if finding.debit else None,
            "debit_txn_date": finding.debit.txn_date if finding.debit else None,
            "t_date": finding.t_date,
            "r_date": finding.r_date,
            "delay_days": finding.delay_days,
            "amount_owed_paise": finding.amount_owed_paise,
            "already_paid_paise": finding.already_paid_paise,
            "accruing": finding.accruing,
            "why": finding.why,
            "snapshot_enc": snapshot,
        }
        statement = (
            insert(findings)
            .values(id=uuid4(), user_id=user_id, finding_key=key, **values)
            .on_conflict_do_update(
                index_elements=["user_id", "finding_key"],
                set_={**values, "updated_at": func.now(), "superseded_at": None},
            )
        )
        await conn.execute(statement)
    stale = and_(findings.c.user_id == user_id, findings.c.superseded_at.is_(None))
    if keys:
        stale = and_(stale, findings.c.finding_key.notin_(keys))
    result = await conn.execute(update(findings).where(stale).values(superseded_at=func.now()))
    return result.rowcount


async def current(conn: AsyncConnection, user_id: UUID) -> list[StoredFinding]:
    statement = (
        select(*COLUMNS)
        .where(findings.c.user_id == user_id, findings.c.superseded_at.is_(None))
        .order_by(findings.c.level, findings.c.t_date.desc())
    )
    return [StoredFinding(**dict(r._mapping)) for r in await conn.execute(statement)]


async def get(conn: AsyncConnection, finding_id: UUID) -> StoredFinding | None:
    row = (await conn.execute(select(*COLUMNS).where(findings.c.id == finding_id))).first()
    return None if row is None else StoredFinding(**dict(row._mapping))


async def set_status(conn: AsyncConnection, finding_id: UUID, status: str) -> None:
    await conn.execute(update(findings).where(findings.c.id == finding_id).values(status=status, updated_at=func.now()))


def snapshot_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, default=str)
