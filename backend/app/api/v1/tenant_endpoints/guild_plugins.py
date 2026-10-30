"""Plug-ins installed into a guild.

Reading is open to every member — the sidebar has to know which plug-ins are there,
and a plug-in's existence is guild-wide knowledge. Installing, renaming, disabling,
upgrading, configuring and removing are guild-admin actions: a plug-in mounts a
guild-wide surface, which is the guild's shape rather than any one member's.

**Who connects follows what the credential is.** Where a vendor authorizes a
person, each member connects their own account, no admin is involved, and
installation never waits for anyone to do so. Where it authorizes an
organization — through a page of its own, which is the only way some vendors
grant one — a guild admin runs that flow once for everybody, exactly as they
would fill in the same connection by hand.

Admins govern the install and its guild-wide credentials either way; they can
see who connected as which vendor account and end that access, but they neither
perform another member's connection nor read its values.

What a member may *do* inside a plug-in is not decided here. The content a plug-in
creates carries its own grants, and the tool that owns it enforces them exactly
as it does for initiative content. A plug-in's *pages* are the
exception, because they have no local content to carry grants: the handoff mint
is where who-may-open-this is settled, against where the seat placed the plug-in
and which roles it allowed there.

Two things a guild admin does not govern. A plug-in the deployment marks mandatory
is installed everywhere and is neither removable nor disableable here — the
operator's registration decides whether it exists. And the operator's kill
switch outranks everything: a service whose registration is switched off reaches
nothing, whether or not the guild wanted it.
"""

import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
from sqlalchemy import func, union
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import require_surface_open
from app.core.rules import SURFACE_PLUGINS
from app.api.deps import (
    AgeViewerDep,
    CurrentUser,
    GuildContextDep,
    RLSSessionDep,
    SeatContextDep,
    SeatSessionDep,
    SeatWriteContextDep,
    SeatWriteSessionDep,
    require_first_party_session,
    require_grant_writes,
    require_seat,
)
from app.core.audit_events import AuditEventType
from app.core.messages import (
    GuildPluginMessages,
    InitiativeMessages,
    MarketplaceMessages,
)
from app.core.plugin_scopes import plugin_scope_target
from app.core.rate_limit import limiter
from app.db import post_commit
from app.db.guild_standing import GuildContext
from app.db.query import build_paginated_response, paginated_query
from app.db.session import routed_guild_id
from app.models.platform.guild import GuildMembership
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.guild_plugin_user_connection import GuildPluginUserConnection
from app.models.tenant.initiative import Initiative
from app.models.tenant.plugin_member_consent import PluginMemberConsent
from app.schemas.tenant.guild_plugin import (
    CommunityPluginConfigUpdate,
    CommunityPluginConnectionSummary,
    CommunityPluginConnectStart,
    CommunityPluginConsentAnswer,
    CommunityPluginConsentRead,
    CommunityPluginConsentSummary,
    CommunityPluginDecline,
    CommunityPluginDetail,
    CommunityPluginEntitlementRead,
    CommunityPluginHandoff,
    CommunityPluginInstall,
    CommunityPluginListResponse,
    CommunityPluginMembersResponse,
    CommunityPluginRead,
    CommunityPluginScopesUpdate,
    CommunityPluginSettingUpdate,
    CommunityPluginUninstallNotice,
    CommunityPluginUpdate,
    CommunityPluginUpgrade,
    PluginPlacementRead,
    PluginPlacementUpdate,
    serialize_consent,
    serialize_guild_plugin,
    serialize_guild_plugin_detail,
    serialize_member_connection,
    serialize_member_consent,
    upgrade_asks_read,
)
from app.services import audit as audit_service
from app.services.marketplace import catalog as catalog_service
from app.services.marketplace import (
    plugin_entitlements,
    registration_lookup,
)
from app.services.marketplace import plugin_installs as plugin_installs_service
from app.services.marketplace.definitions import (
    GUILD_INSTALLABLE_PLUGIN_KINDS,
    PLUGIN_KINDS,
)
from app.services.marketplace.installs import (
    count_install,
    resolve_listing_install,
)
from app.services.membership import initiative_scope_clause
from app.services.platform import billing_ping
from app.services.tenant import guild_plugins as guild_plugins_service
from app.services.tenant import plugin_age
from app.services.tenant import plugin_config as plugin_config_service
from app.services.tenant import plugin_connection_flows as flows_service
from app.services.tenant import plugin_connections as connections_service
from app.services.tenant import plugin_handoff as handoff_service
from app.services.tenant import plugin_member_consents as consents_service
from app.services.tenant import plugin_schedules as plugin_schedules_service
from app.services.tenant import plugin_updates as plugin_updates_service
from app.services.tenant.plugin_age import AgeViewer

logger = logging.getLogger(__name__)

router = APIRouter()

#: Configuring this surface, which the deployment may close for one community.
_SURFACE_OPEN = Depends(require_surface_open(SURFACE_PLUGINS))

#: The same installs, reached from inside one initiative. Mounted at the guild
#: root rather than under ``/plugins`` because the initiative comes first in the
#: path — it is what the request is scoped to, and a plug-in is what it is asking
#: about.
initiative_router = APIRouter()


#: What an admin sets on an install itself, as opposed to its configuration or
#: its version. A record of one of these says which of them moved; placement is
#: recorded beside them as ``placed_initiative_ids``.
_PLUGIN_SETTINGS_FIELDS = ("name", "enabled", "auto_update")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


async def _plugin_avatar(session: AsyncSession, plugin: GuildPlugin) -> Optional[str]:
    """The artwork for one install's listing."""
    avatars = await catalog_service.listing_avatars(session, [plugin.listing_uid])
    return avatars.get(plugin.listing_uid)


async def _load_initiative(
    session: RLSSessionDep, initiative_id: int, user_id: int
) -> Initiative:
    """The initiative this request is scoped to, or a 404.

    Scoped with ``initiative_scope_clause`` — the one rule initiative content
    reads use — so what is reachable here is what is reachable anywhere else.
    "Not yours" and "not there" are one answer, as they are on every other
    initiative-scoped read.
    """
    initiative = (
        await session.exec(
            select(Initiative).where(
                Initiative.id == initiative_id,
                initiative_scope_clause(user_id, Initiative.id),
            )
        )
    ).first()
    if initiative is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.NOT_FOUND,
        )
    return initiative


async def _placements(session: AsyncSession, plugin: GuildPlugin) -> list:
    """One install's placement rows, for its serializer."""
    grouped = await guild_plugins_service.placements_by_install(session, [plugin.id])
    return grouped.get(plugin.id, [])


async def _set_placement(
    session: RLSSessionDep, plugin: GuildPlugin, initiative_ids: list[int]
) -> None:
    """Place the install in exactly these initiatives, or a 422.

    The ids are checked on the same routed session the rest of the request runs
    on, so a placement can only ever name an initiative of this guild.
    """
    try:
        await guild_plugins_service.set_placed_initiatives(
            session, plugin, set(initiative_ids)
        )
    except guild_plugins_service.PlacementError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=GuildPluginMessages.PLACEMENT_INVALID,
        ) from exc


async def _plugin_names(
    session: RLSSessionDep, plugin: GuildPlugin, offer: Any
) -> dict[str, str]:
    """The names of the plug-ins the install's ``plugins:`` scopes name, and those a
    pending version's new ones name."""
    scopes = list(guild_plugins_service.requested_scopes(plugin.definition))
    if offer is not None:
        scopes.extend(offer.asks.added_scopes)
    return await guild_plugins_service.plugin_scope_names(session, scopes)


async def _require_grantable(
    session: AsyncSession, granted: set[str], definition: dict, listing_uid: str
) -> None:
    """Refuse a grant the manifest does not request, the ceiling does not allow,
    or that uses a plug-in the community does not have. ``listing_uid`` is the
    listing the definition is a version of, which names a declarative plug-in's
    registration.

    The one check every write of a grant makes: setting the scopes, installing
    with them, and consenting to a version's new ones.
    """
    if not granted <= set(guild_plugins_service.requested_scopes(definition)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=GuildPluginMessages.SCOPE_NOT_REQUESTED,
        )
    registration = await registration_lookup.registration_for_definition(
        definition, listing_uid=listing_uid
    )
    ceiling = set(registration.scope_ceiling) if registration is not None else set()
    if not granted <= ceiling:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=GuildPluginMessages.SCOPE_ABOVE_CEILING,
        )
    installed = await guild_plugins_service.installed_plugin_ids(session)
    if any(
        (target := plugin_scope_target(scope)) is not None and target not in installed
        for scope in granted
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=GuildPluginMessages.SCOPE_TARGET_NOT_INSTALLED,
        )


async def _load(
    session: RLSSessionDep, plugin_id: int, *, for_update: bool = False
) -> GuildPlugin:
    """This guild's install, or a 404.

    ``for_update`` holds the row for the rest of the transaction — see
    :func:`~app.services.tenant.guild_plugins.lock_install`. Anything that rewrites
    a value on this row wants it: removal reads what the install owns, and a
    connect writes the handle map, both of which someone
    else may be changing at the same moment.
    """
    plugin = (
        await guild_plugins_service.lock_install(session, plugin_id)
        if for_update
        else (
            await session.exec(select(GuildPlugin).where(GuildPlugin.id == plugin_id))
        ).first()
    )
    if plugin is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildPluginMessages.NOT_FOUND,
        )
    return plugin


def _require_installable_kind(definition: dict) -> None:
    """Two separate refusals, because they are two different mistakes.

    A listing that is not a plug-in at all is one answer; a plug-in of a *kind* this
    build cannot mount is another. Every kind the vocabulary declares is
    mountable today, so the second refusal is the guard for a kind added ahead
    of the machinery that serves it — reaching the installer with one would
    answer a clear refusal with a 500.
    """
    plugin_kind = definition.get("plugin_kind")
    if plugin_kind not in PLUGIN_KINDS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=GuildPluginMessages.NOT_A_PLUGIN,
        )
    if plugin_kind not in GUILD_INSTALLABLE_PLUGIN_KINDS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=GuildPluginMessages.KIND_NOT_INSTALLABLE,
        )


async def _require_removable(plugin: GuildPlugin, guild_id: int) -> None:
    """Refuse to remove or turn off a plug-in the deployment provides.

    Mandatory constrains guild admins, not the operator: a plug-in marked so on
    its registration stays in every guild until the operator says otherwise.
    The UI omits the affordances entirely, so this answers a request that
    arrived some other way — and it is read from the registration each time, so
    the moment an operator clears the flag the same plug-in becomes removable with
    nothing migrated.
    """
    state = await registration_lookup.install_state(
        plugin.definition, guild_id=guild_id, listing_uid=plugin.listing_uid
    )
    if state.mandatory:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=GuildPluginMessages.MANDATORY,
        )


def _connection_or_404(plugin: GuildPlugin, connection_id: str) -> dict:
    connection = plugin_config_service.connection_by_id(
        plugin.definition, connection_id
    )
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildPluginMessages.CONNECTION_NOT_FOUND,
        )
    return connection


async def _read(
    session: AsyncSession, plugin: GuildPlugin, context: GuildContext, viewer: AgeViewer
) -> CommunityPluginRead:
    """One install as the list reads it."""
    return serialize_guild_plugin(
        plugin,
        viewer=viewer,
        install_state=await registration_lookup.install_state(
            plugin.definition,
            guild_id=context.guild_id,
            listing_uid=plugin.listing_uid,
        ),
        avatar_url=await _plugin_avatar(session, plugin),
        context=context,
        placements=await _placements(session, plugin),
        artifacts=await guild_plugins_service.plugin_artifacts(session, plugin),
    )


async def _entitlement(
    guild_id: int, listing_uid: Optional[str]
) -> Optional[CommunityPluginEntitlementRead]:
    """What the statement held for the install's listing says, if one is."""
    if not listing_uid:
        return None
    statement = await plugin_entitlements.read_statement(guild_id, listing_uid)
    if statement is None:
        return None
    return CommunityPluginEntitlementRead(
        active=plugin_entitlements.statement_active(statement.values),
        reason=plugin_entitlements.statement_reason(statement.values),
    )


async def _detail(
    session: AsyncSession,
    plugin: GuildPlugin,
    context: GuildContext,
    user_id: int,
    viewer: AgeViewer,
    *,
    offer: Optional[plugin_updates_service.UpdateOffer] = None,
) -> CommunityPluginDetail:
    """One install with its connections and consents, as ``user_id`` sees it.

    ``offer`` is the update offered, read here when not given.
    """
    if offer is None:
        offer = await plugin_updates_service.update_offer(session, plugin)
    return serialize_guild_plugin_detail(
        plugin,
        viewer=viewer,
        avatar_url=await _plugin_avatar(session, plugin),
        member_rows=await _member_rows(session, plugin_id=plugin.id, user_id=user_id),
        install_state=await registration_lookup.install_state(
            plugin.definition,
            guild_id=context.guild_id,
            listing_uid=plugin.listing_uid,
        ),
        update_offer=offer,
        installed=await guild_plugins_service.installed_plugin_ids(session),
        plugin_names=await _plugin_names(session, plugin, offer),
        context=context,
        placements=await _placements(session, plugin),
        artifacts=await guild_plugins_service.plugin_artifacts(session, plugin),
        consent_rows=await consents_service.list_member_consents(
            session, install_id=plugin.id, user_id=user_id
        ),
        listing=await catalog_service.get_listing_by_uid(session, plugin.listing_uid),
        entitlement=await _entitlement(context.guild_id, plugin.listing_uid),
    )


def _require_old_enough(plugin: GuildPlugin, viewer: AgeViewer) -> None:
    """Refuse somebody younger than the plug-in's minimum age where they are.

    Per person, on every path a person uses a plug-in through; the install
    itself is never refused for it.
    """
    if not plugin_age.age_allows(plugin.definition, viewer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildPluginMessages.AGE_RESTRICTED,
        )


async def _member_rows(session, *, plugin_id: int, user_id: int) -> dict:
    rows = await connections_service.list_member_connections(
        session, plugin_id=plugin_id, user_id=user_id
    )
    return {row.connection_id: row for row in rows}


# ---------------------------------------------------------------------------
# The install itself
# ---------------------------------------------------------------------------


@router.get("/", response_model=CommunityPluginListResponse)
async def list_community_plugins(
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    viewer: AgeViewerDep,
) -> CommunityPluginListResponse:
    """Every plug-in installed in this guild, enabled or not.

    Disabled ones are included so an admin can find and re-enable them; the
    sidebar filters to enabled. A service plug-in whose registration is gone or
    switched off comes back too, marked unavailable — an install that quietly
    vanished would leave an admin with nothing to look at and nothing to
    remove.
    """
    plugins = (
        await session.exec(
            select(GuildPlugin).order_by(GuildPlugin.name, GuildPlugin.id)
        )
    ).all()
    avatars = await catalog_service.listing_avatars(
        session, [plugin.listing_uid for plugin in plugins]
    )
    placements = await guild_plugins_service.placements_by_install(
        session, [plugin.id for plugin in plugins]
    )
    artifacts = await guild_plugins_service.artifacts_by_install(
        session, [plugin.id for plugin in plugins]
    )
    return CommunityPluginListResponse(
        items=[
            serialize_guild_plugin(
                plugin,
                viewer=viewer,
                install_state=await registration_lookup.install_state(
                    plugin.definition,
                    guild_id=guild_context.guild_id,
                    listing_uid=plugin.listing_uid,
                ),
                avatar_url=avatars.get(plugin.listing_uid),
                context=guild_context,
                placements=placements.get(plugin.id, []),
                artifacts=artifacts.get(plugin.id, []),
            )
            for plugin in plugins
        ]
    )


@router.get("/{plugin_id}", response_model=CommunityPluginDetail)
async def get_community_plugin(
    plugin_id: int,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    viewer: AgeViewerDep,
) -> CommunityPluginDetail:
    """One install with its connections, from the caller's own perspective.

    Any member may read this: the per-member connection blocks report the
    caller's own state, and a guild-scoped one reports presence rather than
    values to everybody but the seat that sets them, so there is nothing here
    that belongs to somebody else.
    """
    plugin = await _load(session, plugin_id)
    return await _detail(session, plugin, guild_context, current_user.id, viewer)


@router.post(
    "/", response_model=CommunityPluginRead, status_code=status.HTTP_201_CREATED, dependencies=[_SURFACE_OPEN])
async def install_community_plugin(
    payload: CommunityPluginInstall,
    session: SeatWriteSessionDep,
    current_user: CurrentUser,
    guild_context: SeatWriteContextDep,
    viewer: AgeViewerDep,
) -> CommunityPluginRead:
    """Install a listing as a guild plug-in.

    The request names a listing; everything stored comes from the catalog row
    and from what the install creates here. One install per listing: a plug-in
    mounts a single guild-wide surface, so a second copy would have nothing to
    be — rename or re-share the one that exists instead.

    Nothing about connections gates this. A plug-in whose credentials are all
    supplied per member installs with none present, and members connect their
    own accounts afterwards if they want what those unlock.

    The install dialog is the seat's consent, and it lands with the install in
    one transaction: the scopes granted (checked as ``PUT …/scopes`` checks
    them), the initiatives the plug-in is placed in (``"all"`` is every initiative
    that exists now), and the built-in roles that open it in each. Anything
    refused is refused before the install exists.
    """
    unknown_roles = set(payload.role_kinds) - set(
        guild_plugins_service.BUILTIN_ROLE_NAMES
    )
    if unknown_roles:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=GuildPluginMessages.PLACEMENT_ROLE_INVALID,
        )

    listing, version = await resolve_listing_install(
        session, payload.listing_uid, kind="plugin"
    )
    if await plugin_entitlements.entitlement_blocks(
        guild_context.guild_id, listing.uid, session
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=GuildPluginMessages.ENTITLEMENT_REQUIRED,
        )

    existing = (
        await session.exec(
            select(GuildPlugin).where(GuildPlugin.listing_uid == listing.uid)
        )
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=GuildPluginMessages.ALREADY_INSTALLED,
        )

    definition = dict(version.definition)
    _require_installable_kind(definition)
    granted = set(payload.granted_scopes)
    await _require_grantable(session, granted, definition, listing.uid)

    name = (payload.name or definition.get("default_name") or listing.name).strip()
    try:
        plugin = await guild_plugins_service.install_plugin(
            session,
            listing_uid=listing.uid,
            listing_version=version.version,
            definition=definition,
            guild_id=guild_context.guild_id,
            created_by=current_user.id,
            name=name,
            actor_user_id=current_user.id,
            granted_scopes=sorted(granted),
            allowed_callers=payload.callers,
        )
        if payload.placements:
            await guild_plugins_service.place_with_roles(
                session,
                plugin,
                None if payload.placements == "all" else payload.placements,
                payload.role_kinds,
            )
        await session.commit()
    except guild_plugins_service.ErasePendingError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=GuildPluginMessages.ERASE_PENDING,
        ) from exc
    except guild_plugins_service.PlacementError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                GuildPluginMessages.PLACEMENT_ROLE_INVALID
                if isinstance(exc, guild_plugins_service.PlacementRoleError)
                else GuildPluginMessages.PLACEMENT_INVALID
            ),
        ) from exc
    except IntegrityError as exc:
        # The look-up above and this insert are not one atomic step, so two
        # installs arriving together both get past it. The unique constraint is
        # what actually holds — at the flush inside the install or at the commit
        # — and this turns losing that race into the same answer the look-up
        # gives.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=GuildPluginMessages.ALREADY_INSTALLED,
        ) from exc
    await session.refresh(plugin)
    await guild_plugins_service.assign_settings(
        session, plugin, guild_id=guild_context.guild_id
    )
    await plugin_schedules_service.reconcile(
        guild_context.guild_id, plugin.id, plugin.definition
    )

    installed = await _read(session, plugin, guild_context, viewer)
    await count_install(guild_context.guild_id, listing.id)
    return installed


@router.post("/{plugin_id}/upgrade", response_model=CommunityPluginDetail, dependencies=[_SURFACE_OPEN])
async def upgrade_community_plugin(
    plugin_id: int,
    session: SeatWriteSessionDep,
    current_user: CurrentUser,
    guild_context: SeatWriteContextDep,
    viewer: AgeViewerDep,
    payload: Optional[CommunityPluginUpgrade] = None,
) -> CommunityPluginDetail:
    """Re-pin an installed plug-in to its listing's current version, now.

    The button an admin presses when their guild has turned automatic updates
    off — and the shortcut past the sweep for one that has not. Either way it is
    the same re-pin ``services.tenant.plugin_updates`` performs on its own
    schedule, so an install cannot end up in a state only one of the two routes
    can produce.

    Stored configuration survives, minus anything the new version stopped
    declaring — a value cannot outlive the field it was typed into. Per-member
    connections the new version dropped go the same way, and are revoked rather
    than orphaned.

    A version that asks for more than the install holds (a new scope, or a
    new surface inside initiatives) is applied only with the seat's consent:
    ``payload`` names the version the seat was shown and the scopes it grants
    with it. Without it the answer is 409, carrying what the version asks
    for; so is a consent naming a version the catalog no longer offers.
    """
    # Upgrading prunes both configuration maps to the new definition, so it
    # takes the row: a plug-in writing a flow's result back at the same moment
    # must land on one side of the prune or the other.
    plugin = await _load(session, plugin_id, for_update=True)

    # The listing is resolved here rather than inside the shared apply, so a
    # withdrawn or missing one is reported as the HTTP answer it deserves
    # instead of reading as "nothing to update to".
    _, version = await resolve_listing_install(
        session, plugin.listing_uid, kind="plugin", already_installed=True
    )
    if version.version == plugin.listing_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=MarketplaceMessages.ALREADY_LATEST_VERSION,
        )

    definition = dict(version.definition)
    _require_installable_kind(definition)

    registration = await registration_lookup.registration_for_definition(
        definition, listing_uid=plugin.listing_uid
    )
    asks = plugin_updates_service.upgrade_asks(
        plugin,
        definition,
        registration.scope_ceiling if registration else (),
        await guild_plugins_service.installed_plugin_ids(session),
    )
    if (payload is not None and payload.version != version.version) or (
        payload is None and asks.asks_more
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": (
                    GuildPluginMessages.UPGRADE_NEEDS_CONSENT
                    if payload is None
                    else GuildPluginMessages.UPGRADE_VERSION_MOVED
                ),
                **upgrade_asks_read(
                    version.version,
                    asks,
                    declined=plugin.declined_version == version.version,
                ).model_dump(),
            },
        )
    add_scopes = set(payload.add_scopes) if payload is not None else set()
    await _require_grantable(session, add_scopes, definition, plugin.listing_uid)

    previous_version = plugin.listing_version
    previous_grant = sorted(plugin.granted_scopes or [])
    await plugin_updates_service.apply_version(
        session,
        plugin,
        plugin_updates_service.PendingUpdate(
            version=version.version, definition=definition
        ),
        guild_id=guild_context.guild_id,
        add_scopes=add_scopes,
    )
    record: dict[str, Any] = {
        "area": "version",
        "from": previous_version,
        "to": version.version,
    }
    if sorted(plugin.granted_scopes or []) != previous_grant:
        # Scope names are the platform's own vocabulary, so the values are
        # recorded rather than only the fact that they moved.
        record["changed"] = ["granted_scopes"]
        record["values"] = {
            "granted_scopes": {
                "from": previous_grant,
                "to": sorted(plugin.granted_scopes or []),
            }
        }
    await audit_service.record(
        session,
        event_type=AuditEventType.PLUGIN_UPDATED,
        actor_user_id=current_user.id,
        guild_id=guild_context.guild_id,
        target_type="plugin",
        target_id=plugin.id,
        detail=record,
    )
    await session.commit()
    await session.refresh(plugin)
    await guild_plugins_service.assign_settings(
        session, plugin, guild_id=guild_context.guild_id
    )
    await plugin_updates_service.reconcile_repinned(guild_context.guild_id, plugin)
    return await _detail(session, plugin, guild_context, current_user.id, viewer)


@router.post("/{plugin_id}/upgrade/decline", response_model=CommunityPluginDetail, dependencies=[_SURFACE_OPEN])
async def decline_community_plugin_upgrade(
    plugin_id: int,
    payload: CommunityPluginDecline,
    session: SeatWriteSessionDep,
    current_user: CurrentUser,
    guild_context: SeatWriteContextDep,
    viewer: AgeViewerDep,
) -> CommunityPluginDetail:
    """Keep the pinned version, and stop being asked about this one.

    The install goes on running the version it has, with the grant it has.
    The sweep does not ask about the declined version again; a newer one is
    asked about afresh. Accepting it later is still the Update button.
    """
    plugin = await _load(session, plugin_id, for_update=True)
    offer = await plugin_updates_service.update_offer(session, plugin)
    if offer is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=MarketplaceMessages.ALREADY_LATEST_VERSION,
        )
    if offer.version != payload.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=GuildPluginMessages.UPGRADE_VERSION_MOVED,
        )
    if plugin.declined_version != payload.version:
        plugin_updates_service.decline_version(plugin, payload.version)
        session.add(plugin)
        await audit_service.record(
            session,
            event_type=AuditEventType.PLUGIN_UPDATED,
            actor_user_id=current_user.id,
            guild_id=guild_context.guild_id,
            target_type="plugin",
            target_id=plugin.id,
            detail={"area": "version", "declined": payload.version},
        )
    await session.commit()
    await session.refresh(plugin)
    return await _detail(
        session, plugin, guild_context, current_user.id, viewer, offer=offer
    )


@router.patch("/{plugin_id}", response_model=CommunityPluginRead, dependencies=[_SURFACE_OPEN])
async def update_community_plugin(
    plugin_id: int,
    payload: CommunityPluginUpdate,
    session: SeatWriteSessionDep,
    current_user: CurrentUser,
    guild_context: SeatWriteContextDep,
    viewer: AgeViewerDep,
) -> CommunityPluginRead:
    """Rename a plug-in, place it, choose how it updates, or turn it off.

    Renaming is always allowed — a guild may call a plug-in whatever it likes.
    Turning one off is a different matter for a plug-in the deployment provides:
    that switch belongs to the operator, so it is refused by name here.

    ``auto_update`` is the guild's own cadence, and it is on until an admin says
    otherwise. Turning it off does not freeze the plug-in — it moves the decision to
    this page, where the Update button applies exactly what the sweep would
    have. It is offered on every install, provided ones included: the operator
    decides whether a plug-in exists, and the guild decides when it changes under
    them.

    ``placed_initiative_ids`` is the whole set of initiatives a plug-in's
    initiative-scoped surfaces appear in. An initiative that stays placed keeps
    the roles it had, a new one starts with its moderator role, and one left out
    is removed. It is the community's own answer to where a plug-in belongs rather
    than a permission, so it reads the same for everyone, admins included.
    """
    plugin = await _load(session, plugin_id)

    before = {
        **audit_service.snapshot(plugin, _PLUGIN_SETTINGS_FIELDS),
        "placed_initiative_ids": sorted(
            await guild_plugins_service.placed_initiative_ids(session, plugin.id)
        ),
    }
    data = payload.model_dump(exclude_unset=True)
    if data.get("name"):
        plugin.name = data["name"].strip()
    if "enabled" in data and data["enabled"] is not None:
        if not data["enabled"]:
            await _require_removable(plugin, guild_context.guild_id)
        plugin.enabled = data["enabled"]
    if data.get("auto_update") is not None:
        plugin.auto_update = data["auto_update"]
    if data.get("placed_initiative_ids") is not None:
        await _set_placement(session, plugin, data["placed_initiative_ids"])
    plugin.updated_at = datetime.now(timezone.utc)
    session.add(plugin)
    after = {
        **audit_service.snapshot(plugin, _PLUGIN_SETTINGS_FIELDS),
        "placed_initiative_ids": sorted(
            await guild_plugins_service.placed_initiative_ids(session, plugin.id)
        ),
    }
    changed = audit_service.changed_fields(before, after)
    if changed["changed"]:
        await audit_service.record(
            session,
            event_type=AuditEventType.PLUGIN_UPDATED,
            actor_user_id=current_user.id,
            guild_id=guild_context.guild_id,
            target_type="plugin",
            target_id=plugin.id,
            detail={"area": "settings", **changed},
        )
    await session.commit()
    await session.refresh(plugin)
    return await _read(session, plugin, guild_context, viewer)


@router.get(
    "/{plugin_id}/uninstall-notice", response_model=CommunityPluginUninstallNotice
)
@limiter.limit("30/minute")
async def read_uninstall_notice(
    request: Request,
    plugin_id: int,
    session: SeatSessionDep,
    guild_context: SeatContextDep,
    locale: Annotated[
        str, Query(max_length=35, pattern=r"^[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*$")
    ] = "en",
) -> CommunityPluginUninstallNotice:
    """What the removal dialog says about this plug-in beyond the usual.

    For a plug-in whose listing carries package terms, the entitlement issuer
    is asked, for this response only and within two seconds, what removing it
    means for this community; its sentence comes back as it gave it. Anything
    else is ``managed: false``. Read by the seat, which is who removes one.
    """
    plugin = await _load(session, plugin_id)
    listing_uid = plugin.listing_uid
    if (
        not listing_uid
        or await plugin_entitlements.listing_terms(listing_uid, session) is None
    ):
        return CommunityPluginUninstallNotice()
    notice = await billing_ping.plugin_uninstall_notice(
        guild_context.guild_id, listing_uid=listing_uid, locale=locale
    )
    fallback = plugin_entitlements.action_url(listing_uid)
    if notice is None:
        return CommunityPluginUninstallNotice(managed=True, action_url=fallback)
    return CommunityPluginUninstallNotice(
        managed=True,
        message=notice.message,
        action_url=notice.action_url or fallback,
    )


@router.delete("/{plugin_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_SURFACE_OPEN])
async def uninstall_community_plugin(
    plugin_id: int,
    session: SeatWriteSessionDep,
    current_user: CurrentUser,
    guild_context: SeatWriteContextDep,
    background_tasks: BackgroundTasks,
    erase: Annotated[bool, Query()] = False,
) -> None:
    """Remove a plug-in, ending its access and trashing what it created
    (:func:`~app.services.tenant.guild_plugins.uninstall_plugin`).

    What the plug-in calls the community and its members is kept, so installing
    it again picks up where it left off. ``erase`` also asks the plug-in to
    delete everything it holds about the community, and forgets those names
    once it has: the community's admins' choice alone (403
    ``COMMUNITY_PLUGIN_ERASE_ADMIN_ONLY`` for anyone else).

    A plug-in the deployment provides to every guild is not removable here, and
    so not erasable either (§7.7): the operator's registration decides whether
    it exists at all.
    """
    # Held for the rest of this transaction, so a calendar being given to the
    # plug-in either lands before this read and is trashed with everything else, or
    # finds no install and is refused.
    plugin = await _load(session, plugin_id, for_update=True)
    await _require_removable(plugin, guild_context.guild_id)
    if erase and not guild_context.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildPluginMessages.ERASE_ADMIN_ONLY,
        )

    install_id, guild_id = plugin.id, routed_guild_id(session)
    await guild_plugins_service.uninstall_plugin(
        session, plugin, actor_user_id=current_user.id, erase=erase
    )
    await session.commit()
    await plugin_installs_service.forget(guild_id, install_id)
    background_tasks.add_task(post_commit.settle, session)


# ---------------------------------------------------------------------------
# Guild-scoped configuration
# ---------------------------------------------------------------------------


@router.put("/{plugin_id}/config", response_model=CommunityPluginDetail, dependencies=[_SURFACE_OPEN])
async def update_community_plugin_config(
    plugin_id: int,
    payload: CommunityPluginConfigUpdate,
    session: SeatWriteSessionDep,
    current_user: CurrentUser,
    guild_context: SeatWriteContextDep,
    viewer: AgeViewerDep,
) -> CommunityPluginDetail:
    """Set the guild-wide values a plug-in's connections ask for.

    Validated against the *pinned* definition, so what an install accepts is the
    form it was configured against rather than whatever the catalog says today.
    Secret fields are encrypted on the way in and never come back out; the
    response reports which fields hold a value.

    Only guild-scoped connections are settable here. A per-member one is that
    member's to make, and the fields a plug-in marks ``managed`` come from its
    ``after_connect`` hook when a flow completes rather than through a form.
    """
    # Both configuration maps are rewritten whole below, so the row is taken
    # first — a flow completing is doing the same thing to the same values.
    plugin = await _load(session, plugin_id, for_update=True)
    await guild_plugins_service.apply_static_config(
        session, plugin, payload.values, actor_user_id=current_user.id
    )
    await session.commit()
    await session.refresh(plugin)
    return await _detail(session, plugin, guild_context, current_user.id, viewer)


@router.put("/{plugin_id}/settings/{key}", response_model=CommunityPluginDetail, dependencies=[_SURFACE_OPEN])
async def update_community_plugin_setting(
    plugin_id: int,
    key: str,
    payload: CommunityPluginSettingUpdate,
    session: SeatWriteSessionDep,
    current_user: CurrentUser,
    guild_context: SeatWriteContextDep,
    viewer: AgeViewerDep,
) -> CommunityPluginDetail:
    """Set one of the values the plug-in's settings declare.

    Validated against the *pinned* definition. A unique setting holds a
    lowercase letter, then lowercase letters and digits, 2 to 16 in all
    (``COMMUNITY_PLUGIN_SETTING_INVALID`` otherwise), that no other community
    on this server holds, now or as an earlier value
    (``COMMUNITY_PLUGIN_SETTING_UNAVAILABLE`` otherwise). The value it replaces
    stays this community's, and the plug-in still reads it; setting it again
    makes it current.
    """
    plugin = await _load(session, plugin_id, for_update=True)
    await guild_plugins_service.set_setting(
        session,
        plugin,
        key,
        payload.value,
        guild_id=guild_context.guild_id,
        actor_user_id=current_user.id,
    )
    await session.refresh(plugin)
    return await _detail(session, plugin, guild_context, current_user.id, viewer)


# ---------------------------------------------------------------------------
# Placement and scopes, set by the seat
# ---------------------------------------------------------------------------


@router.put(
    "/{plugin_id}/placements/{initiative_id}", response_model=PluginPlacementRead, dependencies=[_SURFACE_OPEN])
async def put_community_plugin_placement(
    plugin_id: int,
    initiative_id: int,
    payload: PluginPlacementUpdate,
    session: SeatWriteSessionDep,
    current_user: CurrentUser,
    guild_context: SeatWriteContextDep,
) -> PluginPlacementRead:
    """Place the plug-in in one initiative with exactly these roles.

    Creates the placement or replaces its roles. Every role must be one of that
    initiative's; guild admins open the plug-in there whatever the roles say.
    """
    plugin = await _load(session, plugin_id)
    before = await guild_plugins_service.placement_role_ids(
        session, plugin.id, initiative_id
    )
    try:
        placement = await guild_plugins_service.set_placement_roles(
            session, plugin, initiative_id, payload.role_ids
        )
    except guild_plugins_service.PlacementRoleError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=GuildPluginMessages.PLACEMENT_ROLE_INVALID,
        ) from exc
    except guild_plugins_service.PlacementError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=GuildPluginMessages.PLACEMENT_INVALID,
        ) from exc
    after = list(placement.role_ids or [])
    changed = audit_service.changed_fields(
        {"placed": before is not None, "role_ids": before},
        {"placed": True, "role_ids": after},
    )
    if changed["changed"]:
        await audit_service.record(
            session,
            event_type=AuditEventType.PLUGIN_UPDATED,
            actor_user_id=current_user.id,
            guild_id=guild_context.guild_id,
            target_type="plugin",
            target_id=plugin.id,
            detail={"area": "placement", "initiative_id": initiative_id, **changed},
        )
    await session.commit()
    return PluginPlacementRead(initiative_id=initiative_id, role_ids=after)


@router.put("/{plugin_id}/scopes", response_model=CommunityPluginRead, dependencies=[_SURFACE_OPEN])
async def put_community_plugin_scopes(
    plugin_id: int,
    payload: CommunityPluginScopesUpdate,
    session: SeatWriteSessionDep,
    current_user: CurrentUser,
    guild_context: SeatWriteContextDep,
    viewer: AgeViewerDep,
) -> CommunityPluginRead:
    """Grant the install exactly these scopes.

    Each must be one the plug-in's manifest requests and one the deployment's
    registration allows the plug-in (its ceiling). The whole set is replaced: a
    scope left out is withdrawn.
    """
    plugin = await _load(session, plugin_id, for_update=True)

    granted = set(payload.granted)
    await _require_grantable(session, granted, plugin.definition, plugin.listing_uid)
    await guild_plugins_service.set_granted_scopes(
        session,
        plugin,
        granted,
        actor_user_id=current_user.id,
        guild_id=guild_context.guild_id,
    )
    await session.commit()
    await session.refresh(plugin)
    return await _read(session, plugin, guild_context, viewer)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@router.post("/{plugin_id}/handoff/{surface_id}", response_model=CommunityPluginHandoff)
async def create_community_plugin_handoff(
    plugin_id: int,
    surface_id: str,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    viewer: AgeViewerDep,
) -> CommunityPluginHandoff:
    """Mint the short-lived credential for one of this plug-in's pages.

    Whether the surface may be opened is decided here, under the caller's real
    session, so the plug-in never makes that call and never sees a request from
    somebody who failed it. At the community level only the guild's admins open
    a surface.

    The token goes to the iframe by ``postMessage`` — never a query string —
    and expires in a minute.
    """
    plugin = await _load(session, plugin_id)
    handoff = await handoff_service.mint_page_handoff(
        session,
        plugin,
        surface_id=surface_id,
        context=guild_context,
        viewer=viewer,
        # This route reaches a guild and names no initiative. A surface that
        # renders only inside one is not offered here.
        initiative_id=None,
    )
    # The mint records this member's subject the first time it is needed, and
    # the token naming it is about to leave — so it is committed before then.
    await session.commit()
    return _handoff_response(handoff)


@initiative_router.post(
    "/initiatives/{initiative_id}/plugins/{plugin_id}/handoff/{surface_id}",
    response_model=CommunityPluginHandoff,
    tags=["plugins"],
)
async def create_initiative_plugin_handoff(
    initiative_id: int,
    plugin_id: int,
    surface_id: str,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    viewer: AgeViewerDep,
) -> CommunityPluginHandoff:
    """Mint the credential for a surface opened inside one initiative.

    The install is the guild's — there is one of it, not one per initiative —
    but the surface is being opened somewhere narrower, and the token says so.

    Three gates, outermost first. The initiative must be one this caller can
    reach. The manifest must declare the surface for this scope, and the seat
    must have placed the plug-in here. And the caller must hold one of the roles
    that placement allows — or be a guild admin, as everywhere in their own
    guild. A surface marked ``admin_only`` is for the admins alone.

    The initiative in the minted token is this route's, never the caller's to
    supply, so a plug-in can scope what it shows without asking a second question
    or trusting a parameter.
    """
    initiative = await _load_initiative(session, initiative_id, current_user.id)
    plugin = await _load(session, plugin_id)
    handoff = await handoff_service.mint_page_handoff(
        session,
        plugin,
        surface_id=surface_id,
        context=guild_context,
        viewer=viewer,
        initiative_id=initiative.id,
    )
    await session.commit()
    return _handoff_response(handoff)


def _handoff_response(handoff: handoff_service.PageHandoff) -> CommunityPluginHandoff:
    """The same answer either route gives.

    The initiative is not in it: it is a claim in the token, and the browser
    already knows which initiative it is looking at.
    """
    return CommunityPluginHandoff(
        handoff_token=handoff.token,
        expires_in_seconds=handoff.expires_in_seconds,
        page_url=handoff.page_url,
        allowed_origins=list(handoff.allowed_origins),
        audience=handoff.audience,
        surface_id=handoff.surface_id,
    )


# ---------------------------------------------------------------------------
# Starting a vendor's flow
# ---------------------------------------------------------------------------


@router.post(
    "/{plugin_id}/connections/{connection_id}/connect",
    response_model=CommunityPluginConnectStart, dependencies=[_SURFACE_OPEN])
async def connect_community_plugin(
    plugin_id: int,
    connection_id: str,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    viewer: AgeViewerDep,
) -> CommunityPluginConnectStart:
    """Start the vendor flow behind one connection.

    Two kinds run through here, and the connection's scope decides which:

    * **A member's own account.** Any member may, because the vendor is going to
      authorize *them* and what the resulting credential reaches is what they
      already reach.
    * **The guild's own credential**, where the vendor authorizes an
      organization through a page of its own rather than through anything an
      admin could type. The seat only — it is one credential for everybody.

    Initiative runs the flow: the answer is the vendor's own address (its
    authorization page, or its install page for a connection an organization
    installs), and the vendor returns the person to Initiative's callback.
    Nothing is stored until it does.
    """
    plugin = await _load(session, plugin_id)
    _require_old_enough(plugin, viewer)
    if not plugin.enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=GuildPluginMessages.DISABLED
        )

    connection = _connection_or_404(plugin, connection_id)
    if not plugin_config_service.runs_vendor_flow(connection):
        # Nothing to run and nowhere to send anybody. A guild-wide connection
        # without a flow is a form, and is filled in through the config route.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=GuildPluginMessages.CONNECTION_NOT_INTERACTIVE,
        )
    guild_wide = connection.get("scope") == "static"
    if guild_wide:
        require_seat(guild_context)
        require_grant_writes(guild_context)

    registration = await handoff_service.require_live_registration(
        plugin, guild_context.guild_id
    )

    if guild_wide:
        stored_config = (plugin.config or {}).get(connection_id) or {}
        satisfied = plugin_config_service.is_satisfied(
            connection,
            stored_config,
            (plugin.secret_fields or {}).get(connection_id) or {},
        )
        current_status = "connected" if satisfied else "pending"
        user_id = None
    else:
        existing = await connections_service.get_connection(
            session,
            plugin_id=plugin.id,
            connection_id=connection_id,
            user_id=current_user.id,
        )
        if connections_service.is_blocked(existing):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=GuildPluginMessages.CONNECTION_BLOCKED,
            )
        stored_config = existing.config if existing is not None else {}
        current_status = existing.status if existing is not None else "pending"
        user_id = current_user.id

    connect_url = await flows_service.start_url(
        plugin=plugin,
        connection=connection,
        guild_id=guild_context.guild_id,
        user_id=user_id,
        started_by=current_user.id,
        public_id=registration.public_id,
        fields=plugin_config_service.without_tokens(stored_config),
    )
    return CommunityPluginConnectStart(
        connection_id=connection_id,
        connect_url=connect_url,
        status=current_status,
    )


@router.delete(
    "/{plugin_id}/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_SURFACE_OPEN])
async def disconnect_community_plugin(
    plugin_id: int,
    connection_id: str,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> None:
    """Disconnect: a member's own account, or a guild-wide credential.

    Which one depends on the connection's scope, not on who is asking. A
    per-member connection is always the caller's own — an admin ending somebody
    else's uses the Members endpoints, which record who acted. Clearing a
    guild-wide credential is an admin action, since it is the guild's.
    """
    plugin = await _load(session, plugin_id)
    connection = _connection_or_404(plugin, connection_id)

    if connection.get("scope") == "static":
        require_seat(guild_context)
        require_grant_writes(guild_context)
        # Clearing rewrites both configuration maps, so it takes the row: a plug-in
        # writing back at the same moment must not put back what was cleared.
        plugin = await _load(session, plugin_id, for_update=True)
        await guild_plugins_service.clear_static_connection(
            session, plugin, connection_id
        )
    else:
        await connections_service.disconnect(
            session,
            plugin=plugin,
            connection_id=connection_id,
            user_id=current_user.id,
        )

    await session.commit()


# ---------------------------------------------------------------------------
# Acting as a member
# ---------------------------------------------------------------------------


async def _own_consent(
    session: AsyncSession, *, plugin_id: int, consent_id: int, user_id: int
) -> PluginMemberConsent:
    """One of the caller's own requests from this plug-in, or 404."""
    row = await consents_service.get_member_consent(
        session, consent_id=consent_id, install_id=plugin_id, user_id=user_id
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildPluginMessages.CONSENT_NOT_FOUND,
        )
    return row


@router.put(
    "/{plugin_id}/consents/{consent_id}", response_model=CommunityPluginConsentRead
)
async def grant_my_consent(
    plugin_id: int,
    consent_id: int,
    payload: CommunityPluginConsentAnswer,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    credential: Annotated[str, Depends(require_first_party_session)],
    viewer: AgeViewerDep,
) -> CommunityPluginConsentRead:
    """Allow this plug-in to act as you for one of its requests, at ``access``.

    Never more than the plug-in asked for. Acts on the caller alone and takes no
    user id. Signed-in only (``require_first_party_session``), and the way you
    signed in is recorded with the answer.
    """
    plugin = await _load(session, plugin_id)
    _require_old_enough(plugin, viewer)
    row = await _own_consent(
        session, plugin_id=plugin.id, consent_id=consent_id, user_id=current_user.id
    )
    try:
        row = await consents_service.grant(
            session,
            row,
            access=payload.access,
            confirmed_factor=credential,
            actor_user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildPluginMessages.CONSENT_EXCEEDS_REQUEST,
        ) from exc
    await session.commit()
    await session.refresh(row)
    return serialize_consent(row)


@router.delete(
    "/{plugin_id}/consents/{consent_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def revoke_my_consent(
    plugin_id: int,
    consent_id: int,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> None:
    """Decline one of this plug-in's requests, or withdraw what you allowed. The
    plug-in stops acting as you for it on its next request."""
    plugin = await _load(session, plugin_id)
    row = await _own_consent(
        session, plugin_id=plugin.id, consent_id=consent_id, user_id=current_user.id
    )
    await consents_service.revoke(
        session,
        row,
        revoked_by_id=current_user.id,
        actor_user_id=current_user.id,
    )
    await session.commit()


# ---------------------------------------------------------------------------
# Admin governance of members' connections
# ---------------------------------------------------------------------------


@router.get("/{plugin_id}/members", response_model=CommunityPluginMembersResponse)
async def list_community_plugin_members(
    plugin_id: int,
    session: SeatSessionDep,
    current_user: CurrentUser,
    guild_context: SeatContextDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> CommunityPluginMembersResponse:
    """Who has connected which of this plug-in's per-member connections, and who
    answered its requests to act as them — a page of members at a time.

    Guild admins only, and never secret values: what this supports is governance
    — seeing which vendor account somebody connected as, and ending it — rather
    than looking at credentials.
    """
    plugin = await _load(session, plugin_id)

    member_count = (
        await session.exec(
            select(func.count()).where(
                GuildMembership.guild_id == guild_context.guild_id
            )
        )
    ).one()
    tallies = await connections_service.connection_tallies(session, plugin_id=plugin.id)

    summary: list[CommunityPluginConnectionSummary] = []
    for connection in plugin_config_service.definition_connections(plugin.definition):
        if connection.get("scope") != "interactive":
            continue
        connection_id = connection.get("id") or ""
        connected, blocked = tallies.get(connection_id, (0, 0))
        summary.append(
            CommunityPluginConnectionSummary(
                connection_id=connection_id,
                label=connection.get("label") or {},
                connected_count=connected,
                blocked_count=blocked,
                member_count=member_count,
            )
        )

    # Everybody with a connection to this plug-in or an answer to one of its
    # requests, once each.
    members = union(
        select(GuildPluginUserConnection.user_id).where(
            GuildPluginUserConnection.plugin_id == plugin.id
        ),
        select(PluginMemberConsent.user_id).where(
            PluginMemberConsent.install_id == plugin.id
        ),
    ).subquery()
    user_ids, total_count, actual_page = await paginated_query(
        session,
        select(members.c.user_id).order_by(members.c.user_id),
        select(func.count()).select_from(members),
        page=page,
        page_size=page_size,
    )

    rows = await connections_service.list_plugin_connections(
        session, plugin_id=plugin.id, user_ids=user_ids
    )
    consents = await consents_service.list_install_consents(
        session, install_id=plugin.id, user_ids=user_ids
    )
    consent_tallies = await consents_service.consent_tallies(
        session, install_id=plugin.id
    )
    return CommunityPluginMembersResponse(
        **build_paginated_response(
            [serialize_member_connection(row) for row in rows],
            total_count,
            actual_page,
            page_size,
            summary=summary,
            consents=[serialize_member_consent(row) for row in consents],
            consent_summary=CommunityPluginConsentSummary(
                member_count=consent_tallies.members,
                allowed_count=consent_tallies.allowed,
                open_count=consent_tallies.open,
            ),
        )
    )


@router.delete(
    "/{plugin_id}/members/{user_id}/connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_member_connection(
    plugin_id: int,
    user_id: int,
    connection_id: str,
    session: SeatWriteSessionDep,
    current_user: CurrentUser,
    guild_context: SeatWriteContextDep,
) -> None:
    """End one member's connection. They may connect again unless blocked."""
    plugin = await _load(session, plugin_id)
    _connection_or_404(plugin, connection_id)

    await connections_service.disconnect(
        session,
        plugin=plugin,
        connection_id=connection_id,
        user_id=user_id,
        reason="admin_revoked",
    )
    await session.commit()


@router.post(
    "/{plugin_id}/members/{user_id}/connections/{connection_id}/block",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def block_member_connection(
    plugin_id: int,
    user_id: int,
    connection_id: str,
    session: SeatWriteSessionDep,
    current_user: CurrentUser,
    guild_context: SeatWriteContextDep,
) -> None:
    """Revoke a member's connection and refuse the next one.

    The lever for "this person should no longer reach that system through us"
    that does not mean uninstalling the plug-in for everyone.
    """
    plugin = await _load(session, plugin_id)
    _connection_or_404(plugin, connection_id)

    await connections_service.block_member_connection(
        session,
        plugin=plugin,
        connection_id=connection_id,
        user_id=user_id,
        blocked_by_id=current_user.id,
    )
    await session.commit()


@router.delete(
    "/{plugin_id}/members/{user_id}/connections/{connection_id}/block",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unblock_member_connection(
    plugin_id: int,
    user_id: int,
    connection_id: str,
    session: SeatWriteSessionDep,
    current_user: CurrentUser,
    guild_context: SeatWriteContextDep,
) -> None:
    """Lift a block, so the member may connect their own account again."""
    plugin = await _load(session, plugin_id)
    _connection_or_404(plugin, connection_id)

    await connections_service.unblock_member_connection(
        session, plugin=plugin, connection_id=connection_id, user_id=user_id
    )
    await session.commit()


@router.delete(
    "/{plugin_id}/members/{user_id}/consents",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_member_consents(
    plugin_id: int,
    user_id: int,
    session: SeatWriteSessionDep,
    current_user: CurrentUser,
    guild_context: SeatWriteContextDep,
) -> None:
    """End every answer one member gave this plug-in's requests to act as them,
    pending requests included.

    An admin ends an answer and cannot give one: the member allows a request
    again themselves, or nobody does. Governance runs one way here, which is
    what keeps "the plug-in acts as me" something its subject actually decided.
    """
    plugin = await _load(session, plugin_id)

    await consents_service.revoke_member_consents(
        session,
        install_id=plugin.id,
        user_id=user_id,
        revoked_by_id=current_user.id,
        actor_user_id=current_user.id,
    )
    await session.commit()


@router.post("/{plugin_id}/consents/revoke-all", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_all_member_consents(
    plugin_id: int,
    session: SeatWriteSessionDep,
    current_user: CurrentUser,
    guild_context: SeatWriteContextDep,
) -> None:
    """Stop this plug-in acting as anybody, without uninstalling it.

    Ends every member's answer to the plug-in's requests to act as them, pending
    ones included. The companion to ``revoke-all`` for connections: for a
    suspected plug-in compromise, reacting fast should not cost the guild its
    configuration. Members may allow requests again once the guild is
    satisfied.
    """
    plugin = await _load(session, plugin_id)

    await consents_service.revoke_all(
        session,
        install_id=plugin.id,
        revoked_by_id=current_user.id,
        actor_user_id=current_user.id,
    )
    await session.commit()


@router.post("/{plugin_id}/revoke-all", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_all_member_connections(
    plugin_id: int,
    session: SeatWriteSessionDep,
    current_user: CurrentUser,
    guild_context: SeatWriteContextDep,
) -> None:
    """End every member's connection at once, leaving the install standing.

    For a suspected plug-in or vendor compromise: reacting fast should not cost the
    guild its configuration.
    """
    plugin = await _load(session, plugin_id)

    await connections_service.revoke_all(session, plugin=plugin)
    await session.commit()
