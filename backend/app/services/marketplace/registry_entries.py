"""Applying one verified registry listing to this deployment.

A registry listing is the signed target ``publishers/<prefix>/<uid>/listing.json``
(the entry), beside the files it names: each version's manifest and the
listing's pictures. The TUF client has already verified the entry and checks
every file it fetches here against its own target metadata; this module checks
that the files are the ones the entry names, and turns the entry into rows:

* **a publisher** (``publishers``), matched by prefix, with the display name
  and verified flag from the publisher's record — the target
  ``publishers/<prefix>.json`` the top-level ``targets`` role signs. An
  operator's row for the same prefix wins: the entry is refused and logged.
* **a listing and its versions** (``marketplace_listings``,
  ``marketplace_listing_versions``), ``source='registry'``, through the same
  ``upsert_listing`` and validator every other source uses. A uid or name
  another source already published is refused, never taken over. Pictures are
  kept in ``marketplace_media`` by digest.
* **for a plug-in, its registration's plug-in facts** (``plugin_service_registrations``,
  ``source='registry'``), from the entry's ``registration`` block, through the
  same ``upsert_listing`` as every other source's listing. The block is the
  container image and the scope ceiling; where the container runs and its keys
  are the deployment's.

The caller runs each entry in its own savepoint, so a refusal part-way leaves
nothing of that entry behind.

**Withdrawal** (:func:`withdraw_missing`): a listing the repository no longer
carries is marked unavailable and its registration switched off. Nothing is
deleted, so installs keep their data.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, NamedTuple

from fastapi import HTTPException
from sqlalchemy import update as sa_update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.messages import MarketplaceRegistryMessages as Codes
from app.models.platform.marketplace import (
    UID_ALPHABET,
    UID_LENGTH,
    MarketplaceListing,
    MarketplaceListingVersion,
)
from app.models.platform.marketplace_registry import MarketplaceMedia
from app.models.platform.plugin_service_registration import (
    PluginServiceRegistration,
    RegistrationSource,
)
from app.models.platform.publisher import (
    Publisher,
    PublisherSource,
    publisher_prefix,
)
from app.services import audit as audit_service
from app.services.marketplace import media
from app.services.marketplace import publishers as publishers_service
from app.services.marketplace import registrations as registrations_service
from app.services.marketplace.catalog import (
    DEFAULT_AVATAR_URL,
    REGISTRY_SOURCE,
    CatalogError,
    CatalogSourceConflict,
    upsert_listing,
    withdraw_listing,
)
from app.services.marketplace.definitions import LISTING_KINDS

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_PUBLISHER_RECORD_BYTES",
    "EntryContext",
    "ListingPath",
    "RegistryError",
    "UnsupportedEntry",
    "apply_entry",
    "listing_path",
    "parse_listing_path",
    "parse_prefix",
    "publisher_record_path",
    "withdraw_missing",
]

#: The entry format this client reads.
ENTRY_SCHEMA = 1

#: Ceilings on what one entry may name, and on each file.
MAX_ENTRY_BYTES = 256 * 1024
MAX_MANIFEST_BYTES = 512 * 1024
MAX_IMAGE_BYTES = 1024 * 1024
MAX_PUBLISHER_RECORD_BYTES = 16 * 1024
MAX_IMAGES = 12
MAX_VERSIONS = 50

#: ``core`` names listings shipped in this repository and is never a
#: registry publisher.
RESERVED_PREFIX = "core"

_HEX_DIGITS = frozenset("0123456789abcdef")
_DIGEST_LENGTH = 64

#: Characters a path inside a listing's directory may use.
_PATH_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)


class RegistryError(Exception):
    """A refusal, carrying the message code that names it."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


class UnsupportedEntry(Exception):
    """An entry of a kind this build does not carry. Skipped and logged, and
    not a failure of the refresh: a newer build may carry it."""


class ListingPath(NamedTuple):
    prefix: str
    uid: str


def parse_prefix(value: str) -> str | None:
    """``value`` when it can be a registry publisher's prefix, else ``None``."""
    if value == RESERVED_PREFIX or not publishers_service.valid_prefix(value):
        return None
    return value


def _valid_uid(value: str) -> bool:
    return len(value) == UID_LENGTH and all(char in UID_ALPHABET for char in value)


def listing_path(prefix: str, uid: str) -> str:
    return f"publishers/{prefix}/{uid}/listing.json"


def publisher_record_path(prefix: str) -> str:
    """The publisher's record, signed by the top-level ``targets`` role."""
    return f"publishers/{prefix}.json"


def parse_listing_path(path: str) -> ListingPath | None:
    """The publisher and uid a listing target names, or ``None`` when ``path``
    is not ``publishers/<prefix>/<uid>/listing.json``."""
    parts = path.split("/")
    if len(parts) != 4 or parts[0] != "publishers" or parts[3] != "listing.json":
        return None
    prefix = parse_prefix(parts[1])
    if prefix is None or not _valid_uid(parts[2]):
        return None
    return ListingPath(prefix=prefix, uid=parts[2])


@dataclass(frozen=True)
class EntryContext:
    """What applying an entry needs from the verified repository."""

    #: A target's bytes, checked against its metadata, capped at the size.
    fetch: Callable[[str, int], Awaitable[bytes]]
    #: The bytes of ``publishers/<prefix>.json`` as the top-level role signs
    #: it, or ``None`` when there is no record.
    publisher_record: Callable[[str], Awaitable[bytes | None]]
    now: datetime


# --- reading the entry ---------------------------------------------------------


def _invalid(detail: str) -> RegistryError:
    return RegistryError(Codes.ENTRY_INVALID, detail)


def _json_object(raw: bytes, *, what: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise _invalid(f"{what} is not JSON") from exc
    if not isinstance(parsed, dict):
        raise _invalid(f"{what} is not a JSON object")
    return parsed


def _digest(value: Any, *, what: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _DIGEST_LENGTH
        or any(char not in _HEX_DIGITS for char in value)
    ):
        raise _invalid(f"{what} has no usable sha256")
    return value


def _matches(data: bytes, expected: str) -> bool:
    return hmac.compare_digest(hashlib.sha256(data).hexdigest(), expected)


def _relative(directory: str, value: Any, *, what: str) -> str:
    """A path inside the listing's directory, as a target path."""
    if not isinstance(value, str) or not value or len(value) > 200:
        raise _invalid(f"{what} has no usable path")
    parts = value.split("/")
    for part in parts:
        if part in ("", ".", "..") or any(char not in _PATH_CHARS for char in part):
            raise _invalid(f"{what} path {value!r} is not a plain relative path")
    return directory + value


def _optional_text(entry: Mapping[str, Any], key: str) -> str | None:
    value = entry.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid(f"{key} must be a string")
    return value


@dataclass(frozen=True)
class _Version:
    version: str
    manifest: str
    sha256: str
    min_app_version: str | None
    min_plugin_api: str | None
    release_notes: str | None


def _versions(entry: Mapping[str, Any], directory: str) -> list[_Version]:
    """The entry's versions, oldest first: the last one is the latest."""
    raw = entry.get("versions")
    if not isinstance(raw, list) or not raw:
        raise _invalid("versions must be a non-empty list")
    if len(raw) > MAX_VERSIONS:
        raise _invalid(f"more than {MAX_VERSIONS} versions")
    versions: list[_Version] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            raise _invalid("a version is not an object")
        version = item.get("version")
        if not isinstance(version, str) or not version or version in seen:
            raise _invalid("a version has no usable version string")
        seen.add(version)
        versions.append(
            _Version(
                version=version,
                manifest=_relative(
                    directory, item.get("manifest"), what=f"version {version}"
                ),
                sha256=_digest(item.get("sha256"), what=f"version {version}"),
                min_app_version=_optional_text(item, "min_app_version"),
                min_plugin_api=_optional_text(item, "min_plugin_api"),
                release_notes=_optional_text(item, "release_notes"),
            )
        )
    return versions


# --- the publisher ---------------------------------------------------------------


async def _publisher_fields(context: EntryContext, prefix: str) -> tuple[str, bool]:
    """The display name and verified flag the publisher's record gives, or
    the prefix itself, unverified, when the repository carries no record."""
    raw = await context.publisher_record(prefix)
    if raw is None:
        return prefix, False
    record = _json_object(raw, what=f"publisher record {prefix}")
    if record.get("prefix") != prefix:
        raise _invalid(f"publisher record {prefix} names another prefix")
    name = record.get("name")
    try:
        display_name = publishers_service.normalize_display_name(
            name if isinstance(name, str) else ""
        )
    except HTTPException as exc:
        raise _invalid(f"publisher record {prefix} has no usable name") from exc
    return display_name, record.get("verified") is True


async def _apply_publisher(
    session: AsyncSession, context: EntryContext, prefix: str
) -> Publisher:
    display_name, verified = await _publisher_fields(context, prefix)
    row = await publishers_service.publisher_by_prefix(session, prefix)
    if row is not None and row.source == PublisherSource.OPERATOR:
        raise RegistryError(
            Codes.PUBLISHER_CONFLICT,
            f"this deployment's operator added the publisher {prefix!r}",
        )
    if row is None:
        row = Publisher(
            prefix=prefix,
            display_name=display_name,
            verified=verified,
            enabled=True,
            source=PublisherSource.REGISTRY,
        )
        session.add(row)
        await session.flush()
        await audit_service.record(
            session,
            event_type=AuditEventType.PLUGIN_PUBLISHER_CREATED,
            actor_user_id=None,
            target_type="plugin_publisher",
            target_id=row.id,
            detail={
                "via": "registry",
                **audit_service.changed_fields(
                    {},
                    audit_service.snapshot(row, publishers_service.AUDITED_FIELDS),
                ),
            },
        )
        return row

    # The seeded row, or one an earlier refresh added: the registry keeps it
    # up to date. Its switch is the operator's and is left alone.
    before = audit_service.snapshot(row, publishers_service.AUDITED_FIELDS)
    row.display_name = display_name
    row.verified = verified
    row.source = PublisherSource.REGISTRY
    session.add(row)
    changed = audit_service.changed_fields(
        before, audit_service.snapshot(row, publishers_service.AUDITED_FIELDS)
    )
    if changed["changed"]:
        await audit_service.record(
            session,
            event_type=AuditEventType.PLUGIN_PUBLISHER_UPDATED,
            actor_user_id=None,
            target_type="plugin_publisher",
            target_id=row.id,
            detail={"via": "registry", **changed},
        )
    return row


# --- pictures ----------------------------------------------------------------------


async def _keep_picture(
    session: AsyncSession,
    context: EntryContext,
    directory: str,
    spec: Any,
    *,
    what: str,
) -> str | None:
    """Keep one picture the entry names, and return the path it is served
    from; ``None`` for a picture of a type the catalogue does not keep.

    Keyed on the digest the entry gives, so a picture already kept is not
    fetched again.
    """
    if not isinstance(spec, Mapping):
        raise _invalid(f"{what} is not an object")
    target = _relative(directory, spec.get("path"), what=what)
    digest = _digest(spec.get("sha256"), what=what)
    kept = (
        await session.exec(
            select(MarketplaceMedia.id).where(MarketplaceMedia.sha256 == digest)
        )
    ).first()
    if kept is not None:
        return media.media_path(digest)
    data = await context.fetch(target, MAX_IMAGE_BYTES)
    if not _matches(data, digest):
        raise RegistryError(
            Codes.TARGET_REJECTED, f"{target} does not match the sha256 the entry gives"
        )
    content_type = media.image_type_of(data)
    if content_type is None:
        logger.info(
            "marketplace registry: %s is not a picture type the catalogue keeps",
            target,
        )
        return None
    return await media.store_media(
        session, data, content_type=content_type, source_url=target, now=context.now
    )


# --- versions -------------------------------------------------------------------------


def _pack_decorations(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    definition = manifest.get("definition")
    if not isinstance(definition, dict):
        return []
    entries = definition.get("decorations")
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


async def _manifest(
    context: EntryContext,
    version: _Version,
    *,
    uid: str,
    public_id: str,
    kind: str,
) -> dict[str, Any]:
    """One version's manifest, checked against the digest the entry gives
    and against the entry's identity."""
    raw = await context.fetch(version.manifest, MAX_MANIFEST_BYTES)
    if not _matches(raw, version.sha256):
        raise RegistryError(
            Codes.TARGET_REJECTED,
            f"{version.manifest} does not match the sha256 the entry gives",
        )
    manifest = _json_object(raw, what=version.manifest)
    # The entry names the listing; a manifest that says otherwise is not its.
    for key, expected in (("uid", uid), ("public_id", public_id), ("kind", kind)):
        if key in manifest and manifest[key] != expected:
            raise _invalid(f"{version.manifest} names a different {key}")
    if "definition" not in manifest:
        raise _invalid(f"{version.manifest} has no definition")
    return manifest


# --- one entry ------------------------------------------------------------------------


async def apply_entry(session: AsyncSession, path: str, context: EntryContext) -> None:
    """Apply the entry at ``path``. Raises ``RegistryError`` to refuse it and
    ``UnsupportedEntry`` for a kind this build does not carry."""
    parsed = parse_listing_path(path)
    if parsed is None:
        raise _invalid(f"{path} is not a listing path")
    prefix, uid = parsed
    directory = f"publishers/{prefix}/{uid}/"

    entry = _json_object(await context.fetch(path, MAX_ENTRY_BYTES), what=path)
    if entry.get("schema") != ENTRY_SCHEMA:
        raise _invalid(f"{path} is not entry schema {ENTRY_SCHEMA}")
    if entry.get("uid") != uid:
        raise _invalid(f"{path} names another uid")
    if entry.get("publisher") != prefix:
        raise _invalid(f"{path} names another publisher")
    public_id = entry.get("public_id")
    if not isinstance(public_id, str) or publisher_prefix(public_id) != prefix:
        raise _invalid(f"{path} has a public_id outside its publisher")
    if prefix == RESERVED_PREFIX:  # pragma: no cover - refused by the path
        raise RegistryError(Codes.RESERVED_NAMESPACE, public_id)
    kind = entry.get("kind")
    if not isinstance(kind, str) or kind not in LISTING_KINDS:
        raise UnsupportedEntry(f"{path} is a {kind!r} listing")
    registration = entry.get("registration")
    if (registration is not None) != (kind == "plugin"):
        raise _invalid("a plug-in carries a registration, and nothing else does")

    versions = _versions(entry, directory)
    publisher = await _apply_publisher(session, context, prefix)

    avatar_url = DEFAULT_AVATAR_URL
    if entry.get("avatar") is not None:
        avatar_url = (
            await _keep_picture(
                session, context, directory, entry["avatar"], what="avatar"
            )
            or DEFAULT_AVATAR_URL
        )
    image_specs = entry.get("images") or []
    if not isinstance(image_specs, list) or len(image_specs) > MAX_IMAGES:
        raise _invalid(f"images must be a list of at most {MAX_IMAGES}")
    images: list[str] = []
    for index, spec in enumerate(image_specs):
        kept = await _keep_picture(
            session, context, directory, spec, what=f"image {index}"
        )
        if kept is not None:
            images.append(kept)

    held = {
        row
        for row in (
            await session.exec(
                select(MarketplaceListingVersion.version)
                .join(
                    MarketplaceListing,
                    MarketplaceListing.id == MarketplaceListingVersion.listing_id,
                )
                .where(MarketplaceListing.uid == uid)
            )
        ).all()
    }
    listing: MarketplaceListing | None = None
    for index, version in enumerate(versions):
        latest = index == len(versions) - 1
        if version.version in held and not latest:
            # A published version is immutable; there is nothing to read again.
            continue
        manifest = await _manifest(
            context, version, uid=uid, public_id=public_id, kind=kind
        )
        if kind == "profile_pack":
            # A pack's pictures come from its own assets, not from inside the
            # manifest.
            for decoration in _pack_decorations(manifest):
                decoration.pop("image", None)
        published = {
            **manifest,
            "uid": uid,
            "public_id": public_id,
            "kind": kind,
            "name": entry.get("name") or manifest.get("name"),
            "publisher": publisher.display_name,
            "description": entry.get("summary") or manifest.get("description"),
            "long_description": entry.get("description")
            or manifest.get("long_description"),
            "avatar_url": avatar_url,
            "images": images,
            "version": version.version,
            "min_app_version": version.min_app_version,
            "min_plugin_api": version.min_plugin_api,
            "release_notes": version.release_notes,
            "registration": registration if latest else None,
        }
        try:
            listing = await upsert_listing(
                session,
                published,
                source=REGISTRY_SOURCE,
            )
        except CatalogSourceConflict as exc:
            raise RegistryError(Codes.SOURCE_CONFLICT, str(exc)) from exc
        except CatalogError as exc:
            raise RegistryError(Codes.LISTING_REJECTED, str(exc)) from exc

    assert listing is not None  # the latest version is always published
    listing.publisher_id = publisher.id
    listing.publisher_verified = publisher.verified
    session.add(listing)
    # The dashboards a plug-in bundles are its publish, and share its provenance.
    await session.exec(
        sa_update(MarketplaceListing)
        .where(MarketplaceListing.bundled_with_uid == uid)
        .values(publisher_id=publisher.id, publisher_verified=publisher.verified)
    )
    await session.flush()


# --- withdrawal -------------------------------------------------------------------------


async def withdraw_missing(
    session: AsyncSession,
    *,
    present: set[str],
    uncertain: Callable[[str], bool],
    now: datetime,
) -> int:
    """Withdraw what the repository no longer carries. Returns how many
    listings were withdrawn.

    ``present`` is every uid the repository lists; ``uncertain`` says whether a
    listing path falls under a publisher whose role did not load this time, and
    so is unknown rather than gone. Bundled dashboards go with their plug-in.
    """
    withdrawn = 0
    listings = (
        await session.exec(
            select(MarketplaceListing).where(
                MarketplaceListing.source == REGISTRY_SOURCE,
                MarketplaceListing.available.is_(True),
                MarketplaceListing.bundled_with_uid.is_(None),
            )
        )
    ).all()
    for listing in listings:
        if listing.uid in present:
            continue
        if uncertain(listing_path(publisher_prefix(listing.public_id), listing.uid)):
            continue
        if await withdraw_listing(session, listing.uid):
            withdrawn += 1
            logger.info(
                "marketplace registry: withdrew %s — no longer in the repository",
                listing.public_id,
            )

    registrations = (
        await session.exec(
            select(PluginServiceRegistration).where(
                PluginServiceRegistration.source == RegistrationSource.REGISTRY,
                PluginServiceRegistration.enabled.is_(True),
            )
        )
    ).all()
    for row in registrations:
        if row.listing_uid in present:
            continue
        if row.listing_uid is not None and uncertain(
            listing_path(publisher_prefix(row.public_id), row.listing_uid)
        ):
            continue
        before = audit_service.snapshot(row, registrations_service.AUDITED_FIELDS)
        row.enabled = False
        row.updated_at = now
        session.add(row)
        await audit_service.record(
            session,
            event_type=AuditEventType.PLUGIN_SERVICE_UPDATED,
            actor_user_id=None,
            target_type="plugin_service_registration",
            target_id=row.id,
            detail={
                "via": "registry",
                **audit_service.changed_fields(
                    before,
                    audit_service.snapshot(row, registrations_service.AUDITED_FIELDS),
                ),
            },
        )
    await session.flush()
    return withdrawn
