"""The plug-in platform's token endpoint: who is asking, and what they are given.

Initiative is the authorization server for the plug-ins a deployment registers.
One endpoint, form-encoded per RFC 6749, authenticates the plug-in by a JWT it
signs with a key its registration publishes (RFC 7523 §2.2,
``private_key_jwt``) and issues one of two sealed access tokens
(:mod:`app.core.plugin_access_token`):

* ``client_credentials`` alone: a **plug-in token**, which lists the plug-in's installs;
* ``client_credentials`` with ``installation``: an **installation token** for
  that install, optionally down-scoped (``scope``, RFC 6749 §3.3) and narrowed
  to one initiative it is placed in (``resource``, RFC 8707). ``level`` asks
  for a standing on top of its scopes: ``moderator`` (narrowed to an
  initiative) or ``guild_admin`` (narrowed or not; narrowed, it administers
  within that one initiative). The community must have
  granted the level's scope (``LEVEL_SCOPES``), and the token then carries it.
  No token carries a standing it did not ask for, and ``scope`` cannot name
  one;
* ``urn:ietf:params:oauth:grant-type:jwt-bearer`` (RFC 7523 §2.1): a **member
  token**, an installation token that acts for one member, for a purpose that
  member consented to. The ``assertion`` is signed with the same registered key
  and also authenticates the client (RFC 7523 §3): ``sub`` is the member's
  reference at this install, ``installation`` the install's, and ``purpose``
  the purpose, when the consent names one. With no live consent the answer is
  ``consent_required``; ``scope`` and ``resource`` narrow as for an
  installation token, and a consent bound to an initiative is only used by a
  token narrowed to it.

Everything here runs on the system engine. A community's rows are read on a
system session from its cohort, routed by ``guild_id`` alone, as any sweep
reads them.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import ed25519
from sqlalchemy import Row, TextClause, text
from sqlalchemy.exc import DBAPIError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.config import API_V1_STR, settings
from app.core.plugin_access_token import (
    ACCESS_TOKEN_LIFETIME_SECONDS,
    seal_install_token,
    seal_plugin_token,
)
from app.core.plugin_scopes import (
    LEVEL_SCOPES,
    InstallLevel,
    PluginScopeAccess,
    UnknownPluginScope,
    expand,
    is_known_scope,
    is_standing_scope,
    parse_scope,
    plugin_scope_target,
    validate_scopes,
)
from app.db import cohorts
from app.db.guild_standing import ISSUABLE_SCOPES_SQL
from app.db.request_context import SystemGuild
from app.db.session import set_rls_context
from app.models.platform.guild import GuildMembership
from app.models.platform.plugin_assertion_jti import ASSERTION_JTI_MAX_LENGTH
from app.models.platform.plugin_service_registration import (
    RegistrationKind,
    registration_live_sql,
)
from app.models.platform.user import User, UserStatus
from app.models.tenant.plugin_member_consent import ConsentAccess, is_valid_purpose
from app.services import audit as audit_service
from app.services.marketplace import (
    plugin_installs,
    plugin_keys,
    plugin_refs,
    registration_lookup,
)
from app.services.marketplace.registration_lookup import RegistrationSnapshot
from app.services.membership import live_membership_clause

logger = logging.getLogger(__name__)

__all__ = [
    "ASSERTION_TYPE",
    "GRANT_CLIENT_CREDENTIALS",
    "GRANT_JWT_BEARER",
    "INITIATIVE_RESOURCE_PREFIX",
    "TOKEN_PATH",
    "InstallationListing",
    "IssuedToken",
    "OAuthError",
    "issue_token",
    "list_installations",
    "token_endpoint_url",
    "verify_client_assertion",
    "verify_member_assertion",
]

#: Where the endpoint is mounted, under the API prefix.
TOKEN_PATH = f"{API_V1_STR}/plugin-platform/oauth/token"

ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
GRANT_CLIENT_CREDENTIALS = "client_credentials"
GRANT_JWT_BEARER = "urn:ietf:params:oauth:grant-type:jwt-bearer"
#: A ``resource`` naming one initiative: this prefix, then its id.
INITIATIVE_RESOURCE_PREFIX = "urn:initiative:initiative:"

#: The longest an assertion may be valid for, from its ``iat`` to its ``exp``.
MAX_ASSERTION_LIFETIME_SECONDS = 300
#: How far ahead of this server's clock an assertion's ``iat`` may be.
IAT_CLOCK_SKEW_SECONDS = 60

_DIGITS = frozenset("0123456789")
#: An initiative id is a Postgres ``integer``.
_MAX_INITIATIVE_ID = 2**31 - 1


class OAuthError(Exception):
    """An error response the token endpoint owes its caller (RFC 6749 §5.2)."""

    def __init__(self, error: str, description: str, status_code: int = 400) -> None:
        super().__init__(f"{error}: {description}")
        self.error = error
        self.description = description
        self.status_code = status_code


def _invalid_client(description: str) -> OAuthError:
    return OAuthError("invalid_client", description, status_code=401)


def _invalid_grant(description: str) -> OAuthError:
    return OAuthError("invalid_grant", description)


def _consent_required(description: str) -> OAuthError:
    """No live consent covers the request: the plug-in asks the member again
    (the error OpenID Connect names ``consent_required``)."""
    return OAuthError("consent_required", description)


def token_endpoint_url() -> str:
    """The token endpoint's absolute URL: the ``aud`` every client assertion
    must carry, exactly.

    Built from ``APP_URL`` the way every other public callback address is: the
    API is served under the same origin as the app, at ``API_V1_STR``.
    """
    return f"{settings.APP_URL.rstrip('/')}{TOKEN_PATH}"


# --- client authentication ----------------------------------------------------


def _algorithm_for(key: Any) -> str | None:
    """The one algorithm a plug-in key verifies with: EdDSA, for the Ed25519
    key every plug-in signs with (RFC 8037). Any other key verifies nothing."""
    if isinstance(key, ed25519.Ed25519PublicKey):
        return "EdDSA"
    return None


def _numeric_date(
    claims: Mapping[str, Any],
    name: str,
    fail: Callable[[str], OAuthError] = _invalid_client,
) -> float:
    value = claims.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise fail(f"{name} must be a NumericDate")
    return float(value)


async def verify_client_assertion(
    session: AsyncSession,
    *,
    assertion_type: str | None,
    assertion: str | None,
    client_id: str | None = None,
    now: float | None = None,
) -> RegistrationSnapshot:
    """Authenticate the plug-in behind a client assertion, and spend the assertion.

    Returns the registration it verified against. Raises :class:`OAuthError`
    (``invalid_client``) on any failure.

    The registration, its key and the key's algorithm come from rows, never from
    the assertion's own say-so: ``iss`` selects the registration, ``kid`` the key
    in its set, and the key's type the algorithm. The ``jti`` is recorded in the
    same statement that confirms the registration is still live, and a
    second presentation meets the primary key.
    """
    if assertion_type != ASSERTION_TYPE or not assertion:
        raise _invalid_client("a jwt-bearer client assertion is required")
    snapshot, _claims = await _verify_signed_assertion(
        session,
        assertion=assertion,
        client_id=client_id,
        now=now,
        member=False,
    )
    return snapshot


async def verify_member_assertion(
    session: AsyncSession,
    *,
    assertion: str | None,
    client_id: str | None = None,
    now: float | None = None,
) -> tuple[RegistrationSnapshot, dict[str, Any]]:
    """Verify a member grant's assertion (RFC 7523 §2.1), which also
    authenticates the client (§3), and spend it.

    Held to everything a client assertion is, except that ``sub`` names the
    member rather than the client, and it must carry ``installation``. Returns
    the registration and the verified claims. Raises :class:`OAuthError`
    (``invalid_grant``) on any failure.
    """
    if not assertion:
        raise _invalid_grant("an assertion is required")
    return await _verify_signed_assertion(
        session, assertion=assertion, client_id=client_id, now=now, member=True
    )


#: Records the assertion's jti against its registration, in the one statement
#: that also reads the registration fresh; only a live registration matches.
_BURN_JTI_SQL = (
    "INSERT INTO public.plugin_assertion_jtis "
    "(registration_id, jti, expires_at) "
    "SELECT r.id, :jti, :expires_at "
    "FROM public.plugin_service_registrations r "
    "JOIN public.publishers p ON p.id = r.publisher_id "
    "WHERE r.public_id = :public_id "
    f"AND r.kind = '{RegistrationKind.CONTAINER}' "
    f"AND {registration_live_sql('r', 'p')} "
    "ON CONFLICT DO NOTHING "
    "RETURNING registration_id"
)


async def _verify_signed_assertion(
    session: AsyncSession,
    *,
    assertion: str,
    client_id: str | None,
    now: float | None,
    member: bool,
) -> tuple[RegistrationSnapshot, dict[str, Any]]:
    """The one verification both assertions share: one key lookup, one
    signature, one ``jti`` spent. ``member`` selects the member grant's shape
    and error code."""
    fail = _invalid_grant if member else _invalid_client

    try:
        header = jwt.get_unverified_header(assertion)
        unverified = jwt.decode(assertion, options={"verify_signature": False})
    except jwt.PyJWTError as exc:
        raise fail("the assertion is not a JWT") from exc

    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise fail("the assertion names no kid")
    issuer = unverified.get("iss")
    if not isinstance(issuer, str) or not issuer:
        raise fail("the assertion names no issuer")
    if client_id is not None and client_id != issuer:
        raise fail("client_id does not match the assertion")

    snapshot = (await registration_lookup.load_registrations()).get(issuer)
    # Only a container signs: a declarative plug-in has no code to hold a key.
    if snapshot is None or not snapshot.live or snapshot.declarative:
        raise fail("unknown client")
    key = await plugin_keys.key_for(snapshot, kid)
    if key is None:
        raise fail("unknown key")
    algorithm = _algorithm_for(key)
    if algorithm is None:
        raise fail("the key cannot verify an assertion")
    if header.get("alg") != algorithm:
        raise fail("the assertion's algorithm does not match its key")

    audience = token_endpoint_url()
    required = ["iss", "sub", "aud", "jti", "iat", "exp"]
    if member:
        required.append("installation")
    try:
        claims = jwt.decode(
            assertion,
            key,
            algorithms=[algorithm],
            audience=audience,
            issuer=issuer,
            # A client assertion's subject is the client; a member grant's is
            # the member, checked by the grant.
            subject=None if member else issuer,
            leeway=0,
            options={
                "require": required,
                "strict_aud": True,
                # Checked below with the skew this endpoint allows.
                "verify_iat": False,
            },
        )
    except jwt.PyJWTError as exc:
        raise fail("the assertion did not verify") from exc

    if claims.get("aud") != audience:
        raise fail("the assertion is not for this endpoint")
    current = time.time() if now is None else now
    issued_at = _numeric_date(claims, "iat", fail)
    expires_at = _numeric_date(claims, "exp", fail)
    if issued_at > current + IAT_CLOCK_SKEW_SECONDS:
        raise fail("the assertion was issued in the future")
    if expires_at <= current:
        raise fail("the assertion has expired")
    if expires_at <= issued_at:
        raise fail("the assertion expires before it was issued")
    if expires_at - issued_at > MAX_ASSERTION_LIFETIME_SECONDS:
        raise fail("the assertion is valid for too long")
    jti = claims.get("jti")
    if not isinstance(jti, str) or not jti or len(jti) > ASSERTION_JTI_MAX_LENGTH:
        raise fail("the assertion's jti is not usable")

    # One statement: the registration is read fresh (the snapshot may be up to
    # a minute old) and the jti recorded against it. No row back means the
    # registration is no longer live, or the jti has been spent.
    spent = (
        await session.exec(
            text(_BURN_JTI_SQL),
            params={
                "jti": jti,
                "expires_at": datetime.fromtimestamp(expires_at, tz=UTC),
                "public_id": issuer,
            },
        )
    ).first()
    await session.commit()
    if spent is None:
        audit_service.emit(
            event_type=AuditEventType.SECURITY_REPLAY_REJECTED,
            actor_user_id=None,
            detail={
                "channel": "plugin_member_assertion" if member else "plugin_assertion",
                "install": issuer,
            },
        )
        raise fail("the assertion was already used")
    return snapshot, dict(claims)


# --- grants -------------------------------------------------------------------


@dataclass(frozen=True)
class IssuedToken:
    access_token: str
    expires_in: int
    scope: str


def _initiative_resource(value: str) -> int:
    """The initiative a ``resource`` names, or ``invalid_target``."""
    if not value.startswith(INITIATIVE_RESOURCE_PREFIX):
        raise OAuthError("invalid_target", "resource must name an initiative")
    digits = value[len(INITIATIVE_RESOURCE_PREFIX) :]
    if not digits or not set(digits) <= _DIGITS or len(digits) > 10:
        raise OAuthError("invalid_target", "resource must name an initiative")
    initiative_id = int(digits)
    if initiative_id <= 0 or initiative_id > _MAX_INITIATIVE_ID:
        raise OAuthError("invalid_target", "resource must name an initiative")
    return initiative_id


def _covered(requested: frozenset[str], granted: frozenset[str]) -> bool:
    """Whether every requested scope is within the grant. A written resource
    may be asked for at read."""
    readable, writable = expand(granted)
    wanted_read, wanted_write = expand(requested)
    # A ``plugins:`` scope names no resource; it is covered only by itself.
    wanted_plugins = {scope for scope in requested if plugin_scope_target(scope)}
    return (
        wanted_read <= readable
        and wanted_write <= writable
        and wanted_plugins <= set(granted)
    )


def _requested_scopes(value: str | None) -> frozenset[str] | None:
    """The scopes a ``scope`` parameter asks for; ``None`` when it asks for
    none in particular."""
    if value is None:
        return None
    requested = frozenset(value.split())
    if not requested:
        return None
    try:
        checked = validate_scopes(requested)
    except UnknownPluginScope as exc:
        raise OAuthError("invalid_scope", f"{exc.scope!r} is not a scope") from exc
    for wanted in sorted(checked):
        if is_standing_scope(wanted):
            raise OAuthError(
                "invalid_scope", f"{wanted!r} is asked for with level, not scope"
            )
    return checked


def _requested_level(value: str | None) -> InstallLevel | None:
    """The standing a ``level`` parameter asks for, or ``None``."""
    if value is None:
        return None
    try:
        return InstallLevel(value)
    except ValueError as exc:
        raise OAuthError("invalid_request", "level is not a level") from exc


def _without_standings(scopes: frozenset[str]) -> frozenset[str]:
    """``scopes`` less every standing: what a token carries by default."""
    return frozenset(scope for scope in scopes if not is_standing_scope(scope))


def _with_level(
    scopes: frozenset[str],
    granted: frozenset[str],
    level: InstallLevel | None,
    initiative_id: int | None,
) -> frozenset[str]:
    """``scopes`` plus the standing ``level`` asks for, when the grant holds
    it and the token's narrowing suits it."""
    if level is None:
        return scopes
    scope = LEVEL_SCOPES[level]
    if scope not in granted:
        raise OAuthError("invalid_scope", f"{scope!r} has not been granted")
    if level is InstallLevel.moderator and initiative_id is None:
        raise OAuthError("invalid_target", "a moderator token names its initiative")
    return scopes | {scope}


def _issuable(row: Any, client: RegistrationSnapshot) -> frozenset[str]:
    """What an install's grant issues now: :data:`ISSUABLE_SCOPES_SQL`, within
    the registration's ``scope_ceiling`` as it stands, less any scope the
    vocabulary no longer defines, which the token could never be used with."""
    ceiling = set(client.scope_ceiling)
    return frozenset(
        scope for scope in row.issuable if scope in ceiling and is_known_scope(scope)
    )


_INSTALL_SQL_TEXT = (
    f"SELECT a.id, a.listing_uid, a.enabled, {ISSUABLE_SCOPES_SQL} AS issuable, "
    "ARRAY(SELECT p.initiative_id FROM plugin_placements p "
    "WHERE p.install_id = a.id ORDER BY p.initiative_id) AS placed "
    "FROM guild_plugins a WHERE a.listing_uid = :listing_uid"
)
_INSTALL_SQL = text(_INSTALL_SQL_TEXT)


async def _read_in_community(
    guild_id: int, statement: TextClause, params: dict[str, Any]
) -> Sequence[Row[Any]] | None:
    """``statement``'s rows in one community's schema, read on a system session
    from its cohort, or ``None`` when the community has no role left to route
    into."""
    async with cohorts.system_session(guild_id) as session:
        try:
            await set_rls_context(session, SystemGuild(guild_id))
            return (await session.exec(statement, params=params)).all()
        except DBAPIError:
            return None


async def _installation_token(
    client: RegistrationSnapshot,
    *,
    installation: str,
    scope: str | None,
    resource: str | None,
    level: str | None = None,
) -> IssuedToken:
    wanted_level = _requested_level(level)
    resolved = await plugin_refs.resolve_plugin_guild_ref(ref=installation)
    # The reference names the community in the client's own sector, and the
    # install is the one the community has of the client's listing now.
    if resolved is None or resolved[1] != client.public_id:
        raise OAuthError("invalid_grant", "unknown installation")
    guild_id = resolved[0]
    if client.listing_uid is None:
        raise OAuthError("invalid_grant", "unknown installation")

    rows = await _read_in_community(
        guild_id, _INSTALL_SQL, {"listing_uid": client.listing_uid}
    )
    row = rows[0] if rows else None
    if row is None or not row.enabled or not client.serves(guild_id):
        raise OAuthError("invalid_grant", "unknown installation")
    install_id = int(row.id)

    granted = _issuable(row, client)
    requested = _requested_scopes(scope)
    if requested is not None and not _covered(requested, granted):
        raise OAuthError("invalid_scope", "a requested scope has not been granted")
    scopes = _without_standings(granted) if requested is None else requested

    initiative_id: int | None = None
    if resource is not None:
        initiative_id = _initiative_resource(resource)
        if initiative_id not in set(row.placed or ()):
            raise OAuthError(
                "invalid_target", "the installation is not placed in that initiative"
            )
    scopes = _with_level(scopes, granted, wanted_level, initiative_id)

    token, _exp = seal_install_token(
        guild_id=guild_id,
        install_id=install_id,
        client_id=client.public_id,
        scopes=scopes,
        initiative_id=initiative_id,
    )
    return IssuedToken(
        access_token=token,
        expires_in=ACCESS_TOKEN_LIFETIME_SECONDS,
        scope=" ".join(sorted(scopes)),
    )


#: The install, where it is placed, and, for one member and purpose, the
#: initiatives the member is in and their live consent. Read on the system
#: engine routed into the community.
_MEMBER_INSTALL_SQL_TEXT = (
    f"SELECT a.id, a.listing_uid, a.enabled, {ISSUABLE_SCOPES_SQL} AS issuable, "
    "ARRAY(SELECT p.initiative_id FROM plugin_placements p "
    "WHERE p.install_id = a.id ORDER BY p.initiative_id) AS placed, "
    "ARRAY(SELECT im.initiative_id FROM initiative_members im "
    "WHERE im.user_id = :user_id ORDER BY im.initiative_id) AS member_of, "
    "c.granted_access, c.initiative_id AS consent_initiative_id "
    "FROM guild_plugins a "
    "LEFT JOIN plugin_member_consents c ON c.install_id = a.id "
    "AND c.user_id = :user_id "
    "AND c.purpose IS NOT DISTINCT FROM CAST(:purpose AS varchar) "
    "AND c.granted_access IS NOT NULL AND c.revoked_at IS NULL "
    "WHERE a.listing_uid = :listing_uid"
)
_MEMBER_INSTALL_SQL = text(_MEMBER_INSTALL_SQL_TEXT)


def _read_only_scopes(scopes: frozenset[str]) -> frozenset[str]:
    """``scopes`` with every write scope read instead: what a token may use
    for a member who allowed reading only."""
    out: set[str] = set()
    for scope in scopes:
        if is_standing_scope(scope):
            continue
        if plugin_scope_target(scope) is not None:
            # Calling another plug-in is not a write of the community's; which of
            # its endpoints a read-only consent reaches is the hub's to decide.
            out.add(scope)
            continue
        resource, access = parse_scope(scope)
        out.add(
            f"{resource.value}:{PluginScopeAccess.read.value}"
            if access is PluginScopeAccess.write
            else scope
        )
    return frozenset(out)


async def _member_token(
    session: AsyncSession,
    client: RegistrationSnapshot,
    claims: Mapping[str, Any],
    *,
    scope: str | None,
    resource: str | None,
) -> IssuedToken:
    """A member token: what the member consented to, for the purpose the
    assertion names, within the install's placement and scopes."""
    installation = claims.get("installation")
    if not isinstance(installation, str) or not installation:
        raise _invalid_grant("installation must name the install")
    purpose = claims.get("purpose")
    if purpose is not None and not is_valid_purpose(purpose):
        raise _invalid_grant("purpose is not usable")
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise _invalid_grant("sub must name the member")

    resolved = await plugin_refs.resolve_plugin_guild_ref(ref=installation)
    if resolved is None or resolved[1] != client.public_id:
        raise _invalid_grant("unknown installation")
    guild_id = resolved[0]
    if client.listing_uid is None:
        raise _invalid_grant("unknown installation")

    # The member, by the reference this plug-in holds for them in the community.
    member_ref = await plugin_refs.resolve_plugin_ref(
        session, ref=subject, guild_id=guild_id
    )
    if member_ref is None or member_ref.sector_plugin != client.public_id:
        raise _invalid_grant("unknown member")
    user_id = int(member_ref.entity_id)
    belongs = (
        await session.exec(
            select(GuildMembership.user_id)
            .join(User, User.id == GuildMembership.user_id)  # type: ignore[arg-type]
            .where(
                GuildMembership.guild_id == guild_id,
                GuildMembership.user_id == user_id,
                live_membership_clause(),
                User.status == UserStatus.active,
            )
        )
    ).first()
    await session.rollback()

    # The install the community has of the client's listing now: the member's
    # reference outlives an uninstall, and a token is issued only while there is
    # one again.
    rows = await _read_in_community(
        guild_id,
        _MEMBER_INSTALL_SQL,
        {"listing_uid": client.listing_uid, "user_id": user_id, "purpose": purpose},
    )
    row = rows[0] if rows else None
    if row is None or not row.enabled or not client.serves(guild_id):
        raise _invalid_grant("unknown installation")
    install_id = int(row.id)
    if belongs is None or row.granted_access is None:
        raise _consent_required("the member has not consented to this")

    granted = _issuable(row, client)
    requested = _requested_scopes(scope)
    if requested is not None and not _covered(requested, granted):
        raise OAuthError("invalid_scope", "a requested scope has not been granted")
    # A member token acts for the member, whose own standing it already is.
    scopes = _without_standings(granted if requested is None else requested)
    if row.granted_access != ConsentAccess.read_write.value:
        scopes = _read_only_scopes(scopes)

    initiative_id: int | None = None
    if resource is not None:
        initiative_id = _initiative_resource(resource)
    consent_initiative = row.consent_initiative_id
    if consent_initiative is not None and initiative_id != consent_initiative:
        raise OAuthError(
            "invalid_target",
            "this consent is for one initiative; name it as the resource",
        )
    if initiative_id is not None:
        if initiative_id not in set(row.placed or ()):
            raise OAuthError(
                "invalid_target", "the installation is not placed in that initiative"
            )
        if initiative_id not in set(row.member_of or ()):
            raise _consent_required("the member is not in that initiative")

    token, _exp = seal_install_token(
        guild_id=guild_id,
        install_id=install_id,
        client_id=client.public_id,
        scopes=scopes,
        initiative_id=initiative_id,
        user_id=user_id,
        purpose=purpose,
    )
    return IssuedToken(
        access_token=token,
        expires_in=ACCESS_TOKEN_LIFETIME_SECONDS,
        scope=" ".join(sorted(scopes)),
    )


async def issue_token(
    session: AsyncSession,
    *,
    grant_type: str | None,
    client_assertion_type: str | None,
    client_assertion: str | None,
    client_id: str | None = None,
    installation: str | None = None,
    scope: str | None = None,
    resource: str | None = None,
    level: str | None = None,
    assertion: str | None = None,
) -> IssuedToken:
    """Answer one token request, or raise :class:`OAuthError`."""
    if not grant_type:
        raise OAuthError("invalid_request", "grant_type is required")
    if grant_type == GRANT_JWT_BEARER:
        if level is not None:
            raise OAuthError("invalid_request", "a member token takes no level")
        # The assertion is the client's authentication too (RFC 7523 §3), and
        # names the install itself.
        if client_assertion_type is not None or client_assertion is not None:
            raise OAuthError(
                "invalid_request", "the assertion authenticates the client"
            )
        if installation is not None:
            raise OAuthError("invalid_request", "the assertion names the installation")
        client, claims = await verify_member_assertion(
            session, assertion=assertion, client_id=client_id
        )
        return await _member_token(
            session, client, claims, scope=scope, resource=resource
        )
    if grant_type != GRANT_CLIENT_CREDENTIALS:
        raise OAuthError("unsupported_grant_type", "unsupported grant_type")
    if assertion is not None:
        raise OAuthError("invalid_request", "assertion belongs to the jwt-bearer grant")

    client = await verify_client_assertion(
        session,
        assertion_type=client_assertion_type,
        assertion=client_assertion,
        client_id=client_id,
    )

    if installation is None:
        if _requested_scopes(scope) is not None:
            raise OAuthError("invalid_scope", "a plug-in token carries no scope")
        if resource is not None:
            raise OAuthError("invalid_target", "a plug-in token names no resource")
        if level is not None:
            raise OAuthError("invalid_request", "a plug-in token takes no level")
        token, _exp = seal_plugin_token(client_id=client.public_id)
        return IssuedToken(
            access_token=token, expires_in=ACCESS_TOKEN_LIFETIME_SECONDS, scope=""
        )

    if not installation:
        raise OAuthError("invalid_request", "installation is empty")
    return await _installation_token(
        client,
        installation=installation,
        scope=scope,
        resource=resource,
        level=level,
    )


# --- the plug-in's installs -------------------------------------------------------


@dataclass(frozen=True)
class InstallationListing:
    installation: str
    #: The install is switched on, its community is in use and its plug-in is
    #: for that community, so a token can be issued for it. An install that is off, or whose community is on hold,
    #: suspended or awaiting deletion, is still listed: it still exists.
    active: bool


async def list_installations(
    client: RegistrationSnapshot, *, cursor: str | None, limit: int
) -> tuple[list[InstallationListing], str | None]:
    """One page of the installs of ``client``'s listing, and the cursor for
    the next page (``None`` at the end).

    Read from the install index alone (:mod:`plugin_installs`), so no community
    is visited. Each says whether it is active: switched on, in a community in
    use. A plug-in tells an install that is only paused from one that is gone by
    whether it is listed at all; what an install was granted is in the token
    issued for it.
    """
    if client.listing_uid is None:
        return [], None
    entries, next_cursor = await plugin_installs.page(
        client.listing_uid, cursor=cursor, limit=limit
    )
    refs = await plugin_refs.ensure_plugin_guild_refs(
        (entry.guild_id, client.public_id) for entry in entries
    )
    # An install the plug-in may not be named in (one whose erase is not
    # finished) is not listed.
    return [
        InstallationListing(
            installation=refs[(entry.guild_id, client.public_id)],
            active=entry.active and client.serves(entry.guild_id),
        )
        for entry in entries
        if (entry.guild_id, client.public_id) in refs
    ], next_cursor
