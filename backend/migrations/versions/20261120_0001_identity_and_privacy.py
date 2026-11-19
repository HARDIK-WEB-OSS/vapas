from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USER_TABLES = ("users", "user_keys", "sessions", "email_tokens", "consents")

TABLES = """
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE users (
    id uuid PRIMARY KEY,
    email citext NOT NULL UNIQUE CHECK (length(email) <= 254),
    password_hash text NOT NULL,
    email_verified_at timestamptz,
    locale text NOT NULL DEFAULT 'en' CHECK (locale IN ('en', 'hi')),
    password_changed_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE user_keys (
    user_id uuid PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    wrapped_dek bytea NOT NULL,
    kek_version smallint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    rotated_at timestamptz
);

CREATE TABLE sessions (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    family_id uuid NOT NULL,
    refresh_token_hash bytea NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    replaced_by uuid
);
CREATE INDEX sessions_user_active ON sessions (user_id) WHERE revoked_at IS NULL;
CREATE INDEX sessions_family ON sessions (family_id);

CREATE TABLE email_tokens (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    purpose text NOT NULL CHECK (purpose IN ('verify_email', 'reset_password')),
    token_hash bytea NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    used_at timestamptz
);
CREATE INDEX email_tokens_user ON email_tokens (user_id, purpose);

CREATE TABLE consent_notices (
    version text PRIMARY KEY,
    text_en text NOT NULL,
    text_hi text NOT NULL,
    sha256 bytea NOT NULL,
    published_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE consents (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    notice_version text NOT NULL REFERENCES consent_notices (version),
    purpose text NOT NULL CHECK (purpose IN ('statement_analysis')),
    granted_at timestamptz NOT NULL DEFAULT now(),
    withdrawn_at timestamptz
);
CREATE INDEX consents_user_purpose ON consents (user_id, purpose);

CREATE TABLE audit_log (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id uuid REFERENCES users (id) ON DELETE SET NULL,
    actor text NOT NULL CHECK (actor IN ('user', 'system')),
    action text NOT NULL,
    entity_type text,
    entity_id uuid,
    ip_hash bytea,
    at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_log_user_at ON audit_log (user_id, at);
"""

SECURITY = """
CREATE FUNCTION app_user_id() RETURNS uuid
    LANGUAGE sql STABLE
    AS $$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$;

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
CREATE POLICY owner ON users USING (id = app_user_id()) WITH CHECK (id = app_user_id());

ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_reads ON audit_log FOR SELECT USING (user_id = app_user_id());
CREATE POLICY own_or_anonymous_writes ON audit_log FOR INSERT
    WITH CHECK (user_id IS NULL OR user_id = app_user_id());

CREATE FUNCTION auth_lookup(p_email citext)
    RETURNS TABLE (id uuid, password_hash text, email_verified_at timestamptz)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$ SELECT u.id, u.password_hash, u.email_verified_at FROM public.users u WHERE u.email = p_email $$;

CREATE FUNCTION session_lookup(p_token_hash bytea)
    RETURNS TABLE (id uuid, user_id uuid, family_id uuid, expires_at timestamptz, revoked_at timestamptz)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$
        SELECT s.id, s.user_id, s.family_id, s.expires_at, s.revoked_at
        FROM public.sessions s WHERE s.refresh_token_hash = p_token_hash
    $$;

CREATE FUNCTION email_token_lookup(p_token_hash bytea, p_purpose text)
    RETURNS TABLE (id uuid, user_id uuid, expires_at timestamptz, used_at timestamptz)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$
        SELECT t.id, t.user_id, t.expires_at, t.used_at
        FROM public.email_tokens t WHERE t.token_hash = p_token_hash AND t.purpose = p_purpose
    $$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON FUNCTION auth_lookup(citext), session_lookup(bytea), email_token_lookup(bytea, text) FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO vapas_app, vapas_worker;
GRANT EXECUTE ON FUNCTION app_user_id() TO vapas_app, vapas_worker;
GRANT EXECUTE ON FUNCTION auth_lookup(citext), session_lookup(bytea), email_token_lookup(bytea, text) TO vapas_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON users, user_keys, sessions, email_tokens, consents TO vapas_app;
GRANT SELECT, INSERT ON audit_log TO vapas_app, vapas_worker;
GRANT SELECT ON consent_notices TO vapas_app, vapas_worker;
GRANT SELECT ON user_keys, consents TO vapas_worker;
"""


def owner_policy(table: str) -> str:
    return f"""
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
CREATE POLICY owner ON {table} USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id());
"""


def run_script(script: str) -> None:
    for statement in (part.strip() for part in script.split(";\n")):
        if statement:
            op.execute(statement)


def upgrade() -> None:
    run_script(TABLES)
    run_script(SECURITY)
    for table in USER_TABLES[1:]:
        run_script(owner_policy(table))


def downgrade() -> None:
    op.execute("DROP FUNCTION auth_lookup(citext), session_lookup(bytea), email_token_lookup(bytea, text)")
    op.execute("DROP TABLE audit_log, consents, consent_notices, email_tokens, sessions, user_keys, users")
    op.execute("DROP FUNCTION app_user_id()")
