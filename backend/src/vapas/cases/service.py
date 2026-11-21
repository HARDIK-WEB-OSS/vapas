import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from vapas.cases.evidence_pack import EvidenceRow
from vapas.cases.timeline import CaseFacts, CaseState, Event, compute_deadlines
from vapas.classify.channel_rules import channel_of, reference_of
from vapas.db import cases as store
from vapas.db import findings as finding_store
from vapas.letters.facts import LetterFacts, LetterItem
from vapas.rules.loader import RuleBook
from vapas.security.crypto import FieldCipher

SNAPSHOT = "findings.snapshot"
LETTER_BODY = "letters.body"
CASE_LEVELS = frozenset({"claim", "worth_checking"})
REMINDER_DAYS = {"d30": 30, "d7": 7, "d1": 1}


class CaseError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CaseFinding:
    stored: finding_store.StoredFinding
    snapshot: dict[str, Any]
    bank_code: str


async def _bank_of(conn: AsyncConnection, statement_id: UUID | None) -> str:
    if statement_id is None:
        return "UNKNOWN"
    value = await conn.scalar(text("SELECT bank_code FROM statements WHERE id = :s"), {"s": statement_id})
    return str(value or "UNKNOWN")


async def load_findings(conn: AsyncConnection, ids: Sequence[UUID], cipher: FieldCipher) -> list[CaseFinding]:
    found: list[CaseFinding] = []
    for finding_id in ids:
        stored = await finding_store.get(conn, finding_id)
        if stored is None:
            raise CaseError("finding_not_found", f"finding {finding_id} was not found")
        snapshot = json.loads(cipher.decrypt(stored.snapshot_enc, SNAPSHOT))
        found.append(CaseFinding(stored, snapshot, await _bank_of(conn, stored.statement_id)))
    return found


def check_findings(findings: Sequence[CaseFinding], already_in_case: set[UUID]) -> str:
    if not findings:
        raise CaseError("no_findings", "choose at least one finding")
    for item in findings:
        stored = item.stored
        if stored.id in already_in_case:
            raise CaseError("already_in_case", "a finding is already part of another case")
        if stored.level not in CASE_LEVELS or stored.status == "dismissed":
            raise CaseError("not_actionable", f"a {stored.level} finding cannot be put into a complaint")
    banks = {item.bank_code for item in findings}
    if len(banks) != 1:
        raise CaseError("mixed_banks", "one complaint can only cover findings from one bank")
    return banks.pop()


def letter_item(item: CaseFinding, rulebook: RuleBook) -> LetterItem:
    stored, debit = item.stored, (item.snapshot.get("debit") or {})
    claim = stored.level == "claim" and bool(stored.amount_owed_paise)
    rule = rulebook.tat_rules.get(stored.rule_id or "") if claim else None
    narration = str(debit.get("narration", ""))
    reference = reference_of(narration, channel_of(narration))
    source = (item.snapshot.get("facts") or {}).get("merchant_source") or None
    return LetterItem(
        finding_id=str(stored.id),
        claim=claim and rule is not None,
        rule_id=rule.id if rule else None,
        clause=rule.clause if rule else None,
        instrument_ref=rulebook.instrument_ref if rule else None,
        channel=str(debit.get("channel", "")),
        txn_date=date.fromisoformat(str(debit.get("date") or stored.t_date)),
        amount_paise=int(debit.get("amount_paise") or 0),
        reference_last4=reference[-4:] if reference else None,
        reversal_date=stored.r_date if rule else None,
        due_date=stored.t_date + timedelta(days=rule.deadline_days)
        if rule and stored.t_date and rule.deadline_days is not None
        else None,
        delay_days=stored.delay_days if rule else None,
        per_day_inr=rule.per_day_inr if rule else None,
        compensation_paise=stored.amount_owed_paise if rule else None,
        already_paid_paise=stored.already_paid_paise if rule else 0,
        accruing=stored.accruing,
        merchant_source=source if rule else None,
        rule_disclosure=rule.letter_disclosure if rule else None,
    )


def letter_facts(
    row: store.CaseRow, findings: Sequence[CaseFinding], rulebook: RuleBook, language: str, today: date
) -> LetterFacts:
    items = tuple(sorted((letter_item(f, rulebook) for f in findings), key=lambda i: (i.txn_date, i.finding_id)))
    return LetterFacts(
        bank_code=row.bank_code,
        language=language,
        letter_date=today,
        items=items,
        sent_on=row.sent_on,
        received_on=row.bank_received_on,
        last_communication_on=row.last_communication_on,
    )


def evidence_rows(findings: Sequence[CaseFinding], facts: LetterFacts) -> list[EvidenceRow]:
    narrations = {str(f.stored.id): str((f.snapshot.get("debit") or {}).get("narration", "")) for f in findings}
    return [EvidenceRow(item, narrations.get(item.finding_id, "")) for item in facts.items]


def rule_wait_days(findings: Sequence[CaseFinding], rulebook: RuleBook) -> list[int | None]:
    waits: list[int | None] = [None]
    for item in findings:
        rule = rulebook.tat_rules.get(item.stored.rule_id or "")
        waits.append(rule.escalation_wait_days if rule else None)
    return waits


def case_facts(row: store.CaseRow, rulebook: RuleBook, waits: Sequence[int | None]) -> CaseFacts:
    deadlines = (
        compute_deadlines(rulebook, row.bank_received_on, waits, row.last_communication_on, row.unsatisfied_reply_on)
        if row.bank_received_on
        else None
    )
    return CaseFacts(
        state=CaseState(row.state),
        sent_on=row.sent_on,
        received_on=row.bank_received_on,
        last_communication_on=row.last_communication_on,
        unsatisfied_reply_on=row.unsatisfied_reply_on,
        escalated_on=row.escalated_on,
        deadlines=deadlines,
    )


def reminders_for(facts: CaseFacts, today: date) -> list[tuple[str, date]]:
    deadlines = facts.deadlines
    if deadlines is None or facts.state not in (CaseState.AWAITING_REPLY, CaseState.ESCALATION_ELIGIBLE):
        return []
    due: list[tuple[str, date]] = [("eligible", deadlines.eligible_on)]
    for kind, days in REMINDER_DAYS.items():
        on = deadlines.filing_deadline_on - timedelta(days=days)
        if on >= today:
            due.append((kind, on))
    return due


async def commit(
    conn: AsyncConnection,
    row: store.CaseRow,
    before: CaseFacts,
    after: CaseFacts,
    events: Sequence[Event],
    version_id: int | None,
    today: date,
) -> None:
    await store.save(conn, row.id, after, version_id)
    await store.append_events(conn, row.id, row.user_id, events)
    if after.deadlines != before.deadlines or after.state != before.state:
        await store.replace_reminders(conn, row.id, row.user_id, reminders_for(after, today))
