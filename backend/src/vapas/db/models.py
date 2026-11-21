from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    FetchedValue,
    ForeignKey,
    Identity,
    Integer,
    LargeBinary,
    MetaData,
    SmallInteger,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID

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

statements = Table(
    "statements",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("content_sha256", LargeBinary, nullable=False),
    Column("file_kind", Text, nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("object_key", Text, nullable=False, unique=True),
    Column("status", Text, nullable=False),
    Column("failure_code", Text),
    Column("parse_requests", Integer, nullable=False),
    Column("bank_code", Text),
    Column("layout_code", Text),
    Column("parser_version", Integer),
    Column("period_from", Date),
    Column("period_to", Date),
    Column("rows_parsed", Integer),
    Column("rows_rejected", Integer),
    Column("reconciled", Boolean),
    Column("reconcile_breaks", Integer),
    Column("row_order", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("confirmed_at", DateTime(timezone=True)),
    Column("parsed_at", DateTime(timezone=True)),
    Column("raw_deleted_at", DateTime(timezone=True)),
)

transactions = Table(
    "transactions",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=False, server_default=FetchedValue()),
    Column("txn_date", Date, primary_key=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("statement_id", UUID(as_uuid=True), ForeignKey("statements.id"), nullable=False),
    Column("row_index", Integer, nullable=False),
    Column("value_date", Date),
    Column("direction", Text, nullable=False),
    Column("amount_paise", BigInteger, nullable=False),
    Column("balance_paise", BigInteger),
    Column("channel", Text),
    Column("narration_enc", LargeBinary, nullable=False),
    Column("ref_enc", LargeBinary),
    Column("ref_hmac", LargeBinary),
    Column("kind", Text),
    Column("ext_ref_enc", LargeBinary),
    Column("ext_ref_hmac", LargeBinary),
    Column("classifier_version", SmallInteger),
)

jobs = Table(
    "jobs",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("queue", Text, nullable=False),
    Column("idempotency_key", Text, nullable=False, unique=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id")),
    Column("payload", JSONB, nullable=False),
    Column("state", Text, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("max_attempts", Integer, nullable=False),
    Column("run_after", DateTime(timezone=True), nullable=False),
    Column("locked_by", Text),
    Column("locked_until", DateTime(timezone=True)),
    Column("last_error_code", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
)

outbox = Table(
    "outbox",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("event_type", Text, nullable=False),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id")),
    Column("payload", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("published_at", DateTime(timezone=True)),
)

llm_usage = Table(
    "llm_usage",
    metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True),
    Column("day", Date, primary_key=True),
    Column("calls", Integer, nullable=False),
)

rule_versions = Table(
    "rule_versions",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("rules_sha256", LargeBinary, nullable=False),
    Column("policy_sha256", LargeBinary, nullable=False),
    Column("legal_content", JSONB, nullable=False),
    Column("policy_content", JSONB, nullable=False),
    Column("loaded_at", DateTime(timezone=True), nullable=False),
)

findings = Table(
    "findings",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("finding_key", LargeBinary, nullable=False),
    Column("detector", Text, nullable=False),
    Column("level", Text, nullable=False),
    Column("confidence", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("rule_id", Text),
    Column("rule_version_id", BigInteger, ForeignKey("rule_versions.id"), nullable=False),
    Column("policy_version", Text, nullable=False),
    Column("detector_version", SmallInteger, nullable=False),
    Column("finding_policy", Text),
    Column("letter_scope", Text),
    Column("question", Text),
    Column("group_key", Text),
    Column("statement_id", UUID(as_uuid=True), ForeignKey("statements.id")),
    Column("debit_txn_id", BigInteger),
    Column("debit_txn_date", Date),
    Column("t_date", Date),
    Column("r_date", Date),
    Column("delay_days", Integer),
    Column("amount_owed_paise", BigInteger),
    Column("already_paid_paise", BigInteger, nullable=False),
    Column("accruing", Boolean, nullable=False),
    Column("why", Text, nullable=False),
    Column("snapshot_enc", LargeBinary, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("superseded_at", DateTime(timezone=True)),
)

user_inputs = Table(
    "user_inputs",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("question", Text, nullable=False),
    Column("subject", Text, nullable=False),
    Column("answer", JSONB, nullable=False),
    Column("entered_at", DateTime(timezone=True), nullable=False),
)

cases = Table(
    "cases",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("state", Text, nullable=False),
    Column("bank_code", Text, nullable=False),
    Column("language", Text, nullable=False),
    Column("sent_on", Date),
    Column("bank_received_on", Date),
    Column("last_communication_on", Date),
    Column("unsatisfied_reply_on", Date),
    Column("escalated_on", Date),
    Column("wait_days", Integer),
    Column("escalation_eligible_on", Date),
    Column("filing_deadline_on", Date),
    Column("deadline_rule_version_id", BigInteger, ForeignKey("rule_versions.id")),
    Column("closed_reason", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

letters = Table(
    "letters",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("case_id", UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("kind", Text, nullable=False),
    Column("language", Text, nullable=False),
    Column("template_version", Integer, nullable=False),
    Column("body_enc", LargeBinary, nullable=False),
    Column("polished", Boolean, nullable=False),
    Column("guardrail_note", Text, nullable=False),
    Column("approved_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
