from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATEMENTS = [
    """
    CREATE TABLE invite_codes (
        id uuid PRIMARY KEY,
        code_hash bytea NOT NULL UNIQUE,
        cohort text NOT NULL CHECK (length(cohort) BETWEEN 1 AND 40),
        max_uses integer NOT NULL CHECK (max_uses BETWEEN 1 AND 1000),
        used_count integer NOT NULL DEFAULT 0 CHECK (used_count >= 0 AND used_count <= max_uses),
        expires_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "ALTER TABLE invite_codes ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE invite_codes FORCE ROW LEVEL SECURITY",
    "REVOKE ALL ON invite_codes FROM PUBLIC",
    "ALTER TABLE users ADD COLUMN invite_id uuid REFERENCES invite_codes (id)",
    """
    CREATE FUNCTION redeem_invite(p_code_hash bytea) RETURNS uuid
        LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
        AS $$
        UPDATE public.invite_codes SET used_count = used_count + 1
        WHERE code_hash = p_code_hash AND used_count < max_uses AND (expires_at IS NULL OR expires_at > now())
        RETURNING id
    $$
    """,
    "REVOKE ALL ON FUNCTION redeem_invite(bytea) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION redeem_invite(bytea) TO vapas_app",
    """
    CREATE TABLE finding_feedback (
        finding_id uuid PRIMARY KEY REFERENCES findings (id) ON DELETE CASCADE,
        user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        verdict text NOT NULL CHECK (verdict IN ('correct', 'wrong', 'not_sure')),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX finding_feedback_user ON finding_feedback (user_id)",
    "ALTER TABLE finding_feedback ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE finding_feedback FORCE ROW LEVEL SECURITY",
    "CREATE POLICY owner ON finding_feedback USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id())",
    "REVOKE ALL ON finding_feedback FROM PUBLIC",
    "GRANT SELECT, INSERT, UPDATE (verdict, updated_at) ON finding_feedback TO vapas_app",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE finding_feedback")
    op.execute("DROP FUNCTION redeem_invite(bytea)")
    op.execute("ALTER TABLE users DROP COLUMN invite_id")
    op.execute("DROP TABLE invite_codes")
