from datetime import date, datetime, timedelta, timezone
import hashlib
import hmac
import logging
from dataclasses import dataclass, replace
from typing import Any, Annotated
from urllib.parse import urlencode

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError
from sqlmodel import delete as sql_delete, select

from app.api.deps import (
    CommunityIdPath,
    SessionDep,
    get_current_active_user,
    get_current_user_optional,
    SystemSessionDep,
)
from app.db import post_commit
from app.db import session as db_session
from app.db.session import set_rls_context
from app.core.config import API_V1_STR, is_device, settings
from sqlmodel.ext.asyncio.session import AsyncSession
from app.core import audit_context, auth_context
from app.core.rate_limit import MAIL_SENDS, limiter
from app.core.encryption import (
    decrypt_field,
    normalize_email,
    SALT_EMAIL,
    SALT_OIDC_CLIENT_SECRET,
)
from app.core.login_methods import LoginMethod
from app.core.messages import (
    AuthMessages,
    NativeMessages,
    OidcMessages,
    UserMessages,
)
from app.core.password_policy import validate_new_password
from app.core import usernames
from app.core.usernames import UsernameError
from app.core.identify import identify
from app.core.security import (
    REFRESH_COOKIE_NAME,
    create_handle_offer,
    create_upload_token,
    get_password_hash,
    read_handle_offer,
)
from app.core.user_input_validators import (
    is_safe_next_path,
    is_valid_provider_slug,
    normalize_timezone,
)
from app.api.v1.platform_endpoints.session_cookies import (
    REFRESH_COOKIE_PATH,
    clear_refresh_cookie,
    clear_session_cookie,
)
from app.api.v1.platform_endpoints.session_opening import (
    PASSWORD_LEG,
    SECOND_FACTOR_PURPOSES,
    current_session_row,
    MOBILE_CALLBACK_URI,
    first_leg_of,
    mint_for,
    open_session,
    prove_password,
    prove_second_factor,
    require_login_method,
    require_passkeys_allowed,
    second_factor_outstanding,
    set_password,
    upgrade_session,
)
from app.core.audit_events import AuditEventType
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.auth_provider_secret import AuthProviderSecret
from app.models.platform.auth_session import AuthSession
from app.models.platform.user import (
    LOGIN_STATUSES,
    User,
    UserRole,
    UserStatus,
    may_sign_in,
)
from app.models.platform.guild import Guild, CommunityRole
from app.schemas.platform.token import Token
from app.schemas.platform.second_factor import SecondFactorChallengeAnswer
from app.schemas.platform.auth import (
    NativeSignInRedeem,
    RefreshRequest,
    LoginProviderEntry,
    LoginProvidersResponse,
    PasswordResetRequest,
    PasswordResetSubmit,
    UploadTokenResponse,
    UsernameAvailabilityResponse,
    UsernameSuggestionsResponse,
    VerificationConfirmRequest,
    VerificationSendResponse,
)
from app.schemas.platform.passkey import (
    PasskeyRegistrationOptions,
    PasskeySignUpFinish,
    PasskeySignUpResult,
    PasskeySignUpStart,
)
from app.schemas.platform.guild import NewCommunity
from app.schemas.platform.user import UserCreate, UserRead
from app.services import audit as audit_service
from webauthn.helpers import bytes_to_base64url

from app.services.auth import account_changes, addresses
from app.services.auth import (
    guild_provider_connections as guild_connections,
)
from app.services.auth import challenges as challenge_service
from app.services.auth import native_handoff
from app.services.auth import passkeys as passkey_service
from app.services.auth import totp as totp_service
from app.services.auth import sessions as session_service
from app.services.auth import subject as subject_service
from app.services.auth.assurance import (
    passkey_amr,
    read_assurance,
    read_narrowing,
    record_for_provider,
    session_amr,
)
from app.services.platform import app_settings as app_settings_service
from app.services.platform import legal as legal_service
from app.services.platform import usernames as username_service
from app.services.platform import users as users_service
from app.services.auth.identity import (
    ResolutionOutcome,
    any_account_exists,
    link_identity,
    resolve_oidc_identity,
    set_identity_refresh_token,
)
from app.services.auth.oidc.discovery import OidcDiscovery
from app.services.auth.oidc.flow_state import FlowStateError, decode_flow_state
from app.services.auth.oidc.jwks import JwksResolver
from app.services.auth.oidc.provider import (
    OidcClientConfig,
    OidcFlowError,
    OidcProvider,
)
from app.services.auth import provider_registry
from app.services.auth.provider_registry import (
    frontend_callback_url,
    provider_callback_url,
)
from app.services.auth.platform_provider import (
    PLATFORM_OIDC_SLUG,
    get_platform_provider,
    is_login_ready,
)
from app.services.auth.sessions import RefreshOutcome
from app.services.tenant.plugin_age import request_country
from app.services.platform import auth_posture
from app.services.platform import dm_settings as dm_settings_service
from app.services import email as email_service
from app.services.platform import user_tokens
from app.services.platform import guilds as guilds_service
from app.services.oidc_sync import extract_claim_values, sync_oidc_assignments
from app.services.content_sockets import sockets as content_sockets
from app.services.platform import provider_placement
from app.models.platform.user_token import UserTokenPurpose
from app.db.request_context import Platform

router = APIRouter()


logger = logging.getLogger(__name__)

# Shared across requests so provider discovery + JWKS caching work; the
# per-request OidcProvider is just configuration composed around them.
_oidc_discovery = OidcDiscovery()
_oidc_jwks = JwksResolver()


def _refresh_rejected(detail: str) -> JSONResponse:
    """A 401 for a failed refresh that also clears the stale auth cookies.

    The clearing must ride on the *returned* response: mutating the injected
    ``Response`` and then ``raise``-ing an ``HTTPException`` drops the Set-Cookie
    headers (FastAPI builds a fresh response for the exception), so the browser
    would keep resending a dead refresh token. Returning the response directly is
    the only way the delete-cookie headers reach the client."""
    response = JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": detail},
        headers={"WWW-Authenticate": "Bearer"},
    )
    clear_refresh_cookie(response)
    clear_session_cookie(response)
    return response


@dataclass(frozen=True)
class RegistrationDetails:
    """What somebody says about themselves when they register.

    The same set whichever door they came through, so the one registration
    body below reads them from here rather than from a schema belonging to one
    of them.
    """

    email: str
    username: str
    timezone: str | None = None
    captcha_token: str | None = None
    community: NewCommunity | None = None
    birthdate: date | None = None
    username_offer: str | None = None
    #: The documents the form showed, by slug (see ``record_acceptance``).
    accepted_documents: tuple[str, ...] = ()


@dataclass(frozen=True)
class PasskeyToKeep:
    """A verified credential, waiting for the account it belongs to."""

    registered: passkey_service.RegisteredCredential
    name: str


@dataclass(frozen=True)
class RegisteredAccount:
    """A new account and, where it holds no password, the codes that are its
    way back to one."""

    user: User
    codes: list[str]


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register_user(
    request: Request,
    user_in: UserCreate,
    session: SystemSessionDep,
    invite_code: str | None = Query(default=None),
) -> UserRead:
    # Registering here mints a password account, so it is the password method's
    # own door. A deployment that does not permit passwords onboards through an
    # identity provider, or through the passkey door below.
    await require_login_method(session, LoginMethod.password)
    # Enforce password policy (NIST 800-63B: length + HIBP breach check) before
    # we hash. Raises 422 PASSWORD_TOO_SHORT / PASSWORD_BREACHED on failure.
    await validate_new_password(session, user_in.password)
    registered = await _register_account(
        request,
        session,
        details=RegistrationDetails(
            email=user_in.email,
            username=user_in.username,
            timezone=user_in.timezone,
            captcha_token=user_in.captcha_token,
            community=user_in.community,
            birthdate=user_in.birthdate,
            username_offer=user_in.username_offer,
            accepted_documents=tuple(user_in.accepted_documents),
        ),
        invite_code=invite_code,
        hashed_password=get_password_hash(user_in.password),
    )
    return await users_service.to_self_read(session, registered.user)


async def _refuse_birthdate(
    request: Request, session: AsyncSession, birthdate: date | None
) -> None:
    """Refuse a date nobody was born on, and, while the deployment checks age,
    somebody under the minimum for an account where they are."""
    if birthdate is None:
        return
    try:
        users_service.check_birthdate(birthdate)
    except users_service.InvalidBirthdateError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=UserMessages.AGE_INVALID_BIRTHDATE,
        ) from exc
    if not await app_settings_service.community_age_gate_enabled(session):
        return
    if users_service.below_account_minimum(birthdate, request_country(request)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=UserMessages.AGE_BELOW_ACCOUNT_MINIMUM,
        )


async def _registration_gate(
    request: Request,
    session: AsyncSession,
    *,
    email: str,
    invite: str | None,
    captcha_token: str | None,
    check_captcha: bool = True,
) -> bool:
    """Whether this address may register here at all, and whether it is first.

    Asked before an account is made and, for the passkey door, before the
    browser is sent to an authenticator — a refusal that arrives after the
    ceremony has already cost somebody's key a resident credential.

    The address is asked about last. Whether this deployment takes a
    registration at all, and whether the captcha was answered, are refusals
    about the request; only somebody the deployment would register learns
    whether the address is already held.
    """
    is_first_user = not await any_account_exists(session)

    # Registration is closed without an invite when public registration or
    # guild creation is off. The very first account bootstraps the deployment
    # and is always allowed.
    if (
        not invite
        and not is_first_user
        and not await app_settings_service.registration_open(session)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AuthMessages.REGISTRATION_REQUIRES_INVITE,
        )

    # Captcha gate (no-op when ``CAPTCHA_PROVIDER`` isn't configured; see
    # ``app.services.captcha``). Skipped on the bootstrap first-user path: a
    # fresh deployment has nobody to protect, and its operator should not be
    # locked out by a captcha they have not finished wiring up.
    #
    # ``audit_context.client_ip`` is whatever the ASGI server resolved.
    # ``start.sh`` passes ``--proxy-headers --forwarded-allow-ips`` when
    # ``BEHIND_PROXY`` is true, so behind a proxy the captcha provider sees the
    # client address rather than the proxy's.
    #
    # ``check_captcha`` is false only where a door took the token already and
    # a token is spent by being checked. The passkey door's finish is that
    # case: it can only be reached with a challenge its begin issued, and the
    # begin is where the token was taken.
    if not is_first_user and check_captcha:
        from app.services import captcha as captcha_service

        await captcha_service.verify_or_raise(
            captcha_token,
            remote_ip=audit_context.client_ip(),
        )

    # Address-aware: the address is taken if it reaches ANY account, not
    # only if it is the one that account was created with.
    if await addresses.account_holding(session, email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.EMAIL_ALREADY_REGISTERED,
        )
    return is_first_user


async def _register_account(
    request: Request,
    session: AsyncSession,
    *,
    details: RegistrationDetails,
    invite_code: str | None,
    hashed_password: str | None,
    passkey: PasskeyToKeep | None = None,
    check_captcha: bool = True,
    address_proved: bool = False,
) -> RegisteredAccount:
    """Everything registering does, including settling how the account gets in.

    One body for both doors — the password one above and the passkey one below
    — because what a registration *is* does not depend on what it hands the
    account to come back with: the same address rules, the same invite and
    captcha gates, the same handle and the same verification letter.

    What differs is the way in, and it is settled *here* rather than by the
    caller afterwards: this commits — and, where the registration names a
    community, provisions it — so a credential written after the fact could
    fail and leave an account nobody can sign in to.
    Written in the same breath as the account, it is covered by the same undo.

    The caller has already refused a method this deployment does not permit and
    taken whatever its own door asks for.

    ``address_proved`` is for a door that proved the address on the way in —
    a code read out of that mailbox and typed back. Such an account needs no
    verification letter, because the thing the letter asks for has happened.
    """
    normalized_invite = (invite_code or "").strip() or None
    if normalized_invite and details.community is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=AuthMessages.REGISTRATION_INVITE_OR_COMMUNITY,
        )

    smtp_configured = False
    try:
        smtp_configured = await email_service.email_configured(session)

        normalized_email = normalize_email(details.email)
        is_first_user = await _registration_gate(
            request,
            session,
            email=normalized_email,
            invite=normalized_invite,
            captcha_token=details.captcha_token,
            check_captcha=check_captcha,
        )

        if normalized_invite:
            user_role = UserRole.member
        else:
            # The very first user bootstraps the platform as owner — the only
            # role that can manage app-wide configuration (OIDC, SMTP, …).
            user_role = UserRole.owner if is_first_user else UserRole.member

        # Validate the optional browser-supplied IANA timezone via the
        # same helper used by self-update / operator-update. Returns
        # ``None`` when the field is omitted or blank, in which case
        # we simply don't pass ``timezone`` to the model and the
        # column default ``"UTC"`` applies.
        normalized_timezone = normalize_timezone(details.timezone)

        # Confirmed on the spot when the door proved it, when there is no mail
        # to confirm it with, and for the account that bootstraps the
        # deployment.
        address_confirmed = address_proved or is_first_user or not smtp_configured
        # An invite bound to an address this sign-up has not proved yet waits
        # for the proof: the verification letter carries it, and confirming
        # the address joins the guild.
        awaiting_invite_id: int | None = None
        if normalized_invite and not address_confirmed:
            awaiting = await guilds_service.invite_awaiting_address(
                session, code=normalized_invite, email=normalized_email
            )
            awaiting_invite_id = awaiting.id if awaiting is not None else None
        user_kwargs: dict[str, Any] = dict(
            # Filled in by ``insert_with_handle`` below, which owns the insert
            # so it can redraw the number if another registration took it.
            username="",
            discriminator=0,
            username_chosen=True,
            hashed_password=hashed_password,
            password_set_at=(
                datetime.now(timezone.utc) if hashed_password is not None else None
            ),
            role=user_role,
            status=UserStatus.active,
        )
        if normalized_timezone is not None:
            user_kwargs["timezone"] = normalized_timezone
        user = User(**user_kwargs)
        # Under the minimum for an account where they are is refused, and no
        # account is made. Older than that but under age is recorded rather
        # than refused: it closes the directory, not the account.
        await _refuse_birthdate(request, session, details.birthdate)
        if details.birthdate is not None:
            users_service.record_age_answer(user, details.birthdate)
        # The handle: the name part as typed, and the number the name check
        # showed while it is still free. Registering is where an account picks
        # one, so it counts as chosen and its owner never meets the pick screen.
        await username_service.insert_with_handle(
            session,
            user=user,
            name=details.username,
            prefer=read_handle_offer(details.username_offer, details.username),
        )

        address = addresses.record_address(
            session,
            user_id=user.id,
            email=normalized_email,
            source=addresses.SOURCE_SIGNUP,
            verified=address_confirmed,
        )
        await session.flush()
        # The verification letter proves this row, so it is named by id.
        address_id = address.id
        # The date of birth, kept encrypted beside the answer it gave, in the
        # same transaction as the account: a registration that fails keeps none.
        if details.birthdate is not None:
            await users_service.keep_birthdate(
                session, user_id=user.id, birthdate=details.birthdate
            )
        await dm_settings_service.seed_for_new_account(session, user_id=user.id)
        # The way in. A password is on the row already; a key is a row of its
        # own, and the set of codes beside it is how an account holding no
        # password gets one — the same rule as giving a password up, applied
        # from the start.
        codes: list[str] = []
        if passkey is not None:
            await passkey_service.store(
                session,
                user_id=user.id,
                registered=passkey.registered,
                name=passkey.name,
            )
        if hashed_password is None:
            codes = await totp_service.issue_recovery_codes(session, user_id=user.id)
            await audit_service.record(
                session,
                event_type=AuditEventType.AUTH_RECOVERY_CODES_ISSUED,
                actor_user_id=user.id,
            )
        # The form said, above the button they just pressed, that creating an
        # account agrees to the documents it named. Only those are recorded: a
        # required one the form didn't show (its index still loading, or
        # unreachable) is asked for after sign-in. On a deployment that
        # requires none this records nothing.
        await legal_service.record_acceptance(
            session, user_id=user.id, shown=details.accepted_documents
        )
        # Staged beside the account, before either branch below commits it, so
        # a registration that fails leaves no record of one.
        await audit_service.record(
            session,
            event_type=AuditEventType.USER_CREATED,
            actor_user_id=user.id,
            target_user_id=user.id,
            detail={
                "via": "registration",
                "first_user": is_first_user,
                "invited": bool(normalized_invite),
            },
        )

        if awaiting_invite_id is not None:
            # The guild is joined when the address is confirmed.
            await session.commit()
        elif normalized_invite:
            guild = await guilds_service.redeem_invite_for_user(
                session,
                code=normalized_invite,
                user=user,
            )
            # Joining an existing (already-provisioned) guild — just record membership.
            await guilds_service.ensure_membership(
                session,
                guild_id=guild.id,
                user_id=user.id,
                role=CommunityRole.member,
            )
            await session.commit()
            await post_commit.settle(session)
        elif details.community is None:
            await session.commit()
        else:
            # The account is committed with the guild; if the guild cannot be
            # set up, the account goes too.
            user_id = user.id
            try:
                guild = await guilds_service.provision_new_guild(
                    session,
                    name=details.community.name,
                    description=details.community.description,
                    creator=user,
                )
            except guilds_service.GuildProvisionError:
                await session.exec(sql_delete(User).where(User.id == user_id))
                await session.commit()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=AuthMessages.UNABLE_TO_CREATE_USER,
                )
            guild_id = guild.id
            # The account was made with a guild of its own; welcome them to it.
            await guilds_service.welcome_new_guild(guild_id, owner_user_id=user_id)
    except IntegrityError as exc:  # pragma: no cover
        await session.rollback()
        logger.exception("Failed to register user due to integrity error")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.UNABLE_TO_CREATE_USER,
        ) from exc

    # Everything from here is about the account, so it is read on the
    # account's own platform path.
    await set_rls_context(session, Platform(user_id=user.id))
    await session.refresh(user)

    if smtp_configured and not address_confirmed:
        try:
            # On a system-engine session of its own: ``session`` is routed to
            # the account by now, and the token table is the system engine's.
            async with db_session.SystemSessionLocal() as token_session:
                token = await user_tokens.create_token(
                    token_session,
                    user_id=user.id,
                    purpose=UserTokenPurpose.email_verification,
                    expires_minutes=60 * 24,
                    user_email_id=address_id,
                    invite_id=awaiting_invite_id,
                )
            await email_service.send_verification_email(session, user, token)
        except email_service.EmailNotConfiguredError:
            logger.warning(
                "SMTP not configured; skipping verification email for user %s", user.id
            )
        except RuntimeError:  # pragma: no cover
            logger.error("Failed to send verification email for user %s", user.id)
    return RegisteredAccount(user=user, codes=codes)


_SIGN_UP_PURPOSES = (challenge_service.ChallengePurpose.passkey_sign_up,)


@router.post("/register/passkey/begin", response_model=PasskeyRegistrationOptions)
async def begin_passkey_sign_up(
    request: Request,
    payload: PasskeySignUpStart,
    session: SystemSessionDep,
    invite_code: str | None = Query(default=None),
) -> PasskeyRegistrationOptions:
    """Options for making the credential a new account will sign in with.

    Everything a registration is refused for is asked here, before the browser
    is sent to an authenticator: a ceremony that ends in a refusal has already
    cost somebody's key a resident credential it cannot take back.

    No account exists yet, so the ceremony is told a handle of its own rather
    than an account id. Nothing reads it back — a credential is found by its
    own id — and it is what the authenticator files this deployment's entry
    under.
    """
    await require_passkeys_allowed(session)
    await _refuse_birthdate(request, session, payload.birthdate)
    await _registration_gate(
        request,
        session,
        email=normalize_email(payload.email),
        invite=(invite_code or "").strip() or None,
        captcha_token=payload.captcha_token,
    )

    ceremony = passkey_service.begin_sign_up(
        account_name=normalize_email(payload.email),
        display_name=payload.username.strip(),
    )
    await challenge_service.create(
        session,
        user_id=None,
        purpose=challenge_service.ChallengePurpose.passkey_sign_up,
        value=bytes_to_base64url(ceremony.challenge),
    )
    await session.commit()
    return PasskeyRegistrationOptions(options=ceremony.options)


@router.post(
    "/register/passkey/finish",
    response_model=PasskeySignUpResult,
    status_code=status.HTTP_201_CREATED,
)
async def finish_passkey_sign_up(
    request: Request,
    response: Response,
    payload: PasskeySignUpFinish,
    session: SystemSessionDep,
    invite_code: str | None = Query(default=None),
) -> PasskeySignUpResult:
    """Make the account, keep the credential, and sign it in.

    The gates are asked again here — the details are said again rather than
    kept between the calls — except the captcha, which the begin above took
    and which a token is spent by.

    The account is signed in on the spot. The ceremony verified the person as
    well as the device, which is what a sign-in with this key will prove, so
    asking for it twice in a row would say nothing new. Its recovery set comes
    back with it: there is no password to reset, so the codes are how this
    account gets one later, and they are shown once.
    """
    await require_passkeys_allowed(session)

    registered = await passkey_service.register_against_challenge(
        session,
        user_id=None,
        credential=payload.credential,
        purposes=_SIGN_UP_PURPOSES,
    )
    if isinstance(registered, passkey_service.PresentationRefused):
        await registered.settle(session)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.PASSKEY_REGISTRATION_INVALID,
        )

    account = await _register_account(
        request,
        session,
        details=RegistrationDetails(
            email=payload.email,
            username=payload.username,
            timezone=payload.timezone,
            captcha_token=payload.captcha_token,
            community=payload.community,
            birthdate=payload.birthdate,
            username_offer=payload.username_offer,
            accepted_documents=tuple(payload.accepted_documents),
        ),
        invite_code=invite_code,
        hashed_password=None,
        passkey=PasskeyToKeep(registered=registered, name=payload.name),
        check_captcha=False,
    )

    user_id, token_version = account.user.id, account.user.token_version
    token = await open_session(
        request,
        response,
        session,
        user_id=user_id,
        token_version=token_version,
        amr=passkey_amr(backed_up=registered.backed_up),
        audit_detail={"method": "passkey", "during": "registration"},
    )
    return PasskeySignUpResult(access_token=token.access_token, codes=account.codes)


@router.get("/bootstrap")
async def bootstrap_status(session: SessionDep) -> dict[str, bool]:
    return {
        "has_users": await any_account_exists(session),
        "public_registration_enabled": await app_settings_service.registration_open(
            session
        ),
        "demo": settings.DEMO_MODE,
    }


@router.post("/token", response_model=Token)
async def login_access_token(
    request: Request,
    response: Response,
    session: SessionDep,
    system_session: SystemSessionDep,
    form_data: OAuth2PasswordRequestForm = Depends(),
    device_name: Annotated[str | None, Form(max_length=255)] = None,
) -> Token | JSONResponse:
    """Sign in with an address and password, from a browser or a device.

    A device (:func:`is_device`) is handed its refresh token in the body as well
    and opens a device session, labelled ``device_name``.
    """
    user = await prove_password(
        session, system_session, email=form_data.username, password=form_data.password
    )
    # ``user`` is attached to ``system_session``, so a rollback inside the
    # helpers below expires its attributes; the plain values are captured here.
    user_id, token_version = user.id, user.token_version

    # The password is right, and for an account holding a proved factor that
    # is not the whole sign-in.
    challenge = await second_factor_outstanding(
        session,
        system_session,
        user_id=user_id,
        leg=PASSWORD_LEG,
        native=is_device(request),
    )
    if challenge is not None:
        return challenge

    return await open_session(
        request,
        response,
        system_session,
        user_id=user_id,
        token_version=token_version,
        amr=PASSWORD_LEG.amr,
        audit_detail={"method": PASSWORD_LEG.method},
        device_name=(device_name or "").strip() or None,
    )


@router.post("/token/totp", response_model=Token)
async def answer_second_factor(
    request: Request,
    response: Response,
    system_session: SystemSessionDep,
    payload: SecondFactorChallengeAnswer,
) -> Token:
    """The second leg of a sign-in: the challenge, and the code.

    The first leg was a password or a code sent to one of the account's
    addresses; the challenge says which, and the session records both halves.

    A recovery code is accepted here too — it is what the account holds when
    the authenticator is out of reach, and the set exists to be used this way.
    Which one answered is recorded, and told apart in ``amr``.
    """
    challenge = await challenge_service.claim_attempt(
        system_session,
        value=payload.challenge,
        purposes=SECOND_FACTOR_PURPOSES,
    )
    if challenge is None:
        await system_session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.TOTP_CHALLENGE_INVALID,
        )

    user_id = challenge.user_id
    # Before the factor is read, not after: a code presented to an account that
    # cannot sign in anyway should not be spent on finding that out.
    user = await system_session.get(User, user_id)
    if user is None or not may_sign_in(user):
        await system_session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER
        )

    try:
        proof = await prove_second_factor(
            system_session,
            user_id=user_id,
            code=payload.code,
            recovery_code=payload.recovery_code,
            during="sign_in",
            signed_in=False,
        )
    except HTTPException:
        # The attempt the claim took stands, and the challenge with it until
        # it runs out, so they can try again.
        await system_session.commit()
        raise

    if not await challenge_service.consume(system_session, challenge):
        # Spent between the claim and here, so the session it bought is not
        # this request's to open a second time.
        await system_session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.TOTP_CHALLENGE_INVALID,
        )

    leg, _ = first_leg_of(challenge.purpose)
    return await open_session(
        request,
        response,
        system_session,
        user_id=user_id,
        token_version=user.token_version,
        amr=[*leg.amr, *proof.amr],
        audit_detail={"method": leg.method, "second_factor": proof.method},
    )


@router.post("/refresh", response_model=Token)
async def refresh_access_token(
    request: Request,
    response: Response,
    system_session: SystemSessionDep,
    payload: RefreshRequest | None = None,
) -> Token | JSONResponse:
    """Rotate the refresh cookie → a fresh short-lived access token + new refresh.

    Single-use rotation with theft detection lives in the session service; this
    endpoint is the ``rotate → commit → branch`` caller (see
    ``services.auth.sessions``). Reuse of a spent token revokes the whole chain,
    but the client is always told the same generic thing — never that a replay
    was detected. Runs on the system engine: validation is a pre-auth lookup by
    refresh-token hash.
    """
    # Cookie first, so the browser is unchanged. A native client has no cookie
    # to send — its refresh token lives in the platform's secure storage — so it
    # presents one in the body and gets the rotated one back the same way.
    raw = request.cookies.get(REFRESH_COOKIE_NAME)
    presented_in_body = False
    if not raw and payload is not None and payload.refresh_token:
        raw = payload.refresh_token
        presented_in_body = True
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMessages.NOT_AUTHENTICATED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await session_service.rotate_session(
        system_session,
        raw_refresh_token=raw,
        user_agent=audit_context.client_user_agent(),
        ip=audit_context.client_ip(),
        idle=timedelta(seconds=(payload.idle_seconds or 0) if payload else 0),
    )
    if result.outcome is RefreshOutcome.REUSED and result.user_id is not None:
        # No actor, for the same reason a refused sign-in has none, and more
        # sharply: this endpoint is authorised by possession of the cookie
        # alone, and the credential has just been rejected. The account that
        # owned the chain is what the replay was against.
        await audit_service.record(
            system_session,
            event_type=AuditEventType.AUTH_REFRESH_REUSE_DETECTED,
            actor_user_id=None,
            target_user_id=result.user_id,
            target_type="user",
            target_id=result.user_id,
        )
    # The name the replacement token will carry, in the rotation's own
    # transaction. The raw refresh secret the rotation mints exists only in
    # ``issued`` until the response sets it, so anything that can fail belongs
    # before the commit that spends the presented one.
    subject = (
        await subject_service.subject_for_user(
            system_session, user_id=result.issued.session.user_id
        )
        if result.ok and result.issued is not None
        else None
    )
    # Commit BEFORE branching: one commit persists the rotation (ROTATED) or the
    # theft-revocation (REUSED), so a rejection can't leave the chain kill
    # uncommitted (see RotationResult).
    await system_session.commit()

    if not result.ok:
        if result.outcome is RefreshOutcome.REUSED:
            logger.warning("Refresh token replay detected; revoked session chain")
        return _refresh_rejected(AuthMessages.INVALID_REFRESH_TOKEN)

    issued = result.issued
    user = await system_session.get(User, issued.session.user_id)
    if user is None or user.status not in LOGIN_STATUSES:
        # The account was deactivated/removed after the session was minted — kill
        # the fresh session too rather than hand back a usable token.
        await session_service.revoke_chain(system_session, session_id=issued.session.id)
        await system_session.commit()
        return _refresh_rejected(AuthMessages.INVALID_REFRESH_TOKEN)

    # Bounded by the row it renews, the same way the first token was.
    renewed = mint_for(issued, subject=subject, token_version=user.token_version)
    renewed.set_cookies(response)
    return renewed.to_token(include_refresh=presented_in_body)


@router.get("/username-suggestions", response_model=UsernameSuggestionsResponse)
async def suggest_usernames(
    request: Request,
    session: SystemSessionDep,
    seed: str | None = Query(default=None, max_length=64),
) -> UsernameSuggestionsResponse:
    """Name parts nobody holds yet, offered while somebody picks one.

    Unauthenticated for the reason the availability check is. ``seed`` is what
    they have typed so far; the suggestions start from it where it is usable.
    """
    return UsernameSuggestionsResponse(
        suggestions=await username_service.suggest(session, seed=seed)
    )


@router.get("/username-available", response_model=UsernameAvailabilityResponse)
async def check_username_available(
    request: Request,
    session: SystemSessionDep,
    username: str = Query(max_length=64, description="The name part to check"),
) -> UsernameAvailabilityResponse:
    """Whether a name part can still be handed out.

    Registration happens before there is a session, so this is unauthenticated.
    It answers about the exact candidate typed and nothing else — it does not
    enumerate — and it answers about the name part only: the number behind it
    is drawn server-side.
    """
    try:
        usernames.validate(username)
    except UsernameError as exc:
        return UsernameAvailabilityResponse(available=False, reason=exc.code)

    try:
        name, number = await username_service.allocate(session, name=username)
    except UsernameError as exc:
        return UsernameAvailabilityResponse(available=False, reason=exc.code)
    # The number shown beside the name, signed so the account it becomes gets
    # that number while it is still free.
    return UsernameAvailabilityResponse(
        available=True,
        discriminator=number,
        offer=create_handle_offer(name, number),
    )


async def _revoke_signed_out_login(
    request: Request,
    system_session: AsyncSession,
    *,
    payload: RefreshRequest | None,
    user_id: int,
) -> None:
    """Revoke the rotation chain behind the login this request is on.

    Two ways a client names it, in the order it can. The refresh token it
    presents identifies the row exactly — a cookie for the browser, the body
    for a native client, which keeps its own in secure storage and has no
    cookie to send. Failing that, the ``sid`` its access token carries.

    Either way it goes through ``revoke_chain`` rather than ``revoke_session``:
    a refresh replaces the row it rotates, so a credential minted earlier in
    the chain still names the live one.
    """
    row = await _presented_live_session(request, system_session, payload=payload)
    if row is not None and row.user_id == user_id:
        await session_service.revoke_chain(system_session, session_id=row.id)
        return
    session_id = current_session_row(request)
    if session_id is not None:
        await session_service.revoke_chain(system_session, session_id=session_id)


async def _presented_live_session(
    request: Request,
    system_session: AsyncSession,
    *,
    payload: RefreshRequest | None,
) -> AuthSession | None:
    """The live session the refresh token this request presents belongs to.

    A cookie for the browser, the body for a native client. ``None`` where
    neither carries one, or the one carried names no live session.
    """
    raw = request.cookies.get(REFRESH_COOKIE_NAME) or (
        payload.refresh_token if payload is not None else None
    )
    if not raw:
        return None
    return await session_service.get_live_session_by_refresh_token(system_session, raw)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    system_session: SystemSessionDep,
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
    payload: RefreshRequest | None = None,
) -> None:
    """End the session this request is on, and leave the account's others.

    Signing out is per device: the rotation chain behind this login is revoked
    and the cookies that carried it are cleared, so a phone signing out does
    not close the laptop. What signs an account out everywhere is a credential
    change — a password change or reset, a second factor disabled, an account
    action taken by an operator — each of which bumps
    ``users.token_version`` on its own path.

    What is revoked here is the refresh side — the rotation chain behind this
    login. The access token it came in on is short-lived and the client drops
    it.

    A client whose access token has already expired still signs out: the
    refresh token it presents names its session, and holding it is what
    renewing would have asked for. That session's chain is revoked and no
    other.

    Connections opened on the ended session are re-checked once it commits, and
    close.
    """
    signed_out: int | None = None
    # ``auth_sessions`` is reached on the system engine, so the login chain and
    # the record commit together.
    if current_user is not None:
        await _revoke_signed_out_login(
            request, system_session, payload=payload, user_id=current_user.id
        )
        signed_out = current_user.id
    else:
        row = await _presented_live_session(request, system_session, payload=payload)
        if row is not None:
            await session_service.revoke_chain(system_session, session_id=row.id)
            signed_out = row.user_id
    if signed_out is not None:
        await audit_service.record(
            system_session,
            event_type=AuditEventType.AUTH_SIGNED_OUT,
            actor_user_id=signed_out,
        )
        await system_session.commit()
        await content_sockets.revoke_user_everywhere(signed_out)
    clear_session_cookie(response)
    clear_refresh_cookie(response)


@router.post("/upload-token", response_model=UploadTokenResponse)
@limiter.limit("60/minute")
async def issue_upload_token(
    request: Request,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UploadTokenResponse:
    """Mint a short-lived, uploads-scoped token for the authenticated user.

    Native (Capacitor) clients call this to load ``/uploads/*`` media and
    file downloads via ``?token=`` without putting the long-lived session
    JWT in the URL. The
    token is accepted only by the uploads/download routes and is useless as a
    general API credential.
    """
    # No longer than the session that asked for it: its access token is minted
    # no longer-lived than the session row, so ending with the access token
    # ends no later than the session. An API key has no session to end with.
    identified = identify(request)
    session_exp = identified.session.exp if identified and identified.session else None
    # Copy the minting session's satisfied-provider set into the scoped token
    # so media loads and the collaboration handover pass a policy-gated guild
    # exactly when the session itself would.
    recorded = auth_context.current()
    token, expires_in = create_upload_token(
        user_id=current_user.id,
        satisfied_providers=sorted(recorded.satisfied_providers),
        satisfied_claims=recorded.satisfied_claims,
        session_amr=recorded.session_amr,
        not_after=(
            datetime.fromtimestamp(session_exp, timezone.utc)
            if session_exp is not None
            else None
        ),
    )
    return UploadTokenResponse(upload_token=token, expires_in=expires_in)


@router.post("/native/token", response_model=Token)
async def redeem_native_sign_in(
    request: Request,
    response: Response,
    system_session: SystemSessionDep,
    payload: NativeSignInRedeem,
) -> Token:
    """Open the session a sign-in in the phone's browser earned.

    The app presents the code the browser handed back and the PKCE verifier it
    began the sign-in with, and is given an access token and a refresh token to
    keep. The session carries what the sign-in proved, satisfied providers
    included.
    """
    handoff = await native_handoff.redeem(
        system_session, code=payload.code, code_verifier=payload.code_verifier
    )
    user = (
        await system_session.get(User, handoff.user_id) if handoff is not None else None
    )
    if handoff is None or user is None or not may_sign_in(user):
        await system_session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMessages.NOT_AUTHENTICATED,
        )
    return await open_session(
        request,
        response,
        system_session,
        user_id=user.id,
        token_version=user.token_version,
        amr=handoff.amr,
        audit_detail={"method": handoff.method, "native": True},
        satisfied_providers=handoff.satisfied_providers,
        provider_auth=handoff.provider_auth,
        device_name=handoff.device_name,
        device=True,
    )


def _provider_state_key(row: AuthProvider) -> str:
    """The identity a login-flow state binds to.

    One sign-in, so one key: the provider's slug. A community is not a party
    to the flow — it applies what it said about the provider afterwards.
    """
    return row.slug


# Carries a validated SPA return path from /auth/{slug}/login to the web
# callback (e.g. the guild page a step-up started from). Scoped to the auth
# routes and short-lived — it only needs to survive one IdP round trip.
OIDC_NEXT_COOKIE = "oidc_next"
OIDC_NEXT_COOKIE_MAX_AGE = 600
# The browser that began a provider sign-in, named by a digest of its state:
# the callback completes only in the browser the state was handed to.
OIDC_FLOW_COOKIE = "oidc_flow"


def _state_digest(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


async def _active_platform_provider(
    system_session: AsyncSession,
) -> AuthProvider | None:
    """The platform provider row when its login is actually offerable —
    enabled, issuer + client id, AND a stored client secret (the platform flow
    has always required one; PKCE-only stays a guild-provider affordance).

    Offered in both postures. An operator-global provider is never
    authoritative for a guild — a guild policy may only name a provider of its
    own (``set_guild_auth_policy`` refuses any other), so signing in through
    one satisfies no guild's requirement. Returns None when any condition
    fails."""
    row = await get_platform_provider(system_session)
    if row is None or not is_login_ready(row):
        return None
    if not await provider_registry.secret_is_set(system_session, row.id):
        return None
    return row


async def _resolve_login_provider(
    system_session: AsyncSession, provider_slug: str
) -> AuthProvider:
    """The enabled operator-global provider row for one login slug, or 404.

    Resolves in both postures: an operator-global provider authenticates a
    person into their account and speaks for no guild (see
    ``_active_platform_provider``). Every slug — the platform ``oidc`` slug
    included — resolves to its registry row directly (the row is the source of
    truth; the old reconcile-from-settings shim is gone). A malformed slug is
    treated like an unknown one (no registry row can carry it)."""
    if not is_valid_provider_slug(provider_slug):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=OidcMessages.OIDC_NOT_ENABLED
        )
    if not await auth_posture.login_method_allowed(system_session, LoginMethod.sso):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=OidcMessages.OIDC_NOT_ENABLED
        )
    if provider_slug == PLATFORM_OIDC_SLUG:
        row = await _active_platform_provider(system_session)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=OidcMessages.OIDC_NOT_ENABLED,
            )
        return row
    row = (
        await system_session.exec(
            select(AuthProvider).where(AuthProvider.slug == provider_slug)
        )
    ).one_or_none()
    if row is None or not is_login_ready(row):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=OidcMessages.OIDC_NOT_ENABLED
        )
    return row


async def _build_row_oidc_provider(
    system_session: AsyncSession, row: AuthProvider
) -> OidcProvider:
    """The relying-party client for one provider row — the single builder for
    every slug. The platform row is reconciled from ``app_settings`` (config
    AND secret) by ``_resolve_login_provider`` before it gets here, so the
    registry row is always the client's source of truth. The secret comes from
    the app_admin-only companion table; ``None`` (public / PKCE-only client)
    is valid. Tests monkeypatch this builder to point flows at a fake IdP."""
    secret_row = await system_session.get(AuthProviderSecret, row.id)
    client_secret = (
        decrypt_field(secret_row.client_secret_encrypted, SALT_OIDC_CLIENT_SECRET)
        if secret_row and secret_row.client_secret_encrypted
        else None
    )
    return OidcProvider(
        OidcClientConfig(
            issuer=row.issuer,
            client_id=row.client_id,
            redirect_uri=provider_callback_url(row.slug),
            client_secret=client_secret,
            scopes=row.scopes or "openid",
            provider_slug=_provider_state_key(row),
        ),
        discovery=_oidc_discovery,
        jwks=_oidc_jwks,
    )


def _login_entry(row: AuthProvider) -> LoginProviderEntry:
    """One way in, as the sign-in page needs it.

    One address per provider, whichever page offers it: a community's page
    lists the ways in that count as its own, and they are the deployment's
    ways in.
    """
    login_url = f"{API_V1_STR}/auth/{row.slug}/login"
    return LoginProviderEntry(
        id=row.id,
        slug=row.slug,
        display_name=row.display_name,
        kind=row.kind,
        login_url=login_url,
        icon=row.icon,
        button_style=row.button_style,
    )


@router.get("/providers", response_model=LoginProvidersResponse)
async def list_login_providers(
    session: SessionDep, system_session: SystemSessionDep
) -> LoginProvidersResponse:
    """The sign-in providers the login page offers — non-secret metadata only.

    Listed in both postures — an operator-global provider signs a person into
    their account and is authoritative for no guild — and empty on instances
    with no SSO configured. Strictly read-only: the platform entry, like every
    other, is its registry row (the source of truth) — no write path is
    reachable from here. Registry rows are read on the system engine
    (``auth_providers`` carries no request-path grant)."""
    if not await auth_posture.login_method_allowed(system_session, LoginMethod.sso):
        return LoginProvidersResponse(providers=[])
    entries: list[LoginProviderEntry] = []
    platform_row = await _active_platform_provider(system_session)
    if platform_row is not None:
        entries.append(
            LoginProviderEntry(
                id=platform_row.id,
                slug=PLATFORM_OIDC_SLUG,
                display_name=platform_row.display_name,
                kind="oidc",
                login_url=f"{API_V1_STR}/auth/{PLATFORM_OIDC_SLUG}/login",
                icon=platform_row.icon,
                button_style=platform_row.button_style,
            )
        )

    rows = (
        await system_session.exec(
            select(AuthProvider)
            .where(
                AuthProvider.slug != PLATFORM_OIDC_SLUG,
                AuthProvider.enabled.is_(True),
                AuthProvider.kind == "oidc",
                AuthProvider.issuer.is_not(None),
                AuthProvider.client_id.is_not(None),
            )
            .order_by(AuthProvider.display_name)
        )
    ).all()
    # is_login_ready re-checks the same predicates and stays the single
    # authority (it also guards empty strings, which SQL NULL checks miss).
    entries.extend(_login_entry(row) for row in rows if is_login_ready(row))
    return LoginProvidersResponse(providers=entries)


async def _begin_provider_login(
    system_session: AsyncSession,
    provider_row: AuthProvider,
    *,
    mobile: bool,
    device_name: str,
    next_path: str,
    app_challenge: str = "",
) -> RedirectResponse:
    """Begin the relying-party flow for a resolved provider row.

    ``next_path`` is an optional SPA path to return to after the web callback
    (e.g. the guild page a step-up started from). Only a validated relative
    path is accepted; it rides a short-lived cookie to the callback, which
    passes it to the SPA's ``/oidc/callback`` page as a query param."""
    provider = await _build_row_oidc_provider(system_session, provider_row)
    try:
        begun = await provider.begin(
            mobile=mobile,
            device_name=device_name if mobile else "",
            app_challenge=app_challenge if mobile else "",
        )
    except OidcFlowError as exc:
        logger.error("OIDC login could not start: %s (%s)", exc.code, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=OidcMessages.OIDC_METADATA_INCOMPLETE,
        ) from exc
    # Discovery validated the authorization endpoint as an absolute https URL
    # (see app.services.auth.oidc.discovery), so this redirect always goes to
    # an https location.
    response = RedirectResponse(begun.authorization_url)
    response.set_cookie(
        key=OIDC_FLOW_COOKIE,
        value=_state_digest(begun.state),
        max_age=OIDC_NEXT_COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.app_url_is_https,
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
    )
    if not mobile and is_safe_next_path(next_path):
        response.set_cookie(
            key=OIDC_NEXT_COOKIE,
            value=next_path,
            max_age=OIDC_NEXT_COOKIE_MAX_AGE,
            httponly=True,
            secure=settings.app_url_is_https,
            samesite="lax",
            path=REFRESH_COOKIE_PATH,
        )
    return response


@router.get("/c/{community_id}/providers", response_model=LoginProvidersResponse)
async def list_community_login_providers(
    session: SessionDep, system_session: SystemSessionDep, guild_id: CommunityIdPath
) -> LoginProvidersResponse:
    """The ways in this community counts as its own — non-secret metadata
    only, plus its display name for its sign-in page.

    A community does not authenticate anybody: these are the deployment's own
    providers, and the buttons lead to the deployment's sign-in. What the
    community has said about them is applied when somebody reaches it. Empty
    (and nameless) where it connects to nothing and where single sign-on is
    not permitted; an unknown guild id is indistinguishable from an empty
    list."""
    if not await auth_posture.login_method_allowed(system_session, LoginMethod.sso):
        return LoginProvidersResponse(providers=[])
    rows = await guild_connections.connected_providers(
        system_session, guild_id=guild_id
    )
    entries = [_login_entry(row) for row in rows if is_login_ready(row)]
    guild_name = None
    if entries:
        guild = await system_session.get(Guild, guild_id)
        guild_name = guild.name if guild else None
    return LoginProvidersResponse(providers=entries, community_name=guild_name)


@router.get("/{provider_slug}/login")
async def provider_login(
    request: Request,
    session: SessionDep,
    system_session: SystemSessionDep,
    provider_slug: str,
    mobile: bool = Query(default=False),
    device_name: str = Query(default="Mobile Device"),
    next_path: str = Query(default="", alias="next"),
    code_challenge: str = Query(default=""),
) -> RedirectResponse:
    """Begin the relying-party flow for one operator-global provider. The
    platform provider's slug is ``oidc``, so the pre-generalization
    ``/auth/oidc/login`` URL is this same route.

    The app sends ``code_challenge`` (S256) and gets back a one-time code bound
    to it; see :mod:`app.services.auth.native_handoff`."""
    if code_challenge and not native_handoff.is_challenge(code_challenge):
        return _error_redirect(mobile, "invalid_state")
    provider_row = await _resolve_login_provider(system_session, provider_slug)
    return await _begin_provider_login(
        system_session,
        provider_row,
        mobile=mobile,
        device_name=device_name,
        next_path=next_path,
        app_challenge=code_challenge,
    )


def _error_redirect(is_mobile: bool | None, error: str) -> RedirectResponse:
    """Redirect to app/frontend with error instead of returning JSON."""
    params = {"error": error}
    if is_mobile:
        url = f"{MOBILE_CALLBACK_URI}?{urlencode(params)}"
    else:
        url = f"{frontend_callback_url()}?{urlencode(params)}"
    return RedirectResponse(url)


async def _complete_provider_login(
    request: Request,
    session: AsyncSession,
    system_session: AsyncSession,
    provider_row: AuthProvider,
    code: str | None,
    state: str | None,
):
    """Complete the relying-party flow for a resolved provider.

    One sign-in for the whole deployment. What each community makes of it —
    whether this arrival counts as one of its own, and whether it joins them
    to it — is applied from its connections once the identity is settled.
    """
    # Best-effort mobile flag so even early failures land on the right surface
    # (app vs. web); ``complete()`` re-validates the state authoritatively.
    is_mobile: bool | None = None
    if state:
        try:
            is_mobile = decode_flow_state(state).mobile
        except FlowStateError:
            is_mobile = None

    if not state or not hmac.compare_digest(
        request.cookies.get(OIDC_FLOW_COOKIE, ""), _state_digest(state)
    ):
        return _error_redirect(is_mobile, "invalid_state")
    provider = await _build_row_oidc_provider(system_session, provider_row)
    try:
        completion = await provider.complete(code=code or "", state=state or "")
    except OidcFlowError as exc:
        logger.warning("OIDC callback rejected: %s (%s)", exc.code, exc)
        return _error_redirect(is_mobile, exc.code)
    is_mobile = completion.mobile

    # The verified id_token is the identity source of truth; userinfo (when the
    # provider advertises it) only enriches profile claims, and only when its
    # sub matches the id_token's (OIDC Core §5.3.2).
    claims = dict(completion.claims)
    userinfo: dict[str, Any] | None = None
    if completion.access_token:
        try:
            userinfo = await provider.fetch_userinfo(completion.access_token)
        except OidcFlowError as exc:
            logger.warning("OIDC userinfo enrichment failed: %s", exc)
    if userinfo is not None:
        if userinfo.get("sub") == completion.subject:
            for key, value in userinfo.items():
                claims.setdefault(key, value)
        else:
            logger.warning(
                "OIDC userinfo sub does not match id_token sub; ignoring userinfo"
            )
            userinfo = None

    # Does the community this route belongs to recognise who just arrived?
    # Asked of the verified id_token and before any account or membership is
    # touched, because a no here means this person is not theirs.

    email_claim = claims.get("email")
    email = (
        normalize_email(email_claim)
        if isinstance(email_claim, str) and email_claim.strip()
        else None
    )
    # Trust the IdP's ``email_verified`` claim only as an explicit ``true``; a
    # missing/false claim is treated as unverified (some IdPs omit it entirely).
    email_verified = claims.get("email_verified") is True
    picture_claim = claims.get("picture")
    avatar_url = (
        picture_claim if isinstance(picture_claim, str) and picture_claim else None
    )

    resolution = await resolve_oidc_identity(
        system_session,
        provider=provider_row,
        subject=completion.subject,
        email=email,
        email_verified=email_verified,
        avatar_url=avatar_url,
    )

    if resolution.user is None:
        # JIT_DISABLED / REGISTRATION_DISABLED: unknown user, provisioning off.
        return _error_redirect(is_mobile, OidcMessages.REGISTRATION_DISABLED)
    user = resolution.user

    # Refuse to silently reactivate an operator- or self-deactivated account via
    # SSO — deactivation is reversed by an operator, not by a login. Checked
    # before any link is written.
    #
    # An account waiting out its erasure window is the deliberate exception
    # (SIGN_IN_STATUSES): the holder coming back is exactly what calls the
    # deletion off, and which way they came back is not the question. Unless
    # its own age answer closed it, which no sign-in calls off (may_sign_in).
    if not may_sign_in(user):
        return _error_redirect(is_mobile, OidcMessages.ACCOUNT_INACTIVE)

    if resolution.outcome is ResolutionOutcome.EMAIL_UNVERIFIED:
        # An unlinked local account matched by an email the IdP has not
        # verified: refused, protecting pre-registered accounts.
        logger.warning(
            "OIDC login refused: email_verified not asserted for existing "
            "account (user_id=%s)",
            user.id,
        )
        return _error_redirect(is_mobile, OidcMessages.EMAIL_UNVERIFIED)

    identity = resolution.identity
    matched = resolution.outcome is ResolutionOutcome.EMAIL_MATCH
    # Set where this sign-in proves an address the person added themselves.
    proved_at = datetime.now(timezone.utc)
    proved_address: str | None = None
    proved_id: int | None = None
    # The address this provider asserts for the account. A provisioned account
    # already holds it; a linked one existed first, so this is where a work
    # address arrives beside whatever the person signed up with. A matched
    # account's address is proved below, by the rule an emailed code uses.
    row = (
        await addresses.ensure_address(
            system_session,
            user_id=user.id,
            email=email,
            source=addresses.SOURCE_OIDC,
            verified=email_verified and not matched,
            provider_id=provider_row.id,
            now=proved_at,
        )
        if email
        else None
    )
    if matched:
        # Platform policy: a verified IdP email claims its matching local
        # account (parity with the previous flow); the link makes every later
        # login resolve by (provider, subject).
        # Staged before the link, which commits: the two land together rather
        # than the record trailing a link already durable.
        await audit_service.record(
            system_session,
            event_type=AuditEventType.AUTH_IDENTITY_LINKED,
            actor_user_id=user.id,
            target_type="auth_provider",
            target_id=provider_row.id,
            detail={"provider": provider_row.slug, "matched_by": "verified_email"},
        )
        # An address the account had not proved is proved here for the first
        # time, and the account starts from that proof, as it does when an
        # emailed code is the first proof. The proof, the retirement and the
        # link land in one commit.
        if row is not None and row.id is not None:
            await addresses.prove_at_sign_in(
                system_session, user=user, address_id=row.id, now=proved_at
            )
        identity = await link_identity(
            system_session,
            user=user,
            provider=provider_row,
            subject=completion.subject,
            email_verified=email_verified,
        )
    if row is not None and await addresses.proved_a_new_way_in(
        system_session, row, at=proved_at
    ):
        proved_address, proved_id = email, row.id

    # Profile refresh from the verified claims.
    if avatar_url and user.avatar_url != avatar_url:
        user.avatar_url = avatar_url
    # Record the login on the identity link: the IdP refresh token (rotated by
    # the background group re-sync) and the sync stamp the sweep filters on —
    # the ``federated_identities`` successors of the legacy ``users.oidc_*``
    # columns, which are no longer written and drop in the final cutover phase.
    if identity is not None:
        if completion.refresh_token:
            await set_identity_refresh_token(
                system_session,
                identity_id=identity.id,
                refresh_token=completion.refresh_token,
            )
        identity.last_synced_at = datetime.now(timezone.utc)
        system_session.add(identity)
    system_session.add(user)
    await system_session.commit()
    await system_session.refresh(user)
    if matched:
        # A new way into the account: its holder is told, with the way to say
        # it wasn't them.
        await email_service.announce_identity_linked(
            system_session, user, provider=provider_row.display_name
        )
    if proved_address is not None:
        # A sign-in at a provider is no place the account already uses, so a
        # proof that arrives with it can be undone by the addresses before it.
        await email_service.announce_address_change(
            system_session,
            user,
            change="proved",
            address=proved_address,
            record=await account_changes.change_record(
                system_session,
                user_id=user.id,
                risky=True,
                undo={"kind": "proved", "address_id": proved_id},
            ),
        )

    # What each community makes of this arrival. A connection can say that
    # people it counts as its own join on sight, which is how somebody reaches
    # a community they have never been invited to.
    await guild_connections.join_on_arrival(
        system_session,
        provider_id=provider_row.id,
        user_id=user.id,
        claims=dict(claims or {}),
    )
    await post_commit.settle(system_session)
    # It commits and rolls back the communities at capacity, either of which
    # leaves this copy of the account stale.
    await system_session.refresh(user)

    # OIDC claim-to-role sync (the id_token claims are verified upstream now).
    # A rule grants in the community it names, where that community's
    # connection counts this arrival as one of its own.
    try:
        claim_path = provider_row.role_claim_path
        if await provider_placement.provider_syncs_placement(
            system_session, provider_id=provider_row.id
        ):
            claim_values = (
                extract_claim_values(userinfo or {}, completion.claims, claim_path)
                if claim_path
                else set()
            )
            async with db_session.SystemSessionLocal() as sync_session:
                sync_result = await sync_oidc_assignments(
                    sync_session,
                    user_id=user.id,
                    provider_id=provider_row.id,
                    claim_values=claim_values,
                    claims=claims,
                )
                logger.info(
                    "OIDC sync for user %s: +%d/~%d/-%d guilds, +%d/~%d/-%d initiatives",
                    user.id,
                    len(sync_result.guilds_added),
                    len(sync_result.guilds_updated),
                    len(sync_result.guilds_removed),
                    len(sync_result.initiatives_added),
                    len(sync_result.initiatives_updated),
                    len(sync_result.initiatives_removed),
                )
    except Exception:
        logger.exception("OIDC claim sync failed for user %s", user.id)

    if is_mobile and not completion.app_challenge:
        # An app bundle from before the code flow began this sign-in. It can
        # only be handed a session through the code, so it is asked to update.
        return _error_redirect(True, NativeMessages.APP_UPDATE_REQUIRED)
    # ``user`` is attached to ``system_session``, so a rollback expires its
    # attributes; the plain values are captured up front so the failure path
    # never touches the ORM object again.
    user_id, token_version = user.id, user.token_version
    provider_id, provider_slug = provider_row.id, provider_row.slug
    provider_asserts_factor = provider_row.asserts_second_factor
    # Return the browser to where the login started (a step-up hands the
    # guild page it interrupted): the login route stored a validated SPA
    # path in the short-lived cookie; re-validate before echoing it, and
    # clear the cookie either way.
    next_path = request.cookies.get(OIDC_NEXT_COOKIE, "")
    frontend_uri = frontend_callback_url()
    if is_safe_next_path(next_path):
        frontend_uri = f"{frontend_uri}?{urlencode({'next': next_path})}"
    oidc_response = RedirectResponse(frontend_uri)
    oidc_response.delete_cookie(key=OIDC_NEXT_COOKIE, path=REFRESH_COOKIE_PATH)
    oidc_response.delete_cookie(key=OIDC_FLOW_COOKIE, path=REFRESH_COOKIE_PATH)
    assurance = read_assurance(completion.claims)
    # What this provider asserted for the claims some community narrows it by.
    # A fact about the authentication, kept beside the rest, so the rule about
    # which values count is read fresh when somebody reaches a community.
    narrowing = await guild_connections.narrowed_by(
        system_session, provider_id=provider_id
    )
    if narrowing:
        assurance = replace(
            assurance,
            claims=read_narrowing(completion.claims, userinfo, narrowing),
        )
    amr = session_amr(
        provider_slug,
        assurance,
        asserts_second_factor=provider_asserts_factor,
    )
    satisfied = [provider_id]
    if is_mobile:
        try:
            code = await native_handoff.issue(
                system_session,
                app_challenge=completion.app_challenge,
                handoff=native_handoff.Handoff(
                    user_id=user_id,
                    method="oidc",
                    amr=amr,
                    device_name=completion.device_name or "Mobile Device",
                    satisfied_providers=satisfied,
                    provider_auth=record_for_provider(
                        None, provider_id=provider_id, assurance=assurance
                    ),
                ),
            )
            await system_session.commit()
        except Exception:
            await system_session.rollback()
            logger.exception("Could not hand a native sign-in to user %s", user_id)
            return _error_redirect(True, OidcMessages.SESSION_STORE_UNAVAILABLE)
        return RedirectResponse(f"{MOBILE_CALLBACK_URI}?{urlencode({'code': code})}")
    # A step-up upgrades the session it interrupted rather than starting over
    # (see ``upgrade_session``). Only the same user's session merges; anything
    # else is a fresh sign-in.
    #
    # The assurance record merges per provider: this provider's entry is
    # replaced by what it just asserted, and every other provider's account of
    # its own event is left as it was.
    prior = None
    prior_raw = request.cookies.get(REFRESH_COOKIE_NAME)
    if prior_raw:
        prior = await session_service.get_live_session_by_refresh_token(
            system_session, prior_raw
        )
        if prior is not None and prior.user_id != user_id:
            prior = None
    provider_auth = record_for_provider(
        prior.provider_auth if prior is not None else None,
        provider_id=provider_id,
        assurance=assurance,
    )
    # What the provider said about this authentication, in the same shape the
    # session row keeps, with its narrowing claims named rather than valued.
    # Absent claims add no keys.
    assured = assurance.as_record()
    claims = assured.pop("claims", None)
    audit_detail = {
        "method": "oidc",
        "provider": provider_slug,
        "step_up": prior is not None,
        **assured,
        **({"claim_names": sorted(claims)} if claims else {}),
    }
    try:
        if prior is None:
            await open_session(
                request,
                oidc_response,
                system_session,
                user_id=user_id,
                token_version=token_version,
                amr=amr,
                audit_detail=audit_detail,
                satisfied_providers=satisfied,
                provider_auth=provider_auth,
                device=False,
            )
        else:
            await upgrade_session(
                request,
                oidc_response,
                system_session,
                user=user,
                add_amr=amr,
                prior=prior,
                add_providers=satisfied,
                provider_auth=provider_auth,
                audit_detail=audit_detail,
            )
    except HTTPException:
        # The provider authenticated them; we could not record it. Back to the
        # app with a code rather than a credential that cannot renew.
        return _error_redirect(is_mobile, OidcMessages.SESSION_STORE_UNAVAILABLE)
    return oidc_response


@router.get("/{provider_slug}/callback")
async def provider_callback(
    request: Request,
    session: SessionDep,
    system_session: SystemSessionDep,
    provider_slug: str,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
):
    """Complete the relying-party flow for one operator-global provider (see
    provider_login: the platform provider's slug is ``oidc``, so the URL
    operators registered at their IdP is this same route)."""
    provider_row = await _resolve_login_provider(system_session, provider_slug)
    return await _complete_provider_login(
        request, session, system_session, provider_row, code, state
    )


@router.post("/verification/confirm", response_model=VerificationSendResponse)
async def confirm_verification(
    request: Request,
    system_session: SystemSessionDep,
    payload: VerificationConfirmRequest,
) -> VerificationSendResponse:
    # The account and the token are both the system engine's (the caller holds
    # a token, not a session), so the address it proves and the token it spends
    # commit together.
    record = await user_tokens.get_valid_token(
        system_session,
        token=payload.token,
        purpose=UserTokenPurpose.email_verification,
    )
    if not record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.INVALID_OR_EXPIRED_TOKEN,
        )
    user_stmt = select(User).where(User.id == record.user_id)
    user_result = await system_session.exec(user_stmt)
    user = user_result.one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )
    # A token minted for one address proves that address; the older
    # account-level tokens carry none and prove the account.
    proved_address = None
    proved_id: int | None = None
    # Whether adding it was risky, as the request that added it found.
    risky = (record.change or {}).get("risky", True)
    if record.user_email_id is not None:
        proved_at = datetime.now(timezone.utc)
        try:
            row = await addresses.verify_for_user(
                system_session,
                user_id=user.id,
                address_id=record.user_email_id,
                now=proved_at,
            )
        except addresses.AddressError:
            # Somebody else proved the same address first. The claim is over,
            # and the token that carried it is spent either way. The rollback
            # expired ``record``, so it is spent by its value.
            await system_session.rollback()
            await user_tokens.consume_token(
                system_session,
                token=payload.token,
                purpose=UserTokenPurpose.email_verification,
            )
            raise
        if await addresses.proved_a_new_way_in(system_session, row, at=proved_at):
            proved_address = decrypt_field(row.email_encrypted, SALT_EMAIL)
            proved_id = row.id

    record.consumed_at = datetime.now(timezone.utc)
    system_session.add(record)
    if record.invite_id is not None:
        await _join_awaited_invite(
            system_session, invite_id=record.invite_id, user=user
        )
    await system_session.commit()
    if proved_address is not None:
        await email_service.announce_address_change(
            system_session,
            user,
            change="proved",
            address=proved_address,
            record=await account_changes.change_record(
                system_session,
                user_id=user.id,
                risky=risky,
                undo={"kind": "proved", "address_id": proved_id},
            ),
        )
    await post_commit.settle(system_session)
    return VerificationSendResponse(status="verified")


async def _join_awaited_invite(
    session: AsyncSession, *, invite_id: int, user: User
) -> None:
    """Join the guild a sign-up's invite was waiting on its address for.

    The address is proved whether or not this goes through: an invite that
    expired, filled up or was withdrawn in the meantime joins nothing, and the
    person can be sent another.
    """
    try:
        async with session.begin_nested():
            await guilds_service.redeem_invite_for_user(
                session, invite_id=invite_id, user=user
            )
    except (
        guilds_service.GuildInviteError,
        guilds_service.GuildCapacityError,
        guilds_service.GuestsDisabledError,
        guilds_service.AgeConfirmationRequiredError,
    ) as exc:
        logger.info(
            "Invite %s not joined on confirming user %s: %s", invite_id, user.id, exc
        )


async def _post_reset_letter(user_id: int, token: str) -> None:
    """Post a reset letter once the response has gone.

    After the response, on a session of its own, so the answer to a reset
    request takes the same time whether or not the address reaches an account.
    A letter that cannot be posted is logged; the person asks again.
    """
    try:
        async with db_session.SystemSessionLocal() as letter_session:
            user = await letter_session.get(User, user_id)
            if user is not None:
                await email_service.send_password_reset_email(
                    letter_session, user, token
                )
    except Exception:
        logger.exception("Could not post a password reset letter to %s", user_id)


@router.post("/password/forgot", response_model=VerificationSendResponse)
async def request_password_reset(
    request: Request,
    payload: PasswordResetRequest,
    background: BackgroundTasks,
    session: SessionDep,
    system_session: SystemSessionDep,
) -> VerificationSendResponse:
    """Send a reset link to the account an address reaches.

    Answered the same way for every address: whether mail can be sent at all is
    asked before the address is looked up, the address's mail allowance is
    taken whether or not anybody holds it, and the letter is posted after the
    response.
    """
    await require_login_method(session, LoginMethod.password)
    if not await email_service.email_configured(system_session):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.SMTP_NOT_CONFIGURED,
        )
    if not await MAIL_SENDS.take(payload.email):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=AuthMessages.RATE_LIMITED,
        )
    # Held, not necessarily confirmed: an account that never confirmed the
    # address it signed up with is exactly the one a reset has to reach.
    user = await addresses.account_holding(system_session, payload.email)
    if user is not None and user.status == UserStatus.active:
        token = await user_tokens.create_token(
            system_session,
            user_id=user.id,
            purpose=UserTokenPurpose.password_reset,
            expires_minutes=60,
        )
        background.add_task(_post_reset_letter, user.id, token)
    return VerificationSendResponse(status="sent")


@router.post("/password/reset", response_model=VerificationSendResponse)
async def reset_password(
    request: Request,
    payload: PasswordResetSubmit,
    session: SessionDep,
    system_session: SystemSessionDep,
) -> VerificationSendResponse:
    await require_login_method(session, LoginMethod.password)
    # Run the policy first so an invalid candidate doesn't burn the
    # reset token; ``consume_token`` is one-shot.
    await validate_new_password(session, payload.password)
    record = await user_tokens.consume_token(
        system_session,
        token=payload.token,
        purpose=UserTokenPurpose.password_reset,
    )
    if not record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.INVALID_OR_EXPIRED_TOKEN,
        )
    # The caller holds a one-shot token rather than a session, so the row is
    # written on the system engine.
    user = await system_session.get(User, record.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )
    # The link proved the inbox, which is what lets the reset start the count
    # against the account over.
    await set_password(
        request, system_session, user=user, password=payload.password, via="reset"
    )
    return VerificationSendResponse(status="reset")
