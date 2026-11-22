import hashlib
import hmac
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from vapas.auth import passwords
from vapas.auth.invites import InvalidInviteError, invite_code_hash
from vapas.auth.tokens import hash_opaque_token, issue_access_token, new_opaque_token
from vapas.config import Settings
from vapas.db import repo
from vapas.db.session import Database
from vapas.mail.sender import EmailMessage, EmailSender
from vapas.privacy.notices import CURRENT_NOTICE_VERSION
from vapas.rules.loader import default_rules_dir
from vapas.security.crypto import KeyRing, new_data_key
from vapas.security.email_domains import MxLookup, Verdict, email_verdict, load_domain_policy, lookup_mx
from vapas.security.ratelimit import (
    EMAIL_PER_ACCOUNT,
    EMAIL_PER_IP,
    LOGIN_FAILURES_PER_ACCOUNT,
    LOGIN_PER_IP,
    REFRESH_PER_IP,
    SIGNUP_PER_IP,
    Limit,
    RateLimiter,
)

log = logging.getLogger(__name__)

VERIFY_EMAIL = "verify_email"
RESET_PASSWORD = "reset_password"
VERIFY_TOKEN_LIFETIME = timedelta(hours=24)
RESET_TOKEN_LIFETIME = timedelta(hours=1)
CORE_PURPOSE = "statement_analysis"


class AuthError(Exception):
    pass


class RateLimitedError(AuthError):
    def __init__(self, retry_after_seconds: float) -> None:
        super().__init__("too many requests")
        self.retry_after_seconds = retry_after_seconds


class InvalidCredentialsError(AuthError):
    pass


class InvalidTokenError(AuthError):
    pass


class ConsentVersionError(AuthError):
    pass


class EmailDomainRejectedError(AuthError):
    def __init__(self, verdict: Verdict) -> None:
        super().__init__(f"email domain rejected: {verdict.value}")
        self.verdict = verdict


@dataclass(frozen=True)
class Grant:
    access_token: str
    expires_in: int
    refresh_token: str


def _now() -> datetime:
    return datetime.now(UTC)


def _usable(row: repo.EmailTokenRow | None) -> repo.EmailTokenRow:
    if row is None or row.used_at is not None or row.expires_at <= _now():
        raise InvalidTokenError("token is invalid or expired")
    return row


class AuthService:
    def __init__(
        self, settings: Settings, db: Database, keys: KeyRing, limiter: RateLimiter, mailer: EmailSender
    ) -> None:
        self._settings = settings
        self._db = db
        self._keys = keys
        self._limiter = limiter
        self._mailer = mailer
        self._domains = load_domain_policy(settings.rules_dir or default_rules_dir())
        self._mx: MxLookup | None = lookup_mx if settings.email_mx_check else None
        secret = settings.jwt_secret.get_secret_value().encode()
        self._ip_key = hmac.new(secret, b"ip-hash", hashlib.sha256).digest()

    def ip_hash(self, ip: str) -> bytes:
        return hmac.new(self._ip_key, ip.encode(), hashlib.sha256).digest()[:16]

    async def _require(self, limit: Limit, subject: str) -> None:
        decision = await self._limiter.hit(limit, subject)
        if not decision.allowed:
            raise RateLimitedError(decision.retry_after_seconds)

    async def _send_link(self, email: str, subject: str, page: str, token: str, kind: str) -> None:
        link = f"{self._settings.public_app_url}/{page}#token={token}"
        body = f"Open this link to continue:\n{link}\n\nIf you did not ask for this, ignore this email."
        try:
            await self._mailer.send(EmailMessage(to=email, subject=subject, body=body, kind=kind))
        except Exception as error:
            log.error("auth email not sent", extra={"kind": kind, "error_type": type(error).__name__})

    async def _lookup_token(self, token: str, purpose: str) -> repo.EmailTokenRow:
        async with self._db.anonymous() as conn:
            return _usable(await repo.lookup_email_token(conn, hash_opaque_token(token), purpose))

    async def signup(
        self, email: str, password: str, notice_version: str, locale: str, ip: str, invite_code: str | None = None
    ) -> None:
        await self._require(SIGNUP_PER_IP, ip)
        if notice_version != CURRENT_NOTICE_VERSION:
            raise ConsentVersionError("consent notice version is not current")
        if self._settings.invite_only and not invite_code:
            raise InvalidInviteError("an invite code is required")
        verdict = await email_verdict(email, self._domains, self._mx)
        if verdict is not Verdict.ALLOWED:
            log.info("signup refused for email domain", extra={"verdict": verdict.value})
            raise EmailDomainRejectedError(verdict)
        passwords.check_password_strength(password, email)
        user_id = uuid4()
        token = new_opaque_token()
        try:
            async with self._db.as_user(user_id) as conn:
                invite_id = None
                if self._settings.invite_only and invite_code:
                    invite_id = await repo.redeem_invite(conn, invite_code_hash(invite_code))
                    if invite_id is None:
                        raise InvalidInviteError("invite code is invalid, used up or expired")
                await repo.insert_user(conn, user_id, email, passwords.hash_password(password), locale, invite_id)
                await repo.insert_user_key(conn, user_id, self._keys.wrap(new_data_key(), user_id))
                await repo.insert_consent(conn, user_id, notice_version, CORE_PURPOSE)
                expires = _now() + VERIFY_TOKEN_LIFETIME
                await repo.insert_email_token(conn, user_id, VERIFY_EMAIL, hash_opaque_token(token), expires)
                await repo.write_audit(conn, user_id, "signup", self.ip_hash(ip))
        except IntegrityError:
            log.info("signup for an existing email ignored")
            return
        await self._send_link(email, "Verify your VAPAS email", "verify-email", token, VERIFY_EMAIL)

    async def verify_email(self, token: str) -> None:
        row = await self._lookup_token(token, VERIFY_EMAIL)
        async with self._db.as_user(row.user_id) as conn:
            if not await repo.consume_email_token(conn, row.id):
                raise InvalidTokenError("token is invalid or expired")
            await repo.mark_email_verified(conn, row.user_id)
            await repo.write_audit(conn, row.user_id, "email_verified")

    async def _account_for_email(self, email: str, ip: str) -> repo.LoginRow | None:
        await self._require(EMAIL_PER_IP, ip)
        await self._require(EMAIL_PER_ACCOUNT, email.casefold())
        async with self._db.anonymous() as conn:
            return await repo.lookup_login(conn, email)

    async def resend_verification(self, email: str, ip: str) -> None:
        account = await self._account_for_email(email, ip)
        if account is None or account.email_verified_at is not None:
            return
        token = new_opaque_token()
        async with self._db.as_user(account.user_id) as conn:
            expires = _now() + VERIFY_TOKEN_LIFETIME
            await repo.insert_email_token(conn, account.user_id, VERIFY_EMAIL, hash_opaque_token(token), expires)
        await self._send_link(email, "Verify your VAPAS email", "verify-email", token, VERIFY_EMAIL)

    async def request_password_reset(self, email: str, ip: str) -> None:
        account = await self._account_for_email(email, ip)
        if account is None:
            return
        token = new_opaque_token()
        async with self._db.as_user(account.user_id) as conn:
            expires = _now() + RESET_TOKEN_LIFETIME
            await repo.insert_email_token(conn, account.user_id, RESET_PASSWORD, hash_opaque_token(token), expires)
            await repo.write_audit(conn, account.user_id, "password_reset_requested", self.ip_hash(ip))
        await self._send_link(email, "Reset your VAPAS password", "reset-password", token, RESET_PASSWORD)

    async def reset_password(self, token: str, new_password: str, ip: str) -> None:
        row = await self._lookup_token(token, RESET_PASSWORD)
        async with self._db.as_user(row.user_id) as conn:
            account = await repo.get_user(conn, row.user_id)
            if account is None:
                raise InvalidTokenError("token is invalid or expired")
            passwords.check_password_strength(new_password, account.email)
            if not await repo.consume_email_token(conn, row.id):
                raise InvalidTokenError("token is invalid or expired")
            await repo.update_password(conn, row.user_id, passwords.hash_password(new_password))
            await repo.revoke_all_sessions(conn, row.user_id)
            await repo.mark_email_verified(conn, row.user_id)
            await repo.write_audit(conn, row.user_id, "password_reset", self.ip_hash(ip))

    async def login(self, email: str, password: str, ip: str) -> Grant:
        await self._require(LOGIN_PER_IP, ip)
        async with self._db.anonymous() as conn:
            account = await repo.lookup_login(conn, email)
        if account is None:
            passwords.burn_verification_time(password)
            raise InvalidCredentialsError("invalid email or password")
        failures = await self._limiter.peek(LOGIN_FAILURES_PER_ACCOUNT, str(account.user_id))
        if not failures.allowed:
            raise RateLimitedError(failures.retry_after_seconds)
        if not passwords.verify_password(account.password_hash, password):
            await self._limiter.hit(LOGIN_FAILURES_PER_ACCOUNT, str(account.user_id))
            async with self._db.as_user(account.user_id) as conn:
                await repo.write_audit(conn, account.user_id, "login_failed", self.ip_hash(ip))
            raise InvalidCredentialsError("invalid email or password")
        expires = _now() + self._settings.refresh_token_lifetime
        async with self._db.as_user(account.user_id) as conn:
            if passwords.needs_rehash(account.password_hash):
                await repo.rehash_password(conn, account.user_id, passwords.hash_password(password))
            grant = await self._open_session(conn, account.user_id, uuid4(), uuid4(), expires)
            await repo.write_audit(conn, account.user_id, "login", self.ip_hash(ip))
        return grant

    async def _open_session(
        self, conn: AsyncConnection, user_id: UUID, session_id: UUID, family_id: UUID, expires: datetime
    ) -> Grant:
        refresh = new_opaque_token()
        await repo.insert_session(conn, session_id, user_id, family_id, hash_opaque_token(refresh), expires)
        lifetime = self._settings.access_token_lifetime
        secret = self._settings.jwt_secret.get_secret_value()
        access = issue_access_token(secret, user_id, session_id, lifetime, _now())
        return Grant(access_token=access, expires_in=int(lifetime.total_seconds()), refresh_token=refresh)

    async def refresh(self, refresh_token: str, ip: str) -> Grant:
        await self._require(REFRESH_PER_IP, ip)
        async with self._db.anonymous() as conn:
            current = await repo.lookup_session(conn, hash_opaque_token(refresh_token))
        if current is None or current.expires_at <= _now():
            raise InvalidTokenError("refresh token is invalid or expired")
        if current.revoked_at is None:
            new_session_id = uuid4()
            async with self._db.as_user(current.user_id) as conn:
                if await repo.rotate_out_session(conn, current.id, new_session_id):
                    grant = await self._open_session(
                        conn, current.user_id, new_session_id, current.family_id, current.expires_at
                    )
                    await repo.write_audit(conn, current.user_id, "session_refreshed", self.ip_hash(ip))
                    return grant
        await self._revoke_after_reuse(current, ip)
        raise InvalidTokenError("refresh token was already used")

    async def _revoke_after_reuse(self, session: repo.SessionRow, ip: str) -> None:
        async with self._db.as_user(session.user_id) as conn:
            await repo.revoke_family(conn, session.family_id)
            await repo.write_audit(conn, session.user_id, "refresh_token_reuse_detected", self.ip_hash(ip))
        log.warning("refresh token reuse detected; session family revoked")

    async def logout(self, conn: AsyncConnection, user_id: UUID, session_id: UUID, ip: str) -> None:
        family = await repo.session_family(conn, session_id)
        if family is not None:
            await repo.revoke_family(conn, family)
        await repo.write_audit(conn, user_id, "logout", self.ip_hash(ip))
