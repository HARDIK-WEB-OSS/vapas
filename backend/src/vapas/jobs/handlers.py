import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from vapas.db import statements as store
from vapas.ingest.layouts import Layout
from vapas.ingest.llm_fallback import FallbackRejectedError, infer_layout
from vapas.ingest.model import (
    FileKind,
    NeedsPasswordError,
    ParsedRow,
    ParsedStatement,
    ParseError,
    UnknownLayoutError,
    WrongPasswordError,
)
from vapas.ingest.reconcile import reconcile
from vapas.ingest.sandbox import ParseTimeoutError, parse_isolated
from vapas.jobs import queue
from vapas.jobs.context import WorkerContext
from vapas.llm_gateway.gateway import BudgetExceededError, LlmUnavailableError, SensitiveDataBlockedError
from vapas.security.crypto import FieldCipher
from vapas.security.upload_guard import UploadRejectedError, check_upload
from vapas.security.user_keys import NARRATION, REF_NO, take_pdf_password, user_cipher
from vapas.storage.object_store import delete_object, read_object

log = logging.getLogger(__name__)
PROCESSING_FAILED = "processing_failed"


@dataclass(frozen=True)
class Outcome:
    status: str
    code: str | None = None
    parsed: ParsedStatement | None = None
    delete_raw: bool = True


def _encrypted_row(cipher: FieldCipher, user_id: UUID, statement_id: UUID, row: ParsedRow) -> dict[str, Any]:
    ref = row.ref_no.strip() if row.ref_no else None
    return {
        "txn_date": row.txn_date,
        "user_id": user_id,
        "statement_id": statement_id,
        "row_index": row.row_index,
        "value_date": row.value_date,
        "direction": row.direction.value,
        "amount_paise": row.amount_paise,
        "balance_paise": row.balance_paise,
        "narration_enc": cipher.encrypt(row.narration, NARRATION),
        "ref_enc": cipher.encrypt(ref, REF_NO) if ref else None,
        "ref_hmac": cipher.blind_index(ref, REF_NO) if ref else None,
    }


async def _parse(
    ctx: WorkerContext, data: bytes, kind: FileKind, password: str | None, layouts: Sequence[Layout]
) -> ParsedStatement:
    timeout = ctx.settings.parse_timeout_seconds
    return await asyncio.to_thread(parse_isolated, data, kind, password, layouts, timeout)


async def _fallback(
    ctx: WorkerContext, user_id: UUID, data: bytes, kind: FileKind, password: str | None, sketch: Sequence[str]
) -> Outcome:
    if not ctx.gateway.available:
        return Outcome(store.NEEDS_REVIEW, "unknown_layout")
    try:
        async with ctx.db.as_user(user_id) as conn:
            layout = await infer_layout(ctx.gateway, conn, user_id, sketch)
        parsed = await _parse(ctx, data, kind, password, (layout,))
    except (LlmUnavailableError, BudgetExceededError, SensitiveDataBlockedError, FallbackRejectedError) as error:
        return Outcome(store.NEEDS_REVIEW, error.code)
    except ParseError:
        return Outcome(store.NEEDS_REVIEW, "unknown_layout")
    if not reconcile(parsed.rows, parsed.opening_balance_paise).reconciled:
        return Outcome(store.NEEDS_REVIEW, "llm_layout_unreconciled")
    return Outcome(store.PARSED, parsed=parsed)


async def _outcome(ctx: WorkerContext, row: store.StatementRow, cipher: FieldCipher) -> Outcome:
    deps = ctx.dependencies
    data = await asyncio.to_thread(read_object, deps.s3, deps.bucket, row.object_key)
    if data is None:
        return Outcome(store.FAILED, "file_missing", delete_raw=False)
    if hashlib.sha256(data).digest() != row.content_sha256:
        return Outcome(store.FAILED, "hash_mismatch")
    try:
        kind = check_upload(data, FileKind(row.file_kind))
    except UploadRejectedError as error:
        return Outcome(store.FAILED, error.code)
    password = await take_pdf_password(deps.redis, cipher, row.id) if kind is FileKind.PDF else None
    try:
        return Outcome(store.PARSED, parsed=await _parse(ctx, data, kind, password, ()))
    except (NeedsPasswordError, WrongPasswordError) as error:
        return Outcome(store.NEEDS_PASSWORD, error.code, delete_raw=False)
    except UnknownLayoutError as error:
        return await _fallback(ctx, row.user_id, data, kind, password, error.sketch)
    except UploadRejectedError as error:
        return Outcome(store.FAILED, error.code)
    except ParseTimeoutError:
        raise
    except ParseError as error:
        return Outcome(store.FAILED, error.code)


def _parse_result(parsed: ParsedStatement) -> dict[str, Any]:
    check = reconcile(parsed.rows, parsed.opening_balance_paise)
    period = parsed.period
    if not parsed.rows:
        status, code = store.NEEDS_REVIEW, "no_transactions"
    elif check.reconciled:
        status, code = store.PARSED, None
    else:
        status, code = store.NEEDS_REVIEW, "balance_mismatch"
    return {
        "status": status,
        "failure_code": code,
        "bank_code": parsed.bank_code,
        "layout_code": parsed.layout_code,
        "parser_version": parsed.parser_version,
        "period_from": period[0] if period else None,
        "period_to": period[1] if period else None,
        "rows_parsed": len(parsed.rows),
        "rows_rejected": parsed.rejected_rows,
        "reconciled": check.reconciled,
        "reconcile_breaks": len(check.breaks),
        "row_order": check.order.value,
    }


async def handle_parse(ctx: WorkerContext, job: queue.Job) -> None:
    if job.user_id is None:
        raise ValueError("parse job without a user")
    user_id = job.user_id
    statement_id = UUID(job.payload["statement_id"])
    async with ctx.db.as_user(user_id) as conn:
        row = await store.get(conn, statement_id)
        if row is None or row.status not in (store.QUEUED, store.PARSING):
            await queue.complete(conn, job.id)
            return
        cipher = await user_cipher(conn, ctx.keys, user_id)
        await store.set_status(conn, statement_id, store.PARSING)
    outcome = await _outcome(ctx, row, cipher)
    async with ctx.db.as_user(user_id) as conn:
        if outcome.parsed is not None:
            rows = outcome.parsed.rows
            await store.ensure_partitions(conn, [r.txn_date.replace(day=1) for r in rows])
            await store.replace_transactions(
                conn, statement_id, [_encrypted_row(cipher, user_id, statement_id, r) for r in rows]
            )
            await store.record_parse(conn, statement_id, _parse_result(outcome.parsed))
        else:
            await store.set_status(conn, statement_id, outcome.status, outcome.code)
        await queue.complete(conn, job.id)
    if outcome.delete_raw:
        deps = ctx.dependencies
        await asyncio.to_thread(delete_object, deps.s3, deps.bucket, row.object_key)
        async with ctx.db.as_user(user_id) as conn:
            await store.mark_raw_deleted(conn, statement_id)
    log.info("statement processed", extra={"statement_id": str(statement_id), "status": outcome.status})


async def parse_gave_up(ctx: WorkerContext, job: queue.Job) -> None:
    if job.user_id is None:
        return
    async with ctx.db.as_user(job.user_id) as conn:
        await store.set_status(conn, UUID(job.payload["statement_id"]), store.FAILED, PROCESSING_FAILED)


Handler = Callable[[WorkerContext, queue.Job], Awaitable[None]]
HANDLERS: dict[str, tuple[Handler, Handler]] = {"parse": (handle_parse, parse_gave_up)}
