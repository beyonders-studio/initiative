"""An installed plug-in's calls about its own installation.

Every route here takes an **installation token** and reaches the install the
token names — no ``community_ref`` in the path, and no scope, because these are
the install's own configuration rather than community content. A token
narrowed to one initiative reaches them too. A member token acts for somebody
and is refused.

* ``GET /installation/config`` — the decrypted configuration: the guild-wide
  values, and each member's managed values. Never a flow's tokens.
* ``GET /installation/connections`` — the plug-in's per-member connections, by
  opaque reference, with status only.
* ``POST /installation/connections/{connection_ref}/token`` — a usable access
  token for one connection, refreshed or minted first.
* ``POST /installation/config-status`` — the plug-in's verdict on the
  configuration it was handed.
* ``POST /installation/events`` — an event the plug-in emits, kept for the outbox
  poller to deliver to the community's subscriptions.
* ``GET`` / ``PUT /installation/metadata`` and ``GET /installation/metadata/lookup``
  — the values the plug-in keeps on items and on its install.
* ``GET /installation/entitlement`` — the entitlement statement held for the
  install's community and listing (404 ``NO_ENTITLEMENT`` without one).
* ``PUT /installation/usage/{meter}/{period}`` — a period's cumulative total
  for a meter the listing's terms name.

The token is checked by the install seam (``establish_install_access``),
whose standing statement admits the install only while it may act: the
community is in use, the install is on, and its registration is live. The
configuration and event work runs on the system engine, routed into the
community one install at a time (:mod:`app.services.tenant.plugin_channels`).
The metadata routes run as the install itself, on the session the seam routed,
so the table's policies decide which rows it reaches
(:mod:`app.services.tenant.metadata`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    CREDENTIAL_INSTALL,
    InstallAccessError,
    SessionDep,
    VerifiedInstall,
    establish_install_access,
    oauth2_scheme,
    SystemSessionDep,
)
from app.core import audit_context
from app.core.body_limit import max_body
from app.core.plugin_access_token import InstallAccessToken
from app.core.identify import bearer_plugin_token
from app.core.messages import AuthMessages, PluginChannelMessages
from app.db.guild_standing import InstallContext
from app.db.session import clear_rls_context
from app.models.platform.plugin_entitlement import (
    METER_MAX_LENGTH,
    METER_PATTERN,
    PERIOD_PATTERN,
)
from app.models.tenant.guild_plugin import GuildPlugin
from app.schemas.tenant.plugin_channel import (
    MetadataTarget,
    PluginConnectionRead,
    PluginConnectionsResponse,
    PluginConnectionToken,
    PluginEntitlementRead,
    PluginInstallConfigRead,
    PluginInstallationEvent,
    PluginMetadataItem,
    PluginMetadataItems,
    PluginMetadataValues,
    PluginMetadataWrite,
    PluginStatusRead,
    PluginStatusReport,
    PluginUsageRead,
    PluginUsageReport,
)
from app.services.marketplace import plugin_entitlements, registration_lookup
from app.services.marketplace.registration_lookup import RegistrationSnapshot
from app.services.tenant import plugin_channels as channels_service
from app.services.tenant import metadata as metadata_service

# Not part of the OpenAPI document: only plug-in containers call these, never the
# SPA, so the generated frontend client carries none of them.
router = APIRouter(prefix="/installation", include_in_schema=False)

#: The most one installation call may carry. Every write here is a
#: configuration report or an event, none larger than an event: its payload
#: and its envelope. The handler's exact cap still applies after.
MAX_REQUEST_BYTES = channels_service.MAX_EVENT_PAYLOAD_BYTES + 8 * 1024

_bounded = max_body(lambda: MAX_REQUEST_BYTES, PluginChannelMessages.EVENT_TOO_LARGE)

#: The most one metadata write may carry: everything an install may keep on
#: itself, and its envelope. The per-value and per-item caps still apply after.
_metadata_bounded = max_body(
    lambda: metadata_service.INSTALL_BYTES + 64 * 1024,
    PluginChannelMessages.METADATA_LIMIT_REACHED,
)


def _refuse() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS,
        headers={"WWW-Authenticate": "Bearer"},
    )


@dataclass(frozen=True)
class Installation:
    """The install an installation token names, admitted by the seam."""

    guild_id: int
    install_id: int
    registration: RegistrationSnapshot
    #: What the seam computed: the install's standing in its community.
    context: InstallContext
    #: The initiative the token is narrowed to, when it is.
    initiative_id: Optional[int] = None


async def _admit(
    request: Request, session: AsyncSession, *, routed: bool
) -> Installation:
    """The install the request's installation token names, or 401.

    The token is unsealed locally, then the seam computes the install's
    standing, which is what says it may act now. ``routed`` keeps the request's
    session routed as the install; otherwise it is left unrouted.
    """
    token = bearer_plugin_token(request)
    if not isinstance(token, InstallAccessToken) or token.user_id is not None:
        raise _refuse()
    try:
        context = await establish_install_access(
            session,
            VerifiedInstall(
                guild_id=token.guild_id,
                install_id=token.install_id,
                client_id=token.client_id,
                scopes=token.scopes,
                initiative_id=token.initiative_id,
            ),
        )
    except InstallAccessError as exc:
        raise _refuse() from exc
    if not routed:
        clear_rls_context(session)
        await session.rollback()

    registration = (await registration_lookup.load_registrations()).get(
        context.client_id
    )
    if registration is None or not registration.live_in(context.guild_id):
        raise _refuse()

    request.state.credential = CREDENTIAL_INSTALL
    audit_context.note_install(
        plugin=context.client_id,
        guild_id=context.guild_id,
        install_id=context.install_id,
    )
    # Whose request this is, for the rate limiter's key.
    request.state.plugin_install = (
        context.client_id,
        context.guild_id,
        context.install_id,
    )
    return Installation(
        guild_id=context.guild_id,
        install_id=context.install_id,
        registration=registration,
        context=context,
        initiative_id=context.scope_initiative_id,
    )


async def installation_caller(
    request: Request,
    session: SessionDep,
    # Declares the scheme for the API description; read by ``bearer_plugin_token``.
    bearer: Annotated[Optional[str], Depends(oauth2_scheme)] = None,
) -> Installation:
    """The install the token names, with the request's session left unrouted:
    the work runs on the system engine."""
    return await _admit(request, session, routed=False)


async def routed_installation_caller(
    request: Request,
    session: SessionDep,
    bearer: Annotated[Optional[str], Depends(oauth2_scheme)] = None,
) -> Installation:
    """The install the token names, with the request's session routed as it:
    the route reads and writes as the install, under its policies."""
    return await _admit(request, session, routed=True)


InstallationDep = Annotated[Installation, Depends(installation_caller)]
RoutedInstallationDep = Annotated[Installation, Depends(routed_installation_caller)]


async def _load(
    session: AsyncSession, installation: Installation, *, for_write: bool = False
) -> GuildPlugin:
    return await channels_service.load_install(
        session,
        installation.registration,
        installation.guild_id,
        plugin_install_id=installation.install_id,
        for_write=for_write,
    )


@router.get("/config", response_model=PluginInstallConfigRead)
async def read_installation_config(
    installation: InstallationDep, session: SystemSessionDep
) -> PluginInstallConfigRead:
    """The decrypted configuration for this install.

    The guild-wide values an admin supplied, plus the per-member ones the plug-in
    wrote back itself, each keyed by the opaque reference it knows that member
    by. Refused when the community has turned the plug-in off.
    """
    plugin = await _load(session, installation)
    payload = await channels_service.config_payload(session, plugin)
    return PluginInstallConfigRead(**payload)


@router.get("/connections", response_model=PluginConnectionsResponse)
async def list_installation_connections(
    installation: InstallationDep, session: SystemSessionDep
) -> PluginConnectionsResponse:
    """The plug-in's per-member connections for this install, by opaque reference
    and with status only."""
    plugin = await _load(session, installation)
    rows = await channels_service.connection_payload(session, plugin)
    return PluginConnectionsResponse(
        items=[PluginConnectionRead(**row) for row in rows]
    )


@router.post(
    "/connections/{connection_ref}/token", response_model=PluginConnectionToken
)
@_bounded
async def read_installation_connection_token(
    connection_ref: str,
    installation: InstallationDep,
    session: SystemSessionDep,
) -> PluginConnectionToken:
    """A usable access token for one of this install's connections.

    A member's connection must be connected and not blocked; its token is
    refreshed first when it is within two minutes of expiring, and one the
    vendor will not refresh leaves the connection ``expired`` (409). A
    guild-wide connection answers its ``jwt_bearer`` token, minted and reused
    until shortly before it expires, or its own stored token.
    """
    plugin = await _load(session, installation, for_write=True)
    token = await channels_service.connection_token(
        session,
        plugin,
        installation.registration,
        connection_ref=connection_ref,
    )
    return PluginConnectionToken(**token)


@router.post("/config-status", response_model=PluginStatusRead)
@_bounded
async def report_installation_config_status(
    payload: PluginStatusReport,
    installation: InstallationDep,
    session: SystemSessionDep,
) -> PluginStatusRead:
    """Record whether the configuration this community supplied works.

    Only the vendor can confirm a credential carries the permissions it needs;
    this is how that answer reaches the admin who supplied it. An install
    nothing reports on stays ``unverified``.
    """
    plugin = await _load(session, installation, for_write=True)
    result = await channels_service.report_config_state(
        session, plugin, state=payload.state, detail=payload.detail
    )
    return PluginStatusRead(**result)


@router.post("/events", status_code=status.HTTP_202_ACCEPTED)
@_bounded
async def ingest_installation_event(
    payload: PluginInstallationEvent,
    installation: InstallationDep,
    session: SystemSessionDep,
) -> dict[str, str]:
    """Emit one event in the community this install is in.

    The event type must be one the pinned definition declares, namespaced
    under the calling plug-in, and the payload at most 8 KiB. An event about an
    initiative names one the install is placed in (403 otherwise). Answers
    ``202``: the event is kept and delivered to the community's subscriptions,
    and what subscribers do with it is not the emitting plug-in's to know.
    """
    plugin = await _load(session, installation, for_write=True)
    await channels_service.emit_event(
        session,
        plugin,
        installation.registration,
        event_type=payload.event_type,
        payload=payload.payload,
        initiative_id=payload.initiative_id,
        token_initiative_id=installation.initiative_id,
    )
    return {"status": "accepted"}


@router.get("/entitlement", response_model=PluginEntitlementRead)
async def read_installation_entitlement(
    installation: InstallationDep, session: SystemSessionDep
) -> PluginEntitlementRead:
    """The entitlement statement this deployment's issuer sent for the
    install's community and listing, as the ``entitlement`` hook delivers it:
    ``{"statement": "<jws>"}``, the signed statement exactly as it was sent.

    404 ``NO_ENTITLEMENT`` when there is none, which is every install on a
    deployment with no issuer.
    """
    plugin = await _load(session, installation)
    statement = (
        await plugin_entitlements.read_statement(
            installation.guild_id, plugin.listing_uid
        )
        if plugin.listing_uid
        else None
    )
    if statement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=PluginChannelMessages.NO_ENTITLEMENT,
        )
    return PluginEntitlementRead(statement=statement.jws)


@router.put("/usage/{meter}/{period}", response_model=PluginUsageRead)
@_bounded
async def report_installation_usage(
    payload: PluginUsageReport,
    installation: InstallationDep,
    session: SystemSessionDep,
    meter: Annotated[str, Path(max_length=METER_MAX_LENGTH, pattern=METER_PATTERN)],
    period: Annotated[str, Path(pattern=PERIOD_PATTERN)],
) -> PluginUsageRead:
    """A period's cumulative total for one meter, kept and passed on.

    The meter must be one the terms of the install's listing name (403
    ``METER_NOT_ALLOWED``, which is every meter on a deployment whose listings
    carry none), and the total may not fall below the one held for the period
    (409 ``USAGE_TOTAL_DECREASED``). The same total again is accepted.
    """
    plugin = await _load(session, installation)
    terms = await plugin_entitlements.listing_terms(plugin.listing_uid)
    if terms is None or meter not in terms.meters:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PluginChannelMessages.METER_NOT_ALLOWED,
        )
    assert plugin.listing_uid is not None  # a listing with terms has a uid
    outcome = await plugin_entitlements.record_usage(
        installation.guild_id,
        plugin.listing_uid,
        meter=meter,
        period=period,
        quantity=payload.quantity,
        as_of=payload.as_of,
    )
    if outcome.decreased:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=PluginChannelMessages.USAGE_TOTAL_DECREASED,
        )
    return PluginUsageRead(meter=meter, period=period, quantity=outcome.quantity)


def _items(
    found: list[tuple[str, int, dict]],
) -> PluginMetadataItems:
    return PluginMetadataItems(
        items=[
            PluginMetadataItem(entity_type=kind, entity_id=entity_id, values=values)
            for kind, entity_id, values in found
        ]
    )


@router.get("/metadata", response_model=PluginMetadataItems)
async def read_installation_metadata(
    installation: RoutedInstallationDep,
    session: SessionDep,
    entity_type: MetadataTarget,
    entity_ids: Annotated[List[int], Query()] = [],
) -> PluginMetadataItems:
    """The values this install keeps on each named item, or on itself with
    ``entity_type=plugin`` (``entity_ids`` is then not read), a list field's
    as an array of its elements, newest first.

    An item holding none, one the install cannot read, and an id that names
    nothing are all left out.
    """
    found = await metadata_service.read(
        session, installation.context, entity_type.value, entity_ids
    )
    return _items(found)


@router.put("/metadata", response_model=PluginMetadataValues)
@_metadata_bounded
async def write_installation_metadata(
    payload: PluginMetadataWrite,
    installation: RoutedInstallationDep,
    session: SessionDep,
) -> PluginMetadataValues:
    """Change this install's values on one item, or on itself: ``values``
    sets them by key, a ``null`` removing its key; ``upsert`` adds a list
    field's elements, or merges each into the element with its ``ref``; and
    ``remove`` takes the elements with these refs. Answers every value it
    keeps there now, a list field's as an array of its elements, newest
    first. A value on an item whose key the pinned version declares as a
    field there is shown to whoever can read the item.

    On an item, the install needs the read scope of the item's tool (403) and
    to be able to read the item (404). A key is a lowercase letter, then
    lowercase letters, digits, ``_`` and ``.``, at most 64 characters, and is
    changed by one of the three (400); only a key the pinned version declares
    as a list field there holds elements (400); a value, and each element, at
    most 8192 bytes as JSON (413); an item at most 32 keys and 65536 bytes, a
    list counting as one key, and the install itself 256 keys and 1048576
    bytes (409).
    """

    async def pinned() -> Any:
        return await metadata_service.pinned_fields(session, installation.install_id)

    values = await metadata_service.write(
        session,
        installation.context,
        payload.entity_type.value,
        payload.entity_id,
        [
            metadata_service.change(
                values=payload.values, upsert=payload.upsert, remove=payload.remove
            )
        ],
        pinned,
    )
    return PluginMetadataValues(values=values)


@router.get("/metadata/lookup", response_model=PluginMetadataItems)
async def find_installation_metadata(
    installation: RoutedInstallationDep,
    session: SessionDep,
    key: str,
    value: str,
) -> PluginMetadataItems:
    """The items this install can read that hold ``value`` under ``key``, with
    every value it keeps on each: at most 100, in kind and id order. A value
    is found by its text, a number or a boolean as JSON writes it, and a list
    field's element by its ``ref``."""
    found = await metadata_service.find(session, installation.context, key, value)
    return _items(found)
