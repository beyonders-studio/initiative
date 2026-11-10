"""Minting a plug-in's page handoff.

A page is a cross-origin iframe, so the token that bootstraps it crosses a
trust boundary: the plug-in verifies it against the published public half of the
plug-in platform's own keypair. That is why it is EdDSA with a dedicated key, why
the audience names one registration, and why the lifetime is a minute.

**Authorization is settled here, before a token exists.** The member's real
session decides whether the surface may be opened at all — the install must be
enabled, its plug-in service must be registered and live, the manifest must declare
that surface, and the community's own roles must admit the caller: inside an
initiative, the install is placed there and the caller's role holds the
permission the surface names, as a tool's permissions are held; at the
community level, the caller holds it as an admin surface is held. A plug-in
never has to make that decision, and never sees a request from somebody who
failed it.

**The token carries the minimum.** Guild and its status, install, surface, who is opening it,
whether they administer the community, and — where the surface was opened
inside an initiative — which one and whether they moderate it. Nothing about
their name or their address, and no other role. What a plug-in may do with a person is a function of what the
manifest declared and the guild accepted, not of anything it can read out of a
claim set.

The claims a plug-in receives:

* ``sub`` — the member, by the reference this plug-in knows them by in the
  community, which a reinstall keeps;
* ``community_ref`` — the community, by the reference this plug-in knows it by;
* ``community_status`` — where the community stands now;
* ``plugin_install_id`` and ``surface_id`` — which install and which surface;
* ``community_admin`` — ``true`` when the viewer administers the community, read
  from the same standing that decided whether they may open the surface. A
  plug-in uses it to shape its own screens, such as showing community-level
  settings; it is not a grant, and every call the plug-in makes to Initiative is
  still decided by that call's own token;
* ``initiative_id`` — present only when the surface was opened inside an
  initiative;
* ``initiative_moderator`` — present with ``initiative_id``: ``true`` when the
  viewer's role there manages it with "Full access", as a moderator's does. A
  plug-in uses it the way it uses ``community_admin``, such as to let only a
  moderator set something up that acts with a moderator's standing;
* ``permissions`` — the ids of the plug-in's permissions the viewer holds
  where the surface was opened, at that level, ``use`` among them. A plug-in
  shapes its pages by them; like ``community_admin``, they are not a grant;
* ``jti``, ``iat``, ``exp``, ``iss`` and ``aud`` — the envelope.

**Where a surface was opened is the route's to say.** A surface declares the
scopes it renders in, and the caller names none of them: the initiative in the
token is the one whose route was taken and whose gate the caller passed, never a
value they supplied.

This generalizes the advanced tool's mint: same shape, but target, origins and
audience come from the registration row rather than from deployment settings, so
every registered plug-in gets one without a settings block of its own.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import GuildPluginMessages, PluginServiceMessages
from app.core.security import (
    PLUGIN_HANDOFF_TOKEN_TYPE,
    TOKEN_ISSUER,
    PluginPlatformSigningNotConfiguredError,
    plugin_platform_audience,
    resolve_plugin_platform_signing_material,
    sign_eddsa,
)
from app.db.guild_standing import GuildContext
from app.models.tenant.guild_plugin import GuildPlugin
from app.services.marketplace import plugin_refs, registration_lookup
from app.services.marketplace.community_status import community_status
from app.services.marketplace.service_plugins import declared_permissions
from app.services.tenant import plugin_age
from app.services.tenant.guild_plugins import (
    SurfaceAccess,
    declared_surfaces,
    holds_permission,
    is_placed,
    surface_access,
    surface_renders_in,
)
from app.services.tenant.plugin_age import AgeViewer

__all__ = [
    "PLUGIN_PAGE_HANDOFF_LIFETIME",
    "PageHandoff",
    "authorize_surface",
    "mint_page_handoff",
    "page_by_id",
    "require_live_registration",
    "signing_material",
    "surface_claims",
]

#: Single source for the handoff's lifetime, so the response advertises exactly
#: what the ``exp`` claim encodes. Short by design: the handoff is spent within a
#: minute, and the long-lived session belongs to the plug-in, not to this token.
PLUGIN_PAGE_HANDOFF_LIFETIME = timedelta(seconds=60)


@dataclass(frozen=True)
class PageHandoff:
    """A minted handoff plus everything the browser needs to use it."""

    token: str
    expires_in_seconds: int
    #: Where the iframe points: the registration's browser base joined to the
    #: path the manifest declared for this surface.
    page_url: str
    #: The origins the SPA accepts messages from, and posts the token to.
    allowed_origins: tuple[str, ...]
    audience: str
    surface_id: str


def page_by_id(
    definition: dict[str, Any] | None, surface_id: str, *, scope: str
) -> dict[str, Any] | None:
    """One declared page from a pinned definition, if it renders here.

    ``scope`` is where the surface is being opened from — the route's to state,
    never the caller's. A surface that never asked to render there is not a
    surface of that route, so it is simply not found. Definitions pinned before
    a surface could say where it belongs carry no ``scopes``, and every one of
    those is community-wide.
    """
    for page in declared_surfaces(definition):
        if page.get("id") != surface_id:
            continue
        return page if surface_renders_in(page, scope) else None
    return None


async def require_live_registration(
    plugin: GuildPlugin, guild_id: int
) -> registration_lookup.RegistrationSnapshot:
    """The registration behind this install in community ``guild_id``, or a
    refusal.

    Both halves of "not available" answer the same way: a plug-in service this
    deployment never wired up, and one whose registration the operator turned
    off, are equally unreachable from here.
    """
    registration = await registration_lookup.registration_for_definition(
        plugin.definition, listing_uid=plugin.listing_uid
    )
    if registration is None or not registration.live_in(guild_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=GuildPluginMessages.SERVICE_NOT_REGISTERED,
        )
    return registration


async def authorize_surface(
    session: AsyncSession,
    plugin: GuildPlugin,
    *,
    surface_id: str,
    context: GuildContext,
    initiative_id: int | None,
    viewer: AgeViewer,
) -> tuple[dict[str, Any], registration_lookup.RegistrationSnapshot]:
    """Whether the caller may open one surface here, or a refusal; answered
    with the page the manifest declares and the registration behind it.

    ``initiative_id`` is where the surface was opened, and it is the only thing
    that says so — the scope is derived from it rather than passed alongside,
    because two arguments could disagree and there is nothing sensible for a
    mint to do when they do. It comes from a route whose gate the caller already
    passed, so by the time it is a claim it is a fact.

    Who may open it is :func:`~app.services.tenant.guild_plugins.surface_access`,
    the same decision the plug-in read reports to the client, measured on the
    viewer's standing (``context``) and their age where they are (``viewer``).
    An initiative surface reads whether it is placed there in one query. The
    page handoff and Sign in with Initiative both ask it, so both doors make
    one decision.
    """
    if not plugin.enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=GuildPluginMessages.DISABLED
        )

    scope = "community" if initiative_id is None else "initiative"
    # Two ways there is no surface here: the plug-in never declared one for this
    # scope, or the guild placed its initiative surfaces somewhere else. Same
    # answer, because from this route both mean the same thing.
    page = page_by_id(plugin.definition, surface_id, scope=scope)
    if page is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildPluginMessages.SURFACE_NOT_FOUND,
        )
    access = surface_access(
        plugin,
        page,
        context=context,
        initiative_id=initiative_id,
        placed=await is_placed(session, plugin.id, initiative_id),
        age_allows=plugin_age.age_allows(plugin.definition, viewer),
    )
    if access is SurfaceAccess.not_here:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildPluginMessages.SURFACE_NOT_FOUND,
        )
    if access is SurfaceAccess.too_young:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildPluginMessages.AGE_RESTRICTED,
        )
    if access is SurfaceAccess.refused:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildPluginMessages.SURFACE_PERMISSION_REQUIRED,
        )

    return page, await require_live_registration(plugin, context.guild_id)


def signing_material() -> tuple[str, str | None]:
    """The plug-in platform's signing key, or a 503 naming what is missing.

    The keypair is required and has no fallback, so an unconfigured
    deployment fails closed rather than minting something no plug-in can
    verify.
    """
    try:
        return resolve_plugin_platform_signing_material()
    except PluginPlatformSigningNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=PluginServiceMessages.SIGNING_NOT_CONFIGURED,
        ) from exc


async def surface_claims(
    plugin: GuildPlugin,
    registration: registration_lookup.RegistrationSnapshot,
    *,
    surface_id: str,
    context: GuildContext,
    initiative_id: int | None,
) -> dict[str, Any]:
    """What a plug-in is told about the person opening one of its surfaces,
    which :func:`authorize_surface` admitted: the claims beside each token's
    envelope (see the module docstring)."""
    guild_id = context.guild_id
    try:
        subject = await plugin_refs.ensure_plugin_ref(
            guild_id=guild_id,
            public_id=registration.public_id,
            user_id=context.user_id,
        )
        guild_ref = await plugin_refs.ensure_plugin_guild_ref(
            guild_id=guild_id, public_id=registration.public_id
        )
    except plugin_refs.PluginNameRefused as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=GuildPluginMessages.ERASE_PENDING,
        ) from exc
    claims: dict[str, Any] = {
        # The reference this plug-in knows the member by in this community
        # (OIDC Core §8.1 pairwise), never the row id: it is stable for the
        # plug-in here, across a reinstall, and unrelated to what any other
        # sector holds for the same person.
        "sub": subject,
        # The guild by reference, for the same reason as the member above: an
        # index names a row to us, not an entity to somebody else.
        "community_ref": guild_ref,
        "plugin_install_id": plugin.id,
        # Where the community stands now, which every token carries.
        "community_status": await community_status(guild_id),
        "surface_id": surface_id,
        # The viewer's community role, from the standing the access decision
        # was measured on, so a plug-in need not ask for it separately.
        "community_admin": bool(context.is_admin),
        # What the viewer holds of the plug-in here, from the same standing.
        "permissions": [
            entry["id"]
            for entry in declared_permissions(plugin.definition)
            if entry["level"]
            == ("community" if initiative_id is None else "initiative")
            and holds_permission(
                context, plugin, entry["id"], initiative_id=initiative_id
            )
        ],
    }
    # Absent guild-wide rather than null, so "which initiative is this?" has one
    # answer instead of two shapes that both mean none.
    if initiative_id is not None:
        claims["initiative_id"] = initiative_id
        claims["initiative_moderator"] = (
            initiative_id in context.manager_initiatives
            and initiative_id in context.override_initiatives
        )
    return claims


async def mint_page_handoff(
    session: AsyncSession,
    plugin: GuildPlugin,
    *,
    surface_id: str,
    context: GuildContext,
    initiative_id: int | None,
    viewer: AgeViewer,
) -> PageHandoff:
    """Authorize the caller for one surface (:func:`authorize_surface`), then
    mint its handoff."""
    page, registration = await authorize_surface(
        session,
        plugin,
        surface_id=surface_id,
        context=context,
        initiative_id=initiative_id,
        viewer=viewer,
    )
    key, kid = signing_material()
    claims = await surface_claims(
        plugin,
        registration,
        surface_id=surface_id,
        context=context,
        initiative_id=initiative_id,
    )

    now = datetime.now(UTC)
    audience = plugin_platform_audience(registration.public_id)
    payload: dict[str, Any] = {
        # One-shot marker: the plug-in blocklists a handoff once it has exchanged
        # it, so a captured token is not replayable inside its short window.
        "jti": str(uuid.uuid4()),
        "aud": audience,
        "iss": TOKEN_ISSUER,
        "iat": int(now.timestamp()),
        "exp": now + PLUGIN_PAGE_HANDOFF_LIFETIME,
        **claims,
    }
    token = sign_eddsa(payload, key, kid, typ=PLUGIN_HANDOFF_TOKEN_TYPE)

    return PageHandoff(
        token=token,
        expires_in_seconds=int(PLUGIN_PAGE_HANDOFF_LIFETIME.total_seconds()),
        page_url=f"{registration.browser_base}{page.get('path') or ''}",
        allowed_origins=registration.allowed_origins,
        audience=audience,
        surface_id=surface_id,
    )
