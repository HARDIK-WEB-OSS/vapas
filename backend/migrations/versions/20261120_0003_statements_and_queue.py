from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATEMENTS = [
    """
    CREATE TABLE statements (
        id uuid PRIMARY KEY,
        user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        content_sha256 bytea NOT NULL,
        file_kind text NOT NULL CHECK (file_kind IN ('pdf', 'csv', 'xls', 'xlsx')),
        size_bytes integer NOT NULL CHECK (size_bytes > 0),
        object_key text NOT NULL UNIQUE,
        status text NOT NULL CHECK (status IN (
            'awaiting_upload', 'queued', 'parsing', 'parsed', 'needs_password', 'needs_review', 'failed', 'expired'
        )),
        failure_code text,
        parse_requests integer NOT NULL DEFAULT 0,
        bank_code text,
        layout_code text,
        parser_version integer,
        period_from date,
        period_to date,
        rows_parsed integer,
        rows_rejected integer,
        reconciled boolean,
        reconcile_breaks integer,
        row_order text,
        created_at timestamptz NOT NULL DEFAULT now(),
        confirmed_at timestamptz,
        parsed_at timestamptz,
        raw_deleted_at timestamptz,
        UNIQUE (user_id, content_sha256)
    )
    """,
    "CREATE INDEX statements_user_created ON statements (user_id, created_at DESC)",
    "CREATE SEQUENCE transactions_id_seq AS bigint",
    """
    CREATE TABLE transactions (
        id bigint NOT NULL DEFAULT nextval('transactions_id_seq'),
        txn_date date NOT NULL,
        user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        statement_id uuid NOT NULL REFERENCES statements (id) ON DELETE CASCADE,
        row_index integer NOT NULL,
        value_date date,
        direction text NOT NULL CHECK (direction IN ('debit', 'credit')),
        amount_paise bigint NOT NULL CHECK (amount_paise > 0),
        balance_paise bigint,
        channel text,
        narration_enc bytea NOT NULL,
        ref_enc bytea,
        ref_hmac bytea,
        PRIMARY KEY (id, txn_date),
        UNIQUE (statement_id, row_index, txn_date)
    ) PARTITION BY RANGE (txn_date)
    """,
    "ALTER SEQUENCE transactions_id_seq OWNED BY transactions.id",
    "CREATE INDEX transactions_user_date ON transactions (user_id, txn_date)",
    "CREATE INDEX transactions_user_ref ON transactions (user_id, ref_hmac) WHERE ref_hmac IS NOT NULL",
    """
    CREATE TABLE jobs (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        queue text NOT NULL,
        idempotency_key text NOT NULL UNIQUE,
        user_id uuid REFERENCES users (id) ON DELETE CASCADE,
        payload jsonb NOT NULL,
        state text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued', 'running', 'done', 'dead')),
        attempts integer NOT NULL DEFAULT 0,
        max_attempts integer NOT NULL DEFAULT 3,
        run_after timestamptz NOT NULL DEFAULT now(),
        locked_by text,
        locked_until timestamptz,
        last_error_code text,
        created_at timestamptz NOT NULL DEFAULT now(),
        finished_at timestamptz
    )
    """,
    "CREATE INDEX jobs_ready ON jobs (queue, run_after) WHERE state = 'queued'",
    "CREATE INDEX jobs_expired_leases ON jobs (locked_until) WHERE state = 'running'",
    """
    CREATE TABLE outbox (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        event_type text NOT NULL,
        user_id uuid REFERENCES users (id) ON DELETE CASCADE,
        payload jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        published_at timestamptz
    )
    """,
    "CREATE INDEX outbox_pending ON outbox (id) WHERE published_at IS NULL",
    """
    CREATE TABLE llm_usage (
        user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        day date NOT NULL,
        calls integer NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, day)
    )
    """,
    """
    CREATE FUNCTION ensure_transaction_partition(p_month date) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
        AS $$
    DECLARE
        start_month date := date_trunc('month', p_month)::date;
        partition_name text := format('transactions_y%sm%s', to_char(start_month, 'YYYY'), to_char(start_month, 'MM'));
    BEGIN
        PERFORM pg_advisory_xact_lock(hashtext(partition_name));
        IF to_regclass('public.' || partition_name) IS NULL THEN
            EXECUTE format(
                'CREATE TABLE public.%I PARTITION OF public.transactions FOR VALUES FROM (%L) TO (%L)',
                partition_name, start_month, (start_month + interval '1 month')::date
            );
            EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC', partition_name);
        END IF;
    END
    $$
    """,
    """
    CREATE FUNCTION drop_expired_transaction_partitions(p_keep_months integer) RETURNS integer
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
        AS $$
    DECLARE
        cutoff date := (date_trunc('month', now()) - make_interval(months => p_keep_months))::date;
        part record;
        dropped integer := 0;
    BEGIN
        FOR part IN
            SELECT c.relname
            FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid
            WHERE i.inhparent = 'public.transactions'::regclass
              AND c.relname ~ '^transactions_y[0-9]{4}m[0-9]{2}$'
        LOOP
            IF make_date(substr(part.relname, 15, 4)::int, substr(part.relname, 20, 2)::int, 1) < cutoff THEN
                EXECUTE format('DROP TABLE public.%I', part.relname);
                dropped := dropped + 1;
            END IF;
        END LOOP;
        RETURN dropped;
    END
    $$
    """,
    """
    CREATE FUNCTION mark_raw_deleted(p_keys text[]) RETURNS integer
        LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, public
        AS $$
        WITH changed AS (
            UPDATE public.statements
            SET raw_deleted_at = now(),
                status = CASE WHEN status = 'awaiting_upload' THEN 'expired' ELSE status END
            WHERE object_key = ANY (p_keys) AND raw_deleted_at IS NULL
            RETURNING 1
        )
        SELECT count(*)::integer FROM changed
    $$
    """,
    "ALTER TABLE statements ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE statements FORCE ROW LEVEL SECURITY",
    "CREATE POLICY owner ON statements USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id())",
    "ALTER TABLE transactions ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE transactions FORCE ROW LEVEL SECURITY",
    "CREATE POLICY owner ON transactions USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id())",
    "ALTER TABLE llm_usage ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE llm_usage FORCE ROW LEVEL SECURITY",
    "CREATE POLICY owner ON llm_usage USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id())",
    "REVOKE ALL ON statements, transactions, jobs, outbox, llm_usage FROM PUBLIC",
    "REVOKE ALL ON FUNCTION ensure_transaction_partition(date) FROM PUBLIC",
    "REVOKE ALL ON FUNCTION drop_expired_transaction_partitions(integer) FROM PUBLIC",
    "REVOKE ALL ON FUNCTION mark_raw_deleted(text[]) FROM PUBLIC",
    "GRANT SELECT, INSERT, UPDATE ON statements TO vapas_app",
    "GRANT SELECT ON transactions TO vapas_app",
    "GRANT INSERT ON outbox TO vapas_app",
    "GRANT SELECT, UPDATE ON statements TO vapas_worker",
    "GRANT SELECT, INSERT, DELETE ON transactions TO vapas_worker",
    "GRANT USAGE ON SEQUENCE transactions_id_seq TO vapas_worker",
    "GRANT SELECT, INSERT, UPDATE ON jobs, llm_usage TO vapas_worker",
    "GRANT SELECT, UPDATE ON outbox TO vapas_worker",
    "GRANT EXECUTE ON FUNCTION ensure_transaction_partition(date) TO vapas_worker",
    "GRANT EXECUTE ON FUNCTION drop_expired_transaction_partitions(integer) TO vapas_worker",
    "GRANT EXECUTE ON FUNCTION mark_raw_deleted(text[]) TO vapas_worker",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP FUNCTION mark_raw_deleted(text[])")
    op.execute("DROP FUNCTION drop_expired_transaction_partitions(integer)")
    op.execute("DROP FUNCTION ensure_transaction_partition(date)")
    op.execute("DROP TABLE llm_usage, outbox, jobs, transactions, statements")
