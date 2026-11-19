import math

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from vapas.auth.passwords import WeakPasswordError
from vapas.auth.service import (
    ConsentVersionError,
    InvalidCredentialsError,
    InvalidTokenError,
    RateLimitedError,
)
from vapas.security.ratelimit import RateLimiterUnavailableError


def _error(status_code: int, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"error": code, "message": message}, status_code=status_code, headers=headers)


async def rate_limited(_: Request, error: Exception) -> JSONResponse:
    retry = math.ceil(error.retry_after_seconds) if isinstance(error, RateLimitedError) else 60
    headers = {"Retry-After": str(max(retry, 1))}
    return _error(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited", "Too many attempts. Try again later.", headers)


async def limiter_down(_: Request, __: Exception) -> JSONResponse:
    return _error(status.HTTP_503_SERVICE_UNAVAILABLE, "temporarily_unavailable", "Please try again shortly.")


async def invalid_credentials(_: Request, __: Exception) -> JSONResponse:
    return _error(status.HTTP_401_UNAUTHORIZED, "invalid_credentials", "Invalid email or password.")


async def invalid_token(_: Request, __: Exception) -> JSONResponse:
    return _error(status.HTTP_400_BAD_REQUEST, "invalid_token", "This link or session is invalid or has expired.")


async def consent_version(_: Request, __: Exception) -> JSONResponse:
    return _error(status.HTTP_409_CONFLICT, "consent_notice_changed", "Please review the current privacy notice.")


async def weak_password(_: Request, error: Exception) -> JSONResponse:
    return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "weak_password", str(error))


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RateLimitedError, rate_limited)
    app.add_exception_handler(RateLimiterUnavailableError, limiter_down)
    app.add_exception_handler(InvalidCredentialsError, invalid_credentials)
    app.add_exception_handler(InvalidTokenError, invalid_token)
    app.add_exception_handler(ConsentVersionError, consent_version)
    app.add_exception_handler(WeakPasswordError, weak_password)
