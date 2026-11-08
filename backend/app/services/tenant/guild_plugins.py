"""Installing and removing guild plug-ins.

Three shapes, and the difference is what the plug-in brings with it.

A **tool instance** mounts one of this build's own tools at guild scope. Its
rows are ordinary rows in that tool's ordinary table with no initiative — a
guild-level calendar is a `calendars` row with `initiative_id` NULL — owned
by the install. Installing the calendar plug-in creates one, so the sidebar
can link straight to it; the community contacts plug-in starts empty. Nothing
about the tool changes: same table, same UI, same sharing, same trash. The
content is seeded shared with everyone in the guild, which is what makes a plug-in
useful the moment it lands. From there the guild admin decides its sharing:
remove the everyone grant to make it private, add write grants to let
particular members or roles post in it. Writing the row itself is the admin's.

An install is not limited to what it created on the way in. A guild admin
adding another guild calendar gives it to the install too, because the plug-in is
the container: it is the entry that reaches the content, so removing it takes
the content with it rather than stranding rows nothing links to.

A **service** plug-in brings connections rather than content: what it needs is
configuration, which lives on the install row, in its secret values
(:func:`store_secrets`) and in each member's own connection. It creates no artifacts here.

**Artifacts are what the install owns.** An install may produce more than
one thing; what it produced is every guild-level row whose owner grant names
it, read as `[{"type": …, "id": …}]`, and removal walks that through
:data:`ARTIFACT_HANDLERS`. Every tool a plug-in may mount has a handler — asserted
by a test rather than left to be noticed the day an uninstall quietly leaves a
row behind.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.messages import GuildPluginMessages
from app.core.plugin_scopes import ordered_scopes, plugin_scope, plugin_scope_target
from app.core.tools import Tool
from app.db.session import routed_guild_id
from app.models.platform.marketplace import MarketplaceListing
from app.models.tenant.calendar import Calendar
from app.models.tenant.contact import Contact
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.guild_plugin_secret import GuildPluginSecret
from app.models.tenant.initiative import (
    BUILTIN_ROLES,
    Initiative,
    InitiativeRoleModel,
)
from app.models.tenant.plugin_placement import PluginPlacement
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.schemas.tenant.resource_grant import initiative_readable
from app.schemas.tenant.tool_layout import PLUGIN_FIELD_PREFIX
from app.services import audit as audit_service
from app.services.marketplace import (
    community_hooks,
    plugin_entitlements,
    plugin_installs,
    registration_lookup,
)
from app.services.marketplace.manifest_values import is_unique_setting_value
from app.services.marketplace.service_plugins import is_admin_only
from app.services.platform import guilds as guilds_service
from app.services.tenant import ownership as ownership_service
from app.services.tenant import plugin_config as plugin_config_service
from app.services.tenant import plugin_connections as connections_service
from app.services.tenant import plugin_member_consents as consents_service
from app.services.tenant import tool_layouts as tool_layouts_service
from app.services.tenant import webhook_subscriptions as webhook_subscriptions_service
from app.services.tenant.plugin_revocation import queue_install_revocations
from app.services.tenant.soft_delete import soft_delete_entity

logger = logging.getLogger(__name__)

__all__ = [
    "ARTIFACT_HANDLERS",
    "BUILTIN_ROLE_NAMES",
    "ArtifactHandler",
    "PlacementError",
    "PlacementRoleError",
    "SurfaceAccess",
    "SurfaceOpenability",
    "apply_static_config",
    "artifacts_by_install",
    "assign_settings",
    "claim_newly_unique",
    "clear_static_connection",
    "create_plugin_artifacts",
    "declared_surfaces",
    "definition_public_id",
    "find_mounting_plugin",
    "has_initiative_surfaces",
    "initiative_surface_ids",
    "install_plugin",
    "install_public_id",
    "installed_plugin_ids",
    "is_placed",
    "load_secrets",
    "lock_install",
    "offered_scopes",
    "place_in_every_initiative",
    "place_with_roles",
    "placed_initiative_ids",
    "placement_role_ids",
    "placements_by_install",
    "plugin_artifacts",
    "plugin_callers",
    "set_granted_scopes",
    "set_placed_initiatives",
    "set_placement_roles",
    "set_plugin_callers",
    "set_setting",
    "store_secrets",
    "surface_access",
    "surface_openability",
    "surface_renders_in",
    "touch",
    "uninstall_plugin",
]

# --- artifacts --------------------------------------------------------------


@dataclass(frozen=True)
class ArtifactHandler:
    """How one kind of artifact is made and unmade.

    ``create`` makes the row, owned by the install, or is ``None`` where
    installing makes nothing (contacts arrive one at a time); ``remove``
    disposes of one. Removal is soft wherever the tool has a trash, because
    what a plug-in holds is guild content — the events someone put in a guild
    calendar should survive an admin removing the plug-in.
    """

    remove: Callable[..., Awaitable[None]]
    create: Callable[..., Awaitable[None]] | None = None


async def _create_calendar(
    session: AsyncSession, *, plugin: GuildPlugin, name: str, guild_id: int
) -> None:
    calendar = Calendar(
        # No initiative: this belongs to the guild. Its grants decide who reads
        # and writes what it holds, exactly as for an initiative calendar.
        initiative_id=None,
        created_by=plugin.created_by,
        name=name,
    )
    session.add(calendar)
    await session.flush()
    # Shared with the guild from the start — a plug-in nobody can see is not
    # useful, and narrowing it afterwards is one edit to its sharing.
    await ownership_service.give_to_install(
        session,
        Tool.calendar,
        calendar,
        install_id=plugin.id,
        guild_id=guild_id,
        grants=initiative_readable(),
    )


def _trash(model: type[Calendar | Contact]) -> Callable[..., Awaitable[None]]:
    """Removal that sends one of ``model``'s rows to the trash."""

    async def remove(
        session: AsyncSession,
        artifact_id: int,
        *,
        deleted_by_user_id: int | None,
        retention_days: int | None,
    ) -> None:
        row = (await session.exec(select(model).where(model.id == artifact_id))).first()
        if row is None:
            return
        await soft_delete_entity(
            session,
            row,
            deleted_by_user_id=deleted_by_user_id,
            retention_days=retention_days,
        )

    return remove


#: One entry per tool a plug-in may mount at guild scope, keyed by the artifact
#: type (which is the tool's own name). ``guild_plugins_test`` asserts this covers
#: every entry in ``MOUNTABLE_TOOLS``, so a tool added to the manifest
#: vocabulary cannot ship without a way to unmake what it created.
ARTIFACT_HANDLERS: dict[str, ArtifactHandler] = {
    Tool.calendar.value: ArtifactHandler(
        create=_create_calendar, remove=_trash(Calendar)
    ),
    Tool.contact.value: ArtifactHandler(remove=_trash(Contact)),
}


async def artifacts_by_install(
    session: AsyncSession, install_ids: Iterable[int]
) -> dict[int, list[dict[str, Any]]]:
    """What each install produced, as ``[{"type": …, "id": …}]``, in one query.

    An install's artifacts are the guild-level rows it owns: the owner grant
    naming the install is the record, so there is no second list to keep in
    step with it.
    """
    ids = list(install_ids)
    if not ids:
        return {}
    rows = await session.exec(
        select(
            ResourceGrant.plugin_install_id,
            ResourceGrant.resource_type,
            ResourceGrant.resource_id,
        )
        .where(
            col(ResourceGrant.plugin_install_id).in_(ids),
            ResourceGrant.level == ResourceAccessLevel.owner,
            col(ResourceGrant.initiative_id).is_(None),
            col(ResourceGrant.resource_type).in_(ARTIFACT_HANDLERS),
        )
        .order_by(col(ResourceGrant.plugin_install_id), col(ResourceGrant.resource_id))
    )
    grouped: dict[int, list[dict[str, Any]]] = {install_id: [] for install_id in ids}
    for install_id, artifact_type, artifact_id in rows.all():
        grouped[install_id].append({"type": artifact_type, "id": artifact_id})
    return grouped


async def plugin_artifacts(
    session: AsyncSession, plugin: GuildPlugin
) -> list[dict[str, Any]]:
    """What one install produced; see :func:`artifacts_by_install`."""
    return (await artifacts_by_install(session, [plugin.id]))[plugin.id]


async def lock_install(session: AsyncSession, plugin_id: int) -> GuildPlugin | None:
    """Hold one install's row for the rest of this transaction.

    Several things on this row are values rewritten whole rather than appended
    to — the configuration maps, the connection handles — so writing one means
    reading it, changing it, and putting the result back. Two of those
    overlapping would have the second write carry a value read before the first
    landed, and the first change would be gone with no sign that it had been
    made. Taking the row first puts them in an order instead.

    Removal takes it too, before reading what the install owns. Giving the
    install something waits on it, because the owner grant's foreign key names
    this row, so the new content is either among what removal reads or finds
    the install gone.

    Answers ``None`` if the row is gone, which is the same answer as this guild
    never having had the install.
    """
    return (
        await session.exec(
            select(GuildPlugin)
            .where(GuildPlugin.id == plugin_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).first()


async def load_secrets(session: AsyncSession, plugin: GuildPlugin) -> dict[str, Any]:
    """An install's secret values, ``{connection_id: {key: ciphertext}}``.

    Read from ``guild_plugin_secrets``, which the seat and the system engine read.
    No row reads as ``{}``.
    """
    stored = (
        await session.exec(
            select(GuildPluginSecret.secrets).where(
                GuildPluginSecret.install_id == plugin.id
            )
        )
    ).first()
    return dict(stored or {})


async def store_secrets(
    session: AsyncSession, plugin: GuildPlugin, secrets: Mapping[str, Any]
) -> None:
    """Replace an install's secret values; an empty map removes its row.

    The trigger on ``guild_plugin_secrets`` rewrites ``guild_plugins.secret_fields``
    in the same statement, and ``plugin`` is refreshed with it. Pending changes to
    ``plugin`` are flushed first, so the refresh replaces ``secret_fields`` alone.
    """
    await session.flush()
    if secrets:
        insert = pg_insert(GuildPluginSecret).values(
            install_id=plugin.id, secrets=dict(secrets)
        )
        await session.exec(
            insert.on_conflict_do_update(
                index_elements=[GuildPluginSecret.install_id],
                set_={"secrets": insert.excluded.secrets},
            )
        )
    else:
        await session.exec(
            delete(GuildPluginSecret).where(
                col(GuildPluginSecret.install_id) == plugin.id
            )
        )
    await session.refresh(plugin, ["secret_fields"])


async def find_mounting_plugin(
    session: AsyncSession, *, tool: str
) -> GuildPlugin | None:
    """The install that mounts ``tool`` at guild scope, if this guild has one.

    A tool-instance install is the container for what it mounts, so this is the
    question "does this guild have somewhere to put a guild-level calendar" —
    asked before creating one, and answered from the install rows rather than
    from the content, since an install with everything trashed is still the
    container.
    """
    plugins = (await session.exec(select(GuildPlugin))).all()
    for plugin in plugins:
        definition = plugin.definition or {}
        if (
            definition.get("plugin_kind") == "tool_instance"
            and definition.get("tool") == tool
        ):
            return plugin
    return None


async def create_plugin_artifacts(
    session: AsyncSession, plugin: GuildPlugin, *, guild_id: int
) -> None:
    """Create what the plug-in mounts, owned by its install.

    Only a tool instance produces anything. A **service** plug-in brings
    connections rather than content — its install is the row plus the definition it pinned, and what it
    offers is served from the container the operator registered.
    """
    definition = plugin.definition or {}
    if definition.get("plugin_kind") != "tool_instance":
        return

    tool = definition.get("tool")
    handler = ARTIFACT_HANDLERS.get(tool or "")
    if handler is None:
        # Unreachable through the endpoints — the definition validator admits
        # only tools listed there — but this is the place that would need
        # teaching about a new one.
        raise ValueError(f"cannot mount {tool!r} at guild scope")

    if handler.create is not None:
        await handler.create(
            session, plugin=plugin, name=plugin.name, guild_id=guild_id
        )


class ErasePendingError(Exception):
    """The community asked this plug-in to erase its data, and the erase is not
    finished: installing it now would hand it the names the erase is about to
    drop."""


async def _refuse_while_erasing(
    guild_id: int, definition: dict, listing_uid: str
) -> None:
    """Raise :class:`ErasePendingError` while an erase of this plug-in in the
    community is unfinished."""
    public_id = await definition_public_id(definition, listing_uid)
    if public_id is not None and await community_hooks.erase_pending(
        guild_id=guild_id, public_id=public_id
    ):
        raise ErasePendingError(public_id)


async def install_plugin(
    session: AsyncSession,
    *,
    listing_uid: str,
    listing_version: str,
    definition: dict,
    guild_id: int,
    created_by: int,
    name: str,
    actor_user_id: int | None = None,
    via: str = "install",
    granted_scopes: Sequence[str] = (),
    allowed_callers: Collection[int] | None = (),
) -> GuildPlugin:
    """Create the install row, and whatever the plug-in mounts alongside it.

    One place knows what an install *is*, because there are two callers now: a
    guild admin choosing a plug-in, and the deployment placing a mandatory one into
    every guild (§7.7). The row is flushed rather than committed — the caller
    owns the transaction, since a guild creation commits the install together
    with the rest of the guild's seed.

    ``actor_user_id`` is the account the caller's session runs as — an admin
    choosing the plug-in, or ``None`` for a sweep running as nobody. ``via`` says
    which of the two routes this install came down, and rides the record.

    ``granted_scopes`` is what the seat consented to in the install dialog,
    already checked against the manifest and the ceiling by the caller. It is
    written with the row, so the install never exists without its consent.
    ``allowed_callers`` is the rest of that answer: the installs here let use
    this plug-in (:func:`set_plugin_callers`; ``None`` lets every one).

    Raises :class:`ErasePendingError`, having written nothing, while the
    community's request that this plug-in erase its data is unfinished.
    """
    await _refuse_while_erasing(guild_id, definition, listing_uid)
    plugin = GuildPlugin(
        listing_uid=listing_uid,
        listing_version=listing_version,
        plugin_kind=definition["plugin_kind"],
        name=name,
        definition=definition,
        config={},
        granted_scopes=sorted(set(granted_scopes)),
        created_by=created_by,
    )
    session.add(plugin)
    await session.flush()
    await create_plugin_artifacts(session, plugin, guild_id=guild_id)
    # Staged in the caller's transaction, after the flush that gives the install
    # its id, so the record and the install land together or not at all.
    await audit_service.record(
        session,
        event_type=AuditEventType.PLUGIN_INSTALLED,
        actor_user_id=actor_user_id,
        guild_id=guild_id,
        target_type="plugin",
        target_id=plugin.id,
        detail={
            "listing_uid": listing_uid,
            "version": listing_version,
            "via": via,
            "granted_scopes": sorted(set(granted_scopes)),
        },
    )
    public_id = await install_public_id(plugin)
    if public_id is not None:
        await set_plugin_callers(
            session,
            public_id,
            allowed_callers,
            exclude_id=plugin.id,
            actor_user_id=actor_user_id,
            guild_id=guild_id,
        )
        # Written with the install, so it is told once the install commits, by
        # either route, first time or again, and never for one rolled back.
        await community_hooks.queue_community_hooks(
            session,
            guild_id=guild_id,
            public_id=public_id,
            hooks=("installed",),
            install_id=plugin.id,
        )
    plugin_entitlements.after_install(session, guild_id, listing_uid)
    return plugin


async def uninstall_plugin(
    session: AsyncSession,
    plugin: GuildPlugin,
    *,
    actor_user_id: int,
    erase: bool = False,
) -> None:
    """Remove an install, ending its access and trashing what it created.

    What the plug-in calls the community and its members is kept, so a later
    install brings the same names back. It is told ``uninstalled`` once the
    removal commits; with ``erase``, it is then told ``erase``, and the names
    are dropped once it answers (``community_hooks``).

    The two halves are deliberately different. **Credentials are deleted**, both
    the guild's and every member's, and each plug-in is told to let go at the vendor
    — an uninstalled plug-in still receiving a guild's data is the thing this
    prevents. **Content is trashed** through the ordinary soft-delete path,
    because the events someone put in a guild calendar are the guild's, and
    should survive an admin removing the plug-in for as long as the retention
    window allows.

    The caller holds the install row (:func:`lock_install`), commits, and then
    dispatches the queued revocations.
    """
    guild_id = routed_guild_id(session)
    retention_days = await guilds_service.get_guild_retention_days(session)
    connections = await connections_service.delete_plugin_connections(
        session, plugin=plugin
    )
    # Every member's answers to its requests go with it. The foreign key would
    # take them with the install row; removed here so the record counts them.
    consents = await consents_service.delete_install_consents(
        session, install_id=plugin.id
    )
    # An install is what makes a plug-in present in a guild, so removing it ends
    # what that plug-in is sent. Switched off rather than deleted: the row records
    # what was going where, and a reinstall registers afresh.
    await webhook_subscriptions_service.deactivate_for_install(
        session, guild_id=guild_id, plugin_install_id=plugin.id
    )
    secrets = await load_secrets(session, plugin)
    # The revocations to the plug-in itself are written to its hook queue
    # here, ahead of the uninstalled and erase below.
    await queue_install_revocations(
        session,
        plugin,
        {*(plugin.config or {}), *secrets},
        secrets=secrets,
        reason="uninstalled",
    )
    for artifact in await plugin_artifacts(session, plugin):
        await ARTIFACT_HANDLERS[artifact["type"]].remove(
            session,
            artifact["id"],
            deleted_by_user_id=actor_user_id,
            retention_days=retention_days,
        )
    # Nothing here may use it any more, and a later install asks again.
    public_id = await install_public_id(plugin)
    if public_id is not None:
        await set_plugin_callers(
            session,
            public_id,
            (),
            exclude_id=plugin.id,
            actor_user_id=actor_user_id,
            guild_id=guild_id,
        )

    # Told with the removal, in its transaction, under the public id its
    # references key on, registration or not, so an erase still reaches them.
    if public_id is not None:
        await community_hooks.queue_community_hooks(
            session,
            guild_id=guild_id,
            public_id=public_id,
            hooks=("uninstalled", "erase") if erase else ("uninstalled",),
            install_id=plugin.id,
        )
    install_id, listing_uid = plugin.id, plugin.listing_uid
    await session.delete(plugin)
    # Staged before the commit that removes the row, and reading the counts the
    # steps above returned rather than asking again.
    await audit_service.record(
        session,
        event_type=AuditEventType.PLUGIN_UNINSTALLED,
        actor_user_id=actor_user_id,
        guild_id=guild_id,
        target_type="plugin",
        target_id=install_id,
        detail={
            "listing_uid": listing_uid,
            "connections": connections,
            "consents": consents,
            "erase": erase,
        },
    )


async def clear_static_connection(
    session: AsyncSession, plugin: GuildPlugin, connection_id: str
) -> None:
    """Clear a guild-wide connection's stored values and its handle.

    Its grant is ended at the vendor after the caller commits. The handle goes
    with the values, so a token asked for by the old one is refused;
    connecting again mints a fresh one. The caller holds the install row.
    """
    secrets = await load_secrets(session, plugin)
    if (plugin.config or {}).get(connection_id) or secrets.get(connection_id):
        await queue_install_revocations(
            session, plugin, [connection_id], secrets=secrets, reason="disconnected"
        )
    plugin.config = {
        key: value
        for key, value in (plugin.config or {}).items()
        if key != connection_id
    }
    await store_secrets(
        session,
        plugin,
        {key: value for key, value in secrets.items() if key != connection_id},
    )
    plugin.connection_refs = {
        key: value
        for key, value in (plugin.connection_refs or {}).items()
        if key != connection_id
    }
    _unverified(plugin)


def _config_fields(config: dict, secrets: dict) -> dict[str, Any]:
    """Every stored configuration field, keyed ``connection.field``.

    The shape a before/after comparison reads: the keys are what a record
    carries, and the values are only ever compared with one another.
    """
    fields: dict[str, Any] = {}
    for store in (config, secrets):
        for connection_id, values in (store or {}).items():
            for field, value in (values or {}).items():
                fields[f"{connection_id}.{field}"] = value
    return fields


async def apply_static_config(
    session: AsyncSession,
    plugin: GuildPlugin,
    values: Mapping[str, Mapping[str, Any]],
    *,
    actor_user_id: int,
) -> None:
    """Set the guild-wide values ``values`` names, per connection.

    Validated against the *pinned* definition, so what an install accepts is
    the form it was configured against. Only guild-scoped connections are
    settable here. Raises :class:`~app.services.tenant.plugin_config.PluginConfigError`
    for anything refused. The caller holds the install row and commits.
    """
    config = dict(plugin.config or {})
    secrets = await load_secrets(session, plugin)
    before = _config_fields(config, secrets)

    for connection_id, submitted in values.items():
        connection = plugin_config_service.connection_by_id(
            plugin.definition, connection_id
        )
        if connection is None:
            raise plugin_config_service.PluginConfigError(
                GuildPluginMessages.CONFIG_UNKNOWN_CONNECTION
            )
        if connection.get("scope") != "static":
            raise plugin_config_service.PluginConfigError(
                GuildPluginMessages.CONNECTION_NOT_STATIC
            )
        new_config, new_secrets = plugin_config_service.apply_connection_values(
            connection,
            submitted,
            current=config.get(connection_id) or {},
            current_secrets=secrets.get(connection_id) or {},
        )
        if new_config:
            config[connection_id] = new_config
        else:
            config.pop(connection_id, None)
        if new_secrets:
            secrets[connection_id] = new_secrets
        else:
            secrets.pop(connection_id, None)
        if plugin_config_service.token_of(connection) is not None:
            # A connection the plug-in asks a token for is addressed by a handle.
            plugin_config_service.guild_connection_ref(plugin, connection_id)

    plugin.config = config
    await store_secrets(session, plugin, secrets)
    _unverified(plugin)
    # Which fields hold something different now, by name. A configuration value
    # is the plug-in's credential to the vendor, so none of it reaches the record.
    moved = audit_service.changed_fields(before, _config_fields(config, secrets))[
        "changed"
    ]
    if moved:
        await audit_service.record(
            session,
            event_type=AuditEventType.PLUGIN_UPDATED,
            actor_user_id=actor_user_id,
            guild_id=routed_guild_id(session),
            target_type="plugin",
            target_id=plugin.id,
            detail={
                "area": "config",
                "changed": moved,
                "connection_ids": sorted(values),
            },
        )


def _unverified(plugin: GuildPlugin) -> None:
    """The plug-in has not seen the install's values as they now stand, so its
    previous verdict no longer describes them. It reports again once it has
    pulled and checked."""
    plugin.config_state = "unverified"
    plugin.config_state_detail = None
    touch(plugin)


def touch(plugin: GuildPlugin) -> None:
    plugin.updated_at = datetime.now(UTC)


# --- settings ---------------------------------------------------------------
#
# A unique setting's value is claimed across communities
# (``plugin_installs.claim_value``) in the transaction that stores it on the
# install, so the install's values and its claims never disagree.


def _unassigned(plugin: GuildPlugin) -> list[str]:
    """The keys of the assigned settings the install holds no value for."""
    held = plugin.settings or {}
    return [
        setting["key"]
        for setting in plugin_config_service.definition_settings(plugin.definition)
        if setting.get("assigned") and not held.get(setting["key"])
    ]


def _unique_keys(definition: Any) -> set[str]:
    return {
        setting["key"]
        for setting in plugin_config_service.definition_settings(definition)
        if setting.get("unique") is True
    }


async def assign_settings(
    session: AsyncSession, plugin: GuildPlugin, *, guild_id: int
) -> None:
    """Give each assigned setting the pinned definition declares, and the
    install holds no value for, a value of its own
    (:func:`~app.services.marketplace.plugin_installs.assigned_value`), and
    store it on the install.

    Called once the install, or the version that declares the setting, is in.
    Only when a setting has no value does it take the install's row and commit
    ``session``, with the claims.
    """
    if not _unassigned(plugin):
        return
    await session.flush()
    locked = await lock_install(session, plugin.id)
    keys = _unassigned(locked) if locked is not None else []
    if locked is None or not keys:
        await session.commit()
        return
    settings = dict(locked.settings or {})
    for key in keys:
        value = await plugin_installs.assigned_value(session, guild_id, locked, key)
        if value is not None:
            settings[key] = value
    if settings != (locked.settings or {}):
        locked.settings = settings
        touch(locked)
        session.add(locked)
    await session.commit()


async def claim_newly_unique(
    session: AsyncSession,
    plugin: GuildPlugin,
    previous: Any,
    *,
    guild_id: int,
) -> None:
    """Claim the value the install holds for each setting its pinned
    definition makes unique where ``previous`` did not, in the caller's
    transaction. A value a unique setting may not hold, or that another
    install of the plug-in holds, is dropped: an assigned setting then gets a
    value of its own (:func:`assign_settings`), and any other is left for the
    seat to set.
    """
    settings = dict(plugin.settings or {})
    for key in _unique_keys(plugin.definition) - _unique_keys(previous):
        value = settings.get(key)
        if not value:
            continue
        value = value.lower() if isinstance(value, str) else value
        if is_unique_setting_value(value) and await plugin_installs.claim_value(
            session, guild_id, plugin, key, value
        ):
            settings[key] = value
            continue
        del settings[key]
        logger.info(
            "plug-in settings: install %s in guild %s could not keep %s",
            plugin.id,
            guild_id,
            key,
        )
    if settings != (plugin.settings or {}):
        plugin.settings = settings
        session.add(plugin)


async def set_setting(
    session: AsyncSession,
    plugin: GuildPlugin,
    key: str,
    value: Any,
    *,
    guild_id: int,
    actor_user_id: int,
) -> None:
    """Set one of the install's settings to ``value``, and commit.

    Checked against the *pinned* definition
    (:func:`~app.services.tenant.plugin_config.setting_value`). A unique
    setting's value is claimed in the same transaction; one another install of
    the plug-in holds, now or as an earlier value, is refused with
    ``SETTING_UNAVAILABLE``. The value it replaces becomes the newest earlier
    one and stays the install's, and renaming back to an earlier one makes it
    current again. Raises
    :class:`~app.services.tenant.plugin_config.PluginConfigError` for anything
    refused. The caller holds the install row.
    """
    setting = next(
        (
            one
            for one in plugin_config_service.definition_settings(plugin.definition)
            if one.get("key") == key
        ),
        None,
    )
    if setting is None:
        raise plugin_config_service.PluginConfigError(
            GuildPluginMessages.SETTING_NOT_FOUND, 404
        )
    new = plugin_config_service.setting_value(setting, value)
    settings = dict(plugin.settings or {})
    old = settings.get(key)
    if new == old:
        return
    aliases = dict(plugin.setting_aliases or {})
    if setting.get("unique") is True:
        if not await plugin_installs.claim_value(session, guild_id, plugin, key, new):
            raise plugin_config_service.PluginConfigError(
                GuildPluginMessages.SETTING_UNAVAILABLE, 409
            )
        earlier = [one for one in aliases.pop(key, []) if one != new]
        if old:
            earlier.insert(0, old)
        if earlier:
            aliases[key] = earlier
    if new is None:
        settings.pop(key, None)
    else:
        settings[key] = new
    plugin.settings = settings
    plugin.setting_aliases = aliases
    touch(plugin)
    session.add(plugin)
    name = f"settings.{key}"
    await audit_service.record(
        session,
        event_type=AuditEventType.PLUGIN_UPDATED,
        actor_user_id=actor_user_id,
        guild_id=guild_id,
        target_type="plugin",
        target_id=plugin.id,
        detail={
            "area": "settings",
            **audit_service.changed_fields({name: old}, {name: new}),
        },
    )
    await session.commit()


# --- placement --------------------------------------------------------------
#
# Where a plug-in's initiative-scoped surfaces appear: one ``plugin_placements`` row
# per initiative, carrying the initiative roles allowed to open the plug-in there.
# An initiative with no row is one the plug-in is not placed in. Placement is the
# seat's answer to "where does this belong", so it applies to everyone
# including guild admins — unlike the roles on a row, which an admin always
# clears.


class PlacementError(ValueError):
    """A placement that names something this guild cannot place a plug-in in."""


class PlacementRoleError(PlacementError):
    """A placement naming a role that is not one of its initiative's."""


#: The built-in initiative roles, by name. Every initiative is created with
#: each of them, so a name here resolves to one role in any initiative.
BUILTIN_ROLE_NAMES: tuple[str, ...] = tuple(spec.name for spec in BUILTIN_ROLES)


async def _builtin_role_ids(
    session: AsyncSession, initiative_ids: Iterable[int], names: Iterable[str]
) -> dict[int, list[int]]:
    """Each initiative's built-in roles of those names, keyed by initiative.

    One query for every initiative. An initiative missing one of the roles
    (renamed or deleted) is placed with the ones it has.
    """
    ids = list(initiative_ids)
    wanted = sorted(set(names))
    if not ids or not wanted:
        return {}
    rows = await session.exec(
        select(InitiativeRoleModel.initiative_id, InitiativeRoleModel.id)
        .where(
            InitiativeRoleModel.initiative_id.in_(ids),
            InitiativeRoleModel.name.in_(wanted),
            InitiativeRoleModel.is_builtin.is_(True),
        )
        .order_by(InitiativeRoleModel.id)
    )
    roles: dict[int, list[int]] = {}
    for initiative_id, role_id in rows.all():
        roles.setdefault(initiative_id, []).append(role_id)
    return roles


async def _moderator_role_ids(
    session: AsyncSession, initiative_ids: Iterable[int]
) -> dict[int, list[int]]:
    """Each initiative's built-in moderator role, keyed by initiative."""
    return await _builtin_role_ids(session, initiative_ids, ("moderator",))


def _default_role_ids(roles: dict[int, list[int]], initiative_id: int) -> list[int]:
    """The role set a new placement starts with: the initiative's moderators."""
    return sorted(roles.get(initiative_id, []))


async def placements_by_install(
    session: AsyncSession, install_ids: Iterable[int]
) -> dict[int, list[PluginPlacement]]:
    """Every placement of each install, ordered by initiative, in one query."""
    ids = list(install_ids)
    if not ids:
        return {}
    rows = await session.exec(
        select(PluginPlacement)
        .where(PluginPlacement.install_id.in_(ids))
        .order_by(PluginPlacement.install_id, PluginPlacement.initiative_id)
    )
    grouped: dict[int, list[PluginPlacement]] = {install_id: [] for install_id in ids}
    for row in rows.all():
        grouped.setdefault(row.install_id, []).append(row)
    return grouped


async def placed_initiative_ids(session: AsyncSession, install_id: int) -> set[int]:
    """The initiatives this install is placed in."""
    rows = await session.exec(
        select(PluginPlacement.initiative_id).where(
            PluginPlacement.install_id == install_id
        )
    )
    return set(rows.all())


async def is_placed(
    session: AsyncSession, install_id: int, initiative_id: int | None
) -> bool:
    """Whether this install offers its initiative surfaces in that initiative.

    ``None`` is the guild-wide reading, which placement says nothing about.
    """
    if initiative_id is None:
        return True
    row = (
        await session.exec(
            select(PluginPlacement.initiative_id).where(
                PluginPlacement.install_id == install_id,
                PluginPlacement.initiative_id == initiative_id,
            )
        )
    ).first()
    return row is not None


async def placement_role_ids(
    session: AsyncSession, install_id: int, initiative_id: int
) -> list[int] | None:
    """The roles allowed to open this install's surfaces in one initiative.

    ``None`` when the install is not placed there, which is a different answer
    from a placement allowing no role: the first has no surface to open, the
    second has one that only admins open.
    """
    row = (
        await session.exec(
            select(PluginPlacement.role_ids).where(
                PluginPlacement.install_id == install_id,
                PluginPlacement.initiative_id == initiative_id,
            )
        )
    ).first()
    return None if row is None else list(row or [])


async def set_placement_roles(
    session: AsyncSession,
    plugin: GuildPlugin,
    initiative_id: int,
    role_ids: Iterable[int],
) -> PluginPlacement:
    """Place the install in one initiative with exactly these roles.

    Creates the placement or replaces its roles. The initiative must be one of
    this guild's, and every role one of *that* initiative's, both read on the
    same routed session; anything else raises :class:`PlacementError`.
    """
    wanted: set[int] = set()
    for entry in role_ids:
        if isinstance(entry, bool) or not isinstance(entry, int):
            raise PlacementError("roles must be a list of role ids")
        wanted.add(entry)
    initiative = (
        await session.exec(select(Initiative.id).where(Initiative.id == initiative_id))
    ).first()
    if initiative is None:
        raise PlacementError(f"initiative {initiative_id} is not one of this guild's")
    if wanted:
        known = set(
            (
                await session.exec(
                    select(InitiativeRoleModel.id).where(
                        InitiativeRoleModel.initiative_id == initiative_id,
                        InitiativeRoleModel.id.in_(sorted(wanted)),
                    )
                )
            ).all()
        )
        foreign = sorted(wanted - known)
        if foreign:
            raise PlacementRoleError(
                f"role {foreign[0]} is not a role of initiative {initiative_id}"
            )

    placement = (
        await session.exec(
            select(PluginPlacement).where(
                PluginPlacement.install_id == plugin.id,
                PluginPlacement.initiative_id == initiative_id,
            )
        )
    ).first()
    if placement is None:
        placement = PluginPlacement(
            install_id=plugin.id, initiative_id=initiative_id, role_ids=sorted(wanted)
        )
        await show_on_saved_layouts(session, plugin, [initiative_id])
    else:
        placement.role_ids = sorted(wanted)
        placement.updated_at = datetime.now(UTC)
    session.add(placement)
    await session.flush()
    return placement


async def set_placed_initiatives(
    session: AsyncSession, plugin: GuildPlugin, initiative_ids: set[int]
) -> None:
    """Place the install in exactly these initiatives.

    Every id must be one of this guild's initiatives, read on the same routed
    session. A placement that stays keeps the roles it had; one that is new
    starts with the initiative's built-in moderator role; one not listed is
    removed.
    """
    for entry in initiative_ids:
        if isinstance(entry, bool) or not isinstance(entry, int):
            raise PlacementError("placement must be a list of initiative ids")
    known = set((await session.exec(select(Initiative.id))).all())
    unknown = sorted(initiative_ids - known)
    if unknown:
        raise PlacementError(f"initiative {unknown[0]} is not one of this guild's")

    current = await placed_initiative_ids(session, plugin.id)
    removed = current - initiative_ids
    if removed:
        await session.exec(
            delete(PluginPlacement).where(
                PluginPlacement.install_id == plugin.id,
                PluginPlacement.initiative_id.in_(sorted(removed)),
            )
        )
    added = sorted(initiative_ids - current)
    roles = await _moderator_role_ids(session, added)
    for initiative_id in added:
        session.add(
            PluginPlacement(
                install_id=plugin.id,
                initiative_id=initiative_id,
                role_ids=_default_role_ids(roles, initiative_id),
            )
        )
    await show_on_saved_layouts(session, plugin, added)
    await session.flush()


async def place_in_every_initiative(session: AsyncSession, plugin: GuildPlugin) -> None:
    """Place the install in every initiative that exists now.

    What installing a mandatory plug-in does. Where it appears afterwards, new
    initiatives included, is the seat's to decide.
    """
    every = set((await session.exec(select(Initiative.id))).all())
    current = await placed_initiative_ids(session, plugin.id)
    added = sorted(every - current)
    roles = await _moderator_role_ids(session, added)
    for initiative_id in added:
        session.add(
            PluginPlacement(
                install_id=plugin.id,
                initiative_id=initiative_id,
                role_ids=_default_role_ids(roles, initiative_id),
            )
        )
    await show_on_saved_layouts(session, plugin, added)
    await session.flush()


async def place_with_roles(
    session: AsyncSession,
    plugin: GuildPlugin,
    initiative_ids: Iterable[int] | None,
    role_names: Iterable[str],
) -> list[int]:
    """Place a new install in these initiatives, each with these built-in roles.

    What the install dialog does. ``None`` is every initiative that exists now,
    the same set "every current initiative" places from the placement panel;
    an initiative created afterwards is placed only if the seat places it.
    Each name must be a built-in role, resolved to that initiative's own role
    of the name. Anything else raises :class:`PlacementError`, before anything
    is written. Answers the initiatives placed, sorted.
    """
    names = list(role_names)
    for name in names:
        if name not in BUILTIN_ROLE_NAMES:
            raise PlacementRoleError(f"{name!r} is not a built-in role")
    known = set((await session.exec(select(Initiative.id))).all())
    if initiative_ids is None:
        chosen = known
    else:
        chosen = set()
        for entry in initiative_ids:
            if isinstance(entry, bool) or not isinstance(entry, int):
                raise PlacementError("placement must be a list of initiative ids")
            chosen.add(entry)
        unknown = sorted(chosen - known)
        if unknown:
            raise PlacementError(f"initiative {unknown[0]} is not one of this guild's")

    placed = sorted(chosen)
    roles = await _builtin_role_ids(session, placed, names)
    for initiative_id in placed:
        session.add(
            PluginPlacement(
                install_id=plugin.id,
                initiative_id=initiative_id,
                role_ids=sorted(roles.get(initiative_id, [])),
            )
        )
    await show_on_saved_layouts(session, plugin, placed)
    await session.flush()
    return placed


def _declared_on(definition: Any, block: str, id_key: str, kind: str) -> list[str]:
    """What a definition declares in one block on one kind of item, in its order."""
    return [
        entry[id_key]
        for entry in _declared(
            definition if isinstance(definition, dict) else {}, block, id_key
        )
        if kind in (entry.get("on") or ())
    ]


def _arriving(
    definition: Any, previous: Any, block: str, id_key: str, kind: str
) -> list[str]:
    """What ``definition`` declares on ``kind`` that ``previous`` did not."""
    had = set(_declared_on(previous, block, id_key, kind))
    return [
        each
        for each in _declared_on(definition, block, id_key, kind)
        if each not in had
    ]


async def show_on_saved_layouts(
    session: AsyncSession,
    plugin: GuildPlugin,
    initiative_ids: Iterable[int],
    *,
    previous: Any = None,
    only: tool_layouts_service.Target | None = None,
) -> None:
    """Show the install's fields, then its parts, on the saved details of these
    initiatives, for each kind of item whose page draws plug-ins, and its task
    fields on their saved boards and tables, as it declares them: what placing
    it does. After an upgrade, ``previous`` is the definition it replaced, and
    only what that did not declare is added. Once added, one a manager takes
    off stays off. A field one of its parts also shows is drawn once, where the
    page is drawn. ``only`` keeps to one target's layouts: a project an import
    has just laid out."""
    initiative_ids = list(initiative_ids)
    for kind in tool_layouts_service.PLUGIN_DETAILS:
        fields = _arriving(plugin.definition, previous, "fields", "key", kind)
        parts = _arriving(plugin.definition, previous, "parts", "id", kind)
        await tool_layouts_service.add_to_saved_details(
            session,
            kind,
            initiative_ids,
            [
                *(
                    {
                        "type": "field",
                        "props": {"field": f"{PLUGIN_FIELD_PREFIX}{plugin.id}:{key}"},
                    }
                    for key in fields
                ),
                *(
                    {"type": "plugin", "props": {"plugin": plugin.id, "part": part}}
                    for part in parts
                ),
            ],
            only=only,
        )
    await tool_layouts_service.add_to_saved_lists(
        session,
        initiative_ids,
        [
            f"{PLUGIN_FIELD_PREFIX}{plugin.id}:{key}"
            for key in _arriving(plugin.definition, previous, "fields", "key", "task")
        ],
        only=only,
    )


async def show_placed_on(
    session: AsyncSession, target: tool_layouts_service.Target
) -> None:
    """Show every install placed in the target's initiative on the target's
    saved layouts, as placing it did on the layouts saved then: a project an
    import has just laid out draws them as a shipped one would."""
    installs = await session.exec(
        select(GuildPlugin)
        .join(PluginPlacement, col(PluginPlacement.install_id) == GuildPlugin.id)
        .where(PluginPlacement.initiative_id == target.initiative_id)
        .order_by(col(GuildPlugin.id))
    )
    for plugin in installs.all():
        await show_on_saved_layouts(
            session, plugin, [target.initiative_id], only=target
        )


# --- opening a surface ------------------------------------------------------
#
# One decision, read by both the handoff mint and the plug-in read that tells the
# client where each surface may be opened, so the two cannot disagree.


class SurfaceAccess(str, Enum):
    """What one viewer gets when opening one surface somewhere."""

    #: The surface may be opened here.
    open = "open"
    #: There is no such surface here: it does not render in this scope, or the
    #: install is not placed in this initiative.
    not_here = "not_here"
    #: The surface is here, and this viewer may not open it.
    refused = "refused"
    #: The surface is here and the viewer's standing would open it, but they
    #: are younger than the plug-in's minimum age where they are.
    too_young = "too_young"


def requested_scopes(definition: Any) -> list[str]:
    """The scopes a pinned definition asks for, in vocabulary order, then the
    ``plugins:`` scopes sorted: a container's in its ``service`` block, a
    declarative plug-in's at the top of its manifest.

    Only known scopes are returned, each once.
    """
    if registration_lookup.is_declarative(definition):
        scopes = definition.get("scopes")
    else:
        service = definition.get("service") if isinstance(definition, dict) else None
        scopes = service.get("scopes") if isinstance(service, dict) else None
    if not isinstance(scopes, list):
        return []
    return ordered_scopes(scopes)


def install_scopes(
    plugin: GuildPlugin, registration: registration_lookup.RegistrationSnapshot
) -> frozenset[str]:
    """The scopes the install acts with now: granted, still requested by the
    pinned version, and within the registration's ceiling."""
    requested = set(requested_scopes(plugin.definition))
    ceiling = set(registration.scope_ceiling)
    return frozenset(
        scope
        for scope in plugin.granted_scopes or ()
        if scope in requested and scope in ceiling
    )


def offered_scopes(definition: Any, installed: Collection[str]) -> list[str]:
    """The requested scopes a seat is asked about, in the order
    :func:`requested_scopes` gives them.

    A ``plugins:`` scope is one only while the plug-in it names is among
    ``installed`` (:func:`installed_plugin_ids`): there is nothing to let a
    plug-in use until the community has it. Installing that plug-in is when the
    seat is asked (:func:`set_plugin_callers`).
    """
    return [
        scope
        for scope in requested_scopes(definition)
        if (target := plugin_scope_target(scope)) is None or target in installed
    ]


def grantable_scopes(
    definition: Any, ceiling: Iterable[str], installed: Collection[str]
) -> list[str]:
    """The offered scopes (:func:`offered_scopes`) the deployment's ceiling allows."""
    allowed = set(ceiling)
    return [
        scope for scope in offered_scopes(definition, installed) if scope in allowed
    ]


async def definition_public_id(definition: dict, listing_uid: str | None) -> str | None:
    """The public id of the plug-in a pinned definition is, for one that is
    installed or about to be: the registration's when this deployment has
    one, else the ``service.public_id`` the definition pinned, which is what
    the plug-in's references key on. ``None`` for a plug-in with no service
    behind it, and for a declarative one with no registration."""
    registration = await registration_lookup.registration_for_definition(
        definition, listing_uid=listing_uid
    )
    if registration is not None:
        return registration.public_id
    return registration_lookup.service_public_id(definition)


async def install_public_id(plugin: GuildPlugin) -> str | None:
    """The public id of the plug-in an existing install is of: what names it,
    acts for it and keys its references, whether or not its registration still
    stands. The registration's when it speaks for this install (its listing,
    and the plug-in the install names), else the one the install pinned;
    ``None`` when a registration stands that is not this install's, or for a
    plug-in with no service behind it.

    Reaching the plug-in's container is another question, which only a live
    registration answers (``registration_lookup.registration_for_definition``)."""
    from app.services.tenant.plugin_channels import owns_install

    registration = await registration_lookup.registration_for_definition(
        plugin.definition, listing_uid=plugin.listing_uid
    )
    if registration is not None:
        return registration.public_id if owns_install(plugin, registration) else None
    if plugin.plugin_kind != "service":
        return None
    return registration_lookup.service_public_id(plugin.definition)


async def installed_plugin_ids(session: AsyncSession) -> frozenset[str]:
    """The public ids of the plug-ins installed in the routed guild."""
    installs = (await session.exec(select(GuildPlugin))).all()
    return frozenset(
        {
            public_id
            for plugin in installs
            if (public_id := await install_public_id(plugin))
        }
    )


async def plugin_callers(
    session: AsyncSession, public_id: str, *, exclude_id: int | None = None
) -> list[GuildPlugin]:
    """The installs here that may be let use ``public_id``: their pinned version
    requests ``plugins:<public_id>`` and their registration's ceiling allows it.
    ``exclude_id`` is the install of ``public_id`` itself."""
    scope = plugin_scope(public_id)
    installs = (
        await session.exec(select(GuildPlugin).order_by(col(GuildPlugin.id)))
    ).all()
    callers = []
    for plugin in installs:
        if plugin.id == exclude_id or scope not in requested_scopes(plugin.definition):
            continue
        state = await registration_lookup.install_state(
            plugin.definition,
            guild_id=routed_guild_id(session),
            listing_uid=plugin.listing_uid,
        )
        if scope in state.scope_ceiling:
            callers.append(plugin)
    return callers


async def set_granted_scopes(
    session: AsyncSession,
    plugin: GuildPlugin,
    scopes: Iterable[str],
    *,
    actor_user_id: int | None,
    guild_id: int,
) -> None:
    """Grant the install exactly ``scopes``, recording the change when there is
    one. The caller has checked them and holds the row."""
    before = sorted(plugin.granted_scopes or [])
    after = sorted(set(scopes))
    if before == after:
        return
    plugin.granted_scopes = after
    plugin.updated_at = datetime.now(UTC)
    session.add(plugin)
    await audit_service.record(
        session,
        event_type=AuditEventType.PLUGIN_UPDATED,
        actor_user_id=actor_user_id,
        guild_id=guild_id,
        target_type="plugin",
        target_id=plugin.id,
        detail={
            "area": "scopes",
            "changed": ["granted_scopes"],
            # Scope names are the platform's own vocabulary, so the values are
            # recorded rather than only the fact that they moved.
            "values": {"granted_scopes": {"from": before, "to": after}},
        },
    )


async def set_plugin_callers(
    session: AsyncSession,
    public_id: str,
    allowed: Collection[int] | None,
    *,
    exclude_id: int | None = None,
    actor_user_id: int | None,
    guild_id: int,
) -> None:
    """Let exactly the ``allowed`` installs use ``public_id`` (``None`` lets every
    one that may be let, :func:`plugin_callers`), and take ``plugins:<public_id>``
    from every other install that holds it.

    Called when ``public_id`` is installed, with the seat's answer, and when it
    is removed, with none, so a later install asks again.
    """
    scope = plugin_scope(public_id)
    # Held, in one order, like a grant the seat sets on its own (:func:`lock_install`).
    installs = (
        await session.exec(
            select(GuildPlugin)
            .order_by(col(GuildPlugin.id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).all()
    callers = {
        plugin.id
        for plugin in await plugin_callers(session, public_id, exclude_id=exclude_id)
        if allowed is None or plugin.id in allowed
    }
    for plugin in installs:
        granted = set(plugin.granted_scopes or ())
        if plugin.id in callers:
            granted.add(scope)
        else:
            granted.discard(scope)
        await set_granted_scopes(
            session, plugin, granted, actor_user_id=actor_user_id, guild_id=guild_id
        )


async def plugin_scope_names(
    session: AsyncSession, scopes: Iterable[str]
) -> dict[str, str]:
    """For each ``plugins:`` scope among ``scopes``, the name the plug-in it names
    goes by in the catalog, keyed by its public id: its registration's
    listing's name, or the public id itself when there is none to read."""
    targets = sorted(
        {target for scope in scopes if (target := plugin_scope_target(scope))}
    )
    if not targets:
        return {}
    registrations = await registration_lookup.load_registrations()
    by_uid = {
        registrations[target].listing_uid: target
        for target in targets
        if target in registrations and registrations[target].listing_uid
    }
    names: dict[str, str] = {}
    if by_uid:
        rows = (
            await session.exec(
                select(MarketplaceListing.uid, MarketplaceListing.name).where(
                    col(MarketplaceListing.uid).in_(list(by_uid))
                )
            )
        ).all()
        names = {by_uid[uid]: name for uid, name in rows}
    return {target: names.get(target, target) for target in targets}


def declared_surfaces(definition: Any) -> list[dict[str, Any]]:
    """The pages a pinned definition declares, well-formed ones only."""
    if not isinstance(definition, dict):
        return []
    pages = definition.get("pages")
    if not isinstance(pages, list):
        return []
    return [
        page
        for page in pages
        if isinstance(page, dict) and isinstance(page.get("id"), str)
    ]


def initiative_surface_ids(definition: Any) -> set[str]:
    """The ids of the surfaces a pinned definition renders inside initiatives."""
    return {
        page["id"]
        for page in declared_surfaces(definition)
        if surface_renders_in(page, "initiative")
    }


def has_initiative_surfaces(definition: Any) -> bool:
    """Whether the plug-in has anything to place in an initiative: a page
    rendering there, or fields, sections or actions on items, which are drawn
    in the item's initiative to whoever its placement admits
    (:data:`ITEM_SURFACE`)."""
    if not isinstance(definition, dict):
        return False
    return bool(
        initiative_surface_ids(definition)
        or _declared(definition, "fields", "key")
        or _declared(definition, "parts", "id")
        or _declared(definition, "actions", "id")
    )


def surface_renders_in(page: dict[str, Any], scope: str) -> bool:
    """Whether a surface asked to render in ``scope``.

    Definitions pinned before a surface could say where it belongs carry no
    ``scopes``, and every one of those is community-wide.
    """
    scopes = page.get("scopes")
    return scope in scopes if isinstance(scopes, list) else scope == "community"


#: What a plug-in adds to an item — its values, its actions — taken as a
#: surface rendered inside the item's initiative, so the same people reach it.
ITEM_SURFACE: dict[str, Any] = {"scopes": ["initiative"]}


def surface_access(
    page: dict[str, Any],
    *,
    initiative_id: int | None,
    placement_role_ids: Collection[int] | None,
    is_guild_admin: bool,
    member_role_ids: Collection[int],
    age_allows: bool = True,
) -> SurfaceAccess:
    """Whether a viewer may open ``page`` where it is being opened.

    ``initiative_id`` is where: ``None`` is the community level. For an
    initiative, ``placement_role_ids`` is that placement's roles, or ``None``
    when the install is not placed there.

    * In an initiative, the install must be placed there, and the viewer is a
      guild admin or holds one of the placement's roles.
    * At the community level, the viewer is a guild admin.
    * A surface marked ``admin_only`` is opened by guild admins alone,
      wherever it is (read by :func:`is_admin_only`, which also honours the
      earlier contract's term on a definition pinned before it).

    ``member_role_ids`` are the viewer's initiative roles across the community.
    A role belongs to one initiative and a placement names only its own
    initiative's roles, so meeting one of them here is holding it here.

    ``age_allows`` is :func:`~app.services.tenant.plugin_age.age_allows` for
    this viewer and plug-in, and it binds admins too: an age limit is about the
    person, not their standing.
    """
    scope = "community" if initiative_id is None else "initiative"
    if not surface_renders_in(page, scope):
        return SurfaceAccess.not_here
    if initiative_id is not None and placement_role_ids is None:
        return SurfaceAccess.not_here
    if not age_allows:
        return SurfaceAccess.too_young
    if is_guild_admin:
        return SurfaceAccess.open
    if initiative_id is None or is_admin_only(page):
        return SurfaceAccess.refused
    allowed = set(placement_role_ids or ())
    if allowed.intersection(member_role_ids):
        return SurfaceAccess.open
    return SurfaceAccess.refused


@dataclass(frozen=True)
class SurfaceOpenability:
    """Where one viewer may open one surface."""

    surface_id: str
    openable_guild_wide: bool
    openable_initiatives: tuple[int, ...]


@dataclass(frozen=True)
class ItemOpenability:
    """Where one viewer meets a plug-in on items, and what of it they meet."""

    #: The initiatives whose items show the viewer the plug-in's values.
    initiatives: tuple[int, ...]
    #: The declared fields and parts whose connections hold what they need.
    fields: tuple[str, ...]
    parts: tuple[str, ...]
    #: The declared actions the viewer may run on those items.
    actions: tuple[str, ...]


def _declared(definition: dict[str, Any], block: str, id_key: str) -> list[dict]:
    entries = definition.get(block)
    return [
        entry
        for entry in (entries if isinstance(entries, list) else [])
        if isinstance(entry, dict) and isinstance(entry.get(id_key), str)
    ]


def item_openability(
    plugin: Any,
    *,
    placements: Sequence[PluginPlacement],
    is_guild_admin: bool,
    member_role_ids: Collection[int],
    age_allows: bool = True,
    frozen: bool = False,
) -> ItemOpenability:
    """:data:`ITEM_SURFACE` measured against each placement, as
    :func:`surface_openability` measures a page. A field, a part or an action
    is offered while the community's connections it requires hold a value
    (:func:`~app.services.tenant.plugin_config.installation_meets`), and an
    action while those its endpoint requires do too. A member's own connection
    an action requires is theirs to make when they run it, and so is one a
    declarative plug-in's endpoint requires, whose call may run on it; a
    container's endpoint is called as the installation. An admin-only action,
    or one whose endpoint is admin-only, is the community's admins' alone, and
    a frozen community runs none."""
    definition = plugin.definition if isinstance(plugin.definition, dict) else {}
    initiatives = tuple(
        row.initiative_id
        for row in sorted(placements, key=lambda row: row.initiative_id)
        if surface_access(
            ITEM_SURFACE,
            initiative_id=row.initiative_id,
            placement_role_ids=list(row.role_ids or []),
            is_guild_admin=is_guild_admin,
            member_role_ids=member_role_ids,
            age_allows=age_allows,
        )
        is SurfaceAccess.open
    )
    if not initiatives:
        return ItemOpenability(initiatives=(), fields=(), parts=(), actions=())

    def met(entry: dict, members_connect: bool = False) -> bool:
        return plugin_config_service.installation_meets(
            plugin, entry.get("requires"), members_connect=members_connect
        )

    declarative = registration_lookup.is_declarative(definition)
    endpoints = {
        endpoint["id"]: endpoint
        for endpoint in _declared(definition, "endpoints", "id")
    }
    return ItemOpenability(
        initiatives=initiatives,
        fields=tuple(
            f["key"] for f in _declared(definition, "fields", "key") if met(f)
        ),
        parts=tuple(p["id"] for p in _declared(definition, "parts", "id") if met(p)),
        actions=()
        if frozen
        else tuple(
            action["id"]
            for action in _declared(definition, "actions", "id")
            if met(action, members_connect=True)
            and met(
                endpoints.get(action.get("endpoint")) or {},
                members_connect=declarative,
            )
            and (
                is_guild_admin
                or not (
                    is_admin_only(action)
                    or is_admin_only(endpoints.get(action.get("endpoint")))
                )
            )
        ),
    )


def surface_openability(
    definition: Any,
    *,
    placements: Sequence[PluginPlacement],
    is_guild_admin: bool,
    member_role_ids: Collection[int],
    age_allows: bool = True,
) -> list[SurfaceOpenability]:
    """Every declared surface, with where this viewer may open it.

    Measured with :func:`surface_access` against each placement the install
    has, which is the same decision the handoff makes.
    """
    ordered = sorted(placements, key=lambda row: row.initiative_id)
    answers: list[SurfaceOpenability] = []
    for page in declared_surfaces(definition):
        guild_wide = surface_access(
            page,
            initiative_id=None,
            placement_role_ids=None,
            is_guild_admin=is_guild_admin,
            member_role_ids=member_role_ids,
            age_allows=age_allows,
        )
        initiatives = tuple(
            row.initiative_id
            for row in ordered
            if surface_access(
                page,
                initiative_id=row.initiative_id,
                placement_role_ids=list(row.role_ids or []),
                is_guild_admin=is_guild_admin,
                member_role_ids=member_role_ids,
                age_allows=age_allows,
            )
            is SurfaceAccess.open
        )
        answers.append(
            SurfaceOpenability(
                surface_id=page["id"],
                openable_guild_wide=guild_wide is SurfaceAccess.open,
                openable_initiatives=initiatives,
            )
        )
    return answers
