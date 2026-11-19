import base64
from uuid import uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vapas.security.crypto import (
    CryptoError,
    FieldCipher,
    InvalidCiphertextError,
    KeyRing,
    UnknownKeyVersionError,
    WrappedKey,
    decode_key,
    new_data_key,
)

KEK_V1 = bytes(range(32))
KEK_V2 = bytes(range(32, 64))


def ring(active: int = 1) -> KeyRing:
    return KeyRing({1: KEK_V1, 2: KEK_V2}, active)


def test_data_key_round_trip_through_wrapping() -> None:
    user = uuid4()
    dek = new_data_key()
    wrapped = ring().wrap(dek, user)
    assert wrapped.kek_version == 1
    assert dek not in wrapped.blob
    assert ring().unwrap(wrapped, user) == dek


def test_wrapped_key_is_bound_to_its_user() -> None:
    wrapped = ring().wrap(new_data_key(), uuid4())
    with pytest.raises(InvalidCiphertextError):
        ring().unwrap(wrapped, uuid4())


def test_wrapped_key_cannot_claim_another_kek_version() -> None:
    user = uuid4()
    wrapped = ring().wrap(new_data_key(), user)
    with pytest.raises(InvalidCiphertextError):
        ring().unwrap(WrappedKey(kek_version=2, blob=wrapped.blob), user)


def test_rotation_rewraps_under_the_active_kek_and_keeps_the_data_key() -> None:
    user = uuid4()
    dek = new_data_key()
    old = ring(active=1).wrap(dek, user)
    rotated = ring(active=2).rewrap(old, user)
    assert rotated.kek_version == 2
    assert ring(active=2).unwrap(rotated, user) == dek
    assert ring(active=2).rewrap(rotated, user) is rotated


def test_retired_kek_cannot_unwrap() -> None:
    user = uuid4()
    wrapped = ring(active=1).wrap(new_data_key(), user)
    with pytest.raises(UnknownKeyVersionError):
        KeyRing({2: KEK_V2}, 2).unwrap(wrapped, user)


def test_active_version_must_exist() -> None:
    with pytest.raises(UnknownKeyVersionError):
        KeyRing({1: KEK_V1}, 3)


def test_short_keys_are_rejected() -> None:
    with pytest.raises(CryptoError):
        KeyRing({1: b"short"}, 1)
    with pytest.raises(CryptoError):
        decode_key(base64.b64encode(b"short").decode())


@settings(max_examples=50)
@given(plaintext=st.text(max_size=500), context=st.text(min_size=1, max_size=40))
def test_field_round_trip(plaintext: str, context: str) -> None:
    cipher = FieldCipher(new_data_key(), uuid4())
    assert cipher.decrypt(cipher.encrypt(plaintext, context), context) == plaintext


def test_same_plaintext_encrypts_differently_each_time() -> None:
    cipher = FieldCipher(new_data_key(), uuid4())
    assert cipher.encrypt("UPI/123/Ravi", "transactions.narration") != cipher.encrypt(
        "UPI/123/Ravi", "transactions.narration"
    )


def test_ciphertext_cannot_move_between_fields() -> None:
    cipher = FieldCipher(new_data_key(), uuid4())
    blob = cipher.encrypt("secret", "transactions.narration")
    with pytest.raises(InvalidCiphertextError):
        cipher.decrypt(blob, "transactions.ref_no")


def test_ciphertext_cannot_move_between_users() -> None:
    dek = new_data_key()
    blob = FieldCipher(dek, uuid4()).encrypt("secret", "ctx")
    with pytest.raises(InvalidCiphertextError):
        FieldCipher(dek, uuid4()).decrypt(blob, "ctx")


def test_tampering_is_detected() -> None:
    cipher = FieldCipher(new_data_key(), uuid4())
    blob = bytearray(cipher.encrypt("secret", "ctx"))
    blob[-1] ^= 1
    with pytest.raises(InvalidCiphertextError):
        cipher.decrypt(bytes(blob), "ctx")


def test_unknown_format_is_rejected() -> None:
    cipher = FieldCipher(new_data_key(), uuid4())
    with pytest.raises(InvalidCiphertextError):
        cipher.decrypt(b"\x09" + b"0" * 40, "ctx")


def test_blind_index_is_stable_per_user_and_context() -> None:
    dek = new_data_key()
    user = uuid4()
    a, b = FieldCipher(dek, user), FieldCipher(dek, user)
    assert a.blind_index("412345678901", "ref") == b.blind_index("412345678901", "ref")
    assert len(a.blind_index("412345678901", "ref")) == 16
    assert a.blind_index("412345678901", "ref") != a.blind_index("412345678901", "other")
    assert a.blind_index("412345678901", "ref") != FieldCipher(new_data_key(), user).blind_index("412345678901", "ref")


def test_crypto_shredding_makes_data_unreadable() -> None:
    user = uuid4()
    blob = FieldCipher(new_data_key(), user).encrypt("narration", "ctx")
    with pytest.raises(InvalidCiphertextError):
        FieldCipher(new_data_key(), user).decrypt(blob, "ctx")
