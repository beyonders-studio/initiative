"""What a deployment adds to its own marketplace.

A deployment's marketplace is the catalogue it was shipped and the registries it
trusts, plus what it adds itself: ``local`` listings. Two ways in:

* **A member shares an item.** The item is exported, stripped to what belongs
  to the work (``publish_profile``), and submitted. Unless the owner lets
  members publish directly, it waits for the owner's review, stored but not
  offered.
* **The owner uploads a listing file** — the same manifest a catalog
  directory or a registry carries — and it is published as it is.

A ``local`` listing is a plain catalogue row, deployment-wide like every other.
Nothing is signed, and there is no file or index behind it, so no sweep of the
other sources ever retires one; it is taken down by the member who shared it,
or refused by the owner before it is ever offered.

Every write here runs on the system engine: the catalogue has no request-path
writer. The member's own export runs before, on their own session.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import CodedError
from app.core.tools import Tool
from app.models.platform.marketplace import (
    UID_ALPHABET,
    UID_LENGTH,
    MarketplaceListing,
    MarketplaceListingVersion,
)
from app.services.marketplace import catalog as catalog_service
from app.services.marketplace import vendor_values as vendor_values_service
from app.services.marketplace.catalog import DEFAULT_AVATAR_URL, CatalogError
from app.services.marketplace.definitions import LOCAL_SOURCE
from app.services.marketplace.tool_listings import ListingTooLargeError

__all__ = [
    "LocalListingError",
    "PendingVersion",
    "approve_version",
    "listings_submitted_by",
    "mint_uid",
    "pending_versions",
    "reject_version",
    "submit_share",
    "upload_listing",
    "waiting_versions_of",
    "withdraw_share",
]

#: The publisher prefix a member's share is published under. Its public id is
#: this and its own uid, so two shares can never collide on a slug.
LOCAL_PUBLIC_ID_PREFIX = "local."


class LocalListingError(CodedError):
    """A share or a review that cannot go ahead: 404 when there is no such
    listing, 422 for a share that cannot be taken."""

    status_code = 422


def mint_uid() -> str:
    """A fresh catalog uid, for a listing this deployment publishes itself."""
    return "".join(secrets.choice(UID_ALPHABET) for _ in range(UID_LENGTH))


async def _version_count(session: AsyncSession, listing_id: int) -> int:
    rows = await session.exec(
        select(MarketplaceListingVersion.id).where(
            MarketplaceListingVersion.listing_id == listing_id
        )
    )
    return len(rows.all())


async def submit_share(
    session: AsyncSession,
    *,
    tool: Tool,
    envelope: dict[str, Any],
    example: dict[str, Any] | None,
    name: str,
    description: str,
    long_description: str | None,
    release_notes: str | None,
    publisher: str,
    submitter_id: int,
    listing_uid: str | None,
    hold_for_review: bool,
    images: Sequence[str] = (),
) -> tuple[MarketplaceListing, MarketplaceListingVersion]:
    """Publish a member's share as a new listing, or as a new version of one
    they shared before.

    A new version keeps the listing's name, description and pictures: those
    are what the shelf shows, and changing them is a publish of its own that nothing here
    offers yet. Versions are numbered in the order they were submitted.
    """
    from app.core.messages import MarketplaceMessages

    if listing_uid is None:
        uid = mint_uid()
        public_id = f"{LOCAL_PUBLIC_ID_PREFIX}{uid.lower()}"
        version = "1.0.0"
    else:
        existing = await catalog_service.get_listing_by_uid(session, listing_uid)
        if (
            existing is None
            or existing.source != LOCAL_SOURCE
            or existing.submitted_by != submitter_id
        ):
            # Somebody else's listing reads the same as none: this is not a way
            # to learn who shared what.
            raise LocalListingError(MarketplaceMessages.LISTING_NOT_FOUND, 404)
        if existing.kind != tool.value:
            raise LocalListingError(MarketplaceMessages.SHARE_KIND_MISMATCH)
        uid, public_id = existing.uid, existing.public_id
        name, description = existing.name, existing.description
        long_description = existing.long_description
        images = list(existing.images or [])
        version = f"{await _version_count(session, existing.id) + 1}.0.0"

    manifest: dict[str, Any] = {
        "uid": uid,
        "public_id": public_id,
        "kind": tool.value,
        "name": name,
        "publisher": publisher,
        "description": description,
        "long_description": long_description,
        "avatar_url": DEFAULT_AVATAR_URL,
        # Pictures the member uploaded for the listing, already in the
        # marketplace's media. Nothing here comes from the community.
        "images": list(images),
        "version": version,
        "release_notes": release_notes,
        "definition": envelope,
        "example": example,
    }
    try:
        listing = await catalog_service.upsert_listing(
            session,
            manifest,
            source=LOCAL_SOURCE,
            hold_for_review=hold_for_review,
            submitted_by=submitter_id,
        )
    except CatalogError as exc:
        too_large = isinstance(exc.__cause__, ListingTooLargeError)
        raise LocalListingError(
            MarketplaceMessages.SHARE_TOO_LARGE
            if too_large
            else MarketplaceMessages.SHARE_INVALID
        ) from exc
    stored = (
        await session.exec(
            select(MarketplaceListingVersion).where(
                MarketplaceListingVersion.listing_id == listing.id,
                MarketplaceListingVersion.version == version,
            )
        )
    ).one()
    return listing, stored


async def upload_listing(
    session: AsyncSession, manifest: dict[str, Any]
) -> MarketplaceListing:
    """Publish a listing file the owner uploaded, as it is.

    The same manifest a catalog directory or a registry carries, held to the
    same validator. A uid already held by another source is refused rather than
    taken over: the catalogue that published it owns it.
    """
    uid = str(manifest.get("uid", ""))
    public_id = str(manifest.get("public_id", ""))
    for held in (
        await catalog_service.get_listing_by_uid(session, uid),
        await catalog_service.get_listing(session, public_id),
    ):
        if held is not None and held.source != LOCAL_SOURCE:
            raise CatalogError(
                f"{held.public_id} is published by the {held.source} catalogue"
            )
        if held is not None and held.submitted_by is not None:
            raise CatalogError(f"{held.public_id} was shared by a member")
    return await catalog_service.upsert_listing(session, manifest, source=LOCAL_SOURCE)


class PendingVersion:
    """A version waiting for review, with the listing it belongs to."""

    __slots__ = ("listing", "version")

    def __init__(
        self, listing: MarketplaceListing, version: MarketplaceListingVersion
    ) -> None:
        self.listing = listing
        self.version = version


async def pending_versions(session: AsyncSession) -> list[PendingVersion]:
    """Every version waiting for review, oldest first."""
    rows = await session.exec(
        select(MarketplaceListing, MarketplaceListingVersion)
        .join(
            MarketplaceListingVersion,
            MarketplaceListingVersion.listing_id == MarketplaceListing.id,
        )
        .where(MarketplaceListingVersion.awaiting_review.is_(True))
        .order_by(MarketplaceListingVersion.published_at)
    )
    return [PendingVersion(listing, version) for listing, version in rows.all()]


async def _pending(
    session: AsyncSession, uid: str, version: str
) -> tuple[MarketplaceListing, MarketplaceListingVersion]:
    from app.core.messages import MarketplaceMessages

    listing = await catalog_service.get_listing_by_uid(session, uid)
    row = None
    if listing is not None:
        row = (
            await session.exec(
                select(MarketplaceListingVersion).where(
                    MarketplaceListingVersion.listing_id == listing.id,
                    MarketplaceListingVersion.version == version,
                    MarketplaceListingVersion.awaiting_review.is_(True),
                )
            )
        ).first()
    if listing is None or row is None:
        raise LocalListingError(MarketplaceMessages.LISTING_NOT_FOUND, 404)
    return listing, row


async def approve_version(
    session: AsyncSession, uid: str, version: str
) -> MarketplaceListing:
    """Put a reviewed version on the shelf: it becomes the listing's latest,
    and a listing that had nothing offered yet becomes available."""
    listing, row = await _pending(session, uid, version)
    row.awaiting_review = False
    session.add(row)
    listing.latest_version_id = row.id
    listing.available = True
    listing.updated_at = datetime.now(UTC)
    session.add(listing)
    await session.flush()
    await vendor_values_service.sync_required_for_listing(
        session, listing.uid, row.definition
    )
    return listing


async def reject_version(session: AsyncSession, uid: str, version: str) -> None:
    """Refuse a version. It is deleted, and so is a listing that has no other
    version: nothing was ever offered, so nothing anywhere depends on it."""
    listing, row = await _pending(session, uid, version)
    await session.delete(row)
    await session.flush()
    if await _version_count(session, listing.id) == 0:
        await session.delete(listing)
        await session.flush()


async def listings_submitted_by(
    session: AsyncSession, user_id: int
) -> Sequence[MarketplaceListing]:
    """The listings one member has shared, newest first."""
    return (
        await session.exec(
            select(MarketplaceListing)
            .where(MarketplaceListing.submitted_by == user_id)
            .order_by(MarketplaceListing.created_at.desc())
        )
    ).all()


async def waiting_versions_of(
    session: AsyncSession, listing_ids: Sequence[int]
) -> dict[int, list[str]]:
    """The versions still waiting for review, per listing, oldest first."""
    if not listing_ids:
        return {}
    rows = await session.exec(
        select(MarketplaceListingVersion.listing_id, MarketplaceListingVersion.version)
        .where(
            MarketplaceListingVersion.listing_id.in_(list(listing_ids)),
            MarketplaceListingVersion.awaiting_review.is_(True),
        )
        .order_by(MarketplaceListingVersion.published_at)
    )
    waiting: dict[int, list[str]] = {}
    for listing_id, version in rows.all():
        waiting.setdefault(listing_id, []).append(version)
    return waiting


async def withdraw_share(session: AsyncSession, uid: str, user_id: int) -> None:
    """Take down a listing its member shared.

    Withdrawn, not deleted, like any other listing: a community that installed
    a copy keeps it. Versions still waiting for review go, since they were
    never offered.
    """
    from app.core.messages import MarketplaceMessages

    listing = await catalog_service.get_listing_by_uid(session, uid)
    if listing is None or listing.submitted_by != user_id:
        raise LocalListingError(MarketplaceMessages.LISTING_NOT_FOUND, 404)
    for row in (
        await session.exec(
            select(MarketplaceListingVersion).where(
                MarketplaceListingVersion.listing_id == listing.id,
                MarketplaceListingVersion.awaiting_review.is_(True),
            )
        )
    ).all():
        await session.delete(row)
    await session.flush()
    if listing.latest_version_id is None:
        await session.delete(listing)
    else:
        listing.available = False
        listing.updated_at = datetime.now(UTC)
        session.add(listing)
    await session.flush()
