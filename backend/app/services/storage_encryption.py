"""Encrypting what communities stored before ``STORAGE_ENCRYPTION`` was set.

Once a deployment sets it, every new object is written encrypted
(``app.services.storage.EncryptedStorage``), and objects already there keep
reading as they are. This pass catches them up: community by community, it
lists the namespace, and re-writes each object stored in the clear encrypted
under that community's key, in place and under the same key, so nothing that
names an object has to change.

- **One process at a time**, under an advisory lock: a second one finds it
  taken and leaves it.
- **Each community once.** When a community's namespace holds nothing in the
  clear, its key row records ``backfilled_at`` and later passes skip it. New
  objects in it are encrypted as they are written.
- **Staging and evidence are left alone.** A file still arriving in parts
  finishes as it began, and its parts and kept tail are thrown away with it;
  evidence is encrypted under its own scheme already.

On S3 a re-write leaves the plaintext as the object's previous version, which
the bucket's own lifecycle removes (30 days on the cloud's uploads bucket).
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from app.db import session as db_session
from app.db.advisory_locks import LockNamespace, advisory_lock, advisory_unlock

logger = logging.getLogger(__name__)

#: How often a process looks for something left to encrypt.
PASS_SECONDS = 6 * 3600


def _left_alone(key: str) -> bool:
    from app.services.resumable import STAGING_PREFIX
    from app.services.storage import EVIDENCE_KEY_PREFIX

    return key.startswith((STAGING_PREFIX, EVIDENCE_KEY_PREFIX)) or key.endswith(
        ("-tail", "-etail")
    )


def encrypt_community(guild_id: int) -> int:
    """Encrypt every object ``guild_id`` stored in the clear. Blocks; returns
    how many it re-wrote."""
    from app.services.storage import EncryptedStorage, get_guild_storage

    storage = get_guild_storage(guild_id)
    if not isinstance(storage, EncryptedStorage):
        return 0
    # Made now if the community has none yet, so its row can record the pass.
    storage._keyring.key_for(guild_id, create=True)
    done = failed = 0
    for key in list(storage.inner.iter_keys()):  # type: ignore[attr-defined]
        if _left_alone(key):
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


async def encrypt_existing() -> int:
    """One pass over every community not yet caught up. Returns how many
    objects it encrypted."""
    from app.services import storage_keys

    keyring = storage_keys.active_keyring()
    if keyring is None or not keyring.encrypts:
        return 0
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
                    done = await asyncio.to_thread(encrypt_community, guild_id)
                except Exception:
                    continue
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
