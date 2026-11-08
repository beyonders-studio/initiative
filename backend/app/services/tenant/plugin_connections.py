"""Per-member connections to an installed plug-in's vendor, and how they end.

A member connects their own account, an admin governs who may, and every way
the relationship can end deletes the stored values and records a revocation.
That last part is the reason this module is one place rather than a helper
beside each caller: leaving a guild, being removed from it, being revoked or
blocked, deleting an account, uninstalling the plug-in and deleting the guild are
six different stories with one requirement in common, and the way that
requirement gets missed is each story implementing it separately.

Every deletion path here goes through :func:`_delete_rows`, which is what makes
"the values are gone and the plug-in has been told" a property of the module rather
than of each caller remembering.

The ``connection_ref`` a plug-in addresses a credential by is minted once per
(install, connection, member), when the member's first flow completes, and
reused across reconnects, so a member's history stays one row. It is random
rather than derived from anything about the person, which is what keeps the
same member uncorrelated across plug-ins and guilds.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.clock import utcnow
from app.db.cohorts import as_system
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.guild_plugin_user_connection import GuildPluginUserConnection
from app.models.tenant.plugin_connection_secret import PluginConnectionSecret
from app.services.tenant.plugin_config import mint_connection_ref
from app.services.tenant.plugin_revocation import queue_revocations_for_rows

__all__ = [
    "block_member_connection",
    "connection_tallies",
    "delete_guild_connections",
    "delete_member_connections",
    "delete_plugin_connections",
    "disconnect",
    "get_connection",
    "is_blocked",
    "list_member_connections",
    "list_plugin_connections",
    "revoke_all",
    "unblock_member_connection",
]


# --- reading ----------------------------------------------------------------


async def get_connection(
    session: AsyncSession, *, plugin_id: int, connection_id: str, user_id: int
) -> GuildPluginUserConnection | None:
    """One member's row for one connection, if it exists.

    Under the table's policies this returns the caller's row when the caller is
    the member, and any member's row when the caller holds the community's seat
    — the same query either way, because the gate is in the database rather
    than in a branch here.
    """
    return (
        await session.exec(
            select(GuildPluginUserConnection).where(
                GuildPluginUserConnection.plugin_id == plugin_id,
                GuildPluginUserConnection.connection_id == connection_id,
                GuildPluginUserConnection.user_id == user_id,
            )
        )
    ).first()


async def list_member_connections(
    session: AsyncSession, *, plugin_id: int, user_id: int
) -> list[GuildPluginUserConnection]:
    """Every connection this member holds for one install."""
    return list(
        (
            await session.exec(
                select(GuildPluginUserConnection)
                .where(
                    GuildPluginUserConnection.plugin_id == plugin_id,
                    GuildPluginUserConnection.user_id == user_id,
                )
                .order_by(GuildPluginUserConnection.connection_id)
            )
        ).all()
    )


async def list_plugin_connections(
    session: AsyncSession,
    *,
    plugin_id: int,
    user_ids: Sequence[int] | None = None,
) -> list[GuildPluginUserConnection]:
    """Every member's connection for one install — the admin's Members view.
    ``user_ids`` narrows it to those members, one page of that view.

    Returns only the caller's own rows unless the session is routed as a guild
    admin; the endpoint that offers this requires one.
    """
    stmt = select(GuildPluginUserConnection).where(
        GuildPluginUserConnection.plugin_id == plugin_id
    )
    if user_ids is not None:
        stmt = stmt.where(GuildPluginUserConnection.user_id.in_(user_ids))
    return list(
        (
            await session.exec(
                stmt.order_by(
                    GuildPluginUserConnection.connection_id,
                    GuildPluginUserConnection.user_id,
                )
            )
        ).all()
    )


async def connection_tallies(
    session: AsyncSession, *, plugin_id: int
) -> dict[str, tuple[int, int]]:
    """Per connection of one install: how many members are connected, and how
    many are blocked."""
    blocked = GuildPluginUserConnection.blocked_at.is_not(None)
    rows = await session.exec(
        select(
            GuildPluginUserConnection.connection_id,
            func.count().filter(~blocked),
            func.count().filter(blocked),
        )
        .where(GuildPluginUserConnection.plugin_id == plugin_id)
        .group_by(GuildPluginUserConnection.connection_id)
    )
    return {
        connection_id: (connected, blocked_count)
        for connection_id, connected, blocked_count in rows.all()
    }


# --- what a connection holds -----------------------------------------------


async def load_connection_secrets(
    session: AsyncSession, row: GuildPluginUserConnection
) -> dict[str, Any]:
    """One connection's secret values, ``{key: ciphertext}``, tokens included.

    Read on ``session``, which only the member it belongs to and the system
    engine reach. No row reads as ``{}``.
    """
    stored = (
        await session.exec(
            select(PluginConnectionSecret.secrets).where(
                PluginConnectionSecret.connection_row_id == row.id
            )
        )
    ).first()
    return dict(stored or {})


async def connection_secrets_of(
    session: AsyncSession, row_ids: Sequence[int]
) -> dict[int, dict[str, Any]]:
    """The secret values of several connections, by row id, read as the
    platform (:func:`app.db.cohorts.as_system`) whoever is asking."""
    if not row_ids:
        return {}
    async with as_system(session) as system:
        rows = await system.exec(
            select(PluginConnectionSecret).where(
                PluginConnectionSecret.connection_row_id.in_(list(row_ids))  # type: ignore[attr-defined]
            )
        )
        return {row.connection_row_id: dict(row.secrets or {}) for row in rows.all()}


async def store_connection_secrets(
    session: AsyncSession, row: GuildPluginUserConnection, secrets: dict[str, Any]
) -> None:
    """Replace one connection's secret values; an empty map removes its row.

    The trigger on ``plugin_connection_secrets`` rewrites the connection's
    ``secret_fields`` in the same statement. ``row`` is flushed first so it
    has an id.
    """
    session.add(row)
    await session.flush()
    if secrets:
        await session.exec(
            pg_insert(PluginConnectionSecret)
            .values(connection_row_id=row.id, secrets=secrets)
            .on_conflict_do_update(
                index_elements=[PluginConnectionSecret.connection_row_id],
                set_={"secrets": secrets},
            )
        )
    else:
        await session.exec(
            sa_delete(PluginConnectionSecret).where(
                PluginConnectionSecret.connection_row_id == row.id
            )
        )
    await session.refresh(row, attribute_names=["secret_fields"])


# --- ending it --------------------------------------------------------------


async def _delete_rows(
    session: AsyncSession,
    rows: Sequence[GuildPluginUserConnection],
    *,
    reason: str,
    installs: dict[int, tuple[str, dict[str, Any] | None]],
) -> int:
    """Delete stored credentials and record the matching revocations.

    The single choke point for ending per-member access: an intent carrying
    each row's sealed tokens is queued before the row goes, so no caller can
    delete values without the grant being ended at the vendor. ``installs`` is
    as :func:`~app.services.tenant.plugin_revocation.queue_revocations_for_rows`
    takes it.
    """
    if not rows:
        return 0
    await queue_revocations_for_rows(session, rows, reason=reason, installs=installs)
    for row in rows:
        await session.delete(row)
    return len(rows)


async def disconnect(
    session: AsyncSession,
    *,
    plugin: GuildPlugin,
    connection_id: str,
    user_id: int,
    reason: str = "disconnected",
    definition: dict[str, Any] | None = None,
) -> int:
    """A member's own connection, or one an admin is ending for them.

    ``definition`` is the one the connection was made under, when the install
    has just moved off it.
    """
    row = await get_connection(
        session, plugin_id=plugin.id, connection_id=connection_id, user_id=user_id
    )
    if row is None:
        return 0
    return await _delete_rows(
        session,
        [row],
        reason=reason,
        installs={
            plugin.id: (
                plugin.listing_uid,
                definition if definition is not None else plugin.definition,
            )
        },
    )


async def block_member_connection(
    session: AsyncSession,
    *,
    plugin: GuildPlugin,
    connection_id: str,
    user_id: int,
    blocked_by_id: int,
) -> GuildPluginUserConnection:
    """Revoke a member's connection and stop them making another.

    The row survives as a tombstone holding ``blocked_at`` and who acted, which
    is what distinguishes "this person should no longer reach that system
    through us" from a revocation they could simply undo by clicking Connect
    again. The values go exactly as they do on any other revocation — a block
    that left the credential in place would be a worse outcome than a plain
    revoke, not a stronger one.

    The values are the member's own to reach, so the platform does the whole
    block, in one transaction that holds the row from before it reads them: a
    flow finishing at the same moment either lands first and has its values
    revoked with the rest, or finds the row blocked. The revocation goes once
    that transaction commits.
    """
    async with as_system(session) as system:
        row = (
            await system.exec(
                select(GuildPluginUserConnection)
                .where(
                    GuildPluginUserConnection.plugin_id == plugin.id,
                    GuildPluginUserConnection.connection_id == connection_id,
                    GuildPluginUserConnection.user_id == user_id,
                )
                .with_for_update()
            )
        ).first()
        if row is None:
            row = GuildPluginUserConnection(
                plugin_id=plugin.id,
                connection_id=connection_id,
                user_id=user_id,
                connection_ref=mint_connection_ref(),
            )
        else:
            await queue_revocations_for_rows(
                system,
                [row],
                reason="blocked",
                installs={plugin.id: (plugin.listing_uid, plugin.definition)},
            )
        row.status = "blocked"
        row.config = {}
        row.account_label = None
        row.blocked_at = utcnow()
        row.blocked_by_id = blocked_by_id
        row.updated_at = utcnow()
        await store_connection_secrets(system, row, {})
        return row


async def unblock_member_connection(
    session: AsyncSession, *, plugin: GuildPlugin, connection_id: str, user_id: int
) -> bool:
    """Lift a block. The tombstone goes; the member may connect again."""
    row = await get_connection(
        session, plugin_id=plugin.id, connection_id=connection_id, user_id=user_id
    )
    if row is None or row.blocked_at is None:
        return False
    # Nothing to revoke — a blocked row holds no values — so the row is simply
    # removed and the member starts clean if they choose to reconnect.
    await session.delete(row)
    return True


async def revoke_all(
    session: AsyncSession, *, plugin: GuildPlugin, reason: str = "revoke_all"
) -> int:
    """Every member's connection for one install, at once.

    For a suspected plug-in or vendor compromise: it ends access without tearing
    down the install, so an admin does not have to choose between reacting fast
    and keeping the plug-in's configuration.
    """
    rows = [
        row
        for row in await list_plugin_connections(session, plugin_id=plugin.id)
        if row.blocked_at is None
    ]
    return await _delete_rows(
        session,
        rows,
        reason=reason,
        installs={plugin.id: (plugin.listing_uid, plugin.definition)},
    )


async def delete_plugin_connections(
    session: AsyncSession, *, plugin: GuildPlugin, reason: str = "uninstalled"
) -> int:
    """Everything for one install, blocked tombstones included.

    Uninstalling ends the plug-in's access completely, so a tombstone recording that
    somebody was blocked from a plug-in that is no longer installed has nothing
    left to constrain.
    """
    rows = await list_plugin_connections(session, plugin_id=plugin.id)
    return await _delete_rows(
        session,
        rows,
        reason=reason,
        installs={plugin.id: (plugin.listing_uid, plugin.definition)},
    )


async def delete_member_connections(
    session: AsyncSession, *, user_id: int, reason: str
) -> int:
    """Every connection one member holds in the routed guild.

    For the paths where the person's relationship with the guild ends — leaving,
    being removed, deactivating or deleting their account. Their connections in
    other guilds are untouched, because those relationships have not ended.

    The session must already be routed into the guild. Whoever ends the
    relationship — a plain admin among them — need not reach the member's
    credentials, so the platform deletes them, in a transaction of its own, and
    sends the revocations once that commits. Blocked tombstones are left
    alone: a block outlives a membership, so somebody removed and later
    re-invited does not come back with the block quietly lifted.
    """
    async with as_system(session) as system:
        rows = list(
            (
                await system.exec(
                    select(GuildPluginUserConnection).where(
                        GuildPluginUserConnection.user_id == user_id,
                        GuildPluginUserConnection.blocked_at.is_(None),
                    )
                )
            ).all()
        )
        return await _delete_rows(
            system,
            rows,
            reason=reason,
            installs=await _installs_by_plugin_id(
                system, plugin_ids={r.plugin_id for r in rows}
            ),
        )


async def delete_guild_connections(
    session: AsyncSession, *, reason: str = "guild_deleted"
) -> int:
    """Every connection in the routed guild, before the guild goes.

    Dropping the schema would remove the rows without anyone being told, which
    would leave vendor grants outliving the guild that authorized them. This
    runs first so each plug-in is asked to let go.
    """
    rows = list((await session.exec(select(GuildPluginUserConnection))).all())
    return await _delete_rows(
        session,
        rows,
        reason=reason,
        installs=await _installs_by_plugin_id(
            session, plugin_ids={r.plugin_id for r in rows}
        ),
    )


async def _installs_by_plugin_id(
    session: AsyncSession, *, plugin_ids: set[int]
) -> dict[int, tuple[str, dict[str, Any] | None]]:
    """Which listing each install came from and the definition it pinned, for
    the revocations of its connections."""
    if not plugin_ids:
        return {}
    rows = (
        await session.exec(
            select(
                GuildPlugin.id, GuildPlugin.listing_uid, GuildPlugin.definition
            ).where(GuildPlugin.id.in_(plugin_ids))
        )
    ).all()
    return {
        row[0]: (row[1], dict(row[2]) if row[2] is not None else None) for row in rows
    }


def is_blocked(row: Any | None) -> bool:
    """Whether a member has been stopped from connecting this one."""
    return row is not None and row.blocked_at is not None
