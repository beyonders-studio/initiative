"""Backfill: copy existing local uploads into the configured S3 bucket.

The final step of the local→S3 migration. Run it with the ``S3_*`` settings
pointed at your object store **while the app is still on
``STORAGE_BACKEND=local``**: it copies every blob under
``UPLOADS_DIR/guild_<id>/`` to the S3 key ``guild_<id>/<file>``, setting the
content-type recorded on the ``uploads`` row (falling back to a guess from the
extension). It's **idempotent** — an object already present in S3 is skipped — so
it is safe to re-run and resume.

After it reports 0 failures, cut over: set ``STORAGE_BACKEND=s3`` (with
``S3_LOCAL_FALLBACK=true`` for a verification window, then turn it off).

    python -m app.db.backfill_uploads_to_s3 [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import mimetypes
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import settings
from app.db import cohorts
from app.db.advisory_locks import LockNamespace, advisory_lock, advisory_unlock
from app.db import session as db_session
from app.db.schema_provisioning import guild_schema_name
from app.services import storage_config
from app.services.storage import S3Storage, StorageBackend, build_s3_client
from app.db.request_context import SystemGuild

logger = logging.getLogger(__name__)

# One-shot guard so the "HeadObject 403 -> probably missing s3:ListBucket" hint is
# logged once per run, not once per file. Reset at the start of each backfill.
_warned_head_forbidden = False


def _object_exists(dest: StorageBackend, key: str) -> bool:
    """Whether ``key`` is already in ``dest``, tolerating a 403 HeadObject.

    Many S3 stores return **403 Forbidden** instead of 404 for ``HeadObject`` on
    a *missing* key when the credentials lack ``s3:ListBucket`` on the bucket.
    That must not abort the migration: we can't confirm presence, so we report
    "not present" and let the idempotent write below decide — a real
    write-permission problem then surfaces on ``PutObject`` (recorded per file),
    while a fresh bucket simply gets every object (re-runs lose the skip
    optimization but stay correct). Non-403 errors propagate as before.
    """
    from botocore.exceptions import ClientError

    try:
        return dest.exists(key)
    except ClientError as exc:
        if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 403:
            raise
        global _warned_head_forbidden
        if not _warned_head_forbidden:
            _warned_head_forbidden = True
            logger.warning(
                "HeadObject returned 403 for a not-yet-copied object; the bucket "
                "credentials likely lack s3:ListBucket (so the store can't answer "
                "'not found'). Proceeding to upload anyway. Grant s3:ListBucket to "
                "enable skip-on-rerun and silence this."
            )
        return False


@dataclass
class BackfillSummary:
    """Outcome of a backfill run, for the final log line / exit code."""

    copied: int = 0
    skipped: int = 0
    failed: int = 0
    hash_mismatches: int = 0
    failed_keys: list[str] = field(default_factory=list)
    # True when another worker held the advisory lock, so this run did nothing.
    already_running: bool = False


def backfill_guild_dir(
    guild_dir: Path,
    meta: dict[str, tuple[str | None, str | None]],
    dest: StorageBackend,
    summary: BackfillSummary,
    *,
    guild_id: int,
    dry_run: bool,
    arriving: frozenset[str] = frozenset(),
) -> None:
    """Copy one guild's local blobs into ``dest`` (S3). Pure of the DB.

    ``meta`` maps filename -> (content_type, content_hash) from the ``uploads``
    rows; ``arriving`` names the files still arriving in parts, which are left
    for a later run. Updates ``summary`` in place. Idempotent: an object already in ``dest``
    is skipped; a content_hash mismatch is treated as a failure (the blob is NOT
    copied) so corruption isn't propagated. ``dry_run`` skips only the write — the
    ``exists`` check still runs against ``dest``, so a dry run reports the real
    remaining work rather than re-counting already-copied files.
    """
    for path in sorted(guild_dir.iterdir()):
        if not path.is_file():
            continue
        key = path.name
        # Copied now, a file still arriving would leave a cut-short copy that
        # a later run skips.
        if key in arriving:
            continue
        content_type, content_hash = meta.get(key, (None, None))
        if content_type is None:
            content_type = mimetypes.guess_type(key)[0]
        label = f"guild_{guild_id}/{key}"
        try:
            if _object_exists(dest, key):
                summary.skipped += 1
                continue
            data = path.read_bytes()
            if content_hash and hashlib.sha256(data).hexdigest() != content_hash:
                logger.warning("content_hash mismatch for %s — not copying", label)
                summary.hash_mismatches += 1
                summary.failed += 1
                summary.failed_keys.append(label)
                continue
            if dry_run:
                logger.info(
                    "[dry-run] would copy %s (%d bytes, %s)",
                    label,
                    len(data),
                    content_type,
                )
                summary.copied += 1
                continue
            dest.write(key, data, content_type=content_type)
            summary.copied += 1
        except Exception:  # noqa: BLE001 — one bad blob must not abort the run
            logger.exception("failed to back up %s", label)
            summary.failed += 1
            summary.failed_keys.append(label)


async def _guild_upload_meta(
    conn: AsyncConnection, schema: str
) -> dict[str, tuple[str | None, str | None]]:
    """filename -> (content_type, content_hash) for a guild's uploads, or {} if
    the schema/table is absent."""
    exists = (
        await conn.execute(
            text(
                "SELECT 1 FROM pg_tables "
                "WHERE schemaname = :s AND tablename = 'uploads'"
            ),
            {"s": schema},
        )
    ).scalar()
    if exists is None:
        return {}
    rows = (
        await conn.execute(
            # schema = guild_schema_name(int), a digits-only identifier.
            text(
                f'SELECT filename, content_type, content_hash FROM "{schema}".uploads'  # noqa: S608
            )
        )
    ).all()
    return {row[0]: (row[1], row[2]) for row in rows if row[0]}


async def _guild_arriving(conn: AsyncConnection, schema: str) -> frozenset[str]:
    """The stored names of a guild's resumable uploads not yet taken."""
    rows = await conn.execute(
        # schema = guild_schema_name(int), a digits-only identifier.
        text(f'SELECT staging_key FROM "{schema}".pending_uploads')  # noqa: S608
    )
    return frozenset(rows.scalars().all())


async def backfill_uploads_to_s3(
    *,
    dry_run: bool = False,
    on_progress: "Callable[[BackfillSummary], Awaitable[None]] | None" = None,
) -> BackfillSummary:
    """Copy every guild's local blobs into S3. See module docstring.

    ``on_progress`` (if given) is awaited after each guild with the running
    summary, so a caller can persist a heartbeat + live counts to shared state.
    """
    global _warned_head_forbidden
    _warned_head_forbidden = False
    summary = BackfillSummary()
    root = Path(settings.UPLOADS_DIR)
    # Snapshot the storage config once for the whole run: a settings change
    # mid-backfill must not send later guilds to a different bucket. One client,
    # one bucket/prefix scheme, for every guild.
    cfg = storage_config.current_storage_config()
    if cfg.backend != "s3" or not cfg.bucket:
        raise ValueError("backfill requires an S3 backend with S3_BUCKET configured")
    client = build_s3_client(cfg)
    # The lock and the guild list are read on a platform connection, and each
    # guild's uploads on a system session from that guild's cohort.
    async with db_session.system_engine.connect() as conn:
        # One backfill at a time across every worker/process: the in-process
        # status guard sees only this one. The lock is held for this
        # connection; a second worker that can't take it backs off rather than
        # double-copying every guild.
        if not await advisory_lock(
            conn, LockNamespace.UPLOAD_BACKFILL, wait=False, xact=False
        ):
            logger.warning("backfill skipped: another run holds the advisory lock")
            summary.already_running = True
            return summary
        try:
            guild_ids = (
                (await conn.execute(text("SELECT id FROM public.guilds ORDER BY id")))
                .scalars()
                .all()
            )
            for gid in guild_ids:
                guild_dir = root / f"guild_{gid}"
                if not guild_dir.is_dir():
                    continue
                async with cohorts.system_session(gid) as session:
                    await db_session.set_rls_context(session, SystemGuild(gid))
                    guild_conn = await session.connection()
                    schema = guild_schema_name(gid)
                    meta = await _guild_upload_meta(guild_conn, schema)
                    arriving = await _guild_arriving(guild_conn, schema)
                # Always a real S3 backend, even on a dry run, so the exists() skip
                # check reflects what's already in the bucket.
                dest = S3Storage(
                    bucket=cfg.bucket,
                    client=client,
                    prefix=f"guild_{int(gid)}/",
                )
                backfill_guild_dir(
                    guild_dir,
                    meta,
                    dest,
                    summary,
                    guild_id=gid,
                    dry_run=dry_run,
                    arriving=arriving,
                )
                if on_progress is not None:
                    await on_progress(summary)
        finally:
            # Roll back first, so the unlock below runs in a fresh transaction.
            # The advisory lock is session-scoped and survives the rollback.
            await conn.rollback()
            await advisory_unlock(conn, LockNamespace.UPLOAD_BACKFILL)
    return summary


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(
        description="Copy existing local uploads into the configured S3 bucket."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be copied (checking the bucket for already-present "
        "objects) without writing",
    )
    args = parser.parse_args()
    if not settings.S3_BUCKET:
        raise SystemExit(
            "S3_BUCKET (and the other S3_* settings) must point at your object "
            "store to run the backfill (a dry run queries the bucket too)."
        )
    summary = asyncio.run(backfill_uploads_to_s3(dry_run=args.dry_run))
    logger.info(
        "backfill complete: copied=%d skipped=%d failed=%d hash_mismatches=%d",
        summary.copied,
        summary.skipped,
        summary.failed,
        summary.hash_mismatches,
    )
    if summary.failed:
        logger.error(
            "backfill had %d failure(s): %s", summary.failed, summary.failed_keys
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
