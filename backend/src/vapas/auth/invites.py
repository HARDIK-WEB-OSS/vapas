import hashlib
import secrets

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_GROUPS = 4
GROUP_LENGTH = 4
MAX_CODE_LENGTH = 40


class InvalidInviteError(Exception):
    pass


def new_invite_code() -> str:
    groups = ("".join(secrets.choice(CODE_ALPHABET) for _ in range(GROUP_LENGTH)) for _ in range(CODE_GROUPS))
    return "-".join(groups)


def normalize_invite_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def invite_code_hash(code: str) -> bytes:
    return hashlib.sha256(normalize_invite_code(code).encode()).digest()
