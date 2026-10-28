"""Community storage keys against the test database: made once, read from a
fresh process, destroyed with the community, and the backfill that encrypts
what was stored before."""

import pytest
from sqlalchemy import text

from app.core import storage_crypto
from app.core.config import settings
from app.db import session as db_session
from app.services import storage_config, storage_encryption, storage_keys
from app.services.storage import (
    EncryptedStorage,
    LocalFilesystemStorage,
    get_guild_storage,
)
from app.services.storage_keys import DatabaseKeyStore, Keyring, LocalRoot
from app.testing.factories import create_guild


@pytest.fixture(autouse=True)
def _reset(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")
    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path))
    storage_config.reset_for_tests()
    yield
    storage_keys.use_keyring(None)
    monkeypatch.setattr(storage_keys, "_keys_to_read", False)
    storage_config.reset_for_tests()


async def _row(guild_id):
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


async def test_the_backfill_encrypts_what_was_stored_before(session, tmp_path):
    guild = await create_guild(session)
    plain = LocalFilesystemStorage(prefix=f"guild_{guild.id}/")
    plain.write("before.txt", b"stored in the clear")
    plain.write("resumable-staging", b"left as it began")

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
        plain.resolve_readable("resumable-staging").read_bytes() == b"left as it began"
    )
    assert (await _row(guild.id)).backfilled_at is not None

    # Caught up: the next pass does not look again.
    assert await storage_encryption.encrypt_existing() == 0
