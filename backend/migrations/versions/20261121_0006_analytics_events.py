from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATEMENTS = [
    """
    CREATE TABLE analytics_events (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        event_type text NOT NULL,
        props jsonb NOT NULL,
        at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX analytics_events_type_at ON analytics_events (event_type, at)",
    "REVOKE ALL ON analytics_events FROM PUBLIC",
    "GRANT INSERT ON analytics_events TO vapas_worker",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE analytics_events")
