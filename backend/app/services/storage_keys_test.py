"""Community storage keys against the test database: made once, read from a
fresh process, destroyed with the community, and the backfill that encrypts
what was stored before."""

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from app.core import storage_crypto
from app.core.config import settings
from app.db import session as db_session
from app.services import storage_config, storage_encryption, storage_keys
from app.services.storage import (
    EVIDENCE_KEY_PREFIX,
    EncryptedStorage,
    LocalFilesystemStorage,
    get_guild_storage,
)
from app.models.tenant.pending_upload import PendingUpload
from app.services.storage_keys import DatabaseKeyStore, Keyring, LocalRoot
from app.testing import route_session_to_guild
from app.testing.factories import create_guild, create_user


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.setattr(storage_encryption, "START_DELAY_SECONDS", 0)
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")
    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path))
    storage_config.reset_for_tests()
    yield
    storage_keys.use_keyring(None)
    monkeypatch.setattr(storage_keys, "_keys_to_read", False)
    storage_config.reset_for_tests()


async def _row(guild_id: int) -> Any:
    async with db_session.SystemSessionLocal() as session:
        return (
            await session.exec(
                text(
                    "SELECT local_sealed, kms_sealed, backfilled_at "
                    "FROM guild_storage_keys WHERE guild_id = :g"
                ),
                params={"g": guild_id},
            )
        ).first()


async def test_a_community_gets_one_key_that_a_fresh_process_reads(session):
    guild = await create_guild(session)
    key = Keyring(DatabaseKeyStore(), LocalRoot()).key_for(guild.id, create=True)

    assert (
        Keyring(DatabaseKeyStore(), LocalRoot()).key_for(guild.id, create=True) == key
    )
    assert Keyring(DatabaseKeyStore(), None).key_for(guild.id, create=False) == key
    row = await _row(guild.id)
    assert row.local_sealed and row.kms_sealed is None


async def test_destroying_the_key_leaves_none(session):
    guild = await create_guild(session)
    Keyring(DatabaseKeyStore(), LocalRoot()).key_for(guild.id, create=True)
    async with db_session.SystemSessionLocal() as system:
        assert await storage_keys.destroy(system, guild.id) is True
        await system.commit()
    assert Keyring(DatabaseKeyStore(), None).key_for(guild.id, create=False) is None


async def test_a_deprovisioned_community_takes_its_key(session):
    from app.db.schema_provisioning import deprovision_guild

    guild = await create_guild(session)
    keyring = Keyring(DatabaseKeyStore(), LocalRoot())
    storage_keys.use_keyring(keyring)
    get_guild_storage(guild.id).write("a.bin", b"stored encrypted")

    await deprovision_guild(guild.id)
    assert await _row(guild.id) is None


async def test_keys_left_with_encryption_unset_are_found_at_startup(
    session, monkeypatch
):
    guild = await create_guild(session)
    Keyring(DatabaseKeyStore(), LocalRoot()).key_for(guild.id, create=True)
    monkeypatch.setattr(settings, "STORAGE_ENCRYPTION", "")
    async with db_session.SystemSessionLocal() as system:
        await storage_keys.prime(system)
    assert storage_keys._keys_to_read is True
    keyring = storage_keys.active_keyring()
    assert keyring is not None and not keyring.encrypts


async def test_a_deployment_that_never_encrypted_starts_with_nothing_to_read(
    session, monkeypatch
):
    monkeypatch.setattr(settings, "STORAGE_ENCRYPTION", "")
    async with db_session.SystemSessionLocal() as system:
        await storage_keys.prime(system)
    assert storage_keys._keys_to_read is False
    assert storage_keys.active_keyring() is None


async def test_the_backfill_encrypts_what_was_stored_before(session: Any) -> None:
    guild = await create_guild(session)
    plain = LocalFilesystemStorage(prefix=f"guild_{guild.id}/")
    plain.write("before.txt", b"stored in the clear")
    plain.write(f"{EVIDENCE_KEY_PREFIX}x", b"sealed by its own scheme")

    storage_keys.use_keyring(Keyring(DatabaseKeyStore(), LocalRoot()))
    assert await storage_encryption.encrypt_existing() == 1

    storage = get_guild_storage(guild.id)
    assert isinstance(storage, EncryptedStorage)
    assert storage.is_encrypted("before.txt") is True
    assert (
        plain.resolve_readable("before.txt")
        .read_bytes()
        .startswith(storage_crypto.MAGIC)
    )
    assert (
        b"".join(storage.open_readable("before.txt").stream) == b"stored in the clear"
    )
    assert (
        plain.resolve_readable(f"{EVIDENCE_KEY_PREFIX}x").read_bytes()
        == b"sealed by its own scheme"
    )
    assert (await _row(guild.id)).backfilled_at is not None

    # Caught up: the next pass does not look again.
    assert await storage_encryption.encrypt_existing() == 0


async def _arriving(session: Any, guild_id: int, key: str, *, encrypted: bool) -> None:
    """A tus upload still arriving in ``guild_id``, begun encrypted or not."""
    user = await create_user(session)
    await route_session_to_guild(session, guild_id)
    session.add(
        PendingUpload(
            id=key.removeprefix("resumable-"),
            created_by=user.id,
            purpose="file",
            filename="big.mov",
            length=100,
            staging_key=key,
            blob_state={"store": "local", "enc": {}}
            if encrypted
            else {"store": "local"},
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
    )
    await session.commit()


async def test_finished_uploads_are_encrypted_and_arriving_ones_left_alone(
    session: Any,
) -> None:
    guild = await create_guild(session)
    plain = LocalFilesystemStorage(prefix=f"guild_{guild.id}/")
    # A finished tus upload keeps its staging key as its filename for good.
    plain.write("resumable-done", b"a finished upload")
    plain.write("resumable-going", b"half of a file still arrivi")
    await _arriving(session, guild.id, "resumable-going", encrypted=False)

    storage_keys.use_keyring(Keyring(DatabaseKeyStore(), LocalRoot()))
    assert await storage_encryption.encrypt_existing() == 1

    assert (
        plain.resolve_readable("resumable-done")
        .read_bytes()
        .startswith(storage_crypto.MAGIC)
    )
    assert (
        plain.resolve_readable("resumable-going").read_bytes()
        == b"half of a file still arrivi"
    )
    # It will finish in the clear, so the community is not caught up yet.
    assert (await _row(guild.id)).backfilled_at is None


async def test_an_upload_begun_encrypted_does_not_hold_the_community_back(
    session: Any,
) -> None:
    guild = await create_guild(session)
    await _arriving(session, guild.id, "resumable-sealed", encrypted=True)
    storage_keys.use_keyring(Keyring(DatabaseKeyStore(), LocalRoot()))
    await storage_encryption.encrypt_existing()
    assert (await _row(guild.id)).backfilled_at is not None


async def test_storing_in_the_clear_after_encryption_was_unset_reopens_the_community(
    session: Any,
) -> None:
    guild = await create_guild(session)
    storage_keys.use_keyring(Keyring(DatabaseKeyStore(), LocalRoot()))
    await storage_encryption.encrypt_existing()
    assert (await _row(guild.id)).backfilled_at is not None

    storage_keys.use_keyring(Keyring(DatabaseKeyStore(), None))
    get_guild_storage(guild.id).write("between.bin", b"stored while it was off")
    assert (await _row(guild.id)).backfilled_at is None

    storage_keys.use_keyring(Keyring(DatabaseKeyStore(), LocalRoot()))
    assert await storage_encryption.encrypt_existing() == 1
