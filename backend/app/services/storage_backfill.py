"""Runner + shared status for the local->S3 upload backfill.

Wraps :func:`app.db.backfill_uploads_to_s3.backfill_uploads_to_s3` so the Storage
settings tab can kick off the transfer and poll its progress.

Status lives in a Postgres **UNLOGGED** singleton table ``storage_backfill_state``
(id=1) — *not* an Alembic migration. The backfill is a one-off transfer, not part
of the permanent schema, so the table is created lazily at runtime (idempotent
``CREATE UNLOGGED TABLE IF NOT EXISTS``) rather than migrated in. UNLOGGED means
its rows aren't WAL-logged (cheap, and fine to lose on a crash — you'd just re-run
the transfer). It is nonetheless **shared across workers**, so every worker
reports the same status — the earlier in-memory version showed running/failed/idle
inconsistently on a multi-worker deployment and could wrongly accept a losing
start.

The start path is an **atomic DB claim**: a single conditional UPDATE flips the
row to ``running`` only if it isn't already running (or its heartbeat has gone
stale, i.e. the worker that claimed it died). Whoever wins the UPDATE owns the
run; everyone else gets a conflict immediately, before any work starts. The copy
loop additionally holds a Postgres advisory lock (in ``backfill_uploads_to_s3``)
as the hard guard against the CLI racing a UI run.

The table is created by the superuser provisioning engine (DDL) and read/written
only by the ``app_admin`` BYPASSRLS engine; RLS is forced with no policies, so no
scoped request role can reach it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Container
from datetime import timedelta

from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.clock import utcnow
from app.core.messages import SettingsMessages
from app.db import post_commit
from app.db import session as db_session
from app.db.backfill_uploads_to_s3 import BackfillSummary, backfill_uploads_to_s3
from app.db.public_rls import PUBLIC_RLS, render_table_rls
from app.db.session import SystemSessionLocal
from app.db.system_grants import (
    ROLE_GRANTS,
    grant_statements,
    grantee,
    revoke_statements,
)

logger = logging.getLogger(__name__)

GLOBAL_ID = 1
# A 'running' row whose heartbeat is older than this is treated as a dead worker
# and may be reclaimed. The copy loop's advisory lock is the real concurrency
# guard, so a too-eager reclaim still can't cause a double copy.
_STALE_AFTER = timedelta(minutes=15)

_TABLE = "storage_backfill_state"

_CREATE_TABLE = """
CREATE UNLOGGED TABLE IF NOT EXISTS storage_backfill_state (
    id integer PRIMARY KEY,
    status varchar(20) NOT NULL DEFAULT 'idle',
    copied integer NOT NULL DEFAULT 0,
    skipped integer NOT NULL DEFAULT 0,
    failed integer NOT NULL DEFAULT 0,
    hash_mismatches integer NOT NULL DEFAULT 0,
    failed_keys jsonb NOT NULL DEFAULT '[]'::jsonb,
    error varchar(2000),
    started_at timestamptz,
    finished_at timestamptz,
    heartbeat timestamptz
)
"""

_table_lock = asyncio.Lock()
_table_ready = False


def _table_ddl(present: Container[str]) -> str:
    """The table, then its row security and grants as the shared-table
    registry declares them. Every role in ``present`` (catalog names) has its
    grants revoked before any are granted, so a table created by an earlier
    build converges on the registry, the schema's default grants to the two
    request-path floors are taken back where it gives them none, and a login
    named by both login fields keeps the verbs of each."""
    return "\n".join(
        [
            f"{_CREATE_TABLE.strip()};",
            render_table_rls(_TABLE, PUBLIC_RLS[_TABLE]),
            *(
                f"{statement};"
                for role in ROLE_GRANTS
                if grantee(role) in present
                for statement in revoke_statements(role, [_TABLE])
            ),
            *(
                f"{statement};"
                for role in ROLE_GRANTS
                for statement in grant_statements(role, [_TABLE])
            ),
        ]
    )


class BackfillAlreadyRunning(RuntimeError):
    """Raised when a backfill is already running (the claim was lost)."""


async def _ensure_table() -> None:
    """Create the UNLOGGED status table once per process (idempotent).

    The provisioning engine creates the table and applies the grants declared
    in the shared-table registry (:func:`_table_ddl`).
    """
    global _table_ready
    if _table_ready:
        return
    async with _table_lock:
        if _table_ready:
            return
        async with db_session.provisioning_engine.begin() as conn:
            present = (
                await conn.execute(
                    text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:names)"),
                    {"names": [grantee(role) for role in ROLE_GRANTS]},
                )
            ).scalars()
            ddl = _table_ddl(set(present))
            raw = await conn.get_raw_connection()
            await raw.driver_connection.execute(ddl)
        _table_ready = True


def reset_for_tests() -> None:
    """Force the next access to re-create the table (test isolation helper)."""
    global _table_ready
    _table_ready = False


async def _fetch(session: AsyncSession) -> dict | None:
    result = await session.exec(
        text("SELECT * FROM storage_backfill_state WHERE id = :id"),
        params={"id": GLOBAL_ID},
    )
    row = result.mappings().first()
    return dict(row) if row is not None else None


async def _ensure_row(session: AsyncSession) -> None:
    await session.exec(
        text(
            "INSERT INTO storage_backfill_state (id, status) VALUES (:id, 'idle') "
            "ON CONFLICT (id) DO NOTHING"
        ),
        params={"id": GLOBAL_ID},
    )
    await session.commit()


async def get_status(session: AsyncSession) -> dict:
    """Return the shared status row (created idle on first read)."""
    await _ensure_table()
    row = await _fetch(session)
    if row is None:
        await _ensure_row(session)
        row = await _fetch(session)
    if row is None:
        raise RuntimeError("storage backfill state row missing after creation")
    return row


async def try_claim(session: AsyncSession) -> bool:
    """Atomically claim the singleton for a new run. Returns True if claimed.

    The conditional UPDATE is the cross-worker guard: only one worker's UPDATE can
    match (status not running, or running-but-stale) and flip the row to running,
    so concurrent starts on different workers can't both proceed.
    """
    await _ensure_table()
    await _ensure_row(session)
    now = utcnow()
    result = await session.exec(
        text(
            "UPDATE storage_backfill_state SET "
            "status = 'running', started_at = :now, finished_at = NULL, "
            "heartbeat = :now, copied = 0, skipped = 0, failed = 0, "
            "hash_mismatches = 0, failed_keys = '[]'::jsonb, error = NULL "
            "WHERE id = :id AND "
            "(status <> 'running' OR heartbeat IS NULL OR heartbeat < :stale)"
        ),
        params={"id": GLOBAL_ID, "now": now, "stale": now - _STALE_AFTER},
    )
    await session.commit()
    return (result.rowcount or 0) == 1


async def _persist(
    session: AsyncSession,
    *,
    status: str,
    summary: BackfillSummary | None = None,
    error: str | None = None,
    finished: bool = False,
) -> None:
    sets = ["status = :status", "heartbeat = :hb"]
    params: dict = {"id": GLOBAL_ID, "status": status, "hb": utcnow()}
    if summary is not None:
        sets += [
            "copied = :copied",
            "skipped = :skipped",
            "failed = :failed",
            "hash_mismatches = :hm",
            "failed_keys = CAST(:fk AS jsonb)",
        ]
        params.update(
            copied=summary.copied,
            skipped=summary.skipped,
            failed=summary.failed,
            hm=summary.hash_mismatches,
            fk=json.dumps(list(summary.failed_keys)),
        )
    if error is not None:
        sets.append("error = :error")
        params["error"] = error
    if finished:
        sets.append("finished_at = :fin")
        params["fin"] = utcnow()
    await session.exec(
        text(f"UPDATE storage_backfill_state SET {', '.join(sets)} WHERE id = :id"),
        params=params,
    )
    await session.commit()


async def _finalize(
    session: AsyncSession,
    *,
    summary: BackfillSummary | None = None,
    error: str | None = None,
) -> None:
    """Write the terminal status of a run to the shared row."""
    if error is not None:
        await _persist(session, status="failed", error=error, finished=True)
    elif summary is not None and summary.already_running:
        # The copy loop's advisory lock was held elsewhere (e.g. the CLI), so this
        # run copied nothing. Report it rather than a misleading "complete,
        # copied=0".
        await _persist(
            session,
            status="failed",
            summary=summary,
            error=SettingsMessages.STORAGE_BACKFILL_RUNNING,
            finished=True,
        )
    else:
        if summary is None:
            raise RuntimeError("finalize requires a summary when no error is given")
        await _persist(
            session,
            status="failed" if summary.failed else "complete",
            summary=summary,
            finished=True,
        )


async def _run() -> None:
    """Detached task: run the backfill with its own system session and persist
    progress + the final outcome to the shared row."""
    try:
        async with SystemSessionLocal() as session:

            async def _on_progress(summary: BackfillSummary) -> None:
                await _persist(session, status="running", summary=summary)

            try:
                summary = await backfill_uploads_to_s3(on_progress=_on_progress)
                await _finalize(session, summary=summary)
            except Exception:
                logger.exception("storage backfill failed")
                await _finalize(session, error=SettingsMessages.STORAGE_BACKFILL_FAILED)
    except asyncio.CancelledError:
        # Stopped at shutdown, however early. The copy skips what the bucket
        # already holds, so the next run carries on from here and may start now.
        async with SystemSessionLocal() as session:
            await _persist(session, status="failed", finished=True)
        raise


async def start_backfill(session: AsyncSession) -> dict:
    """Claim and launch a backfill. Raises ``BackfillAlreadyRunning`` if one is
    already in progress (cluster-wide)."""
    if not await try_claim(session):
        raise BackfillAlreadyRunning()
    post_commit.spawn(_run(), cancel_on_settle=True)
    row = await _fetch(session)
    if row is None:
        raise RuntimeError("storage backfill state row missing after claim")
    return row
