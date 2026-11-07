"""Moving an install onto a newer version of its listing.

One function does the re-pin, and two callers ask for it: a guild admin
pressing Update, and the sweep below that applies published versions to the
installs tracking them. Writing that reasoning twice is how the two would come
to disagree about what an upgrade leaves behind — so the endpoint keeps the
HTTP vocabulary and this keeps the meaning.

**Auto is the resting state.** An install tracks its listing unless a guild
admin says otherwise, because an install quietly falling behind its publisher is
the worse default: a fix reaches the guild without anyone having to notice it
exists. Turning it off is a guild's own answer to "we read each version first",
and the manual Update button then does exactly what this sweep would have.

**A version that asks for more waits.** Asking for more is a grantable scope
neither the install's grant nor its pinned version already names, or a surface
inside initiatives the pinned version does not have. The sweep does not apply
such a version: it records it as ``pending_version`` and tells the community's
seat once, and the install keeps running its pinned version with its current
grant. The seat accepts it from the Update button, adding the scopes it
consents to, or declines it, which stops the asking until a newer version is
published. A version asking for nothing new applies as before.

**A version waits only while the seat can take it.** Once the catalog no
longer offers it (withdrawn, or replaced by one this server cannot run), the
sweep clears ``pending_version``. While the deployment manages the community's
plug-ins, the seat cannot answer, so the sweep neither records a version nor
tells anyone; when the seat gets plug-ins back, it is asked.

**A required plug-in does not wait.** The deployment's registration is what
installed it and granted what it requests within the ceiling, with no seat
asked; its newer versions are applied the same way, adding the new scopes
within the ceiling. A community with no seat holder would otherwise keep a
required plug-in on a version it can no longer serve.

What survives an upgrade is the same either way. Stored configuration is pruned
to what the new definition still declares — a value cannot outlive the field it
was typed into — and a connection the new version dropped is *revoked* rather
than merely forgotten, since the plug-in is still holding whatever that credential
bought it.
"""

from __future__ import annotations

import logging
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.rules import SURFACE_PLUGINS
from app.db import cohorts
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.models.platform.guild import CommunityRole, GuildMembership
from app.models.platform.notification import NotificationType
from app.models.tenant.guild_plugin import GuildPlugin
from app.services.marketplace import registration_lookup
from app.services.marketplace.definitions import GUILD_INSTALLABLE_PLUGIN_KINDS
from app.services.platform import rules
from app.services.marketplace.installs import (
    ListingInstallError,
    resolve_listing_install,
)
from app.services.tenant import guild_plugins as guild_plugins_service
from app.services.tenant import plugin_config as plugin_config_service
from app.services.tenant import plugin_connections as connections_service
from app.services.tenant import metadata, plugin_schedules
from app.services.tenant import plugin_revocation as revocation_service

logger = logging.getLogger(__name__)

__all__ = [
    "AskedUpdate",
    "PendingUpdate",
    "RefusedUpdate",
    "UpdateOffer",
    "UpgradeAsks",
    "apply_version",
    "decline_version",
    "notify_pending_updates",
    "reconcile_repinned",
    "update_offer",
    "updates_target_path",
    "upgrade_asks",
    "update_guild",
]


def updates_target_path(install_id: int) -> str:
    """Where the seat answers a pending version, inside the community: the
    integrations settings, with the install's row open."""
    return f"/settings/integrations?plugin={int(install_id)}"


@dataclass(frozen=True)
class PendingUpdate:
    """A version an install could move to, and the definition it carries."""

    version: str
    definition: dict


@dataclass(frozen=True)
class UpgradeAsks:
    """What a version asks for that the install does not already have.

    ``added_scopes`` are grantable scopes (requested and within the ceiling)
    that neither the install's grant nor its pinned version names, in
    vocabulary order. A scope the pinned version already requested and the
    seat left out is not new: the seat has answered it. ``added_surfaces``
    are the surfaces rendering inside initiatives that the pinned version does
    not have, as ``{"id", "name"}``.
    """

    added_scopes: tuple[str, ...] = ()
    added_surfaces: tuple[dict[str, Any], ...] = field(default=())

    @property
    def asks_more(self) -> bool:
        return bool(self.added_scopes or self.added_surfaces)


def upgrade_asks(
    plugin: GuildPlugin,
    definition: dict,
    ceiling: Iterable[str],
    installed: Collection[str],
) -> UpgradeAsks:
    """What moving ``plugin`` to ``definition`` would ask the seat for. Using a
    plug-in the community does not have (``installed``) is not asked; installing
    that plug-in asks it."""
    held = set(plugin.granted_scopes or ()) | set(
        guild_plugins_service.requested_scopes(plugin.definition)
    )
    added_scopes = tuple(
        scope
        for scope in guild_plugins_service.grantable_scopes(
            definition, ceiling, installed
        )
        if scope not in held
    )
    current = guild_plugins_service.initiative_surface_ids(plugin.definition)
    added_surfaces = tuple(
        {"id": page["id"], "name": page.get("name") or {}}
        for page in guild_plugins_service.declared_surfaces(definition)
        if guild_plugins_service.surface_renders_in(page, "initiative")
        and page["id"] not in current
    )
    return UpgradeAsks(added_scopes=added_scopes, added_surfaces=added_surfaces)


async def _ceiling(definition: dict, listing_uid: str) -> tuple[str, ...]:
    """The registration's ceiling for the plug-in a version of the listing
    ``listing_uid`` is, or none."""
    registration = await registration_lookup.registration_for_definition(
        definition, listing_uid=listing_uid
    )
    return tuple(registration.scope_ceiling) if registration is not None else ()


@dataclass(frozen=True)
class UpdateOffer:
    """The version an install could move to, and what it would ask for."""

    update: "PendingUpdate"
    asks: UpgradeAsks

    @property
    def version(self) -> str:
        return self.update.version


@dataclass(frozen=True)
class RefusedUpdate:
    """A newer version of the install's listing that this server cannot run,
    with the ``messages.py`` code of the refusal."""

    version: str
    reason: str


async def update_offer(
    session: AsyncSession, plugin: GuildPlugin
) -> UpdateOffer | RefusedUpdate | None:
    """The listing's current version, as an offer with what taking it asks, or
    as a refusal when this server cannot run it.

    ``None`` when it is the pinned version, when the listing is gone or
    withdrawn, and when its kind is one this build cannot mount: applying that
    would leave the guild with an install nothing can serve.
    """
    try:
        _, version = await resolve_listing_install(
            session, plugin.listing_uid, kind="plugin", already_installed=True
        )
    except ListingInstallError as refused:
        newer = (refused.params or {}).get("version")
        if newer is None or newer == plugin.listing_version:
            return None
        return RefusedUpdate(version=newer, reason=refused.code)
    if version.version == plugin.listing_version:
        return None
    definition = dict(version.definition)
    if definition.get("plugin_kind") not in GUILD_INSTALLABLE_PLUGIN_KINDS:
        return None
    asks = upgrade_asks(
        plugin,
        definition,
        await _ceiling(definition, plugin.listing_uid),
        await guild_plugins_service.installed_plugin_ids(session),
    )
    return UpdateOffer(
        update=PendingUpdate(version=version.version, definition=definition),
        asks=asks,
    )


async def apply_version(
    session: AsyncSession,
    plugin: GuildPlugin,
    pending: PendingUpdate,
    *,
    guild_id: int,
    add_scopes: Iterable[str] = (),
) -> GuildPlugin:
    """Re-pin one install to a newer version of its listing.

    Everything the guild put in stays where it is, minus what the new definition
    stopped declaring. A dropped connection takes its values with it and is
    revoked on the way out; a dropped per-member connection is disconnected the
    same way, so no member is left holding vendor access this build no longer
    has a form for.

    ``add_scopes`` are the scopes the seat consented to with this version,
    already checked by the caller against the manifest and the ceiling. They
    join the grant; nothing is taken out of it here, because what a token
    carries is the grant intersected with what the pinned version requests.

    The caller commits — an upgrade is one transaction with whatever else it is
    part of — and the queued revocations are sent once it does, so a plug-in is
    told a credential is finished only once the write that finished it is
    durable.
    """
    definition = pending.definition
    previous = plugin.definition
    added = set(add_scopes)
    if added - set(plugin.granted_scopes or ()):
        plugin.granted_scopes = sorted(set(plugin.granted_scopes or ()) | added)
    # Whatever was waiting or declined was a question about an older version
    # than the one this install is now on.
    plugin.pending_version = None
    plugin.declined_version = None

    stored_secrets = await guild_plugins_service.load_secrets(session, plugin)
    config, secrets, dropped = plugin_config_service.prune_to_definition(
        definition, plugin.config, stored_secrets
    )
    await revocation_service.queue_install_revocations(
        session, plugin, dropped, secrets=stored_secrets, reason="upgraded"
    )
    plugin.config = config
    plugin.definition = definition
    plugin.listing_version = pending.version
    await guild_plugins_service.claim_newly_unique(
        session, plugin, previous, guild_id=guild_id
    )
    # The plug-in has not seen the new configuration shape yet, so whatever it said
    # about the old one is no longer an answer to the current question.
    plugin.config_state = "unverified"
    plugin.config_state_detail = None
    guild_plugins_service.touch(plugin)
    session.add(plugin)
    await guild_plugins_service.store_secrets(session, plugin, secrets)

    surviving = {
        connection.get("id")
        for connection in plugin_config_service.definition_connections(definition)
    }
    for row in await connections_service.list_plugin_connections(
        session, plugin_id=plugin.id
    ):
        if row.connection_id not in surviving:
            await connections_service.disconnect(
                session,
                plugin=plugin,
                connection_id=row.connection_id,
                user_id=row.user_id,
                reason="upgraded",
                definition=previous,
            )
    # What the new version adds to tasks shows where it is placed.
    await guild_plugins_service.show_on_saved_layouts(
        session,
        plugin,
        await guild_plugins_service.placed_initiative_ids(session, plugin.id),
        previous=previous,
    )
    return plugin


async def reconcile_repinned(
    guild_id: int, plugin: GuildPlugin, *, session: Optional[AsyncSession] = None
) -> None:
    """Bring what follows an install's pinned definition into line with it
    once it has moved: its schedules, and which of its values are shown.

    ``session`` is the community's system session, routed, whose caller
    commits; without one both are written and committed on one system
    session of their own."""
    if session is None:
        async with cohorts.system_session(guild_id) as own:
            await set_rls_context(own, SystemGuild(guild_id))
            await reconcile_repinned(guild_id, plugin, session=own)
            await own.commit()
        return
    await plugin_schedules.reconcile(
        guild_id, plugin.id, plugin.definition, session=session
    )
    await metadata.sync_definitions(guild_id, plugin.id, session=session)


def decline_version(plugin: GuildPlugin, version: str) -> None:
    """Keep the pinned version, and stop asking about ``version``.

    A newer version than this one is asked about afresh.
    """
    plugin.declined_version = version
    plugin.pending_version = None
    guild_plugins_service.touch(plugin)


# --- the sweep --------------------------------------------------------------


@dataclass(frozen=True)
class AskedUpdate:
    """A version the sweep recorded as pending, for the seat to be told."""

    plugin_id: int
    plugin_name: str
    version: str


async def notify_pending_updates(
    session: AsyncSession, guild_id: int, asked: Iterable[AskedUpdate]
) -> None:
    """Tell the community's seat holders that versions are waiting for them.

    One line per version per holder, in the approvals category. Runs out of
    the community's schema, on the bell's own rows in ``public``; the caller
    commits.
    """
    from app.services.platform import notice_outbox

    waiting = list(asked)
    if not waiting:
        return
    await set_rls_context(session, Unattributed())
    holders = (
        await session.exec(
            select(GuildMembership.user_id).where(
                GuildMembership.guild_id == guild_id,
                GuildMembership.role == CommunityRole.superadmin,
            )
        )
    ).all()
    await notice_outbox.enqueue(
        session,
        [
            notice_outbox.row(
                user_id,
                guild_id,
                NotificationType.plugin_update_pending,
                {
                    "community_id": guild_id,
                    "plugin_id": one.plugin_id,
                    "plugin_name": one.plugin_name,
                    "version": one.version,
                    "target_path": updates_target_path(one.plugin_id),
                },
            )
            for user_id in holders
            for one in waiting
        ],
    )


async def _update_guild(
    session: AsyncSession,
    guild_id: int,
    *,
    asked: Optional[list[AskedUpdate]] = None,
) -> int:
    """Apply what the catalog offers to one guild's tracking installs.

    Runs on a session already routed into that guild. A disabled install is
    updated too: ``auto_update`` says this guild tracks the listing, and a plug-in
    switched back on months later should not come back on a version its
    publisher has long since replaced.

    **An admin editing an install always wins.** The pass reads ids first and
    then takes each row again under ``FOR UPDATE``, rather than working from the
    snapshot the scan produced. Two things follow, and both matter because
    resolving the catalog takes real time between the two reads: the values this
    prunes are the ones the install holds *now*, so a credential saved in the
    meantime is pruned rather than overwritten by a stale copy; and
    ``auto_update`` is read again under the lock, so a guild that opted out in
    the meantime is not updated one last time. An edit arriving while the lock
    is held waits and then applies on top, which is the order it happened in.

    A version that asks for more is not applied. It is recorded as the
    install's ``pending_version`` and appended to ``asked`` the first time it
    is seen, so the caller can tell the seat once it has committed. A version
    the seat declined, or one already pending, is passed over quietly. An
    install with nothing the seat could take clears ``pending_version``.
    Returns how many installs were moved.

    A version that declares an assigned setting the install holds no value for
    gives it one (:func:`guild_plugins.assign_settings`), which commits what
    the pass has done so far.
    """
    candidates = (
        await session.exec(
            select(GuildPlugin.id)
            .where(GuildPlugin.auto_update.is_(True))
            .order_by(GuildPlugin.id)
        )
    ).all()

    # The seat answers a version only while the deployment leaves the
    # community's plug-ins to it.
    seat_answers = await rules.community_value(session, guild_id, SURFACE_PLUGINS)

    applied = 0
    for plugin_id in candidates:
        plugin = (
            await session.exec(
                select(GuildPlugin).where(GuildPlugin.id == plugin_id).with_for_update()
            )
        ).first()
        # Gone, or no longer tracking, since the scan.
        if plugin is None or not plugin.auto_update:
            continue
        offer = await update_offer(session, plugin)
        # A required plug-in's registration stands in for the seat, as at
        # install, so its versions never wait.
        waits = (
            isinstance(offer, UpdateOffer)
            and offer.asks.asks_more
            and not (
                await registration_lookup.install_state(
                    plugin.definition, guild_id=guild_id, listing_uid=plugin.listing_uid
                )
            ).mandatory
        )
        if not isinstance(offer, UpdateOffer) or (waits and not seat_answers):
            if plugin.pending_version is not None:
                plugin.pending_version = None
                guild_plugins_service.touch(plugin)
                session.add(plugin)
            continue
        if waits:
            if offer.version not in (plugin.pending_version, plugin.declined_version):
                plugin.pending_version = offer.version
                guild_plugins_service.touch(plugin)
                session.add(plugin)
                if asked is not None:
                    asked.append(
                        AskedUpdate(
                            plugin_id=plugin.id,
                            plugin_name=plugin.name,
                            version=offer.version,
                        )
                    )
                logger.info(
                    "plug-in auto-update: guild=%s plug-in=%s listing=%s %s waits for the seat",
                    guild_id,
                    plugin.id,
                    plugin.listing_uid,
                    offer.version,
                )
            continue
        from_version = plugin.listing_version
        await apply_version(
            session,
            plugin,
            offer.update,
            guild_id=guild_id,
            add_scopes=offer.asks.added_scopes,
        )
        await reconcile_repinned(guild_id, plugin, session=session)
        await guild_plugins_service.assign_settings(session, plugin, guild_id=guild_id)
        applied += 1
        logger.info(
            "plug-in auto-update: guild=%s plug-in=%s listing=%s%s %s -> %s",
            guild_id,
            plugin.id,
            plugin.listing_uid,
            " required," if offer.asks.asks_more else "",
            from_version,
            offer.version,
        )
    return applied


async def update_guild(session: AsyncSession, guild_id: int) -> None:
    """The sweep's visit to one guild, on a session routed into it.

    Run by the hourly pass: a published version reaching every guild within
    the hour is what "automatic" needs to mean, and a visit costs one catalog
    read per installed listing. Only ``active`` guilds are visited: a guild on
    hold is frozen, and a background re-pin is still a change to what its
    members see.
    """
    asked: list[AskedUpdate] = []
    await _update_guild(session, guild_id, asked=asked)
    await session.commit()
    # The versions now waiting are durable, so the seat is told about them. A
    # bell that cannot be written is logged: the version stays pending on the
    # install and the settings page still shows it.
    if asked:
        try:
            await notify_pending_updates(session, guild_id, asked)
            await session.commit()
        except Exception:
            logger.exception(
                "plug-in auto-update: guild %s seat could not be told", guild_id
            )
            await session.rollback()
