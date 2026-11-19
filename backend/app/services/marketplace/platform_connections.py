"""Community connections the platform connects once, for every community.

A plug-in's community connection (GitHub's organization, say) is ordinarily
made in each community, by its seat. The operator may instead connect one
for every community from the plug-in's registration: the flow is the
community connection's own (:mod:`app.services.tenant.plugin_connection_flows`),
and what it answers is kept on the registration, in ``platform_connections``,
by connection id::

    {"values": {...as a community's stored connection holds them...},
     "connected_by": <user id>, "connected_at": <ISO time>,
     "checked_at": <ISO time>, "failures": <int>}

Every community with the plug-in then reads that connection as the
platform's, in place of its own (:func:`~app.services.tenant.plugin_config.
platform_held`), and connects or disconnects it no more. A community's own
stored values are left where they are, and read again once the platform
disconnects.

Only a connection Initiative runs from end to end can be connected so
(:func:`for_platform`): a declarative plug-in's community connection with a
flow and a token minted from the vendor values, and no secret field. It holds
nothing secret of its own, so its values are kept in the plain.

Its health is checked once for every community, by :func:`check_health`, on
the connection's own ``health.every``, and a vendor's report that the account
was removed or restored is written here (:func:`set_state`), not in any
community.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.capabilities import Capability, user_has_capability
from app.core.clock import utcnow
from app.core.messages import PluginServiceMessages
from app.db import session as db_session
from app.models.platform.plugin_service_registration import (
    PluginServiceRegistration,
    RegistrationKind,
)
from app.models.platform.user import User
from app.services import audit as audit_service
from app.services.marketplace import registration_lookup
from app.services.marketplace.service_plugins import schedule_minutes
from app.services.marketplace.vendor_values import listing_definitions
from app.services.tenant import plugin_config as plugin_config_service

logger = logging.getLogger(__name__)

__all__ = [
    "HEALTH_CHECK_SECONDS",
    "PlatformFlow",
    "check_health",
    "disconnect",
    "for_platform",
    "load",
    "may_connect",
    "set_state",
    "store",
    "views",
]

#: How often the worker looks for a platform connection whose check is due.
HEALTH_CHECK_SECONDS = 60


def for_platform(
    definition: Mapping[str, Any] | None, connection_id: str
) -> dict[str, Any] | None:
    """The connection, when the platform can connect it for every community:
    a declarative plug-in's community connection with a flow, whose token is
    minted from the vendor values, and that declares no secret field."""
    if not registration_lookup.is_declarative(definition):
        return None
    connection = plugin_config_service.connection_by_id(definition, connection_id)
    if (
        connection is None
        or connection.get("scope") != "static"
        or not isinstance(connection.get("flow"), dict)
        or (plugin_config_service.token_of(connection) or {}).get("type")
        != "jwt_bearer"
        or any(
            isinstance(field, dict) and field.get("type") == "secret"
            for field in connection.get("fields") or []
        )
    ):
        return None
    return connection


@dataclass(frozen=True)
class PlatformFlow:
    """What the platform's flow for one connection runs with."""

    public_id: str
    #: The listing's latest definition.
    definition: dict[str, Any]
    connection: dict[str, Any]
    flow: dict[str, Any]
    #: The connection's values as the platform holds them now, or none.
    fields: dict[str, Any]


async def load(public_id: str | None, connection_id: str) -> PlatformFlow | None:
    """The flow of a connection the platform can connect for every
    community, on a live registration, or ``None``."""
    snapshot = (await registration_lookup.load_registrations()).get(public_id or "")
    if snapshot is None or not snapshot.live or not snapshot.declarative:
        return None
    async with db_session.SystemSessionLocal() as session:
        definition = (await listing_definitions(session, [snapshot.listing_uid])).get(
            snapshot.listing_uid or ""
        )
    connection = for_platform(definition, connection_id)
    if definition is None or connection is None:
        return None
    return PlatformFlow(
        public_id=snapshot.public_id,
        definition=definition,
        connection=connection,
        flow=connection["flow"],
        fields=plugin_config_service.without_tokens(
            snapshot.platform_connections.get(connection_id)
        ),
    )


def _connection_ids(definition: Mapping[str, Any] | None) -> list[str]:
    return [
        str(connection["id"])
        for connection in plugin_config_service.definition_connections(definition)
        if for_platform(definition, str(connection.get("id"))) is not None
    ]


def views(
    row: PluginServiceRegistration, definition: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    """Each connection of the listing's latest version the platform can
    connect, and what it connected, for the operator's page."""
    stored = row.platform_connections or {}
    out = []
    for connection_id in _connection_ids(definition):
        connection = plugin_config_service.connection_by_id(definition, connection_id)
        entry = stored.get(connection_id) or {}
        values = entry.get("values") or {}
        connected_at = entry.get("connected_at")
        out.append(
            {
                "connection_id": connection_id,
                "label": (connection or {}).get("label") or {},
                "connected": bool(values),
                "account_label": values.get(plugin_config_service.ACCOUNT_LABEL),
                "connected_at": datetime.fromisoformat(connected_at)
                if isinstance(connected_at, str)
                else None,
                "removed": plugin_config_service.REMOVED_AT in values,
            }
        )
    return out


async def may_connect(user_id: int) -> bool:
    """Whether the person may still connect for every community: what the
    plug-in services page asks of them."""
    async with db_session.SystemSessionLocal() as session:
        user = await session.get(User, user_id)
    return user is not None and user_has_capability(user, Capability.PLUGINS_MANAGE)


async def _locked(session: AsyncSession, public_id: str) -> PluginServiceRegistration:
    row = (
        await session.exec(
            select(PluginServiceRegistration)
            .where(PluginServiceRegistration.public_id == public_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=PluginServiceMessages.NOT_FOUND,
        )
    return row


async def _write(
    session: AsyncSession,
    row: PluginServiceRegistration,
    entries: dict[str, Any],
    *,
    audit: dict[str, Any] | None,
    actor_user_id: int | None,
) -> None:
    row.platform_connections = entries
    row.updated_at = utcnow()
    session.add(row)
    if audit is not None:
        await audit_service.record(
            session,
            event_type=AuditEventType.PLUGIN_SERVICE_UPDATED,
            actor_user_id=actor_user_id,
            target_type="plugin_service_registration",
            target_id=row.id,
            detail={"platform_connection": audit},
        )
    await session.commit()
    registration_lookup.invalidate_registrations()


async def store(
    public_id: str,
    connection_id: str,
    *,
    values: Mapping[str, Any],
    account_label: str | None,
    actor_user_id: int,
) -> str:
    """Keep what a platform connection's flow answered, for every community.
    Answers the landing outcome: ``not_recorded`` when the registration no
    longer declares the connection for the platform, or the values do not
    fit it."""
    async with db_session.SystemSessionLocal() as session:
        row = await _locked(session, public_id)
        definition = (await listing_definitions(session, [row.listing_uid])).get(
            row.listing_uid or ""
        )
        connection = for_platform(definition, connection_id)
        if connection is None:
            return "not_recorded"
        managed = {
            str(field["key"])
            for field in connection.get("fields") or []
            if isinstance(field, dict) and field.get("managed") is True
        }
        try:
            config, _ = plugin_config_service.apply_connection_values(
                connection,
                {key: value for key, value in values.items() if key in managed},
                current={},
                current_secrets={},
                allow_managed=True,
            )
        except plugin_config_service.PluginConfigError as exc:
            logger.warning(
                "platform connection: %s's values for %s refused (%s)",
                public_id,
                connection_id,
                exc.code,
            )
            return "not_recorded"
        if account_label:
            config[plugin_config_service.ACCOUNT_LABEL] = account_label
        entries = dict(row.platform_connections or {})
        entries[connection_id] = {
            "values": config,
            "connected_by": actor_user_id,
            "connected_at": utcnow().isoformat(),
        }
        await _write(
            session,
            row,
            entries,
            audit={
                "connection_id": connection_id,
                "connected": True,
                "account_label": account_label,
            },
            actor_user_id=actor_user_id,
        )
    return "connected"


async def disconnect(
    session: AsyncSession,
    registration_id: int,
    connection_id: str,
    *,
    actor_user_id: int,
) -> PluginServiceRegistration:
    """End a platform connection: every community reads its own again."""
    row = (
        await session.exec(
            select(PluginServiceRegistration)
            .where(PluginServiceRegistration.id == registration_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=PluginServiceMessages.NOT_FOUND,
        )
    entries = dict(row.platform_connections or {})
    if entries.pop(connection_id, None) is not None:
        await _write(
            session,
            row,
            entries,
            audit={"connection_id": connection_id, "connected": False},
            actor_user_id=actor_user_id,
        )
    return row


async def set_state(
    public_id: str, connection_id: str, state: str, *, about: Mapping[str, Any]
) -> None:
    """Write what the vendor said of a platform connection's account: marked
    removed on ``removed``, unmarked on ``ok``. Any other state leaves it, and
    so does a report ``about`` an account the connection no longer holds: the
    values it was read for, each compared as text."""
    if state not in ("ok", "removed"):
        return
    async with db_session.SystemSessionLocal() as session:
        row = await _locked(session, public_id)
        entries = dict(row.platform_connections or {})
        entry = entries.get(connection_id)
        if not isinstance(entry, dict) or not isinstance(entry.get("values"), dict):
            return
        values = dict(entry["values"])
        if any(str(values.get(key)) != str(value) for key, value in about.items()):
            return
        removed = state == "removed"
        if (plugin_config_service.REMOVED_AT in values) == removed:
            return
        values.pop(plugin_config_service.REMOVED_AT, None)
        if removed:
            values[plugin_config_service.REMOVED_AT] = int(utcnow().timestamp())
        entries[connection_id] = {**entry, "values": values}
        await _write(session, row, entries, audit=None, actor_user_id=None)


async def _due(now: datetime) -> list[tuple[str, str, dict, dict[str, Any]]]:
    """Each platform connection whose check is due: its registration's
    public id, the connection id, its health and its values."""
    async with db_session.SystemSessionLocal() as session:
        rows = (
            await session.exec(
                select(PluginServiceRegistration).where(
                    PluginServiceRegistration.kind == RegistrationKind.DECLARATIVE
                )
            )
        ).all()
        live = await registration_lookup.load_registrations()
        # A suspended plug-in, or one whose publisher is switched off, calls
        # no vendor.
        rows = [
            row
            for row in rows
            if row.platform_connections
            and (snapshot := live.get(row.public_id)) is not None
            and snapshot.live
        ]
        definitions = await listing_definitions(
            session, [row.listing_uid for row in rows]
        )
    due = []
    for row in rows:
        definition = definitions.get(row.listing_uid or "")
        for connection_id, entry in (row.platform_connections or {}).items():
            connection = for_platform(definition, connection_id)
            health = (connection or {}).get("health")
            if not isinstance(health, dict) or not isinstance(entry, dict):
                continue
            checked = entry.get("checked_at")
            every = timedelta(minutes=schedule_minutes(health["every"]))
            if (
                isinstance(checked, str)
                and datetime.fromisoformat(checked) + every > now
            ):
                continue
            due.append((row.public_id, connection_id, health, entry))
    return due


async def check_health() -> None:
    """Check each platform connection whose check is due, once for every
    community: ``ok`` is written at once, any other state once two checks
    in a row have read it."""
    from app.services.marketplace import declarative
    from app.services.tenant import plugin_connection_flows as flows

    now = datetime.now(UTC)
    for public_id, connection_id, health, entry in await _due(now):
        async with db_session.SystemSessionLocal() as session:
            row = await _locked(session, public_id)
            held = (row.platform_connections or {}).get(connection_id)
            if held != entry:
                # Connected again, or checked by another process meanwhile.
                continue
            entries = dict(row.platform_connections)
            entries[connection_id] = {**entry, "checked_at": now.isoformat()}
            await _write(session, row, entries, audit=None, actor_user_id=None)
            definition = (await listing_definitions(session, [row.listing_uid])).get(
                row.listing_uid or ""
            )
        fields = plugin_config_service.without_tokens(entry["values"])
        try:
            token = await flows.platform_token(
                public_id, for_platform(definition, connection_id) or {}, fields
            )
            async with asyncio.timeout(declarative.REQUEST_TIMEOUT_SECONDS):
                state = await declarative.health_state(
                    definition,
                    health,
                    fields=fields,
                    access_token=token.access_token,
                    installed={"settings": {}, "aliases": {}},
                )
        except (flows.ConnectionFlowError, TimeoutError) as exc:
            logger.info(
                "platform connection: %s could not check %s (%s)",
                public_id,
                connection_id,
                type(exc).__name__,
            )
            state = "unavailable"
        failures = 0 if state == "ok" else int(entry.get("failures") or 0) + 1
        async with db_session.SystemSessionLocal() as session:
            row = await _locked(session, public_id)
            current = (row.platform_connections or {}).get(connection_id)
            if (
                not isinstance(current, dict)
                or current.get("values") != entry["values"]
            ):
                continue
            entries = dict(row.platform_connections)
            entries[connection_id] = {**current, "failures": failures}
            await _write(session, row, entries, audit=None, actor_user_id=None)
        if state == "ok" or failures >= 2:
            await set_state(public_id, connection_id, state, about=fields)
