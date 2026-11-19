from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Response, status
from pydantic import BaseModel, EmailStr, Field

from vapas.auth.deps import ClientIpDep, CurrentUserDep, ServicesDep
from vapas.auth.passwords import MAX_PASSWORD_LENGTH
from vapas.auth.service import Grant, InvalidTokenError
from vapas.config import Settings

REFRESH_COOKIE = "vapas_refresh"
REFRESH_COOKIE_PATH = "/auth"

router = APIRouter(prefix="/auth", tags=["auth"])


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)
    consent_notice_version: str = Field(max_length=32)
    locale: Literal["en", "hi"] = "en"


class EmailIn(BaseModel):
    email: EmailStr


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class TokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class ResetIn(TokenIn):
    new_password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class Status(BaseModel):
    status: str


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


CHECK_EMAIL = Status(status="check_email")


def _set_refresh_cookie(response: Response, settings: Settings, grant: Grant) -> TokenOut:
    response.set_cookie(
        REFRESH_COOKIE,
        grant.refresh_token,
        max_age=int(settings.refresh_token_lifetime.total_seconds()),
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
        path=REFRESH_COOKIE_PATH,
    )
    return TokenOut(access_token=grant.access_token, expires_in=grant.expires_in)


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, httponly=True, secure=settings.secure_cookies, samesite="strict"
    )


@router.post("/signup", status_code=status.HTTP_202_ACCEPTED)
async def signup(body: SignupIn, services: ServicesDep, ip: ClientIpDep) -> Status:
    await services.auth.signup(body.email, body.password, body.consent_notice_version, body.locale, ip)
    return CHECK_EMAIL


@router.post("/verify-email")
async def verify_email(body: TokenIn, services: ServicesDep) -> Status:
    await services.auth.verify_email(body.token)
    return Status(status="verified")


@router.post("/resend-verification", status_code=status.HTTP_202_ACCEPTED)
async def resend_verification(body: EmailIn, services: ServicesDep, ip: ClientIpDep) -> Status:
    await services.auth.resend_verification(body.email, ip)
    return CHECK_EMAIL


@router.post("/login")
async def login(body: LoginIn, response: Response, services: ServicesDep, ip: ClientIpDep) -> TokenOut:
    grant = await services.auth.login(body.email, body.password, ip)
    return _set_refresh_cookie(response, services.settings, grant)


@router.post("/refresh")
async def refresh(
    response: Response,
    services: ServicesDep,
    ip: ClientIpDep,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> TokenOut:
    if not refresh_token:
        raise InvalidTokenError("refresh token missing")
    grant = await services.auth.refresh(refresh_token, ip)
    return _set_refresh_cookie(response, services.settings, grant)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, user: CurrentUserDep, services: ServicesDep, ip: ClientIpDep) -> None:
    await services.auth.logout(user.conn, user.user_id, user.session_id, ip)
    _clear_refresh_cookie(response, services.settings)


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
async def request_password_reset(body: EmailIn, services: ServicesDep, ip: ClientIpDep) -> Status:
    await services.auth.request_password_reset(body.email, ip)
    return CHECK_EMAIL


@router.post("/password-reset/confirm")
async def confirm_password_reset(body: ResetIn, services: ServicesDep, ip: ClientIpDep) -> Status:
    await services.auth.reset_password(body.token, body.new_password, ip)
    return Status(status="password_changed")
