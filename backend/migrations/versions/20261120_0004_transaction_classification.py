from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS = "'payment', 'receipt', 'reversal', 'merchant_refund', 'chargeback', 'compensation', 'charge', 'interest'"
CHANNELS = (
    "'upi', 'imps', 'neft', 'rtgs', 'atm', 'pos', 'ecom', 'nach', 'aeps', "
    "'charges', 'cheque', 'cash', 'interest', 'unclassified'"
)


def upgrade() -> None:
    op.execute("ALTER TABLE transactions ADD COLUMN kind text")
    op.execute("ALTER TABLE transactions ADD COLUMN ext_ref_enc bytea")
    op.execute("ALTER TABLE transactions ADD COLUMN ext_ref_hmac bytea")
    op.execute("ALTER TABLE transactions ADD COLUMN classifier_version smallint")
    op.execute(f"ALTER TABLE transactions ADD CONSTRAINT transactions_kind_check CHECK (kind IN ({KINDS}))")
    op.execute(f"ALTER TABLE transactions ADD CONSTRAINT transactions_channel_check CHECK (channel IN ({CHANNELS}))")
    op.execute(
        "CREATE INDEX transactions_user_ext_ref ON transactions (user_id, ext_ref_hmac) WHERE ext_ref_hmac IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX transactions_user_ext_ref")
    op.execute("ALTER TABLE transactions DROP CONSTRAINT transactions_channel_check")
    op.execute("ALTER TABLE transactions DROP CONSTRAINT transactions_kind_check")
    op.execute("ALTER TABLE transactions DROP COLUMN classifier_version")
    op.execute("ALTER TABLE transactions DROP COLUMN ext_ref_hmac")
    op.execute("ALTER TABLE transactions DROP COLUMN ext_ref_enc")
    op.execute("ALTER TABLE transactions DROP COLUMN kind")
