from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from vapas.auth.passwords import (
    WeakPasswordError,
    check_password_strength,
    hash_password,
    needs_rehash,
    verify_password,
)
from vapas.auth.tokens import (
    InvalidAccessTokenError,
    decode_access_token,
    hash_opaque_token,
    issue_access_token,
    new_opaque_token,
)

SECRET = "test-jwt-secret-0123456789abcdef0123456789"


def test_passwords_use_argon2id() -> None:
    stored = hash_password("correct horse battery")
    assert stored.startswith("$argon2id$")
    assert verify_password(stored, "correct horse battery")
    assert not verify_password(stored, "correct horse batterY")
    assert not needs_rehash(stored)


def test_garbage_hash_never_verifies() -> None:
    assert not verify_password("not-a-hash", "anything")


@pytest.mark.parametrize(
    ("password", "email"),
    [("short", "a@b.in"), ("x" * 129, "a@b.in"), ("person@example.in", "person@example.in"), ("aaaaabbbbbb", "a@b.in")],
)
def test_weak_passwords_are_rejected(password: str, email: str) -> None:
    with pytest.raises(WeakPasswordError):
        check_password_strength(password, email)


def test_reasonable_password_is_accepted() -> None:
    check_password_strength("statement-audit-2026", "person@example.in")


def test_access_token_round_trip() -> None:
    user, session = uuid4(), uuid4()
    now = datetime.now(UTC)
    claims = decode_access_token(SECRET, issue_access_token(SECRET, user, session, timedelta(minutes=15), now))
    assert (claims.user_id, claims.session_id) == (user, session)


def test_expired_access_token_is_rejected() -> None:
    past = datetime.now(UTC) - timedelta(hours=1)
    token = issue_access_token(SECRET, uuid4(), uuid4(), timedelta(minutes=15), past)
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(SECRET, token)


def test_token_signed_with_another_secret_is_rejected() -> None:
    token = issue_access_token(
        "another-secret-0123456789abcdef012345", uuid4(), uuid4(), timedelta(minutes=5), datetime.now(UTC)
    )
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(SECRET, token)


def test_unsigned_token_is_rejected() -> None:
    now = datetime.now(UTC)
    claims = {
        "sub": str(uuid4()),
        "sid": str(uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(
            SECRET, jwt.encode(claims | {"iss": "vapas", "aud": "vapas-api", "typ": "access"}, key="", algorithm="none")
        )


def test_wrong_token_type_is_rejected() -> None:
    now = datetime.now(UTC)
    claims = {
        "iss": "vapas",
        "aud": "vapas-api",
        "sub": str(uuid4()),
        "sid": str(uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "typ": "refresh",
    }
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(SECRET, jwt.encode(claims, SECRET, algorithm="HS256"))


def test_opaque_tokens_are_random_and_stored_hashed() -> None:
    a, b = new_opaque_token(), new_opaque_token()
    assert a != b
    assert len(a) >= 40
    assert hash_opaque_token(a) == hash_opaque_token(a)
    assert len(hash_opaque_token(a)) == 32
