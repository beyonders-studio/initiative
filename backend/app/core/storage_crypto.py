"""Encrypting a stored object in place: the format, and nothing that stores it.

When ``STORAGE_ENCRYPTION`` is set, every object a community keeps (an upload,
a file's version, an export, a staged import) is written in this format by
:class:`app.services.storage.EncryptedStorage`. It is the evidence format
(``app.core.blob_crypto``) made self-describing, so the storage layer can read
it without any row beside it:

- **A key per object** (the DEK), wrapped by the community's storage key and
  written into the object's own header. Nothing outside the object records it.
- **Chunked AES-256-GCM.** Each chunk's associated data names its place in
  the object and whether it is the last, so a chunk moved, dropped, repeated
  or cut short fails to decrypt. Each chunk is sealed under a random nonce of
  its own, stored in front of it: nothing that is re-sent (a part of an
  upload retried after its first write landed) is ever sealed twice under
  one nonce. 96 random bits per chunk stay well inside AES-GCM's bound for
  any object a store holds (2^32 chunks: 256 TiB).
- **The plaintext length is in the header**, and bound to the DEK's wrap with
  the rest of the header, so a reader knows where every chunk starts without
  reading the object — a byte range of a large file reads only the chunks it
  covers — and a header altered in any way does not unwrap.
- **The wrap names the community**, so an object copied into another
  community's namespace does not open there. It does not name the object's
  key, so a copy within one community stays a server-side copy.

The header is a fixed size and starts with :data:`MAGIC`, which is how a
reader tells an encrypted object from one written before encryption was on.
"""

from __future__ import annotations

import os
import struct
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"IST1"

#: The plaintext each chunk carries, but the last.
CHUNK_SIZE = 64 * 1024

TAG_LEN = 16
NONCE_LEN = 12
#: What sealing adds to each chunk: its nonce in front, its tag behind.
CHUNK_OVERHEAD = NONCE_LEN + TAG_LEN
_WRAP_NONCE_LEN = 12
_DEK_LEN = 32
_WRAPPED_LEN = _DEK_LEN + TAG_LEN

#: magic | chunk size (u32) | plaintext length (u64) | key generation (u32) |
#: wrap nonce | wrapped DEK
_HEADER = struct.Struct(f">4sIQI{_WRAP_NONCE_LEN}s{_WRAPPED_LEN}s")
HEADER_SIZE = _HEADER.size
#: What the wrap authenticates besides the community: every header field
#: before the wrap itself.
_BOUND = struct.Struct(">4sIQI")


class StorageCryptoError(Exception):
    """The object is not what it should be: altered, cut short, or not this
    community's."""


@dataclass(frozen=True)
class Header:
    chunk_size: int
    length: int
    generation: int
    wrap_nonce: bytes
    wrapped: bytes

    def pack(self) -> bytes:
        return _HEADER.pack(
            MAGIC,
            self.chunk_size,
            self.length,
            self.generation,
            self.wrap_nonce,
            self.wrapped,
        )

    @property
    def chunk_count(self) -> int:
        """An empty object is one empty last chunk, so even it is
        authenticated."""
        return max(1, -(-self.length // self.chunk_size))

    @property
    def stored_size(self) -> int:
        return HEADER_SIZE + self.length + self.chunk_count * CHUNK_OVERHEAD

    def chunk_span(self, index: int) -> tuple[int, int]:
        """Where chunk ``index`` sits in the stored object: its first byte and
        one past its last."""
        start = HEADER_SIZE + index * (self.chunk_size + CHUNK_OVERHEAD)
        plain = min(self.chunk_size, self.length - index * self.chunk_size)
        return start, start + max(plain, 0) + CHUNK_OVERHEAD


def parse_header(data: bytes) -> Header | None:
    """The header ``data`` starts with, or ``None`` where it is not an
    encrypted object (one stored before encryption was on)."""
    if len(data) < HEADER_SIZE or data[:4] != MAGIC:
        return None
    magic, chunk_size, length, generation, nonce, wrapped = _HEADER.unpack(
        bytes(data[:HEADER_SIZE])
    )
    if chunk_size <= 0:
        raise StorageCryptoError("not an encrypted object")
    return Header(chunk_size, length, generation, nonce, wrapped)


def _wrap_aad(guild_id: int, header_fields: bytes) -> bytes:
    return struct.pack(">Q", int(guild_id)) + header_fields


def _bound(chunk_size: int, length: int, generation: int) -> bytes:
    return _BOUND.pack(MAGIC, chunk_size, length, generation)


def new_header(
    community_key: bytes,
    *,
    guild_id: int,
    length: int,
    generation: int,
    chunk_size: int = CHUNK_SIZE,
) -> tuple[Header, bytes]:
    """A header for a new object of ``length`` bytes, and the DEK it wraps."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    dek = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(_WRAP_NONCE_LEN)
    wrapped = AESGCM(community_key).encrypt(
        nonce,
        dek,
        _wrap_aad(guild_id, _bound(chunk_size, length, generation)),
    )
    return Header(chunk_size, length, generation, nonce, wrapped), dek


def unwrap(header: Header, community_key: bytes, *, guild_id: int) -> bytes:
    """The object's DEK, from its header."""
    try:
        return AESGCM(community_key).decrypt(
            header.wrap_nonce,
            header.wrapped,
            _wrap_aad(
                guild_id,
                _bound(header.chunk_size, header.length, header.generation),
            ),
        )
    except InvalidTag as exc:
        raise StorageCryptoError(
            "the object's key does not unwrap in this community"
        ) from exc


def _chunk_aad(header: Header, guild_id: int, index: int) -> bytes:
    last = index == header.chunk_count - 1
    return struct.pack(">QIB", int(guild_id), index, 1 if last else 0)


def seal_chunk(
    header: Header, dek: bytes, *, guild_id: int, index: int, plaintext: bytes
) -> bytes:
    """Chunk ``index`` of the object, sealed under a fresh nonce, which leads
    it."""
    nonce = os.urandom(NONCE_LEN)
    return nonce + AESGCM(dek).encrypt(
        nonce, plaintext, _chunk_aad(header, guild_id, index)
    )


def open_chunk(
    header: Header, dek: bytes, *, guild_id: int, index: int, sealed: bytes
) -> bytes:
    """Chunk ``index`` of the object, opened."""
    try:
        return AESGCM(dek).decrypt(
            sealed[:NONCE_LEN], sealed[NONCE_LEN:], _chunk_aad(header, guild_id, index)
        )
    except InvalidTag as exc:
        raise StorageCryptoError(f"chunk {index} does not decrypt") from exc


class Sealer:
    """Encrypts an object a piece at a time, in order.

    Pieces may be any size. Whole chunks are sealed as they fill; the last is
    sealed when the bytes the header promised have all arrived, and anything
    past them is refused.
    """

    def __init__(
        self, header: Header, dek: bytes, *, guild_id: int, index: int = 0
    ) -> None:
        self.header, self._dek, self._guild_id = header, dek, guild_id
        self.index = index
        self._buffer = bytearray()
        #: Resuming at chunk ``index`` means every chunk before it was whole.
        self.consumed = min(index * header.chunk_size, header.length)

    def feed(self, data: bytes) -> bytes:
        size = self.header.chunk_size
        if self.consumed + len(data) > self.header.length:
            raise StorageCryptoError("more bytes than the object's length")
        if self.done:
            return b""
        self.consumed += len(data)
        self._buffer += data
        out = bytearray()
        while len(self._buffer) >= size and self.index < self.header.chunk_count - 1:
            out += self._seal(bytes(self._buffer[:size]))
            del self._buffer[:size]
        if (
            self.consumed == self.header.length
            and self.index == self.header.chunk_count - 1
        ):
            out += self._seal(bytes(self._buffer))
            self._buffer.clear()
        return bytes(out)

    @property
    def pending(self) -> int:
        """Bytes fed but not yet sealed: a partial chunk waiting for more."""
        return len(self._buffer)

    @property
    def done(self) -> bool:
        return self.index == self.header.chunk_count

    def _seal(self, plaintext: bytes) -> bytes:
        sealed = seal_chunk(
            self.header,
            self._dek,
            guild_id=self._guild_id,
            index=self.index,
            plaintext=plaintext,
        )
        self.index += 1
        return sealed


def encrypt(
    plaintext: bytes,
    community_key: bytes,
    *,
    guild_id: int,
    generation: int,
    chunk_size: int = CHUNK_SIZE,
) -> bytes:
    """The stored form of ``plaintext``."""
    header, dek = new_header(
        community_key,
        guild_id=guild_id,
        length=len(plaintext),
        generation=generation,
        chunk_size=chunk_size,
    )
    sealer = Sealer(header, dek, guild_id=guild_id)
    return header.pack() + sealer.feed(plaintext)


def decrypt_range(
    stored: Iterable[bytes],
    header: Header,
    dek: bytes,
    *,
    guild_id: int,
    first: int,
    last: int,
    start: int,
    end: int,
) -> Iterator[bytes]:
    """Plaintext bytes ``start``..``end`` (inclusive), from ``stored``: the
    sealed chunks ``first``..``last`` exactly, in pieces of any size.

    Raises :class:`StorageCryptoError` the moment a chunk fails or the stored
    bytes stop short of the chunks asked for.
    """
    pieces = iter(stored)
    buffer = bytearray()
    size = header.chunk_size
    for index in range(first, last + 1):
        span_start, span_end = header.chunk_span(index)
        want = span_end - span_start
        while len(buffer) < want:
            piece = next(pieces, None)
            if piece is None:
                raise StorageCryptoError("the object ends before its last chunk")
            buffer += piece
        plain = open_chunk(
            header, dek, guild_id=guild_id, index=index, sealed=bytes(buffer[:want])
        )
        del buffer[:want]
        offset = index * size
        lo = max(start - offset, 0)
        hi = min(end - offset + 1, len(plain))
        if lo < hi:
            yield plain[lo:hi]
    if buffer or next(pieces, None):
        raise StorageCryptoError("bytes follow the chunks asked for")


def plaintext_range(header: Header, byte_range: str | None) -> tuple[int, int] | None:
    """The plaintext bytes a ``Range`` header asks of this object, inclusive,
    or ``None`` to serve it whole (no range, an empty object, or a range that
    starts past the end — served whole, as the object store would)."""
    if byte_range is None or header.length == 0:
        return None
    first, _, last = byte_range.removeprefix("bytes=").partition("-")
    if not first:
        count = int(last)
        if count == 0:
            return None
        return max(header.length - count, 0), header.length - 1
    start = int(first)
    if start >= header.length:
        return None
    end = min(int(last), header.length - 1) if last else header.length - 1
    return start, end
