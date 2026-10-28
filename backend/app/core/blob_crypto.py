"""Encrypting a stored object: a key of its own, held wrapped by its community.

Evidence — what a person attaches to a ticket or a report — is stored under a
key made for that one object (the DEK). The object's row keeps the DEK wrapped
by a key derived for the community holding it (the KEK); the object itself is
never encrypted under anything shared.

- **The object** is chunked AES-256-GCM. Each chunk's nonce and associated data
  name the object and the chunk's place in it, and the last chunk says it is
  last, so a chunk moved, dropped, repeated or cut short fails to decrypt, and
  bytes from one object never decrypt as another's. Memory stays flat however
  large the object: a chunk at a time, each way.
- **The wrap** binds the DEK to the community holding it and to the object, so a
  wrapped key copied into another community's row does not unwrap there.
- **Rotation** re-wraps the key, never the object: :func:`rewrap` is a few
  bytes per row.
- **Crossing communities** copies the object's bytes as they are and re-wraps
  only the key (``app.services.platform.evidence``): the object keeps the
  identity it was created with.

The KEK comes in two versions, recorded on each row. Version 1 is derived
from ``SECRET_KEY``, so it protects stored bytes from anybody holding the
store but not the application's configuration. Version 2, used whenever
``STORAGE_ENCRYPTION`` is set, is derived from the community's storage key
(``app.services.storage_keys``): that key is wrapped by the deployment's root
(a Cloud KMS key on the cloud) and destroyed with the community, which takes
its evidence with it.
"""

from __future__ import annotations

import os
import struct
import uuid
from typing import Iterable, Iterator

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings

#: The KEK's salt. Never change it: every wrapped key depends on it.
EVIDENCE_KEK_SALT = b"evidence-kek"

#: Which derivation a row's KEK came from, written beside its wrapped key:
#: from SECRET_KEY.
KEK_VERSION = 1
#: From the community's storage key, where storage is encrypted.
COMMUNITY_KEK_VERSION = 2

#: The plaintext each chunk carries, but the last.
CHUNK_SIZE = 64 * 1024

_MAGIC = b"IEV1"
_PREFIX_LEN = 7
_TAG_LEN = 16
#: magic | chunk size (u32) | nonce prefix
_HEADER = struct.Struct(f">4sI{_PREFIX_LEN}s")
_WRAP_NONCE_LEN = 12


class BlobCryptoError(Exception):
    """The object or key is not what it should be: altered, truncated, or not
    this object's or this community's."""


def new_dek() -> bytes:
    """A fresh key for one object."""
    return AESGCM.generate_key(bit_length=256)


def current_kek_version() -> int:
    """The version a new wrap is made under: the community's storage key where
    storage is encrypted, ``SECRET_KEY`` where it is not."""
    from app.services.storage_keys import active_keyring

    keyring = active_keyring()
    return (
        COMMUNITY_KEK_VERSION
        if keyring is not None and keyring.encrypts
        else KEK_VERSION
    )


def _community_kek(guild_id: int) -> bytes:
    from app.services.storage_keys import active_keyring

    keyring = active_keyring()
    found = keyring.key_for(guild_id, create=True) if keyring is not None else None
    if found is None:
        raise BlobCryptoError("the community's storage key is gone")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=EVIDENCE_KEK_SALT,
        info=f"evidence-kek:v{COMMUNITY_KEK_VERSION}:guild:{int(guild_id)}".encode(),
    ).derive(found[0])


def kek(
    guild_id: int, *, version: int = KEK_VERSION, secret_key: str | None = None
) -> bytes:
    """The key that wraps objects' keys in ``guild_id``."""
    if version == COMMUNITY_KEK_VERSION:
        return _community_kek(guild_id)
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=EVIDENCE_KEK_SALT,
        info=f"evidence-kek:v{version}:guild:{int(guild_id)}".encode(),
    ).derive((secret_key if secret_key is not None else settings.SECRET_KEY).encode())


def _wrap_aad(holding_guild_id: int, origin_id: uuid.UUID) -> bytes:
    return struct.pack(">Q", int(holding_guild_id)) + origin_id.bytes


def wrap(
    dek: bytes,
    *,
    holding_guild_id: int,
    origin_id: uuid.UUID,
    secret_key: str | None = None,
    version: int = KEK_VERSION,
) -> bytes:
    """``dek``, wrapped for the community holding the object."""
    nonce = os.urandom(_WRAP_NONCE_LEN)
    sealed = AESGCM(
        kek(holding_guild_id, version=version, secret_key=secret_key)
    ).encrypt(nonce, dek, _wrap_aad(holding_guild_id, origin_id))
    return nonce + sealed


def unwrap(
    wrapped: bytes,
    *,
    holding_guild_id: int,
    origin_id: uuid.UUID,
    secret_key: str | None = None,
    version: int = KEK_VERSION,
) -> bytes:
    """The object's key, from the wrapped form its community's row holds."""
    nonce, sealed = bytes(wrapped[:_WRAP_NONCE_LEN]), bytes(wrapped[_WRAP_NONCE_LEN:])
    try:
        return AESGCM(
            kek(holding_guild_id, version=version, secret_key=secret_key)
        ).decrypt(nonce, sealed, _wrap_aad(holding_guild_id, origin_id))
    except InvalidTag as exc:
        raise BlobCryptoError("the key does not unwrap here") from exc


def rewrap(
    wrapped: bytes,
    *,
    holding_guild_id: int,
    origin_id: uuid.UUID,
    old_secret_key: str,
    new_secret_key: str,
) -> bytes:
    """The same key, wrapped under the community's key for ``new_secret_key``."""
    dek = unwrap(
        wrapped,
        holding_guild_id=holding_guild_id,
        origin_id=origin_id,
        secret_key=old_secret_key,
    )
    return wrap(
        dek,
        holding_guild_id=holding_guild_id,
        origin_id=origin_id,
        secret_key=new_secret_key,
    )


def _chunk_params(
    prefix: bytes, origin_guild_id: int, origin_id: uuid.UUID, index: int, last: bool
) -> tuple[bytes, bytes]:
    tail = struct.pack(">IB", index, 1 if last else 0)
    nonce = prefix + tail
    aad = struct.pack(">Q", int(origin_guild_id)) + origin_id.bytes + tail
    return nonce, aad


def encrypt(
    plaintext: bytes,
    dek: bytes,
    *,
    origin_guild_id: int,
    origin_id: uuid.UUID,
    chunk_size: int = CHUNK_SIZE,
) -> bytes:
    """The stored form of ``plaintext``: a header, then its sealed chunks.

    An empty object is one empty last chunk, so even it is authenticated.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    prefix = os.urandom(_PREFIX_LEN)
    aead = AESGCM(dek)
    out = bytearray(_HEADER.pack(_MAGIC, chunk_size, prefix))
    total = len(plaintext)
    count = max(1, -(-total // chunk_size))
    for index in range(count):
        last = index == count - 1
        nonce, aad = _chunk_params(prefix, origin_guild_id, origin_id, index, last)
        chunk = plaintext[index * chunk_size : (index + 1) * chunk_size]
        out += aead.encrypt(nonce, chunk, aad)
    return bytes(out)


def ciphertext_size(plaintext_size: int, chunk_size: int = CHUNK_SIZE) -> int:
    """How many bytes :func:`encrypt` writes for ``plaintext_size`` bytes."""
    count = max(1, -(-plaintext_size // chunk_size))
    return _HEADER.size + plaintext_size + count * _TAG_LEN


def decrypt_stream(
    stored: Iterable[bytes],
    dek: bytes,
    *,
    origin_guild_id: int,
    origin_id: uuid.UUID,
) -> Iterator[bytes]:
    """The plaintext of a stored object, a chunk at a time.

    ``stored`` may arrive in pieces of any size. Raises
    :class:`BlobCryptoError` the moment a chunk fails, or at the end where the
    object stops before its last chunk — so a reader that has been sent part
    of an object learns it was not the whole of it.
    """
    aead = AESGCM(dek)
    buffer = bytearray()
    pieces = iter(stored)
    header: tuple[bytes, int, bytes] | None = None
    index = 0
    finished = False
    exhausted = False

    while True:
        if header is None:
            while len(buffer) < _HEADER.size and not exhausted:
                piece = next(pieces, None)
                if piece is None:
                    exhausted = True
                else:
                    buffer += piece
            if len(buffer) < _HEADER.size:
                raise BlobCryptoError("not an encrypted object")
            magic, chunk_size, prefix = _HEADER.unpack(bytes(buffer[: _HEADER.size]))
            if magic != _MAGIC or chunk_size <= 0:
                raise BlobCryptoError("not an encrypted object")
            header = (magic, chunk_size, prefix)
            del buffer[: _HEADER.size]

        _, chunk_size, prefix = header
        sealed_size = chunk_size + _TAG_LEN
        # Read until a whole chunk is buffered, or the object has ended.
        while len(buffer) <= sealed_size and not exhausted:
            piece = next(pieces, None)
            if piece is None:
                exhausted = True
            else:
                buffer += piece

        if finished:
            if buffer:
                raise BlobCryptoError("bytes follow the last chunk")
            return

        if exhausted and len(buffer) <= sealed_size:
            # What is left is the last chunk, or the object was cut short.
            if len(buffer) < _TAG_LEN:
                raise BlobCryptoError("the object ends before its last chunk")
            sealed, last = bytes(buffer), True
            buffer.clear()
        else:
            sealed, last = bytes(buffer[:sealed_size]), False
            del buffer[:sealed_size]

        nonce, aad = _chunk_params(prefix, origin_guild_id, origin_id, index, last)
        try:
            yield aead.decrypt(nonce, sealed, aad)
        except InvalidTag as exc:
            raise BlobCryptoError(
                "a chunk does not decrypt"
                if not last
                else "the object ends before its last chunk, or was altered"
            ) from exc
        index += 1
        if last:
            finished = True


def decrypt(
    stored: bytes, dek: bytes, *, origin_guild_id: int, origin_id: uuid.UUID
) -> bytes:
    """The whole plaintext of a stored object."""
    return b"".join(
        decrypt_stream(
            [stored], dek, origin_guild_id=origin_guild_id, origin_id=origin_id
        )
    )
