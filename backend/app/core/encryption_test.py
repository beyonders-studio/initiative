"""Unit tests for the encryption module."""

import pytest
from cryptography.fernet import InvalidToken

from app.core.config import settings
from app.core.encryption import (
    SALT_AI_API_KEY,
    SALT_EMAIL,
    decrypt_field,
    encrypt_field,
    hash_email,
)

# Two distinct test-only keys (each ≥32 chars). Not secrets.
_KEY_A = "a" * 48
_KEY_B = "b" * 48


def test_hash_email_is_a_normalised_keyed_digest() -> None:
    h = hash_email("alice@example.com")
    assert len(h) == 64  # SHA-256 hex digest
    assert hash_email("  ALICE@Example.COM  ") == h
    assert hash_email("bob@example.com") != h
    # A rotation must recompute it: the digest differs per key, and the
    # default key is the live one.
    h_a = hash_email("alice@example.com", secret_key=_KEY_A)
    assert h_a != hash_email("alice@example.com", secret_key=_KEY_B)
    assert hash_email("alice@example.com", secret_key=settings.SECRET_KEY) == h


def test_a_field_round_trips_under_its_own_salt_only() -> None:
    ct_email = encrypt_field("secret", SALT_EMAIL)
    ct_ai = encrypt_field("secret", SALT_AI_API_KEY)
    assert ct_email != "secret"
    assert ct_email != encrypt_field("secret", SALT_EMAIL)  # randomised
    assert ct_email != ct_ai
    assert decrypt_field(ct_email, SALT_EMAIL) == "secret"
    assert decrypt_field(ct_ai, SALT_AI_API_KEY) == "secret"


def test_an_explicit_key_rotates_a_field() -> None:
    """Decrypt under the old key, re-encrypt under the new one; the old key's
    ciphertext does not open under the new key, which is how the rotation sweep
    tells rotated rows from un-rotated ones."""
    old_ct = encrypt_field("smtp-pw", SALT_EMAIL, secret_key=_KEY_A)
    with pytest.raises(InvalidToken):
        decrypt_field(old_ct, SALT_EMAIL, secret_key=_KEY_B)
    plain = decrypt_field(old_ct, SALT_EMAIL, secret_key=_KEY_A)
    new_ct = encrypt_field(plain, SALT_EMAIL, secret_key=_KEY_B)
    assert decrypt_field(new_ct, SALT_EMAIL, secret_key=_KEY_B) == "smtp-pw"
