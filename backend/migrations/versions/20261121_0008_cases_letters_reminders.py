from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USER_TABLES = ("cases", "case_findings", "case_events", "letters", "reminders", "notifications")

STATEMENTS = [
    """
    CREATE TABLE cases (
        id uuid PRIMARY KEY,
        user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        state text NOT NULL CHECK (state IN (
            'draft', 'sent_to_bank', 'awaiting_reply', 'resolved', 'escalation_eligible', 'escalated',
            'closed', 'expired'
        )),
        bank_code text NOT NULL,
        language text NOT NULL CHECK (language IN ('en', 'hi')),
        sent_on date,
        bank_received_on date,
        last_communication_on date,
        unsatisfied_reply_on date,
        escalated_on date,
        wait_days integer,
        escalation_eligible_on date,
        filing_deadline_on date,
        deadline_rule_version_id bigint REFERENCES rule_versions (id),
        closed_reason text,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX cases_user ON cases (user_id, created_at DESC)",
    """
    CREATE INDEX cases_due ON cases (escalation_eligible_on, filing_deadline_on)
        WHERE state IN ('awaiting_reply', 'escalation_eligible')
    """,
    """
    CREATE TABLE case_findings (
        case_id uuid NOT NULL REFERENCES cases (id) ON DELETE CASCADE,
        finding_id uuid NOT NULL REFERENCES findings (id) ON DELETE CASCADE,
        user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        PRIMARY KEY (case_id, finding_id),
        UNIQUE (finding_id)
    )
    """,
    """
    CREATE TABLE case_events (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        case_id uuid NOT NULL REFERENCES cases (id) ON DELETE CASCADE,
        user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        seq integer NOT NULL,
        type text NOT NULL,
        payload jsonb NOT NULL,
        at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (case_id, seq)
    )
    """,
    """
    CREATE TABLE letters (
        id uuid PRIMARY KEY,
        case_id uuid NOT NULL REFERENCES cases (id) ON DELETE CASCADE,
        user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        kind text NOT NULL CHECK (kind IN ('bank', 'cms')),
        language text NOT NULL CHECK (language IN ('en', 'hi')),
        template_version integer NOT NULL,
        body_enc bytea NOT NULL,
        polished boolean NOT NULL,
        guardrail_note text NOT NULL,
        approved_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX letters_case ON letters (case_id, created_at DESC)",
    """
    CREATE TABLE reminders (
        id uuid PRIMARY KEY,
        case_id uuid NOT NULL REFERENCES cases (id) ON DELETE CASCADE,
        user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        kind text NOT NULL CHECK (kind IN ('eligible', 'd30', 'd7', 'd1')),
        due_on date NOT NULL,
        sent_at timestamptz,
        attempts integer NOT NULL DEFAULT 0,
        UNIQUE (case_id, kind)
    )
    """,
    "CREATE INDEX reminders_due ON reminders (due_on) WHERE sent_at IS NULL",
    """
    CREATE TABLE notifications (
        id uuid PRIMARY KEY,
        user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        case_id uuid REFERENCES cases (id) ON DELETE CASCADE,
        kind text NOT NULL,
        message text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        read_at timestamptz
    )
    """,
    "CREATE INDEX notifications_unread ON notifications (user_id, created_at DESC) WHERE read_at IS NULL",
    """
    CREATE FUNCTION users_with_case_work(p_today date) RETURNS TABLE (user_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
        AS $$
        SELECT c.user_id FROM public.cases c
        WHERE c.state IN ('awaiting_reply', 'escalation_eligible')
          AND (c.escalation_eligible_on <= p_today OR c.filing_deadline_on < p_today)
        UNION
        SELECT r.user_id FROM public.reminders r WHERE r.sent_at IS NULL AND r.due_on <= p_today
    $$
    """,
    "REVOKE ALL ON FUNCTION users_with_case_work(date) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION users_with_case_work(date) TO vapas_worker",
    "REVOKE ALL ON cases, case_findings, case_events, letters, reminders, notifications FROM PUBLIC",
    "GRANT SELECT, INSERT, UPDATE ON cases, letters TO vapas_app",
    "GRANT SELECT, INSERT ON case_findings, case_events TO vapas_app",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON reminders TO vapas_app",
    "GRANT SELECT, INSERT, UPDATE (read_at) ON notifications TO vapas_app",
    "GRANT SELECT, UPDATE ON cases TO vapas_worker",
    "GRANT SELECT, INSERT ON case_events TO vapas_worker",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON reminders TO vapas_worker",
    "GRANT SELECT, INSERT ON notifications TO vapas_worker",
    "GRANT SELECT ON users, rule_versions TO vapas_worker",
    "GRANT SELECT ON case_findings TO vapas_worker",
]


def owner_policy(table: str) -> list[str]:
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY owner ON {table} USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id())",
    ]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)
    for table in USER_TABLES:
        for statement in owner_policy(table):
            op.execute(statement)


def downgrade() -> None:
    op.execute("DROP FUNCTION users_with_case_work(date)")
    op.execute("DROP TABLE notifications, reminders, letters, case_events, case_findings, cases")
