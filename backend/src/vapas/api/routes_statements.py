import asyncio
from datetime import date, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from vapas.auth.deps import CurrentUser, CurrentUserDep, ServicesDep
from vapas.auth.passwords import MAX_PASSWORD_LENGTH
from vapas.auth.service import CORE_PURPOSE, RateLimitedError
from vapas.db import repo
from vapas.db import statements as store
from vapas.ingest.model import FileKind
from vapas.security.ratelimit import UPLOADS_PER_USER
from vapas.security.upload_guard import MAX_UPLOAD_BYTES
from vapas.security.user_keys import stash_pdf_password, user_cipher
from vapas.services import Services
from vapas.storage.object_store import PRESIGN_EXPIRY_SECONDS, object_size, presign_upload, raw_key

CONTENT_TYPES = {
    FileKind.PDF: "application/pdf",
    FileKind.CSV: "text/csv",
    FileKind.XLS: "application/vnd.ms-excel",
    FileKind.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

ANALYSIS_NOTES = {
    "balance_mismatch": (
        "The running balance in this statement did not add up row by row, so some rows may have been read wrongly. "
        "To avoid false claims, VAPAS did not use this statement to look for compensation. Try downloading it again "
        "or uploading a different format (PDF, CSV or Excel)."
    ),
    "no_transactions": "No transactions could be read from this statement, so it was not analysed.",
    "unknown_layout": "VAPAS cannot read this bank's statement layout yet, so it was not analysed.",
    "llm_layout_unreconciled": (
        "VAPAS tried to read this layout but the balances did not add up, so it was not analysed."
    ),
    "llm_layout_rejected": "VAPAS cannot read this bank's statement layout yet, so it was not analysed.",
    "llm_unavailable": "VAPAS cannot read this bank's statement layout right now. Please try again later.",
    "llm_budget_exceeded": (
        "VAPAS has reached today's limit for unfamiliar statement layouts. Please try again tomorrow."
    ),
    "needs_password": "This statement is password protected. Enter its password to continue.",
    "wrong_password": "The password was not correct. Enter it again to continue.",
    "file_missing": "The uploaded file was no longer available. Please upload it again.",
    "hash_mismatch": "The uploaded file did not match what your browser sent. Please upload it again.",
    "processing_failed": "This statement could not be processed. Please upload it again.",
}

router = APIRouter(prefix="/statements", tags=["statements"])


class PresignIn(BaseModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0, le=MAX_UPLOAD_BYTES)
    file_kind: FileKind


class PresignOut(BaseModel):
    statement_id: UUID
    duplicate: bool
    status: str
    upload_url: str | None
    content_type: str
    expires_in: int


class PasswordIn(BaseModel):
    password: str | None = Field(default=None, min_length=1, max_length=MAX_PASSWORD_LENGTH)


class StatementOut(BaseModel):
    id: UUID
    status: str
    failure_code: str | None
    file_kind: str
    bank_code: str | None
    rows_parsed: int | None
    reconciled: bool | None
    period_from: date | None
    period_to: date | None
    created_at: datetime
    analysis_note: str | None


def _out(row: store.StatementRow) -> StatementOut:
    return StatementOut(
        id=row.id,
        status=row.status,
        failure_code=row.failure_code,
        file_kind=row.file_kind,
        bank_code=row.bank_code,
        rows_parsed=row.rows_parsed,
        reconciled=row.reconciled,
        period_from=row.period_from,
        period_to=row.period_to,
        created_at=row.created_at,
        analysis_note=ANALYSIS_NOTES.get(row.failure_code or "") if row.status != store.PARSED else None,
    )


async def processing_allowed(user: CurrentUserDep) -> CurrentUser:
    account = await repo.get_user(user.conn, user.user_id)
    if account is None or account.email_verified_at is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="email_not_verified")
    if not await repo.has_active_consent(user.conn, user.user_id, CORE_PURPOSE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="consent_withdrawn")
    return user


AllowedUser = Annotated[CurrentUser, Depends(processing_allowed)]


async def _owned(user: CurrentUser, statement_id: UUID) -> store.StatementRow:
    row = await store.get(user.conn, statement_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return row


async def _stash_password(services: Services, user: CurrentUser, statement_id: UUID, password: str) -> None:
    cipher = await user_cipher(user.conn, services.settings.key_ring(), user.user_id)
    await stash_pdf_password(services.dependencies.redis, cipher, statement_id, password)


@router.post("/presign")
async def presign(body: PresignIn, user: AllowedUser, services: ServicesDep) -> PresignOut:
    sha = bytes.fromhex(body.sha256)
    content_type = CONTENT_TYPES[body.file_kind]
    existing = await store.by_hash(user.conn, user.user_id, sha)
    if existing is not None:
        return PresignOut(
            statement_id=existing.id,
            duplicate=True,
            status=existing.status,
            upload_url=None,
            content_type=content_type,
            expires_in=0,
        )
    decision = await services.limiter.hit(UPLOADS_PER_USER, str(user.user_id))
    if not decision.allowed:
        raise RateLimitedError(decision.retry_after_seconds)
    statement_id = uuid4()
    key = raw_key(str(user.user_id), str(statement_id))
    await store.create(user.conn, statement_id, user.user_id, sha, body.file_kind.value, body.size_bytes, key)
    url = presign_upload(services.presign_client, services.settings.s3_bucket_raw, key, content_type)
    return PresignOut(
        statement_id=statement_id,
        duplicate=False,
        status=store.AWAITING_UPLOAD,
        upload_url=url,
        content_type=content_type,
        expires_in=PRESIGN_EXPIRY_SECONDS,
    )


@router.post("/{statement_id}/confirm", status_code=status.HTTP_202_ACCEPTED)
async def confirm(statement_id: UUID, body: PasswordIn, user: AllowedUser, services: ServicesDep) -> StatementOut:
    row = await _owned(user, statement_id)
    if row.status != store.AWAITING_UPLOAD:
        return _out(row)
    deps = services.dependencies
    size = await asyncio.to_thread(object_size, deps.s3, deps.bucket, row.object_key)
    if size is None or size != row.size_bytes:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="upload_incomplete")
    if body.password:
        await _stash_password(services, user, statement_id, body.password)
    await store.queue_for_parsing(user.conn, row)
    return _out(await _owned(user, statement_id))


@router.post("/{statement_id}/password", status_code=status.HTTP_202_ACCEPTED)
async def provide_password(
    statement_id: UUID, body: PasswordIn, user: AllowedUser, services: ServicesDep
) -> StatementOut:
    row = await _owned(user, statement_id)
    if row.status != store.NEEDS_PASSWORD:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="password_not_needed")
    if row.raw_deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="upload_again")
    if not body.password:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="password_required")
    await _stash_password(services, user, statement_id, body.password)
    await store.queue_for_parsing(user.conn, row)
    return _out(await _owned(user, statement_id))


@router.get("")
async def list_statements(user: CurrentUserDep, response: Response) -> list[StatementOut]:
    response.headers["Cache-Control"] = "no-store"
    return [_out(row) for row in await store.list_for_user(user.conn, user.user_id)]


@router.get("/{statement_id}")
async def get_statement(statement_id: UUID, user: CurrentUserDep) -> StatementOut:
    return _out(await _owned(user, statement_id))
