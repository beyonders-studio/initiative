"""Sign in with Initiative: the page handoff, delivered by a redirect.

A plug-in with pages may name a ``sign_in`` in its manifest: one of its pages,
and the path Initiative sends somebody back to. People then open the plug-in at
its own address, sign in with their Initiative account, choose where to open
it, and land in that page full-window. It is OpenID Connect's authorization
code flow, with Initiative as the provider:

1. The plug-in sends the person to Initiative's authorize page with its
   ``client_id`` (its public id), the return address, ``state``, ``nonce`` and a
   PKCE ``S256`` challenge. The client and the exact return address are checked
   before anything else (:func:`resolve_client`); a request that fails either
   is answered on Initiative's own page and never sent back.
2. The person signs in to Initiative as they always do, and is offered the
   places where they may open the page (:func:`places_for`): each community
   holding the plug-in, at community level and in each initiative it is placed
   in, kept to those where :func:`~app.services.tenant.plugin_handoff.authorize_surface`
   would admit them.
3. They are sent back with a code (:func:`authorize`): sealed, good for a
   minute, bound to the client, the return address, the challenge and the
   place, and spent once.
4. The plug-in's server spends it at the token endpoint, authenticating with
   its registered key as for every other grant, and gets an ID token carrying
   the handoff's claims for that place, and a refresh token
   (:func:`issue_token`).

**Every renewal asks again.** A refresh token names the client, the place and
the person's Initiative sign-in, and is sealed, so it needs no table: the
sign-in's session row says whether it still stands. Each answer re-reads that
row's chain, routes into the community through the seam as that sign-in, and
asks :func:`authorize_surface` again, so signing out of Initiative, leaving the
community or the initiative, a changed role and an uninstall each end the
plug-in's session at its next renewal.

**A plug-in learns what a handoff tells it, and nothing more.** The ID token
carries the handoff's claims: the member by the reference this plug-in knows them
by in that community, and nothing about their name, address or other
communities. Its issuer is the deployment's own address, its audience the
plug-in's ``client_id`` (its public id), and its ``typ`` is ``JWT``, so it is
never taken for a handoff, nor a handoff for it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

from cryptography.fernet import InvalidToken
from fastapi import HTTPException
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import auth_context
from app.core.clock import utcnow
from app.core.config import API_V1_STR, settings
from app.core.encryption import (
    SALT_PLUGIN_SIGN_IN_CODE,
    SALT_PLUGIN_SIGN_IN_REFRESH,
    decrypt_field,
    encrypt_field,
)
from app.core.messages import PluginSignInMessages
from app.core.plugin_access_token import (
    ACCESS_TOKEN_LIFETIME_SECONDS,
    seal_plugin_token,
)
from app.core.security import sign_eddsa
from app.db import cohorts
from app.db import session as db_session
from app.db.guild_standing import GuildContext
from app.db.session import require_guild_context
from app.models.platform.auth_session import AuthSession
from app.models.platform.guild import Guild
from app.models.platform.user import User, UserStatus
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.initiative import Initiative
from app.services.auth import sessions as auth_sessions
from app.services.auth.assurance import policy_markers
from app.services.cross_guild import gather_across_guilds, member_guild_ids
from app.services.marketplace import catalog, plugin_installs, plugin_oauth
from app.services.marketplace.plugin_oauth import OAuthError
from app.services.marketplace.registration_lookup import (
    RegistrationSnapshot,
    load_registrations,
)
from app.services.membership import initiative_scope_clause
from app.services.tenant import plugin_age
from app.services.tenant.guild_plugins import (
    placements_by_install,
    surface_openability,
)
from app.services.tenant.plugin_age import AgeViewer
from app.services.tenant.plugin_channels import owns_install
from app.services.tenant.plugin_handoff import (
    authorize_surface,
    signing_material,
    surface_claims,
)

__all__ = [
    "AUTHORIZE_PATH",
    "GRANTS",
    "AuthorizeRequest",
    "IssuedSignIn",
    "Place",
    "SignInClient",
    "SignInRequestError",
    "authorize",
    "check_request",
    "denied",
    "discovery_document",
    "issue_token",
    "issuer",
    "places_for",
    "resolve_client",
]

#: The authorize page, on the deployment's own address: the SPA serves it.
AUTHORIZE_PATH = "/oauth/authorize"
GRANT_AUTHORIZATION_CODE = "authorization_code"
GRANT_REFRESH_TOKEN = "refresh_token"
#: The grants this module answers at the plug-in platform's token endpoint.
GRANTS = frozenset({GRANT_AUTHORIZATION_CODE, GRANT_REFRESH_TOKEN})

#: How long a code may wait in the person's browser before it is spent.
CODE_LIFETIME_SECONDS = 60
#: How long an ID token is good for: renew before then.
ID_TOKEN_LIFETIME_SECONDS = ACCESS_TOKEN_LIFETIME_SECONDS
#: The ``typ`` an ID token carries, as OpenID Connect's do.
ID_TOKEN_TYPE = "JWT"

CODE_PREFIX = "icd_"
REFRESH_PREFIX = "irt_"

#: The widest ``state`` and ``nonce`` a request may carry. The request comes
#: back through sign-in as its own return path, so it has to stay short.
MAX_STATE_LENGTH = 256
MAX_NONCE_LENGTH = 256
#: A PKCE ``S256`` challenge: 32 bytes of SHA-256, base64url without padding.
_CHALLENGE_LENGTH = 43
_BASE64URL = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)
#: PKCE verifiers are 43 to 128 unreserved characters (RFC 7636 §4.1).
_VERIFIER = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)


def issuer() -> str:
    """The deployment's own address: every ID token's ``iss``, and where its
    discovery document is published."""
    return settings.APP_URL.rstrip("/")


def discovery_document() -> dict[str, Any]:
    """OpenID Connect Discovery 1.0 §3: where a plug-in's library finds the
    endpoints and the keys. EdDSA alone: one key to keep and rotate."""
    base = issuer()
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}{AUTHORIZE_PATH}",
        "token_endpoint": plugin_oauth.token_endpoint_url(),
        "jwks_uri": f"{base}{API_V1_STR}/plugin-platform/jwks.json",
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": [GRANT_AUTHORIZATION_CODE, GRANT_REFRESH_TOKEN],
        "subject_types_supported": ["pairwise"],
        "id_token_signing_alg_values_supported": ["EdDSA"],
        "scopes_supported": ["openid"],
        "token_endpoint_auth_methods_supported": ["private_key_jwt"],
        "token_endpoint_auth_signing_alg_values_supported": ["EdDSA"],
        "code_challenge_methods_supported": ["S256"],
        "authorization_response_iss_parameter_supported": True,
        "claims_supported": [
            "iss",
            "sub",
            "aud",
            "exp",
            "iat",
            "nonce",
            "community_ref",
            "community_status",
            "plugin_install_id",
            "surface_id",
            "community_admin",
            "initiative_id",
            "initiative_moderator",
        ],
    }


# --- the request --------------------------------------------------------------


class SignInRequestError(Exception):
    """A request that cannot be trusted to name where to send its answer:
    shown on Initiative's own page (``code`` is a ``PluginSignInMessages``)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SignInClient:
    """A plug-in that offers Sign in with Initiative, and the one address it
    may be sent back to."""

    registration: RegistrationSnapshot
    listing_uid: str
    #: What the marketplace calls the listing, for adding it to a community.
    listing_public_id: str
    name: str
    redirect_uri: str


def _return_address(browser_base: str, return_path: str) -> str:
    """The manifest's ``return_path`` on the origin the plug-in's pages are
    served from."""
    parts = urlsplit(browser_base)
    return f"{parts.scheme}://{parts.netloc}{return_path}"


def _sign_in_of(definition: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    sign_in = (definition or {}).get("sign_in")
    return sign_in if isinstance(sign_in, Mapping) else None


async def resolve_client(
    client_id: str | None, redirect_uri: str | None
) -> SignInClient:
    """The plug-in asking, if it offers Sign in with Initiative and
    ``redirect_uri`` is exactly the address its manifest names.

    The address is checked against the listing's current version, which is
    what the marketplace offers today; each community's own pinned version
    then says which page opens there (:func:`places_for`).
    """
    registration = (await load_registrations()).get(client_id or "")
    if (
        registration is None
        or not registration.live
        or registration.declarative
        or not registration.listing_uid
    ):
        raise SignInRequestError(PluginSignInMessages.UNKNOWN_CLIENT)
    async with db_session.SystemSessionLocal() as session:
        listing = await catalog.get_listing_by_uid(session, registration.listing_uid)
        version = (
            None
            if listing is None
            else await catalog.get_listing_version(session, listing.latest_version_id)
        )
    if listing is None or version is None:
        raise SignInRequestError(PluginSignInMessages.UNKNOWN_CLIENT)
    sign_in = _sign_in_of(version.definition)
    if sign_in is None:
        raise SignInRequestError(PluginSignInMessages.NOT_OFFERED)
    expected = _return_address(registration.browser_base, str(sign_in["return_path"]))
    # Exact, query and all (RFC 9700 §2.1): the address is the registration's
    # and the manifest's, never the request's.
    if redirect_uri != expected:
        raise SignInRequestError(PluginSignInMessages.REDIRECT_MISMATCH)
    return SignInClient(
        registration=registration,
        listing_uid=registration.listing_uid,
        listing_public_id=listing.public_id,
        name=listing.name,
        redirect_uri=expected,
    )


@dataclass(frozen=True)
class AuthorizeRequest:
    """An authorize request whose client and return address were checked."""

    client: SignInClient
    state: str
    nonce: str
    code_challenge: str


def _redirect(redirect_uri: str, params: dict[str, str]) -> str:
    # RFC 9207: every response names who answered it.
    return f"{redirect_uri}?{urlencode({**params, 'iss': issuer()})}"


def _refusal(client: SignInClient, state: str | None, error: str) -> str:
    params = {"error": error}
    if state:
        params["state"] = state
    return _redirect(client.redirect_uri, params)


def denied(client: SignInClient, state: str | None) -> str:
    """Where somebody who declines is sent: back, with ``access_denied``."""
    return _refusal(client, state, "access_denied")


def check_request(
    client: SignInClient, params: Mapping[str, str | None]
) -> AuthorizeRequest | str:
    """The request, or the address to send its refusal to.

    With the client and its return address already checked, a malformed
    request is the plug-in's to hear about (RFC 6749 §4.1.2.1). Every request
    carries PKCE ``S256`` and a nonce: optional elsewhere, they cost a plug-in
    nothing here, and the SDK always sends both.
    """
    state = params.get("state")
    if not state or len(state) > MAX_STATE_LENGTH:
        return _refusal(client, None, "invalid_request")
    if params.get("response_type") != "code":
        return _refusal(client, state, "unsupported_response_type")
    if "openid" not in (params.get("scope") or "").split():
        return _refusal(client, state, "invalid_scope")
    nonce = params.get("nonce")
    challenge = params.get("code_challenge") or ""
    if (
        not nonce
        or len(nonce) > MAX_NONCE_LENGTH
        or params.get("code_challenge_method") != "S256"
        or len(challenge) != _CHALLENGE_LENGTH
        or not set(challenge) <= _BASE64URL
    ):
        return _refusal(client, state, "invalid_request")
    return AuthorizeRequest(
        client=client, state=state, nonce=nonce, code_challenge=challenge
    )


# --- the places ---------------------------------------------------------------


@dataclass(frozen=True)
class Place:
    """Somewhere a person may open the plug-in's sign-in page."""

    community_id: int
    community_name: str
    initiative_id: int | None = None
    initiative_name: str | None = None


async def _install(
    routed: AsyncSession, registration: RegistrationSnapshot
) -> GuildPlugin | None:
    """This community's install of the plug-in, when it is the plug-in's own
    and live here."""
    plugin = (
        await routed.exec(
            select(GuildPlugin).where(
                GuildPlugin.listing_uid == registration.listing_uid
            )
        )
    ).first()
    if (
        plugin is None
        or not plugin.enabled
        or not owns_install(plugin, registration)
        or not registration.live_in(require_guild_context(routed).guild_id)
    ):
        return None
    return plugin


def _page_of(plugin: GuildPlugin) -> str | None:
    """The page the community's pinned version of the plug-in opens at sign-in."""
    sign_in = _sign_in_of(plugin.definition)
    return None if sign_in is None else str(sign_in.get("page") or "") or None


async def _initiative_names(
    routed: AsyncSession, user_id: int, initiative_ids: tuple[int, ...]
) -> dict[int, str]:
    """The names of those initiatives the person can reach, as the handoff's
    own route reads them."""
    if not initiative_ids:
        return {}
    rows = await routed.exec(
        select(Initiative.id, Initiative.name).where(
            col(Initiative.id).in_(initiative_ids),
            initiative_scope_clause(user_id, Initiative.id),
        )
    )
    return {int(row[0]): str(row[1]) for row in rows.all()}


async def places_for(
    session: AsyncSession, user: User, client: SignInClient, viewer: AgeViewer
) -> tuple[list[Place], list[int]]:
    """Where ``user`` may open the plug-in's sign-in page, and every community
    of theirs holding the plug-in (whether or not it admits them there).

    Each community is entered through the seam as the person
    (:func:`~app.services.cross_guild.gather_across_guilds`), and each place is
    measured with the decision the handoff makes, so a place listed here is
    one where opening the page inside Initiative would succeed.
    """
    holding = await plugin_installs.communities_holding(
        client.listing_uid, await member_guild_ids(session, user.id)
    )
    if not holding:
        return [], []
    names = {
        int(row[0]): str(row[1])
        for row in (
            await session.exec(
                select(Guild.id, Guild.name).where(col(Guild.id).in_(holding))
            )
        ).all()
    }

    async def fetch(routed: AsyncSession, guild_id: int) -> list[Place]:
        context = require_guild_context(routed)
        plugin = await _install(routed, client.registration)
        page_id = None if plugin is None else _page_of(plugin)
        if context.membership is None or plugin is None or page_id is None:
            return []
        placements = (await placements_by_install(routed, [plugin.id]))[plugin.id]
        openable = next(
            (
                answer
                for answer in surface_openability(
                    plugin.definition,
                    placements=placements,
                    is_guild_admin=context.is_admin,
                    member_role_ids=context.member_role_ids,
                    age_allows=plugin_age.age_allows(plugin.definition, viewer),
                )
                if answer.surface_id == page_id
            ),
            None,
        )
        if openable is None:
            return []
        community = names.get(guild_id, "")
        found = (
            [Place(community_id=guild_id, community_name=community)]
            if openable.openable_guild_wide
            else []
        )
        initiatives = await _initiative_names(
            routed, user.id, openable.openable_initiatives
        )
        found.extend(
            Place(
                community_id=guild_id,
                community_name=community,
                initiative_id=initiative_id,
                initiative_name=initiatives[initiative_id],
            )
            for initiative_id in openable.openable_initiatives
            if initiative_id in initiatives
        )
        return found

    places = await gather_across_guilds(session, {user.id: holding}, fetch)
    return places, holding


async def _authorize_place(
    routed: AsyncSession,
    expected: RegistrationSnapshot,
    context: GuildContext,
    initiative_id: int | None,
    viewer: AgeViewer,
) -> tuple[GuildPlugin, str, RegistrationSnapshot]:
    """The install, its sign-in page and its registration, when the person
    may open that page in this place now; ``HTTPException`` otherwise.

    The one decision both doors make: :func:`authorize_surface`, as the
    handoff's own route asks it, after the same reachability check.
    """
    refused = HTTPException(
        status_code=403, detail=PluginSignInMessages.PLACE_UNAVAILABLE
    )
    if context.membership is None:
        raise refused
    plugin = await _install(routed, expected)
    page_id = None if plugin is None else _page_of(plugin)
    if plugin is None or page_id is None:
        raise refused
    if initiative_id is not None and not await _initiative_names(
        routed, context.user_id, (initiative_id,)
    ):
        raise refused
    _page, registration = await authorize_surface(
        routed,
        plugin,
        surface_id=page_id,
        context=context,
        initiative_id=initiative_id,
        viewer=viewer,
    )
    if registration.public_id != expected.public_id:
        raise refused
    return plugin, page_id, registration


# --- sealed codes and refresh tokens -----------------------------------------


def _seal(prefix: str, salt: bytes, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return prefix + encrypt_field(body, salt)


def _unseal(
    value: str | None, prefix: str, salt: bytes, ttl: int | None
) -> dict[str, Any]:
    if not value or not value.startswith(prefix):
        raise OAuthError("invalid_grant", "not a grant this deployment issued")
    try:
        payload = json.loads(decrypt_field(value[len(prefix) :], salt, ttl_seconds=ttl))
    except (InvalidToken, ValueError, TypeError) as exc:
        raise OAuthError("invalid_grant", "the grant is expired or altered") from exc
    if not isinstance(payload, dict):
        raise OAuthError("invalid_grant", "the grant is altered")
    return payload


@dataclass(frozen=True)
class _Grant:
    """What a code and a refresh token both name: the client, the place and
    the person's Initiative sign-in."""

    client_id: str
    guild_id: int
    initiative_id: int | None
    user_id: int
    session_id: uuid.UUID

    def sealed_fields(self) -> dict[str, Any]:
        return {
            "client": self.client_id,
            "guild": self.guild_id,
            "initiative": self.initiative_id,
            "user": self.user_id,
            "sid": str(self.session_id),
        }

    @classmethod
    def from_sealed(cls, payload: Mapping[str, Any]) -> _Grant:
        try:
            initiative = payload["initiative"]
            return cls(
                client_id=str(payload["client"]),
                guild_id=int(payload["guild"]),
                initiative_id=None if initiative is None else int(initiative),
                user_id=int(payload["user"]),
                session_id=uuid.UUID(str(payload["sid"])),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise OAuthError("invalid_grant", "the grant is altered") from exc


async def authorize(
    user: User,
    request: AuthorizeRequest,
    *,
    community_id: int,
    initiative_id: int | None,
    viewer: AgeViewer,
) -> str:
    """Send the person back with a code for the place they chose, when they
    may open the page there; ``HTTPException`` otherwise.

    Runs on the request that carries their own session: the code names that
    sign-in, whose chain every later renewal follows.
    """
    from app.api.deps import GuildAccessError, establish_guild_access

    credential = auth_context.current().session_credential
    if credential is None:
        raise HTTPException(
            status_code=403, detail=PluginSignInMessages.SESSION_REQUIRED
        )
    async with cohorts.request_sessionmaker(community_id)() as routed:
        account = await routed.merge(user, load=False)
        # The page offered this place a moment ago; whatever changed since,
        # the answer to the person is the same one.
        try:
            context = await establish_guild_access(routed, account, community_id)
            await _authorize_place(
                routed, request.client.registration, context, initiative_id, viewer
            )
        except (GuildAccessError, HTTPException) as exc:
            raise HTTPException(
                status_code=403, detail=PluginSignInMessages.PLACE_UNAVAILABLE
            ) from exc

    grant = _Grant(
        client_id=request.client.registration.public_id,
        guild_id=community_id,
        initiative_id=initiative_id,
        user_id=user.id,
        session_id=credential.session_id,
    )
    code = _seal(
        CODE_PREFIX,
        SALT_PLUGIN_SIGN_IN_CODE,
        {
            **grant.sealed_fields(),
            "jti": secrets.token_urlsafe(16),
            "redirect_uri": request.client.redirect_uri,
            "challenge": request.code_challenge,
            "nonce": request.nonce,
        },
    )
    return _redirect(
        request.client.redirect_uri, {"code": code, "state": request.state}
    )


# --- the token endpoint ------------------------------------------------------


@dataclass(frozen=True)
class IssuedSignIn:
    access_token: str
    expires_in: int
    id_token: str
    refresh_token: str


def _s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


async def _issue(
    client: RegistrationSnapshot, grant: _Grant, nonce: str | None
) -> IssuedSignIn:
    """An ID token for the grant's place as it stands now, and the refresh
    token that asks again. Any refusal is ``invalid_grant``: the plug-in's
    session ends, and the person signs in again."""
    from app.api.deps import GuildAccessError, establish_guild_access

    ended = OAuthError("invalid_grant", "the sign-in no longer stands")
    async with db_session.SystemSessionLocal() as system:
        tip = (
            await auth_sessions.live_chain_tips(
                system, session_ids=[grant.session_id], now=utcnow()
            )
        ).get(grant.session_id)
        row = None if tip is None else await system.get(AuthSession, tip)
        user = await system.get(User, grant.user_id)
    if (
        row is None
        or row.user_id != grant.user_id
        or user is None
        or user.status != UserStatus.active
    ):
        raise ended

    viewer = await plugin_age.current_viewer(grant.user_id)
    async with cohorts.request_sessionmaker(grant.guild_id)() as routed:
        # Present this sign-in and nothing else, as the socket re-check does:
        # the community's own sign-in rule and the deployment's second-factor
        # rule are answered by what that session proved.
        auth_context.reset(
            auth_context.AuthContext(
                session_amr=policy_markers(row.amr),
                satisfied_claims=auth_context.claims_from_provider_auth(
                    row.provider_auth
                ),
            )
        )
        account = await routed.merge(user, load=False)
        try:
            context = await establish_guild_access(
                routed,
                account,
                grant.guild_id,
                satisfied_providers=frozenset(row.satisfied_providers),
            )
            plugin, page_id, registration = await _authorize_place(
                routed, client, context, grant.initiative_id, viewer
            )
            claims = await surface_claims(
                plugin,
                registration,
                surface_id=page_id,
                context=context,
                initiative_id=grant.initiative_id,
            )
        except (GuildAccessError, HTTPException) as exc:
            raise ended from exc
        finally:
            auth_context.reset()

    try:
        key, kid = signing_material()
    except HTTPException as exc:
        raise OAuthError(
            "temporarily_unavailable", "signing is not configured", status_code=503
        ) from exc
    now = int(datetime.now(UTC).timestamp())
    payload: dict[str, Any] = {
        "jti": str(uuid.uuid4()),
        "iss": issuer(),
        # OpenID Connect Core §2: the client_id it was issued to, which is the
        # plug-in's public id. A handoff names ``initiative-plugin:<id>``.
        "aud": client.public_id,
        "iat": now,
        "exp": now + ID_TOKEN_LIFETIME_SECONDS,
        **claims,
    }
    # Core §12.2: a renewed ID token carries no nonce.
    if nonce is not None:
        payload["nonce"] = nonce
    renewed = _Grant(
        client_id=grant.client_id,
        guild_id=grant.guild_id,
        initiative_id=grant.initiative_id,
        user_id=grant.user_id,
        # The chain's live row, so the next renewal walks from here.
        session_id=row.id,
    )
    access_token, _exp = seal_plugin_token(client_id=client.public_id)
    return IssuedSignIn(
        access_token=access_token,
        expires_in=ID_TOKEN_LIFETIME_SECONDS,
        id_token=sign_eddsa(payload, key, kid, typ=ID_TOKEN_TYPE),
        refresh_token=_seal(
            REFRESH_PREFIX, SALT_PLUGIN_SIGN_IN_REFRESH, renewed.sealed_fields()
        ),
    )


async def issue_token(
    session: AsyncSession,
    *,
    grant_type: str,
    client_assertion_type: str | None,
    client_assertion: str | None,
    client_id: str | None,
    code: str | None,
    redirect_uri: str | None,
    code_verifier: str | None,
    refresh_token: str | None,
) -> IssuedSignIn:
    """Answer an ``authorization_code`` or ``refresh_token`` request, or raise
    :class:`OAuthError`. The plug-in authenticates with its registered key, as
    for every other grant (OpenID Connect Core §9, ``private_key_jwt``)."""
    client = await plugin_oauth.verify_client_assertion(
        session,
        assertion_type=client_assertion_type,
        assertion=client_assertion,
        client_id=client_id,
    )
    if grant_type == GRANT_REFRESH_TOKEN:
        grant = _Grant.from_sealed(
            _unseal(refresh_token, REFRESH_PREFIX, SALT_PLUGIN_SIGN_IN_REFRESH, None)
        )
        if grant.client_id != client.public_id:
            raise OAuthError("invalid_grant", "the refresh token is another client's")
        return await _issue(client, grant, nonce=None)

    sealed = _unseal(code, CODE_PREFIX, SALT_PLUGIN_SIGN_IN_CODE, CODE_LIFETIME_SECONDS)
    grant = _Grant.from_sealed(sealed)
    if grant.client_id != client.public_id:
        raise OAuthError("invalid_grant", "the code is another client's")
    if redirect_uri != sealed.get("redirect_uri"):
        raise OAuthError("invalid_grant", "redirect_uri does not match the request")
    verifier = code_verifier or ""
    if (
        not 43 <= len(verifier) <= 128
        or not set(verifier) <= _VERIFIER
        or not secrets.compare_digest(_s256(verifier), str(sealed.get("challenge")))
    ):
        raise OAuthError("invalid_grant", "code_verifier does not match the challenge")
    jti = sealed.get("jti")
    if not isinstance(jti, str) or not jti:
        raise OAuthError("invalid_grant", "the code is altered")
    if not await plugin_oauth.spend_jti(
        session,
        public_id=client.public_id,
        jti=f"code:{jti}",
        expires_at=datetime.now(UTC) + timedelta(seconds=CODE_LIFETIME_SECONDS),
        channel="plugin_sign_in_code",
    ):
        raise OAuthError("invalid_grant", "the code was already used")
    nonce = sealed.get("nonce")
    return await _issue(client, grant, nonce=nonce if isinstance(nonce, str) else None)
