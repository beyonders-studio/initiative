"""Browsing the marketplace from inside a guild.

The catalog itself is platform data — one shared set of listings with globally
unique ids, and no guild column anywhere in it. Browsing it is nevertheless
guild-addressed, because what is *offered* depends on the guild asking: a
dashboard a plug-in ships with draws that plug-in's widgets, so it appears only where
the plug-in is installed.

That makes the guild a required part of the question rather than a filter the
client applies afterwards, and it puts browse on the same footing as the
install: both run on the guild-routed session, and both read the guild's own
installs through :func:`installed_plugin_uids`, so a card and the install behind
it always agree.

Listings are written by the system engine (boot seeding, the operator's
catalog directory, the registry refresh) through the platform routes. Installing
writes the guild's own schema: a tool's listing through that tool's importer
(below), a plug-in through the guild's plug-in routes.
"""

from typing import Annotated

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.api.deps import (
    CurrentUser,
    GuildContextDep,
    RLSSessionDep,
)
from app.core.audit_events import AuditEventType
from app.core.messages import ImportEngineMessages, MarketplaceMessages
from app.core.user_display import handle_of
from app.db import cohorts
from app.db.query import build_paginated_response
from app.db.session import routed_guild_id
from app.models.platform.marketplace import MarketplaceListing
from app.schemas.platform.marketplace import (
    ListingKind,
    ListingOffer,
    ListingSource,
    ListingStartFrom,
    ListingUnavailable,
    ListingUnavailableReason,
    MarketplaceInstallRequest,
    MarketplaceInstallResult,
    MarketplaceListingCaller,
    MarketplaceListingDetail,
    MarketplaceListingPage,
    MarketplaceShareRequest,
    MarketplaceShareResult,
    serialize_listing_summary,
)
from app.services import audit as audit_service
from app.services.marketplace import catalog as catalog_service
from app.services.marketplace import (
    local_listings,
    plugin_entitlements,
    registration_lookup,
)
from app.services.marketplace.definitions import TOOL_LISTING_KINDS
from app.services.marketplace.installs import (
    count_install,
    installed_plugin_uids,
    listing_is_offered,
    resolve_listing_install,
)
from app.services.marketplace.listing_assets import (
    MAX_IMAGE_BYTES,
    MAX_LISTING_IMAGES,
    UploadedImageError,
    store_uploaded_image,
)
from app.services.marketplace.publish_profile import export_for_listing
from app.services.marketplace.tool_listings import (
    example_is_generated,
    install_tool_listing,
    listing_example,
)
from app.services.platform import app_settings as app_settings_service
from app.services.platform import billing_ping
from app.services.tenant import guild_plugins as guild_plugins_service
from app.services.tenant.attachments import FileTooLargeError, read_upload_bounded

router = APIRouter()


MAX_PAGE_SIZE = 100

#: The reader's language, which billing words an offer in.
LocaleQuery = Annotated[
    str, Query(max_length=35, pattern=r"^[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*$")
]


def _unavailable(
    guild_id: int, uid: str, gated: dict[str, str | None]
) -> ListingUnavailable | None:
    """Why this community cannot install listing ``uid`` yet, if it cannot."""
    if uid not in gated:
        return None
    if gated[uid] == plugin_entitlements.REASON_TERM_FULL:
        return ListingUnavailable(reason=ListingUnavailableReason.term_full)
    return ListingUnavailable(
        reason=ListingUnavailableReason.entitlement_required,
        action_url=plugin_entitlements.action_url(uid),
    )


@router.get("/listings", response_model=MarketplaceListingPage)
async def list_marketplace_listings(
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    kind: ListingKind | None = Query(default=None),  # type: ignore[valid-type]
    search: str | None = Query(default=None, max_length=200),
    source: list[ListingSource] | None = Query(default=None),  # type: ignore[valid-type]
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=MAX_PAGE_SIZE),
) -> MarketplaceListingPage:
    """A page of listings this guild can install, searchable by name,
    description, or publisher, and narrowed to the given ``source`` values
    when any are named.

    A guild with none of a plug-in installed sees the same catalog as before —
    the plug-ins themselves, and the dashboards that stand alone.
    """
    listings, total = await catalog_service.list_listings(
        session,
        kind=kind,
        query=search,
        bundled_with=sorted(await installed_plugin_uids(session)),
        sources=[value.value for value in source] if source else None,
        page=page,
        page_size=page_size,
    )
    # One query for the page's versions rather than one per card.
    versions = await catalog_service.get_listing_versions(
        session, [listing.latest_version_id for listing in listings]
    )
    gated = await plugin_entitlements.gated_listings(guild_context.guild_id, listings)
    return MarketplaceListingPage(
        **build_paginated_response(
            [
                serialize_listing_summary(
                    listing, versions.get(listing.latest_version_id)
                ).model_copy(
                    update={
                        "unavailable": _unavailable(
                            guild_context.guild_id, listing.uid, gated
                        )
                    }
                )
                for listing in listings
            ],
            total,
            page,
            page_size,
        )
    )


async def _offer(guild_id: int, uid: str, locale: str) -> ListingOffer | None:
    """How billing sells listing ``uid`` to this community, in ``locale``, or
    ``None`` when it has no answer. Shown as given: nothing here reasons
    about it."""
    offer = await billing_ping.plugin_offer(guild_id, listing_uid=uid, locale=locale)
    return ListingOffer.model_validate(offer.model_dump()) if offer else None


async def _detail(
    session, listing: MarketplaceListing, locale: str
) -> MarketplaceListingDetail:
    """A listing's page, or the answer the shelf gives by leaving it out.

    Two things put a listing out of reach, and both read as *not found* here
    because both are already true of the shelf: a plug-in whose service this
    deployment does not run, and a dashboard whose plug-in this guild has not
    installed.

    A listing that wants an entitlement this community lacks, whether it is
    not installed yet or installed with its statement inactive, carries how
    billing sells it here, asked for this response only in ``locale``.
    """
    latest = await catalog_service.get_listing_version(
        session, listing.latest_version_id
    )
    offered = await registration_lookup.plugin_is_offered(
        latest.definition if latest else None,
        guild_id=routed_guild_id(session),
        listing_uid=listing.uid,
    ) and await listing_is_offered(session, listing)
    if not offered:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=MarketplaceMessages.LISTING_NOT_FOUND,
        )
    guild_id = routed_guild_id(session)
    summary = serialize_listing_summary(listing, latest)
    summary.unavailable = _unavailable(
        guild_id,
        listing.uid,
        await plugin_entitlements.gated_listings(guild_id, [listing]),
    )
    if (
        summary.unavailable is not None
        and summary.unavailable.reason == ListingUnavailableReason.entitlement_required
    ):
        summary.unavailable.offer = await _offer(guild_id, listing.uid, locale)
    definition = dict(latest.definition) if latest else {}
    # What the install dialog asks the seat about, from the version it would
    # install and the registration's ceiling. Empty for anything not a plug-in.
    requested: list[str] = []
    grantable: list[str] = []
    callers: list[MarketplaceListingCaller] = []
    if listing.kind == "plugin":
        installed = await guild_plugins_service.installed_plugin_ids(session)
        requested = guild_plugins_service.offered_scopes(definition, installed)
        registration = await registration_lookup.registration_for_definition(
            definition, listing_uid=listing.uid
        )
        grantable = guild_plugins_service.grantable_scopes(
            definition, registration.scope_ceiling if registration else (), installed
        )
        public_id = registration_lookup.service_public_id(
            definition, listing_public_id=listing.public_id
        )
        if public_id is not None:
            callers = [
                MarketplaceListingCaller(id=plugin.id, name=plugin.name)
                for plugin in await guild_plugins_service.plugin_callers(
                    session, public_id
                )
            ]
    return MarketplaceListingDetail(
        **summary.model_dump(),
        requested_scopes=requested,
        grantable_scopes=grantable,
        plugin_names=await guild_plugins_service.plugin_scope_names(session, requested),
        has_initiative_surfaces=(
            listing.kind == "plugin"
            and guild_plugins_service.has_initiative_surfaces(definition)
        ),
        callers=callers,
        long_description=listing.long_description,
        # A preview of what installing would produce. The install path re-reads
        # the catalog itself, so this is display data, not an input.
        definition=dict(latest.definition) if latest else None,
        example=(
            listing_example(TOOL_LISTING_KINDS[listing.kind], listing.uid, latest)
            if latest is not None and listing.kind in TOOL_LISTING_KINDS
            else None
        ),
    )


# Declared before ``/listings/{public_id}`` so the literal segment wins: uids and
# public ids are different identifier spaces and a path has to pick one.
@router.get("/listings/by-uid/{uid}", response_model=MarketplaceListingDetail)
async def resolve_marketplace_listing(
    uid: str,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    locale: LocaleQuery = "en",
) -> MarketplaceListingDetail:
    """The listing a code names.

    This is what an installed instance uses to find where it came from: the
    instance stores the uid, and the catalog answers with the listing and the
    version it currently publishes. A listing this guild can no longer take —
    a bundled dashboard whose plug-in it removed — answers 404, which is what
    stops an update being offered that the install would refuse.
    """
    listing = await catalog_service.get_listing_by_uid(session, uid)
    if listing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=MarketplaceMessages.LISTING_NOT_FOUND,
        )
    return await _detail(session, listing, locale)


@router.get("/listings/{public_id}", response_model=MarketplaceListingDetail)
async def read_marketplace_listing(
    public_id: str,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    locale: LocaleQuery = "en",
) -> MarketplaceListingDetail:
    """One listing, with what it would install and every version it has."""
    listing = await catalog_service.get_listing(session, public_id)
    if listing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=MarketplaceMessages.LISTING_NOT_FOUND,
        )
    return await _detail(session, listing, locale)


@router.post(
    "/listings/by-uid/{uid}/install",
    response_model=MarketplaceInstallResult,
    status_code=status.HTTP_201_CREATED,
)
async def install_marketplace_listing(
    uid: str,
    payload: MarketplaceInstallRequest,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> MarketplaceInstallResult:
    """Install a tool's listing: import a copy of it into an initiative.

    Any member who may create that tool in the initiative may install one —
    content runs no code and reaches nothing, so this is the importer's own
    permission and nothing more. The copy is the member's: it records the
    listing and version it came from, and nothing links it back.

    Plug-ins and profile packs install elsewhere; a uid naming one reads as not
    found here, as it would from any installer that cannot install it.
    """
    # Installing is authoring, like any import: a community whose content is
    # frozen takes none, and a grant reaches existing content only.
    if guild_context.content_read_only or guild_context.is_pam:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ImportEngineMessages.IMPORT_WRITE_REQUIRED,
        )
    listing = await catalog_service.get_listing_by_uid(session, uid)
    tool = TOOL_LISTING_KINDS.get(listing.kind) if listing is not None else None
    if listing is None or tool is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=MarketplaceMessages.LISTING_NOT_FOUND,
        )
    listing, version = await resolve_listing_install(session, uid, kind=listing.kind)
    if payload.start_from == ListingStartFrom.example and (
        example_is_generated(tool) or not version.example
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=MarketplaceMessages.LISTING_HAS_NO_EXAMPLE,
        )

    result = await install_tool_listing(
        session,
        tool=tool,
        listing=listing,
        version=version,
        user=current_user,
        guild_id=guild_context.guild_id,
        initiative_id=payload.initiative_id,
        start_from=payload.start_from.value,
        starts_on=payload.starts_on,
    )
    await session.commit()
    await count_install(guild_context.guild_id, listing.id)
    return MarketplaceInstallResult(
        kind=listing.kind,
        listing_uid=listing.uid,
        listing_version=version.version,
        result=result,
    )


@router.post(
    "/share",
    response_model=MarketplaceShareResult,
    status_code=status.HTTP_201_CREATED,
)
async def share_to_marketplace(
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    kind: Annotated[ListingKind, Form()],  # type: ignore[valid-type]
    entity_id: Annotated[int, Form()],
    name: Annotated[str, Form()],
    description: Annotated[str, Form()],
    example_entity_id: Annotated[int | None, Form()] = None,
    long_description: Annotated[str | None, Form()] = None,
    release_notes: Annotated[str | None, Form()] = None,
    listing_uid: Annotated[str | None, Form()] = None,
    images: Annotated[list[UploadFile], File()] = [],  # noqa: B006 — FastAPI reads the default, never mutates it
) -> MarketplaceShareResult:
    """Share an item from this community to the deployment's marketplace.

    The item is read the way exporting it reads it, on the member's own
    session — so a member shares only what they could export — and stripped
    to what belongs to the work (``publish_profile``). It then becomes a
    ``local`` listing, on the shelf straight away if the owner lets members
    publish directly, and otherwise waiting for the owner's review.

    Nothing is read from the community's storage: its pictures are its own.
    ``images`` are the pictures the member uploads for the listing with the
    share — the ones its card and page show — and they are the only pictures
    it has. A new version keeps the listing's pictures, like its name.
    """
    try:
        payload = MarketplaceShareRequest(
            kind=kind,
            entity_id=entity_id,
            example_entity_id=example_entity_id,
            name=name,
            description=description,
            long_description=long_description,
            release_notes=release_notes,
            listing_uid=listing_uid,
        )
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc
    if len(images) > MAX_LISTING_IMAGES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=MarketplaceMessages.SHARE_IMAGE_INVALID,
        )
    uploaded: list[bytes] = []
    for image in images:
        try:
            uploaded.append(await read_upload_bounded(image, MAX_IMAGE_BYTES))
        except FileTooLargeError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=MarketplaceMessages.SHARE_IMAGE_INVALID,
            ) from exc

    if guild_context.is_pam:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=MarketplaceMessages.SHARE_NOT_PERMITTED,
        )
    tool = TOOL_LISTING_KINDS.get(payload.kind)
    if tool is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=MarketplaceMessages.SHARE_INVALID,
        )
    if payload.example_entity_id is not None and example_is_generated(tool):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=MarketplaceMessages.SHARE_INVALID,
        )

    envelope = await export_for_listing(
        session,
        tool=tool,
        entity_id=payload.entity_id,
        user=current_user,
        guild_id=guild_context.guild_id,
    )
    example = (
        await export_for_listing(
            session,
            tool=tool,
            entity_id=payload.example_entity_id,
            user=current_user,
            guild_id=guild_context.guild_id,
        )
        if payload.example_entity_id is not None
        else None
    )

    # The catalogue's writer is the system engine, on this community's cohort;
    # the member's session has done its part by reading the item.
    async with cohorts.system_session(guild_context.guild_id) as system:
        hold = not await app_settings_service.marketplace_members_publish_directly(
            system
        )
        # The pictures the member uploaded become files in the marketplace's
        # media, in the same transaction as the listing that shows them.
        try:
            image_paths = [
                await store_uploaded_image(system, data) for data in uploaded
            ]
        except UploadedImageError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=MarketplaceMessages.SHARE_IMAGE_INVALID,
            ) from exc
        listing, version = await local_listings.submit_share(
            system,
            tool=tool,
            envelope=envelope,
            example=example,
            name=payload.name,
            description=payload.description,
            long_description=payload.long_description,
            release_notes=payload.release_notes,
            # The handle, which names the account the same way on every
            # shelf; a real name is each community's to show or not.
            publisher=handle_of(current_user),
            submitter_id=current_user.id,
            listing_uid=payload.listing_uid,
            images=image_paths,
            hold_for_review=hold,
        )
        await audit_service.record(
            system,
            event_type=AuditEventType.MARKETPLACE_LISTING_SHARED,
            actor_user_id=current_user.id,
            guild_id=guild_context.guild_id,
            detail={
                "listing_uid": listing.uid,
                "kind": listing.kind,
                "version": version.version,
                "awaiting_review": version.awaiting_review,
            },
        )
        await system.commit()
    return MarketplaceShareResult(
        uid=listing.uid,
        public_id=listing.public_id,
        version=version.version,
        awaiting_review=version.awaiting_review,
    )
