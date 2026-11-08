"""Managing the deployment's plug-in service registrations.

Every plug-in splits the same way, whatever published its listing
(:mod:`app.models.platform.plugin_service_registration`):

* **Its listing gives the plug-in facts.** A listing from any source (the
  registry, a local upload, the operator's catalog directory, the build) may
  carry a ``registration`` block, and ``upsert_listing`` hands it to
  :func:`read_listing_registration` and :func:`apply_listing_registration`,
  which write the listing, scope ceiling, image and Compose service onto the
  registration for the service it names, creating the row when there is none.
* **The operator gives the deployment facts**: where the plug-in runs, the keys
  its container signs with, its vendor values, the switch, the mandatory and
  operations-only flags and the origins. Through the ``plugins.manage`` endpoints, or in
  ``PLUGIN_SERVICES_CONFIG``, a file a chart mounts, reconciled at boot. An
  entry's ``vendor_env`` names the environment variables holding its vendor
  values, which are sealed into the registration on each boot. An entry for a
  plug-in whose listing has not arrived waits for it: the listing apply that
  creates the row applies the entry.

Nothing is fetched from the plug-in to fill any of it in, except its key set when
the operator asks: **Connect** (:func:`published_keys`, then
:func:`connect_registration`) reads the set the plug-in serves under its base URL,
shows each key's fingerprint, and pins the set the operator confirms in place
of any ``jwks_uri``. A changed set is picked up only by connecting again. Its publisher is the row
for its ``public_id`` prefix (:mod:`app.services.marketplace.publishers`). The
one secret it may hold is its vendor values
(:mod:`app.services.marketplace.vendor_values`).

One rule the reconciler keeps, about not undoing a person: it never re-enables
a registration an operator disabled — deactivating a plug-in is the
incident-response lever, so a restart must not quietly reverse it.

Everything here runs on the system engine: ``plugin_service_registrations`` has no
request-path write grant.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException
from fastapi import status as http_status
from jwt import PyJWK
from jwt.exceptions import InvalidKeyError, PyJWKError
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.clock import utcnow
from app.core.config import settings
from app.core.messages import PluginServiceMessages
from app.core.plugin_scopes import ALL_SCOPES, plugin_scope_target
from app.core.security import plugin_platform_signing_enabled
from app.db.errors import dbapi_constraint
from app.models.platform.plugin_install import EXCLUSIVE_ROUTE_INDEX, PluginInstall
from app.models.platform.plugin_service_registration import (
    IMAGE_REFERENCE_MAX_LENGTH,
    LISTING_STATED_FIELDS,
    MAX_PLUGIN_ID_LENGTH,
    PluginServiceRegistration,
    RegistrationKind,
    RegistrationSource,
)
from app.models.platform.publisher import (
    Publisher,
    publisher_prefix,
)
from app.services import audit as audit_service
from app.services.marketplace import vendor_values as vendor_values_service
from app.services.marketplace.plugin_keys import (
    PRIVATE_JWK_MEMBERS,
    KeySetUnreadableError,
    is_plugin_key,
    jwk_thumbprint,
    jwks_uri_allowed,
    key_set_url,
    read_key_set,
)
from app.services.marketplace.publishers import ensure_publisher
from app.services.marketplace.registration_lookup import (
    invalidate_registrations,
    is_declarative,
    live_registration_clause,
    service_public_id,
)

logger = logging.getLogger(__name__)

#: What a registration confers and where it points, for the record.
AUDITED_FIELDS: tuple[str, ...] = (
    "public_id",
    "listing_uid",
    "kind",
    "publisher_id",
    "base_url",
    "page_origin",
    "allowed_origins",
    "jwks",
    "jwks_uri",
    "scope_ceiling",
    "mandatory",
    "operations_only",
    "shared_routes",
    "enabled",
    "source",
    "image_digest",
    "compose",
)


__all__ = [
    "DeploymentFacts",
    "ListingRegistration",
    "ListingRegistrationError",
    "PublishedKey",
    "ReconcileResult",
    "RegistrationView",
    "apply_deployment_facts",
    "apply_listing_registration",
    "check_signing_configured",
    "configured_facts",
    "connect_registration",
    "create_registration",
    "delete_registration",
    "filled_compose",
    "get_registration",
    "list_registrations",
    "normalize_base_url",
    "normalize_jwks",
    "normalize_jwks_uri",
    "normalize_origin",
    "normalize_origins",
    "normalize_page_origin",
    "normalize_public_id",
    "origin_of",
    "published_keys",
    "read_listing_registration",
    "reconcile_from_config",
    "registration_views",
    "row_browser_base",
    "update_registration",
]

#: Characters a ``public_id`` may use: ``<publisher>.<slug>``, lowercase — the
#: same shape the catalog requires, checked as an explicit set so a stored id is
#: exactly what a URL and a JWT audience will carry.
_PUBLIC_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789.-_")
_MAX_PUBLIC_ID = MAX_PLUGIN_ID_LENGTH
_MAX_BASE_URL = 1000
_MAX_ORIGIN = 253 + 16
_MAX_ORIGINS = 20


def _bad_request(code: str, detail: str) -> HTTPException:
    logger.debug("plug-in service registration refused (%s): %s", code, detail)
    return HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=code)


def row_browser_base(row: PluginServiceRegistration) -> str | None:
    """Where a browser loads the plug-in's surfaces, or ``None`` for a plug-in that
    has no location yet."""
    return row.page_origin or row.base_url


def _registry_managed() -> HTTPException:
    return HTTPException(
        status_code=http_status.HTTP_409_CONFLICT,
        detail=PluginServiceMessages.REGISTRY_MANAGED,
    )


# --- validation --------------------------------------------------------------


def check_signing_configured() -> None:
    """Refuse to run the plug-in platform without its own signing key.

    The keypair is required and has no fallback to any other configured key, so
    an unset one is reported as configuration rather than silently substituted.
    """
    if not plugin_platform_signing_enabled():
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=PluginServiceMessages.SIGNING_NOT_CONFIGURED,
        )


def normalize_public_id(value: str) -> str:
    cleaned = (value or "").strip().lower()
    if not cleaned or len(cleaned) > _MAX_PUBLIC_ID:
        raise _bad_request(
            PluginServiceMessages.INVALID_PUBLIC_ID,
            f"public_id must be 1..{_MAX_PUBLIC_ID} characters",
        )
    for char in cleaned:
        if char not in _PUBLIC_ID_CHARS:
            raise _bad_request(
                PluginServiceMessages.INVALID_PUBLIC_ID,
                f"public_id contains {char!r}, which is not allowed",
            )
    if "." not in cleaned:
        raise _bad_request(
            PluginServiceMessages.INVALID_PUBLIC_ID,
            "public_id must be '<publisher>.<slug>'",
        )
    return cleaned


def _normalize_url_base(value: str, *, code: str, field: str) -> str:
    """A base URL is a scheme, a host, an optional port, and an optional path
    prefix — nothing else. The egress policy (scheme vs address class) is
    applied when the connection is actually made, by ``safe_http``.
    """
    cleaned = (value or "").strip().rstrip("/")
    if not cleaned or len(cleaned) > _MAX_BASE_URL:
        raise _bad_request(code, f"{field} must be 1..{_MAX_BASE_URL} characters")
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https"):
        raise _bad_request(code, f"{field} must be http or https")
    if not parsed.hostname:
        raise _bad_request(code, f"{field} needs a host")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise _bad_request(code, f"{field} carries no query, fragment, or credentials")
    return cleaned


def normalize_base_url(value: str) -> str:
    """Where Initiative's own server calls this plug-in."""
    return _normalize_url_base(
        value, code=PluginServiceMessages.INVALID_BASE_URL, field="base_url"
    )


def normalize_page_origin(value: str) -> str:
    """Where a person's browser loads this plug-in's surfaces.

    Held to the same shape as ``base_url`` because it stands in for it: the
    manifest declares one path per surface, and it is joined to whichever of the
    two addresses the reader is on. A deployment that publishes its plug-ins under a
    path prefix can therefore say so here as well.
    """
    return _normalize_url_base(
        value, code=PluginServiceMessages.INVALID_PAGE_ORIGIN, field="page_origin"
    )


def origin_of(base: str) -> str:
    """The origin half of an already-normalized base URL.

    A base may carry a path prefix and an origin never does, so the prefix is
    dropped here rather than refused — this reads a value the service itself
    validated, not something a person typed.
    """
    parsed = urlparse(base)
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}"


def normalize_origin(value: str) -> str:
    """An allowed origin is ``scheme://host[:port]`` and nothing more — a path
    or a wildcard would widen it beyond what an origin comparison can honor."""
    cleaned = (value or "").strip().rstrip("/")
    if not cleaned or len(cleaned) > _MAX_ORIGIN:
        raise _bad_request(
            PluginServiceMessages.INVALID_ORIGIN, "origin has an unusable length"
        )
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise _bad_request(
            PluginServiceMessages.INVALID_ORIGIN,
            "origin must be 'scheme://host[:port]'",
        )
    if parsed.path or parsed.query or parsed.fragment:
        raise _bad_request(
            PluginServiceMessages.INVALID_ORIGIN, "origin carries no path or query"
        )
    return origin_of(cleaned)


def normalize_origins(values: Iterable[str] | None, *, browser_base: str) -> list[str]:
    """Canonicalize the origin list, defaulting to the browser base's own origin.

    Derived from the browser base rather than the wire surface because these are
    browser origins: what a document may frame, and what the SPA posts to.
    """
    items = [v for v in (values or []) if isinstance(v, str) and v.strip()]
    if not items:
        return [origin_of(browser_base)]
    if len(items) > _MAX_ORIGINS:
        raise _bad_request(
            PluginServiceMessages.INVALID_ORIGIN,
            f"at most {_MAX_ORIGINS} origins per registration",
        )
    normalized: list[str] = []
    for item in items:
        origin = normalize_origin(item)
        if origin not in normalized:
            normalized.append(origin)
    return normalized


def normalize_jwks(value: dict | None) -> dict | None:
    """Check a plug-in's key set holds public verification keys, each carrying
    the ``kid`` a JWT names.

    The set is the plug-in's client credential: the token endpoint verifies the
    assertions it signs against it. A registration with neither this set nor
    a ``jwks_uri`` is not live.

    Parsed on the way in rather than at first use, so an operator provisioning
    a key learns here whether it landed instead of at the first call that
    needs it. An empty object clears the set.

    Held to public asymmetric keys only. This column is served in full to the
    owner's settings, which is right for a public half and wrong for anything
    else, so a key carrying private members or a shared symmetric value is
    refused rather than stored — the paste is a mistake worth naming at the
    moment it happens.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise _bad_request(
            PluginServiceMessages.INVALID_JWKS,
            "expected a JWKS object",
        )
    if not value:
        return None

    keys = value.get("keys")
    if not isinstance(keys, list) or not keys:
        raise _bad_request(
            PluginServiceMessages.INVALID_JWKS,
            "expected {'keys': [...]} holding at least one key",
        )

    seen: set[str] = set()
    for entry in keys:
        if not isinstance(entry, dict):
            raise _bad_request(
                PluginServiceMessages.INVALID_JWKS,
                "every entry in 'keys' must be an object",
            )
        kid = entry.get("kid")
        if not isinstance(kid, str) or not kid.strip():
            raise _bad_request(
                PluginServiceMessages.INVALID_JWKS,
                "every key needs a 'kid' — a token names one to select it",
            )
        if kid in seen:
            raise _bad_request(
                PluginServiceMessages.INVALID_JWKS,
                f"two keys share the kid {kid!r}",
            )
        seen.add(kid)
        if not is_plugin_key(entry):
            raise _bad_request(
                PluginServiceMessages.INVALID_JWKS,
                f"key {kid!r} is not an Ed25519 key (kty OKP, crv Ed25519): "
                "a plug-in signs with Ed25519",
            )
        private = sorted(PRIVATE_JWK_MEMBERS.intersection(entry))
        if private:
            raise _bad_request(
                PluginServiceMessages.INVALID_JWKS,
                f"key {kid!r} carries private material ({', '.join(private)}) — "
                "provision the public half",
            )
        try:
            PyJWK.from_dict(entry)
        except (PyJWKError, InvalidKeyError, KeyError, TypeError, ValueError) as exc:
            raise _bad_request(
                PluginServiceMessages.INVALID_JWKS,
                f"key {kid!r} is unusable: {exc}",
            ) from exc

    return value


def normalize_jwks_uri(value: str | None, *, base_url: str) -> str | None:
    """Where the plug-in publishes its key set: https, on ``base_url``'s own
    origin, with no query, fragment or credentials. Empty clears it."""
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    if len(cleaned) > _MAX_BASE_URL:
        raise _bad_request(
            PluginServiceMessages.INVALID_JWKS_URI, "jwks_uri has an unusable length"
        )
    parsed = urlparse(cleaned)
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise _bad_request(
            PluginServiceMessages.INVALID_JWKS_URI,
            "jwks_uri carries no query, fragment, or credentials",
        )
    if not jwks_uri_allowed(cleaned, base_url):
        raise _bad_request(
            PluginServiceMessages.INVALID_JWKS_URI,
            "jwks_uri must be https on base_url's own origin",
        )
    return cleaned


# --- reads -------------------------------------------------------------------


async def list_registrations(
    session: AsyncSession,
) -> Sequence[PluginServiceRegistration]:
    result = await session.exec(
        select(PluginServiceRegistration).order_by(
            PluginServiceRegistration.public_id.asc()
        )
    )
    return result.all()


@dataclass(frozen=True)
class RegistrationView:
    """A registration with its publisher, and whether it is live."""

    row: PluginServiceRegistration
    publisher: Publisher
    live: bool


async def registration_views(
    session: AsyncSession, registration_id: int | None = None
) -> list[RegistrationView]:
    """Every registration, or the one ``registration_id`` names, each with its
    publisher and whether it is live, in one statement."""
    query = (
        select(PluginServiceRegistration, Publisher, live_registration_clause())
        .join(Publisher, Publisher.id == PluginServiceRegistration.publisher_id)
        .order_by(PluginServiceRegistration.public_id.asc())
    )
    if registration_id is not None:
        query = query.where(PluginServiceRegistration.id == registration_id)
    rows = (await session.exec(query)).all()
    return [
        RegistrationView(row=row, publisher=publisher, live=bool(live))
        for row, publisher, live in rows
    ]


async def get_registration(
    session: AsyncSession, registration_id: int
) -> PluginServiceRegistration:
    row = await session.get(PluginServiceRegistration, registration_id)
    if row is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=PluginServiceMessages.NOT_FOUND,
        )
    return row


async def _by_public_id(
    session: AsyncSession, public_id: str
) -> PluginServiceRegistration | None:
    result = await session.exec(
        select(PluginServiceRegistration).where(
            PluginServiceRegistration.public_id == public_id
        )
    )
    return result.first()


# --- writes ------------------------------------------------------------------


async def create_registration(
    session: AsyncSession,
    *,
    public_id: str,
    base_url: str,
    page_origin: str | None = None,
    allowed_origins: Iterable[str] | None = None,
    jwks: dict | None = None,
    jwks_uri: str | None = None,
    mandatory: bool = False,
    operations_only: bool = False,
    enabled: bool = True,
    vendor_values: dict[str, str | None] | None = None,
    actor_user_id: int | None = None,
) -> PluginServiceRegistration:
    """Set up a plug-in service's deployment facts before its listing arrives.

    Nothing is fetched from the plug-in: the operator names it, its addresses and
    its keys. Its plug-in facts wait for the listing that names it. Its publisher
    is the row for its prefix, added unverified when there is none.
    """
    check_signing_configured()
    resolved_id = normalize_public_id(public_id)
    base_url = normalize_base_url(base_url)
    page = normalize_page_origin(page_origin) if page_origin else None
    origins = normalize_origins(allowed_origins, browser_base=page or base_url)
    key_set = normalize_jwks(jwks)
    key_uri = normalize_jwks_uri(jwks_uri, base_url=base_url)

    if await _by_public_id(session, resolved_id) is not None:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=PluginServiceMessages.DUPLICATE_PUBLIC_ID,
        )
    publisher = await ensure_publisher(session, publisher_prefix(resolved_id))

    row = PluginServiceRegistration(
        public_id=resolved_id,
        publisher_id=publisher.id,
        base_url=base_url,
        page_origin=page,
        allowed_origins=origins,
        jwks=key_set,
        jwks_uri=key_uri,
        mandatory=mandatory,
        operations_only=operations_only,
        enabled=enabled,
    )
    vendor_changed = await _apply_vendor(session, row, vendor_values)
    await vendor_values_service.sync_required(session, row)
    session.add(row)
    await session.flush()
    await audit_service.record(
        session,
        event_type=AuditEventType.PLUGIN_SERVICE_CREATED,
        actor_user_id=actor_user_id,
        target_type="plugin_service_registration",
        target_id=row.id,
        detail={
            **audit_service.changed_fields(
                {}, audit_service.snapshot(row, AUDITED_FIELDS)
            ),
            **({"vendor_values": vendor_changed} if vendor_changed else {}),
        },
    )
    await session.commit()
    await session.refresh(row)
    invalidate_registrations()
    return row


async def _apply_vendor(
    session: AsyncSession,
    row: PluginServiceRegistration,
    submitted: dict[str, str | None] | None,
) -> list[str]:
    """Set the vendor values the form sent, against the fields the listing's
    manifest declares. Returns the keys that changed, never their values."""
    if not submitted:
        return []
    definitions = await vendor_values_service.listing_definitions(
        session, [row.listing_uid]
    )
    return vendor_values_service.apply_vendor_values(
        row, submitted, definition=definitions.get(row.listing_uid or "")
    )


async def update_registration(
    session: AsyncSession,
    registration_id: int,
    *,
    base_url: str | None = None,
    page_origin: str | None = None,
    allowed_origins: Iterable[str] | None = None,
    jwks: dict | None = None,
    jwks_uri: str | None = None,
    mandatory: bool | None = None,
    operations_only: bool | None = None,
    shared_routes: bool | None = None,
    enabled: bool | None = None,
    vendor_values: dict[str, str | None] | None = None,
    actor_user_id: int | None = None,
) -> PluginServiceRegistration:
    """Edit a registration's deployment facts.

    An empty ``page_origin`` clears it, putting both surfaces back on
    ``base_url``; an empty ``jwks_uri`` clears it. A ``jwks_uri`` kept while
    ``base_url`` moves is checked against the new origin. ``shared_routes``
    is written to the registration's installs in the install index in the same
    transaction, and turning it off is refused (409) while a vendor
    installation routes to more than one community.
    """
    row = await get_registration(session, registration_id)
    before = audit_service.snapshot(row, AUDITED_FIELDS)
    placement = (base_url, page_origin, allowed_origins, jwks, jwks_uri)
    if row.kind == RegistrationKind.DECLARATIVE and any(
        value is not None for value in placement
    ):
        raise _bad_request(
            PluginServiceMessages.DECLARATIVE_NOT_PLACED,
            "a declarative plug-in has no address, origins or keys",
        )
    _write_placement(
        row,
        base_url=base_url,
        page_origin=page_origin,
        allowed_origins=allowed_origins,
        jwks=jwks,
        jwks_uri=jwks_uri,
    )
    if mandatory is not None:
        row.mandatory = mandatory
    if operations_only is not None:
        row.operations_only = operations_only
    if shared_routes is not None:
        row.shared_routes = shared_routes
    if enabled is not None:
        row.enabled = enabled
    vendor_changed = await _apply_vendor(session, row, vendor_values)
    await vendor_values_service.sync_required(session, row)

    row.updated_at = utcnow()
    session.add(row)
    if shared_routes is not None and row.listing_uid:
        await _write_exclusive(session, row)
    changed = audit_service.changed_fields(
        before, audit_service.snapshot(row, AUDITED_FIELDS)
    )
    if vendor_changed:
        # Which values moved, by key. A value is the vendor client's
        # credential, so none of it reaches the record.
        changed = {**changed, "vendor_values": vendor_changed}
    if changed["changed"] or vendor_changed:
        await audit_service.record(
            session,
            event_type=AuditEventType.PLUGIN_SERVICE_UPDATED,
            actor_user_id=actor_user_id,
            target_type="plugin_service_registration",
            target_id=row.id,
            detail=changed,
        )
    await session.commit()
    await session.refresh(row)
    # The kill switch, the flags, the keys and the origin list are all
    # read through a cached snapshot on the request path, so an operator's edit
    # drops it rather than waiting out its TTL.
    invalidate_registrations()
    return row


async def _write_exclusive(
    session: AsyncSession, row: PluginServiceRegistration
) -> None:
    """Write each of the registration's installs ``exclusive`` as
    ``shared_routes`` now says. The registration's row is written first: a
    connect claiming a route reads it under a share lock, so it comes wholly
    before this write or after it."""
    exclusive = not row.shared_routes
    await session.flush()
    try:
        await session.exec(
            update(PluginInstall)
            .where(
                PluginInstall.listing_uid == row.listing_uid,
                PluginInstall.exclusive != exclusive,
            )
            .values(exclusive=exclusive)
        )
    except IntegrityError as exc:
        await session.rollback()
        if dbapi_constraint(exc) != EXCLUSIVE_ROUTE_INDEX:
            raise
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=PluginServiceMessages.SHARED_ROUTES_IN_USE,
        ) from exc


def _write_placement(
    row: PluginServiceRegistration,
    *,
    base_url: str | None,
    page_origin: str | None,
    allowed_origins: Iterable[str] | None,
    jwks: dict | None,
    jwks_uri: str | None,
) -> None:
    """Write where a plug-in runs, the origins that may frame it, and its keys.

    ``None`` leaves a field as it is; an empty ``page_origin``, ``jwks`` or
    ``jwks_uri`` clears it.
    """
    # Whether the origin list is still just the plug-in's own origin. An untouched
    # list follows the address it was derived from; one an operator typed is
    # theirs and is left exactly as typed. A container with no location yet
    # has no origin of its own, so its empty list counts as untouched.
    current_base = row_browser_base(row)
    origins_were_default = (
        list(row.allowed_origins or []) == [origin_of(current_base)]
        if current_base
        else not row.allowed_origins
    )

    if base_url is not None:
        row.base_url = normalize_base_url(base_url)
    if page_origin is not None:
        cleaned = page_origin.strip()
        row.page_origin = normalize_page_origin(cleaned) if cleaned else None
    new_base = row_browser_base(row)
    if allowed_origins is not None:
        if new_base is None:
            # Nothing to derive a default from, and nothing to frame yet.
            row.allowed_origins = [normalize_origin(item) for item in allowed_origins]
        else:
            row.allowed_origins = normalize_origins(
                allowed_origins, browser_base=new_base
            )
    elif origins_were_default and new_base is not None:
        row.allowed_origins = normalize_origins(None, browser_base=new_base)
    if jwks is not None:
        # Replaces rather than merges, and an empty object clears: a key set is
        # provisioned whole, so two entries mean a rotation is in flight and
        # one means it is over.
        row.jwks = normalize_jwks(jwks)
    if jwks_uri is not None and row.base_url is not None:
        row.jwks_uri = normalize_jwks_uri(jwks_uri, base_url=row.base_url)
    elif row.jwks_uri is not None and base_url is not None and row.base_url:
        row.jwks_uri = normalize_jwks_uri(row.jwks_uri, base_url=row.base_url)


async def delete_registration(
    session: AsyncSession, registration_id: int, *, actor_user_id: int | None = None
) -> None:
    """Remove a registration. One whose plug-in facts come from the registry is
    switched off instead (409): the next refresh would bring it back."""
    row = await get_registration(session, registration_id)
    if row.source == RegistrationSource.REGISTRY:
        raise _registry_managed()
    await session.delete(row)
    await audit_service.record(
        session,
        event_type=AuditEventType.PLUGIN_SERVICE_DELETED,
        actor_user_id=actor_user_id,
        target_type="plugin_service_registration",
        target_id=registration_id,
        detail={},
    )
    await session.commit()
    invalidate_registrations()


# --- connect: the key set the plug-in serves --------------------------------------


@dataclass(frozen=True, order=True)
class PublishedKey:
    """One key the plug-in serves: its ``kid`` and RFC 7638 thumbprint."""

    kid: str
    fingerprint: str


async def _served_key_set(
    base_url: str | None, transport: httpx.AsyncBaseTransport | None
) -> tuple[dict, list[PublishedKey]]:
    """The key set the plug-in serves under ``base_url``, held to what a pasted
    set must be, with each key's fingerprint."""
    if not base_url:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=PluginServiceMessages.CONNECT_NEEDS_BASE_URL,
        )
    url = key_set_url(base_url)
    try:
        document = await read_key_set(url, transport=transport)
    except KeySetUnreadableError as exc:
        logger.info("plug-in services: %s could not be read (%s)", url, exc)
        raise HTTPException(
            status_code=http_status.HTTP_502_BAD_GATEWAY,
            detail=PluginServiceMessages.KEYS_UNREADABLE,
        ) from exc
    key_set = normalize_jwks(document)
    if key_set is None:
        raise _bad_request(
            PluginServiceMessages.INVALID_JWKS, "the plug-in serves no keys"
        )
    keys = [
        PublishedKey(kid=entry["kid"], fingerprint=jwk_thumbprint(entry))
        for entry in key_set["keys"]
    ]
    return key_set, keys


def _keys_changed() -> HTTPException:
    return HTTPException(
        status_code=http_status.HTTP_409_CONFLICT,
        detail=PluginServiceMessages.KEYS_CHANGED,
    )


async def published_keys(
    session: AsyncSession,
    registration_id: int,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[PublishedKey]:
    """The keys the plug-in serves, for the operator to compare with the
    fingerprints its container logged. Writes nothing."""
    row = await get_registration(session, registration_id)
    _, keys = await _served_key_set(row.base_url, transport)
    return keys


async def connect_registration(
    session: AsyncSession,
    registration_id: int,
    *,
    keys: Sequence[PublishedKey],
    actor_user_id: int | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> PluginServiceRegistration:
    """Pin the key set the plug-in serves as the registration's ``jwks``, and
    clear its ``jwks_uri`` so the pinned set is the only one it is verified
    against.

    The set is read again rather than taken from the request, and stored only
    when its keys, ``kid`` and fingerprint together, are the ones the operator
    confirmed, and the base URL it was read from is still the registration's
    (409 otherwise). The row is locked for that check and the write, after the
    read, so no lock is held while the plug-in is asked.
    """
    base_url = (await get_registration(session, registration_id)).base_url
    key_set, served = await _served_key_set(base_url, transport)
    if sorted(served) != sorted(keys):
        raise _keys_changed()
    locked = (
        await session.exec(
            select(PluginServiceRegistration)
            .where(PluginServiceRegistration.id == registration_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).first()
    if locked is None or locked.base_url != base_url:
        await session.rollback()
        raise _keys_changed()
    return await update_registration(
        session,
        registration_id,
        jwks=key_set,
        jwks_uri="",
        actor_user_id=actor_user_id,
    )


# --- plug-in facts, from a listing ------------------------------------------------

#: What a listing's ``registration`` block may not name: where a container runs
#: and the keys it signs with are the deployment's.
_DEPLOYMENT_KEYS = ("base_url", "page_origin", "jwks", "jwks_uri")

#: What a listing's Compose service may hold: YAML text, and the address the
#: service answers at on the Compose network. A ``${`` opens one of the
#: placeholders filled when the snippet is shown, and nothing else.
_COMPOSE_KEYS = frozenset({"service", "base_url"})
_MAX_COMPOSE_SERVICE = 4096
_MAX_COMPOSE_BASE_URL = 512
_COMPOSE_IMAGE = "${IMAGE}"
_COMPOSE_INITIATIVE_URL = "${INITIATIVE_URL}"
#: A host as a URL parser reads it back, lowercased.
_COMPOSE_HOST_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789.-")

#: Characters a container image reference may use (``<repository>@sha256:``).
_IMAGE_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789._/:-@")
_IMAGE_DIGEST_MARK = "@sha256:"
_HEX_DIGITS = frozenset("0123456789abcdef")


class ListingRegistrationError(ValueError):
    """A listing's ``registration`` block that is not applied. ``conflict``
    says another listing holds the registration for the plug-in it names."""

    def __init__(self, detail: str, *, conflict: bool = False) -> None:
        super().__init__(detail)
        self.conflict = conflict


@dataclass(frozen=True)
class ListingRegistration:
    """The plug-in facts one listing gives the registration for its service."""

    public_id: str
    listing_uid: str
    #: The catalog source of the listing (``registry``, ``operator``, …).
    source: str
    #: ``container`` or ``declarative`` (``RegistrationKind``).
    kind: str
    image: str | None
    scope_ceiling: list[str]
    #: The Compose service its publisher wrote, placeholders unfilled.
    compose: dict[str, str] | None = None


def _image_reference(value: Any) -> str:
    """A container image pinned by digest: ``<repository>@sha256:<hex>``."""
    if (
        not isinstance(value, str)
        or len(value) > IMAGE_REFERENCE_MAX_LENGTH
        or any(char not in _IMAGE_CHARS for char in value)
        or value.count("@") != 1
    ):
        raise ListingRegistrationError("the container image is not a usable reference")
    repository, mark, digest = value.partition(_IMAGE_DIGEST_MARK)
    if (
        not repository
        or not mark
        or len(digest) != 64
        or any(char not in _HEX_DIGITS for char in digest)
    ):
        raise ListingRegistrationError(
            "the container image is not pinned by sha256 digest"
        )
    return value


def _compose(value: Any, *, image: str | None) -> dict[str, str]:
    """A listing's Compose service: ``service``, YAML text whose only
    placeholders are ``${IMAGE}`` (only beside an image) and
    ``${INITIATIVE_URL}``, and ``base_url``, an http(s) address with a host, an
    optional port and an optional path."""
    if not isinstance(value, Mapping) or set(value) != _COMPOSE_KEYS:
        raise ListingRegistrationError("compose names its service and base_url only")
    service, base_url = value["service"], value["base_url"]
    if not isinstance(service, str) or not 0 < len(service) <= _MAX_COMPOSE_SERVICE:
        raise ListingRegistrationError(
            f"compose.service must be 1..{_MAX_COMPOSE_SERVICE} characters"
        )
    start = service.find("${")
    while start != -1:
        placeholder = next(
            (
                name
                for name in (_COMPOSE_IMAGE, _COMPOSE_INITIATIVE_URL)
                if service.startswith(name, start)
            ),
            None,
        )
        if placeholder is None:
            raise ListingRegistrationError(
                "compose.service fills ${IMAGE} and ${INITIATIVE_URL} only"
            )
        if placeholder == _COMPOSE_IMAGE and image is None:
            raise ListingRegistrationError("compose.service names an image it lacks")
        start = service.find("${", start + len(placeholder))
    if not isinstance(base_url, str) or len(base_url) > _MAX_COMPOSE_BASE_URL:
        raise ListingRegistrationError(
            f"compose.base_url must be at most {_MAX_COMPOSE_BASE_URL} characters"
        )
    try:
        parsed = urlparse(base_url)
        _ = parsed.port  # a port that is not a number raises
    except ValueError as exc:
        raise ListingRegistrationError("compose.base_url is not a usable URL") from exc
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or any(char not in _COMPOSE_HOST_CHARS for char in parsed.hostname)
        or parsed.username is not None
        or any(char in "?#" or char.isspace() for char in base_url)
    ):
        raise ListingRegistrationError("compose.base_url is not a usable URL")
    return {"service": service, "base_url": base_url}


def filled_compose(row: PluginServiceRegistration) -> str | None:
    """The registration's Compose service as the operator copies it: its
    image pinned by digest and Initiative's public address filled in."""
    service = (row.compose or {}).get("service")
    if not isinstance(service, str):
        return None
    return service.replace(_COMPOSE_IMAGE, row.image_digest or "").replace(
        _COMPOSE_INITIATIVE_URL, settings.APP_URL.rstrip("/")
    )


def _vocabulary(values: Any, allowed: frozenset[str], *, what: str) -> list[str]:
    """``values`` ∩ ``allowed``, sorted; anything else is dropped and logged,
    so a listing written for a newer build still applies."""
    if values is None:
        return []
    if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
        raise ListingRegistrationError(f"{what} must be a list of strings")
    dropped = sorted({value for value in values if value not in allowed})
    if dropped:
        logger.warning(
            "plug-in services: %s drops what this build does not define: %s",
            what,
            ", ".join(dropped),
        )
    return sorted({value for value in values if value in allowed})


async def read_listing_registration(
    session: AsyncSession,
    spec: Any,
    *,
    listing_uid: str,
    listing_public_id: str,
    definition: Any,
    source: str,
) -> ListingRegistration:
    """Read a listing's ``registration`` block, before the listing is written.

    The block is the same from every source: ``kind`` — ``container``, or
    ``declarative`` for a plug-in with no service block — an optional ``image``
    pinned by digest and its Compose service (a container's only), the
    and the ``scope_ceiling``. It names no location and no keys. The registration it writes is
    the one for the plug-in the listing's definition names, under the listing's own
    prefix; one another listing already holds is refused.
    """
    if not isinstance(spec, Mapping):
        raise ListingRegistrationError("registration is not an object")
    declarative = is_declarative(definition)
    kind = RegistrationKind.DECLARATIVE if declarative else RegistrationKind.CONTAINER
    service_id = service_public_id(definition, listing_public_id=listing_public_id)
    if service_id is None:
        raise ListingRegistrationError("only a service plug-in carries a registration")
    try:
        public_id = normalize_public_id(service_id)
    except HTTPException as exc:
        raise ListingRegistrationError("the service public_id is not usable") from exc
    prefix = publisher_prefix(public_id)
    if prefix != publisher_prefix(listing_public_id):
        raise ListingRegistrationError("the service is published under another prefix")
    if spec.get("kind") != kind:
        raise ListingRegistrationError(f'registration.kind must be "{kind}"')
    if declarative and any(key in spec for key in ("image", "compose")):
        raise ListingRegistrationError("a declarative plug-in runs no container")
    stated = [key for key in _DEPLOYMENT_KEYS if key in spec]
    if stated:
        raise ListingRegistrationError(
            f"a container's location and keys are the deployment's: {', '.join(stated)}"
        )
    declared_image = spec.get("image")
    image = _image_reference(declared_image) if declared_image is not None else None
    declared_compose = spec.get("compose")
    compose = (
        _compose(declared_compose, image=image)
        if declared_compose is not None
        else None
    )
    declared_ceiling = spec.get("scope_ceiling")
    ceiling = _vocabulary(
        declared_ceiling,
        frozenset(ALL_SCOPES)
        | frozenset(
            scope
            for scope in (
                declared_ceiling if isinstance(declared_ceiling, list) else []
            )
            if isinstance(scope, str) and plugin_scope_target(scope) is not None
        ),
        what=f"{public_id} ceiling",
    )
    held = await _by_public_id(session, public_id)
    if held is not None and held.listing_uid not in (None, listing_uid):
        raise ListingRegistrationError(
            f"{public_id} is registered for listing {held.listing_uid}",
            conflict=True,
        )
    return ListingRegistration(
        public_id=public_id,
        listing_uid=listing_uid,
        source=source,
        kind=kind,
        image=image,
        scope_ceiling=ceiling,
        compose=compose,
    )


async def apply_listing_registration(
    session: AsyncSession, registration: ListingRegistration
) -> PluginServiceRegistration:
    """Write a listing's plug-in facts onto the registration for its service.

    The one writer of plug-in facts, for every source. A registration that is not
    there yet is created, with the deployment facts ``PLUGIN_SERVICES_CONFIG``
    gives it, and is not live until it has a location and keys. The caller
    commits.
    """
    row = await _by_public_id(session, registration.public_id)
    created = row is None
    if row is None:
        publisher = await ensure_publisher(
            session, publisher_prefix(registration.public_id)
        )
        row = PluginServiceRegistration(
            public_id=registration.public_id, publisher_id=publisher.id
        )
    before = {} if created else audit_service.snapshot(row, AUDITED_FIELDS)
    row.listing_uid = registration.listing_uid
    row.kind = registration.kind
    if registration.kind == RegistrationKind.DECLARATIVE:
        # Runs nowhere and signs nothing: a location and keys a container
        # version left behind go with it.
        row.base_url = row.page_origin = row.jwks = row.jwks_uri = None
        row.allowed_origins = []
    row.scope_ceiling = registration.scope_ceiling
    row.image_digest = registration.image
    row.compose = registration.compose
    row.source = (
        RegistrationSource.REGISTRY
        if registration.source == RegistrationSource.REGISTRY
        else RegistrationSource.OPERATOR
    )
    if created:
        facts = configured_facts(registration.public_id)
        if facts is not None:
            apply_deployment_facts(row, facts)
    await vendor_values_service.sync_required(session, row)
    changed = audit_service.changed_fields(
        before, audit_service.snapshot(row, AUDITED_FIELDS)
    )
    if not changed["changed"]:
        return row
    row.updated_at = utcnow()
    session.add(row)
    await session.flush()
    await audit_service.record(
        session,
        event_type=(
            AuditEventType.PLUGIN_SERVICE_CREATED
            if created
            else AuditEventType.PLUGIN_SERVICE_UPDATED
        ),
        actor_user_id=None,
        target_type="plugin_service_registration",
        target_id=row.id,
        detail={"via": registration.source, **changed},
    )
    invalidate_registrations()
    return row


# --- boot reconciliation -----------------------------------------------------


@dataclass(frozen=True)
class ReconcileResult:
    """What one pass over ``PLUGIN_SERVICES_CONFIG`` did."""

    updated: int = 0
    unchanged: int = 0
    #: Entries for plug-ins whose listing has not arrived yet.
    waiting: int = 0
    skipped: int = 0

    @property
    def total(self) -> int:
        return self.updated + self.unchanged + self.waiting + self.skipped


def _load_entries(path: Path) -> list[dict[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(document, dict):
        document = document.get("plugin_services", [])
    if not isinstance(document, list):
        raise ValueError("expected a JSON array of plug-in service entries")
    return [entry for entry in document if isinstance(entry, dict)]


@dataclass(frozen=True)
class DeploymentFacts:
    """How this deployment runs a plug-in, from an ``PLUGIN_SERVICES_CONFIG`` entry.

    ``None`` is a fact the entry leaves out, which leaves the row's value as
    it is. A container's placement is one statement: an entry that gives its
    ``base_url`` gives its browser address and keys with it, and clears the
    ones it leaves out.
    """

    base_url: str | None = None
    page_origin: str | None = None
    jwks: dict | None = None
    jwks_uri: str | None = None
    allowed_origins: list[str] | None = None
    mandatory: bool | None = None
    operations_only: bool | None = None
    vendor_env: Any = None

    @property
    def places(self) -> bool:
        """Whether it gives a location and keys."""
        return self.base_url is not None


def _deployment_facts(entry: dict[str, Any]) -> DeploymentFacts:
    """Read an entry, refusing one that names what only the plug-in's listing
    states, or a location and keys that do not fit together."""
    stated = [key for key in LISTING_STATED_FIELDS if key in entry]
    if stated:
        raise _bad_request(
            PluginServiceMessages.STATED_BY_LISTING,
            f"the plug-in's listing states {', '.join(stated)}",
        )
    declared_base = entry.get("base_url")
    base_url = normalize_base_url(str(declared_base)) if declared_base else None
    if base_url is None and any(
        entry.get(key) for key in ("page_origin", "jwks", "jwks_uri")
    ):
        raise _bad_request(
            PluginServiceMessages.INVALID_BASE_URL,
            "a container's browser address and keys come with its base_url",
        )
    declared_origins = entry.get("allowed_origins") or []
    if not isinstance(declared_origins, list) or len(declared_origins) > _MAX_ORIGINS:
        raise _bad_request(
            PluginServiceMessages.INVALID_ORIGIN,
            f"allowed_origins must be a list of at most {_MAX_ORIGINS} origins",
        )
    origins = [normalize_origin(str(item)) for item in declared_origins]
    declared_page = entry.get("page_origin")
    declared_uri = entry.get("jwks_uri")
    return DeploymentFacts(
        base_url=base_url,
        page_origin=(
            normalize_page_origin(str(declared_page)) if declared_page else None
        ),
        jwks=normalize_jwks(entry.get("jwks")),
        jwks_uri=(
            normalize_jwks_uri(str(declared_uri), base_url=base_url or "")
            if declared_uri
            else None
        ),
        allowed_origins=origins or None,
        mandatory=bool(entry["mandatory"]) if "mandatory" in entry else None,
        operations_only=(
            bool(entry["operations_only"]) if "operations_only" in entry else None
        ),
        vendor_env=entry.get("vendor_env"),
    )


def configured_facts(public_id: str) -> DeploymentFacts | None:
    """The facts ``PLUGIN_SERVICES_CONFIG`` gives for ``public_id``, or ``None``.

    Read when a listing apply creates the registration, so an entry written
    before the listing arrived reaches its row. An entry reconciliation
    refuses gives nothing here either.
    """
    configured = settings.PLUGIN_SERVICES_CONFIG
    if not configured:
        return None
    try:
        entries = _load_entries(Path(configured))
    except (OSError, ValueError):
        return None
    for entry in entries:
        if str(entry.get("public_id", "")).strip().lower() != public_id:
            continue
        try:
            return _deployment_facts(entry)
        except HTTPException:
            continue
    return None


def apply_deployment_facts(
    row: PluginServiceRegistration, facts: DeploymentFacts
) -> bool:
    """Write an entry's facts onto a registration, and say whether any moved.

    Vendor values are sealed from the environment variables the entry names.
    """

    def state() -> tuple:
        return (
            row.base_url,
            row.page_origin,
            list(row.allowed_origins or []),
            row.jwks,
            row.jwks_uri,
            row.mandatory,
            row.operations_only,
        )

    was = state()
    if row.kind == RegistrationKind.DECLARATIVE:
        # Runs nowhere and signs nothing: an entry's placement does not apply.
        facts = replace(facts, base_url=None, allowed_origins=None)
    _write_placement(
        row,
        base_url=facts.base_url,
        page_origin=(facts.page_origin or "") if facts.places else None,
        allowed_origins=facts.allowed_origins,
        jwks=(facts.jwks or {}) if facts.places else None,
        jwks_uri=(facts.jwks_uri or "") if facts.places else None,
    )
    if facts.mandatory is not None:
        row.mandatory = facts.mandatory
    if facts.operations_only is not None:
        row.operations_only = facts.operations_only
    vendor_moved = vendor_values_service.apply_vendor_env(
        row, facts.vendor_env, public_id=row.public_id
    )
    return bool(vendor_moved) or state() != was


async def reconcile_from_config(session: AsyncSession) -> ReconcileResult:
    """Apply the mounted config file's deployment facts to the registrations
    it names.

    Each entry is ``{public_id}`` with any of ``base_url``, ``page_origin``,
    ``allowed_origins``, ``jwks``, ``jwks_uri``, ``mandatory``,
    ``operations_only`` and ``vendor_env`` (vendor key → environment variable name, read and sealed on
    every pass). An entry naming what only the plug-in's listing states is
    refused. Database-only: this updates rows and stops. It creates none: an
    entry for a plug-in whose listing has not arrived waits, and the listing
    apply that creates its registration applies it.

    ``enabled`` is not reconciled: turning a registration off is an operator
    action, and a restart must not reverse it.

    An entry naming ``grants`` is read without it, and the pass logs that it
    was: the field is no longer part of a registration, and a file written for
    an earlier release still boots.

    A malformed file or an unreadable path costs that file, and a refused entry
    costs that entry, and nothing else — the caller keeps booting.
    """
    configured = settings.PLUGIN_SERVICES_CONFIG
    if not configured:
        return ReconcileResult()

    path = Path(configured)
    try:
        entries = _load_entries(path)
    except (OSError, ValueError) as exc:
        logger.warning("plug-in services: %s could not be read (%s)", path, exc)
        return ReconcileResult()

    updated = unchanged = waiting = skipped = 0
    # The rows this pass changed, with what they looked like before.
    edited: list[tuple[PluginServiceRegistration, dict]] = []
    seen: set[str] = set()

    for entry in entries:
        try:
            public_id = normalize_public_id(str(entry.get("public_id", "")))
            facts = _deployment_facts(entry)
        except HTTPException as exc:
            logger.warning(
                "plug-in services: entry %r refused (%s)",
                entry.get("public_id"),
                exc.detail,
            )
            skipped += 1
            continue
        if "grants" in entry:
            logger.warning(
                "plug-in services: entry %r names grants, which a registration no "
                "longer has; the field is ignored",
                public_id,
            )
        if public_id in seen:
            logger.warning(
                "plug-in services: %r appears more than once in %s — later entry skipped",
                public_id,
                path,
            )
            skipped += 1
            continue
        seen.add(public_id)

        row = await _by_public_id(session, public_id)
        if row is None:
            logger.info(
                "plug-in services: %r has no listing here yet; the listing that "
                "brings it applies its entry",
                public_id,
            )
            waiting += 1
            continue
        before = audit_service.snapshot(row, AUDITED_FIELDS)
        required_before = list(row.vendor_required or [])
        moved = apply_deployment_facts(row, facts)
        await vendor_values_service.sync_required(session, row)
        if not moved and required_before == list(row.vendor_required or []):
            unchanged += 1
            continue
        row.updated_at = utcnow()
        session.add(row)
        edited.append((row, before))
        updated += 1

    # The file is the author, so the records carry no actor.
    for edit, was in edited:
        await audit_service.record(
            session,
            event_type=AuditEventType.PLUGIN_SERVICE_UPDATED,
            actor_user_id=None,
            target_type="plugin_service_registration",
            target_id=edit.id,
            detail={
                "via": "config",
                **audit_service.changed_fields(
                    was, audit_service.snapshot(edit, AUDITED_FIELDS)
                ),
            },
        )
    await session.commit()
    invalidate_registrations()
    return ReconcileResult(
        updated=updated, unchanged=unchanged, waiting=waiting, skipped=skipped
    )
