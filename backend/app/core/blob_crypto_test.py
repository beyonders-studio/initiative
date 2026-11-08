"""An encrypted object opens only as itself, whole, in the community holding it."""

from __future__ import annotations

import os
import uuid

import pytest

from app.core import blob_crypto
from app.core.blob_crypto import BlobCryptoError

pytestmark = pytest.mark.always

ORIGIN = uuid.uuid4()


def _sealed(plaintext: bytes, *, chunk_size: int = 16) -> tuple[bytes, bytes]:
    dek = blob_crypto.new_dek()
    return dek, blob_crypto.encrypt(
        plaintext, dek, origin_guild_id=4, origin_id=ORIGIN, chunk_size=chunk_size
    )


@pytest.mark.parametrize("size", [0, 1, 15, 16, 17, 48, 1000])
def test_an_object_comes_back_as_it_went_in(size: int):
    plaintext = os.urandom(size)
    dek, stored = _sealed(plaintext)
    assert (
        blob_crypto.decrypt(stored, dek, origin_guild_id=4, origin_id=ORIGIN)
        == plaintext
    )


def test_it_reads_in_pieces_of_any_size():
    plaintext = os.urandom(200)
    dek, stored = _sealed(plaintext)
    pieces = [stored[i : i + 7] for i in range(0, len(stored), 7)]
    assert (
        b"".join(
            blob_crypto.decrypt_stream(pieces, dek, origin_guild_id=4, origin_id=ORIGIN)
        )
        == plaintext
    )


@pytest.mark.parametrize("cut", [1, 16 + 16, 2 * (16 + 16)])
def test_a_truncated_object_fails(cut: int):
    dek, stored = _sealed(os.urandom(64))
    with pytest.raises(BlobCryptoError):
        blob_crypto.decrypt(stored[:-cut], dek, origin_guild_id=4, origin_id=ORIGIN)


def test_reordered_chunks_fail():
    dek, stored = _sealed(os.urandom(64))
    header, body = stored[:15], stored[15:]
    chunks = [body[i : i + 32] for i in range(0, len(body), 32)]
    chunks[0], chunks[1] = chunks[1], chunks[0]
    with pytest.raises(BlobCryptoError):
        blob_crypto.decrypt(
            header + b"".join(chunks), dek, origin_guild_id=4, origin_id=ORIGIN
        )


def test_an_altered_byte_fails():
    dek, stored = _sealed(os.urandom(40))
    altered = bytearray(stored)
    altered[20] ^= 1
    with pytest.raises(BlobCryptoError):
        blob_crypto.decrypt(bytes(altered), dek, origin_guild_id=4, origin_id=ORIGIN)


def test_an_object_opens_only_as_the_object_it_was_made_as():
    dek, stored = _sealed(b"evidence")
    with pytest.raises(BlobCryptoError):
        blob_crypto.decrypt(stored, dek, origin_guild_id=4, origin_id=uuid.uuid4())
    with pytest.raises(BlobCryptoError):
        blob_crypto.decrypt(stored, dek, origin_guild_id=5, origin_id=ORIGIN)


def test_a_wrapped_key_does_not_unwrap_in_another_community():
    dek = blob_crypto.new_dek()
    wrapped = blob_crypto.wrap(dek, holding_guild_id=4, origin_id=ORIGIN)
    assert blob_crypto.unwrap(wrapped, holding_guild_id=4, origin_id=ORIGIN) == dek
    with pytest.raises(BlobCryptoError):
        blob_crypto.unwrap(wrapped, holding_guild_id=9, origin_id=ORIGIN)
    with pytest.raises(BlobCryptoError):
        blob_crypto.unwrap(wrapped, holding_guild_id=4, origin_id=uuid.uuid4())


def test_rewrapping_moves_the_key_to_the_new_secret_and_leaves_the_object():
    dek, stored = _sealed(b"evidence")
    old, new = "old-secret-key-" + "x" * 20, "new-secret-key-" + "y" * 20
    wrapped = blob_crypto.wrap(
        dek, holding_guild_id=4, origin_id=ORIGIN, secret_key=old
    )
    rewrapped = blob_crypto.rewrap(
        wrapped,
        holding_guild_id=4,
        origin_id=ORIGIN,
        old_secret_key=old,
        new_secret_key=new,
    )
    with pytest.raises(BlobCryptoError):
        blob_crypto.unwrap(
            rewrapped, holding_guild_id=4, origin_id=ORIGIN, secret_key=old
        )
    key = blob_crypto.unwrap(
        rewrapped, holding_guild_id=4, origin_id=ORIGIN, secret_key=new
    )
    assert blob_crypto.decrypt(stored, key, origin_guild_id=4, origin_id=ORIGIN) == (
        b"evidence"
    )


def test_something_else_is_not_an_object():
    with pytest.raises(BlobCryptoError):
        blob_crypto.decrypt(
            b"not encrypted at all",
            blob_crypto.new_dek(),
            origin_guild_id=4,
            origin_id=ORIGIN,
        )
