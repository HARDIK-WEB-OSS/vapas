from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from vapas.privacy.notices import load_notice

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VERSION = "2026-11-v1"


def upgrade() -> None:
    notice = load_notice(VERSION)
    op.execute(
        sa.text(
            "INSERT INTO consent_notices (version, text_en, text_hi, sha256) VALUES (:version, :en, :hi, :sha)"
        ).bindparams(version=notice.version, en=notice.text_en, hi=notice.text_hi, sha=notice.sha256)
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM consent_notices WHERE version = :version").bindparams(version=VERSION))
