"""Tests for the UNLOGGED-table backfill runner (shared cross-worker status).

The ``storage_backfill_state`` UNLOGGED table is created lazily at runtime and is
RLS-forced, reachable only by the ``app_admin`` (BYPASSRLS) engine — these drive
it through ``role_session("app_admin")``, the real production privilege boundary.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from app.core.messages import SettingsMessages
from app.db.backfill_uploads_to_s3 import BackfillSummary
from app.services import storage_backfill


@pytest.fixture
async def system_session(role_session):
    return await role_session("app_admin")


@pytest.fixture(autouse=True)
async def _reset_backfill_row(system_session):
    """Create the table (if needed) and reset the singleton to idle before each
    test — the UNLOGGED table persists across tests within a worker."""
    await storage_backfill.get_status(system_session)  # ensures table + row
    await system_session.exec(
        text(
            "UPDATE storage_backfill_state SET status = 'idle', heartbeat = NULL, "
            "started_at = NULL, finished_at = NULL, copied = 0, skipped = 0, "
            "failed = 0, hash_mismatches = 0, error = NULL"
        )
    )
    await system_session.commit()
    yield


async def test_stale_running_can_be_reclaimed(system_session) -> None:
    """A 'running' row whose heartbeat has gone stale (dead worker) is reclaimable
    so a backfill can't be wedged forever by a crash."""
    assert await storage_backfill.try_claim(system_session) is True
    await system_session.exec(
        text("UPDATE storage_backfill_state SET heartbeat = :hb"),
        params={"hb": storage_backfill.utcnow() - timedelta(hours=2)},
    )
    await system_session.commit()

    assert await storage_backfill.try_claim(system_session) is True


async def test_start_backfill_conflict_raises(system_session, monkeypatch) -> None:
    """start_backfill claims synchronously and raises on a lost claim (any
    worker's): the cross-worker start guard."""

    async def _noop() -> None:
        return None

    # Don't run the real copy task (it would open its own system session); we only
    # assert the synchronous claim/guard behaviour.
    monkeypatch.setattr(storage_backfill, "_run", _noop)

    row = await storage_backfill.start_backfill(system_session)
    assert row["status"] == "running"
    assert row["started_at"] is not None

    with pytest.raises(storage_backfill.BackfillAlreadyRunning):
        await storage_backfill.start_backfill(system_session)


async def test_finalize_maps_outcomes(system_session) -> None:
    await storage_backfill.try_claim(system_session)
    await storage_backfill._finalize(
        system_session, summary=BackfillSummary(copied=3, skipped=1)
    )
    row = await storage_backfill.get_status(system_session)
    assert row["status"] == "complete"
    assert row["copied"] == 3 and row["skipped"] == 1
    assert row["finished_at"] is not None

    await storage_backfill.try_claim(system_session)
    await storage_backfill._finalize(
        system_session, summary=BackfillSummary(failed=2, failed_keys=["a", "b"])
    )
    row = await storage_backfill.get_status(system_session)
    assert row["status"] == "failed"
    assert row["failed"] == 2
    assert list(row["failed_keys"]) == ["a", "b"]

    await storage_backfill.try_claim(system_session)
    await storage_backfill._finalize(
        system_session, summary=BackfillSummary(already_running=True)
    )
    row = await storage_backfill.get_status(system_session)
    assert row["status"] == "failed"
    assert row["error"] == SettingsMessages.STORAGE_BACKFILL_RUNNING

    await storage_backfill.try_claim(system_session)
    await storage_backfill._finalize(
        system_session, error=SettingsMessages.STORAGE_BACKFILL_FAILED
    )
    row = await storage_backfill.get_status(system_session)
    assert row["status"] == "failed"
    assert row["error"] == SettingsMessages.STORAGE_BACKFILL_FAILED
