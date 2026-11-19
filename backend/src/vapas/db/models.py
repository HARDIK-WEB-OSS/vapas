from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    LargeBinary,
    MetaData,
    SmallInteger,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import CITEXT, UUID

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("email", CITEXT, nullable=False, unique=True),
    Column("password_hash", Text, nullable=False),
    Column("email_verified_at", DateTime(timezone=True)),
    Column("locale", Text, nullable=False),
    Column("password_changed_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

user_keys = Table(
    "user_keys",
    metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True),
    Column("wrapped_dek", LargeBinary, nullable=False),
    Column("kek_version", SmallInteger, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("rotated_at", DateTime(timezone=True)),
)

sessions = Table(
    "sessions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("family_id", UUID(as_uuid=True), nullable=False),
    Column("refresh_token_hash", LargeBinary, nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    Column("replaced_by", UUID(as_uuid=True)),
)

email_tokens = Table(
    "email_tokens",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("purpose", Text, nullable=False),
    Column("token_hash", LargeBinary, nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("used_at", DateTime(timezone=True)),
)

consent_notices = Table(
    "consent_notices",
    metadata,
    Column("version", Text, primary_key=True),
    Column("text_en", Text, nullable=False),
    Column("text_hi", Text, nullable=False),
    Column("sha256", LargeBinary, nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=False),
)

consents = Table(
    "consents",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("notice_version", Text, ForeignKey("consent_notices.version"), nullable=False),
    Column("purpose", Text, nullable=False),
    Column("granted_at", DateTime(timezone=True), nullable=False),
    Column("withdrawn_at", DateTime(timezone=True)),
)

audit_log = Table(
    "audit_log",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id")),
    Column("actor", Text, nullable=False),
    Column("action", Text, nullable=False),
    Column("entity_type", Text),
    Column("entity_id", UUID(as_uuid=True)),
    Column("ip_hash", LargeBinary),
    Column("at", DateTime(timezone=True), nullable=False),
)
