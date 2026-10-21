from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, NoReturn, Optional, Sequence

from fastapi import Cookie, Depends, HTTPException, Path, Query, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import text as sa_text
from sqlalchemy.exc import DBAPIError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.plugin_access_token import InstallAccessToken
from app.core.plugin_scopes import (
    UnknownPluginScope,
    parse_scope,
    validate_scopes,
)
from app.core.capabilities import Capability, user_has_capability
from app.core.config import API_V1_STR
from app.core.config import settings as app_config
from app.core.login_methods import LoginMethod
from app.core import auth_context
from app.services.membership import live_membership_clause
from app.services.tenant import plugin_age
from app.services.tenant.plugin_age import AgeViewer
from app.services.auth import credentials
from app.services.auth import guild_provider_connections as guild_connections
from app.core.tools import Tool
from app.core.identify import (
    FEED_URL_CREDENTIALS,
    CredentialKind,
    Identified,
    bearer_plugin_token,
    identify,
    identify_url_token,
)
from app.services.auth.credentials import (
    Authenticated,
    CredentialRefused,
    asked_of_an_account,
)
from app.services.auth.assurance import (
    SECOND_FACTOR_AMR,
    carries_passkey,
)
from app.core.login_methods import SecondFactorRequirement
from app.models.platform.app_setting import AppSetting
from app.core.guild_auth_options import CommunityAuthOption
from app.services.platform import auth_posture
from app.services.platform import guild_entitlements
from app.services.platform.app_settings import GLOBAL_SETTINGS_ID
from app.core import audit_context
from app.core.messages import (
    AccessGrantMessages,
    PluginMessages,
    AuthMessages,
    DirectMessageMessages,
    GuildMessages,
    UserMessages,
)
from app.core.security import (
    SESSION_COOKIE_NAME,
    STEP_UP_CHALLENGE,
)
from app.core.identity_boundary import (
    InstallBoundary,
    admit_install,
    written_mention_refs,
)
from app.db import cohorts
from app.db.guild_standing import (
    ActorContext,
    GuildContext,
    InstallContext,
    named_ref_candidates,
)
from app.models.platform.identity_ref import IdentityEntity
from app.db.public_rls import PLATFORM_SUSPENDED
from app.db.request_context import (
    Filer,
    ContentGrantee,
    SignIn,
    Install,
    Member,
    Platform,
    SettingsGrantee,
)
from app.db.session import (
    apply_guild_standing,
    apply_install_standing,
    clear_rls_context,
    get_session,
    get_system_session,
    restore_rls_context,
    save_rls_context,
    set_rls_context,
)
from app.models.platform.access_grant import (
    AccessGrantPurpose,
    AccessLevel,
)
from app.models.platform.guild import (
    LIVE_STATUS_VALUES,
    Guild,
    GuildMembership,
    CommunityRole,
    CommunityStatus,
)
from app.models.platform.guild_auth_policy import GuildAuthPolicy, SignInHalf
from app.models.platform.user import (
    LOGIN_STATUSES,
    User,
    UserStatus,
)
from app.services.platform import access_grants as access_grants_service

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SystemSessionDep = Annotated[AsyncSession, Depends(get_system_session)]

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{API_V1_STR}/auth/token", auto_error=False
)


_SAFE_HTTP_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: Which kind of credential authenticated a request, recorded on
#: ``request.state.credential``. Most endpoints do not care — a person acting
#: through a script is still that person. It matters where the *act* is granting
#: something authority the credential itself carries, because there the
#: credential is a party to the decision rather than a way of transporting it.
CREDENTIAL_SESSION = CredentialKind.session.value
CREDENTIAL_API_KEY = CredentialKind.api_key.value
#: An installed plug-in's access token. Only a route that names a plug-in scope
#: admits one (:func:`plugin_scope`).
CREDENTIAL_INSTALL = "install"


def _key_overreached(
    request: Request, authenticated: Authenticated, scope: str
) -> None:
    """Write down an API key reaching past what it was made for. Refused, so
    there is no transaction to ride: the line goes now."""
    from app.core.audit_events import AuditEventType
    from app.services import audit as audit_service

    api_key = authenticated.api_key
    if api_key is None:
        return
    audit_service.emit(
        event_type=AuditEventType.API_KEY_SCOPE_VIOLATION,
        actor_user_id=authenticated.user.id,
        target_user_id=authenticated.user.id,
        target_type="api_key",
        target_id=api_key.id,
        detail={"scope": scope, "method": request.method},
    )


def _admit(
    request: Request,
    authenticated: Authenticated,
    resource: tuple[int, Tool, int] | None = None,
) -> User:
    """Hand the request the account a credential named, and say which
    credential it was.

    ``read_only`` API keys may only issue safe (non-mutating) HTTP methods,
    and a key that names one tool resource is admitted only by the route that
    serves that resource, which passes it as ``(guild_id, tool, id)``; those
    are the parts
    of a key's scope that need the request itself. The guild a key is limited
    to was recorded where it was read, and the guild-access gate applies it.
    """
    api_key = authenticated.api_key
    if (
        api_key is not None
        and api_key.read_only
        and request.method not in _SAFE_HTTP_METHODS
    ):
        _key_overreached(request, authenticated, "read_only")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=UserMessages.API_KEY_READ_ONLY,
        )
    names = (
        None
        if api_key is None or api_key.resource_type is None
        else (api_key.guild_id, api_key.resource_type, api_key.resource_id)
    )
    if names != resource:
        _key_overreached(request, authenticated, "resource")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=UserMessages.API_KEY_RESOURCE_ONLY,
        )
    request.state.credential = authenticated.kind.value
    audit_context.note_actor(authenticated.user.id)
    # Which session this request is: what lets an endpoint act on the
    # account's other ones and leave the caller where they are.
    if authenticated.session_id is not None:
        request.state.session_id = str(authenticated.session_id)
    return authenticated.user


async def _authenticate(
    request: Request,
    session: AsyncSession,
    identified: Identified | None,
    resource: tuple[int, Tool, int] | None = None,
) -> User:
    """The account the credential a request presented names, admitted."""
    # Nothing recorded until a credential is read, so a request that presents
    # none reads as something other than a session.
    auth_context.reset()
    request.state.credential = None
    if identified is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMessages.NOT_AUTHENTICATED,
            headers={"WWW-Authenticate": "Bearer"},
        )
    # A credential that cannot be read is 401 "please re-authenticate", not
    # 403: the SPA's 401 interceptor sends an expired session to /welcome.
    try:
        authenticated = await credentials.authenticate(session, identified)
    except CredentialRefused as exc:
        raise exc.as_http() from exc
    return _admit(request, authenticated, resource)


async def get_current_user(
    request: Request,
    session: SessionDep,
    bearer_token: Annotated[Optional[str], Depends(oauth2_scheme)] = None,
    session_cookie: Annotated[Optional[str], Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> User:
    # ``bearer_token`` and ``session_cookie`` declare the schemes for the API
    # description; the credential itself is read once, by ``identify``.
    return await _authenticate(request, session, identify(request))


def require_first_party_session(request: Request) -> str:
    """Refuse anything but the person's own sign-in, and report which kind.

    For the handful of actions that hand out authority rather than exercise it.
    Running unattended is the whole point of the credentials this excludes — a
    workflow acts at three in the morning, a script runs on a timer, and that is
    the feature. What they cannot do is set their own bounds: a grant is what
    says how far a standing credential reaches, so it is made by the person, in
    a session of their own, rather than by the thing being granted.

    Only a session qualifies: it is somebody signing in, on the web or in the
    app.

    Returns the credential kind, which is what a grant records as the factor it
    was confirmed by.
    """
    credential = getattr(request.state, "credential", None)
    if credential != CREDENTIAL_SESSION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AuthMessages.SESSION_REQUIRED,
        )
    return credential


async def get_current_user_optional(
    request: Request,
    session: SessionDep,
    bearer_token: Annotated[Optional[str], Depends(oauth2_scheme)] = None,
    session_cookie: Annotated[Optional[str], Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> User | None:
    try:
        return await get_current_user(request, session, bearer_token, session_cookie)
    except HTTPException:
        return None


async def _account_holds_factor(user: User, guild_id: int | None) -> bool:
    """Whether this account holds a second factor.

    Both credential stores are ``app_admin``-only, so the question goes to the
    system engine — the shape a personal API key's own lookup already uses —
    from the cohort of the community the request serves, if it serves one.

    Asked afresh each time rather than remembered against the request: the
    answer changes the moment somebody enrols, and that is exactly the moment
    they are trying to get back in.
    """
    async with cohorts.system_session(guild_id) as system_session:
        return await auth_posture.holds_second_factor(system_session, user_id=user.id)


async def platform_factor_unmet(
    session: AsyncSession,
    user: User,
    *,
    guild_id: int | None,
    level: SecondFactorRequirement | None = None,
) -> bool:
    """Whether the deployment asks this account for a second factor it lacks.

    Also records what this request answers with, which is what the database
    reads as ``app.platform_factor`` — so a path that never asks this question
    carries no standing and the rule is applied there too, by Postgres.

    Three answers, cheapest first. A session that presented a factor answers
    every level. A deployment that asks nothing of this account's rung asks
    nothing — which is every request on a deployment that asks nobody, so the
    credential stores are never read there at all. Only what is left reads
    them.

    ``level`` is what the deployment asks, where the caller already knows —
    the guild gate reads the settings row beside the membership it is checking,
    so the question costs that path no round trip of its own. Left out, it is
    what the credential validator recorded beside the account, and read here
    only where nothing was.

    ``guild_id`` is the community the request serves, or ``None``.
    """
    if SECOND_FACTOR_AMR in auth_context.current().session_amr:
        auth_context.record(platform_factor=True)
        return False
    if level is None:
        level = auth_context.current().asked_of_account
    if level is None:
        level = await auth_posture.second_factor_requirement(session)
    if not auth_posture.rule_covers(level, user.role):
        auth_context.record(platform_factor=True)
        return False
    held = await _account_holds_factor(user, guild_id)
    auth_context.record(platform_factor=held)
    return not held


async def _active_user(
    request: Request, current_user: User, *, admit_suspended: bool = False
) -> User:
    """The caller, if their account may hold a session at all.

    A *suspended* account may hold one: signing in is how its holder is told
    they are in time out. What it reaches is the time-out allow-list and
    nothing else — the routes that take :data:`AccountHolder` and its session,
    which read the account's own state. Every other route refuses it with
    ``ACCOUNT_SUSPENDED``, so a route written tomorrow is closed to it by
    default.
    """
    if current_user.status not in LOGIN_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER
        )
    if current_user.status == UserStatus.suspended and not admit_suspended:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AuthMessages.ACCOUNT_SUSPENDED,
        )
    # Whose request this is, for the few things that run before the endpoint
    # does and have only the request to read — see
    # ``app.core.rate_limit.get_user_or_ip_key``.
    request.state.user_id = current_user.id
    return current_user


async def get_current_active_user(
    request: Request,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """The caller, held to what this deployment asks of an account.

    The active-account check, and then the deployment's own second-factor
    rule: where it covers this account and the account holds nothing to answer
    it with, the request is refused with the same 401 a community's factor
    requirement answers with, and the same dialog asks for it.

    The refusal is a 401 rather than a 403 for the reason RFC 9470 gives: the
    session authenticated, and what is missing is a factor. It names no guild,
    because this one is the deployment's.
    """
    user = await _active_user(request, current_user)
    await _require_platform_factor(request, session, user)
    return user


async def _require_platform_factor(
    request: Request, session: AsyncSession, user: User
) -> None:
    guild_id = cohorts.addressed_guild_id(request.path_params)
    if await platform_factor_unmet(session, user, guild_id=guild_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=GuildMessages.PLATFORM_AUTH_FACTOR_REQUIRED,
            headers={"WWW-Authenticate": STEP_UP_CHALLENGE},
        )


async def get_current_account_holder(
    request: Request,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """The caller on a time-out allow-list route: active, or suspended.

    Held to the same second-factor rule as :func:`get_current_active_user`.
    The routes that take it read or close the account's own state — its
    sessions, its notifications — and nothing another person can see.
    """
    user = await _active_user(request, current_user, admit_suspended=True)
    await _require_platform_factor(request, session, user)
    return user


async def get_account_holder_exempt_from_factor(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """:func:`get_current_account_holder` for a factor-exempt route."""
    return await _active_user(request, current_user, admit_suspended=True)


async def get_ticket_holder(
    request: Request,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """The caller on a route that files or follows their own tickets.

    An active account is held to the deployment's second-factor rule, as on
    any route. A suspended one is not: its time-out screen, where it appeals
    and follows the appeal, is reachable without the factor, and it cannot
    enrol one while suspended. What it may do on these routes is the routes'
    own narrower question.
    """
    user = await _active_user(request, current_user, admit_suspended=True)
    if user.status != UserStatus.suspended:
        await _require_platform_factor(request, session, user)
    return user


#: The caller on a time-out allow-list route. See :func:`_active_user`.
AccountHolder = Annotated[User, Depends(get_current_account_holder)]
FactorExemptAccountHolder = Annotated[
    User, Depends(get_account_holder_exempt_from_factor)
]
#: The caller on the ticket routes. See :func:`get_ticket_holder`.
TicketHolder = Annotated[User, Depends(get_ticket_holder)]


async def get_active_user_exempt_from_factor(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """The caller, on a route that stays reachable while the rule is unmet.

    Reading who you are, setting a factor up, and presenting one: without
    these an account the rule covers could not act on it. Nothing guild-scoped
    is ever reached this way — those routes resolve their guild through
    ``_load_guild_context``, which asks the same question again.
    """
    return await _active_user(request, current_user)


CurrentUser = Annotated[User, Depends(get_current_active_user)]


async def refuse_demo_sample(
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """403 ``DEMO_SAMPLE_ACCOUNT`` for one of the demo's sample accounts, on a
    route that changes how it is signed in to, its devices or its sessions:
    those are shared by everyone who signs in to it. Asks nothing of anyone
    else, and nothing at all outside the demo."""
    if app_config.DEMO_MODE:
        from app.demo import samples

        await samples.refuse(current_user)


#: Route dependency: refuses the demo's sample accounts. See
#: :func:`refuse_demo_sample`.
NotDemoSample = Depends(refuse_demo_sample)


async def get_age_viewer(request: Request, current_user: CurrentUser) -> AgeViewer:
    """The person making the request, as a plug-in's minimum age reads them:
    their age from the kept date of birth, their country from the request."""
    return await plugin_age.viewer_for(request, current_user.id)


AgeViewerDep = Annotated[AgeViewer, Depends(get_age_viewer)]
#: For the handful of routes above. Everything else takes ``CurrentUser``.
FactorExemptUser = Annotated[User, Depends(get_active_user_exempt_from_factor)]


def require_capability(capability: Capability, *alternatives: Capability) -> Callable:
    """Dependency factory gating an endpoint on a platform capability, or on
    any one of several where each is reason enough.

    Access is expressed against the capability model rather than a hardcoded
    role name (see ``app.core.capabilities``).
    """
    accepted = (capability, *alternatives)

    async def dependency(
        current_user: Annotated[User, Depends(get_current_active_user)],
    ) -> User:
        if not any(user_has_capability(current_user, held) for held in accepted):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=AuthMessages.INSUFFICIENT_PRIVILEGES,
            )
        return current_user

    return dependency


# ``GuildContext`` is defined beside the standing it carries
# (:mod:`app.db.guild_standing`) so the routing that replays it can read it
# without importing this module. This is still the only place one is built.


class GuildAccessError(Exception):
    """Transport-agnostic "no access to this guild" signal.

    The single entry point (``establish_guild_access`` / ``_load_guild_context``)
    raises this instead of an ``HTTPException`` so the access decision stays
    independent of how the caller speaks to the client: the REST dependency maps
    it to ``HTTPException(403)``, a WebSocket handler maps it to a ``1008`` close,
    and the collaboration handover POST maps it the way REST does. It carries
    the machine-readable ``detail`` code so the REST mapping is byte-identical to
    the prior inline ``raise HTTPException``.
    """

    def __init__(
        self,
        detail: str = GuildMessages.COMMUNITY_ACCESS_DENIED,
        *,
        step_up_provider_slug: str | None = None,
        step_up_guild_id: int | None = None,
    ) -> None:
        self.detail = detail
        # Set for COMMUNITY_AUTH_STEP_UP_REQUIRED: which provider the session must
        # satisfy (X-Auth-Step-Up) and which guild's login flow serves it
        # (X-Auth-Step-Up-Community) — guild-scoped providers resolve their login
        # URL through the guild, not a global slug.
        self.step_up_provider_slug = step_up_provider_slug
        self.step_up_guild_id = step_up_guild_id
        super().__init__(detail)


def _sign_in(satisfied: frozenset[int], on_behalf: bool) -> SignIn:
    """How this request's session signed in, as the routing records it: the
    providers ``satisfied`` names, and the rest as the credential validator
    recorded it."""
    recorded = auth_context.current()
    return SignIn(
        providers=tuple(satisfied),
        claims=recorded.satisfied_claims,
        amr=recorded.session_amr,
        platform_factor=recorded.platform_factor,
        on_behalf=on_behalf,
    )


async def _enforce_guild_auth_policy(
    session: AsyncSession,
    policy: SignInHalf | None,
    guild_id: int,
    satisfied: frozenset[int],
    markers: frozenset[str] = frozenset(),
    *,
    require_second_factor: bool = False,
) -> None:
    """Gate 0 of guild access: the guild's
    sign-in policy must be satisfied by THIS session — membership and PAM
    grants alike. No policy row (or ``open``) admits any authenticated
    session.

    Decided by ``public.guild_auth_satisfied()``, which the standing statement
    asks for every request. This is the same rule read in Python, run once the
    standing has said no, to name the step-up the session owes.

    A row can ask two things and a session has to answer both. ``provider_id``
    names one provider the session must have come through; ``require_methods``
    asks for any of this community's connections without naming which. Both
    are one question to ``guild_connection_admits``, which also applies the
    narrowing a community put on the connection.

    ``policy`` is the half of the guild's row that applies to this request
    (its guests' for a guest), read under the routed session. A second factor
    the community asks for applies while it holds the option it needs, read as
    the database gate reads it.
    """
    restricts, factors_apply = (
        await session.exec(
            select(
                guild_entitlements.holds_option(
                    guild_id, CommunityAuthOption.restrictions
                ),
                guild_entitlements.holds_option(
                    guild_id, CommunityAuthOption.providers
                ),
            )
        )
    ).one()
    # Asked of everybody reaching this community, whatever it says about how
    # they arrive — so it is read before a community with no sign-in rule
    # returns. The answer names no provider and no kind of factor: the
    # step-up says a factor is what is wanted.
    if require_second_factor and restricts and SECOND_FACTOR_AMR not in markers:
        raise GuildAccessError(
            GuildMessages.COMMUNITY_AUTH_FACTOR_REQUIRED,
            step_up_guild_id=guild_id,
        )
    if policy is None or policy.policy == "open":
        return

    def _refuse() -> None:
        raise GuildAccessError(
            detail=GuildMessages.COMMUNITY_AUTH_STEP_UP_REQUIRED,
            step_up_provider_slug=policy.provider_slug,
            step_up_guild_id=guild_id,
        )

    if (
        policy.provider_id is not None
        and not await guild_connections.admits_this_session(
            session, guild_id=guild_id, provider_id=policy.provider_id
        )
    ):
        _refuse()

    # "Any of ours": any connection this community holds, narrowing included.
    # Named rather than counted: ``require_methods`` may hold more than one
    # method, and each is read as itself. The matching leg in
    # ``public.guild_auth_satisfied()`` reads the same row.
    if LoginMethod.sso in policy.require_methods and not (
        await guild_connections.admits_this_session(session, guild_id=guild_id)
    ):
        _refuse()

    # And the account's own second factor, where the community asks for one.
    # The answer names no provider, so the step-up says a factor is what is
    # wanted rather than pointing at a sign-in page.
    if (
        factors_apply
        and LoginMethod.totp in policy.require_methods
        and SECOND_FACTOR_AMR not in markers
    ):
        raise GuildAccessError(
            GuildMessages.COMMUNITY_AUTH_FACTOR_REQUIRED,
            step_up_guild_id=guild_id,
        )

    # And a passkey, where the community asks for one. Read from the passkey
    # markers rather than the factor's, so each method is answered by itself:
    # an assertion records the second factor as well as the key.
    if (
        factors_apply
        and LoginMethod.passkey in policy.require_methods
        and not carries_passkey(markers)
    ):
        raise GuildAccessError(
            GuildMessages.COMMUNITY_AUTH_PASSKEY_REQUIRED,
            step_up_guild_id=guild_id,
        )


def pinned_elsewhere(guild_id: int) -> bool:
    """Whether this request's API key is limited to a guild other than
    ``guild_id``. False for a key limited to no guild and for every other
    credential."""
    pinned = auth_context.current().api_key_guild_id
    return pinned is not None and pinned != guild_id


async def _enforce_guild_api_access(
    session: AsyncSession, membership: GuildMembership
) -> None:
    """A member whose API access the community turned off does not reach it
    with a personal API key (:func:`guild_entitlements.accepts_api_keys`).

    Runs beside the sign-in gate, for members. A grantee is never reached with
    a personal API key at all; the grant branch refuses one before this. The
    key's own ``guild_id`` says nothing here: a key pinned elsewhere and a key
    pinned nowhere both address this guild the same way.

    Covers every path that resolves its guild through
    :func:`_load_guild_context`: REST, uploads and file downloads, subscription
    feeds, the realtime sockets and the keepalive. The cross-guild aggregates,
    which pick their guilds themselves, ask the same question where they do it.
    """
    if auth_context.current().api_key_credential and (
        await guild_entitlements.refuses_api_keys(session, membership)
    ):
        raise GuildAccessError(detail=GuildMessages.COMMUNITY_API_KEYS_REFUSED)


async def _read_membership_gate(
    session: AsyncSession, guild_id: int, user_id: int
) -> tuple[GuildMembership, Guild, SecondFactorRequirement, bool] | None:
    """The three rows the gate needs about a member, in one query.

    ``guild_memberships`` and ``guilds`` both live in ``public`` and are both
    keyed on the guild this request addresses, so asking for them separately
    was two trips for one answer. The settings singleton rides along for the
    same reason — what the deployment asks of an account is
    decided in the same breath as what the community asks of the session, and a
    read of its own would be a round trip on every guild request there is.

    Each row still comes back under its own policies — an outer join to a row
    the session may not read yields NULL, exactly as its own SELECT would have.
    ``None`` means no membership the session can see, which is the grant
    branch's cue.
    """
    row = (
        await session.exec(
            select(GuildMembership, Guild, AppSetting)
            .select_from(GuildMembership)
            .outerjoin(Guild, Guild.id == GuildMembership.guild_id)
            .outerjoin(AppSetting, AppSetting.id == GLOBAL_SETTINGS_ID)
            .where(
                GuildMembership.guild_id == guild_id,
                GuildMembership.user_id == user_id,
                live_membership_clause(),
            )
        )
    ).one_or_none()
    if row is None:
        return None
    membership, guild, settings_row = row
    if guild is None:
        raise ValueError(GuildMessages.COMMUNITY_NOT_FOUND)
    # The age switch rides along for the same reason the factor requirement
    # does: it is decided from this same row, and reading it separately would
    # be a round trip on every guild request there is.
    age_gate_on = bool(
        settings_row is not None and settings_row.community_age_gate_enabled
    )
    return membership, guild, asked_of_an_account(settings_row), age_gate_on


async def _read_grant_gate(
    session: AsyncSession, guild_id: int
) -> tuple[Guild, SecondFactorRequirement]:
    """The same public rows for a grantee, whose PAM context has just been
    applied — a grant reaches the guild row through its own policy leg, so this
    read cannot be folded into the membership one above."""
    row = (
        await session.exec(
            select(Guild, AppSetting)
            .select_from(Guild)
            .outerjoin(AppSetting, AppSetting.id == GLOBAL_SETTINGS_ID)
            .where(Guild.id == guild_id)
        )
    ).one_or_none()
    if row is None:
        raise ValueError(GuildMessages.COMMUNITY_NOT_FOUND)
    return row[0], asked_of_an_account(row[1])


async def _load_guild_context(
    session: AsyncSession,
    current_user: User,
    guild_id: int,
    *,
    for_settings: bool = False,
    for_payment: bool = False,
    factor_asked: bool = False,
) -> GuildContext:
    """Resolve and validate the guild context for one guild.

    ``guild_id`` is the single guild the request operates in (on REST it comes
    from the ``/c/{community_id}/...`` path, which is only a selector, never a trust
    boundary). Access is validated fresh on every call — real membership or a
    live PAM grant, else ``GuildAccessError`` — so a stale or mistyped guild id
    fails closed. The caller has already coerced ``guild_id`` to ``int``; it
    names the role and ``search_path`` the session assumes.

    Transport-agnostic: it takes only the resolved ``guild_id``. A personal
    API key limited to one guild is refused every other one here, so the rule
    holds on every surface that resolves a guild through this function.

    ``for_settings`` is the community's own configuration surface, which a
    guild administrator keeps while its content is frozen: a ``read_only``
    community, and one whose sign-in policy this session does not answer, still
    has an administrator to run it. A community outside the live statuses has
    no settings surface for its members either — it is in time out, and only
    the platform brings it back. It reads the same way on both branches below,
    membership and grant. The rung guard on those routes has already refused
    anyone who does not administer it; what this establishes is the standing
    the database reads.

    ``for_payment`` is the billing handoff, the one way a community held for
    a late payment is paid out of the hold: it admits the seat's own
    membership into an ``on_hold`` community as well as a live one. Every
    other status, and every other member, is refused as before.

    ``factor_asked`` says this request's :func:`get_current_active_user`
    already put the deployment's second-factor question, so it is not put
    twice. Only a REST dependency that takes that one passes it.
    """
    # A suspended account reaches no guild. Ahead of the branches below so it
    # holds for membership and for a grant alike, and it answers with the same
    # generic code every other refusal here uses, so a guild is not told that
    # one of its members was suspended. Nothing is revoked: the membership is
    # still theirs when the suspension lifts.
    if current_user.status == UserStatus.suspended:
        raise GuildAccessError()
    if pinned_elsewhere(guild_id):
        raise GuildAccessError()

    # Establish the caller context before loading their membership.
    await set_rls_context(session, Platform(user_id=current_user.id))

    gate = await _read_membership_gate(session, guild_id, current_user.id)
    if gate is None:
        # Resolve live grants when the caller has no membership.
        grants = await access_grants_service.get_live_grants(
            session, user_id=current_user.id, guild_id=guild_id
        )
        grant = grants.get(AccessGrantPurpose.content)
        # A settings grant reaches the community's configuration and nothing
        # of its work, so a content request needs the content grant.
        if grant is None and not for_settings:
            raise GuildAccessError()
        settings_grant = grants.get(AccessGrantPurpose.settings)
        if grant is None and settings_grant is None:
            raise GuildAccessError()
        # A grant is reached by the person in a session of their own, never
        # with a personal API key, whatever the community's options.
        if auth_context.current().api_key_credential:
            raise GuildAccessError(detail=GuildMessages.COMMUNITY_API_KEYS_REFUSED)
        is_read_write = (
            grant is not None and grant.access_level == AccessLevel.read_write.value
        )
        # Establish the grant context before loading guild metadata.
        await set_rls_context(
            session,
            ContentGrantee(
                guild_id=guild_id, user_id=current_user.id, read_write=is_read_write
            ),
        )
        guild, asked = await _read_grant_gate(session, guild_id)
        # What the deployment asks of the account, before what this community
        # asks of the session. Asked here as well as in the dependency above
        # because the sockets, the keepalive and the stream re-check resolve
        # their guild through this function and never run that one — off the
        # row the read above already carried.
        if not factor_asked and await platform_factor_unmet(
            session, current_user, guild_id=guild_id, level=asked
        ):
            raise GuildAccessError(GuildMessages.PLATFORM_AUTH_FACTOR_REQUIRED)
        # A grantee holds no membership row, and none is invented for them:
        # what the two grants reach is computed from the rows themselves by
        # the standing statement. ``context.role`` answers ``support`` — the
        # identity granted access carries — and clears no guard of its own.
        return GuildContext(
            guild=guild,
            user_id=current_user.id,
            guild_id=guild_id,
            grant=grant,
            settings_grant=settings_grant,
            settings_grant_level=(
                None if settings_grant is None else settings_grant.access_level
            ),
        )
    membership, guild, asked, age_gate_on = gate
    # Membership access respects the guild's lifecycle status: the statuses
    # that serve members are named, and every other one is refused, on every
    # surface. A suspended community is in time out — its administrators are
    # members like any other until the platform lifts it. The seat of a
    # community on hold is let through to pay its way out, on the route that
    # asks for that and no other.
    held_for_payment = (
        for_payment
        and guild.status == CommunityStatus.on_hold.value
        and membership.role == CommunityRole.superadmin
    )
    if guild.status not in LIVE_STATUS_VALUES and not held_for_payment:
        raise GuildAccessError()
    await _enforce_guild_api_access(session, membership)
    # A listed community is open to anyone signed in, so the deployment's age
    # question is owed by the people in it — and the ways in that had nobody at
    # a keyboard could not put it to them. It is put here instead: at the door
    # of the community it is for, and nowhere else. A private community never
    # asks, and neither does the rest of the platform.
    #
    # Free in the common case: it stops on the account's own column, which is
    # already loaded, for everyone who has answered.
    if (
        not for_settings
        and current_user.age_confirmed_at is None
        and guild.is_community
        and age_gate_on
    ):
        raise GuildAccessError(
            GuildMessages.AGE_BELOW_MINIMUM
            if current_user.age_below_minimum_at is not None
            else GuildMessages.AGE_CONFIRMATION_REQUIRED
        )
    # And the deployment's own question, off the row the gate read carried.
    if not factor_asked and await platform_factor_unmet(
        session, current_user, guild_id=guild_id, level=asked
    ):
        raise GuildAccessError(GuildMessages.PLATFORM_AUTH_FACTOR_REQUIRED)
    return GuildContext(
        guild=guild,
        user_id=current_user.id,
        guild_id=guild_id,
        membership=membership,
        guild_role=membership.role.value,
        content_read_only=(
            not for_settings and guild.status == CommunityStatus.read_only.value
        ),
    )


#: The community a ``/c/{community_id}`` or ``/communities/{community_id}``
#: route addresses. Handlers keep the Python name ``guild_id``.
CommunityIdPath = Annotated[
    int, Path(alias="community_id", description="Community this request addresses")
]


async def get_guild_membership(
    request: Request,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_id: CommunityIdPath,
) -> GuildContext:
    """The establishment seam for a REST request: who this reader is in the
    community the path addresses, and the session routed to match.

    Every guild-scoped router mounts under ``/c/{community_id}``, so FastAPI injects
    the segment here. Membership (or a live PAM grant) is validated fresh; a
    non-member or stale grant gets 403. A guild-scoped route mounted *outside*
    the prefix fails at startup (missing path param) — a useful guard that every
    such route is path-addressed.

    The context it returns carries the standing computed in the routed schema,
    so it is resolved and applied together rather than in two steps that could
    disagree. ``RLSSessionDep`` is the other half of this one call: FastAPI
    caches a dependency per request, so it hands back the session this routed.
    """
    try:
        return await establish_guild_access(
            session, current_user, guild_id, factor_asked=True
        )
    except GuildAccessError as exc:
        raise_for_guild_access(exc)


GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


def raise_for_guild_access(exc: GuildAccessError) -> NoReturn:
    """Turn a refusal from the seam into the response it owes the caller.

    Three shapes: the two step-up 401s, which say what is missing and where to
    present it, and 403 for everything else.
    """
    if exc.detail in (
        GuildMessages.COMMUNITY_AUTH_FACTOR_REQUIRED,
        GuildMessages.COMMUNITY_AUTH_PASSKEY_REQUIRED,
        GuildMessages.PLATFORM_AUTH_FACTOR_REQUIRED,
    ):
        # 401 for the same reason as the provider step-up below, and apart
        # from it because what satisfies these is presented against the
        # session already open rather than a sign-in page to visit. RFC
        # 9470 all the same: the session authenticated, and what is missing
        # is a factor. The detail says which of the two, so the dialog
        # knows whether to ask for a code or run a ceremony.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=exc.detail,
            headers={
                "WWW-Authenticate": STEP_UP_CHALLENGE,
                "X-Auth-Step-Up-Community": (
                    str(exc.step_up_guild_id)
                    if exc.step_up_guild_id is not None
                    else ""
                ),
            },
        ) from exc
    if exc.detail == GuildMessages.COMMUNITY_AUTH_STEP_UP_REQUIRED:
        # 401, not 403: the session lacks an auth factor, not a permission.
        #
        # Said twice, for two audiences. ``WWW-Authenticate`` is the
        # standard form (RFC 9470), which an OAuth client library can act
        # on knowing nothing about this app. The ``X-Auth-Step-Up`` pair
        # names *which* provider serves the factor and which guild's login
        # flow reaches it — ours to answer, and what our own SPA reads.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=exc.detail,
            headers={
                "WWW-Authenticate": STEP_UP_CHALLENGE,
                "X-Auth-Step-Up": exc.step_up_provider_slug or "",
                "X-Auth-Step-Up-Community": (
                    str(exc.step_up_guild_id)
                    if exc.step_up_guild_id is not None
                    else ""
                ),
            },
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail=exc.detail
    ) from exc


def holds_guild_role(
    context: GuildContext, *roles: CommunityRole, settings: bool = False
) -> bool:
    """Whether this request reaches any of ``roles``, by the standing.

    :meth:`GuildContext.reaches` is the one answer — a rung asked for is that
    rung or above, and on the configuration surface (``settings``) a settings
    grant answers at the rung it lends — and this is its form for a guard
    naming several. Kept beside :func:`require_guild_roles` because some
    endpoints ask part-way through a handler rather than at the door, and the
    two must not drift.
    """
    if not roles:
        return True
    return any(context.reaches(role, settings=settings) for role in roles)


def require_seat(
    context: GuildContext, *, detail: str = GuildMessages.COMMUNITY_SUPERADMIN_REQUIRED
) -> None:
    """Raise 403 unless this request holds the community's seat, by the
    standing — the membership row's, or lent by a settings grant at that
    rung."""
    if not context.guild_seat:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _rung_refusal(roles: tuple[CommunityRole, ...]) -> str:
    """The code a guard answers with, from the rung it names: a guard for
    the seat says so, one for an administrator says so, and one naming
    anything else says a permission is missing."""
    if roles == (CommunityRole.superadmin,):
        return GuildMessages.COMMUNITY_SUPERADMIN_REQUIRED
    if roles == (CommunityRole.admin,):
        return GuildMessages.COMMUNITY_ADMIN_REQUIRED
    return GuildMessages.COMMUNITY_PERMISSION_REQUIRED


def require_guild_roles(
    *roles: CommunityRole, settings: bool = False, write: bool = False
) -> Callable:
    """Guard an endpoint on the caller's rung in the guild named by the path.

    See :func:`holds_guild_role`, which is what it asks. ``settings`` puts the
    guard on the community's configuration surface — established by
    :func:`get_guild_settings_context`, which a settings grant may serve and
    an administrator keeps while the content is closed. ``write`` is a route
    that changes something: a grantee is then also asked for the
    ``read_write`` grant beside the rung (:func:`require_grant_writes`).
    The refusal's code comes from the rung named (:func:`_rung_refusal`).
    """
    establish = get_guild_settings_context if settings else get_guild_membership
    detail = _rung_refusal(roles)

    async def dependency(
        context: Annotated[GuildContext, Depends(establish)],
    ) -> GuildContext:
        if not holds_guild_role(context, *roles, settings=settings):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
        if write:
            require_grant_writes(context)
        return context

    return dependency


GuildAdminContext = Annotated[
    GuildContext, Depends(require_guild_roles(CommunityRole.admin))
]


def _note_privileged_request(current_user: User, guild_context: GuildContext) -> None:
    """Record on the request's own context which grant is serving it.

    Read back when the response is finished, to write the one line that says
    what this request did with the grant (``app.core.request_audit``).
    """
    grant, settings_grant = guild_context.grant, guild_context.settings_grant
    issued = grant or settings_grant
    audit_context.note_grant(
        actor_user_id=current_user.id,
        guild_id=guild_context.guild_id,
        grant_id=grant.id if grant is not None else None,
        access_level=grant.access_level if grant is not None else None,
        settings_grant_id=settings_grant.id if settings_grant is not None else None,
        settings_level=(
            settings_grant.access_level if settings_grant is not None else None
        ),
        break_glass=(
            issued.requested_by_id == issued.approved_by_id
            if issued is not None
            else None
        ),
    )


async def apply_guild_session_context(
    session: AsyncSession,
    current_user: User,
    guild_context: GuildContext,
    satisfied: frozenset[int] = frozenset(),
    *,
    on_behalf: bool = False,
    for_seat: bool = False,
) -> GuildContext:
    """Route ``session`` into ``guild_context``'s community and compute the
    reader's standing there, returning the context that says what it is.

    The second and third of the seam's three round trips. The first — the
    lookup that decided there is any access at all, and which Postgres role
    this assumes — has already run (:func:`_load_guild_context`), and what it
    found is the ``guild_context`` handed in here.

    The routing writes the community, the credential and an empty standing.
    The standing statement then fills it, in the routed schema, from the
    database's own rows. Between the two the standing answers no to every
    membership leg, so a routing that stops half-way loses rows rather than
    gaining them.

    ``for_seat`` is the four configuration routes asking for the seat's role
    rather than the community's. It is honoured only where the seat is within
    reach; holding it and asking for it are two conditions, and an ordinary
    request by a seat holder routes as an ordinary member.
    """

    seat = for_seat and guild_context.reaches_seat

    if guild_context.is_settings_only:
        _note_privileged_request(current_user, guild_context)
        await set_rls_context(
            session,
            SettingsGrantee(
                guild_id=guild_context.guild_id,
                user_id=current_user.id,
                standing=guild_context,
                tier=current_user.role.value,
                sign_in=_sign_in(satisfied, on_behalf),
                seat=seat,
            ),
        )
        return await apply_guild_standing(session, guild_context)

    if guild_context.is_pam:
        _note_privileged_request(current_user, guild_context)
        # The routing needs the grant's level to pick the Postgres role; the
        # statement below recomputes the flags the policies read from the
        # grant rows, so what a leg answers to is the row rather than what the
        # lookup carried out of it.
        grant = guild_context.grant
        access_level = (
            grant.access_level if grant is not None else AccessLevel.read.value
        )
        await set_rls_context(
            session,
            ContentGrantee(
                guild_id=guild_context.guild_id,
                user_id=current_user.id,
                standing=guild_context,
                read_write=access_level == AccessLevel.read_write.value,
                # Break-glass is a pair: a settings grant beside the content
                # grant, into the same community.
                settings=guild_context.settings_grant is not None,
                tier=current_user.role.value,
                sign_in=_sign_in(satisfied, on_behalf),
                seat=seat,
            ),
        )
        return await apply_guild_standing(session, guild_context)

    await set_rls_context(
        session,
        Member(
            guild_id=guild_context.guild_id,
            user_id=current_user.id,
            standing=guild_context,
            # Recorded, not routed with: the community's own role governs
            # inside the schema. It is what a later hop back out to ``public``
            # re-assumes.
            tier=current_user.role.value,
            sign_in=_sign_in(satisfied, on_behalf),
            # Community in read_only status: the membership legs evaluate
            # normally but the session assumes the SELECT-only role, so content
            # writes are refused by Postgres rather than by app code.
            read_only=guild_context.content_read_only,
            seat=seat,
        ),
    )
    return await apply_guild_standing(session, guild_context)


async def get_guild_settings_context(
    request: Request,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_id: CommunityIdPath,
) -> GuildContext:
    """The establishment seam for a request to the community's own
    configuration and roster.

    :func:`get_guild_membership` for the surface an administrator keeps while
    the content is closed, and the one a settings grant may serve: the same
    lookup, routing and standing, established ``for_settings`` — so the
    community's sign-in rule, a ``read_only`` freeze and the deployment's age
    question, which govern its work, do not stand between an administrator and
    the settings that govern them. A suspended community has no settings
    surface for its members: it is in time out.
    """
    try:
        return await establish_guild_access(
            session, current_user, guild_id, for_settings=True, factor_asked=True
        )
    except GuildAccessError as exc:
        raise_for_guild_access(exc)


async def get_guild_session(
    session: SessionDep,
    _guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> AsyncSession:
    """The session :func:`get_guild_membership` routed, for content requests.

    The routing and the standing are applied there — one seam call, of which
    this is the other half. Context is transaction-local and replayed at the
    start of every transaction (see ``app.db.session``), so post-commit queries
    need no manual re-apply.
    """
    return session


async def get_guild_settings_session(
    session: SessionDep,
    _guild_context: Annotated[GuildContext, Depends(get_guild_settings_context)],
) -> AsyncSession:
    """The session :func:`get_guild_settings_context` routed, for the
    community's configuration and roster."""
    return session


async def get_guild_settings_write_session(
    session: SessionDep,
    guild_context: Annotated[GuildContext, Depends(get_guild_settings_context)],
) -> AsyncSession:
    """The same session, for a configuration route that changes something: a
    grantee is asked for the ``read_write`` grant beside the rung."""
    require_grant_writes(guild_context)
    return session


async def establish_guild_access(
    session: AsyncSession,
    current_user: User,
    guild_id: int,
    satisfied_providers: frozenset[int] | None = None,
    *,
    on_behalf: bool = False,
    for_settings: bool = False,
    for_seat: bool = False,
    for_payment: bool = False,
    factor_asked: bool = False,
) -> GuildContext:
    """Resolve guild access AND apply the session context — the single entry
    point for callers that can't use the REST dependency chain.

    *Resolve* access (membership / live PAM / break-glass, else
    ``GuildAccessError``), *route* the session and *compute the standing*,
    returning the completed ``GuildContext``. REST reaches the same three steps
    through ``get_guild_membership``; WebSocket and keepalive handlers call this
    so they cannot resolve-without-applying — the omission that denied a guild
    admin on the collaboration socket while the REST read allowed them. The caller maps ``GuildAccessError`` to its transport
    (REST → 403, WebSocket → 1008, keepalive → soft error body).

    ``satisfied_providers`` feeds the guild auth-policy gate and the
    ``app.satisfied_providers`` GUC. ``None`` (the default) reads the ambient
    ``auth_context`` the credential validator recorded — right for every path
    serving a live session. The stream re-auth sweep passes the set captured
    at socket join.

    ``on_behalf`` is work a job does as the person who asked for it — an
    export, an import, a published view drawn as its author, a digest. Their
    own request met the community's sign-in rule when it was made, so the
    routing answers that rule for them; membership, grants and the standing
    are resolved exactly as for the person themselves.

    ``for_payment`` and ``factor_asked`` are :func:`_load_guild_context`'s.
    """
    satisfied = (
        auth_context.current().satisfied_providers
        if satisfied_providers is None
        else satisfied_providers
    )
    guild_context = await _load_guild_context(
        session,
        current_user,
        guild_id,
        for_settings=for_settings,
        for_payment=for_payment,
        factor_asked=factor_asked,
    )
    looked_up = save_rls_context(session)
    guild_context = await apply_guild_session_context(
        session,
        current_user,
        guild_context,
        satisfied=satisfied,
        on_behalf=on_behalf,
        for_seat=for_seat,
    )
    # The community's sign-in rule governs its work, not the surface that sets
    # the rule: an administrator keeps that one while their session does not
    # answer it.
    if not for_settings and not guild_context.guild_auth_ok:
        try:
            await _refuse_sign_in(session, guild_context, satisfied)
        except GuildAccessError:
            # Refused, the session goes back to the lookup's context, as a
            # refusal before routing leaves it: a caller that carries on with
            # it is not left inside the community.
            await restore_rls_context(session, looked_up)
            raise
    return guild_context


async def _refuse_sign_in(
    session: AsyncSession, guild_context: GuildContext, satisfied: frozenset[int]
) -> NoReturn:
    """Refuse a session the standing says does not answer the community's
    sign-in rule, saying what it is missing.

    The standing statement answered the question from the rows; this reads the
    rule, under the routing, to name the step-up the caller owes.
    """
    guild_id = guild_context.guild_id
    row = await session.get(GuildAuthPolicy, guild_id)
    await _enforce_guild_auth_policy(
        session,
        row.half(guild_context.routes_as_guest) if row is not None else None,
        guild_id,
        satisfied,
        auth_context.current().session_amr,
        require_second_factor=guild_context.guild.require_second_factor,
    )
    raise GuildAccessError()


@dataclass(frozen=True)
class VerifiedInstall:
    """An install whose token has been verified: the community it is installed
    in, the install, the client the token was issued to, the scopes it carries,
    the one initiative it is narrowed to, when it is, and, for a member token,
    the member it acts for and the purpose they consented to."""

    guild_id: int
    install_id: int
    client_id: str
    scopes: frozenset[str]
    initiative_id: int | None = None
    user_id: int | None = None
    purpose: str | None = None


class InstallAccessError(Exception):
    """Transport-agnostic "this install may not act here" signal.

    Raised by :func:`establish_install_access` when the install's standing is
    not live, or its community cannot be routed into. The route dependency maps
    it to 401.
    """


class FilerAccessError(Exception):
    """There is no operations community to read a filed case in."""


async def establish_filer_access(session: AsyncSession, user: User) -> int:
    """Route ``session`` as ``user`` reading the cases they filed — the
    establishment seam for a filer, beside :func:`establish_guild_access`.

    Into the operations community's ``guild_<id>_filer`` role, which is what
    decides what they read; nothing is looked up for them first, because a
    filer has no standing to compute. ``session`` comes from that community's
    cohort on the request engine. Returns the community's id.

    Raises :class:`FilerAccessError` where no operations community is set, or
    it has no filer role to assume.
    """
    from app.services.platform.intake import configured_operations_guild_id

    guild_id = await configured_operations_guild_id()
    if guild_id is None:
        raise FilerAccessError("no operations community")
    try:
        await set_rls_context(session, Filer(guild_id=guild_id, user_id=int(user.id)))
        # Their cases, read through the role's own row on intake_cases: the
        # one read the other filer rows are then keyed on.
        cases = (
            await session.exec(
                sa_text("SELECT task_id FROM intake_cases ORDER BY task_id")
            )
        ).all()
        # End the transaction, which leaves the role, before routing again:
        # the role holds nothing to write a routing with.
        await session.rollback()
        await set_rls_context(
            session,
            Filer(
                guild_id=guild_id,
                user_id=int(user.id),
                cases=tuple(row[0] for row in cases),
            ),
        )
    except DBAPIError as exc:
        clear_rls_context(session)
        await session.rollback()
        raise FilerAccessError("operations community cannot be routed") from exc
    return guild_id


async def establish_install_access(
    session: AsyncSession,
    install: VerifiedInstall,
    named_refs: Sequence[str] = (),
) -> InstallContext:
    """Route ``session`` as an installed plug-in and compute its standing — the
    establishment seam for an install, beside :func:`establish_guild_access`.
    On a request, ``session`` is the one :func:`get_session` hands out, which
    is from the cohort of the community the install's token names.

    Two statements and no lookup ahead of them: the routing (the community's
    ``guild_<id>_plugin`` role, the install, its client, its token's scopes, the
    narrowed initiative and, for a member token, the member and the purpose,
    all from ``install``), and the install standing statement, which reads
    everything else from rows — for a member token, the member's membership,
    account and consent among them. The context it returns
    is what that statement computed, and is stored with the routing for the
    replay hook.

    ``named_refs`` are the references the request names. The standing
    statement resolves them in the install's own sector and returns them on
    the context (``named_refs``), with the install's community reference; they
    choose rows to look up and decide nothing about access.

    Raises :class:`InstallAccessError` when the standing is not live — the
    community is not in use, the install or its registration is off, the
    registration is not the client the token names, or a member token's member
    has left, is not active or has no live consent — and when the community
    has no role or schema to route into. The session is left unrouted after a
    refusal of the second kind, with its transaction rolled back.
    """
    try:
        scopes = validate_scopes(install.scopes)
    except UnknownPluginScope as exc:
        raise InstallAccessError("unknown scope") from exc
    pending = InstallContext(
        guild_id=int(install.guild_id),
        install_id=int(install.install_id),
        client_id=install.client_id,
        token_scopes=scopes,
        scope_initiative_id=(
            int(install.initiative_id) if install.initiative_id is not None else None
        ),
        member_user_id=int(install.user_id) if install.user_id is not None else None,
        purpose=install.purpose if install.user_id is not None else None,
    )
    try:
        await set_rls_context(
            session,
            Install(
                guild_id=pending.guild_id,
                install_id=pending.install_id,
                standing=pending,
                token_client_id=pending.client_id,
                token_scopes=pending.token_scopes,
                scope_initiative_id=pending.scope_initiative_id,
                member_user_id=pending.member_user_id,
                token_purpose=pending.purpose,
            ),
        )
        completed = await apply_install_standing(session, pending, named_refs)
    except DBAPIError as exc:
        # A community that was deleted has no role left to assume and no schema
        # to read, which is the same answer as an install that may not act.
        clear_rls_context(session)
        await session.rollback()
        raise InstallAccessError("community cannot be routed") from exc
    if not completed.live:
        raise InstallAccessError("install is not live")
    return completed


#: The attribute a scoped route's dependency carries its scope on, for a walk
#: over the routes.
PLUGIN_SCOPE_ATTRIBUTE = "__plugin_scope__"
#: Every scope the dependency may ask of a request, for the same walk: the one
#: scope of :func:`plugin_scope`, each of :func:`plugin_scope_by`'s and of
#: :func:`plugin_scope_checked`'s.
PLUGIN_SCOPES_ATTRIBUTE = "__plugin_scopes__"
#: What the dependency declares, as the API's documents publish it: the scope
#: of :func:`plugin_scope`; the parameter and its scope per value of
#: :func:`plugin_scope_by` (``{"by": …, "scopes": {…}}``); what decides
#: :func:`plugin_scope_checked`'s and the scopes it may ask (``{"per": …,
#: "any_of": […]}``).
PLUGIN_SCOPE_DECLARATION_ATTRIBUTE = "__plugin_scope_declaration__"


def _refuse_install_credential() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _strings_in(value: Any) -> list[str]:
    """Every string in a parsed JSON document, keys included."""
    found: list[str] = []
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, str):
            found.append(current)
        elif isinstance(current, dict):
            pending.extend(current.keys())
            pending.extend(current.values())
        elif isinstance(current, list):
            pending.extend(current)
    return found


async def _named_refs(request: Request) -> list[str]:
    """The references an installed plug-in's request names: in its path, its query
    string and its JSON body, a mention in its text included.

    Read before FastAPI validates any of them, so the standing statement can
    resolve them in the same round trip. Starlette keeps the body it read, so
    the route reads the same bytes after this. A body that is not JSON names
    nobody here; FastAPI answers for it.
    """
    values: list[str] = [str(v) for v in request.path_params.values()]
    values.extend(v for _, v in request.query_params.multi_items())
    content_type = request.headers.get("content-type", "")
    if "json" in content_type and await request.body():
        try:
            strings = _strings_in(await request.json())
        except ValueError:
            strings = []
        values.extend(strings)
        values.extend(ref for text in strings for ref in written_mention_refs(text))
    return named_ref_candidates(values)


async def _establish_install_request(
    request: Request, session: AsyncSession, scope: str | None
) -> InstallContext:
    """Admit an installed plug-in's request to a route that names ``scope``, or
    to an :func:`plugin_scope_checked` route, which names none here (``None``)
    and checks what the request asks for itself.

    The token is read locally; nothing reaches the database until it has been
    unsealed and found to be an installation token. Then the seam routes the
    request's session as the install and computes its standing, the two
    statements an install pays before its handler. The standing statement also
    resolves the references the request names, which the route's identity
    types read while FastAPI validates it (``app.core.identity_boundary``).
    """
    unsealed = bearer_plugin_token(request)
    if not isinstance(unsealed, InstallAccessToken):
        raise _refuse_install_credential()

    install = VerifiedInstall(
        guild_id=unsealed.guild_id,
        install_id=unsealed.install_id,
        client_id=unsealed.client_id,
        scopes=unsealed.scopes,
        initiative_id=unsealed.initiative_id,
        user_id=unsealed.user_id,
        purpose=unsealed.purpose,
    )
    named = await _named_refs(request)
    try:
        context = await establish_install_access(session, install, named)
    except InstallAccessError as exc:
        raise _refuse_install_credential() from exc

    request.state.credential = CREDENTIAL_INSTALL
    audit_context.note_install(
        plugin=context.client_id,
        guild_id=context.guild_id,
        install_id=context.install_id,
    )
    # Whose request this is, for the rate limiter's key (see
    # ``app.core.rate_limit.get_user_or_ip_key``).
    request.state.plugin_install = (
        context.client_id,
        context.guild_id,
        context.install_id,
    )
    # Asked of what the standing holds — the token's scopes and the seat's
    # grant together, with writes off in a read-only community — so a scope
    # the seat has since taken back answers here on the next request.
    if scope is not None and not context.holds(scope):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PluginMessages.SCOPE_REQUIRED,
        )
    admit_install(
        InstallBoundary(
            guild_id=context.guild_id,
            install_id=context.install_id,
            guild_ref=context.guild_ref,
            named={
                ref: (IdentityEntity(entity_type), entity_id)
                for ref, entity_type, entity_id in context.named_refs
            },
            members=context.named_members,
            reads_names=context.holds("members:read"),
            session=session,
        )
    )
    return context


def plugin_scope(scope: str) -> Callable[..., Awaitable[ActorContext]]:
    """The dependency a route names to admit an installed plug-in, at ``scope``.

    A person passes through to the ordinary seam, exactly as
    :data:`GuildContextDep` would take them, so one route serves both. An
    installation token is admitted only here: :func:`get_current_user` refuses
    one, so a route that names no scope cannot be reached by a plug-in. For an
    install, the guild comes from the token and the path's ``{community_id}`` is
    not read; a token whose scopes
    do not cover ``scope`` gets 403 (``PLUGIN_SCOPE_REQUIRED``).

    Either way the request's session — the one :data:`SessionDep` hands out,
    which FastAPI resolves once per request — is routed before the handler
    runs. A scoped route reads it through :data:`ActorSessionDep`.

    A scoped route's router uses ``app.api.actor_route.ActorRoute``. For an
    install, this dependency hands that route class the boundary its
    ``PersonId`` and ``GuildId`` fields translate through; an install's request
    on a route served by any other class is refused.

    The returned callable carries ``scope`` on :data:`PLUGIN_SCOPE_ATTRIBUTE`.
    A route names it the way the type checker reads, as a module-level alias
    or inline::

        FilesRead = Annotated[ActorContext, Depends(plugin_scope("files:read"))]

        async def list_files(actor: FilesRead, session: ActorSessionDep): ...
    """
    parse_scope(scope)

    async def dependency(
        request: Request,
        session: SessionDep,
        guild_id: CommunityIdPath,
        person: Annotated[Optional[User], Depends(get_actor_user)],
    ) -> ActorContext:
        if person is None:
            # ``get_actor_user`` answers ``None`` only for an access token.
            return await _establish_install_request(request, session, scope)
        context = await get_guild_membership(request, session, person, guild_id)
        return context

    setattr(dependency, PLUGIN_SCOPE_ATTRIBUTE, scope)
    setattr(dependency, PLUGIN_SCOPES_ATTRIBUTE, frozenset({scope}))
    setattr(dependency, PLUGIN_SCOPE_DECLARATION_ATTRIBUTE, scope)
    dependency.__name__ = f"plugin_scope_{scope.replace(':', '_')}"
    dependency.__qualname__ = dependency.__name__
    return dependency


def plugin_scope_by(
    param: str, scopes: Mapping[str, str]
) -> Callable[..., Awaitable[ActorContext]]:
    """:func:`plugin_scope` for a route that serves several kinds of thing, named
    by the path parameter ``param``: an installed plug-in's request needs
    ``scopes[<the parameter's value>]``. A value with no entry is one no plug-in
    may ask about, and an installation token gets 403 (``PLUGIN_SCOPE_REQUIRED``)
    for it. A person passes through to the ordinary seam, as with
    :func:`plugin_scope`.

    The returned callable carries every scope it may ask on
    :data:`PLUGIN_SCOPES_ATTRIBUTE`, and ``by <param>`` on
    :data:`PLUGIN_SCOPE_ATTRIBUTE`.
    """
    for scope in scopes.values():
        parse_scope(scope)

    async def dependency(
        request: Request,
        session: SessionDep,
        guild_id: CommunityIdPath,
        person: Annotated[Optional[User], Depends(get_actor_user)],
    ) -> ActorContext:
        if person is None:
            scope = scopes.get(str(request.path_params.get(param)))
            if scope is None:
                # Read locally first, so a token that is not one answers 401
                # whatever it asked for.
                if bearer_plugin_token(request) is None:
                    raise _refuse_install_credential()
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=PluginMessages.SCOPE_REQUIRED,
                )
            return await _establish_install_request(request, session, scope)
        context = await get_guild_membership(request, session, person, guild_id)
        return context

    setattr(dependency, PLUGIN_SCOPE_ATTRIBUTE, f"by {param}")
    setattr(dependency, PLUGIN_SCOPES_ATTRIBUTE, frozenset(scopes.values()))
    setattr(
        dependency,
        PLUGIN_SCOPE_DECLARATION_ATTRIBUTE,
        {"by": param, "scopes": dict(sorted(scopes.items()))},
    )
    dependency.__name__ = f"plugin_scope_by_{param}"
    dependency.__qualname__ = dependency.__name__
    return dependency


def plugin_scope_checked(
    scopes: Iterable[str], *, per: str
) -> Callable[..., Awaitable[ActorContext]]:
    """:func:`plugin_scope` for a route whose scope depends on what the request
    asks for, so no one scope fits the route: ``per`` names what decides it
    (``"event type"``). An installation token is admitted here without a
    scope asked of it, and the route's own code — its service, once it has
    read the request — asks each scope the request needs of the install's
    standing (:meth:`InstallContext.holds`), answering 403
    (``PLUGIN_SCOPE_REQUIRED``) for one it does not hold. A person passes through
    to the ordinary seam, as with :func:`plugin_scope`.

    ``scopes`` is every scope such a check may ask, carried on
    :data:`PLUGIN_SCOPES_ATTRIBUTE` for the walk over the routes; ``per <per>``
    is carried on :data:`PLUGIN_SCOPE_ATTRIBUTE`.
    """
    asked = frozenset(scopes)
    if not asked:
        raise ValueError("a checked plug-in scope names the scopes it may ask")
    for scope in asked:
        parse_scope(scope)

    async def dependency(
        request: Request,
        session: SessionDep,
        guild_id: CommunityIdPath,
        person: Annotated[Optional[User], Depends(get_actor_user)],
    ) -> ActorContext:
        if person is None:
            return await _establish_install_request(request, session, None)
        context = await get_guild_membership(request, session, person, guild_id)
        return context

    label = per.replace(" ", "_")
    setattr(dependency, PLUGIN_SCOPE_ATTRIBUTE, f"per {per}")
    setattr(dependency, PLUGIN_SCOPES_ATTRIBUTE, asked)
    setattr(
        dependency,
        PLUGIN_SCOPE_DECLARATION_ATTRIBUTE,
        {"per": label, "any_of": sorted(asked)},
    )
    dependency.__name__ = f"plugin_scope_per_{label}"
    dependency.__qualname__ = dependency.__name__
    return dependency


async def get_actor_user(
    request: Request,
    session: SessionDep,
    bearer_token: Annotated[Optional[str], Depends(oauth2_scheme)] = None,
    session_cookie: Annotated[Optional[str], Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> Optional[User]:
    """The person a scoped route serves, or ``None`` for an installed plug-in.

    For a person, the same two dependencies a content route composes, in the
    same order. An installation token is admitted by the route's
    :func:`plugin_scope` dependency, not here. FastAPI resolves this once per
    request, so a handler that takes :data:`ActorUserDep` beside its scope gets
    the account the scope dependency authenticated.
    """
    if bearer_plugin_token(request) is not None:
        return None
    user = await get_current_user(request, session, bearer_token, session_cookie)
    return await get_current_active_user(request, session, user)


#: The account a scoped route serves; ``None`` when an installed plug-in calls it.
ActorUserDep = Annotated[Optional[User], Depends(get_actor_user)]


def _route_dependency_value(route: Any, attribute: str) -> Any:
    """The first value of ``attribute`` among a route's dependencies, or
    ``None``."""
    dependant = getattr(route, "dependant", None)
    pending = list(getattr(dependant, "dependencies", ()) or ())
    while pending:
        current = pending.pop()
        found = getattr(current.call, attribute, None)
        if found is not None:
            return found
        pending.extend(current.dependencies or ())
    return None


def route_plugin_scope(route: Any) -> str | None:
    """The plug-in scope a route names, or ``None``: read from its dependencies."""
    return _route_dependency_value(route, PLUGIN_SCOPE_ATTRIBUTE)


def route_plugin_scopes(route: Any) -> frozenset[str]:
    """Every plug-in scope a route may ask of a request: read from its
    dependencies. Empty for a route that names none."""
    return _route_dependency_value(route, PLUGIN_SCOPES_ATTRIBUTE) or frozenset()


def route_plugin_scope_declaration(route: Any) -> str | dict[str, Any] | None:
    """What a route's plug-in scope dependency declares
    (:data:`PLUGIN_SCOPE_DECLARATION_ATTRIBUTE`), or ``None`` for a route that
    names no plug-in scope."""
    return _route_dependency_value(route, PLUGIN_SCOPE_DECLARATION_ATTRIBUTE)


async def get_actor_session(request: Request, session: SessionDep) -> AsyncSession:
    """The session a scoped route's :func:`plugin_scope` dependency routed.

    The same instance, since FastAPI resolves :data:`SessionDep` once per
    request, and every dependency resolves before the handler runs, so by then
    it is routed as the person or the install. A route that takes this without
    naming a scope is a wiring mistake, and is refused as one.
    """
    if route_plugin_scope(request.scope.get("route")) is None:
        raise RuntimeError("ActorSessionDep is for a route that names a plug-in scope")
    return session


#: The routed session of a route that names a plug-in scope.
ActorSessionDep = Annotated[AsyncSession, Depends(get_actor_session)]


async def get_guild_seat_context(
    guild_id: CommunityIdPath,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildContext:
    """Route this request into the community's seat, or refuse it.

    The seat is the rung above ``admin``: a community's sign-in configuration
    and what it pays for. It is reached by the membership row that says so, or
    by a live settings grant at that rung, and the session assumes
    ``guild_<id>_superadmin`` — the one role whose floor carries those tables.
    Every other route by the same person routes as an ordinary member.
    """
    return await _establish_seat(session, current_user, guild_id)


async def _establish_seat(
    session: AsyncSession,
    current_user: User,
    guild_id: int,
    *,
    for_payment: bool = False,
) -> GuildContext:
    """:func:`get_guild_seat_context`'s work, with the one flag a dependency
    cannot take as a parameter (FastAPI would read it from the query)."""
    try:
        context = await establish_guild_access(
            session,
            current_user,
            guild_id,
            for_settings=True,
            for_seat=True,
            for_payment=for_payment,
            factor_asked=True,
        )
    except GuildAccessError as exc:
        raise_for_guild_access(exc)
    if not context.guild_seat:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.COMMUNITY_SUPERADMIN_REQUIRED,
        )
    return context


async def get_guild_seat_session(
    session: SessionDep,
    _context: Annotated[GuildContext, Depends(get_guild_seat_context)],
) -> AsyncSession:
    """The session :func:`get_guild_seat_context` routed, for the four
    configuration routes the seat holds."""
    return session


def require_grant_writes(context: GuildContext) -> None:
    """Refuse a change from a grantee whose grants read.

    A settings rung reaches the community's configuration; changing it takes
    a ``read_write`` content grant beside the rung — the two asks together.
    The membership row's administrator is not a grantee and passes.
    """
    if not context.grant_writes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AccessGrantMessages.WRITE_GRANT_REQUIRED,
        )


async def get_guild_seat_write_context(
    context: Annotated[GuildContext, Depends(get_guild_seat_context)],
) -> GuildContext:
    """The seat, for a route that changes what the seat holds.

    Held by the membership row, the seat writes. Lent by a settings grant, it
    reads, and writes only beside a live ``read_write`` content grant."""
    require_grant_writes(context)
    return context


async def get_guild_seat_write_session(
    session: SessionDep,
    _context: Annotated[GuildContext, Depends(get_guild_seat_write_context)],
) -> AsyncSession:
    """The session :func:`get_guild_seat_write_context` routed."""
    return session


async def get_guild_seat_payment_context(
    guild_id: CommunityIdPath,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> GuildContext:
    """The seat, for the billing handoff: :func:`get_guild_seat_write_context`
    that also reaches a community on hold, so its seat can pay its way out.

    Established ``for_payment``; the handoff is the only route that takes it.
    """
    return await get_guild_seat_write_context(
        await _establish_seat(session, current_user, guild_id, for_payment=True)
    )


async def get_guild_seat_payment_session(
    session: SessionDep,
    _context: Annotated[GuildContext, Depends(get_guild_seat_payment_context)],
) -> AsyncSession:
    """The session :func:`get_guild_seat_payment_context` routed."""
    return session


# Dependency for routes that need RLS-aware database access
RLSSessionDep = Annotated[AsyncSession, Depends(get_guild_session)]
SettingsContextDep = Annotated[GuildContext, Depends(get_guild_settings_context)]
# The configuration surface, by rung: what an administrator keeps while the
# content is closed and what a settings grant may serve, and — for a route
# that changes something — asking a grantee for the read_write grant beside
# the rung.
SettingsAdminContextDep = Annotated[
    GuildContext, Depends(require_guild_roles(CommunityRole.admin, settings=True))
]
SettingsAdminWriteContextDep = Annotated[
    GuildContext,
    Depends(require_guild_roles(CommunityRole.admin, settings=True, write=True)),
]
SettingsSeatWriteContextDep = Annotated[
    GuildContext,
    Depends(require_guild_roles(CommunityRole.superadmin, settings=True, write=True)),
]
SettingsRLSSessionDep = Annotated[AsyncSession, Depends(get_guild_settings_session)]
SettingsWriteSessionDep = Annotated[
    AsyncSession, Depends(get_guild_settings_write_session)
]
SeatContextDep = Annotated[GuildContext, Depends(get_guild_seat_context)]
SeatWriteContextDep = Annotated[GuildContext, Depends(get_guild_seat_write_context)]
SeatSessionDep = Annotated[AsyncSession, Depends(get_guild_seat_session)]
SeatWriteSessionDep = Annotated[AsyncSession, Depends(get_guild_seat_write_session)]
SeatPaymentSessionDep = Annotated[AsyncSession, Depends(get_guild_seat_payment_session)]


async def _include_deleted_flag(
    session: SessionDep,
    include_deleted: Annotated[
        bool,
        Query(
            description=(
                "Also return the resource if it is in the trash. For reading a "
                "resource back after a deleted event — the row still exists "
                "until retention purges it, and access is checked exactly as "
                "for a live one."
            )
        ),
    ] = False,
) -> bool:
    """Opt a detail GET into seeing trashed rows.

    Flips the request session's soft-delete filter off (``session.info`` —
    see ``app.db.soft_delete_filter``) so every load in the handler, including
    the DAC loaders, can resolve a trashed row. Discloses nothing new: RLS and
    the per-resource access checks run unchanged, and the trash surface already
    shows these rows to the same audience. The route's own seam routes the
    session — a person's or an installed plug-in's — so this only sets the flag.
    """
    if include_deleted:
        session.info["include_deleted"] = True
    return include_deleted


IncludeDeletedDep = Annotated[bool, Depends(_include_deleted_flag)]


async def _apply_user_session_context(
    session: AsyncSession, current_user: User
) -> AsyncSession:
    """Route ``session`` for the public/platform path: no guild, the caller's
    own tier. The body the user-session dependencies share.

    A suspended account holds no rung while it is in time out, so it is routed
    as ``platform_suspended`` whatever ``users.role`` says — its own rows, read,
    and nothing written. The rung comes back untouched when the suspension
    lifts.
    """
    tier = (
        PLATFORM_SUSPENDED
        if current_user.status == UserStatus.suspended
        else current_user.role.value
    )
    await set_rls_context(session, Platform(user_id=current_user.id, tier=tier))
    return session


async def get_factor_exempt_user_session(
    session: SessionDep,
    current_user: FactorExemptUser,
) -> AsyncSession:
    """The platform-path session for a route that stays reachable while the
    deployment's second-factor rule is unmet — routed exactly as the ordinary
    one, and holding no more."""
    return await _apply_user_session_context(session, current_user)


FactorExemptSessionDep = Annotated[
    AsyncSession, Depends(get_factor_exempt_user_session)
]


async def get_account_holder_session(
    session: SessionDep,
    current_user: AccountHolder,
) -> AsyncSession:
    """The platform-path session for a time-out allow-list route."""
    return await _apply_user_session_context(session, current_user)


async def get_factor_exempt_account_holder_session(
    session: SessionDep,
    current_user: FactorExemptAccountHolder,
) -> AsyncSession:
    """The platform-path session for a factor-exempt time-out allow-list route."""
    return await _apply_user_session_context(session, current_user)


async def get_ticket_holder_session(
    session: SessionDep,
    current_user: TicketHolder,
) -> AsyncSession:
    """The platform-path session for a ticket route."""
    return await _apply_user_session_context(session, current_user)


AccountHolderSessionDep = Annotated[AsyncSession, Depends(get_account_holder_session)]
TicketHolderSessionDep = Annotated[AsyncSession, Depends(get_ticket_holder_session)]
FactorExemptAccountHolderSessionDep = Annotated[
    AsyncSession, Depends(get_factor_exempt_account_holder_session)
]


async def get_user_session(
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> AsyncSession:
    """Get a session with user context only (no guild).

    For cross-guild operations like guild creation, listing user's guilds,
    or accepting invites where no specific guild context is needed.

    This is the authenticated *public/platform* path: it carries no guild
    context, so the session assumes the caller's platform-tier role
    (``platform_<users.role>``) rather than the broad login role — the request
    is role-scoped at the database and fails closed if a downstream query forgets
    to route. Guild-addressed work uses ``get_guild_session`` instead, which
    ``SET ROLE``s into the guild role.

    No standing all-guild bypass: a platform role's cross-user/guild
    reach on this path is authorized by the ``platform_<tier>`` RLS policies
    (Phase 2), and reaching a guild's *data* requires an explicit break-glass
    PAM grant (§7), never an ambient flag.
    """
    return await _apply_user_session_context(session, current_user)


# Dependency for routes that need user-level RLS without guild context
UserSessionDep = Annotated[AsyncSession, Depends(get_user_session)]


async def get_upload_user(
    request: Request,
    session: SessionDep,
    bearer_token: Annotated[Optional[str], Depends(oauth2_scheme)] = None,
    token_param: Annotated[Optional[str], Query(alias="token")] = None,
    session_cookie: Annotated[Optional[str], Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> User:
    """Auth dependency for /uploads/* and authenticated file downloads.

    Two trust tiers, by where the credential arrives:

      * Authorization header or HttpOnly cookie — not exposed in URLs, so what
        every other route accepts is accepted here.
      * ``?token=`` query param — part of the URL, so only a short-lived
        uploads-scoped token is accepted. A session token or API key there is
        refused; native clients fetch a scoped token from
        ``POST /auth/upload-token`` instead.

    Held to the same account status and second-factor rules as every other
    route.
    """
    identified = identify(request) or identify_url_token(request)
    user = await _active_user(
        request, await _authenticate(request, session, identified)
    )
    await _require_platform_factor(request, session, user)
    return user


UploadUserDep = Annotated[User, Depends(get_upload_user)]


async def authenticate_feed(
    request: Request, session: AsyncSession, resource: tuple[int, Tool, int]
) -> User:
    """The person a subscription link names, for the feed of ``resource``,
    ``(guild_id, tool, id)``.

    Calendar apps fetch a feed by its URL alone, so its ``?token=`` carries a
    personal API key, admitted only when the key names ``resource`` (see
    :func:`_admit`). Held to the same account status and second-factor rules
    as :func:`get_upload_user`; the route then establishes guild access as a
    file download does, where the community's API-access rule applies.

    A feed route calls it from a dependency, so its rate limit counts the
    person the link names (``request.state.user_id``).
    """
    identified = identify_url_token(request, FEED_URL_CREDENTIALS)
    user = await _active_user(
        request, await _authenticate(request, session, identified, resource)
    )
    await _require_platform_factor(request, session, user)
    return user


async def require_direct_messages_enabled(session: UserSessionDep) -> None:
    """Refuse every direct-message route when the deployment does not offer them.

    Applied once, to the routers rather than to the endpoints, so the whole
    surface answers the same way and a route added later is covered by having
    been added to the router. It shares the caller's session: every endpoint
    behind it takes ``UserSessionDep``, so FastAPI resolves that dependency once
    and this costs a single indexed read rather than a second connection.

    Nothing is deleted while it is off -- devices, keys, policies and accepted
    channels all stay -- so the only thing switching it back on has to do is
    stop refusing.
    """
    from app.services.platform import app_settings as app_settings_service

    if not await app_settings_service.direct_messages_enabled(session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DirectMessageMessages.DISABLED_FOR_PLATFORM,
        )


DirectMessagesEnabledDep = Depends(require_direct_messages_enabled)
