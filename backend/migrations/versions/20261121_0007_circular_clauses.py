from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATEMENTS = [
    """
    CREATE TABLE circular_clauses (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        instrument_id text NOT NULL,
        instrument_title text NOT NULL,
        instrument_ref text NOT NULL,
        clause text NOT NULL,
        rule_id text,
        body text NOT NULL,
        search_hints text NOT NULL DEFAULT '',
        source text NOT NULL CHECK (source IN ('rule_yaml', 'pdf')),
        source_sha256 bytea NOT NULL,
        url text NOT NULL,
        page integer,
        legal_status text NOT NULL,
        verified boolean NOT NULL,
        ingested_at timestamptz NOT NULL DEFAULT now(),
        search tsvector GENERATED ALWAYS AS (
            setweight(to_tsvector('english', clause), 'A')
            || setweight(to_tsvector('english', body), 'B')
            || setweight(to_tsvector('english', search_hints), 'C')
        ) STORED,
        UNIQUE (instrument_id, source, clause)
    )
    """,
    "CREATE INDEX circular_clauses_search ON circular_clauses USING gin (search)",
    "REVOKE ALL ON circular_clauses FROM PUBLIC",
    "GRANT SELECT ON circular_clauses TO vapas_app, vapas_worker",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE circular_clauses")
