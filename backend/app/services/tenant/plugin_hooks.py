"""A vendor's webhooks, received for the plug-in that declares them.

A plug-in whose manifest declares ``webhooks`` has one address on this
deployment, ``POST /api/v1/plugin-hooks/{public_id}``, which the operator gives
the vendor. :func:`receive` takes each delivery through four steps:

1. The signature is checked with the registration's vendor secret. A delivery
   that does not verify is refused (401).
2. The route value is read from the delivery wherever a version of the
   listing's ``webhooks.route`` reads it (a path in the JSON body, or a
   header), and each value is matched against the install index
   (:func:`plugin_installs.routed`). An install is matched only when the route
   of the version it is pinned to reads its value. A delivery nothing matches
   is answered 202 and nothing is stored.
3. For each matched install, read as the version it is pinned to, the delivery
   is queued in its community (``plugin_hook_deliveries``) by the vendor's
   delivery id, with its body and the vendor's ``x-`` headers; a copy already
   there, or one the install has had in the last 24 hours, is left as it is.
   The write arms the community's delivery sweep, and the vendor is answered
   202. Whether the install is on is the install row's answer, read here,
   not the index's, which a sweep brings up to date.
4. The sweep's visit (:func:`run_due`) takes each waiting delivery in turn, as
   the version the install is pinned to. A container's install has the body
   and headers sent to its ``webhook`` hook with a ``lifecycle`` token naming
   that install. A declarative plug-in's install maps it with its ``events``
   and ``status``: the changes to its values are made as the install, the
   event goes to the outbox as a container's emission does, and the state to
   the install's configuration state. Work that may succeed if tried again
   waits, a little longer each time; a mapping that cannot succeed is logged.
   Either way the id stays remembered for 24 hours.

The index row that routes a delivery is written only when a community's
connect stored the routed value, which the plug-in's ``after_connect`` hook
checked at the vendor.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Mapping, Optional

from sqlalchemy import func, or_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Row
from sqlmodel import col, delete, select

from app.core import metrics
from app.db import cohorts
from app.db import session as db_session
from app.db.request_context import SystemGuild
from app.db.session import set_rls_context
from app.models.platform.marketplace import (
    MarketplaceListing,
    MarketplaceListingVersion,
)
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.plugin_hook_delivery import (
    DELIVERY_ID_MAX_LENGTH,
    PluginHookDelivery,
)
from app.services.marketplace import (
    community_hooks,
    declarative,
    plugin_installs,
    registration_lookup,
)
from app.services.marketplace.expressions import ExpressionError
from app.services.marketplace.registration_lookup import (
    RegistrationSnapshot,
    is_declarative,
)
from app.services.marketplace.vendor_values import (
    listing_definitions,
    load_vendor_values,
)
from app.services.tenant import guild_plugins as guild_plugins_service
from app.services.tenant import plugin_connection_flows as flows
from app.services.tenant import metadata
from app.services.tenant.plugin_channels import (
    PluginChannelError,
    keep_event,
    owns_install,
    set_connection_state,
)
from app.services.tenant.plugin_config import install_settings, without_tokens

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.services.tenant.expiry import Expiring

logger = logging.getLogger(__name__)

__all__ = ["DELIVERY_TTL", "expire_deliveries", "next_due", "receive", "run_due"]

#: How long a delivery id is remembered once its work is done.
DELIVERY_TTL = timedelta(hours=24)
#: How long a visit holds a delivery while it is mapped or forwarded; one
#: whose visit stopped without finishing is taken again after it.
DELIVERY_LEASE = timedelta(minutes=5)
#: How long a delivery whose work failed waits to be tried again: this,
#: doubled for each failure.
RETRY_AFTER = timedelta(minutes=1)
#: How many times a delivery's work is tried before it is given up.
ATTEMPTS = 8

_DIGESTS = {"hmac_sha256": hashlib.sha256, "hmac_sha1": hashlib.sha1}


def _verified(
    verify: Mapping[str, Any], secret: str, headers: Mapping[str, str], body: bytes
) -> bool:
    """Whether the signature header holds the HMAC of ``body`` under
    ``secret``, as the manifest writes it."""
    digest_of = _DIGESTS.get(str(verify.get("scheme")))
    given = headers.get(str(verify.get("header", "")).lower(), "")
    prefix = str(verify.get("prefix") or "")
    if digest_of is None or not given.startswith(prefix):
        return False
    digest = hmac.new(secret.encode("utf-8"), body, digest_of).digest()
    expected = (
        digest.hex()
        if verify.get("encoding") == "hex"
        else base64.b64encode(digest).decode("ascii")
    )
    return hmac.compare_digest(
        expected.encode("utf-8"), given[len(prefix) :].strip().encode("utf-8")
    )


def _route_value(
    route: Mapping[str, Any], headers: Mapping[str, str], body: bytes
) -> Optional[str]:
    """The value a ``webhooks.route`` reads from a delivery, as the install
    index stores it, or ``None``: the header it names, or the value at its
    ``path`` (keys joined by ``.``) in the JSON body."""
    if "header" in route:
        return headers.get(str(route["header"]).lower()) or None
    try:
        value: Any = json.loads(body)
    except ValueError:
        return None
    for key in str(route.get("path") or "").split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    return str(value) or None


def _vendor_headers(headers: Mapping[str, str], signature: str) -> dict[str, str]:
    """The vendor's own ``x-`` headers, without the signature and the proxy's."""
    return {
        name: value
        for name, value in headers.items()
        if name.startswith("x-")
        and not name.startswith("x-forwarded-")
        and name not in {"x-real-ip", signature.lower()}
    }


async def _webhooks(registration: RegistrationSnapshot) -> Optional[dict[str, Any]]:
    """The ``webhooks`` block of the listing's current definition, which
    checks and routes a delivery before any install is known."""
    async with db_session.SystemSessionLocal() as session:
        definitions = await listing_definitions(session, [registration.listing_uid])
    webhooks = definitions.get(registration.listing_uid or "", {}).get("webhooks")
    return webhooks if isinstance(webhooks, dict) else None


def _route_spec(route: Any) -> Optional[tuple[str, str]]:
    """Where a ``webhooks.route`` reads its value: a header, or a body path."""
    if not isinstance(route, Mapping):
        return None
    if isinstance(route.get("header"), str):
        return ("header", route["header"].lower())
    if isinstance(route.get("path"), str):
        return ("path", route["path"])
    return None


async def _route_specs(listing_uid: str) -> set[tuple[str, str]]:
    """Every place a version of the listing reads its route value from: an
    install is pinned to one of them."""
    route = col(MarketplaceListingVersion.definition)["webhooks"]["route"]
    async with db_session.SystemSessionLocal() as session:
        rows = (
            await session.exec(
                select(route)
                .join(
                    MarketplaceListing,
                    col(MarketplaceListing.id) == MarketplaceListingVersion.listing_id,
                )
                .where(MarketplaceListing.uid == listing_uid)
                .distinct()
            )
        ).all()
    return {spec for row in rows if (spec := _route_spec(row)) is not None}


async def _routed(
    listing_uid: str,
    specs: set[tuple[str, str]],
    headers: Mapping[str, str],
    body: bytes,
) -> list[plugin_installs.IndexedInstall]:
    """The installs a delivery's route values name, one index lookup for each
    value the listing's versions read from it."""
    values = {
        value
        for kind, where in specs
        if (value := _route_value({kind: where}, headers, body)) is not None
    }
    found: dict[tuple[int, int], plugin_installs.IndexedInstall] = {}
    for value in sorted(values):
        for install in await plugin_installs.routed(listing_uid, value):
            found.setdefault((install.guild_id, install.install_id), install)
    return [found[key] for key in sorted(found)]


async def _queue(
    install: plugin_installs.IndexedInstall,
    registration: RegistrationSnapshot,
    delivery_id: str,
    *,
    headers: Mapping[str, str],
    body: bytes,
) -> None:
    """Queue a delivery for an install it is owed to: as it is pinned, the
    install is on, the registration's, and routes by the value the delivery
    was found by. A copy already there, or one the install has had, is left
    as it is. One system session routed into the community, whose write arms
    the delivery sweep."""
    async with cohorts.system_session(install.guild_id) as session:
        await set_rls_context(session, SystemGuild(install.guild_id))
        plugin = (
            await session.exec(
                select(GuildPlugin).where(GuildPlugin.id == install.install_id)
            )
        ).first()
        if (
            plugin is None
            or not plugin.enabled
            or not owns_install(plugin, registration)
        ):
            return
        pinned = (plugin.definition or {}).get("webhooks")
        indexed = plugin_installs.hook_route(plugin.definition, plugin.config)
        if (
            not isinstance(pinned, dict)
            or indexed is None
            or _route_value(pinned["route"], headers, body) != indexed
        ):
            return
        now = datetime.now(timezone.utc)
        await session.exec(
            pg_insert(PluginHookDelivery)
            .values(
                install_id=install.install_id,
                delivery_id=delivery_id,
                expires_at=now + DELIVERY_TTL,
                received_at=now,
                body=body,
                headers=_vendor_headers(headers, str(pinned["verify"]["header"])),
                route=install.route,
            )
            .on_conflict_do_nothing()
        )
        await session.commit()


async def expire_deliveries(session: AsyncSession, expiring: Expiring) -> None:
    """Forget the delivery ids whose 24 hours have run out. One still waiting
    for its work is kept, however long it has waited."""
    await session.exec(
        delete(PluginHookDelivery).where(  # type: ignore[arg-type]
            col(PluginHookDelivery.expires_at) < expiring.now,
            col(PluginHookDelivery.body).is_(None),
        )
    )


def _waiting(now: datetime) -> list[Any]:
    """The conditions of a delivery still waiting for its work."""
    return [col(PluginHookDelivery.body).is_not(None)]


def next_due(now: datetime) -> Any:
    """When the community's next waiting delivery is due: now, or when the
    visit holding it lets go."""
    return select(func.min(func.coalesce(PluginHookDelivery.taken_until, now))).where(
        *_waiting(now)
    )


async def _claim(session: AsyncSession) -> Optional[Row]:
    """Hold the community's oldest waiting delivery no visit holds, or
    return ``None``."""
    now = datetime.now(timezone.utc)
    due = (
        select(PluginHookDelivery.install_id, PluginHookDelivery.delivery_id)
        .where(
            *_waiting(now),
            or_(
                col(PluginHookDelivery.taken_until).is_(None),
                col(PluginHookDelivery.taken_until) <= now,
            ),
        )
        .order_by(col(PluginHookDelivery.received_at))
        .limit(1)
        .with_for_update(skip_locked=True)
        .cte("due")
    )
    result = await session.exec(
        update(PluginHookDelivery)
        .where(
            col(PluginHookDelivery.install_id) == due.c.install_id,
            col(PluginHookDelivery.delivery_id) == due.c.delivery_id,
        )
        .values(taken_until=now + DELIVERY_LEASE)
        .returning(
            PluginHookDelivery.install_id,
            PluginHookDelivery.delivery_id,
            PluginHookDelivery.body,
            PluginHookDelivery.headers,
            PluginHookDelivery.route,
            PluginHookDelivery.attempts,
        )
    )
    claimed = result.first()
    await session.commit()
    return claimed


async def _settle(session: AsyncSession, row: Row, *, done: bool) -> None:
    """Settle a held delivery, committing it with whatever its work staged
    on ``session``. Done, its body goes and its id stays remembered for
    :data:`DELIVERY_TTL` from now; otherwise it waits :data:`RETRY_AFTER`,
    doubled for each failure, and is given up after :data:`ATTEMPTS`."""
    attempts = row.attempts if done else row.attempts + 1
    if not done and attempts >= ATTEMPTS:
        logger.warning(
            "plug-in hooks: delivery %s for install %s was given up after %s tries",
            row.delivery_id,
            row.install_id,
            attempts,
        )
        done = True
    values: dict[str, Any] = (
        {
            "body": None,
            "taken_until": None,
            "attempts": attempts,
            "expires_at": datetime.now(timezone.utc) + DELIVERY_TTL,
        }
        if done
        else {
            "attempts": attempts,
            "taken_until": datetime.now(timezone.utc)
            + RETRY_AFTER * 2 ** (attempts - 1),
        }
    )
    await session.exec(
        update(PluginHookDelivery)
        .where(
            col(PluginHookDelivery.install_id) == row.install_id,
            col(PluginHookDelivery.delivery_id) == row.delivery_id,
        )
        .values(**values)
    )
    await session.commit()


async def run_due(session: AsyncSession, guild_id: int) -> Optional[datetime]:
    """Map or forward each of the community's waiting deliveries, on a session
    routed into it, as the version each install is pinned to, and answer
    when the next comes due. A delivery whose install is gone, off, no
    longer the registration's, or no longer routing by the value it came by
    (the community connected another installation since) is dropped, its id
    remembered. What a delivery emits and sets is committed with its
    settlement, so a visit that stops leaves it waiting whole."""
    live = {
        registration.listing_uid: registration
        for registration in (await registration_lookup.load_registrations()).values()
        if registration.live_in(guild_id) and registration.listing_uid
    }
    while (row := await _claim(session)) is not None:
        plugin = await session.get(GuildPlugin, row.install_id, populate_existing=True)
        registration = live.get(plugin.listing_uid or "") if plugin else None
        pinned = (plugin.definition or {}).get("webhooks") if plugin else None
        if (
            plugin is None
            or registration is None
            or not isinstance(pinned, dict)
            or not plugin.enabled
            or not owns_install(plugin, registration)
            or plugin_installs.hook_route(plugin.definition, plugin.config) != row.route
        ):
            await _settle(session, row, done=True)
            continue
        # Nothing is held here while the install's own sessions do the work.
        await session.commit()
        install = plugin_installs.IndexedInstall(
            guild_id=guild_id, install_id=row.install_id, active=True, route=row.route
        )
        # A declarative registration has no hook to forward to, whatever
        # version an install is still pinned to.
        declared = registration.declarative or is_declarative(plugin.definition)
        hand = _map if declared else _forward
        try:
            done = await hand(
                session,
                install,
                registration,
                plugin,
                pinned,
                delivery_id=row.delivery_id,
                headers=dict(row.headers or {}),
                body=bytes(row.body),
            )
        except Exception:
            logger.exception(
                "plug-in hooks: delivery %s for guild %s failed; it waits",
                row.delivery_id,
                guild_id,
            )
            await session.rollback()
            done = False
        await _settle(session, row, done=done)
    return (await session.exec(next_due(datetime.now(timezone.utc)))).first()


async def _forward(
    session: AsyncSession,
    install: plugin_installs.IndexedInstall,
    registration: RegistrationSnapshot,
    plugin: GuildPlugin,
    webhooks: Mapping[str, Any],
    *,
    delivery_id: str,
    headers: Mapping[str, str],
    body: bytes,
) -> bool:
    """A container's install: the delivery goes to its ``webhook`` hook, as
    its pinned ``webhooks`` describe it. Whether it was accepted."""
    try:
        await community_hooks.call_now(
            "webhook",
            public_id=registration.public_id,
            base_url=registration.base_url,
            guild_id=install.guild_id,
            install_id=install.install_id,
            body={
                "connection": webhooks["route"]["connection"],
                "headers": dict(headers),
                "body": body.decode("utf-8", errors="replace"),
            },
        )
    except flows.HookError as exc:
        logger.warning(
            "plug-in hooks: %s did not accept delivery %s for guild %s (%s)",
            registration.public_id,
            delivery_id,
            install.guild_id,
            exc,
        )
        return False
    return True


async def _map(
    session: AsyncSession,
    install: plugin_installs.IndexedInstall,
    registration: RegistrationSnapshot,
    plugin: GuildPlugin,
    webhooks: Mapping[str, Any],
    *,
    delivery_id: str,
    headers: Mapping[str, str],
    body: bytes,
) -> bool:
    """A declarative plug-in's install: its pinned ``webhooks`` map the delivery
    to changes to the plug-in's values, made as the install
    (:func:`metadata.apply_changes`), to an event, emitted as a
    container's is, and to a connection's state. Whether it is done: a
    mapping that may answer if asked again is not, and waits; one that
    cannot, and changes that are refused, are logged and done."""
    try:
        payload: Any = json.loads(body)
    except ValueError:
        payload = None
    route = webhooks["route"]
    try:
        delivered = await declarative.map_delivery(
            plugin.definition,
            headers=headers,
            payload=payload,
            connection=without_tokens((plugin.config or {}).get(route["connection"])),
            installed=install_settings(plugin),
        )
    except ExpressionError as exc:
        logger.warning(
            "plug-in hooks: %s will map delivery %s for guild %s again (%s)",
            registration.public_id,
            delivery_id,
            install.guild_id,
            type(exc).__name__,
        )
        return False
    for failure in delivered.failures:
        logger.warning(
            "plug-in hooks: %s could not map delivery %s for guild %s (%s)",
            registration.public_id,
            delivery_id,
            install.guild_id,
            failure,
        )
    try:
        await metadata.apply_changes(
            plugin, registration, delivered.writes, guild_id=install.guild_id
        )
    except PluginChannelError as exc:
        logger.warning(
            "plug-in hooks: %s could not make the changes of delivery %s for "
            "guild %s (%s)",
            registration.public_id,
            delivery_id,
            install.guild_id,
            exc.code,
        )
    if delivered.event is not None:
        event_type, event = delivered.event
        try:
            await keep_event(
                session,
                plugin,
                registration,
                event_type=event_type,
                payload=event,
                initiative_id=None,
            )
        except PluginChannelError as exc:
            logger.warning(
                "plug-in hooks: %s emitted %s from delivery %s for guild %s, "
                "which was refused (%s)",
                registration.public_id,
                event_type,
                delivery_id,
                install.guild_id,
                exc.code,
            )
    if delivered.status is not None:
        locked = await guild_plugins_service.lock_install(session, plugin.id)
        if (
            locked is not None
            and plugin_installs.hook_route(locked.definition, locked.config)
            == install.route
            and set_connection_state(locked, *delivered.status)
        ):
            session.add(locked)
    return True


async def receive(public_id: str, headers: Mapping[str, str], body: bytes) -> int:
    """Take one vendor delivery for ``public_id`` and answer its status.

    ``headers`` are the request's, with lowercased names.
    """
    registration = (await registration_lookup.load_registrations()).get(public_id)
    if registration is None or not registration.live or not registration.listing_uid:
        return 404
    webhooks = await _webhooks(registration)
    if webhooks is None:
        return 404
    verify = webhooks["verify"]
    key = str(verify["secret"])[len("{vendor.") : -1]
    secret = (await load_vendor_values(public_id)).get(key)
    if not secret or not _verified(verify, secret, headers, body):
        metrics.plugin_hook_deliveries.labels(outcome="refused").inc()
        return 401

    specs = await _route_specs(registration.listing_uid)
    current = _route_spec(webhooks["route"])
    if current is not None:
        specs.add(current)
    installs = [
        install
        for install in await _routed(registration.listing_uid, specs, headers, body)
        if registration.serves(install.guild_id)
    ]
    if not installs:
        metrics.plugin_hook_deliveries.labels(outcome="unroutable").inc()
        return 202

    delivery_id = headers.get(str(webhooks["dedup"]).lower(), "")
    if not delivery_id or len(delivery_id) > DELIVERY_ID_MAX_LENGTH:
        return 400
    for install in installs:
        await _queue(install, registration, delivery_id, headers=headers, body=body)
    metrics.plugin_hook_deliveries.labels(outcome="queued").inc()
    return 202
