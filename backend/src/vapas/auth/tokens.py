import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt

ALGORITHM = "HS256"
ISSUER = "vapas"
AUDIENCE = "vapas-api"
OPAQUE_TOKEN_BYTES = 32


class InvalidAccessTokenError(Exception):
    pass


@dataclass(frozen=True)
class AccessClaims:
    user_id: UUID
    session_id: UUID
    expires_at: datetime


def issue_access_token(secret: str, user_id: UUID, session_id: UUID, lifetime: timedelta, now: datetime) -> str:
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(user_id),
        "sid": str(session_id),
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
        "typ": "access",
    }
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


def decode_access_token(secret: str, token: str) -> AccessClaims:
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "sid", "iss", "aud"]},
        )
        if claims.get("typ") != "access":
            raise InvalidAccessTokenError("wrong token type")
        return AccessClaims(
            user_id=UUID(claims["sub"]),
            session_id=UUID(claims["sid"]),
            expires_at=datetime.fromtimestamp(claims["exp"], UTC),
        )
    except (jwt.PyJWTError, ValueError, KeyError) as error:
        raise InvalidAccessTokenError("invalid access token") from error


def new_opaque_token() -> str:
    return secrets.token_urlsafe(OPAQUE_TOKEN_BYTES)


def hash_opaque_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()
