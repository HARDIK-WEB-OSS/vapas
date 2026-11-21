import logging
from uuid import UUID

from sqlalchemy import text

from vapas.cases import service
from vapas.cases.reminders import message
from vapas.cases.timeline import CaseState, tick
from vapas.db import cases as store
from vapas.jobs.context import WorkerContext
from vapas.jobs.detection import today_ist
from vapas.mail.sender import EmailMessage
from vapas.rules.loader import load_rulebook
from vapas.security.user_keys import user_cipher

log = logging.getLogger(__name__)


async def _process_user(ctx: WorkerContext, user_id: UUID) -> int:
    rules = load_rulebook(ctx.settings.rules_dir)
    today = today_ist()
    handled = 0
    async with ctx.db.as_user(user_id) as conn:
        cipher = await user_cipher(conn, ctx.keys, user_id)
        version = await store.current_rule_version(conn, rules.rules_sha256)
        email = await store.user_email(conn, user_id)
        for row in await store.open_timelines(conn, user_id):
            findings = await service.load_findings(conn, await store.finding_ids(conn, row.id), cipher)
            before = service.case_facts(row, rules, service.rule_wait_days(findings, rules))
            after, events = tick(before, today)
            if events:
                await service.commit(conn, row, before, after, events, version, today)
                handled += 1
            if after.state is CaseState.EXPIRED:
                deadline = before.deadlines.filing_deadline_on if before.deadlines else None
                subject, body = message("expired", row.language, row.bank_code, deadline, today)
                await store.notify(conn, user_id, row.id, "expired", subject)
        cases_by_id = {row.id: row for row in await store.list_for_user(conn, user_id)}
        for reminder in await store.due_reminders(conn, user_id, today):
            owner = cases_by_id.get(reminder.case_id)
            if owner is None:
                continue
            subject, body = message(reminder.kind, owner.language, owner.bank_code, owner.filing_deadline_on, today)
            if reminder.attempts == 0:
                await store.notify(conn, user_id, owner.id, reminder.kind, subject)
            sent = False
            if email:
                try:
                    await ctx.mailer.send(
                        EmailMessage(to=email, subject=subject, body=body, kind=f"case_{reminder.kind}")
                    )
                    sent = True
                except Exception as error:
                    log.warning("reminder email failed", extra={"error_type": type(error).__name__})
            await store.mark_reminder(conn, reminder.id, sent)
            handled += 1
    return handled


async def process_case_work(ctx: WorkerContext) -> int:
    async with ctx.db.anonymous() as conn:
        users = [
            r.user_id
            for r in await conn.execute(text("SELECT user_id FROM users_with_case_work(:d)"), {"d": today_ist()})
        ]
    total = 0
    for user_id in users:
        try:
            total += await _process_user(ctx, user_id)
        except Exception as error:
            log.warning("case work failed for a user", extra={"error_type": type(error).__name__})
    return total
