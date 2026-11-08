"""Plug-ins calling plug-ins: Initiative is the hub.

An installed plug-in never addresses another plug-in. It asks Initiative, on its own
installation or member token, to call one of the other plug-in's public endpoints
in the same community, and Initiative makes the call the way it makes one for a
widget (:func:`app.services.marketplace.plugin_data._call_plugin`), with a context
token that names the calling plug-in (``act``), whose behalf the call is on
(``actor``), the member by the called plug-in's own reference for them
(``member``), and the initiative the caller is confined to.

The checks, in order, each with its own refusal:

1. the caller's token is live (the install seam, before this module runs);
2. ``plugins:<target>`` is in the token's scopes, the seat's grant and what the
   caller's pinned version requests (``insufficient_scope``);
3. the target is installed, switched on and live in the same community
   (``target_not_installed``);
4. the endpoint is public (``endpoint_not_public``);
5. the endpoint takes the actor: ``installation`` for an installation token,
   ``member`` for a member token (``actor_not_supported``);
6. a caller confined to an initiative finds the target placed there too
   (``target_not_placed``);
7. a member token's member is named to the target by the target's own
   reference, which the caller never sees.

A read goes through the widget path's response cache, keyed also by the
caller, the actor, the member's reference and the initiative. A write is never
cached and never retried.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import or_, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import PluginDataMessages, PluginHubMessages
from app.core.plugin_scopes import plugin_scope
from app.db.guild_standing import ISSUABLE_SCOPES_SQL
from app.db.request_context import SystemGuild
from app.db.session import clear_rls_context, set_rls_context
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.plugin_member_consent import ConsentAccess, PluginMemberConsent
from app.models.tenant.plugin_placement import PluginPlacement
from app.services.marketplace import plugin_data
from app.services.marketplace.plugin_data import CallingPlugin, PluginDataError
from app.services.marketplace.plugin_refs import PluginNameRefused, ensure_plugin_ref
from app.services.marketplace.registration_lookup import RegistrationSnapshot
from app.services.marketplace.service_plugins import is_admin_only
from app.services.tenant.plugin_channels import owns_install

__all__ = [
    "INSTALLATION",
    "MEMBER",
    "HubAnswer",
    "HubCaller",
    "call_plugin",
]

#: The two actors a call can be on behalf of: the community, or one member.
INSTALLATION = "installation"
MEMBER = "member"

#: The directions a caller may invoke. An emission is delivered, not called.
_CALLABLE_DIRECTIONS = frozenset({"read", "write"})


@dataclass(frozen=True)
class HubCaller:
    """The plug-in asking, as its admitted token names it."""

    guild_id: int
    install_id: int
    #: The calling plug-in's public id.
    client_id: str
    token_scopes: frozenset[str]
    #: The initiative the token is confined to, when it is.
    initiative_id: int | None = None
    #: The member a member token acts for, and the purpose they consented to.
    member_user_id: int | None = None
    purpose: str | None = None

    @property
    def actor(self) -> str:
        return MEMBER if self.member_user_id is not None else INSTALLATION


@dataclass(frozen=True)
class HubAnswer:
    """What the plug-in called answered, as it answered it."""

    body: dict[str, Any]
    #: ``read`` or ``write``.
    direction: str
    #: The answer came from the response cache.
    cached: bool = False


_ISSUABLE_SQL_TEXT = (
    f"SELECT {ISSUABLE_SCOPES_SQL} FROM guild_plugins a WHERE a.id = :install_id"
)
_ISSUABLE_SQL = text(_ISSUABLE_SQL_TEXT)


def _refuse(code: str, status_code: int) -> PluginDataError:
    return PluginDataError(code, status_code)


def _callable_endpoint(
    definition: Mapping[str, Any] | None, endpoint_id: str
) -> dict[str, Any] | None:
    """One endpoint of the pinned definition a caller may invoke, or None."""
    return plugin_data.endpoint_by_id(
        definition, endpoint_id, directions=_CALLABLE_DIRECTIONS
    )


async def _target_registration(public_id: str, guild_id: int) -> RegistrationSnapshot:
    """The target's registration, live in community ``guild_id``, or
    ``target_not_installed``."""
    try:
        return await plugin_data._load_registration(public_id, guild_id=guild_id)
    except PluginDataError as exc:
        raise _refuse(PluginHubMessages.TARGET_NOT_INSTALLED, 404) from exc


async def _consent_writes(session: AsyncSession, caller: HubCaller) -> bool:
    """Whether the member a member token acts for let the caller write as
    them, by the consent the token was issued on."""
    consent = (
        await session.exec(
            select(PluginMemberConsent.granted_access).where(
                PluginMemberConsent.install_id == caller.install_id,
                PluginMemberConsent.user_id == caller.member_user_id,
                PluginMemberConsent.purpose.is_not_distinct_from(caller.purpose),
                PluginMemberConsent.granted_access.is_not(None),
                PluginMemberConsent.revoked_at.is_(None),
                or_(
                    PluginMemberConsent.initiative_id.is_(None),
                    PluginMemberConsent.initiative_id == caller.initiative_id,
                ),
            )
        )
    ).first()
    return consent == ConsentAccess.read_write.value


async def _placed(session: AsyncSession, install_id: int, initiative_id: int) -> bool:
    return (
        await session.exec(
            select(PluginPlacement.install_id).where(
                PluginPlacement.install_id == install_id,
                PluginPlacement.initiative_id == initiative_id,
            )
        )
    ).first() is not None


def _hub_cache_key(base: str, caller: HubCaller, member_ref: str | None) -> str:
    """The widget path's key, with everything else the answer may depend on:
    who called, on whose behalf, and where."""
    return (
        f"{base}:hub:{caller.client_id}:{caller.actor}:"
        f"{member_ref or ''}:{caller.initiative_id or ''}"
    )


async def call_plugin(
    session: AsyncSession,
    caller: HubCaller,
    *,
    target_public_id: str,
    endpoint_id: str,
    params: Mapping[str, Any],
    transport: httpx.AsyncBaseTransport | None = None,
) -> HubAnswer:
    """Check one call against checks 2–7 and make it.

    ``session`` is a system-engine session from the caller's community's
    cohort, as ``get_system_session`` hands one to an installation token's
    request. It is routed into that community here, read-only, and left
    unrouted and rolled back afterwards.
    Raises :class:`PluginDataError` with the refusal's code and status.
    """
    scope = plugin_scope(target_public_id)
    if scope not in caller.token_scopes:
        raise _refuse(PluginHubMessages.INSUFFICIENT_SCOPE, 403)

    try:
        await set_rls_context(session, SystemGuild(caller.guild_id, read_only=True))
        # Read now, so a scope the seat has taken back refuses the next call.
        issuable = (
            await session.exec(_ISSUABLE_SQL, params={"install_id": caller.install_id})
        ).scalar_one_or_none()
        if issuable is None or scope not in issuable:
            raise _refuse(PluginHubMessages.INSUFFICIENT_SCOPE, 403)

        registration = await _target_registration(target_public_id, caller.guild_id)
        target = (
            (
                await session.exec(
                    select(GuildPlugin).where(
                        GuildPlugin.listing_uid == registration.listing_uid
                    )
                )
            ).first()
            if registration.listing_uid
            else None
        )
        if (
            target is None
            or target.id == caller.install_id
            or not owns_install(target, registration)
            or not target.enabled
        ):
            raise _refuse(PluginHubMessages.TARGET_NOT_INSTALLED, 404)

        endpoint = _callable_endpoint(target.definition, endpoint_id)
        if endpoint is None:
            raise _refuse(PluginDataMessages.ENDPOINT_NOT_FOUND, 404)
        # An endpoint for the community's admins alone is not offered to plug-ins.
        if endpoint.get("public") is not True or is_admin_only(endpoint):
            raise _refuse(PluginHubMessages.ENDPOINT_NOT_PUBLIC, 403)

        actors = endpoint.get("actors")
        if caller.actor not in (actors if isinstance(actors, list) else []):
            raise _refuse(PluginHubMessages.ACTOR_NOT_SUPPORTED, 403)
        direction = str(endpoint["direction"])
        if (
            caller.actor == MEMBER
            and direction == "write"
            and not await _consent_writes(session, caller)
        ):
            raise _refuse(PluginHubMessages.INSUFFICIENT_SCOPE, 403)

        if caller.initiative_id is not None and not await _placed(
            session, int(target.id or 0), caller.initiative_id
        ):
            raise _refuse(PluginHubMessages.TARGET_NOT_PLACED, 403)

        values, canonical = plugin_data.validate_params(
            endpoint, json.dumps(dict(params)) if params else None
        )
        refs, fields = await plugin_data._resolve_connections(
            session,
            plugin=target,
            endpoint=endpoint,
            user_id=caller.member_user_id,
            actor=caller.actor,
        )
    finally:
        # What was read stays readable once the transaction ends.
        session.expunge_all()
        clear_rls_context(session)
        await session.rollback()

    member_user_id = caller.member_user_id
    try:
        member_ref = (
            await ensure_plugin_ref(
                guild_id=caller.guild_id,
                public_id=registration.public_id,
                user_id=member_user_id,
            )
            if member_user_id is not None
            else None
        )
    except PluginNameRefused as exc:
        raise _refuse(PluginHubMessages.TARGET_NOT_INSTALLED, 404) from exc
    calling = CallingPlugin(
        public_id=caller.client_id,
        actor=caller.actor,
        member_ref=member_ref,
        initiative_id=caller.initiative_id,
    )

    async def read(request: httpx.Request | plugin_data.Answered) -> dict[str, Any]:
        return await plugin_data._read_body(request, transport=transport)

    async def call() -> dict[str, Any]:
        return await plugin_data._call_plugin(
            registration=registration,
            plugin=target,
            guild_id=caller.guild_id,
            endpoint_id=endpoint_id,
            params=values,
            refs=refs,
            fields=fields,
            transport=transport,
            read=read,
            caller=calling,
        )

    if direction != "read":
        return HubAnswer(body=await call(), direction=direction)

    key = _hub_cache_key(
        plugin_data._cache_key(
            guild_id=caller.guild_id,
            plugin=target,
            endpoint_id=endpoint_id,
            canonical_params=canonical,
            refs=refs,
            fields=fields,
        ),
        caller,
        member_ref,
    )
    body, cached = await plugin_data.cached_call(
        key, plugin_data._effective_ttl(endpoint), call
    )
    return HubAnswer(body=body, direction=direction, cached=cached)
