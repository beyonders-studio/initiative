"""Operator CRUD for the plug-in service registry (``plugin_service_registrations``)
and its publishers (``publishers``).

A listing declares what a plug-in is, and gives its registration the plug-in facts:
which listing it is, its image, its scope ceiling and its Compose service. The
operator gives the deployment facts here: its addresses, its public keys, its
vendor values and whether it is ``mandatory``, and the owner suspends a plug-in
everywhere and lifts it, picks the communities a beta plug-in reaches, and may
connect a community connection once for every community. Vendor
values may also come from the vendor's own setup flow, run from here. A publisher is the prefix of
a plug-in's ``public_id``, with a switch that stops every plug-in under it. The whole
surface is gated on ``plugins.manage`` (owner tier).

Every route runs on the system engine: neither table carries a request-path
write grant. The logic lives in ``app.services.marketplace.registrations`` and
``app.services.marketplace.publishers``; these routers gate, translate, and
delegate.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import SystemSessionDep, require_capability
from app.core.capabilities import Capability
from app.core.messages import PluginServiceMessages
from app.db.query import build_paginated_response
from app.models.platform.plugin_service_registration import PluginAvailability
from app.models.platform.publisher import Publisher
from app.models.platform.user import User
from app.schemas.platform.plugin_service import (
    PluginBetaCommunityRead,
    PluginPlatformConnectionRead,
    PluginPlatformConnectStart,
    PluginPublisherCreate,
    PluginPublisherRead,
    PluginPublisherUpdate,
    PluginServiceConnect,
    PluginServicePublishedKey,
    PluginServiceRegistrationCreate,
    PluginServiceRegistrationListResponse,
    PluginServiceRegistrationRead,
    PluginServiceRegistrationUpdate,
    PluginServiceVendorSetup,
    PluginServiceVendorSetupComplete,
    PluginServiceVendorSetupStart,
    PluginVendorFieldRead,
)
from app.services.marketplace import (
    platform_connections as platform_connections_service,
)
from app.services.marketplace import publishers as publishers_service
from app.services.marketplace import registrations as registrations_service
from app.services.marketplace import vendor_check as vendor_check_service
from app.services.marketplace import vendor_setup as vendor_setup_service
from app.services.marketplace import vendor_values as vendor_values_service
from app.services.tenant import plugin_connection_flows as flows_service
from app.services.tenant.connection_flow_state import ConnectingApp

router = APIRouter()
publishers_router = APIRouter()

#: Wiring plug-in services is deployment configuration — owner tier, like the rest
#: of the platform settings wall.
PluginsManageDep = Annotated[
    User, Depends(require_capability(Capability.PLUGINS_MANAGE))
]


def _to_read(
    view: registrations_service.RegistrationView,
    definitions: dict[str, dict],
) -> PluginServiceRegistrationRead:
    row = view.row
    definition = definitions.get(row.listing_uid or "")
    vendor = vendor_values_service.vendor_view(row, definition)
    return PluginServiceRegistrationRead(
        id=row.id,
        public_id=row.public_id,
        listing_uid=row.listing_uid,
        name=view.name,
        avatar_url=view.avatar_url,
        version=view.version,
        first_party=view.first_party,
        kind=row.kind,
        publisher_id=view.publisher.id,
        publisher_prefix=view.publisher.prefix,
        publisher_name=view.publisher.display_name,
        publisher_enabled=view.publisher.enabled,
        base_url=row.base_url,
        page_origin=row.page_origin,
        allowed_origins=list(row.allowed_origins or []),
        jwks=row.jwks,
        jwks_uri=row.jwks_uri,
        scope_ceiling=list(row.scope_ceiling or []),
        mandatory=row.mandatory,
        availability=PluginAvailability(row.availability),
        beta_communities=[
            PluginBetaCommunityRead(id=community_id, name=name)
            for community_id, name in view.beta_communities
        ],
        platform_connections=[
            PluginPlatformConnectionRead(**view)
            for view in platform_connections_service.views(row, definition)
        ],
        suspended_at=row.suspended_at,
        source=row.source,
        image_digest=row.image_digest,
        compose_service=registrations_service.filled_compose(row),
        compose_base_url=(row.compose or {}).get("base_url"),
        vendor_fields=[PluginVendorFieldRead(**field) for field in vendor.fields],
        vendor_values=vendor.values,
        vendor_set=vendor.set_keys,
        vendor_ready=bool(row.vendor_ready),
        vendor_setup=vendor_setup_service.setup_kind(definition),
        connection_callback_url=flows_service.callback_url(),
        connection_setup_url=flows_service.setup_url(),
        webhook_url=flows_service.webhook_url(row.public_id),
        live=view.live,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _read_one(
    session: AsyncSession, registration_id: int
) -> PluginServiceRegistrationRead:
    views = await registrations_service.registration_views(session, registration_id)
    if not views:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=PluginServiceMessages.NOT_FOUND,
        )
    return _to_read(views[0], await _definitions(session, views))


async def _definitions(
    session: AsyncSession, views: list[registrations_service.RegistrationView]
) -> dict[str, dict]:
    """The latest manifest of each registration's listing, for its vendor
    fields."""
    return await vendor_values_service.listing_definitions(
        session, [view.row.listing_uid for view in views]
    )


@router.get("/", response_model=PluginServiceRegistrationListResponse)
async def list_plugin_services(
    session: SystemSessionDep,
    _owner: PluginsManageDep,
    search: str | None = Query(
        default=None, description="Matches the plug-in's id or its publisher's name."
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PluginServiceRegistrationListResponse:
    """One page of the plug-in services this deployment has wired up
    (``plugins.manage``), by id."""
    views, total_count, actual_page = await registrations_service.registration_page(
        session, search=search, page=page, page_size=page_size
    )
    definitions = await _definitions(session, views)
    return PluginServiceRegistrationListResponse(
        **build_paginated_response(
            [_to_read(view, definitions) for view in views],
            total_count,
            actual_page,
            page_size,
        )
    )


@router.get("/{registration_id}", response_model=PluginServiceRegistrationRead)
async def read_plugin_service(
    registration_id: int,
    session: SystemSessionDep,
    _owner: PluginsManageDep,
) -> PluginServiceRegistrationRead:
    """One plug-in service (``plugins.manage``)."""
    return await _read_one(session, registration_id)


@router.post(
    "/",
    response_model=PluginServiceRegistrationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_plugin_service(
    payload: PluginServiceRegistrationCreate,
    session: SystemSessionDep,
    owner: PluginsManageDep,
) -> PluginServiceRegistrationRead:
    """Set up a plug-in service's deployment facts before its listing arrives:
    its id, its addresses and its keys. Its publisher is the one its id's
    prefix names, added unverified when there is none."""
    row = await registrations_service.create_registration(
        session,
        public_id=payload.public_id,
        base_url=payload.base_url,
        page_origin=payload.page_origin,
        allowed_origins=payload.allowed_origins,
        jwks=payload.jwks,
        jwks_uri=payload.jwks_uri,
        mandatory=payload.mandatory,
        vendor_values=payload.vendor_values,
        actor_user_id=owner.id,
    )
    return await _read_one(session, row.id)


@router.patch("/{registration_id}", response_model=PluginServiceRegistrationRead)
async def update_plugin_service(
    registration_id: int,
    payload: PluginServiceRegistrationUpdate,
    session: SystemSessionDep,
    owner: PluginsManageDep,
) -> PluginServiceRegistrationRead:
    """Suspend everywhere or lift, repoint either address, replace the keys,
    make it mandatory or not, set the vendor values, or replace a beta
    plug-in's communities. A list of communities for a plug-in that is not
    beta is refused (409); one naming a community that does not exist is
    refused (400).

    Vendor values the listing's vendor check reads are checked with the
    vendor before anything is written (:mod:`~app.services.marketplace.vendor_check`):
    a refusal is a 400 naming the fields, and a check the vendor could not
    answer saves the values and says so in ``vendor_check``."""
    checked = held = None
    if payload.vendor_values:
        current = await registrations_service.get_registration(session, registration_id)
        # What the check runs against, as stored: the write is refused if it
        # moves before the row is locked.
        held = dict(current.vendor_values or {})
        definition = (
            await vendor_values_service.listing_definitions(
                session, [current.listing_uid]
            )
        ).get(current.listing_uid or "")
        checked = await vendor_check_service.run(
            definition,
            held=vendor_values_service.held_values(current),
            submitted=payload.vendor_values,
        )
    row = await registrations_service.update_registration(
        session,
        registration_id,
        base_url=payload.base_url,
        page_origin=payload.page_origin,
        allowed_origins=payload.allowed_origins,
        jwks=payload.jwks,
        jwks_uri=payload.jwks_uri,
        mandatory=payload.mandatory,
        suspended=payload.suspended,
        beta_community_ids=payload.beta_community_ids,
        vendor_values=payload.vendor_values,
        vendor_values_checked=held if checked is not None else None,
        actor_user_id=owner.id,
    )
    read = await _read_one(session, row.id)
    return read.model_copy(update={"vendor_check": checked})


@router.get(
    "/{registration_id}/connect", response_model=list[PluginServicePublishedKey]
)
async def read_plugin_service_keys(
    registration_id: int,
    session: SystemSessionDep,
    _owner: PluginsManageDep,
) -> list[PluginServicePublishedKey]:
    """The keys the plug-in serves at ``{base_url}/.well-known/jwks.json``, each
    with its fingerprint, for the operator to confirm. Stores nothing."""
    keys = await registrations_service.published_keys(session, registration_id)
    return [
        PluginServicePublishedKey(kid=key.kid, fingerprint=key.fingerprint)
        for key in keys
    ]


@router.post("/{registration_id}/connect", response_model=PluginServiceRegistrationRead)
async def connect_plugin_service(
    registration_id: int,
    payload: PluginServiceConnect,
    session: SystemSessionDep,
    owner: PluginsManageDep,
) -> PluginServiceRegistrationRead:
    """Store the key set the plug-in serves as the registration's pasted set, in
    place of any key set address, when its keys are the ones confirmed and
    its base URL has not moved (409 otherwise)."""
    row = await registrations_service.connect_registration(
        session,
        registration_id,
        keys=[
            registrations_service.PublishedKey(kid=key.kid, fingerprint=key.fingerprint)
            for key in payload.keys
        ],
        actor_user_id=owner.id,
    )
    return await _read_one(session, row.id)


@router.post("/{registration_id}/vendor-setup", response_model=PluginServiceVendorSetup)
async def start_plugin_service_vendor_setup(
    registration_id: int,
    payload: PluginServiceVendorSetupStart,
    session: SystemSessionDep,
    owner: PluginsManageDep,
) -> PluginServiceVendorSetup:
    """Start the vendor's own setup of the plug-in's client: the manifest the
    operator's browser posts to the vendor, where, and the state that brings
    them back (409 when the listing declares no such setup)."""
    started = await vendor_setup_service.start(
        session,
        registration_id,
        organization=payload.organization,
        actor_user_id=owner.id,
    )
    return PluginServiceVendorSetup(
        action=started.action, manifest=started.manifest, state=started.state
    )


@router.post(
    "/{registration_id}/vendor-setup/complete",
    response_model=PluginServiceRegistrationRead,
)
async def complete_plugin_service_vendor_setup(
    registration_id: int,
    payload: PluginServiceVendorSetupComplete,
    session: SystemSessionDep,
    owner: PluginsManageDep,
) -> PluginServiceRegistrationRead:
    """Finish the setup the vendor sent the operator back from, writing the
    new client's values into the registration's vendor values."""
    row, checked = await vendor_setup_service.complete(
        session,
        registration_id,
        code=payload.code,
        state=payload.state,
        actor_user_id=owner.id,
    )
    read = await _read_one(session, row.id)
    return read.model_copy(update={"vendor_check": checked})


@router.post(
    "/{registration_id}/connections/{connection_id}/connect",
    response_model=PluginPlatformConnectStart,
)
async def connect_plugin_service_for_every_community(
    registration_id: int,
    connection_id: str,
    session: SystemSessionDep,
    owner: PluginsManageDep,
    app: Annotated[ConnectingApp | None, Query()] = None,
    code_challenge: Annotated[str | None, Query(max_length=128)] = None,
) -> PluginPlatformConnectStart:
    """Start connecting one of the plug-in's community connections for every
    community: the vendor's address to send the operator to. Nothing is
    stored until the vendor sends them back. Refused (409) for a connection
    the platform cannot make (``for_platform``)."""
    row = await registrations_service.get_registration(session, registration_id)
    return PluginPlatformConnectStart(
        connect_url=await flows_service.start_platform_url(
            public_id=row.public_id,
            connection_id=connection_id,
            started_by=owner.id,
            app=app,
            app_challenge=code_challenge,
        )
    )


@router.delete(
    "/{registration_id}/connections/{connection_id}",
    response_model=PluginServiceRegistrationRead,
)
async def disconnect_plugin_service_for_every_community(
    registration_id: int,
    connection_id: str,
    session: SystemSessionDep,
    owner: PluginsManageDep,
) -> PluginServiceRegistrationRead:
    """End a connection the platform made for every community: each
    community reads its own again."""
    row = await platform_connections_service.disconnect(
        session, registration_id, connection_id, actor_user_id=owner.id
    )
    return await _read_one(session, row.id)


@router.delete("/{registration_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plugin_service(
    registration_id: int,
    session: SystemSessionDep,
    owner: PluginsManageDep,
) -> None:
    """Remove the registration. Every channel it backed stops with the row."""
    await registrations_service.delete_registration(
        session, registration_id, actor_user_id=owner.id
    )


# --- publishers ---------------------------------------------------------------


def _publisher_read(row: Publisher) -> PluginPublisherRead:
    return PluginPublisherRead(
        id=row.id,
        prefix=row.prefix,
        display_name=row.display_name,
        verified=row.verified,
        enabled=row.enabled,
        created_at=row.created_at,
    )


@publishers_router.get("/", response_model=list[PluginPublisherRead])
async def list_plugin_publishers(
    session: SystemSessionDep,
    _owner: PluginsManageDep,
) -> list[PluginPublisherRead]:
    """Every publisher of plug-in services on this deployment (``plugins.manage``)."""
    rows = await publishers_service.list_publishers(session)
    return [_publisher_read(row) for row in rows]


@publishers_router.post(
    "/", response_model=PluginPublisherRead, status_code=status.HTTP_201_CREATED
)
async def create_plugin_publisher(
    payload: PluginPublisherCreate,
    session: SystemSessionDep,
    owner: PluginsManageDep,
) -> PluginPublisherRead:
    """Add a publisher for a prefix, such as a private plug-in's. It starts
    unverified."""
    row = await publishers_service.create_publisher(
        session,
        prefix=payload.prefix,
        display_name=payload.display_name,
        enabled=payload.enabled,
        actor_user_id=owner.id,
    )
    return _publisher_read(row)


@publishers_router.patch("/{publisher_id}", response_model=PluginPublisherRead)
async def update_plugin_publisher(
    publisher_id: int,
    payload: PluginPublisherUpdate,
    session: SystemSessionDep,
    owner: PluginsManageDep,
) -> PluginPublisherRead:
    """Rename a publisher, or switch it on or off. Off makes every plug-in under
    its prefix not live."""
    row = await publishers_service.update_publisher(
        session,
        publisher_id,
        display_name=payload.display_name,
        enabled=payload.enabled,
        actor_user_id=owner.id,
    )
    return _publisher_read(row)
