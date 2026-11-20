from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncConnection

from vapas.db import repo
from vapas.security.crypto import FieldCipher, KeyRing

PDF_PASSWORD_TTL_SECONDS = 900
NARRATION = "transactions.narration"
REF_NO = "transactions.ref_no"
EXT_REF = "transactions.ext_ref"
REFERENCE_INDEX = "transactions.reference"


class MissingDataKeyError(LookupError):
    pass


async def user_cipher(conn: AsyncConnection, keys: KeyRing, user_id: UUID) -> FieldCipher:
    wrapped = await repo.user_key(conn, user_id)
    if wrapped is None:
        raise MissingDataKeyError("user has no data key")
    return FieldCipher(keys.unwrap(wrapped, user_id), user_id)


def _password_key(statement_id: UUID) -> str:
    return f"pdfpw:{statement_id}"


def _password_context(statement_id: UUID) -> str:
    return f"pdf_password:{statement_id}"


async def stash_pdf_password(redis: Redis, cipher: FieldCipher, statement_id: UUID, password: str) -> None:
    sealed = cipher.encrypt(password, _password_context(statement_id))
    await redis.set(_password_key(statement_id), sealed, ex=PDF_PASSWORD_TTL_SECONDS)


async def take_pdf_password(redis: Redis, cipher: FieldCipher, statement_id: UUID) -> str | None:
    sealed = await redis.getdel(_password_key(statement_id))
    if sealed is None:
        return None
    blob = sealed if isinstance(sealed, bytes) else sealed.encode("latin-1")
    return cipher.decrypt(blob, _password_context(statement_id))
