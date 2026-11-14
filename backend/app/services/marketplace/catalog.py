"""Reading and populating the marketplace catalog.

Two audiences, and the split between them is the security shape of this module:

* **Readers** — every browse and detail query, and the listing lookup an install
  does. These run on whatever session the request already has (a platform tier,
  or a guild role), and touch nothing but the two catalog tables.
* **The writer** — ``upsert_listing``, called only from the system-engine path
  (boot seeding, the operator's catalog, uploads, and the registry refresh). No
  user request reaches it. A plug-in's ``registration`` block, from any of them,
  goes to the one writer of a registration's plug-in facts
  (:mod:`app.services.marketplace.registrations`).

Everything a publisher supplies is validated before it lands: the uid's shape,
the ``public_id``'s, the version string's, the attribution, and the definition's
— the last by the same validator the guild-scoped API uses.

Two of those checks are about *who* rather than *what*. Attribution is required,
so nothing is published anonymously; and the ``core.*`` namespace is refused to
any source but this build, so an id cannot imply a provenance the listing does
not have.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Exists, func, or_
from sqlalchemy import update as sa_update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.version import get_version
from app.db.query import apply_pagination
from app.db.session import routed_guild_id
from app.models.platform.marketplace import (
    UID_ALPHABET,
    UID_LENGTH,
    MarketplaceListing,
    MarketplaceListingVersion,
)
from app.services.marketplace import contract, plugin_api, registration_lookup
from app.services.marketplace import registrations as registrations_service
from app.services.marketplace import vendor_values as vendor_values_service
from app.services.marketplace.definitions import (
    LISTING_KINDS,
    LISTING_SOURCES,
    ListingDefinitionError,
    normalize_listing_definition,
    normalize_listing_example,
    normalize_publisher,
    plugin_widget_type,
    reserved_prefix_problem,
)
from app.services.marketplace.manifest_values import check_public_id

__all__ = [
    "REGISTRY_SOURCE",
    "CatalogError",
    "CatalogSourceConflict",
    "bump_installs_count",
    "get_listing",
    "get_listing_by_uid",
    "get_listing_version",
    "get_listing_versions",
    "list_listings",
    "listing_avatars",
    "listing_versions",
    "published_uids",
    "resolve_installable_version",
    "upsert_listing",
    "version_is_compatible",
    "version_runs_here",
    "withdraw_builtins_except",
    "withdraw_listing",
]

#: Characters a version string may use. Deliberately an explicit set rather than
#: a semver pattern — the catalog stores what the publisher published and only
#: needs it to be a safe, short, comparable token. From the vendored contract,
#: which is what the plugin-kit checks a listing against before it is published.
_VERSION_CHARS = contract.charset("version")
_MAX_VERSION = contract.cap("versionLength")


class CatalogError(ValueError):
    """A listing the catalog will not accept. Raised during seeding/refresh, so
    the message names the problem for whoever is publishing."""


class CatalogSourceConflict(CatalogError):
    """The listing's uid or name is held by a listing from another source."""


#: The source every listing a registry refresh publishes is stored under.
REGISTRY_SOURCE = "registry"


def _check_uid(uid: str) -> str:
    if len(uid) != UID_LENGTH:
        raise CatalogError(f"uid must be {UID_LENGTH} characters, got {len(uid)}")
    for char in uid:
        if char not in UID_ALPHABET:
            raise CatalogError(f"uid contains {char!r}, which is not in the alphabet")
    return uid


def _check_public_id(public_id: str) -> str:
    # One rule for the shape of a `<publisher>.<slug>` id, wherever it appears —
    # a listing's own, or the one a service plug-in names itself by.
    try:
        return check_public_id(public_id, what="public_id")
    except ListingDefinitionError as exc:
        raise CatalogError(str(exc)) from exc


#: Characters an artwork path may use — an explicit allow-list, so a stored
#: path is exactly what a browser will request.
_ARTWORK_CHARS = contract.charset("artwork")


#: Shown for a listing that ships no artwork of its own. The app's own mark,
#: which is the honest thing for it to say: nobody drew an icon for this one.
#: Same-origin like every other artwork path, so it obeys the rule below.
DEFAULT_AVATAR_URL = "/icons/logo.svg"


def _check_artwork_path(value: str, *, field: str) -> str:
    """A listing's artwork must be a same-origin path — the shipped files live
    under ``/marketplace/``. A registry wanting third-party artwork mirrors it
    locally rather than linking out."""
    if not value.startswith("/"):
        raise CatalogError(f"{field} must be a same-origin path starting with '/'")
    for char in value:
        if char not in _ARTWORK_CHARS:
            raise CatalogError(f"{field} contains {char!r}, which is not allowed")
    if "//" in value or "/../" in value or value.endswith("/.."):
        raise CatalogError(f"{field} must be a plain path with no '//' or '..'")
    return value


def _check_version(version: str) -> str:
    if not version or len(version) > _MAX_VERSION:
        raise CatalogError(f"version must be 1..{_MAX_VERSION} characters")
    for char in version:
        if char not in _VERSION_CHARS:
            raise CatalogError(f"version contains {char!r}, which is not allowed")
    return version


def _version_tuple(value: str) -> tuple[int, ...]:
    """A version as comparable integers, ignoring any pre-release suffix.

    Only used to answer "is this deployment new enough", so a coarse reading is
    the right one: `1.2.3-rc1` and `1.2.3` are the same floor.
    """
    head = value.split("-", 1)[0].split("+", 1)[0]
    parts: list[int] = []
    for chunk in head.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            break
    return tuple(parts)


def version_is_compatible(min_app_version: str | None) -> bool:
    """Whether this deployment is new enough to run a listing version.

    A definition can name only what its app build has a renderer for, so a
    version needing a newer app is hidden from browse and refused on install
    rather than landing as a canvas full of error tiles.
    """
    if not min_app_version:
        return True
    return _version_tuple(get_version()) >= _version_tuple(min_app_version)


def version_runs_here(version: MarketplaceListingVersion) -> bool:
    """Whether this deployment can install a listing version: new enough
    (:func:`version_is_compatible`), and serving the plug-in API contract it
    needs (:func:`~app.services.marketplace.plugin_api.serves_plugin_api`)."""
    return version_is_compatible(
        version.min_app_version
    ) and plugin_api.serves_plugin_api(version.min_plugin_api)


def _min_plugin_api(manifest: dict[str, Any], public_id: str) -> str | None:
    """The contract a listing version needs, as its listing states it beside
    ``min_app_version`` or its plug-in's manifest does. Both may: the registry
    and the kit's packer write it in each place. When both do, they agree."""
    raw_definition = manifest.get("definition")
    stated = {
        "listing": manifest.get("min_plugin_api"),
        "manifest": raw_definition.get("min_plugin_api")
        if isinstance(raw_definition, dict)
        else None,
    }
    try:
        found = {
            where: plugin_api.check_min_plugin_api(value)
            for where, value in stated.items()
            if value is not None
        }
    except ValueError as exc:
        raise CatalogError(f"{public_id}: {exc}") from exc
    if len(set(found.values())) > 1:
        raise CatalogError(
            f"{public_id}: min_plugin_api {found['listing']!r} differs from its "
            f"manifest's {found['manifest']!r}"
        )
    return next(iter(found.values()), None)


# --- reads ------------------------------------------------------------------


async def _unoffered_plugin(guild_id: int | None) -> Exists:
    """Matches a plug-in listing this deployment does not run the service for
    in community ``guild_id``.

    Read from the registration snapshot rather than joined from the table:
    nothing on the request path holds a grant on it, so it is loaded on the
    system engine instead.

    A listing with no published version and one whose definition names no
    service — a plug-in that mounts one of this build's own tools — match nothing
    here and stay on the shelf.
    """
    latest = MarketplaceListingVersion
    offered = sorted(await registration_lookup.enabled_service_ids(guild_id))
    return (
        select(latest.id)
        .where(
            latest.id == MarketplaceListing.latest_version_id,
            latest.definition["plugin_kind"].astext == "service",
            # A declarative plug-in has no service block and is its listing's
            # public id.
            func.coalesce(
                latest.definition["service"]["public_id"].astext,
                MarketplaceListing.public_id,
            ).notin_(offered),
        )
        .exists()
    )


async def list_listings(
    session: AsyncSession,
    *,
    kind: str | None = None,
    query: str | None = None,
    include_unavailable: bool = False,
    bundled_with: Sequence[str] | None = None,
    sources: Sequence[str] | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[Sequence[MarketplaceListing], int]:
    """A page of listings, newest first, with the total that matched.

    ``bundled_with`` names the plug-in uids the caller is entitled to see bundled
    dashboards for — the plug-ins a guild has installed. Left unset, a dashboard
    that ships with a plug-in is not offered at all, which is the right answer for
    a caller that has no guild to answer it for: such a dashboard draws that
    plug-in's widgets, so offering it where the plug-in cannot be is offering a canvas
    of tiles with nothing behind them.

    A plug-in whose service this deployment has not wired up is not offered
    either, for the same reason: a catalog is published to every deployment,
    and a registration is how one says it runs that plug-in. The rule is read here
    rather than passed in, so browsing, reading a listing and installing one
    cannot end up disagreeing about what this deployment carries. It is asked
    for the community the session is routed to, so a plug-in limited to the
    operations community is on that community's shelf alone.

    ``sources``, when given, keeps only listings that reached the deployment
    one of those ways — what a client showing a narrower catalogue asks for.
    """
    statement = select(MarketplaceListing)
    count_statement = select(func.count()).select_from(MarketplaceListing)

    filters = []
    if not include_unavailable:
        filters.append(MarketplaceListing.available.is_(True))
    if kind:
        filters.append(MarketplaceListing.kind == kind)
    if sources:
        filters.append(MarketplaceListing.source.in_(list(sources)))
    if bundled_with:
        filters.append(
            or_(
                MarketplaceListing.bundled_with_uid.is_(None),
                MarketplaceListing.bundled_with_uid.in_(list(bundled_with)),
            )
        )
    else:
        filters.append(MarketplaceListing.bundled_with_uid.is_(None))
    unoffered_plugin = await _unoffered_plugin(routed_guild_id(session))
    filters.append(~unoffered_plugin)
    if query:
        # Case-insensitive across the three fields someone would actually type.
        needle = f"%{query.strip()}%"
        filters.append(
            or_(
                MarketplaceListing.name.ilike(needle),
                MarketplaceListing.description.ilike(needle),
                MarketplaceListing.publisher.ilike(needle),
            )
        )
    for condition in filters:
        statement = statement.where(condition)
        count_statement = count_statement.where(condition)

    total = (await session.exec(count_statement)).one()
    # By name, then by id: listings may share a name, and without a unique
    # last key their order could change between one page's query and the
    # next, showing one twice and another never.
    statement = apply_pagination(
        statement.order_by(MarketplaceListing.name, MarketplaceListing.id),
        page,
        page_size,
    )
    return (await session.exec(statement)).all(), int(total)


async def get_listing(
    session: AsyncSession, public_id: str
) -> MarketplaceListing | None:
    return (
        await session.exec(
            select(MarketplaceListing).where(MarketplaceListing.public_id == public_id)
        )
    ).first()


async def listing_avatars(session: AsyncSession, uids: Sequence[str]) -> dict[str, str]:
    """Artwork for the given listings, by uid.

    Read rather than pinned into an install: a listing that changes its picture
    should change everywhere it is drawn, and unlike a definition there is
    nothing here an install needs held still.
    """
    unique = {uid for uid in uids if uid}
    if not unique:
        return {}
    rows = await session.exec(
        select(MarketplaceListing.uid, MarketplaceListing.avatar_url).where(
            MarketplaceListing.uid.in_(unique)
        )
    )
    return {uid: avatar for uid, avatar in rows if avatar}


async def get_listing_by_uid(
    session: AsyncSession, uid: str
) -> MarketplaceListing | None:
    return (
        await session.exec(
            select(MarketplaceListing).where(MarketplaceListing.uid == uid)
        )
    ).first()


async def get_listing_version(
    session: AsyncSession, version_id: int | None
) -> MarketplaceListingVersion | None:
    if version_id is None:
        return None
    return (
        await session.exec(
            select(MarketplaceListingVersion).where(
                MarketplaceListingVersion.id == version_id
            )
        )
    ).first()


async def get_listing_versions(
    session: AsyncSession, version_ids: Sequence[int | None]
) -> dict[int, MarketplaceListingVersion]:
    """The named versions, keyed by id.

    What a page of listings needs: browse draws every card from its listing's
    latest version, and asking for them one at a time is a round trip per card.
    Ids that name nothing are simply absent from the result, so a listing with
    no published version reads the same as it does one at a time.
    """
    wanted = {version_id for version_id in version_ids if version_id is not None}
    if not wanted:
        return {}
    rows = await session.exec(
        select(MarketplaceListingVersion).where(
            MarketplaceListingVersion.id.in_(wanted)
        )
    )
    return {version.id: version for version in rows if version.id is not None}


async def resolve_installable_version(
    session: AsyncSession, listing: MarketplaceListing
) -> MarketplaceListingVersion | None:
    """The version a guild would get right now, or ``None`` if there is none it
    can run. A listing whose latest version needs a newer app is not silently
    downgraded to an older one — the guild is told to upgrade instead."""
    version = await get_listing_version(session, listing.latest_version_id)
    if version is None:
        return None
    return version if version_is_compatible(version.min_app_version) else None


# --- writes (system engine only) --------------------------------------------


async def upsert_listing(
    session: AsyncSession,
    manifest: dict[str, Any],
    *,
    source: str,
    bundled_with: str | None = None,
    hold_for_review: bool = False,
    submitted_by: int | None = None,
) -> MarketplaceListing:
    """Create or update one listing and the version its manifest describes.

    Idempotent by ``uid``: re-seeding the same manifest updates metadata in place
    and leaves the version rows alone. Both identities are unique and neither is
    reassignable — a uid already held by a different ``public_id`` is refused,
    and vice versa, so a uid keeps meaning the listing it was first published
    for.

    ``bundled_with`` names the plug-in this listing is published as part of, and is
    a third thing that cannot be reassigned. It is set only by
    :func:`_publish_bundled_dashboards`, which is the plug-in's own publish; every
    other caller leaves it ``None`` and is publishing something that stands on
    its own. A publish whose ownership disagrees with the stored row is refused
    rather than applied, in either direction.

    ``hold_for_review`` stores the version without offering it: it does not
    become the listing's latest, a new listing is created unavailable, and an
    existing one keeps the name and description it is shown under. Approving
    it is :func:`approve_version`. ``submitted_by`` records the member who
    shared a new listing; it is never changed afterwards.

    A plug-in's ``registration`` block is read before anything is written and
    applied once its version is offered.
    """
    if source not in LISTING_SOURCES:
        raise CatalogError(f"unknown listing source {source!r}")

    uid = _check_uid(str(manifest.get("uid", "")))
    public_id = _check_public_id(str(manifest.get("public_id", "")))
    reserved = reserved_prefix_problem(public_id, source=source)
    if reserved is not None:
        raise CatalogError(f"{public_id}: {reserved}")
    kind = str(manifest.get("kind", ""))
    if kind not in LISTING_KINDS:
        raise CatalogError(f"unknown listing kind {kind!r}")
    version_str = _check_version(str(manifest.get("version", "")))
    min_plugin_api = _min_plugin_api(manifest, public_id)

    try:
        definition = normalize_listing_definition(
            kind, manifest.get("definition"), public_id=public_id
        )
        example = normalize_listing_example(kind, manifest.get("example"), definition)

        # Required on every ingestion path: seeding, an operator upload, a
        # registry refresh. There is no path that publishes without one.
        publisher = normalize_publisher(manifest.get("publisher"))
    except ListingDefinitionError as exc:
        raise CatalogError(f"{public_id}: {exc}") from exc

    for required in ("name", "description"):
        if not manifest.get(required):
            raise CatalogError(f"{public_id}: {required} is required")

    registration: registrations_service.ListingRegistration | None = None
    if manifest.get("registration") is not None:
        if kind != "plugin":
            raise CatalogError(f"{public_id}: only a plug-in carries a registration")
        try:
            registration = await registrations_service.read_listing_registration(
                session,
                manifest["registration"],
                listing_uid=uid,
                listing_public_id=public_id,
                definition=definition,
                source=source,
            )
        except registrations_service.ListingRegistrationError as exc:
            error = CatalogSourceConflict if exc.conflict else CatalogError
            raise error(f"{public_id}: registration: {exc}") from exc

    # Artwork is optional: a listing without one gets the app's own mark rather
    # than being refused over a picture. A supplied one is still held to the
    # same-origin rule — the default is not a way in for a remote URL.
    avatar_url = str(manifest.get("avatar_url") or DEFAULT_AVATAR_URL)
    _check_artwork_path(avatar_url, field=f"{public_id}: avatar_url")

    images = manifest.get("images") or []
    if not isinstance(images, list) or any(not isinstance(i, str) for i in images):
        raise CatalogError(f"{public_id}: images must be a list of strings")
    for image in images:
        _check_artwork_path(image, field=f"{public_id}: images")

    existing = await get_listing_by_uid(session, uid)
    if existing is None:
        # A public_id that exists under a *different* uid is the same conflict
        # from the other side: both identities are unique, and neither may be
        # reassigned by a later publish.
        by_public_id = await get_listing(session, public_id)
        if by_public_id is not None:
            error = (
                CatalogSourceConflict
                if _crosses_sources(by_public_id, source)
                else CatalogError
            )
            raise error(
                f"{public_id} is already published under uid {by_public_id.uid}"
            )
    elif _crosses_sources(existing, source):
        raise CatalogSourceConflict(
            f"{public_id} is published by the {existing.source} catalog; "
            f"the {source} catalog does not replace it"
        )
    elif existing.public_id != public_id:
        raise CatalogError(
            f"uid {uid} is already held by {existing.public_id}; refusing to reassign"
        )
    elif existing.bundled_with_uid != bundled_with:
        # Both identities matching is what an *update* looks like, so this is
        # the one path that reaches an existing row rather than being refused
        # above — and who owns a listing is not something a later publish may
        # change. A plug-in bundling a uid somebody else published would otherwise
        # rewrite that listing and attach its withdrawal to a different plug-in.
        held = (
            f"as part of {existing.bundled_with_uid}"
            if existing.bundled_with_uid
            else "on its own"
        )
        wants = f"as part of {bundled_with}" if bundled_with else "on its own"
        raise CatalogError(
            f"{public_id} is already published {held}; refusing to republish {wants}"
        )

    now = datetime.now(UTC)
    # Everything a publish sets, whether the row is new or being updated. Built
    # once so a new listing is constructed complete rather than assembled by
    # assignment after the fact.
    published = {
        "kind": kind,
        "source": source,
        "name": str(manifest["name"]),
        "publisher": publisher,
        "description": str(manifest["description"]),
        "long_description": manifest.get("long_description"),
        "avatar_url": avatar_url,
        "images": list(images),
        "bundled_with_uid": bundled_with,
        "available": True,
        "updated_at": now,
    }
    if existing is None:
        listing = MarketplaceListing(
            uid=uid,
            public_id=public_id,
            created_at=now,
            submitted_by=submitted_by,
            **{**published, "available": not hold_for_review},
        )
    elif hold_for_review:
        # What the shelf shows stays as it is until somebody approves a change.
        listing = existing
    else:
        listing = existing
        for field, value in published.items():
            setattr(listing, field, value)
    session.add(listing)
    await session.flush()

    version = (
        await session.exec(
            select(MarketplaceListingVersion).where(
                MarketplaceListingVersion.listing_id == listing.id,
                MarketplaceListingVersion.version == version_str,
            )
        )
    ).first()
    release_notes = manifest.get("release_notes")
    min_app_version = manifest.get("min_app_version")
    if version is None:
        version = MarketplaceListingVersion(
            listing_id=listing.id,
            version=version_str,
            published_at=now,
            definition=definition,
            example=example,
            release_notes=release_notes,
            min_app_version=min_app_version,
            min_plugin_api=min_plugin_api,
            awaiting_review=hold_for_review,
        )
        session.add(version)
        await session.flush()
    elif _stored_body(kind, version, public_id=public_id) != (
        definition,
        example,
        release_notes,
        min_app_version,
        min_plugin_api,
    ):
        # A published version is immutable, for two reasons:
        #
        #   * instances *pin* a version, and the upgrade path has nothing to
        #     offer an instance already on this one — so a changed body under an
        #     unchanged version would never reach whoever installed it;
        #   * the catalog is shared, so `uid` + version has to name the same
        #     content on every deployment for a shared code to be meaningful.
        #
        # Correcting a listing means publishing a new version. Its name, blurb
        # and artwork are listing-level and stay editable without one.
        raise CatalogError(
            f"{public_id}: version {version_str} is already published with "
            "different content; publish a new version instead"
        )

    if not version.awaiting_review:
        listing.latest_version_id = version.id
    session.add(listing)
    await session.flush()
    if not version.awaiting_review and kind == "plugin":
        # What the latest version requires of the operator is part of whether
        # a registration speaking for this listing is live.
        await vendor_values_service.sync_required_for_listing(
            session, listing.uid, version.definition
        )
        if registration is not None:
            await registrations_service.apply_listing_registration(
                session, registration
            )

    if kind == "plugin":
        await _publish_bundled_dashboards(
            session,
            plugin=listing,
            definition=definition,
            version=version_str,
            source=source,
        )

    return listing


def _stored_body(
    kind: str, version: MarketplaceListingVersion, *, public_id: str
) -> tuple[Any, Any, Any, Any, Any] | None:
    """A published version's content as today's code would write it. A field
    the definition format gained since then takes its default on both sides,
    so it is the content that is compared, not the format it was saved in.

    Normalized under the same ``public_id`` as the incoming manifest: a
    declarative plug-in is named by its listing and does not normalize without
    it, which would make every republish of one read as changed."""
    try:
        definition = normalize_listing_definition(
            kind, version.definition, public_id=public_id
        )
        example = normalize_listing_example(kind, version.example, definition)
    except ListingDefinitionError:
        return None
    return (
        definition,
        example,
        version.release_notes,
        version.min_app_version,
        version.min_plugin_api,
    )


def _crosses_sources(existing: MarketplaceListing, source: str) -> bool:
    """Whether a registry publish would take over another source's listing.

    A registry adds listings beside this deployment's own and never replaces
    one: a built-in, the operator's catalog directory and a local upload each
    keep the rows they published. The other sources hold their own guards
    (the operator catalog and local uploads) or are this build (built-ins).
    """
    return source == REGISTRY_SOURCE and existing.source != REGISTRY_SOURCE


def published_uids(manifest: dict[str, Any]) -> set[str]:
    """Every uid publishing one manifest creates a listing for: its own, plus
    the dashboards it bundles.

    A bundled dashboard's uid is written only inside its plug-in's manifest, so the
    manifest is the only place a caller can learn it. Both catalog sources —
    the shipped build and the operator's directory — sweep what they no longer
    publish by comparing the rows against the uids their files name, and a
    sweep that names fewer uids than the publish created retires a row the same
    pass just wrote.

    Read off the raw manifest, before validation: a file that is present claims
    what it names whether or not it published, so a manifest with a mistake in
    it leaves the listings it names exactly as they were. A ``dashboards`` block
    that is not shaped like one contributes nothing here and is reported by the
    validator on the publish attempt.
    """
    uids = {str(manifest.get("uid", ""))}

    definition = manifest.get("definition")
    if not isinstance(definition, dict):
        return uids
    entries = definition.get("dashboards")
    if not isinstance(entries, list):
        return uids
    for entry in entries:
        if isinstance(entry, dict) and "uid" in entry:
            uids.add(str(entry["uid"]))
    return uids


async def _publish_bundled_dashboards(
    session: AsyncSession,
    *,
    plugin: MarketplaceListing,
    definition: dict[str, Any],
    version: str,
    source: str,
) -> None:
    """Publish one dashboard listing per entry in a plug-in's ``dashboards`` block.

    This is the whole reason a publisher declares these inside the manifest
    rather than beside it: the operator adds one file, and the dashboards that
    ship with the plug-in are published, versioned and withdrawn with it.

    Each one is an ordinary listing. It carries the publisher's own uid — which
    is what makes it a real catalog identity rather than something invented here
    — and inherits the plug-in's publisher, source and version, because it *is* the
    plug-in's publish. ``bundled_with_uid`` is what marks it, and is how the browse
    path knows to offer it only where the plug-in is installed.

    Widget types are resolved to their namespaced form here. A manifest carries
    no uid inside it, so a publisher writes the bare widget id and this stamps
    the plug-in's own uid on — the same value :func:`plugin_widget_type` puts on the
    palette. What gets stored is therefore the shape the dashboard tool already
    renders, and nothing downstream needs to know the row was derived.
    """
    published: set[str] = set()

    for entry in definition.get("dashboards") or []:
        widgets = [
            {
                "id": widget["id"],
                "type": plugin_widget_type(plugin.uid, widget["type"]),
                **({"title": widget["title"]} if "title" in widget else {}),
                **({"grid": widget["grid"]} if "grid" in widget else {}),
                "binding": {
                    "source": "plugin",
                    "plugin_uid": plugin.uid,
                    **widget["binding"],
                },
            }
            for widget in entry["widgets"]
        ]
        manifest: dict[str, Any] = {
            "uid": entry["uid"],
            "public_id": entry["public_id"],
            "kind": "dashboard",
            "name": entry["name"],
            "publisher": plugin.publisher,
            "description": entry.get("description") or plugin.description,
            "version": version,
            # No artwork of its own, deliberately: a dashboard previews by
            # rendering its actual widgets against the sample data those widgets
            # declare, which cannot go stale against the plug-in the way a picture
            # would.
            "avatar_url": DEFAULT_AVATAR_URL,
            "images": [],
            "definition": {
                "schema_version": 1,
                "kind": "dashboard",
                **({"layout": entry["layout"]} if "layout" in entry else {}),
                "widgets": widgets,
            },
        }
        # Ownership goes in as part of the publish rather than being stamped on
        # afterwards, so the same call that refuses to reassign a uid refuses to
        # take a listing away from whoever already published it.
        await upsert_listing(session, manifest, source=source, bundled_with=plugin.uid)
        published.add(entry["uid"])

    # A dashboard dropped from the manifest is withdrawn rather than left
    # offered: the plug-in that supplied its widgets no longer ships it. Withdrawn,
    # not deleted — a guild that already installed it keeps what it has.
    for stale in await _bundled_dashboards_of(session, plugin.uid):
        if stale.uid not in published and stale.available:
            stale.available = False
            stale.updated_at = datetime.now(UTC)
            session.add(stale)

    await session.flush()


async def _bundled_dashboards_of(
    session: AsyncSession, plugin_uid: str
) -> Sequence[MarketplaceListing]:
    """Every dashboard listing published as part of one plug-in."""
    return (
        await session.exec(
            select(MarketplaceListing).where(
                MarketplaceListing.bundled_with_uid == plugin_uid
            )
        )
    ).all()


async def withdraw_listing(session: AsyncSession, uid: str) -> bool:
    """Take a listing out of the catalog, keeping the row. Returns whether one
    was there to withdraw.

    Withdrawn is not deleted: a guild that already installed it keeps its plug-in,
    its pinned definition and its provenance. It simply stops being offered and
    cannot be installed again. Used when a deployment stops being able to serve
    something it previously seeded — an operator removing the configuration a
    plug-in depends on — and later by the registry for a listing its publisher pulls.

    Withdrawing a plug-in withdraws the dashboards it bundles. They were published
    by its manifest and have no existence apart from it, so leaving them offered
    would mean offering an arrangement of widgets a guild can no longer install
    the plug-in for.
    """
    listing = await get_listing_by_uid(session, uid)
    if listing is None or not listing.available:
        return False
    now = datetime.now(UTC)
    listing.available = False
    listing.updated_at = now
    session.add(listing)

    if listing.kind == "plugin":
        for bundled in await _bundled_dashboards_of(session, listing.uid):
            if bundled.available:
                bundled.available = False
                bundled.updated_at = now
                session.add(bundled)

    await session.flush()
    return True


async def listing_versions(
    session: AsyncSession, listing_id: int
) -> Sequence[MarketplaceListingVersion]:
    """Every published version of a listing, newest first. A version still
    waiting for review is not published yet, and is not among them."""
    return (
        await session.exec(
            select(MarketplaceListingVersion)
            .where(
                MarketplaceListingVersion.listing_id == listing_id,
                MarketplaceListingVersion.awaiting_review.is_(False),
            )
            .order_by(MarketplaceListingVersion.published_at.desc())
        )
    ).all()


async def withdraw_builtins_except(
    session: AsyncSession, keep_uids: Sequence[str]
) -> int:
    """Withdraw every shipped listing this build no longer carries.

    Seeding upserts what it finds; without this, a listing whose file was
    removed from the build stays in the catalog of every database that ever saw
    it, still offered and still installable. The row is kept, so a guild that
    already installed it is untouched — it simply stops being on the shelf.

    Scoped to ``builtin``: an operator's own listings and anything from a
    registry are not this build's to withdraw.
    """
    keep = {uid for uid in keep_uids if uid}
    statement = select(MarketplaceListing).where(
        MarketplaceListing.source == "builtin",
        MarketplaceListing.available.is_(True),
    )
    withdrawn = 0
    for listing in (await session.exec(statement)).all():
        if listing.uid in keep:
            continue
        listing.available = False
        listing.updated_at = datetime.now(UTC)
        session.add(listing)
        withdrawn += 1
    if withdrawn:
        await session.flush()
    return withdrawn


async def bump_installs_count(session: AsyncSession, listing_id: int) -> None:
    """Add one to a listing's cumulative install count.

    A number and nothing else: no guild is recorded, so this stays catalog
    telemetry rather than tenant data. Called post-commit and best-effort by the
    install path — a failed bump must never fail an install.
    """
    # One statement, incremented in the database: two installs landing together
    # would otherwise both read the same number and both write it back plus one,
    # quietly losing an install.
    await session.exec(
        sa_update(MarketplaceListing)
        .where(MarketplaceListing.id == listing_id)
        .values(installs_count=MarketplaceListing.installs_count + 1)
    )
