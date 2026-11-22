import json
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from vapas.auth.deps import CurrentUser, CurrentUserDep, ServicesDep
from vapas.db import findings as store
from vapas.db.statements import DETECT_REQUESTED, insert_event
from vapas.detect.model import Question, TxnKey
from vapas.jobs.detection import SNAPSHOT
from vapas.security.user_keys import user_cipher

router = APIRouter(prefix="/findings", tags=["findings"])


class FindingOut(BaseModel):
    id: UUID
    detector: str
    level: str
    confidence: str
    status: str
    rule_id: str | None
    letter_scope: str | None
    question: str | None
    t_date: date | None
    r_date: date | None
    delay_days: int | None
    amount_owed_paise: int | None
    already_paid_paise: int
    accruing: bool
    why: str
    created_at: datetime
    feedback: str | None = None


class FindingDetail(FindingOut):
    snapshot: dict[str, Any]


class AnswerIn(BaseModel):
    value: bool | None = None
    revoked_on: date | None = None
    proof: bool | None = None


class FeedbackIn(BaseModel):
    verdict: Literal["correct", "wrong", "not_sure"]


class StatusIn(BaseModel):
    status: Literal["confirmed", "dismissed", "open"]


class Accepted(BaseModel):
    status: str


def _out(row: store.StoredFinding, feedback: str | None = None) -> FindingOut:
    fields = {name: getattr(row, name) for name in FindingOut.model_fields if name != "feedback"}
    return FindingOut(**fields, feedback=feedback)


async def _owned(user: CurrentUser, finding_id: UUID) -> store.StoredFinding:
    row = await store.get(user.conn, finding_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return row


def _answer(row: store.StoredFinding, body: AnswerIn) -> tuple[str, dict[str, Any]]:
    if row.question in (Question.PAYEE_WAS_MERCHANT, Question.PAYMENT_FAILED):
        if body.value is None or row.debit_txn_id is None or row.debit_txn_date is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="value_required")
        return store.txn_subject(TxnKey(row.debit_txn_id, row.debit_txn_date)), {"value": body.value}
    if row.question == Question.MANDATE_REVOKED:
        if body.revoked_on is None or body.proof is None or row.group_key is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="revocation_required")
        if body.revoked_on > date.today():
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="date_in_future")
        return row.group_key, {"revoked_on": body.revoked_on.isoformat(), "proof": body.proof}
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="no_question")


@router.get("")
async def list_findings(user: CurrentUserDep) -> list[FindingOut]:
    verdicts = await store.feedback_by_finding(user.conn, user.user_id)
    return [_out(row, verdicts.get(row.id)) for row in await store.current(user.conn, user.user_id)]


@router.get("/{finding_id}")
async def get_finding(finding_id: UUID, user: CurrentUserDep, services: ServicesDep) -> FindingDetail:
    row = await _owned(user, finding_id)
    cipher = await user_cipher(user.conn, services.settings.key_ring(), user.user_id)
    snapshot = json.loads(cipher.decrypt(row.snapshot_enc, SNAPSHOT))
    return FindingDetail(**_out(row).model_dump(), snapshot=snapshot)


@router.post("/{finding_id}/answer", status_code=status.HTTP_202_ACCEPTED)
async def answer(finding_id: UUID, body: AnswerIn, user: CurrentUserDep) -> Accepted:
    row = await _owned(user, finding_id)
    if row.question is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="no_question")
    subject, value = _answer(row, body)
    await store.save_answer(user.conn, user.user_id, row.question, subject, value)
    await insert_event(user.conn, DETECT_REQUESTED, user.user_id, {"request_id": str(uuid4()), "reason": "answer"})
    return Accepted(status="recomputing")


@router.post("/{finding_id}/status")
async def set_status(finding_id: UUID, body: StatusIn, user: CurrentUserDep) -> Accepted:
    await _owned(user, finding_id)
    await store.set_status(user.conn, finding_id, body.status)
    return Accepted(status=body.status)


@router.post("/{finding_id}/feedback")
async def give_feedback(finding_id: UUID, body: FeedbackIn, user: CurrentUserDep) -> Accepted:
    await _owned(user, finding_id)
    await store.save_feedback(user.conn, user.user_id, finding_id, body.verdict)
    return Accepted(status=body.verdict)
