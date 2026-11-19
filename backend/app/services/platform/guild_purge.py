"""Destroy guilds whose retention window has run out.

Deleting a guild no longer destroys it: it moves to ``CommunityStatus.deleted``
and keeps everything — the shared rows, the ``guild_<id>`` schema, the stored
blobs — so a platform operator can put the community back. This worker is what
eventually does the destroying, in two steps. First its plug-ins are asked to
erase what they hold about it: an ``erase`` is queued for each plug-in holding
references there, behind whatever that plug-in already has waiting, and
``guilds.purge_started_at`` is stamped, after which the community can no
longer be restored or moved and no plug-in is given a new name in it. Then,
on a later pass, once every hook to its plug-ins has been answered or given up
on (``community_hooks``, whose sweep keeps sending them meanwhile), it does
exactly what the delete used to do inline: remove the shared guild row (whose
``ON DELETE CASCADE`` clears the roster), forget the identities its plug-ins
knew it and its members by, then drop the schema and purge the blobs. A
plug-in that does not answer therefore holds the purge for as long as the
hooks are retried, about four days. Each pass then reclaims any ``guild_<id>`` schema
whose row is already gone — a teardown that deleted the row but did not finish
dropping the schema, here or where a guild's creation was rolled back.

Before any of that, each pass deletes the communities whose hold has run out:
one left ``on_hold`` for longer than the deployment's hold window moves to
``deleted`` exactly as a deletion from its danger zone would, and the
retention window then starts like any other. It also uninstalls each plug-in
install left ``deleted`` for :data:`~app.services.platform.retention.PLUGIN_INSTALL_DELETION_DAYS`,
in its community, as an admin's uninstall would and without an erase.

Polled by ``background_tasks.Loop`` once an hour on ``SystemSessionLocal``
(the ``app_admin`` login). It works on ``public.guilds``; the one thing it does
inside a guild's schema, deleting a held community's plug-in connections, runs on
a system session from that community's cohort. The schema is dropped wholesale
on the provisioning engine.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import text
from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.db import cohorts, post_commit
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db.guild_migrations import GUILD_SCHEMA_REGEX
from app.db.holds import refuse_while_held
from app.db.plugin_tools import provisioned_tools
from app.db.request_context import SystemGuild, Unattributed
from app.db.schema_provisioning import deprovision_guild, provision_community_tools
from app.db.session import SystemSessionLocal, set_rls_context
from app.db.soft_delete_filter import select_including_deleted
from app.db.tool_rows import ToolRow
from app.models.platform.guild import CommunityStatus, Guild
from app.models.platform.plugin_community_hook import PluginCommunityHook
from app.models.platform.plugin_install import (
    PluginInstall,
    PluginInstallClaim,
    PluginInstallStatus,
)
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.initiative import InitiativeRule
from app.models.tenant.resource_grant import ResourceGrant
from app.services import audit as audit_service
from app.services.marketplace import community_hooks, plugin_refs
from app.services.marketplace.tool_plugins import is_tool_plugin, tool_kinds
from app.services.platform import rules
from app.services.platform.retention import (
    COMMUNITY_DELETION,
    COMMUNITY_HOLD,
    PLUGIN_INSTALL_DELETION,
)

logger = logging.getLogger(__name__)


GUILD_PURGE_POLL_SECONDS = 3600


async def _end_plugin_connections(guild_id: int) -> AsyncSession:
    """Delete the community's plug-in connections, in its own schema, and
    commit. Returns the session, whose settling tells the plug-ins."""
    from app.services.tenant import plugin_connections as plugin_connections_service

    async with cohorts.system_session(guild_id) as guild_session:
        await set_rls_context(guild_session, SystemGuild(guild_id))
        await plugin_connections_service.delete_guild_connections(guild_session)
        await guild_session.commit()
    return guild_session


async def _delete_expired_hold(session: AsyncSession, guild: Guild, _days: int) -> None:
    """Delete one community whose hold has run out. Mirrors the danger-zone
    delete: its plug-ins let go, the status moves to ``deleted``, the seat is
    written to, and billing is told to read what happened.

    Runs in the transaction that claimed the row and commits it, so a hold
    lifted while the pass runs leaves the community exactly as it was. Its
    plug-in connections are deleted in its own schema first, under that claim,
    so a status write that fails leaves a held community without them, which
    the next pass deletes. Nobody asked for this deletion, so the roster stays
    whatever its size.
    """
    from app.services import email as email_service
    from app.services.platform import guilds as guilds_service

    guild_id = guild.id
    # The plug-ins are told once this commits, whatever happens below.
    guild_session = await _end_plugin_connections(guild_id)

    notice = await guilds_service.soft_delete_guild(
        session, guild, via="hold_expired", keep_roster=True
    )
    await session.commit()

    await email_service.announce_community_deleted(session, notice)
    # These live on other connections, so they go after the commit that made
    # the deletion real. What its plug-ins call the community is kept until the
    # purge, which tells them to erase it first.
    await post_commit.settle(guild_session)


async def delete_expired_holds(session: AsyncSession, *, now: datetime) -> int:
    """One pass of :data:`~app.services.platform.retention.COMMUNITY_HOLD`.
    Returns how many communities were deleted.

    Counted from ``status_changed_at``, which is stamped when a community is
    put on hold and not again while it stays there, so a hold written twice
    does not restart the clock.
    """
    return await COMMUNITY_HOLD.sweep(session, now=now, act=_delete_expired_hold)


async def _uninstall_deleted(
    session: AsyncSession, install: PluginInstall, _days: int
) -> None:
    """Uninstall one plug-in install whose deletion window has run out: in its
    community's own schema, on a system session from its cohort, without an
    erase, then drop its index row. An install already gone there leaves only
    the row to drop.

    Locks go install first, then its index row, the order the index sweep
    takes them in (``plugin_installs.reindex_community``): the sweep's claim
    on the row is let go, and the row is held again under the install's lock
    and uninstalled only if it is still deleted from the same moment.

    One staff also suspended there is removed without a word to it: nothing is
    queued for it, nothing is revoked at its vendor, and what waited in its
    queue for the community is discarded with the row.

    A tool plug-in goes with its tool (:func:`_purge_tool`), and, once its
    install is gone, its tables, with the community's rules rendered again
    without it, before its index row: a step that fails is taken again by the
    next sweep. While the platform holds any of its content the whole step
    waits for the next sweep."""
    from app.services.tenant import guild_plugins as guild_plugins_service
    from app.services.tenant.attachments import delete_blobs

    guild_id, install_id = install.guild_id, install.install_id
    listing_uid, deleted_at = install.listing_uid, install.status_changed_at
    suspended = install.suspended_at is not None
    public_id: str | None = None
    tool = True  # or an install an earlier sweep removed before its tables
    released: set[str] = set()
    await session.commit()
    async with cohorts.system_session(guild_id) as guild_session:
        await set_rls_context(guild_session, SystemGuild(guild_id))
        plugin = await guild_plugins_service.lock_install(guild_session, install_id)
        still = (
            await session.exec(
                select(PluginInstall)
                .where(
                    col(PluginInstall.guild_id) == guild_id,
                    col(PluginInstall.install_id) == install_id,
                    col(PluginInstall.status) == PluginInstallStatus.deleted.value,
                    col(PluginInstall.status_changed_at) == deleted_at,
                )
                .with_for_update()
            )
        ).one_or_none()
        if still is None:
            # Set back, or gone, since it was found due.
            await guild_session.rollback()
            await session.commit()
            return
        if plugin is not None:
            public_id = await guild_plugins_service.install_public_id(plugin)
            tool = is_tool_plugin(plugin.definition)
            if tool:
                released = await _purge_tool(guild_session, guild_id, plugin)
            await guild_plugins_service.uninstall_plugin(
                guild_session, plugin, actor_user_id=None, suspended=suspended
            )
        await guild_session.commit()
    delete_blobs(guild_id, released)
    if tool:
        await provision_community_tools(guild_id, uninstalled=listing_uid)
    if suspended and public_id is not None:
        await session.exec(
            delete(PluginCommunityHook).where(
                col(PluginCommunityHook.guild_id) == guild_id,
                col(PluginCommunityHook.public_id) == public_id,
                col(PluginCommunityHook.done_at).is_(None),
            )
        )
    for table in (PluginInstall, PluginInstallClaim):
        await session.exec(
            delete(table).where(
                col(table.guild_id) == guild_id, col(table.install_id) == install_id
            )
        )
    await session.commit()
    await post_commit.settle(guild_session)


async def _purge_tool(
    session: AsyncSession, guild_id: int, plugin: GuildPlugin
) -> set[str]:
    """Purge a tool plug-in's rows as the trash purges a tool's (refused
    while the platform holds any of them), then the grants and rules naming
    its kinds, which a later install's tables would otherwise meet. Returns
    the stored names to delete once it commits."""
    from app.services.tenant.soft_delete import hard_purge_entities

    tools = await provisioned_tools(guild_id)
    kinds = tool_kinds(plugin.definition, listing_uid=plugin.listing_uid)
    tool = tools.by_kind[kinds[0]]
    rows = (await session.exec(select_including_deleted(tool.table.c.id))).all()
    released = await hard_purge_entities(
        session, [ToolRow(tool.table, {"id": row_id}) for row_id in rows], tools=tools
    )
    await session.exec(
        delete(ResourceGrant).where(col(ResourceGrant.resource_type).in_(kinds))
    )
    await session.exec(
        delete(InitiativeRule).where(
            col(InitiativeRule.install_id).is_(None),
            col(InitiativeRule.key).contains(tool.kind, autoescape=True),
        )
    )
    return released


async def uninstall_deleted_plugins(session: AsyncSession, *, now: datetime) -> int:
    """One pass of :data:`~app.services.platform.retention.PLUGIN_INSTALL_DELETION`.
    Returns how many installs were uninstalled."""
    return await PLUGIN_INSTALL_DELETION.sweep(session, now=now, act=_uninstall_deleted)


async def _destroy(session: AsyncSession, guild: Guild, days: int) -> bool:
    """Purge one guild whose window has run out: :func:`_remove`.

    The row goes in the transaction that claimed it, recorded and committed:
    that is the reliable part, and it is what makes the guild gone. The schema
    drop and blob purge follow; if they fail, :func:`reclaim_orphaned_guilds`
    drops the schema on the next pass, whereas a failed cleanup that rolled
    back the row would leave the guild due for purge forever.
    """
    await _refuse_while_held(session, guild.id)
    return await _remove(session, guild.id, days)


async def _refuse_while_held(session: AsyncSession, guild_id: int) -> None:
    """Held content keeps its community: the deletion waits, and the sweep
    tries again once the platform has released it (app.db.holds). Taken
    under the lock a hold is placed under, held until ``session`` commits, so
    a hold either landed before the check or finds the community gone."""
    await advisory_lock(session, LockNamespace.CONTENT_HOLDS, guild_id)
    await refuse_while_held(guild_id)


async def _remove(session: AsyncSession, guild_id: int, days: int | None) -> bool:
    """One step of a purge, committed. Returns whether the community is gone.

    Its plug-ins are asked first, while the community still has its row and
    the references to name it by: the purge is marked begun, the community
    marked deleted if it is not already, and an ``erase``
    queued for each plug-in holding references
    (``community_hooks.queue_purge_erases``). The row is deleted only on a pass
    that finds no hook to its plug-ins unfinished, recorded in the same
    transaction; the references, schema and blobs follow it.
    """
    guild = (
        await session.exec(
            select(Guild)
            .where(Guild.id == guild_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if guild is None:
        await session.commit()
        return True
    if guild.purge_started_at is None:
        now = datetime.now(UTC)
        guild.purge_started_at = now
        if guild.status != CommunityStatus.deleted.value:
            # Closed to everybody while it waits on its plug-ins, as a deleted
            # community is: a community destroyed straight away (a demo's)
            # may come here still live.
            guild.status = CommunityStatus.deleted.value
            guild.status_changed_at = now
        session.add(guild)
        await session.flush()
    await community_hooks.queue_purge_erases(session, guild_id=guild_id)
    if await community_hooks.hooks_unfinished(session, guild_id=guild_id):
        await session.commit()
        logger.info("guild purge: guild %s waits for its plug-ins to answer", guild_id)
        return False
    await session.exec(delete(Guild).where(Guild.id == guild_id))
    await audit_service.record(
        session,
        event_type=AuditEventType.GUILD_PURGED,
        actor_user_id=None,
        guild_id=guild_id,
        target_type="guild",
        target_id=guild_id,
        detail={"retention_days": days},
    )
    await session.commit()

    # These live on other connections, so they go after the commit that made
    # the purge real.
    await plugin_refs.forget_guild(guild_id=guild_id)
    try:
        await deprovision_guild(guild_id)
    except Exception:
        logger.exception(
            "guild purge: schema/blob cleanup for guild %s failed "
            "(row already deleted; reclaimed on the next pass)",
            guild_id,
        )
    return True


async def destroy_now(session: AsyncSession, guild: Guild) -> bool:
    """Destroy one guild without a retention window: its plug-ins let go, as on
    any deletion, then the rest as the purge does it. ``session`` is a
    platform system session. Returns whether the community is gone; one whose
    plug-ins have not all answered yet is finished by a later purge pass
    (:func:`finish_started_purges`).

    Raises ``HoldsInForce``, having changed nothing, while the platform holds
    anything there. The check's lock stays until ``session``'s transaction
    ends."""
    await _refuse_while_held(session, guild.id)
    # Its connections' revocations to the plug-ins are queued as this commits,
    # ahead of the erase the purge queues next.
    await post_commit.settle(await _end_plugin_connections(guild.id))
    return await _remove(session, guild.id, 0)


async def purge_due_guilds(session: AsyncSession, *, now: datetime) -> int:
    """One pass of :data:`~app.services.platform.retention.COMMUNITY_DELETION`,
    then of the purges already begun. Returns how many guilds were destroyed.

    Split out from the loop entry point so tests can drive it with the test
    session and a chosen ``now``.
    """
    gone: list[int] = []

    async def destroy(session: AsyncSession, guild: Guild, days: int) -> None:
        guild_id = guild.id
        if await _destroy(session, guild, days):
            gone.append(guild_id)

    await COMMUNITY_DELETION.sweep(session, now=now, act=destroy)
    return len(gone) + await finish_started_purges(session)


async def finish_started_purges(session: AsyncSession) -> int:
    """Take each community whose purge has begun one step further: deleted
    once its plug-ins have answered, whatever the retention window says now.
    Returns how many were deleted. Each is claimed on its own, ``FOR UPDATE
    SKIP LOCKED``, and one that fails is logged and left for the next pass."""
    await set_rls_context(session, Unattributed())
    days = COMMUNITY_DELETION.days(await rules.platform_values(session))
    started = list(
        await session.exec(
            select(Guild.id)
            .where(col(Guild.purge_started_at).is_not(None))
            .order_by(col(Guild.purge_started_at))
        )
    )
    await session.commit()
    gone = 0
    for guild_id in started:
        session.expunge_all()
        try:
            await set_rls_context(session, Unattributed())
            claimed = (
                await session.exec(
                    select(Guild.id)
                    .where(Guild.id == guild_id)
                    .with_for_update(skip_locked=True)
                )
            ).one_or_none()
            if claimed is None:
                await session.commit()
                continue
            await _refuse_while_held(session, guild_id)
            if await _remove(session, guild_id, days):
                gone += 1
        except Exception:
            await session.rollback()
            logger.exception(
                "guild purge: purge of guild %s failed; left for the next pass",
                guild_id,
            )
    return gone


async def _orphaned_guild_ids(session: AsyncSession) -> list[int]:
    """Guild schemas with no ``public.guilds`` row behind them.

    Every path that creates a guild commits its row before provisioning the
    schema, and every path that removes one deletes the row before dropping
    the schema, so a schema without a row is one whose teardown did not finish.
    """
    rows = await session.exec(
        text(
            "SELECT substring(n.nspname FROM 7)::int AS guild_id "
            "FROM pg_namespace n "
            "WHERE n.nspname ~ :pat "
            "AND NOT EXISTS ("
            "SELECT 1 FROM public.guilds g "
            "WHERE g.id = substring(n.nspname FROM 7)::int"
            ") "
            "ORDER BY 1"
        ),
        params={"pat": GUILD_SCHEMA_REGEX},
    )
    return [row[0] for row in rows]


async def reclaim_orphaned_guilds(session: AsyncSession) -> int:
    """Drop the schema, roles and blobs of every guild whose row is gone.

    Runs whatever the retention setting says: the window governs deleted
    communities that still have a row, and these have none. Returns how many
    were reclaimed; one that fails again is logged and retried next pass.
    """
    await set_rls_context(session, Unattributed())
    guild_ids = await _orphaned_guild_ids(session)
    # End the read before the drops, which run on the provisioning engine.
    await session.commit()
    reclaimed = 0
    for guild_id in guild_ids:
        try:
            await deprovision_guild(guild_id)
        except Exception:
            logger.exception(
                "guild purge: reclaiming orphaned schema for guild %s failed",
                guild_id,
            )
            continue
        reclaimed += 1
    if reclaimed:
        logger.info("guild purge: reclaimed %d orphaned guild schema(s)", reclaimed)
    return reclaimed


async def process_guild_purges() -> None:
    """One pass of the guild-purge loop. Idempotent and safe to run on a
    schedule even when nothing is due."""
    now = datetime.now(UTC)
    async with SystemSessionLocal() as session:
        await delete_expired_holds(session, now=now)
        await uninstall_deleted_plugins(session, now=now)
        await purge_due_guilds(session, now=now)
        await reclaim_orphaned_guilds(session)
