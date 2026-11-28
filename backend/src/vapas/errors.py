import logging
import math

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from vapas.auth.invites import InvalidInviteError
from vapas.auth.passwords import WeakPasswordError
from vapas.auth.service import (
    ConsentVersionError,
    EmailDomainRejectedError,
    InvalidCredentialsError,
    InvalidTokenError,
    RateLimitedError,
)
from vapas.security.kill_switch import ServicePausedError
from vapas.security.ratelimit import RateLimiterUnavailableError

log = logging.getLogger(__name__)


def _error(status_code: int, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"error": code, "message": message}, status_code=status_code, headers=headers)


async def rate_limited(_: Request, error: Exception) -> JSONResponse:
    retry = math.ceil(error.retry_after_seconds) if isinstance(error, RateLimitedError) else 60
    headers = {"Retry-After": str(max(retry, 1))}
    return _error(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited", "Too many attempts. Try again later.", headers)


async def limiter_down(_: Request, __: Exception) -> JSONResponse:
    return _error(status.HTTP_503_SERVICE_UNAVAILABLE, "temporarily_unavailable", "Please try again shortly.")


async def database_down(_: Request, error: Exception) -> JSONResponse:
    log.error("database unavailable", extra={"error_type": type(error).__name__})
    return _error(status.HTTP_503_SERVICE_UNAVAILABLE, "temporarily_unavailable", "Please try again shortly.")


async def email_domain_rejected(_: Request, error: Exception) -> JSONResponse:
    verdict = error.verdict.value if isinstance(error, EmailDomainRejectedError) else "disposable"
    code = "email_disposable" if verdict == "disposable" else "email_no_mail_server"
    return _error(status.HTTP_400_BAD_REQUEST, code, "This email address cannot be used to sign up.")


async def invalid_invite(_: Request, __: Exception) -> JSONResponse:
    return _error(status.HTTP_400_BAD_REQUEST, "invalid_invite", "This invite code is not valid.")


async def invalid_credentials(_: Request, __: Exception) -> JSONResponse:
    return _error(status.HTTP_401_UNAUTHORIZED, "invalid_credentials", "Invalid email or password.")


async def invalid_token(_: Request, __: Exception) -> JSONResponse:
    return _error(status.HTTP_400_BAD_REQUEST, "invalid_token", "This link or session is invalid or has expired.")


async def consent_version(_: Request, __: Exception) -> JSONResponse:
    return _error(status.HTTP_409_CONFLICT, "consent_notice_changed", "Please review the current privacy notice.")


async def weak_password(_: Request, error: Exception) -> JSONResponse:
    return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "weak_password", str(error))


async def service_paused(_: Request, __: Exception) -> JSONResponse:
    return _error(status.HTTP_503_SERVICE_UNAVAILABLE, "service_paused", "New signups and uploads are paused.")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ServicePausedError, service_paused)
    app.add_exception_handler(RateLimitedError, rate_limited)
    app.add_exception_handler(RateLimiterUnavailableError, limiter_down)
    app.add_exception_handler(OperationalError, database_down)
    app.add_exception_handler(ConnectionRefusedError, database_down)
    app.add_exception_handler(InvalidCredentialsError, invalid_credentials)
    app.add_exception_handler(InvalidInviteError, invalid_invite)
    app.add_exception_handler(EmailDomainRejectedError, email_domain_rejected)
    app.add_exception_handler(InvalidTokenError, invalid_token)
    app.add_exception_handler(ConsentVersionError, consent_version)
    app.add_exception_handler(WeakPasswordError, weak_password)
