from collections.abc import Callable
from datetime import date, datetime
from functools import partial
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from vapas.auth.deps import CurrentUser, CurrentUserDep, ServicesDep
from vapas.cases import service
from vapas.cases.evidence_pack import build as build_evidence
from vapas.cases.timeline import (
    CaseFacts,
    EscalationChecks,
    Event,
    TransitionError,
    close,
    days_left,
    escalate,
    mark_sent,
    record_communication,
    record_receipt,
    record_reply,
)
from vapas.db import cases as store
from vapas.jobs.detection import today_ist
from vapas.letters.guardrails import BANK, CMS, check
from vapas.letters.polish import polish
from vapas.letters.render import fill, render_bank_letter, render_cms_complaint
from vapas.letters.templates import TEMPLATE_VERSION
from vapas.llm_gateway.gateway import consume_budget
from vapas.rules.loader import RuleBook, load_rulebook
from vapas.security.user_keys import user_cipher
from vapas.services import Services

router = APIRouter(prefix="/cases", tags=["cases"])
Language = Literal["en", "hi"]


class CreateIn(BaseModel):
    finding_ids: list[UUID] = Field(min_length=1, max_length=20)
    language: Language = "en"


class LetterIn(BaseModel):
    kind: Literal["bank", "cms"]
    polish: bool = False


class ApproveIn(BaseModel):
    customer_name: str = Field(min_length=2, max_length=120)
    account_hint: str = Field(pattern=r"^\d{4}$")
    contact: str = Field(min_length=5, max_length=120)
    bank_name: str | None = Field(default=None, max_length=120)


class DateIn(BaseModel):
    on: date


class ReplyIn(BaseModel):
    on: date
    resolved: bool


class EscalateIn(BaseModel):
    filed_on: date
    already_with_ombudsman: bool
    in_court_or_other_forum: bool


class CloseIn(BaseModel):
    reason: str = Field(min_length=2, max_length=300)


class LetterOut(BaseModel):
    id: UUID
    kind: str
    language: str
    text: str
    polished: bool
    guardrail_note: str
    approved_at: datetime | None


class CaseOut(BaseModel):
    id: UUID
    state: str
    bank_code: str
    language: str
    finding_ids: list[UUID]
    sent_on: date | None
    bank_received_on: date | None
    last_communication_on: date | None
    escalation_eligible_on: date | None
    filing_deadline_on: date | None
    days_left: int | None
    escalated_on: date | None
    created_at: datetime


class CaseDetail(CaseOut):
    events: list[dict[str, Any]]
    letters: list[LetterOut]


def _rules(services: Services) -> RuleBook:
    return load_rulebook(services.settings.rules_dir)


def _bad(error: TransitionError | service.CaseError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": error.code, "message": str(error)})


async def _row(user: CurrentUser, case_id: UUID) -> store.CaseRow:
    row = await store.get(user.conn, case_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return row


async def _context(
    user: CurrentUser, services: Services, row: store.CaseRow
) -> tuple[list[service.CaseFinding], CaseFacts, list[int | None]]:
    cipher = await user_cipher(user.conn, services.settings.key_ring(), user.user_id)
    findings = await service.load_findings(user.conn, await store.finding_ids(user.conn, row.id), cipher)
    waits = service.rule_wait_days(findings, _rules(services))
    return findings, service.case_facts(row, _rules(services), waits), waits


async def _out(user: CurrentUser, row: store.CaseRow, services: Services) -> CaseOut:
    _, facts, _ = await _context(user, services, row)
    return CaseOut(
        id=row.id,
        state=facts.state.value,
        bank_code=row.bank_code,
        language=row.language,
        finding_ids=await store.finding_ids(user.conn, row.id),
        sent_on=row.sent_on,
        bank_received_on=row.bank_received_on,
        last_communication_on=row.last_communication_on,
        escalation_eligible_on=facts.deadlines.eligible_on if facts.deadlines else None,
        filing_deadline_on=facts.deadlines.filing_deadline_on if facts.deadlines else None,
        days_left=days_left(facts, today_ist()),
        escalated_on=row.escalated_on,
        created_at=row.created_at,
    )


async def _transition(
    user: CurrentUser,
    services: Services,
    case_id: UUID,
    action: Callable[[CaseFacts, list[int | None]], tuple[CaseFacts, list[Event]]],
) -> CaseOut:
    row = await _row(user, case_id)
    _, before, waits = await _context(user, services, row)
    try:
        after, events = action(before, waits)
    except TransitionError as error:
        raise _bad(error) from error
    version = await store.current_rule_version(user.conn, _rules(services).rules_sha256)
    await service.commit(user.conn, row, before, after, events, version, today_ist())
    return await _out(user, await _row(user, case_id), services)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_case(body: CreateIn, user: CurrentUserDep, services: ServicesDep) -> CaseOut:
    cipher = await user_cipher(user.conn, services.settings.key_ring(), user.user_id)
    try:
        findings = await service.load_findings(user.conn, body.finding_ids, cipher)
        bank = service.check_findings(findings, await store.findings_in_cases(user.conn, body.finding_ids))
    except service.CaseError as error:
        raise _bad(error) from error
    case_id = await store.create(user.conn, user.user_id, bank, body.language, body.finding_ids)
    await store.append_events(user.conn, case_id, user.user_id, [("created", {"findings": len(findings)})])
    return await _out(user, await _row(user, case_id), services)


@router.get("")
async def list_cases(user: CurrentUserDep, services: ServicesDep, response: Response) -> list[CaseOut]:
    response.headers["Cache-Control"] = "no-store"
    return [await _out(user, row, services) for row in await store.list_for_user(user.conn, user.user_id)]


async def _letters(user: CurrentUser, services: Services, case_id: UUID) -> list[LetterOut]:
    cipher = await user_cipher(user.conn, services.settings.key_ring(), user.user_id)
    return [
        LetterOut(
            id=letter.id,
            kind=letter.kind,
            language=letter.language,
            text=cipher.decrypt(letter.body_enc, service.LETTER_BODY),
            polished=letter.polished,
            guardrail_note=letter.guardrail_note,
            approved_at=letter.approved_at,
        )
        for letter in await store.letters_for_case(user.conn, case_id)
    ]


@router.get("/{case_id}")
async def get_case(case_id: UUID, user: CurrentUserDep, services: ServicesDep) -> CaseDetail:
    row = await _row(user, case_id)
    summary = await _out(user, row, services)
    return CaseDetail(
        **summary.model_dump(),
        events=await store.events(user.conn, case_id),
        letters=await _letters(user, services, case_id),
    )


@router.post("/{case_id}/letters", status_code=status.HTTP_201_CREATED)
async def draft_letter(case_id: UUID, body: LetterIn, user: CurrentUserDep, services: ServicesDep) -> LetterOut:
    row = await _row(user, case_id)
    findings, facts, _ = await _context(user, services, row)
    if body.kind == CMS and facts.state.value != "escalation_eligible":
        raise HTTPException(
            status.HTTP_409_CONFLICT, {"code": "not_eligible", "message": "escalation is not possible yet"}
        )
    letter_facts = service.letter_facts(row, findings, _rules(services), row.language, today_ist())
    template = render_bank_letter(letter_facts) if body.kind == BANK else render_cms_complaint(letter_facts)
    result = check(template, letter_facts, body.kind, final=False)
    if not result.ok:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, {"code": "template_failed", "problems": result.problems}
        )
    text, polished, note = template, False, "template"
    if body.polish:
        charge = partial(consume_budget, user.conn, user.user_id, services.gateway.daily_limit)
        outcome = await polish(template, letter_facts, body.kind, services.gateway, charge)
        text, polished, note = outcome.text, outcome.polished, outcome.note
    cipher = await user_cipher(user.conn, services.settings.key_ring(), user.user_id)
    letter_id = await store.insert_letter(
        user.conn,
        case_id,
        user.user_id,
        body.kind,
        row.language,
        TEMPLATE_VERSION,
        cipher.encrypt(text, service.LETTER_BODY),
        polished,
        note,
    )
    await store.append_events(
        user.conn, case_id, user.user_id, [("letter_drafted", {"kind": body.kind, "polished": polished})]
    )
    return LetterOut(
        id=letter_id,
        kind=body.kind,
        language=row.language,
        text=text,
        polished=polished,
        guardrail_note=note,
        approved_at=None,
    )


@router.post("/{case_id}/letters/{letter_id}/approve")
async def approve_letter(
    case_id: UUID, letter_id: UUID, body: ApproveIn, user: CurrentUserDep, services: ServicesDep
) -> LetterOut:
    row = await _row(user, case_id)
    letter = await store.get_letter(user.conn, letter_id)
    if letter is None or letter.case_id != case_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    findings, _, _ = await _context(user, services, row)
    letter_facts = service.letter_facts(row, findings, _rules(services), letter.language, today_ist())
    cipher = await user_cipher(user.conn, services.settings.key_ring(), user.user_id)
    fields = body.model_dump(exclude_none=True)
    final = fill(cipher.decrypt(letter.body_enc, service.LETTER_BODY), letter.language, fields)
    result = check(final, letter_facts, letter.kind, final=True)
    if not result.ok:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"code": "guardrails", "problems": result.problems})
    await store.approve_letter(user.conn, letter_id, cipher.encrypt(final, service.LETTER_BODY), "approved")
    await store.append_events(user.conn, case_id, user.user_id, [("letter_approved", {"kind": letter.kind})])
    return LetterOut(
        id=letter_id,
        kind=letter.kind,
        language=letter.language,
        text=final,
        polished=letter.polished,
        guardrail_note="approved",
        approved_at=datetime.now(),
    )


@router.post("/{case_id}/sent")
async def sent(case_id: UUID, body: DateIn, user: CurrentUserDep, services: ServicesDep) -> CaseOut:
    if await store.approved_letter(user.conn, case_id, BANK) is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, {"code": "letter_not_approved", "message": "approve the bank letter first"}
        )
    return await _transition(user, services, case_id, lambda f, _: mark_sent(f, body.on, today_ist()))


@router.post("/{case_id}/received")
async def received(case_id: UUID, body: DateIn, user: CurrentUserDep, services: ServicesDep) -> CaseOut:
    rules = _rules(services)
    return await _transition(user, services, case_id, lambda f, w: record_receipt(f, body.on, today_ist(), rules, w))


@router.post("/{case_id}/reply")
async def reply(case_id: UUID, body: ReplyIn, user: CurrentUserDep, services: ServicesDep) -> CaseOut:
    rules = _rules(services)
    return await _transition(
        user, services, case_id, lambda f, w: record_reply(f, body.on, body.resolved, today_ist(), rules, w)
    )


@router.post("/{case_id}/communication")
async def communication(case_id: UUID, body: DateIn, user: CurrentUserDep, services: ServicesDep) -> CaseOut:
    rules = _rules(services)
    return await _transition(
        user, services, case_id, lambda f, w: record_communication(f, body.on, today_ist(), rules, w)
    )


@router.post("/{case_id}/escalate")
async def escalate_case(case_id: UUID, body: EscalateIn, user: CurrentUserDep, services: ServicesDep) -> CaseOut:
    checks = EscalationChecks(body.already_with_ombudsman, body.in_court_or_other_forum)
    if not (checks.already_with_ombudsman or checks.in_court_or_other_forum) and (
        await store.approved_letter(user.conn, case_id, CMS) is None
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, {"code": "letter_not_approved", "message": "approve the CMS complaint text first"}
        )
    return await _transition(user, services, case_id, lambda f, _: escalate(f, body.filed_on, checks, today_ist()))


@router.post("/{case_id}/close")
async def close_case(case_id: UUID, body: CloseIn, user: CurrentUserDep, services: ServicesDep) -> CaseOut:
    out = await _transition(user, services, case_id, lambda f, _: close(f, body.reason))
    await store.set_closed_reason(user.conn, case_id, body.reason)
    return out


@router.get("/{case_id}/evidence.pdf")
async def evidence(case_id: UUID, user: CurrentUserDep, services: ServicesDep) -> Response:
    row = await _row(user, case_id)
    findings, _, _ = await _context(user, services, row)
    rules = _rules(services)
    letter_facts = service.letter_facts(row, findings, rules, "en", today_ist())
    quotes = {rule.id: rule.quote for rule in rules.tat_rules.values() if rule.verified}
    data = build_evidence(letter_facts, service.evidence_rows(findings, letter_facts), quotes, today_ist())
    headers = {"Content-Disposition": 'attachment; filename="vapas-evidence.pdf"', "Cache-Control": "no-store"}
    return Response(content=data, media_type="application/pdf", headers=headers)
