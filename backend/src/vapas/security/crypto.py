import base64
import hashlib
import hmac
import os
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

KEY_BYTES = 32
NONCE_BYTES = 12
FORMAT_VERSION = 1
BLIND_INDEX_BYTES = 16
FIELD_KEY_INFO = b"vapas-field-encryption-v1"
BLIND_INDEX_INFO = b"vapas-blind-index-v1"


class CryptoError(Exception):
    pass


class UnknownKeyVersionError(CryptoError):
    pass


class InvalidCiphertextError(CryptoError):
    pass


def decode_key(encoded: str) -> bytes:
    key = base64.b64decode(encoded, validate=True)
    if len(key) != KEY_BYTES:
        raise CryptoError(f"keys must be {KEY_BYTES} bytes")
    return key


@dataclass(frozen=True)
class WrappedKey:
    kek_version: int
    blob: bytes


class KeyRing:
    def __init__(self, keks: Mapping[int, bytes], active_version: int) -> None:
        if active_version not in keks:
            raise UnknownKeyVersionError(f"active KEK version {active_version} is not configured")
        if any(len(key) != KEY_BYTES for key in keks.values()):
            raise CryptoError(f"keys must be {KEY_BYTES} bytes")
        self._keks = dict(keks)
        self.active_version = active_version

    def _kek(self, version: int) -> AESGCM:
        if version not in self._keks:
            raise UnknownKeyVersionError(f"KEK version {version} is not configured")
        return AESGCM(self._keks[version])

    def wrap(self, dek: bytes, user_id: UUID) -> WrappedKey:
        version = self.active_version
        nonce = os.urandom(NONCE_BYTES)
        blob = nonce + self._kek(version).encrypt(nonce, dek, _wrap_aad(user_id, version))
        return WrappedKey(kek_version=version, blob=blob)

    def unwrap(self, wrapped: WrappedKey, user_id: UUID) -> bytes:
        nonce, sealed = wrapped.blob[:NONCE_BYTES], wrapped.blob[NONCE_BYTES:]
        try:
            return self._kek(wrapped.kek_version).decrypt(nonce, sealed, _wrap_aad(user_id, wrapped.kek_version))
        except InvalidTag as error:
            raise InvalidCiphertextError("data key cannot be unwrapped") from error

    def rewrap(self, wrapped: WrappedKey, user_id: UUID) -> WrappedKey:
        if wrapped.kek_version == self.active_version:
            return wrapped
        return self.wrap(self.unwrap(wrapped, user_id), user_id)


def _wrap_aad(user_id: UUID, version: int) -> bytes:
    return b"dek|" + user_id.bytes + version.to_bytes(2, "big")


def new_data_key() -> bytes:
    return os.urandom(KEY_BYTES)


def _derive(dek: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=KEY_BYTES, salt=None, info=info).derive(dek)


class FieldCipher:
    def __init__(self, dek: bytes, user_id: UUID) -> None:
        if len(dek) != KEY_BYTES:
            raise CryptoError(f"data keys must be {KEY_BYTES} bytes")
        self._aead = AESGCM(_derive(dek, FIELD_KEY_INFO))
        self._index_key = _derive(dek, BLIND_INDEX_INFO)
        self._user_id = user_id

    def _aad(self, context: str) -> bytes:
        return FORMAT_VERSION.to_bytes(1, "big") + self._user_id.bytes + context.encode()

    def encrypt(self, plaintext: str, context: str) -> bytes:
        nonce = os.urandom(NONCE_BYTES)
        sealed = self._aead.encrypt(nonce, plaintext.encode(), self._aad(context))
        return FORMAT_VERSION.to_bytes(1, "big") + nonce + sealed

    def decrypt(self, blob: bytes, context: str) -> str:
        if not blob or blob[0] != FORMAT_VERSION:
            raise InvalidCiphertextError("unknown ciphertext format")
        nonce, sealed = blob[1 : 1 + NONCE_BYTES], blob[1 + NONCE_BYTES :]
        try:
            return self._aead.decrypt(nonce, sealed, self._aad(context)).decode()
        except InvalidTag as error:
            raise InvalidCiphertextError("ciphertext failed authentication") from error

    def blind_index(self, value: str, context: str) -> bytes:
        message = context.encode() + b"|" + value.encode()
        return hmac.new(self._index_key, message, hashlib.sha256).digest()[:BLIND_INDEX_BYTES]
