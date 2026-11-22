from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATEMENTS = [
    """
    CREATE FUNCTION delete_unverified_accounts(p_cutoff timestamptz) RETURNS integer
        LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
        AS $$
        DECLARE
            removed integer;
        BEGIN
            WITH gone AS (
                DELETE FROM public.users
                WHERE email_verified_at IS NULL AND created_at < p_cutoff
                RETURNING id
            )
            INSERT INTO public.audit_log (user_id, actor, action, entity_type, entity_id)
            SELECT NULL, 'system', 'unverified_account_deleted', 'user', gone.id FROM gone;
            GET DIAGNOSTICS removed = ROW_COUNT;
            RETURN removed;
        END
    $$
    """,
    "REVOKE ALL ON FUNCTION delete_unverified_accounts(timestamptz) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION delete_unverified_accounts(timestamptz) TO vapas_worker",
    "CREATE INDEX users_unverified_created ON users (created_at) WHERE email_verified_at IS NULL",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP INDEX users_unverified_created")
    op.execute("DROP FUNCTION delete_unverified_accounts(timestamptz)")
