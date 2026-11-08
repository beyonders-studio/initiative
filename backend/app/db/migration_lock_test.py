"""The lock instances take turns on while they migrate a shared database."""

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import settings
from app.db import init_db
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db.session import migration_lock
from conftest import TEST_DATABASE_URL


@pytest.fixture(autouse=True)
def _lock_against_the_test_database(monkeypatch):
    """``migration_lock`` opens its own connection from DATABASE_URL; point that
    at this worker's database so the lock is taken where the probes look."""
    monkeypatch.setattr(settings, "DATABASE_URL", TEST_DATABASE_URL)


async def _key_is_free(engine: AsyncEngine) -> bool:
    """Whether a separate connection can still take the migration key.

    Asks for the transaction-scoped form, which shares its identifier space
    with the session-scoped one the lock itself takes: it answers the same
    question and is released when this connection's transaction ends.
    """
    async with engine.connect() as conn:
        return await advisory_lock(conn, LockNamespace.MIGRATION, wait=False)


async def test_lock_is_held_for_the_block_and_released_after(engine):
    assert await _key_is_free(engine)
    async with migration_lock():
        assert not await _key_is_free(engine)
    assert await _key_is_free(engine)


async def test_lock_is_released_when_the_block_raises(engine):
    with pytest.raises(RuntimeError):
        async with migration_lock():
            raise RuntimeError("migration failed")
    assert await _key_is_free(engine)


async def test_a_second_instance_waits_for_the_first(engine):
    """The second caller blocks until the first is done, rather than migrating
    alongside it."""
    inside = asyncio.Event()

    async def second_instance() -> None:
        async with migration_lock():
            inside.set()

    async with migration_lock():
        waiting = asyncio.create_task(second_instance())
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(inside.wait(), timeout=0.5)

    await asyncio.wait_for(waiting, timeout=10)
    assert inside.is_set()
    assert await _key_is_free(engine)


async def test_a_missing_database_is_named_rather_than_thrown_at_you(monkeypatch):
    """The lock connects before anything else does, so it owes the operator the
    same message the upgrade behind it would have given."""
    absent = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/initiative_no_such_database"
    monkeypatch.setattr(settings, "DATABASE_URL", absent)

    with pytest.raises(RuntimeError) as refused:
        async with migration_lock():
            pass

    assert "initiative_no_such_database" in str(refused.value)


async def test_migrate_database_covers_the_stamp_check_and_the_upgrade(
    engine, monkeypatch
):
    """Both steps run under one lock: the check decides the stamp the upgrade
    then acts on."""
    held: list[bool] = []

    async def _probe(*_conn) -> None:
        held.append(not await _key_is_free(engine))

    monkeypatch.setattr(init_db, "check_pre_baseline_db", _probe)
    monkeypatch.setattr(init_db, "run_migrations", _probe)

    await init_db.migrate_database()

    assert held == [True, True]
