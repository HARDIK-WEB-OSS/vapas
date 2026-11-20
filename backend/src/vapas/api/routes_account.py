from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from vapas.auth.deps import ClientIpDep, CurrentUser, CurrentUserDep, ServicesDep
from vapas.auth.passwords import MAX_PASSWORD_LENGTH, verify_password
from vapas.auth.routes import REFRESH_COOKIE, REFRESH_COOKIE_PATH
from vapas.auth.service import CORE_PURPOSE
from vapas.db import repo
from vapas.db import statements as store
from vapas.security.user_keys import NARRATION, REF_NO, user_cipher
from vapas.services import Services
from vapas.storage.object_store import delete_user_objects

EXPORT_FORMAT_VERSION = 1

router = APIRouter(tags=["account"])


class Me(BaseModel):
    id: str
    email: str
    email_verified: bool
    locale: str
    created_at: datetime
    consent_active: bool


class DeleteIn(BaseModel):
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class NoticeOut(BaseModel):
    version: str
    text_en: str
    text_hi: str


class Status(BaseModel):
    status: str


@router.get("/consent/notice")
async def current_consent_notice(services: ServicesDep) -> NoticeOut:
    async with services.db.anonymous() as conn:
        notice = await repo.current_notice(conn)
    if notice is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="no_consent_notice")
    return NoticeOut(version=notice.version, text_en=notice.text_en, text_hi=notice.text_hi)


@router.get("/account/me")
async def me(user: CurrentUserDep) -> Me:
    account = await repo.get_user(user.conn, user.user_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return Me(
        id=str(account.id),
        email=account.email,
        email_verified=account.email_verified_at is not None,
        locale=account.locale,
        created_at=account.created_at,
        consent_active=await repo.has_active_consent(user.conn, user.user_id, CORE_PURPOSE),
    )


@router.get("/account/export")
async def export(user: CurrentUserDep, services: ServicesDep, ip: ClientIpDep) -> JSONResponse:
    data: dict[str, Any] = {
        "format_version": EXPORT_FORMAT_VERSION,
        "exported_at": datetime.now(UTC),
        **await repo.export_user_data(user.conn, user.user_id),
        **await _statement_data(user, services),
    }
    await repo.write_audit(user.conn, user.user_id, "data_exported", services.auth.ip_hash(ip))
    headers = {"Content-Disposition": 'attachment; filename="vapas-export.json"', "Cache-Control": "no-store"}
    return JSONResponse(jsonable_encoder(data), headers=headers)


async def _statement_data(user: CurrentUser, services: Services) -> dict[str, list[dict[str, Any]]]:
    rows = await store.list_for_user(user.conn, user.user_id, limit=10_000)
    statements_out = [
        {
            "id": r.id,
            "status": r.status,
            "file_kind": r.file_kind,
            "bank_code": r.bank_code,
            "period_from": r.period_from,
            "period_to": r.period_to,
            "rows_parsed": r.rows_parsed,
            "reconciled": r.reconciled,
            "created_at": r.created_at,
        }
        for r in rows
    ]
    stored = await store.transactions_for_user(user.conn, user.user_id)
    if not stored:
        return {"statements": statements_out, "transactions": []}
    cipher = await user_cipher(user.conn, services.settings.key_ring(), user.user_id)
    transactions_out = [
        {
            "statement_id": t.statement_id,
            "row_index": t.row_index,
            "txn_date": t.txn_date,
            "value_date": t.value_date,
            "direction": t.direction,
            "amount_paise": t.amount_paise,
            "balance_paise": t.balance_paise,
            "channel": t.channel,
            "kind": t.kind,
            "narration": cipher.decrypt(bytes(t.narration_enc), NARRATION),
            "ref_no": cipher.decrypt(bytes(t.ref_enc), REF_NO) if t.ref_enc else None,
        }
        for t in stored
    ]
    return {"statements": statements_out, "transactions": transactions_out}


@router.post("/account/consent/withdraw")
async def withdraw_consent(user: CurrentUserDep, services: ServicesDep, ip: ClientIpDep) -> Status:
    await repo.withdraw_consent(user.conn, user.user_id, CORE_PURPOSE)
    await repo.write_audit(user.conn, user.user_id, "consent_withdrawn", services.auth.ip_hash(ip))
    return Status(status="withdrawn")


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    body: DeleteIn, response: Response, user: CurrentUserDep, services: ServicesDep, ip: ClientIpDep
) -> None:
    stored = await repo.password_hash_of(user.conn, user.user_id)
    if stored is None or not verify_password(stored, body.password):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="password_incorrect")
    deps = services.dependencies
    await delete_user_objects(deps.s3, deps.bucket, str(user.user_id))
    await repo.write_audit(user.conn, user.user_id, "account_deleted", services.auth.ip_hash(ip))
    await repo.delete_user(user.conn, user.user_id)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)
