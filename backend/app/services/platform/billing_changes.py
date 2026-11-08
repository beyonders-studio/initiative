"""The change log billing reads (``POST /api/v1/billing/changes``).

What billing needs to know about each community is written to
``public.billing_changes`` by the transaction that changed it, through the
definer function ``public.billing_change_row`` (migration ``20261021_0532``):

* by the triggers on ``guilds``: ``community.created`` (with its owner as
  ``owner_user_ref``: the first superadmin, who is the person a community is
  made for, even when staff made it for them, and whoever made it when it has
  none), ``community.deleted``, ``community.restored``,
  ``community.suspended``, ``community.unsuspended`` and ``community.purged``;
* by the triggers on ``guild_memberships``: ``community.members`` with
  ``members`` and ``guests``, totals, once per community a statement touches,
  counted when the change is served (:func:`page`) rather than written;
* by the triggers on ``plugin_installs``: ``plugin.installed`` and
  ``plugin.uninstalled`` with ``listing_uid`` (an erase follows an uninstall,
  so it's told by the uninstall);
* by the trigger on ``plugin_usage``: ``plugin.usage`` with ``listing_uid``,
  ``meter``, ``period`` (``YYYY-MM``, UTC) and ``quantity``, the meter's
  running total for the month;
* by :func:`storage_moved`, from the system engine: ``community.storage`` with
  ``bytes``, the stored total, at most once per community per
  :data:`STORAGE_WINDOW_SECONDS`, since a row per upload would be too chatty.

A new kind is a trigger (or a call to ``billing_change_row`` on the system
engine) plus a line in billing's ``billing/sync/changes.py``. Every count is a
total, never an increment, so a row read twice changes nothing.

**The cursor never skips a row.** A row's ``xid`` is its transaction's id, and
:func:`page` serves only rows whose transaction is older than the oldest one
still running (``pg_snapshot_xmin``), in ``(xid, id)`` order. Every row it
hasn't served yet belongs to a transaction that will end with a larger
``xid`` than the cursor, so a transaction that commits late is served late
rather than never, and one that aborts left no row to wait for. The cursor is
``"{xid}.{id}"``, opaque to billing.

Rows name the community by billing's reference: captured when the row was
written if it had one (a purge's always does, since the references go after
the row), or resolved here, minting on first use. A row for a community that
no longer exists and never had a reference is skipped: billing never knew it.
A plug-in row for a listing no package names terms for is skipped too: there
is nothing for billing to bill.

A committed row is announced on :data:`CHANNEL`, and each process that hears
it sends billing one ping (:func:`hint`), collapsed over :data:`PING_DEBOUNCE_SECONDS`.
A missed ping costs latency only: billing pulls on a schedule too.

Retention: :data:`RETENTION` (:func:`prune`, by the jti janitor).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import post_commit

logger = logging.getLogger(__name__)

CHANNEL = "billing_changes"
RETENTION = timedelta(days=30)
STORAGE_WINDOW_SECONDS = 30.0
PING_DEBOUNCE_SECONDS = 1.0

_PLUGIN_KINDS = frozenset({"plugin.installed", "plugin.uninstalled", "plugin.usage"})


class CursorInvalid(ValueError):
    """A cursor this deployment didn't hand out."""


def _decode(cursor: str | None) -> tuple[int, int]:
    if not cursor:
        return (-1, -1)
    try:
        xid, _, row = cursor.partition(".")
        return (int(xid), int(row))
    except ValueError:
        raise CursorInvalid(cursor) from None


def _encode(xid: int, row: int) -> str:
    return f"{xid}.{row}"


async def page(
    after: str | None, limit: int
) -> tuple[list[dict[str, Any]], str | None]:
    """The changes after ``after``, and the cursor to read on from."""
    from app.db.session import SystemSessionLocal

    xid, row_id = _decode(after)
    async with SystemSessionLocal() as session:
        rows = (
            await session.exec(
                text(
                    """
                    SELECT id, xid, guild_id, kind, community_ref, data
                      FROM public.billing_changes
                     WHERE xid < (pg_snapshot_xmin(pg_current_snapshot())::text)::bigint
                       AND (xid, id) > (:xid, :id)
                     ORDER BY xid, id
                     LIMIT :n
                    """
                ),
                params={"xid": xid, "id": row_id, "n": limit},
            )
        ).all()
        alive = {
            r[0]
            for r in (
                await session.exec(
                    text("SELECT id FROM public.guilds WHERE id = ANY(:ids)"),
                    params={"ids": list({r.guild_id for r in rows})},
                )
            ).all()
        }
        # The counts are read now, committed, never as the change was written:
        # a join in flight beside another sees only its own row, and the log
        # is ordered by transaction rather than by commit. The newest change
        # billing reads for a community so carries what it holds as served.
        counted = list({r.guild_id for r in rows if r.kind == "community.members"})
        members = (
            {
                r[0]: {"members": int(r[1]), "guests": int(r[2])}
                for r in (
                    await session.exec(
                        text(
                            """
                        SELECT guild_id,
                               count(*) FILTER (WHERE guest_until IS NULL),
                               count(*) FILTER (WHERE guest_until > now())
                          FROM public.guild_memberships
                         WHERE guild_id = ANY(:ids)
                         GROUP BY guild_id
                        """
                        ),
                        params={"ids": counted},
                    )
                ).all()
            }
            if counted
            else {}
        )
        created = [r.guild_id for r in rows if r.kind == "community.created"]
        owners = (
            {
                r[0]: r[1]
                for r in (
                    await session.exec(
                        text(
                            """
                        SELECT DISTINCT ON (guild_id) guild_id, user_id
                          FROM public.guild_memberships
                         WHERE guild_id = ANY(:ids) AND role = 'superadmin'
                         ORDER BY guild_id, joined_at, user_id
                        """
                        ),
                        params={"ids": created},
                    )
                ).all()
            }
            if created
            else {}
        )
    if not rows:
        return [], after
    changes = await _served(rows, alive, owners, members)
    last = rows[-1]
    return changes, _encode(int(last.xid), int(last.id))


async def _served(
    rows: list[Any],
    alive: set[int],
    owners: dict[int, int],
    members: dict[int, dict[str, int]],
) -> list[dict[str, Any]]:
    from app.models.platform.identity_ref import IdentityEntity
    from app.services.marketplace.plugin_entitlements import listing_terms
    from app.services.platform.identity_refs import billing_ref

    refs: dict[int, str] = {}
    terms: dict[str, bool] = {}
    out: list[dict[str, Any]] = []
    for row in rows:
        data: dict[str, Any] = dict(row.data or {})
        if row.kind == "community.members":
            data = dict(members.get(row.guild_id, {"members": 0, "guests": 0}))
        if row.kind in _PLUGIN_KINDS:
            uid = str(data.get("listing_uid") or "")
            if uid not in terms:
                terms[uid] = await listing_terms(uid) is not None
            if not terms[uid]:
                continue
        ref = row.community_ref
        if ref is None:
            if row.guild_id not in alive:
                continue
            if row.guild_id not in refs:
                refs[row.guild_id] = await billing_ref(
                    IdentityEntity.guild, row.guild_id
                )
            ref = refs[row.guild_id]
        made_by = data.pop("owner_user_id", None)
        owner = (
            owners.get(row.guild_id, made_by)
            if row.kind == "community.created"
            else None
        )
        if owner is not None:
            data["owner_user_ref"] = await billing_ref(IdentityEntity.user, int(owner))
        out.append({"id": int(row.id), "kind": row.kind, "community_ref": ref, **data})
    return out


async def prune(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Delete rows past :data:`RETENTION`. On the system engine."""
    cutoff = (now or datetime.now(UTC)) - RETENTION
    result = await session.exec(
        text("DELETE FROM public.billing_changes WHERE occurred_at < :cutoff"),
        params={"cutoff": cutoff},
    )
    await session.commit()
    return int(result.rowcount or 0)


# --- stored bytes ---------------------------------------------------------------

#: Communities whose storage report is already on its way, in this process.
_storage_pending: set[int] = set()


def storage_moved(session: AsyncSession, guild_id: int | None = None) -> None:
    """Once ``session`` commits: report the community's stored bytes to the
    change log, coalesced. ``guild_id`` defaults to the community the session
    is routed to."""
    from app.db.session import routed_guild_id
    from app.services.platform.billing import billing_managed

    if not billing_managed():
        return
    target = guild_id if guild_id is not None else routed_guild_id(session)
    if target is None:
        return
    post_commit.after_commit(
        session, lambda: _report_storage_soon(target), key=("billing-storage", target)
    )


def _report_storage_soon(guild_id: int) -> None:
    if guild_id in _storage_pending:
        return
    _storage_pending.add(guild_id)
    post_commit.spawn(_report_storage(guild_id), cancel_on_settle=True)


async def _report_storage(guild_id: int) -> None:
    from app.db.session import SystemSessionLocal
    from app.services.tenant.attachments import get_guild_storage_usage

    try:
        await asyncio.sleep(STORAGE_WINDOW_SECONDS)
    finally:
        _storage_pending.discard(guild_id)
    try:
        stored = await get_guild_storage_usage(guild_id)
        async with SystemSessionLocal() as session:
            await session.exec(
                text(
                    "SELECT public.billing_change_row("
                    "CAST(:g AS integer), 'community.storage', CAST(:d AS jsonb))"
                ),
                params={"g": guild_id, "d": json.dumps({"bytes": int(stored)})},
            )
            await session.commit()
    except Exception:
        # Billing's reconciliation reads usage too; a lost report costs latency.
        logger.exception("billing: storage report for guild %s not written", guild_id)


# --- the ping ------------------------------------------------------------------

_ping_pending = False


async def hint(_payload: str) -> None:
    """A committed transaction wrote a change row. Registered on
    :data:`CHANNEL`: tell billing, once per :data:`PING_DEBOUNCE_SECONDS`."""
    global _ping_pending
    if _ping_pending:
        return
    _ping_pending = True
    post_commit.spawn(_ping_after_debounce(), cancel_on_settle=True)


async def _ping_after_debounce() -> None:
    global _ping_pending
    from app.services.platform import billing_ping

    try:
        await asyncio.sleep(PING_DEBOUNCE_SECONDS)
    finally:
        _ping_pending = False
    await billing_ping.nudge()
