from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128

_hasher = PasswordHasher()


class WeakPasswordError(ValueError):
    pass


def check_password_strength(password: str, email: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise WeakPasswordError(f"password must be at most {MAX_PASSWORD_LENGTH} characters")
    if password.strip().casefold() == email.strip().casefold():
        raise WeakPasswordError("password must not be your email address")
    if len(set(password)) < 4:
        raise WeakPasswordError("password is too repetitive")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _hasher.hash("vapas-timing-equaliser")


def burn_verification_time(password: str) -> None:
    verify_password(_dummy_hash(), password)
