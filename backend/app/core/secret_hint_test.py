"""A saved secret is shown by its fingerprint or its last characters, never
whole."""

from __future__ import annotations

import base64
import hashlib

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from app.core.encryption import encrypt_field
from app.core.secret_hint import sealed_hint, secret_hint


def test_a_private_key_shows_its_fingerprint_as_github_lists_it():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()
    ).decode()
    # GitHub's: openssl rsa -pubout -outform DER | openssl sha256 -binary | openssl base64
    public = key.public_key().public_bytes(
        Encoding.DER, PublicFormat.SubjectPublicKeyInfo
    )
    expected = base64.b64encode(hashlib.sha256(public).digest()).decode()

    assert secret_hint(pem) == f"SHA256:{expected}"
    # Pasted with the blank lines a copy picks up, it is the same key.
    assert secret_hint(f"\n{pem}\n") == f"SHA256:{expected}"
    assert secret_hint("-----BEGIN RSA PRIVATE KEY-----\nnot a key\n") is None


def test_another_secret_shows_only_its_end_and_a_short_one_nothing():
    assert secret_hint("0123456789abcdef5d25") == "••••••••5d25"
    assert secret_hint("short-secret") is None
    assert secret_hint("") is None
    assert secret_hint(None) is None


def test_a_sealed_secret_is_read_under_its_salt():
    sealed = encrypt_field("0123456789abcdef5d25", b"hint-test")
    assert sealed_hint(sealed, b"hint-test") == "••••••••5d25"
    # Under another salt it does not decrypt, and shows nothing.
    assert sealed_hint(sealed, b"other-salt") is None
    assert sealed_hint(None, b"hint-test") is None
