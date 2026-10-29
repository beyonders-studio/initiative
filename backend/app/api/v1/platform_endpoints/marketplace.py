"""Maintaining the catalog, and serving the artwork it is drawn with.

Reading the marketplace is not here: what a guild is offered depends on which
plug-ins it has installed, so the shelf and a listing's page are guild-addressed
and live in ``tenant_endpoints/marketplace.py``.

What is here is everything that decides *what this deployment carries*, which
is a property of the deployment rather than of any guild. The owner's routes
are gated on the capability that governs deployment configuration — because
that is what publishing a listing is: the rescan of their own catalog
directory, following the registry (its switch, "refresh now", and uploading a
signed bundle for a deployment that cannot reach it), uploading a listing file,
and reviewing what members share. A member's own routes here are the listings
they shared: reading them, and taking one down. Every write runs on the system
engine; sharing itself starts from inside a community, where the item is read
(``tenant_endpoints/marketplace.py``).

The third route is public: the mirrored artwork a registry's listings are
served from, which is the same bytes for everyone and carries nothing about
any guild.
"""

from typing import Annotated

from fastapi import (
    APIRouter,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import SessionDep, UserSessionDep, SystemSessionDep, CurrentUser
from app.api.v1.platform_endpoints.operator import ConfigManageDep
from app.core.audit_events import AuditEventType
from app.core.messages import MarketplaceMessages
from app.core.messages import MarketplaceRegistryMessages as RegistryCodes
from app.models.platform.marketplace_registry import MarketplaceMedia
from app.schemas.platform.marketplace import (
    ListingMediaRead,
    ListingUploadRequest,
    ListingUploadResult,
    MarketplaceLocalSettings,
    MarketplacePendingVersionRead,
    MarketplaceSharedListingRead,
    OperatorCatalogProblem,
    OperatorCatalogScanResult,
    serialize_listing_summary,
)
from app.schemas.platform.marketplace_registry import (
    RegistryRefreshRead,
    RegistrySettings,
    RegistrySkippedListing,
    RegistryStatusRead,
)
from app.services import audit as audit_service
from app.services.marketplace import catalog as catalog_service
from app.services.marketplace import listing_assets, local_listings
from app.services.tenant.attachments import FileTooLargeError, read_upload_bounded
from app.services.marketplace import tuf_registry as registry_service
from app.services.marketplace.catalog import CatalogError
from app.services.platform import app_settings as app_settings_service
from app.services.platform import auth_posture
from app.services.marketplace import operator_catalog as operator_catalog_service

router = APIRouter()


#: A mirrored image is addressed by the hex SHA-256 of its own bytes.
_DIGEST_LENGTH = 64
_HEX_DIGITS = frozenset("0123456789abcdef")


@router.post("/operator-catalog/rescan", response_model=OperatorCatalogScanResult)
async def rescan_operator_catalog(
    session: SystemSessionDep,
    owner: ConfigManageDep,
) -> OperatorCatalogScanResult:
    """Re-read the deployment's own catalog directory (``config.manage``).

    The same scan the boot runs, so a manifest dropped into the mounted
    directory appears without a restart, and one removed from it retires its
    listing. Answers 400 when no directory is configured or the configured one
    is not there, and 409 while a scan is already running.
    """
    if operator_catalog_service.operator_catalog_dir() is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=MarketplaceMessages.OPERATOR_CATALOG_NOT_CONFIGURED,
        )
    try:
        scan = await operator_catalog_service.scan_operator_catalog(session)
    except operator_catalog_service.OperatorCatalogScanRunning:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=MarketplaceMessages.OPERATOR_CATALOG_SCAN_RUNNING,
        ) from None
    if scan.directory_missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=MarketplaceMessages.OPERATOR_CATALOG_DIR_MISSING,
        )
    await audit_service.record(
        session,
        event_type=AuditEventType.MARKETPLACE_CATALOG_REFRESHED,
        actor_user_id=owner.id,
        detail={
            "source": "operator_catalog",
            "published": scan.published,
            "withdrawn": scan.withdrawn,
            "skipped": scan.skipped,
        },
    )
    await session.commit()
    return OperatorCatalogScanResult(
        published=scan.published,
        withdrawn=scan.withdrawn,
        skipped=scan.skipped,
        problems=[
            OperatorCatalogProblem(file=problem.file, reason=problem.reason)
            for problem in scan.problems
        ],
    )


# --- mirrored listing artwork ------------------------------------------------


@router.get("/media/{digest}", include_in_schema=False)
async def read_marketplace_media(digest: str, session: SessionDep) -> Response:
    """Serve one mirrored listing image.

    These bytes stand in for the image files this build ships under
    ``/marketplace/``, and are served the same way: no session required, and
    the same for everyone. They are catalog artwork — a listing's icon and
    screenshots — and carry nothing about any guild.

    Addressed by the digest of the bytes, so the content at a URL never
    changes and the response can be cached indefinitely. The content type is
    the one recorded when the image was mirrored, which came from the signed
    index rather than from the host that served it.
    """
    if len(digest) != _DIGEST_LENGTH or any(c not in _HEX_DIGITS for c in digest):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=MarketplaceMessages.MEDIA_NOT_FOUND,
        )
    media = (
        await session.exec(
            select(MarketplaceMedia).where(MarketplaceMedia.sha256 == digest)
        )
    ).first()
    if media is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=MarketplaceMessages.MEDIA_NOT_FOUND,
        )
    return Response(
        content=media.data,
        media_type=media.content_type,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


# --- the registry (operator) --------------------------------------------------

#: How each refusal of a refresh or a bundle answers.
_REFUSAL_STATUS: dict[str, int] = {
    RegistryCodes.NOT_CONFIGURED: status.HTTP_503_SERVICE_UNAVAILABLE,
    RegistryCodes.ROOT_INVALID: status.HTTP_503_SERVICE_UNAVAILABLE,
    RegistryCodes.DISABLED: status.HTTP_409_CONFLICT,
    RegistryCodes.REFRESH_IN_PROGRESS: status.HTTP_409_CONFLICT,
    RegistryCodes.BUNDLE_INVALID: status.HTTP_400_BAD_REQUEST,
}

#: The largest bundle the upload route reads.
_MAX_BUNDLE_BYTES = registry_service.MAX_BUNDLE_BYTES


def _refresh_read(result: registry_service.RefreshResult) -> RegistryRefreshRead:
    return RegistryRefreshRead(
        root_version=result.root_version,
        upserted=result.upserted,
        withdrawn=result.withdrawn,
        unchanged=result.unchanged,
        skipped=[
            RegistrySkippedListing(name=item.name, code=item.code)
            for item in result.skipped
        ],
    )


def _refused(code: str, *, fetched: bool) -> HTTPException:
    """A refusal's answer. The repository itself failing is the registry's
    problem on a fetch (502) and the upload's on a bundle (422)."""
    fallback = (
        status.HTTP_502_BAD_GATEWAY
        if fetched
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    return HTTPException(status_code=_REFUSAL_STATUS.get(code, fallback), detail=code)


async def _record_refresh(
    session: AsyncSession,
    result: registry_service.RefreshResult,
    *,
    actor_user_id: int,
    source: str,
) -> None:
    # The refresh owns its own transaction, so the record follows it on this
    # session rather than riding the write it describes.
    await audit_service.record(
        session,
        event_type=AuditEventType.MARKETPLACE_CATALOG_REFRESHED,
        actor_user_id=actor_user_id,
        detail={
            "source": source,
            "published": result.upserted,
            "withdrawn": result.withdrawn,
            "skipped": len(result.skipped),
        },
    )
    await session.commit()


@router.get("/registry/status", response_model=RegistryStatusRead)
async def read_registry_status(
    session: SystemSessionDep, current_user: ConfigManageDep
) -> RegistryStatusRead:
    """Where this deployment stands with the registry (``config.manage``).

    The switch, whether this build has a trusted root, and how the last
    refresh or bundle went.
    """
    enabled = await app_settings_service.marketplace_registry_enabled(session)
    state = await registry_service.read_status(session, enabled=enabled)
    return RegistryStatusRead(
        enabled=state.enabled,
        configured=state.configured,
        custom_root=state.custom_root,
        registry_url=state.registry_url,
        root_version=state.root_version,
        expires_at=state.expires_at,
        last_source=state.source,
        last_attempt_at=state.last_attempt_at,
        last_success_at=state.last_success_at,
        last_error=state.last_error,
        listing_count=state.listing_count,
    )


@router.put("/registry/settings", response_model=RegistrySettings)
async def update_registry_settings(
    payload: RegistrySettings, session: UserSessionDep, owner: ConfigManageDep
) -> RegistrySettings:
    """Follow the registry, or stop (``config.manage``). What already arrived
    stays; switching back on picks up from where it left off."""
    await auth_posture.change(
        auth_posture.RuleContext.platform(session, owner),
        {"marketplace_registry_enabled": payload.enabled},
    )
    return RegistrySettings(
        enabled=await app_settings_service.marketplace_registry_enabled(session)
    )


@router.post("/registry/refresh", response_model=RegistryRefreshRead)
async def refresh_registry_now(
    session: SystemSessionDep, current_user: ConfigManageDep
) -> RegistryRefreshRead:
    """Fetch, verify and apply the registry now (``config.manage``).

    The same code the background refresh runs. A refresh already in flight is
    reported rather than queued, and a refusal answers with the code naming it.
    """
    result = await registry_service.refresh_registry(session, force=True)
    if result.code is not None:
        raise _refused(result.code, fetched=True)
    await _record_refresh(
        session, result, actor_user_id=current_user.id, source="registry"
    )
    return _refresh_read(result)


@router.post("/registry/bundle", response_model=RegistryRefreshRead)
async def upload_registry_bundle(
    file: Annotated[UploadFile, File()],
    session: SystemSessionDep,
    owner: ConfigManageDep,
) -> RegistryRefreshRead:
    """Apply a registry bundle (``config.manage``).

    A tar of a registry's ``metadata/`` and ``targets/`` directories, for a
    deployment that cannot reach the registry. It is verified against the
    trusted root exactly as a fetched repository is, and applied the same way.
    """
    try:
        archive = await read_upload_bounded(file, _MAX_BUNDLE_BYTES)
    except FileTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=RegistryCodes.BUNDLE_INVALID,
        ) from exc
    try:
        result = await registry_service.apply_bundle(session, archive)
    except registry_service.RegistryError as exc:
        raise _refused(exc.code, fetched=False) from exc
    if result.code is not None:
        raise _refused(result.code, fetched=False)
    await _record_refresh(
        session, result, actor_user_id=owner.id, source="registry_bundle"
    )
    return _refresh_read(result)


# --- what this deployment adds itself (local) --------------------------------


@router.get("/local/settings", response_model=MarketplaceLocalSettings)
async def read_local_marketplace_settings(
    session: UserSessionDep, _owner: ConfigManageDep
) -> MarketplaceLocalSettings:
    """How this deployment takes its members' shares (``config.manage``)."""
    return MarketplaceLocalSettings(
        members_publish_directly=await app_settings_service.marketplace_members_publish_directly(
            session
        )
    )


@router.put("/local/settings", response_model=MarketplaceLocalSettings)
async def update_local_marketplace_settings(
    payload: MarketplaceLocalSettings,
    session: UserSessionDep,
    owner: ConfigManageDep,
) -> MarketplaceLocalSettings:
    """Let members publish straight to the shelf, or have each share wait for
    review. Changing it moves nothing already waiting."""
    await auth_posture.change(
        auth_posture.RuleContext.platform(session, owner),
        {"marketplace_members_publish_directly": payload.members_publish_directly},
    )
    return MarketplaceLocalSettings(
        members_publish_directly=await app_settings_service.marketplace_members_publish_directly(
            session
        )
    )


@router.get("/local/pending", response_model=list[MarketplacePendingVersionRead])
async def list_pending_shares(
    session: SystemSessionDep, _owner: ConfigManageDep
) -> list[MarketplacePendingVersionRead]:
    """Every shared version waiting for review, oldest first, with what it
    would publish — the envelope and its example, as the shelf would carry
    them."""
    return [
        MarketplacePendingVersionRead(
            uid=pending.listing.uid,
            public_id=pending.listing.public_id,
            kind=pending.listing.kind,
            name=pending.listing.name,
            publisher=pending.listing.publisher,
            description=pending.listing.description,
            version=pending.version.version,
            release_notes=pending.version.release_notes,
            submitted_at=pending.version.published_at,
            is_new_listing=pending.listing.latest_version_id is None,
            definition=dict(pending.version.definition or {}),
            example=dict(pending.version.example) if pending.version.example else None,
        )
        for pending in await local_listings.pending_versions(session)
    ]


async def _review(
    session: AsyncSession, owner_id: int, uid: str, version: str, *, approve: bool
) -> None:
    if approve:
        await local_listings.approve_version(session, uid, version)
    else:
        await local_listings.reject_version(session, uid, version)
    await audit_service.record(
        session,
        event_type=AuditEventType.MARKETPLACE_LISTING_REVIEWED,
        actor_user_id=owner_id,
        detail={
            "listing_uid": uid,
            "version": version,
            "decision": "approved" if approve else "refused",
        },
    )
    await session.commit()


@router.post(
    "/local/{uid}/versions/{version}/approve",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def approve_shared_version(
    uid: str, version: str, session: SystemSessionDep, owner: ConfigManageDep
) -> Response:
    """Put a shared version on the shelf. It becomes the listing's latest."""
    await _review(session, owner.id, uid, version, approve=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/local/{uid}/versions/{version}/refuse",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def refuse_shared_version(
    uid: str, version: str, session: SystemSessionDep, owner: ConfigManageDep
) -> Response:
    """Refuse a shared version. It is deleted, and so is a listing left with no
    version — it was never offered, so nothing depends on it."""
    await _review(session, owner.id, uid, version, approve=False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/local/upload",
    response_model=ListingUploadResult,
    status_code=status.HTTP_201_CREATED,
)
async def upload_listing_file(
    payload: ListingUploadRequest, session: SystemSessionDep, owner: ConfigManageDep
) -> Response:
    """Publish a listing file (``config.manage``).

    The manifest a catalog directory or a registry carries, published as a
    ``local`` listing, on the shelf straight away. A file the catalogue will
    not take answers 422 with the validator's reason beside the code, so the
    person who uploaded it can see what to fix.
    """
    try:
        listing = await local_listings.upload_listing(session, payload.manifest)
    except CatalogError as exc:
        await session.rollback()
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "detail": MarketplaceMessages.LISTING_UPLOAD_INVALID,
                "problem": str(exc)[:500],
            },
        )
    version = await catalog_service.get_listing_version(
        session, listing.latest_version_id
    )
    await audit_service.record(
        session,
        event_type=AuditEventType.MARKETPLACE_LISTING_UPLOADED,
        actor_user_id=owner.id,
        detail={
            "listing_uid": listing.uid,
            "kind": listing.kind,
            "version": version.version if version else None,
        },
    )
    await session.commit()
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=ListingUploadResult(
            uid=listing.uid,
            public_id=listing.public_id,
            version=version.version if version else "",
        ).model_dump(mode="json"),
    )


@router.get("/local/mine", response_model=list[MarketplaceSharedListingRead])
async def list_my_shares(
    session: UserSessionDep, current_user: CurrentUser
) -> list[MarketplaceSharedListingRead]:
    """The listings the signed-in member shared, with any version still
    waiting for review."""
    listings = await local_listings.listings_submitted_by(session, current_user.id)
    versions = await catalog_service.get_listing_versions(
        session, [listing.latest_version_id for listing in listings]
    )
    waiting = await local_listings.waiting_versions_of(
        session, [listing.id for listing in listings if listing.id is not None]
    )
    return [
        MarketplaceSharedListingRead(
            **serialize_listing_summary(
                listing, versions.get(listing.latest_version_id)
            ).model_dump(),
            pending_versions=waiting.get(listing.id, []),
        )
        for listing in listings
    ]


@router.delete("/local/{uid}", status_code=status.HTTP_204_NO_CONTENT)
async def withdraw_my_share(
    uid: str, session: SystemSessionDep, current_user: CurrentUser
) -> Response:
    """Take down a listing the signed-in member shared. Communities that
    installed a copy keep it."""
    await local_listings.withdraw_share(session, uid, current_user.id)
    await audit_service.record(
        session,
        event_type=AuditEventType.MARKETPLACE_LISTING_WITHDRAWN,
        actor_user_id=current_user.id,
        detail={"listing_uid": uid},
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/local/media",
    response_model=ListingMediaRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_listing_picture(
    file: Annotated[UploadFile, File()],
    session: SystemSessionDep,
    _owner: ConfigManageDep,
) -> ListingMediaRead:
    """Upload a picture for a listing file (``config.manage``).

    Returns the path the marketplace serves it from, for the manifest to name —
    as the listing's artwork, or as a picture in its content (a library's, an
    image in a document). A listing's pictures are only ever uploaded like
    this; none is taken from a community.
    """
    try:
        data = await read_upload_bounded(file, listing_assets.MAX_IMAGE_BYTES)
        path = await listing_assets.store_uploaded_image(session, data)
    except (FileTooLargeError, listing_assets.UploadedImageError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=MarketplaceMessages.SHARE_IMAGE_INVALID,
        ) from exc
    await session.commit()
    return ListingMediaRead(path=path)
