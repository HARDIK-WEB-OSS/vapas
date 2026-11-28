from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncConnection

from vapas.auth.tokens import InvalidAccessTokenError, decode_access_token
from vapas.db import repo
from vapas.security.client_ip import resolve_client_ip
from vapas.security.kill_switch import ensure_intake_open
from vapas.services import Services

bearer = HTTPBearer(auto_error=False)
UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="not_authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


def client_ip(request: Request) -> str:
    return resolve_client_ip(request, get_services(request).settings.client_ip_header)


@dataclass(frozen=True)
class CurrentUser:
    user_id: UUID
    session_id: UUID
    conn: AsyncConnection


async def current_user(
    services: Annotated[Services, Depends(get_services)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> AsyncIterator[CurrentUser]:
    if credentials is None:
        raise UNAUTHORIZED
    try:
        claims = decode_access_token(services.settings.jwt_secret.get_secret_value(), credentials.credentials)
    except InvalidAccessTokenError as error:
        raise UNAUTHORIZED from error
    async with services.db.as_user(claims.user_id) as conn:
        if not await repo.session_is_active(conn, claims.session_id, claims.user_id):
            raise UNAUTHORIZED
        yield CurrentUser(user_id=claims.user_id, session_id=claims.session_id, conn=conn)


ServicesDep = Annotated[Services, Depends(get_services)]
CurrentUserDep = Annotated[CurrentUser, Depends(current_user, scope="function")]
ClientIpDep = Annotated[str, Depends(client_ip)]


def intake_open(services: ServicesDep) -> None:
    ensure_intake_open(services.settings.kill_switch)


IntakeOpen = Depends(intake_open)
