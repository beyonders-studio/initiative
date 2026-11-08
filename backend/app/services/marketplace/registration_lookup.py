"""What the request path knows about the plug-in services this deployment wired up.

``plugin_service_registrations`` is deployment configuration: no guild role and no
bare login role holds a grant on it, and an installed plug-in's standing reads only
the few columns of its own row. Everything else a request needs from a
registration — is this plug-in wired up, is it live, where does it live, which
origins may frame it, and which keys it signs with — is loaded once on the
system engine and kept as an immutable snapshot the request path reads.

**Freshness is bounded, and a write is immediate.** An operator's kill switch
has to bite quickly, so the cache is short-lived *and* dropped in-process on
any registration or publisher write. A replica that did not serve the write
picks the change up within the TTL.

Whether a registration is live is computed by the database with the one rule
in :func:`~app.models.platform.plugin_service_registration.registration_live_sql`,
the same one the install standing asks, and carried on the snapshot. Whether
it is live in one community also asks whether it is limited to the operations
community, which the snapshot carries beside it (:meth:`RegistrationSnapshot.live_in`).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from jwt import PyJWK
from sqlalchemy import literal_column
from sqlmodel import select

from app.db import session as db_session
from app.models.platform.app_setting import AppSetting
from app.models.platform.marketplace import MarketplaceListing
from app.models.platform.plugin_service_registration import (
    PluginServiceRegistration,
    RegistrationKind,
    browser_base,
    registration_live_sql,
)
from app.models.platform.publisher import Publisher

logger = logging.getLogger(__name__)

__all__ = [
    "CACHE_TTL_SECONDS",
    "InstallState",
    "RegistrationSnapshot",
    "declarative_registration",
    "enabled_service_ids",
    "frame_origins",
    "install_state",
    "invalidate_registrations",
    "is_declarative",
    "live_registration_clause",
    "load_registrations",
    "mandatory_registrations",
    "plugin_is_offered",
    "registration_for_definition",
    "service_public_id",
]

#: How long a loaded snapshot is reused. Short enough that deactivating a
#: registration takes effect promptly on every replica, long enough that a busy
#: guild's plug-in reads do not each open a system-engine connection.
CACHE_TTL_SECONDS = 60.0


@dataclass(frozen=True)
class RegistrationSnapshot:
    """One registration, as everything outside the operator surface sees it."""

    public_id: str
    listing_uid: str | None
    #: Where Initiative's own server calls this plug-in. Empty for a registry
    #: container the operator has not placed yet, which is never live.
    base_url: str
    #: Where a person's browser loads its surfaces, when the plug-in answers there
    #: rather than at ``base_url``. Read through :attr:`browser_base`.
    page_origin: str | None
    #: Origins this plug-in's surfaces may be framed from and postMessage'd to.
    allowed_origins: tuple[str, ...]
    #: Public verification keys this plug-in signs with — its client assertions at
    #: the token endpoint — by the ``kid`` a JWT names. Parsed once when the
    #: snapshot is built rather than per token.
    #: Empty on a plug-in that has not been provisioned with a pasted set.
    keys: Mapping[str, Any]
    #: The deployment installs this plug-in in every guild (§7.7): the
    #: registration says so, or the package serving its listing does. The
    #: package's word adds the flag and never clears it.
    mandatory: bool
    #: The operator's kill switch on the registration itself.
    enabled: bool
    #: Whether anything may flow through this plug-in right now: enabled, its
    #: publisher enabled, a location, and a key set to verify against.
    #: Computed by the database from ``registration_live_sql`` when the
    #: snapshot is loaded.
    live: bool
    #: The most any install of this plug-in may be granted, as the operator set it.
    #: Not secret: it bounds what a community's seat may grant.
    scope_ceiling: tuple[str, ...] = ()
    #: Where the plug-in publishes its key set, when it does
    #: (:mod:`app.services.marketplace.plugin_keys`).
    jwks_uri: str | None = None
    #: Initiative makes this plug-in's calls itself, from its manifest; it has no
    #: location and no keys.
    declarative: bool = False
    #: The plug-in is for the deployment's operations community alone.
    operations_only: bool = False
    #: The deployment's operations community when the snapshot was loaded.
    operations_guild_id: int | None = None

    @property
    def browser_base(self) -> str:
        """The base to build an address a browser will be sent to."""
        return browser_base(self)

    def serves(self, guild_id: int | None) -> bool:
        """Whether this plug-in is for community ``guild_id``: any community,
        unless it is limited to the operations community and that is another
        one, or none is named."""
        return not self.operations_only or (
            guild_id is not None and guild_id == self.operations_guild_id
        )

    def live_in(self, guild_id: int | None) -> bool:
        """Whether anything may flow through this plug-in in community
        ``guild_id``: the snapshot's spelling of ``registration_live_sql``
        asked for that community."""
        return self.live and self.serves(guild_id)


def _parse_keys(row: PluginServiceRegistration) -> Mapping[str, Any]:
    """Build the ``kid`` → key index for one registration.

    The keys were validated when they were stored, so anything unusable here
    is a surprise worth logging rather than a case to model: the entry is left
    out, and a token naming it finds no key.
    """
    key_set = row.jwks or {}
    parsed: dict[str, Any] = {}
    for entry in key_set.get("keys", []) or []:
        kid = entry.get("kid") if isinstance(entry, dict) else None
        if not kid:
            continue
        try:
            parsed[kid] = PyJWK.from_dict(entry).key
        except Exception:
            logger.warning(
                "plug-in services: %s has an unusable key %r", row.public_id, kid
            )
    return MappingProxyType(parsed)


_cache: dict[str, RegistrationSnapshot] | None = None
_loaded_at: float = 0.0


def invalidate_registrations() -> None:
    """Drop the snapshot. Called on every registration write."""
    global _cache, _loaded_at
    _cache = None
    _loaded_at = 0.0


def live_registration_clause() -> Any:
    """:func:`registration_live_sql` over ``plugin_service_registrations`` joined
    to ``publishers``, for a query that selects both by their table names."""
    return literal_column(
        registration_live_sql(
            PluginServiceRegistration.__tablename__, Publisher.__tablename__
        )
    )


async def load_registrations(*, force: bool = False) -> dict[str, RegistrationSnapshot]:
    """Every registration, keyed by ``public_id``, with whether it is live.

    Runs on the system engine: the table carries no request-path grant beyond
    the install standing's few columns, so this is the reader everything else
    shares. One statement joins each registration to its publisher and its
    listing, and reads the operations community beside it.
    """
    from app.services.marketplace.catalog import REGISTRY_SOURCE
    from app.services.marketplace.tuf_registry import configured_root_is_builtin

    global _cache, _loaded_at
    if (
        not force
        and _cache is not None
        and (time.monotonic() - _loaded_at) < CACHE_TTL_SECONDS
    ):
        return _cache

    operations = (
        select(AppSetting.operations_guild_id)
        .where(AppSetting.id == 1)
        .scalar_subquery()
    )
    async with db_session.SystemSessionLocal() as session:
        rows = (
            await session.exec(
                select(
                    PluginServiceRegistration,
                    live_registration_clause().label("live"),
                    operations.label("operations_guild_id"),
                    MarketplaceListing.mandatory,
                    MarketplaceListing.source,
                )
                .join(Publisher, Publisher.id == PluginServiceRegistration.publisher_id)
                .outerjoin(
                    MarketplaceListing,
                    MarketplaceListing.uid == PluginServiceRegistration.listing_uid,
                )
                .order_by(PluginServiceRegistration.public_id)
            )
        ).all()
    # The package's terms hold only under the shipped root.
    packaged = configured_root_is_builtin()

    snapshots = {
        row.public_id: RegistrationSnapshot(
            public_id=row.public_id,
            listing_uid=row.listing_uid,
            base_url=row.base_url or "",
            page_origin=row.page_origin,
            allowed_origins=tuple(row.allowed_origins or []),
            keys=_parse_keys(row),
            mandatory=bool(row.mandatory)
            or (packaged and bool(signed) and source == REGISTRY_SOURCE),
            enabled=bool(row.enabled),
            live=bool(live),
            scope_ceiling=tuple(sorted(row.scope_ceiling or [])),
            jwks_uri=row.jwks_uri,
            declarative=row.kind == RegistrationKind.DECLARATIVE,
            operations_only=row.operations_only,
            operations_guild_id=operations_guild_id,
        )
        for row, live, operations_guild_id, signed, source in rows
    }
    _cache = snapshots
    _loaded_at = time.monotonic()
    return snapshots


async def frame_origins() -> tuple[str, ...]:
    """Every origin a plug-in surface may be framed from, deduped and ordered.

    This deployment's registrations are its trusted-site list. An origin gets
    on it by an operator wiring up a plug-in service — so what comes back
    describes the services this deployment runs, and says nothing about any
    guild or reader.

    Only live registrations count, which is how the operator's kill switch and
    a publisher's reach the frame policy: within the cache TTL, a stopped plug-in's
    origins are gone from it.
    """
    snapshots = await load_registrations()
    return tuple(
        sorted(
            {
                origin
                for snapshot in snapshots.values()
                if snapshot.live
                for origin in snapshot.allowed_origins
            }
        )
    )


def is_declarative(definition: Mapping[str, Any] | None) -> bool:
    """Whether a definition is a declarative plug-in's: a service plug-in with no
    ``service`` block, whose calls Initiative makes itself."""
    return (
        isinstance(definition, Mapping)
        and definition.get("plugin_kind") == "service"
        and "service" not in definition
    )


def service_public_id(
    definition: Mapping[str, Any] | None, *, listing_public_id: str | None = None
) -> str | None:
    """The plug-in a pinned definition names, if it names one.

    Only a ``service`` plug-in has one — a tool instance mounts one of this build's
    own tools and has no container behind it. A container names itself in its ``service`` block; a
    declarative plug-in has none, and is its listing's ``listing_public_id``.
    """
    if is_declarative(definition):
        return listing_public_id
    if (
        not isinstance(definition, Mapping)
        or definition.get("plugin_kind") != "service"
    ):
        return None
    service = definition.get("service")
    if not isinstance(service, dict):
        return None
    public_id = service.get("public_id")
    return public_id if isinstance(public_id, str) and public_id else None


async def registration_for_definition(
    definition: Mapping[str, Any] | None, *, listing_uid: str | None = None
) -> RegistrationSnapshot | None:
    """The registration behind an installed plug-in, or ``None``.

    ``None`` covers both "this plug-in has no service" and "this deployment has not
    wired that service up". A declarative plug-in's is the one its listing,
    ``listing_uid``, applied.
    """
    if is_declarative(definition):
        return await declarative_registration(listing_uid)
    public_id = service_public_id(definition)
    if public_id is None:
        return None
    return (await load_registrations()).get(public_id)


async def declarative_registration(
    listing_uid: str | None,
) -> RegistrationSnapshot | None:
    """The registration a declarative plug-in's listing, ``listing_uid``, applied."""
    return next(
        (
            snapshot
            for snapshot in (await load_registrations()).values()
            if listing_uid and snapshot.listing_uid == listing_uid
        ),
        None,
    )


@dataclass(frozen=True)
class InstallState:
    """What an installed plug-in's registration says about it, for a client.

    Both halves are derived rather than stored, which is what makes an
    operator's edits take effect without touching a single install: clearing
    ``mandatory`` turns every copy into an ordinary plug-in, and the kill switch
    makes every copy unavailable, in the time it takes a cached snapshot to
    expire.
    """

    mandatory: bool = False
    available: bool = True
    #: The most the operator allows any install of this plug-in to be granted.
    scope_ceiling: tuple[str, ...] = ()


def _has_registration(definition: Mapping[str, Any] | None) -> bool:
    return is_declarative(definition) or service_public_id(definition) is not None


async def install_state(
    definition: dict[str, Any] | None,
    *,
    guild_id: int | None,
    listing_uid: str | None = None,
) -> InstallState:
    """The registration-derived state of one install in community ``guild_id``.

    One limited to the operations community is neither mandatory nor available
    in any other.

    A plug-in with no service behind it — a tool instance — is always
    available and never mandatory: there is no registration for it to depend on.
    """
    if not _has_registration(definition):
        return InstallState()
    snapshot = await registration_for_definition(definition, listing_uid=listing_uid)
    if snapshot is None:
        # Installed here, but this deployment has not wired the service up (or
        # no longer does). Nothing it offers can be reached.
        return InstallState(mandatory=False, available=False)
    return InstallState(
        mandatory=snapshot.mandatory and snapshot.serves(guild_id),
        available=snapshot.live_in(guild_id),
        scope_ceiling=snapshot.scope_ceiling,
    )


async def enabled_service_ids(guild_id: int | None) -> frozenset[str]:
    """Every plug-in service this deployment has wired up and switched on, for
    community ``guild_id`` (``None`` for no community).

    What the catalog reads to decide which plug-in listings it offers: a plug-in is
    published to everyone, and registering it is how a deployment says it runs
    that one. A listing naming a service that is not in here is not offered,
    because installing it would produce a plug-in with nothing behind it.

    Only registrations live there: a plug-in switched off, or whose publisher
    is, or that has no key set, is not offered, nor is one limited to the
    operations community anywhere else.
    """
    return frozenset(
        snapshot.public_id
        for snapshot in (await load_registrations()).values()
        if snapshot.live_in(guild_id)
    )


async def plugin_is_offered(
    definition: dict[str, Any] | None,
    *,
    guild_id: int | None,
    listing_uid: str | None = None,
) -> bool:
    """Whether this deployment offers the plug-in a listing describes to
    community ``guild_id``.

    The per-listing spelling of :func:`enabled_service_ids`, for the paths that
    hold one definition rather than a query: the listing page and the install.

    A plug-in with no service behind it — one that mounts one of this build's own
    tools — is always offered, because there is no registration for it to
    depend on.
    """
    if not _has_registration(definition):
        return True
    snapshot = await registration_for_definition(definition, listing_uid=listing_uid)
    return snapshot is not None and snapshot.live_in(guild_id)


async def mandatory_registrations() -> list[RegistrationSnapshot]:
    """The plug-ins this deployment installs into every guild.

    Only the live ones: a registration the operator switched off, or whose
    publisher is off, installs nowhere new, because the kill switch outranks
    the flag (§7.7). Whether the plug-in's container is up is not asked: an
    install is a local row, and the plug-in finds the guild on its next
    installations pull.
    """
    return [
        snapshot
        for snapshot in (await load_registrations()).values()
        if snapshot.mandatory and snapshot.live
    ]
