import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from vapas.jobs.detection import IST

WILSON_Z = 1.96


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime

    @classmethod
    def week_from(cls, monday: date) -> "Window":
        start = datetime.combine(monday, time.min, IST)
        return cls(start, start + timedelta(days=7))

    @classmethod
    def to_date(cls, end: datetime) -> "Window":
        return cls(datetime(2000, 1, 1, tzinfo=UTC), end)

    @property
    def first_day(self) -> date:
        return self.start.astimezone(IST).date()

    @property
    def end_day(self) -> date:
        return self.end.astimezone(IST).date()


@dataclass(frozen=True)
class Precision:
    correct: int
    wrong: int
    not_sure: int

    @property
    def judged(self) -> int:
        return self.correct + self.wrong

    @property
    def value(self) -> float | None:
        return self.correct / self.judged if self.judged else None

    @property
    def interval(self) -> tuple[float, float] | None:
        n = self.judged
        if n == 0:
            return None
        p = self.correct / n
        z2 = WILSON_Z * WILSON_Z
        centre = (p + z2 / (2 * n)) / (1 + z2 / n)
        half = WILSON_Z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
        return max(0.0, centre - half), min(1.0, centre + half)


@dataclass(frozen=True)
class Impact:
    window: Window
    users_total: int
    users_new: int
    users_active: int
    statements_processed: int
    statements_parsed: int
    statements_reconciled: int
    findings_by_level: dict[str, int]
    claim_precision: Precision
    worth_checking_precision: Precision
    cases_created: int
    cases_escalated: int
    cases_expired: int
    paise_found: int
    paise_recovered: int

    @property
    def reconciled_share(self) -> float | None:
        return self.statements_reconciled / self.statements_parsed if self.statements_parsed else None

    @property
    def findings_per_active_user(self) -> float | None:
        total = sum(self.findings_by_level.values())
        return total / self.users_active if self.users_active else None


async def _scalar(conn: AsyncConnection, sql: str, window: Window) -> int:
    params = {"s": window.start, "e": window.end, "sd": window.first_day, "ed": window.end_day}
    value = await conn.scalar(text(sql), params)
    return int(value or 0)


async def _precision(conn: AsyncConnection, level: str, window: Window) -> Precision:
    rows = await conn.execute(
        text(
            "SELECT fb.verdict, count(*) AS n FROM finding_feedback fb JOIN findings f ON f.id = fb.finding_id "
            "WHERE f.level = :level AND fb.updated_at >= :s AND fb.updated_at < :e GROUP BY fb.verdict"
        ),
        {"level": level, "s": window.start, "e": window.end},
    )
    counts = {row.verdict: int(row.n) for row in rows}
    return Precision(counts.get("correct", 0), counts.get("wrong", 0), counts.get("not_sure", 0))


async def compute_impact(conn: AsyncConnection, window: Window) -> Impact:
    levels = await conn.execute(
        text(
            "SELECT level, count(*) AS n FROM findings "
            "WHERE superseded_at IS NULL AND created_at >= :s AND created_at < :e GROUP BY level"
        ),
        {"s": window.start, "e": window.end},
    )
    return Impact(
        window=window,
        users_total=await _scalar(conn, "SELECT count(*) FROM users WHERE created_at < :e", window),
        users_new=await _scalar(conn, "SELECT count(*) FROM users WHERE created_at >= :s AND created_at < :e", window),
        users_active=await _scalar(
            conn,
            "SELECT count(DISTINCT user_id) FROM statements WHERE confirmed_at >= :s AND confirmed_at < :e",
            window,
        ),
        statements_processed=await _scalar(
            conn,
            "SELECT count(*) FROM statements WHERE status IN ('parsed', 'needs_review', 'failed', 'needs_password') "
            "AND confirmed_at >= :s AND confirmed_at < :e",
            window,
        ),
        statements_parsed=await _scalar(
            conn,
            "SELECT count(*) FROM statements WHERE status = 'parsed' AND parsed_at >= :s AND parsed_at < :e",
            window,
        ),
        statements_reconciled=await _scalar(
            conn,
            "SELECT count(*) FROM statements WHERE status = 'parsed' AND reconciled "
            "AND parsed_at >= :s AND parsed_at < :e",
            window,
        ),
        findings_by_level={row.level: int(row.n) for row in levels},
        claim_precision=await _precision(conn, "claim", window),
        worth_checking_precision=await _precision(conn, "worth_checking", window),
        cases_created=await _scalar(
            conn, "SELECT count(*) FROM cases WHERE created_at >= :s AND created_at < :e", window
        ),
        cases_escalated=await _scalar(
            conn, "SELECT count(*) FROM case_events WHERE type = 'escalated' AND at >= :s AND at < :e", window
        ),
        cases_expired=await _scalar(
            conn, "SELECT count(*) FROM case_events WHERE type = 'expired' AND at >= :s AND at < :e", window
        ),
        paise_found=await _scalar(
            conn,
            "SELECT coalesce(sum(amount_owed_paise), 0) FROM findings "
            "WHERE level = 'claim' AND superseded_at IS NULL AND created_at >= :s AND created_at < :e",
            window,
        ),
        paise_recovered=await _scalar(
            conn,
            "SELECT coalesce(sum(recovered_paise), 0) FROM cases WHERE recovered_on >= :sd AND recovered_on < :ed",
            window,
        ),
    )


def _rupees(paise: int) -> str:
    return f"Rs {paise // 100:,}"


def _share(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _precision_line(label: str, precision: Precision) -> str:
    interval = precision.interval
    ci = "" if interval is None else f" (95% CI {interval[0]:.1%} to {interval[1]:.1%})"
    judged = f"{precision.correct} correct, {precision.wrong} wrong, {precision.not_sure} not sure"
    return f"| {label} | {_share(precision.value)}{ci} | {judged} |"


def render_markdown(week: Impact, to_date: Impact, data_label: str) -> str:
    rows = [
        ("Users (total at end)", str(week.users_total), str(to_date.users_total)),
        ("New users", str(week.users_new), str(to_date.users_new)),
        ("Active users (uploaded)", str(week.users_active), str(to_date.users_active)),
        ("Statements processed", str(week.statements_processed), str(to_date.statements_processed)),
        ("Statements fully reconciled", _share(week.reconciled_share), _share(to_date.reconciled_share)),
        (
            "Findings per active user",
            _share(None) if week.findings_per_active_user is None else f"{week.findings_per_active_user:.2f}",
            _share(None) if to_date.findings_per_active_user is None else f"{to_date.findings_per_active_user:.2f}",
        ),
        ("Cases created", str(week.cases_created), str(to_date.cases_created)),
        ("Cases escalated", str(week.cases_escalated), str(to_date.cases_escalated)),
        ("Cases expired", str(week.cases_expired), str(to_date.cases_expired)),
        ("Money owed found (claims)", _rupees(week.paise_found), _rupees(to_date.paise_found)),
        ("Money recovered (user-reported)", _rupees(week.paise_recovered), _rupees(to_date.paise_recovered)),
    ]
    levels = sorted(set(week.findings_by_level) | set(to_date.findings_by_level))
    rows += [
        (f"Findings: {level}", str(week.findings_by_level.get(level, 0)), str(to_date.findings_by_level.get(level, 0)))
        for level in levels
    ]
    start = week.window.start.astimezone(IST).date()
    end = (week.window.end - timedelta(seconds=1)).astimezone(IST).date()
    lines = [
        f"# VAPAS impact report, week {start.isoformat()} to {end.isoformat()} (IST)",
        "",
        f"Data: {data_label}. Aggregates only, no personal data.",
        "",
        "| Metric | This week | To date |",
        "|---|---|---|",
        *[f"| {name} | {week_value} | {total} |" for name, week_value, total in rows],
        "",
        "User-confirmed precision to date (correct / (correct + wrong)):",
        "",
        "| Finding level | Precision | Feedback |",
        "|---|---|---|",
        _precision_line("Money owed (claim)", to_date.claim_precision),
        _precision_line("Worth checking", to_date.worth_checking_precision),
        "",
    ]
    return "\n".join(lines)
