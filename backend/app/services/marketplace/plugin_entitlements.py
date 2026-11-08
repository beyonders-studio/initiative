"""Entitlement statements and usage totals: what a community holds of a plug-in
whose listing a package names terms for, and what the plug-in reports it used.

Neutral vocabulary throughout. The **issuer** (this deployment's billing
service, on its signed boundary) sends a **statement** per (community,
listing): a compact JWS it signed, whose claims carry ``version`` and
``values``, the values the plug-in's own. This deployment stores the latest
exactly as sent, hands it to the installed plug-in as the ``entitlement`` hook
(``{"statement": "<jws>"}``), and answers the plug-in's pull for it the same
way. It never re-signs or rewrites one: the plug-in verifies the issuer's
signature with the issuer's key, which reaches it from the deployment. The
version and values kept beside it are read from the claims for this
deployment's own use: the install gate and the delivery's dedup. A plug-in
reports **usage** as a period's cumulative total for a meter its terms name,
and the total is passed on to the issuer.

Only a listing with terms takes part (:func:`listing_terms`): its
``access`` comes from the package serving it, under the root shipped in the
image. Every other listing has no statement, no meter and no gate.

**Install gating.** An ``entitled`` listing installs only in a community
holding an *active* statement. A statement is active unless its values carry
``active`` as a boolean that is false: an issuer that states ``active`` decides
by it, and any statement from one that does not counts.

Everything here runs on the system engine: neither table has a request-path
grant, and every caller has authenticated whoever it acts for first.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.db import cohorts, post_commit
from app.db import session as db_session
from app.db.request_context import SystemGuild
from app.db.session import set_rls_context
from app.models.platform.marketplace import ACCESS_ENTITLED, MarketplaceListing
from app.models.platform.plugin_entitlement import PluginEntitlement, PluginUsage
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.plugin_hook_delivery import PluginHookDelivery
from app.services.marketplace import registration_lookup
from app.services.marketplace.catalog import REGISTRY_SOURCE
from app.services.marketplace.package_terms import ListingTerms

logger = logging.getLogger(__name__)

__all__ = [
    "ENTITLEMENT_HOOK",
    "REASON_TERM_FULL",
    "Statement",
    "StoredStatement",
    "UsageOutcome",
    "action_url",
    "after_install",
    "deliver_entitlement",
    "entitlement_blocks",
    "entitlement_satisfied",
    "gated_listings",
    "listing_terms",
    "read_statement",
    "record_usage",
    "statement_active",
    "statement_reason",
    "statements_for",
    "store_statement",
    "terms_for_listings",
]

#: The hook a statement is delivered to.
ENTITLEMENT_HOOK = "entitlement"
#: How long a queued statement's version is remembered for the install, so
#: the same one is not queued for it twice.
DELIVERY_TTL = timedelta(hours=24)


@dataclass(frozen=True)
class Statement:
    #: The signed statement, exactly as the issuer sent it.
    jws: str
    version: int
    values: dict[str, Any]

    @classmethod
    def of(cls, row: PluginEntitlement) -> Statement:
        return cls(jws=row.statement, version=row.version, values=dict(row.values))


@dataclass(frozen=True)
class StoredStatement:
    #: The version held after the write.
    version: int
    #: Whether the statement sent replaced the one held.
    applied: bool


def statement_active(values: Mapping[str, Any]) -> bool:
    """Whether a statement entitles its community: unless it says ``active``
    is false, it does (see the module docstring)."""
    active = values.get("active")
    return active if isinstance(active, bool) else True


#: Why a statement isn't active, as billing says it: the deployment's term
#: for the listing has no seat left for this community. Not a price: the way
#: on is a request to the deployment's owners, never a purchase.
REASON_TERM_FULL = "term_full"


def statement_reason(values: Mapping[str, Any]) -> str | None:
    """Why an inactive statement isn't active, when it says: the ``reason``
    beside ``active: false``, passed through as billing sent it."""
    if statement_active(values):
        return None
    reason = values.get("reason")
    return reason if isinstance(reason, str) and reason else None


# --- terms --------------------------------------------------------------------------


def _terms_honoured() -> bool:
    # Imported here: the registry client imports this package's catalog.
    from app.services.marketplace.tuf_registry import configured_root_is_builtin

    return configured_root_is_builtin()


def _terms(listing: MarketplaceListing) -> ListingTerms | None:
    if listing.access is None or listing.source != REGISTRY_SOURCE:
        return None
    return ListingTerms(
        access=listing.access,
        mandatory=bool(listing.mandatory),
        meters=tuple(listing.meters or ()),
    )


def terms_for_listings(
    listings: Collection[MarketplaceListing],
) -> dict[str, ListingTerms]:
    """The terms each of ``listings`` holds, by uid; a listing without any is
    left out. Every listing is without any under a root other than the one
    shipped in the image."""
    if not listings or not _terms_honoured():
        return {}
    return {
        listing.uid: terms
        for listing in listings
        if (terms := _terms(listing)) is not None
    }


async def listing_terms(
    listing_uid: str | None, session: AsyncSession | None = None
) -> ListingTerms | None:
    """The terms a package gives listing ``listing_uid``, or ``None``.

    Read on ``session`` when given (any role that reads the catalog), else on
    a system-engine session of its own.
    """
    if not listing_uid or not _terms_honoured():
        return None
    statement = select(MarketplaceListing).where(MarketplaceListing.uid == listing_uid)
    if session is not None:
        listing = (await session.exec(statement)).first()
    else:
        async with db_session.SystemSessionLocal() as system_session:
            listing = (await system_session.exec(statement)).first()
    return _terms(listing) if listing is not None else None


# --- statements ---------------------------------------------------------------------


async def read_statement(guild_id: int, listing_uid: str) -> Statement | None:
    """The statement held for one (community, listing), or ``None``."""
    async with db_session.SystemSessionLocal() as session:
        row = await session.get(PluginEntitlement, (guild_id, listing_uid))
    return Statement.of(row) if row else None


async def statements_for(
    guild_id: int, listing_uids: Collection[str]
) -> dict[str, Statement]:
    """The statements held for ``guild_id`` among ``listing_uids``, by uid."""
    if not listing_uids:
        return {}
    async with db_session.SystemSessionLocal() as session:
        rows = (
            await session.exec(
                select(PluginEntitlement).where(
                    PluginEntitlement.guild_id == guild_id,
                    col(PluginEntitlement.listing_uid).in_(sorted(set(listing_uids))),
                )
            )
        ).all()
    return {row.listing_uid: Statement.of(row) for row in rows}


def entitlement_satisfied(
    terms: ListingTerms | None, statement: Statement | None
) -> bool:
    """Whether a community may install a listing with ``terms`` while holding
    ``statement``: anything but an ``entitled`` listing may, and that one only
    on an active statement."""
    if terms is None or terms.access != ACCESS_ENTITLED:
        return True
    return statement is not None and statement_active(statement.values)


async def entitlement_blocks(
    guild_id: int, listing_uid: str, session: AsyncSession | None = None
) -> bool:
    """Whether ``guild_id`` may not install ``listing_uid`` for want of an
    active entitlement statement."""
    terms = await listing_terms(listing_uid, session)
    if terms is None or terms.access != ACCESS_ENTITLED:
        return False
    return not entitlement_satisfied(terms, await read_statement(guild_id, listing_uid))


async def gated_listings(
    guild_id: int, listings: Collection[MarketplaceListing]
) -> dict[str, str | None]:
    """The uids among ``listings`` that ``guild_id`` may not install for want
    of an active entitlement statement, each with the statement's reason when
    it gives one (:func:`statement_reason`). Two queries for any number."""
    entitled = {
        uid: terms
        for uid, terms in terms_for_listings(listings).items()
        if terms.access == ACCESS_ENTITLED
    }
    if not entitled:
        return {}
    held = await statements_for(guild_id, entitled)
    return {
        uid: (statement_reason(held[uid].values) if uid in held else None)
        for uid, terms in entitled.items()
        if not entitlement_satisfied(terms, held.get(uid))
    }


def action_url(listing_uid: str) -> str | None:
    """Where a community acts on its entitlement for a listing: the
    deployment's billing portal, on the manage page with the listing's
    purchase open, or ``None`` with no portal. The client opens it with a
    portal handoff, which is what names the community: no id of ours is in
    the address."""
    base = (settings.BILLING_URL or "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}/manage?app={quote(listing_uid, safe='')}"


async def store_statement(
    guild_id: int,
    listing_uid: str,
    *,
    statement: str,
    version: int,
    values: Mapping[str, Any],
) -> StoredStatement:
    """Keep a statement when it is newer than the one held.

    ``statement`` is the signed statement exactly as the issuer sent it, and
    ``version`` and ``values`` its claims, which the caller has read from it.
    One statement: insert, or replace a row holding a lower version. A version
    no higher than the one held changes nothing and reports what is held.
    """
    now = datetime.now(UTC)
    insert = pg_insert(PluginEntitlement).values(
        guild_id=guild_id,
        listing_uid=listing_uid,
        statement=statement,
        version=version,
        values=dict(values),
        received_at=now,
    )
    upsert = insert.on_conflict_do_update(
        index_elements=[PluginEntitlement.guild_id, PluginEntitlement.listing_uid],
        set_={
            "statement": insert.excluded.statement,
            "version": insert.excluded.version,
            "values": insert.excluded["values"],
            "received_at": insert.excluded.received_at,
        },
        where=col(PluginEntitlement.version) < insert.excluded.version,
    ).returning(PluginEntitlement.version)
    async with db_session.SystemSessionLocal() as session:
        written = (await session.exec(upsert)).first()
        if written is not None:
            await session.commit()
            return StoredStatement(version=int(written[0]), applied=True)
        held = await session.get(PluginEntitlement, (guild_id, listing_uid))
        held_version = held.version if held is not None else version
        await session.rollback()
    return StoredStatement(version=held_version, applied=False)


# --- usage ----------------------------------------------------------------------------


@dataclass(frozen=True)
class UsageOutcome:
    """What a usage report did: the total held, or that it was lower than the
    one held for the period (``decreased``)."""

    quantity: int
    decreased: bool = False


async def record_usage(
    guild_id: int,
    listing_uid: str,
    *,
    meter: str,
    period: str,
    quantity: int,
    as_of: datetime,
) -> UsageOutcome:
    """Keep a period's total for one meter, and pass it on to the issuer.

    A total lower than the one held is refused (``decreased``) and changes
    nothing; an equal or higher one is kept and forwarded. The caller has
    checked the meter against the listing's terms.
    """
    now = datetime.now(UTC)
    insert = pg_insert(PluginUsage).values(
        guild_id=guild_id,
        listing_uid=listing_uid,
        meter=meter,
        period=period,
        quantity=quantity,
        as_of=as_of,
        updated_at=now,
    )
    upsert = insert.on_conflict_do_update(
        index_elements=[
            PluginUsage.guild_id,
            PluginUsage.listing_uid,
            PluginUsage.meter,
            PluginUsage.period,
        ],
        set_={
            "quantity": insert.excluded.quantity,
            "as_of": insert.excluded.as_of,
            "updated_at": insert.excluded.updated_at,
        },
        where=col(PluginUsage.quantity) <= insert.excluded.quantity,
    ).returning(PluginUsage.quantity)
    async with db_session.SystemSessionLocal() as session:
        written = (await session.exec(upsert)).first()
        if written is None:
            held = await session.get(
                PluginUsage, (guild_id, listing_uid, meter, period)
            )
            held_quantity = held.quantity if held is not None else quantity
            await session.rollback()
            return UsageOutcome(quantity=held_quantity, decreased=True)
        await session.commit()
    return UsageOutcome(quantity=quantity)


# --- delivery ---------------------------------------------------------------------------


async def _install_owed(
    guild_id: int, listing_uid: str, version: int
) -> tuple[GuildPlugin, registration_lookup.RegistrationSnapshot] | None:
    """The live install of ``listing_uid`` in ``guild_id`` that has not been
    handed statement ``version``, with its registration, or ``None``."""
    from app.services.tenant.plugin_channels import owns_install

    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id, read_only=True))
        plugin = (
            await session.exec(
                select(GuildPlugin).where(GuildPlugin.listing_uid == listing_uid)
            )
        ).first()
        if plugin is None or not plugin.enabled:
            return None
        registration = await registration_lookup.registration_for_definition(
            plugin.definition, listing_uid=plugin.listing_uid
        )
        if (
            registration is None
            or registration.declarative
            or not registration.live_in(guild_id)
            or not owns_install(plugin, registration)
        ):
            return None
        seen = (
            await session.exec(
                select(PluginHookDelivery.delivery_id).where(
                    PluginHookDelivery.install_id == plugin.id,
                    PluginHookDelivery.delivery_id == _delivery_id(version),
                    PluginHookDelivery.expires_at > datetime.now(UTC),
                )
            )
        ).first()
    return None if seen is not None else (plugin, registration)


def _delivery_id(version: int) -> str:
    return f"{ENTITLEMENT_HOOK}:{version}"


async def _remember(guild_id: int, install_id: int, version: int) -> None:
    expires_at = datetime.now(UTC) + DELIVERY_TTL
    statement = pg_insert(PluginHookDelivery).values(
        install_id=install_id, delivery_id=_delivery_id(version), expires_at=expires_at
    )
    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id))
        await session.exec(
            statement.on_conflict_do_update(
                index_elements=[
                    PluginHookDelivery.install_id,
                    PluginHookDelivery.delivery_id,
                ],
                set_={"expires_at": expires_at},
            )
        )
        await session.commit()


async def deliver_entitlement(guild_id: int, listing_uid: str) -> bool:
    """Hand the installed plug-in the statement held for ``listing_uid`` in
    ``guild_id``, as its ``entitlement`` hook with ``{"statement": "<jws>"}``,
    the signed statement exactly as the issuer sent it.

    Written to the community-hook queue
    (:func:`app.services.marketplace.community_hooks.deliver_community_hook`),
    which delivers it with retries and backoff, replaces a statement still
    waiting with a newer one, and records a 404 as a plug-in that does not take
    the hook. Nothing is queued when there is no statement, no live install,
    or the install was already handed this version. The plug-in can also pull
    the statement whenever it likes. Returns whether it was queued. Never
    raises.
    """
    from app.services.marketplace import community_hooks

    try:
        statement = await read_statement(guild_id, listing_uid)
        if statement is None:
            return False
        owed = await _install_owed(guild_id, listing_uid, statement.version)
        if owed is None:
            return False
        plugin, registration = owed
        queued = await community_hooks.deliver_community_hook(
            guild_id=guild_id,
            public_id=registration.public_id,
            hook=ENTITLEMENT_HOOK,
            body={"statement": statement.jws},
            install_id=plugin.id,
        )
        if queued:
            await _remember(guild_id, int(plugin.id), statement.version)
        return queued
    except Exception:
        logger.exception("plug-in entitlements: delivery for guild %s failed", guild_id)
        return False


# --- the install's lifecycle ------------------------------------------------------------


async def _installed(guild_id: int, listing_uid: str) -> None:
    if await listing_terms(listing_uid) is None:
        return
    await deliver_entitlement(guild_id, listing_uid)


def after_install(session: AsyncSession, guild_id: int, listing_uid: str) -> None:
    """Once ``session`` commits an install of ``listing_uid``: hand the
    plug-in the statement already held for the community. The issuer learns
    of the install from the change log (``app.services.platform.billing_changes``)."""
    post_commit.after_commit(session, lambda: _installed(guild_id, listing_uid))
