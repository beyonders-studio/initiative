"""Encrypting what communities stored before ``STORAGE_ENCRYPTION`` was set.

Once a deployment sets it, every new object is written encrypted
(``app.services.storage.EncryptedStorage``), and objects already there keep
reading as they are. This pass catches them up: community by community, it
lists the namespace, and re-writes each object stored in the clear encrypted
under that community's key, in place and under the same key, so nothing that
names an object has to change.

- **One process at a time**, under an advisory lock: a second one finds it
  taken and leaves it.
- **Each community until it is caught up.** When a community's namespace holds
  nothing in the clear, its key row records ``backfilled_at`` and later passes
  skip it. New objects in it are encrypted as they are written. A community is
  not marked while a file it began in the clear is still arriving, and a
  process that stores in the clear after encryption was unset clears the mark
  again (``EncryptedStorage``), so turning encryption off and on never leaves
  what was stored in between behind.
- **What is still arriving is left alone.** A tus upload's staged object only
  becomes a file once it is complete (and keeps its ``resumable-`` key as its
  filename after that, so finished ones are encrypted like any other file).
  Until then its parts and kept tail are not a file; evidence is encrypted
  under its own scheme already.
- **Not at once on boot.** The first pass waits :data:`START_DELAY_SECONDS`,
  so a rolling deploy that turns encryption on has replaced the processes
  that would still store in the clear before any community is marked.

On S3 a re-write leaves the plaintext as the object's previous version, which
the bucket's own lifecycle removes (30 days on the cloud's uploads bucket).
"""

from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy import text

from app.db import session as db_session
from app.db.advisory_locks import LockNamespace, advisory_lock, advisory_unlock

logger = logging.getLogger(__name__)

#: How often a process looks for something left to encrypt.
PASS_SECONDS = 6 * 3600
#: How long after this process started its first pass waits.
START_DELAY_SECONDS = 600
_STARTED = time.monotonic()


def _left_alone(key: str, arriving: frozenset[str]) -> bool:
    from app.services.storage import EVIDENCE_KEY_PREFIX

    if key.startswith(EVIDENCE_KEY_PREFIX) or key.endswith("-etail"):
        # Sealed already: evidence by blob_crypto, a kept tail by its upload.
        return True
    return key in arriving or key.removesuffix("-tail") in arriving


def encrypt_community(guild_id: int, arriving: frozenset[str] = frozenset()) -> int:
    """Encrypt every object ``guild_id`` stored in the clear, but the uploads
    still ``arriving``. Blocks; returns how many it re-wrote."""
    from app.services.storage import EncryptedStorage, get_guild_storage

    storage = get_guild_storage(guild_id)
    if not isinstance(storage, EncryptedStorage):
        return 0
    # Made now if the community has none yet, so its row can record the pass.
    storage._keyring.key_for(guild_id, create=True)
    done = failed = 0
    for key in list(storage.inner.iter_keys()):  # type: ignore[attr-defined]
        if _left_alone(key, arriving):
            continue
        try:
            if storage.encrypt_in_place(key):
                done += 1
        except Exception:
            # One object that will not re-write must not stop the rest.
            failed += 1
            logger.exception("storage encryption: %s in guild %s failed", key, guild_id)
    if failed:
        # Unmarked, so the next pass tries the community again.
        raise RuntimeError(f"{failed} object(s) in guild {guild_id} were not encrypted")
    return done


async def _arriving(guild_id: int) -> tuple[frozenset[str], bool]:
    """The uploads still arriving in ``guild_id``, and whether any of them
    began in the clear (and so will finish in the clear)."""
    from app.db import cohorts
    from app.db.request_context import SystemGuild

    async with cohorts.system_session(guild_id) as session:
        await db_session.set_rls_context(session, SystemGuild(guild_id, read_only=True))
        rows = (
            await session.exec(
                text(
                    "SELECT staging_key, blob_state FROM pending_uploads "
                    "WHERE completed_at IS NULL"
                )
            )
        ).all()
        await session.rollback()
    keys = frozenset(row.staging_key for row in rows)
    in_the_clear = any("enc" not in (row.blob_state or {}) for row in rows)
    return keys, in_the_clear


async def encrypt_existing() -> int:
    """One pass over every community not yet caught up. Returns how many
    objects it encrypted."""
    from app.services import storage_keys

    keyring = storage_keys.active_keyring()
    if keyring is None or not keyring.encrypts:
        return 0
    wait = START_DELAY_SECONDS - (time.monotonic() - _STARTED)
    if wait > 0:
        await asyncio.sleep(wait)
    total = 0
    async with db_session.system_engine.connect() as conn:
        if not await advisory_lock(
            conn, LockNamespace.STORAGE_ENCRYPTION, wait=False, xact=False
        ):
            return 0
        try:
            guild_ids = (
                (
                    await conn.execute(
                        text(
                            "SELECT g.id FROM public.guilds g "
                            "LEFT JOIN public.guild_storage_keys k ON k.guild_id = g.id "
                            "WHERE k.backfilled_at IS NULL ORDER BY g.id"
                        )
                    )
                )
                .scalars()
                .all()
            )
            await conn.rollback()
            for guild_id in guild_ids:
                try:
                    arriving, in_the_clear = await _arriving(guild_id)
                    done = await asyncio.to_thread(
                        encrypt_community, guild_id, arriving
                    )
                except Exception:
                    logger.exception(
                        "storage encryption: guild %s not caught up", guild_id
                    )
                    continue
                if not in_the_clear:
                    async with db_session.SystemSessionLocal() as session:
                        await storage_keys.mark_backfilled(session, guild_id)
                        await session.commit()
                total += done
                if done:
                    logger.info(
                        "storage encryption: encrypted %d object(s) in guild %s",
                        done,
                        guild_id,
                    )
        finally:
            await conn.rollback()
            await advisory_unlock(conn, LockNamespace.STORAGE_ENCRYPTION)
    return total
