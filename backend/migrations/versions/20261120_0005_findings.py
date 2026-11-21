from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATEMENTS = [
    """
    CREATE TABLE rule_versions (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        rules_sha256 bytea NOT NULL,
        policy_sha256 bytea NOT NULL,
        legal_content jsonb NOT NULL,
        policy_content jsonb NOT NULL,
        loaded_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (rules_sha256, policy_sha256)
    )
    """,
    """
    CREATE TABLE findings (
        id uuid PRIMARY KEY,
        user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        finding_key bytea NOT NULL,
        detector text NOT NULL,
        level text NOT NULL CHECK (level IN (
            'claim', 'worth_checking', 'needs_user_input', 'needs_review', 'historical', 'informational'
        )),
        confidence text NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),
        status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'confirmed', 'dismissed')),
        rule_id text,
        rule_version_id bigint NOT NULL REFERENCES rule_versions (id),
        policy_version text NOT NULL,
        detector_version smallint NOT NULL,
        finding_policy text,
        letter_scope text CHECK (letter_scope IN ('claim', 'reversal_only')),
        question text,
        group_key text,
        statement_id uuid REFERENCES statements (id) ON DELETE SET NULL,
        debit_txn_id bigint,
        debit_txn_date date,
        t_date date,
        r_date date,
        delay_days integer,
        amount_owed_paise bigint CHECK (amount_owed_paise IS NULL OR amount_owed_paise >= 0),
        already_paid_paise bigint NOT NULL DEFAULT 0,
        accruing boolean NOT NULL DEFAULT false,
        why text NOT NULL,
        snapshot_enc bytea NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        superseded_at timestamptz,
        UNIQUE (user_id, finding_key),
        CHECK (amount_owed_paise IS NULL OR level = 'claim' OR level = 'informational'),
        CHECK (letter_scope IS DISTINCT FROM 'reversal_only' OR amount_owed_paise IS NULL)
    )
    """,
    "CREATE INDEX findings_dashboard ON findings (user_id, level, created_at DESC) WHERE superseded_at IS NULL",
    """
    CREATE TABLE user_inputs (
        id uuid PRIMARY KEY,
        user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        question text NOT NULL CHECK (question IN ('payee_was_merchant', 'payment_failed', 'mandate_revoked')),
        subject text NOT NULL,
        answer jsonb NOT NULL,
        entered_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (user_id, question, subject)
    )
    """,
    "ALTER TABLE findings ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE findings FORCE ROW LEVEL SECURITY",
    "CREATE POLICY owner ON findings USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id())",
    "ALTER TABLE user_inputs ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE user_inputs FORCE ROW LEVEL SECURITY",
    "CREATE POLICY owner ON user_inputs USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id())",
    "REVOKE ALL ON rule_versions, findings, user_inputs FROM PUBLIC",
    "GRANT SELECT ON rule_versions TO vapas_app, vapas_worker",
    "GRANT INSERT ON rule_versions TO vapas_worker",
    "GRANT SELECT ON findings TO vapas_app",
    "GRANT UPDATE (status, updated_at) ON findings TO vapas_app",
    "GRANT SELECT, INSERT, UPDATE ON findings TO vapas_worker",
    "GRANT SELECT, INSERT, UPDATE ON user_inputs TO vapas_app",
    "GRANT SELECT ON user_inputs TO vapas_worker",
    "GRANT INSERT ON outbox TO vapas_worker",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE user_inputs, findings, rule_versions")
