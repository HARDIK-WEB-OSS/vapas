from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from vapas.analytics import events as analytics
from vapas.analytics.events import statement_question_counts
from vapas.classify.channel_rules import Channel, Kind, classify
from vapas.db import findings as finding_store
from vapas.db import statements as store
from vapas.detect.engine import detect
from vapas.detect.model import DETECTOR_VERSION, Finding, Txn, TxnKey
from vapas.ingest.model import Direction
from vapas.jobs import queue
from vapas.jobs.context import WorkerContext
from vapas.rules.loader import load_rulebook
from vapas.security.crypto import FieldCipher
from vapas.security.user_keys import NARRATION, user_cipher

IST = timezone(timedelta(hours=5, minutes=30))
SNAPSHOT = "findings.snapshot"
MANDATE_GROUP = "mandate.group"


def today_ist(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(IST).date()


def to_txn(row: Any, cipher: FieldCipher, bank_code: str = "UNKNOWN") -> Txn:
    narration = cipher.decrypt(bytes(row.narration_enc), NARRATION)
    direction = Direction(row.direction)
    fallback = classify(narration, direction)
    references = frozenset(bytes(r) for r in (row.ref_hmac, row.ext_ref_hmac) if r is not None)
    return Txn(
        key=TxnKey(row.id, row.txn_date),
        statement_id=str(row.statement_id),
        row_index=row.row_index,
        txn_date=row.txn_date,
        value_date=row.value_date,
        direction=direction,
        amount_paise=row.amount_paise,
        balance_paise=row.balance_paise,
        channel=Channel(row.channel) if row.channel else fallback.channel,
        kind=Kind(row.kind) if row.kind else fallback.kind,
        narration=narration,
        references=references,
        bank_code=bank_code,
    )


def _txn_facts(txn: Txn) -> dict[str, Any]:
    return {
        "date": txn.txn_date,
        "value_date": txn.value_date,
        "amount_paise": txn.amount_paise,
        "channel": txn.channel.value,
        "narration": txn.narration,
    }


def snapshot(finding: Finding, by_key: dict[TxnKey, Txn]) -> dict[str, Any]:
    debit = by_key.get(finding.debit) if finding.debit else None
    return {
        "debit": _txn_facts(debit) if debit else None,
        "reversals": [_txn_facts(by_key[k]) for k in finding.reversals if k in by_key],
        "facts": finding.facts,
    }


async def handle_detect(ctx: WorkerContext, job: queue.Job) -> None:
    if job.user_id is None:
        raise ValueError("detect job without a user")
    user_id = job.user_id
    rulebook = load_rulebook(ctx.settings.rules_dir)
    config = {"claim_lookback_months": ctx.settings.claim_lookback_months, "detector_version": DETECTOR_VERSION}
    policy_sha = rulebook.policy_sha256(config)
    async with ctx.db.as_user(user_id) as conn:
        version = await finding_store.rule_version_id(conn, rulebook, policy_sha)
        cipher = await user_cipher(conn, ctx.keys, user_id)
        rows = await store.transactions_for_user(conn, user_id, reconciled_only=True)
        banks = {s.id: s.bank_code or "UNKNOWN" for s in await store.list_for_user(conn, user_id, limit=10_000)}
        txns = [to_txn(r, cipher, banks.get(r.statement_id, "UNKNOWN")) for r in rows]
        by_key = {t.key: t for t in txns}
        found = detect(
            txns,
            await finding_store.answers(conn, user_id),
            rulebook,
            today_ist(),
            ctx.settings.claim_lookback_months,
            lambda name: cipher.blind_index(name, MANDATE_GROUP).hex(),
        )
        prepared = [
            (
                f,
                f.key(rulebook.rules_sha256, policy_sha),
                UUID(by_key[f.debit].statement_id) if f.debit in by_key else None,
                cipher.encrypt(finding_store.snapshot_json(snapshot(f, by_key)), SNAPSHOT),
            )
            for f in found
        ]
        await finding_store.replace(conn, user_id, prepared, version, policy_sha.hex())
        parsed_statement = job.payload.get("statement_id") if job.payload.get("reason") == "statement_parsed" else None
        if parsed_statement:
            counts = statement_question_counts(
                parsed_statement, banks.get(UUID(parsed_statement), "UNKNOWN"), txns, found
            )
            await analytics.record(conn, analytics.STATEMENT_ANALYSED, counts)
        await queue.complete(conn, job.id)


async def detect_gave_up(ctx: WorkerContext, job: queue.Job) -> None:
    return None
