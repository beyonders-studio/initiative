"""The stored-object format: pure functions, no store and no database."""

import os
import random

import pytest

from app.core import storage_crypto
from app.core.storage_crypto import (
    HEADER_SIZE,
    MAGIC,
    Sealer,
    StorageCryptoError,
    decrypt_range,
    encrypt,
    new_header,
    parse_header,
    plaintext_range,
    unwrap,
)

KEY = os.urandom(32)
GUILD = 7
CHUNK = 16


def _read(stored: bytes, *, guild_id: int = GUILD, key: bytes = KEY, rng=None):
    header = parse_header(stored)
    assert header is not None
    dek = unwrap(header, key, guild_id=guild_id)
    start, end = rng if rng else (0, header.length - 1)
    first, last = (
        (start // header.chunk_size, end // header.chunk_size)
        if header.length
        else (0, 0)
    )
    lo, hi = header.chunk_span(first)[0], header.chunk_span(last)[1]
    return b"".join(
        decrypt_range(
            [stored[lo:hi]],
            header,
            dek,
            guild_id=guild_id,
            first=first,
            last=last,
            start=start,
            end=end,
        )
    )


@pytest.mark.parametrize("size", [0, 1, CHUNK - 1, CHUNK, CHUNK + 1, 3 * CHUNK + 5])
def test_an_object_reads_back_whole(size):
    plaintext = os.urandom(size)
    stored = encrypt(plaintext, KEY, guild_id=GUILD, generation=1, chunk_size=CHUNK)
    assert stored.startswith(MAGIC)
    assert len(stored) == parse_header(stored).stored_size
    assert _read(stored) == plaintext


def test_any_range_reads_only_its_bytes():
    plaintext = os.urandom(10 * CHUNK + 3)
    stored = encrypt(plaintext, KEY, guild_id=GUILD, generation=1, chunk_size=CHUNK)
    picker = random.Random(5)
    for _ in range(200):
        start = picker.randrange(len(plaintext))
        end = picker.randrange(start, len(plaintext))
        assert _read(stored, rng=(start, end)) == plaintext[start : end + 1]


def test_pieces_of_any_size_seal_the_same_object():
    plaintext = os.urandom(5 * CHUNK + 7)
    header, dek = new_header(
        KEY, guild_id=GUILD, length=len(plaintext), generation=1, chunk_size=CHUNK
    )
    sealer = Sealer(header, dek, guild_id=GUILD)
    out = bytearray(header.pack())
    for at in range(0, len(plaintext), 5):
        out += sealer.feed(plaintext[at : at + 5])
    assert sealer.done
    assert sealer.feed(b"") == b""
    assert _read(bytes(out)) == plaintext


def test_more_bytes_than_promised_are_refused():
    header, dek = new_header(
        KEY, guild_id=GUILD, length=4, generation=1, chunk_size=CHUNK
    )
    with pytest.raises(StorageCryptoError):
        Sealer(header, dek, guild_id=GUILD).feed(b"12345")


def test_an_altered_chunk_does_not_decrypt():
    stored = bytearray(
        encrypt(
            os.urandom(3 * CHUNK), KEY, guild_id=GUILD, generation=1, chunk_size=CHUNK
        )
    )
    stored[HEADER_SIZE + CHUNK + 20] ^= 1
    with pytest.raises(StorageCryptoError):
        _read(bytes(stored))


def test_an_altered_header_does_not_unwrap():
    stored = bytearray(
        encrypt(b"x" * 40, KEY, guild_id=GUILD, generation=1, chunk_size=CHUNK)
    )
    # The length field: a reader told the object is shorter learns nothing.
    stored[8 + 7] ^= 1
    with pytest.raises(StorageCryptoError):
        _read(bytes(stored))


def test_another_community_cannot_open_it():
    stored = encrypt(b"secret", KEY, guild_id=GUILD, generation=1, chunk_size=CHUNK)
    with pytest.raises(StorageCryptoError):
        _read(stored, guild_id=GUILD + 1)


def test_a_cut_short_object_is_noticed():
    stored = encrypt(
        os.urandom(3 * CHUNK), KEY, guild_id=GUILD, generation=1, chunk_size=CHUNK
    )
    header = parse_header(stored)
    dek = unwrap(header, KEY, guild_id=GUILD)
    with pytest.raises(StorageCryptoError):
        b"".join(
            decrypt_range(
                [stored[HEADER_SIZE:-5]],
                header,
                dek,
                guild_id=GUILD,
                first=0,
                last=header.chunk_count - 1,
                start=0,
                end=header.length - 1,
            )
        )


def test_an_object_stored_in_the_clear_has_no_header():
    assert parse_header(b"%PDF-1.7 and the rest of a document" * 4) is None
    assert parse_header(b"") is None


@pytest.mark.parametrize(
    ("header", "wanted"),
    [
        (None, None),
        ("bytes=0-9", (0, 9)),
        ("bytes=90-", (90, 99)),
        ("bytes=-10", (90, 99)),
        ("bytes=50-500", (50, 99)),
        # Past the end, or nothing asked: served whole, as the store would.
        ("bytes=100-", None),
        ("bytes=-0", None),
    ],
)
def test_ranges_are_read_as_the_store_reads_them(header, wanted):
    parsed = parse_header(encrypt(b"y" * 100, KEY, guild_id=GUILD, generation=1))
    assert plaintext_range(parsed, header) == wanted


def test_an_empty_object_has_no_range():
    parsed = parse_header(encrypt(b"", KEY, guild_id=GUILD, generation=1))
    assert storage_crypto.plaintext_range(parsed, "bytes=0-5") is None
