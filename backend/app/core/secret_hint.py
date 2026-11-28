"""What a settings page shows of a saved secret, which it never sends back.

A private key shows its fingerprint, in the form the vendor that issued it
lists its keys (GitHub: the SHA-256 of the public half, in base64), so the
key saved here can be matched against the vendor's list. Any other secret
shows its last few characters behind a mask, as a vendor lists a client
secret it issued; one too short to spare any shows nothing.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.fernet import InvalidToken
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_private_key,
)

from app.core.encryption import decrypt_field

#: The fewest characters a secret has before its end is shown.
SHOWN_FROM = 16
#: How many of its last characters are shown.
SHOWN = 4
MASK = "••••••••"


def secret_hint(secret: str | None) -> str | None:
    """The fingerprint of a PEM private key, as ``SHA256:<base64>``, or the
    mask and the last characters of any other secret. ``None`` for no
    secret, one too short to show any of, or a key that does not load."""
    text = (secret or "").strip()
    if text.startswith("-----BEGIN"):
        try:
            key = load_pem_private_key(text.encode(), password=None)
        except ValueError, TypeError, UnsupportedAlgorithm:
            return None
        public = key.public_key().public_bytes(
            Encoding.DER, PublicFormat.SubjectPublicKeyInfo
        )
        return "SHA256:" + base64.b64encode(hashlib.sha256(public).digest()).decode()
    if len(text) < SHOWN_FROM:
        return None
    return MASK + text[-SHOWN:]


def sealed_hint(ciphertext: str | None, salt: bytes) -> str | None:
    """:func:`secret_hint` of a secret stored encrypted under ``salt``; ``None``
    when there is none or it no longer decrypts."""
    if not ciphertext:
        return None
    try:
        return secret_hint(decrypt_field(ciphertext, salt))
    except InvalidToken, UnicodeDecodeError:
        return None
