from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE cases ADD COLUMN recovered_paise bigint CHECK (recovered_paise > 0)")
    op.execute("ALTER TABLE cases ADD COLUMN recovered_on date")


def downgrade() -> None:
    op.execute("ALTER TABLE cases DROP COLUMN recovered_on, DROP COLUMN recovered_paise")
