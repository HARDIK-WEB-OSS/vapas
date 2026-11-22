from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from vapas.db.models import audit_log, consent_notices, consents, email_tokens, sessions, user_keys, users
from vapas.security.crypto import WrappedKey


@dataclass(frozen=True)
class LoginRow:
    user_id: UUID
    password_hash: str
    email_verified_at: datetime | None


@dataclass(frozen=True)
class SessionRow:
    id: UUID
    user_id: UUID
    family_id: UUID
    expires_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True)
class EmailTokenRow:
    id: UUID
    user_id: UUID
    expires_at: datetime
    used_at: datetime | None


@dataclass(frozen=True)
class NoticeRow:
    version: str
    text_en: str
    text_hi: str


@dataclass(frozen=True)
class UserRow:
    id: UUID
    email: str
    email_verified_at: datetime | None
    locale: str
    created_at: datetime


async def lookup_login(conn: AsyncConnection, email: str) -> LoginRow | None:
    row = (await conn.execute(text("SELECT * FROM auth_lookup(:email)"), {"email": email})).first()
    return None if row is None else LoginRow(row.id, row.password_hash, row.email_verified_at)


async def lookup_session(conn: AsyncConnection, token_hash: bytes) -> SessionRow | None:
    row = (await conn.execute(text("SELECT * FROM session_lookup(:h)"), {"h": token_hash})).first()
    return None if row is None else SessionRow(row.id, row.user_id, row.family_id, row.expires_at, row.revoked_at)


async def lookup_email_token(conn: AsyncConnection, token_hash: bytes, purpose: str) -> EmailTokenRow | None:
    statement = text("SELECT * FROM email_token_lookup(:h, :p)")
    row = (await conn.execute(statement, {"h": token_hash, "p": purpose})).first()
    return None if row is None else EmailTokenRow(row.id, row.user_id, row.expires_at, row.used_at)


async def current_notice(conn: AsyncConnection) -> NoticeRow | None:
    statement = select(consent_notices).order_by(consent_notices.c.published_at.desc()).limit(1)
    row = (await conn.execute(statement)).first()
    return None if row is None else NoticeRow(row.version, row.text_en, row.text_hi)


async def insert_user(
    conn: AsyncConnection, user_id: UUID, email: str, password_hash: str, locale: str, invite_id: UUID | None = None
) -> None:
    values = {"id": user_id, "email": email, "password_hash": password_hash, "locale": locale, "invite_id": invite_id}
    await conn.execute(insert(users).values(**values))


async def redeem_invite(conn: AsyncConnection, code_hash: bytes) -> UUID | None:
    invite_id: UUID | None = await conn.scalar(text("SELECT redeem_invite(:h)"), {"h": code_hash})
    return invite_id


async def set_locale(conn: AsyncConnection, user_id: UUID, locale: str) -> None:
    await conn.execute(update(users).where(users.c.id == user_id).values(locale=locale))


async def get_user(conn: AsyncConnection, user_id: UUID) -> UserRow | None:
    columns = (users.c.id, users.c.email, users.c.email_verified_at, users.c.locale, users.c.created_at)
    row = (await conn.execute(select(*columns).where(users.c.id == user_id))).first()
    return None if row is None else UserRow(row.id, row.email, row.email_verified_at, row.locale, row.created_at)


async def password_hash_of(conn: AsyncConnection, user_id: UUID) -> str | None:
    value = await conn.scalar(select(users.c.password_hash).where(users.c.id == user_id))
    return None if value is None else str(value)


async def update_password(conn: AsyncConnection, user_id: UUID, password_hash: str) -> None:
    values = {"password_hash": password_hash, "password_changed_at": func.now()}
    await conn.execute(update(users).where(users.c.id == user_id).values(**values))


async def rehash_password(conn: AsyncConnection, user_id: UUID, password_hash: str) -> None:
    await conn.execute(update(users).where(users.c.id == user_id).values(password_hash=password_hash))


async def mark_email_verified(conn: AsyncConnection, user_id: UUID) -> None:
    statement = update(users).where(users.c.id == user_id, users.c.email_verified_at.is_(None))
    await conn.execute(statement.values(email_verified_at=func.now()))


async def insert_user_key(conn: AsyncConnection, user_id: UUID, wrapped: WrappedKey) -> None:
    values = {"user_id": user_id, "wrapped_dek": wrapped.blob, "kek_version": wrapped.kek_version}
    await conn.execute(insert(user_keys).values(**values))


async def user_key(conn: AsyncConnection, user_id: UUID) -> WrappedKey | None:
    statement = select(user_keys.c.wrapped_dek, user_keys.c.kek_version).where(user_keys.c.user_id == user_id)
    row = (await conn.execute(statement)).first()
    return None if row is None else WrappedKey(kek_version=row.kek_version, blob=bytes(row.wrapped_dek))


async def insert_consent(conn: AsyncConnection, user_id: UUID, notice_version: str, purpose: str) -> None:
    values = {"id": uuid4(), "user_id": user_id, "notice_version": notice_version, "purpose": purpose}
    await conn.execute(insert(consents).values(**values))


async def has_active_consent(conn: AsyncConnection, user_id: UUID, purpose: str) -> bool:
    statement = select(func.count()).where(
        consents.c.user_id == user_id, consents.c.purpose == purpose, consents.c.withdrawn_at.is_(None)
    )
    return bool(await conn.scalar(statement))


async def withdraw_consent(conn: AsyncConnection, user_id: UUID, purpose: str) -> int:
    statement = update(consents).where(
        consents.c.user_id == user_id, consents.c.purpose == purpose, consents.c.withdrawn_at.is_(None)
    )
    return (await conn.execute(statement.values(withdrawn_at=func.now()))).rowcount


async def insert_email_token(
    conn: AsyncConnection, user_id: UUID, purpose: str, token_hash: bytes, expires_at: datetime
) -> None:
    values = {"id": uuid4(), "user_id": user_id, "purpose": purpose, "token_hash": token_hash}
    await conn.execute(insert(email_tokens).values(**values, expires_at=expires_at))


async def consume_email_token(conn: AsyncConnection, token_id: UUID) -> bool:
    statement = update(email_tokens).where(email_tokens.c.id == token_id, email_tokens.c.used_at.is_(None))
    return (await conn.execute(statement.values(used_at=func.now()))).rowcount == 1


async def insert_session(
    conn: AsyncConnection, session_id: UUID, user_id: UUID, family_id: UUID, token_hash: bytes, expires_at: datetime
) -> None:
    values = {"id": session_id, "user_id": user_id, "family_id": family_id, "refresh_token_hash": token_hash}
    await conn.execute(insert(sessions).values(**values, expires_at=expires_at))


async def rotate_out_session(conn: AsyncConnection, session_id: UUID, replaced_by: UUID) -> bool:
    statement = update(sessions).where(sessions.c.id == session_id, sessions.c.revoked_at.is_(None))
    return (await conn.execute(statement.values(revoked_at=func.now(), replaced_by=replaced_by))).rowcount == 1


async def revoke_family(conn: AsyncConnection, family_id: UUID) -> int:
    statement = update(sessions).where(sessions.c.family_id == family_id, sessions.c.revoked_at.is_(None))
    return (await conn.execute(statement.values(revoked_at=func.now()))).rowcount


async def revoke_all_sessions(conn: AsyncConnection, user_id: UUID) -> int:
    statement = update(sessions).where(sessions.c.user_id == user_id, sessions.c.revoked_at.is_(None))
    return (await conn.execute(statement.values(revoked_at=func.now()))).rowcount


async def session_family(conn: AsyncConnection, session_id: UUID) -> UUID | None:
    value = await conn.scalar(select(sessions.c.family_id).where(sessions.c.id == session_id))
    return None if value is None else UUID(str(value))


async def session_is_active(conn: AsyncConnection, session_id: UUID, user_id: UUID) -> bool:
    statement = select(func.count()).where(
        sessions.c.id == session_id,
        sessions.c.user_id == user_id,
        sessions.c.revoked_at.is_(None),
        sessions.c.expires_at > func.now(),
    )
    return bool(await conn.scalar(statement))


async def write_audit(
    conn: AsyncConnection,
    user_id: UUID | None,
    action: str,
    ip_hash: bytes | None = None,
    actor: str = "user",
) -> None:
    values = {"user_id": user_id, "actor": actor, "action": action, "ip_hash": ip_hash}
    await conn.execute(insert(audit_log).values(**values))


async def delete_user(conn: AsyncConnection, user_id: UUID) -> bool:
    return (await conn.execute(users.delete().where(users.c.id == user_id))).rowcount == 1


def _plain(row: RowMapping) -> dict[str, Any]:
    return {key: value for key, value in row.items()}


async def export_user_data(conn: AsyncConnection, user_id: UUID) -> dict[str, list[dict[str, Any]]]:
    profile = select(users.c.id, users.c.email, users.c.email_verified_at, users.c.locale, users.c.created_at)
    session_columns = (sessions.c.id, sessions.c.created_at, sessions.c.expires_at, sessions.c.revoked_at)
    audit_columns = (audit_log.c.action, audit_log.c.actor, audit_log.c.at)
    queries = {
        "profile": profile.where(users.c.id == user_id),
        "consents": select(consents).where(consents.c.user_id == user_id).order_by(consents.c.granted_at),
        "sessions": select(*session_columns).where(sessions.c.user_id == user_id).order_by(sessions.c.created_at),
        "audit_log": select(*audit_columns).where(audit_log.c.user_id == user_id).order_by(audit_log.c.id),
    }
    return {name: [_plain(r) for r in (await conn.execute(q)).mappings()] for name, q in queries.items()}
