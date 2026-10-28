"""Each community's storage key: made, wrapped, unwrapped, cached, destroyed.

With ``STORAGE_ENCRYPTION`` set, every object a community stores is encrypted
under a key of the community's own (``app.core.storage_crypto``). The key is 32
random bytes, made the first time the community stores something, and kept
only wrapped, on its ``guild_storage_keys`` row, by the deployment's root:

- ``local``: Fernet under ``SECRET_KEY``. Rotating ``SECRET_KEY`` re-wraps it
  with every other encrypted column.
- ``gcp_kms``: a Cloud KMS key the app calls as its own Google identity. The
  key never leaves KMS, every unwrap is in the project's audit log, and
  revoking the app's grant stops every unwrap at once.

A row is unwrapped by the root that wrapped it, whatever the setting says now,
so switching roots never strands what was written before.

**Why a thread of its own.** Storage is synchronous and called from anywhere:
from a worker thread, from a helper a request runs inline, from a CLI. The
key is in the database, which this app reaches only asynchronously. So the
keys are read and made on a small event loop on a thread of its own, with a
connection of its own, and any caller waits on it. An unwrapped key is kept
in memory for :data:`CACHE_SECONDS`, so a busy community costs one read (and,
on KMS, one unwrap) per process every few minutes, not one per file.

**Destroying a key** (:func:`destroy`) deletes the row, which makes every
object the community stored encrypted unreadable, wherever a copy of it is.
Another process may hold the key in memory for up to :data:`CACHE_SECONDS`.

Nothing here runs unless ``STORAGE_ENCRYPTION`` is set, or a deployment that
once set it has keys left to read (:func:`prime`).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import threading
import time
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.encryption import SALT_STORAGE_KEY, decrypt_field, encrypt_field

logger = logging.getLogger(__name__)

#: How long an unwrapped community key is kept in memory.
CACHE_SECONDS = 300
#: How long a caller waits on the key thread before giving up.
_WAIT_SECONDS = 30
_KMS_SCOPE = "https://www.googleapis.com/auth/cloudkms"

T = TypeVar("T")


class StorageKeyError(Exception):
    """A community's key cannot be had: destroyed, or its root refused."""


@dataclass(frozen=True)
class KeyRow:
    guild_id: int
    generation: int
    local_sealed: str | None
    kms_sealed: str | None
    kms_key: str | None


def _aad(guild_id: int) -> bytes:
    return f"initiative-storage-key:guild:{int(guild_id)}".encode()


# --- Roots -------------------------------------------------------------------


class Root(Protocol):
    def wrap(self, guild_id: int, key: bytes) -> dict[str, str]:
        """The row's columns that hold ``key`` wrapped."""
        ...


class LocalRoot:
    """Wraps under ``SECRET_KEY``. Fernet has no associated data, so the
    community's id is sealed in beside the key and checked on the way out: a
    wrapped key copied onto another community's row does not unwrap there."""

    def wrap(self, guild_id: int, key: bytes) -> dict[str, str]:
        sealed = encrypt_field(
            f"{int(guild_id)}:{base64.b64encode(key).decode()}", SALT_STORAGE_KEY
        )
        return {"local_sealed": sealed}

    def unwrap(self, row: KeyRow) -> bytes:
        plain = decrypt_field(row.local_sealed or "", SALT_STORAGE_KEY)
        owner, _, encoded = plain.partition(":")
        if owner != str(row.guild_id) or not encoded:
            raise StorageKeyError("the key is not this community's")
        return base64.b64decode(encoded)


class KmsRoot:
    """Wraps by calling Cloud KMS as the app's Google identity (Workload
    Identity in the cluster), over KMS's REST API with ``google-auth``."""

    def __init__(self, key_name: str) -> None:
        self.key_name = key_name
        self._session: Any = None

    def _authorized(self) -> Any:
        if self._session is None:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession

            credentials, _ = google.auth.default(scopes=[_KMS_SCOPE])
            self._session = AuthorizedSession(credentials)
        return self._session

    def _call(self, key_name: str, verb: str, body: dict[str, str]) -> dict[str, Any]:
        response = self._authorized().post(
            f"https://cloudkms.googleapis.com/v1/{key_name}:{verb}",
            json=body,
            timeout=10,
        )
        if response.status_code >= 400:
            raise StorageKeyError(
                f"Cloud KMS refused {verb} on {key_name}: {response.status_code}"
            )
        return response.json()

    def wrap(self, guild_id: int, key: bytes) -> dict[str, str]:
        answer = self._call(
            self.key_name,
            "encrypt",
            {
                "plaintext": base64.b64encode(key).decode(),
                "additionalAuthenticatedData": base64.b64encode(
                    _aad(guild_id)
                ).decode(),
            },
        )
        return {"kms_sealed": answer["ciphertext"], "kms_key": self.key_name}

    def unwrap(self, row: KeyRow) -> bytes:
        answer = self._call(
            row.kms_key or self.key_name,
            "decrypt",
            {
                "ciphertext": row.kms_sealed or "",
                "additionalAuthenticatedData": base64.b64encode(
                    _aad(row.guild_id)
                ).decode(),
            },
        )
        return base64.b64decode(answer["plaintext"])


def _unwrap(row: KeyRow) -> bytes:
    if row.kms_sealed is not None:
        return KmsRoot(row.kms_key or "").unwrap(row)
    return LocalRoot().unwrap(row)


# --- Where the rows are ------------------------------------------------------


class KeyStore(Protocol):
    def get(self, guild_id: int) -> KeyRow | None: ...

    def add(self, guild_id: int, columns: dict[str, str]) -> KeyRow:
        """Insert the row unless one is there, and return whichever is."""
        ...

    def reopen(self, guild_id: int) -> None:
        """Clear the row's ``backfilled_at``: something was stored in the
        clear since."""
        ...


class _LoopThread:
    """An event loop on a daemon thread of its own, to run coroutines on from
    any thread, including one that is itself running an event loop."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    def _start(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                threading.Thread(
                    target=loop.run_forever, name="storage-keys", daemon=True
                ).start()
                self._loop = loop
            return self._loop

    def run(self, coroutine: Coroutine[Any, Any, T]) -> T:
        loop = self._start()
        return asyncio.run_coroutine_threadsafe(coroutine, loop).result(_WAIT_SECONDS)


_COLUMNS = "guild_id, generation, local_sealed, kms_sealed, kms_key"


class DatabaseKeyStore:
    """``guild_storage_keys``, on a connection of the key thread's own, as the
    system login (``app_admin``), the only one granted the table."""

    def __init__(self) -> None:
        self._thread = _LoopThread()
        self._engine: Any = None

    def _connect(self) -> Any:
        if self._engine is None:
            from sqlalchemy.ext.asyncio import create_async_engine
            from sqlalchemy.pool import NullPool

            from app.db import session as db_session

            self._engine = create_async_engine(
                db_session.system_engine.url, poolclass=NullPool
            )
        return self._engine

    async def _get(self, guild_id: int) -> KeyRow | None:
        async with self._connect().connect() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            f"SELECT {_COLUMNS} FROM guild_storage_keys WHERE guild_id = :g"
                        ),
                        {"g": int(guild_id)},
                    )
                )
                .mappings()
                .first()
            )
        return KeyRow(**row) if row else None

    async def _add(self, guild_id: int, columns: dict[str, str]) -> KeyRow:
        async with self._connect().begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO guild_storage_keys "
                    "(guild_id, generation, local_sealed, kms_sealed, kms_key, created_at) "
                    "VALUES (:g, 1, :local_sealed, :kms_sealed, :kms_key, now()) "
                    "ON CONFLICT (guild_id) DO NOTHING"
                ),
                {
                    "g": int(guild_id),
                    "local_sealed": columns.get("local_sealed"),
                    "kms_sealed": columns.get("kms_sealed"),
                    "kms_key": columns.get("kms_key"),
                },
            )
        row = await self._get(guild_id)
        if row is None:
            raise StorageKeyError(f"no storage key for community {guild_id}")
        return row

    async def _reopen(self, guild_id: int) -> None:
        async with self._connect().begin() as conn:
            await conn.execute(
                text(
                    "UPDATE guild_storage_keys SET backfilled_at = NULL "
                    "WHERE guild_id = :g AND backfilled_at IS NOT NULL"
                ),
                {"g": int(guild_id)},
            )

    def get(self, guild_id: int) -> KeyRow | None:
        return self._thread.run(self._get(guild_id))

    def add(self, guild_id: int, columns: dict[str, str]) -> KeyRow:
        return self._thread.run(self._add(guild_id, columns))

    def reopen(self, guild_id: int) -> None:
        self._thread.run(self._reopen(guild_id))


# --- The keyring ---------------------------------------------------------------


class Keyring:
    """Hands out a community's key, making it first when ``root`` is given.

    Without a root it only reads: the keys a deployment made while
    ``STORAGE_ENCRYPTION`` was set, after it was unset again.
    """

    def __init__(
        self, store: KeyStore, root: Root | None, *, ttl: float = CACHE_SECONDS
    ) -> None:
        self.store, self.root, self._ttl = store, root, ttl
        self._cache: dict[int, tuple[float, bytes, int]] = {}
        self._lock = threading.Lock()

    @property
    def encrypts(self) -> bool:
        """Whether new objects are written encrypted."""
        return self.root is not None

    def key_for(self, guild_id: int, *, create: bool) -> tuple[bytes, int] | None:
        """``guild_id``'s key and its generation; ``None`` where it has none
        and ``create`` is false (or there is no root to make one with)."""
        guild_id = int(guild_id)
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(guild_id)
            if cached and cached[0] > now:
                return cached[1], cached[2]
        row = self.store.get(guild_id)
        if row is None:
            if not create or self.root is None:
                return None
            row = self.store.add(guild_id, self.root.wrap(guild_id, os.urandom(32)))
        key = _unwrap(row)
        with self._lock:
            self._cache[guild_id] = (now + self._ttl, key, row.generation)
        return key, row.generation

    def forget(self, guild_id: int) -> None:
        with self._lock:
            self._cache.pop(int(guild_id), None)

    def stored_in_the_clear(self, guild_id: int) -> None:
        """Note that ``guild_id`` stored something unencrypted while this
        keyring only reads (encryption unset, keys left), so the backfill
        looks at the community again once encryption is back on. One update
        per such write: a state a deployment passes through, not one it
        lives in."""
        if not self.encrypts:
            self.store.reopen(guild_id)


_keyring: Keyring | None = None
#: Whether this deployment has keys to read while STORAGE_ENCRYPTION is unset.
#: Set once at startup by :func:`prime`.
_keys_to_read = False
_built_for: tuple[str, str, bool] | None = None


def _root() -> Root | None:
    if settings.STORAGE_ENCRYPTION == "local":
        return LocalRoot()
    if settings.STORAGE_ENCRYPTION == "gcp_kms":
        return KmsRoot(settings.STORAGE_ENCRYPTION_KMS_KEY)
    return None


def active_keyring() -> Keyring | None:
    """The process's keyring; ``None`` where storage is not encrypted and
    never was, which is every FOSS deployment that leaves it unset."""
    global _keyring, _built_for
    wanted = (
        settings.STORAGE_ENCRYPTION,
        settings.STORAGE_ENCRYPTION_KMS_KEY,
        _keys_to_read,
    )
    if _built_for != wanted:
        root = _root()
        _keyring = Keyring(DatabaseKeyStore(), root) if root or _keys_to_read else None
        _built_for = wanted
    return _keyring


def use_keyring(keyring: Keyring | None) -> None:
    """Replace the process's keyring (tests)."""
    global _keyring, _built_for
    _keyring = keyring
    _built_for = (
        settings.STORAGE_ENCRYPTION,
        settings.STORAGE_ENCRYPTION_KMS_KEY,
        _keys_to_read,
    )


async def prime(session: AsyncSession) -> None:
    """At startup: whether this deployment holds community keys although
    ``STORAGE_ENCRYPTION`` is unset, so objects stored encrypted while it was
    set still read. One indexed probe of an empty table on a deployment that
    never encrypted."""
    global _keys_to_read
    if settings.STORAGE_ENCRYPTION:
        return
    found = (
        await session.exec(text("SELECT 1 FROM guild_storage_keys LIMIT 1"))
    ).first()
    _keys_to_read = found is not None
    if _keys_to_read:
        logger.warning(
            "STORAGE_ENCRYPTION is unset, but communities hold storage keys: new "
            "objects are stored unencrypted, and the encrypted ones still read."
        )


async def destroy(session: AsyncSession, guild_id: int) -> bool:
    """Delete ``guild_id``'s key, so nothing it stored encrypted reads again.
    The caller commits. Returns whether there was a key."""
    result = await session.exec(
        text("DELETE FROM guild_storage_keys WHERE guild_id = :g"),
        params={"g": int(guild_id)},
    )
    keyring = _keyring
    if keyring is not None:
        keyring.forget(guild_id)
    return bool(result.rowcount)


async def mark_backfilled(session: AsyncSession, guild_id: int) -> None:
    """Record that ``guild_id`` has nothing stored from before encryption.
    The caller commits."""
    await session.exec(
        text("UPDATE guild_storage_keys SET backfilled_at = now() WHERE guild_id = :g"),
        params={"g": int(guild_id)},
    )
