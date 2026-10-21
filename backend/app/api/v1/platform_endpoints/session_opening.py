"""Opening the session a sign-in earned, whatever proved it.

Every way in ends the same way — a server-side session, an access token bounded
by it, a refresh token, and one audit record saying which way it was — and
:func:`issue_session` is the one place that writes a session and mints its
token. It stages; :func:`session_store` commits what the caller staged beside
it, or rolls all of it back and answers 503. :func:`mint_for` is the one place
an access token is given its lifetime, so a session narrowed by a community's
compliance setting narrows every token minted for it, on every path.

What each route keeps for itself is the proving. :func:`prove_password` is that
proving for the two routes that take a password, and
:func:`second_factor_outstanding` is what both of them, and the emailed code,
answer with when the account holds a second factor. :func:`prove_second_factor`
takes that factor's answer, at a sign-in and wherever else it is asked for.

:func:`open_session` is a fresh sign-in and :func:`upgrade_session` a step-up
against the session already open. :func:`set_password` is the one write of the
account's password, and opens the session a caller carries on with after it
retires every credential the account held.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlmodel import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel.ext.asyncio.session import AsyncSession as SqlModelSession

from app.api.v1.platform_endpoints.session_cookies import (
    set_refresh_cookie,
    set_session_cookie,
)
from app.core.audit_events import AuditEventType
from app.core.config import install_id, is_device, settings
from app.core.login_methods import LoginMethod
from app.core.messages import AuthMessages, SettingsMessages
from app.core import audit_context
from app.core.rate_limit import SIGN_IN_FAILURES
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.core.security import (
    REFRESH_COOKIE_NAME,
    get_password_hash,
    mint_access_token,
    password_needs_rehash,
    verify_sign_in_password,
)
from app.demo import samples as demo_samples
from app.models.platform.auth_session import AuthSession
from app.models.platform.user import User, may_sign_in
from app.schemas.platform.token import Token
from app.services import audit as audit_service
from app.services import email as email_service
from app.services.auth import addresses
from app.services.auth.assurance import SECOND_FACTOR_AMR
from app.services.auth import challenges as challenge_service
from app.services.auth import passkeys as passkey_service
from app.services.auth import sessions as session_service
from app.services.auth import sign_in_locks
from app.services.auth import subject as subject_service
from app.services.auth import totp as totp_service
from app.services.platform import auth_posture
from app.services.platform import user_tokens
from app.services.content_sockets import sockets as content_sockets

logger = logging.getLogger(__name__)

#: Where a phone's sign-in comes back to. The app registers this scheme and
#: ``useDeepLinks`` routes it; the OIDC callback and the passkey relay both
#: hand the app a one-time code at this address (see ``native_handoff``).
MOBILE_CALLBACK_URI = "initiative://oidc/callback"


async def require_login_method(session: AsyncSession, method: LoginMethod) -> None:
    """Refuse a sign-in by a route this deployment does not permit.

    Server-side, so withdrawing a method closes the route rather than only
    hiding its form. Existing sessions are untouched — this gates opening a new
    one, not holding one already open.
    """
    if not await auth_posture.login_method_allowed(session, method):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=SettingsMessages.LOGIN_METHOD_NOT_PERMITTED,
        )


async def require_passkeys_allowed(session: AsyncSession) -> None:
    """Refuse a passkey ceremony — a sign-in, a sign-up, a registration or a
    step-up — this deployment would not accept.

    Two things: the deployment permits passkeys, by the same rule as every
    other way in, and its address can carry one — a plain-http or IP-literal
    address cannot, and saying so is better than a ceremony the browser will
    refuse. The credentials an account already holds are left where they are;
    while either refusal stands they simply stop being a way in.
    """
    await require_login_method(session, LoginMethod.passkey)
    if passkey_service.site_refusal() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.PASSKEY_SITE_UNSUPPORTED,
        )


def current_session_row(request: Request) -> uuid.UUID | None:
    """The server-side session this request is on, or ``None``.

    Named by the request's own access token: every client carries one of
    those, and a credential that is not a session — an API key — names
    none.
    """
    raw = getattr(request.state, "session_id", None)
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


def require_session_row(request: Request) -> uuid.UUID:
    """The server-side session this request is on, or 403.

    The step-ups add to a session, so this is what they have to be holding
    before a ceremony is worth starting. Signing out has something to do
    either way, and reads :func:`current_session_row` instead.
    """
    session_id = current_session_row(request)
    if session_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AuthMessages.SESSION_REQUIRED,
        )
    return session_id


# Walk a session back up its rotation chain and read the oldest row there.
# ``parent_id`` always points at an older, pre-existing row and
# ``ck_auth_sessions_parent_not_self`` blocks the only reachable self-loop, so
# the graph is a strict in-tree and the recursion terminates.
_CHAIN_ROOT_SQL = text(
    """
    WITH RECURSIVE ancestors AS (
        SELECT id, parent_id, created_at FROM auth_sessions WHERE id = :sid
        UNION
        SELECT s.id, s.parent_id, s.created_at
        FROM auth_sessions s JOIN ancestors a ON s.id = a.parent_id
    )
    SELECT created_at FROM ancestors ORDER BY created_at LIMIT 1
    """
)


async def chain_started_at(
    system_session: AsyncSession, *, session_id: uuid.UUID
) -> datetime | None:
    """When the sign-in this session descends from was opened.

    Every refresh mints a new row pointing at the one it replaced, so a session
    that has been renewed for a week is still the same chain; its root is the
    sign-in. A step-up and a replacement each start a chain of their own, so
    both read as the moment they happened.

    ``None`` where there is no such row.
    """
    # One round trip on the session's own connection: a chain gains a row per
    # refresh, so walking it a row at a time would be as many.
    connection = await system_session.connection()
    result = await connection.execute(_CHAIN_ROOT_SQL, {"sid": session_id})
    return result.scalar_one_or_none()


async def signed_in_since(
    system_session: AsyncSession, *, session_id: uuid.UUID
) -> datetime | None:
    """How long the person behind this session has been signed in here.

    The start of its chain, or, where it took the place of an earlier session,
    the start of that one's: a step-up proves the person again without
    starting their time here over.
    """
    row = await system_session.get(AuthSession, session_id)
    if row is not None and row.continues_since is not None:
        return row.continues_since
    return await chain_started_at(system_session, session_id=session_id)


async def record_sign_in_failure(
    system_session: AsyncSession,
    user: User | None,
    *,
    method: str,
    reason: str,
) -> None:
    """Write down a refused sign-in and commit it.

    The account is the **target**, when one resolved, and there is no actor: the
    request that made the attempt is unauthenticated. An unknown address still
    records the refusal but retains no submitted identity.

    ``method`` is how the sign-in was being attempted — a password, a passkey —
    so the board can tell one run of refusals from another.


    Its own commit because the request is about to raise.
    """
    target_user_id = user.id if user is not None else None
    await audit_service.record(
        system_session,
        event_type=AuditEventType.AUTH_SIGN_IN_FAILED,
        actor_user_id=None,
        target_user_id=target_user_id,
        target_type="user" if target_user_id is not None else None,
        target_id=target_user_id,
        detail={"method": method, "reason": reason},
    )
    await system_session.commit()


def access_ttl_for(row: AuthSession, *, now: datetime) -> timedelta | None:
    """How long an access token for this session may live.

    ``None`` leaves the deployment's own ``AUTH_ACCESS_TTL_MINUTES`` in place,
    which is every ordinary session. Where the refresh row ends sooner than
    that — a community held to the compliance standard narrows it — the token
    ends with it: a token outliving the session it names would be the one gap
    in a control the row's own expiry otherwise keeps.

    Read off the row rather than resolved again, so the two clocks cannot
    disagree and no path pays a second query for the answer.
    """
    standard = timedelta(minutes=settings.AUTH_ACCESS_TTL_MINUTES)
    remaining = row.expires_at - now
    return remaining if remaining < standard else None


async def refuse_if_locked(system_session: AsyncSession, user_id: int) -> None:
    """Refuse a password or code for an account whose password and codes are
    turned off right now.

    Asked before the answer is checked, so a right one is refused too.
    """
    if await sign_in_locks.is_locked(system_session, user_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=AuthMessages.SIGN_IN_LOCKED,
        )


async def count_wrong_answer(system_session: AsyncSession, user_id: int) -> None:
    """Count a wrong password or code against the account, commit it, and tell
    the holder if that placed a lock. A demo sample account, which everyone
    signs in to, is never locked."""
    if await demo_samples.is_sample(user_id):
        return
    failure = await sign_in_locks.record_failure(system_session, user_id)
    await system_session.commit()
    if failure.lock_for is None:
        return
    user = await system_session.get(User, user_id)
    if user is not None:
        await email_service.announce_sign_in_locked(
            system_session,
            user,
            lock_for=failure.lock_for,
        )


async def _upgrade_password_hash(
    system_session: SqlModelSession, *, user: User, password: str
) -> None:
    """Re-hash a password that verified against outdated hashing parameters.

    Runs on the system engine. The row is the sign-in's own, but this happens
    before a session exists, so there is no request-path identity for the
    own-row rule on ``public.users`` to match against.

    Best-effort: a transient failure must not turn a successful authentication
    into a 500. The next sign-in retries the upgrade, and the stored hash keeps
    verifying until then.
    """
    try:
        new_hash = get_password_hash(password)
        await system_session.exec(
            sql_update(User).where(User.id == user.id).values(hashed_password=new_hash)
        )
        await system_session.commit()
        user.hashed_password = new_hash
    except Exception:
        await system_session.rollback()
        logger.exception("Failed to upgrade password hash for user %s", user.id)


async def prove_password(
    session: AsyncSession,
    system_session: SqlModelSession,
    *,
    email: str,
    password: str,
) -> User:
    """The account an address and password sign in to, or the refusal.

    The one proving for every route that takes a password, so each asks the
    same questions in the same order: whether the deployment permits passwords
    at all, whether the address has refusals left, whether the account is
    locked, whether the password matches, and whether the account and address
    may sign in. Every refusal is recorded.

    The password is checked whether or not the address resolved, so every
    attempt pays the same work.
    """
    await require_login_method(session, LoginMethod.password)
    # A demo sample's password is shown on the sign-in page, so a wrong one
    # holds nobody else back from it.
    shared = bool(await demo_samples.addresses_of([email]))
    if not shared and not await SIGN_IN_FAILURES.left(email):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=AuthMessages.SIGN_IN_LOCKED,
        )
    # Any of the account's addresses signs it in, resolved on the system engine
    # because there is nobody to scope a policy to until it returns.
    user = await addresses.find_user_by_address(system_session, email)
    # An address its holder has not confirmed admits nobody, but it is worth
    # saying so: resolved here only so the refusal below can name the reason.
    unconfirmed = (
        await addresses.account_awaiting_confirmation(system_session, email)
        if user is None
        else None
    )
    user = user or unconfirmed
    if user is not None:
        await refuse_if_locked(system_session, user.id)
    password_matches = verify_sign_in_password(
        password, user.hashed_password if user is not None else None
    )
    if not user or not password_matches:
        # Recorded whether or not the address resolved; the record keeps no
        # identity when there was none to keep.
        if not shared:
            await SIGN_IN_FAILURES.take(email)
        await record_sign_in_failure(
            system_session, user, method="password", reason="bad_password"
        )
        if user is not None:
            await count_wrong_answer(system_session, user.id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.INCORRECT_CREDENTIALS,
        )

    # Refused even though the password matched. SIGN_IN_STATUSES rather than
    # active: an account waiting out its erasure window signs in precisely so
    # that signing in can call the deletion off — unless its own age answer
    # closed it, which no sign-in calls off (may_sign_in).
    if not may_sign_in(user):
        await record_sign_in_failure(
            system_session, user, method="password", reason="inactive"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER
        )
    if unconfirmed is not None:
        await record_sign_in_failure(
            system_session, user, method="password", reason="email_unverified"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.EMAIL_NOT_VERIFIED,
        )

    if password_needs_rehash(user.hashed_password):
        await _upgrade_password_hash(system_session, user=user, password=password)
    # Which of the account's addresses was used, for the account page and for
    # telling an address in use from one nobody has signed in with.
    await addresses.note_sign_in(system_session, email=email)
    await SIGN_IN_FAILURES.clear(email)
    return user


@dataclass(frozen=True)
class SecondFactorProof:
    """Which of the account's codes answered, and what a session records for it."""

    method: str
    amr: tuple[str, ...]


async def prove_second_factor(
    system_session: AsyncSession,
    *,
    user_id: int,
    code: str | None,
    recovery_code: str | None,
    during: str,
    signed_in: bool,
) -> SecondFactorProof:
    """Take a code from the authenticator, or one of the recovery codes, or
    the refusal.

    The one check for every route that asks for the account's second factor,
    so each asks the same questions in the same order: whether the account is
    locked, then whether the answer is right. A recovery code is taken when one
    is presented, and a code from the authenticator otherwise. A wrong answer
    is recorded, counted against the account and committed; a right one starts
    the count over, and a spent recovery code is recorded with how many are
    left, both staged for the caller to commit.

    ``during`` names the errand in the audit line, and ``signed_in`` says
    whether the account's holder is the actor on it or the request is a
    sign-in nobody is authenticated for yet.
    """
    await refuse_if_locked(system_session, user_id)

    if recovery_code:
        accepted = await totp_service.consume_recovery_code(
            system_session, user_id=user_id, code=recovery_code
        )
        proof = SecondFactorProof(method="recovery_code", amr=(SECOND_FACTOR_AMR,))
        refusal = AuthMessages.RECOVERY_CODE_INVALID
    else:
        accepted = await totp_service.verify_code(
            system_session, user_id=user_id, code=code or ""
        )
        proof = SecondFactorProof(method="totp", amr=("otp", SECOND_FACTOR_AMR))
        refusal = AuthMessages.TOTP_INVALID

    if not accepted:
        await audit_service.record(
            system_session,
            event_type=AuditEventType.AUTH_SECOND_FACTOR_FAILED,
            actor_user_id=user_id if signed_in else None,
            target_user_id=user_id,
            target_type="user",
            target_id=user_id,
            detail={"method": proof.method, "during": during},
        )
        await count_wrong_answer(system_session, user_id)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=refusal)

    await sign_in_locks.record_success(system_session, user_id)
    if recovery_code:
        await audit_service.record(
            system_session,
            event_type=AuditEventType.AUTH_RECOVERY_CODE_USED,
            actor_user_id=user_id,
            detail={
                "remaining": await totp_service.remaining_recovery_codes(
                    system_session, user_id=user_id
                )
            },
        )
    return proof


@dataclass(frozen=True)
class FirstLeg:
    """What a sign-in proved before its second factor was asked for.

    Carried across to the second leg by the purpose of the challenge that holds
    the sign-in open, so the session it opens records both halves.
    """

    method: str
    amr: tuple[str, ...]
    purpose: challenge_service.ChallengePurpose
    native_purpose: challenge_service.ChallengePurpose


PASSWORD_LEG = FirstLeg(
    method="password",
    amr=("pwd",),
    purpose=challenge_service.ChallengePurpose.sign_in,
    native_purpose=challenge_service.ChallengePurpose.sign_in_native,
)
EMAIL_CODE_LEG = FirstLeg(
    method="email_otp",
    amr=("otp",),
    purpose=challenge_service.ChallengePurpose.sign_in_after_code,
    native_purpose=challenge_service.ChallengePurpose.sign_in_after_code_native,
)
FIRST_LEGS: tuple[FirstLeg, ...] = (PASSWORD_LEG, EMAIL_CODE_LEG)

#: Every purpose a second-factor challenge is opened with.
SECOND_FACTOR_PURPOSES: tuple[challenge_service.ChallengePurpose, ...] = tuple(
    purpose for leg in FIRST_LEGS for purpose in (leg.purpose, leg.native_purpose)
)


def first_leg_of(purpose: str) -> tuple[FirstLeg, bool]:
    """The first leg a second-factor challenge was opened after, and whether
    it was the native sign-in's."""
    for leg in FIRST_LEGS:
        if purpose == leg.purpose.value:
            return leg, False
        if purpose == leg.native_purpose.value:
            return leg, True
    raise ValueError(f"not a second-factor challenge: {purpose!r}")


async def second_factor_outstanding(
    session: AsyncSession,
    system_session: AsyncSession,
    *,
    user_id: int,
    leg: FirstLeg,
    native: bool,
) -> JSONResponse | None:
    """The challenge to present a second factor against, where one is owed.

    ``None`` when the account holds no second factor, or the deployment does
    not permit one, and the sign-in is finished. Otherwise the challenge is
    committed and the 401 that hands it to the client comes back for the route
    to return.
    """
    if not await auth_posture.login_method_allowed(session, LoginMethod.totp):
        return None
    if not await totp_service.is_enrolled(system_session, user_id=user_id):
        return None
    issued = await challenge_service.create(
        system_session,
        user_id=user_id,
        purpose=leg.native_purpose if native else leg.purpose,
    )
    await system_session.commit()
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": AuthMessages.TOTP_REQUIRED, "challenge": issued.value},
    )


@dataclass(frozen=True)
class OpenedSession:
    """A session and the tokens that carry it, as :func:`mint_for` hands it.

    ``refresh_token`` exists only here until a response carries it.
    """

    session: AuthSession
    access_token: str
    access_max_age: int
    refresh_token: str

    def to_token(self, *, include_refresh: bool) -> Token:
        return Token(
            access_token=self.access_token,
            refresh_token=self.refresh_token if include_refresh else None,
        )

    def set_cookies(self, response: Response) -> None:
        set_session_cookie(response, self.access_token, max_age=self.access_max_age)
        set_refresh_cookie(response, self.refresh_token)


def mint_for(
    issued: session_service.IssuedSession, *, subject: str, token_version: int
) -> OpenedSession:
    """The access token for one session, bounded by the session.

    The only place an access token is given its lifetime: a session opened
    here and a session renewed by ``/auth/refresh`` both come through it.
    """
    row = issued.session
    access_token, access_max_age = mint_access_token(
        subject=subject,
        token_version=token_version,
        session_id=row.id,
        amr=row.amr,
        satisfied_providers=row.satisfied_providers,
        provider_auth=row.provider_auth,
        expires_in=access_ttl_for(row, now=row.created_at),
    )
    return OpenedSession(
        session=row,
        access_token=access_token,
        access_max_age=access_max_age,
        refresh_token=issued.refresh_token,
    )


@asynccontextmanager
async def session_store(
    system_session: AsyncSession, *, user_id: int
) -> AsyncIterator[None]:
    """Commit a session and everything staged beside it, or none of it.

    A sign-in *is* the session. If it cannot be written the request says so
    with a 503 rather than handing back a lesser credential. Anything the
    caller stages inside — an audit record, the revocation of
    the session it replaces — commits with the session, or goes with it.
    """
    try:
        yield
        await system_session.commit()
    except Exception as exc:
        await system_session.rollback()
        logger.exception("Could not open a session for user %s", user_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AuthMessages.SESSION_STORE_UNAVAILABLE,
        ) from exc


async def issue_session(
    request: Request,
    system_session: AsyncSession,
    *,
    user_id: int,
    token_version: int,
    amr: Sequence[str],
    satisfied_providers: Sequence[int] = (),
    provider_auth: dict[str, Any] | None = None,
    device_name: str | None = None,
    install: uuid.UUID | None = None,
    replaces: uuid.UUID | None = None,
    ends_by: datetime | None = None,
) -> OpenedSession:
    """Stage a session and mint the access token for it.

    Called inside :func:`session_store`, which commits it. Session writes run
    on the system engine (``auth_sessions`` is ``app_admin``-only).

    ``amr`` is what the session may claim was proved. ``replaces`` names a
    session this one takes the place of: its whole rotation chain is revoked in
    the same transaction, since a refresh can have left descendants the new
    session also replaces. The new session is a fresh chain root, so the walk
    never reaches it.

    ``install`` makes it a device's session. A sign-in from an install that has
    signed in before continues that install, live or not: its last session's
    chain is revoked and its key store and push registration move here, so the
    device keeps its messages and is still one device. It is a new sign-in, so
    it starts its own chain and its own limits.
    """
    previous: uuid.UUID | None = None
    if install is not None:
        # Two sign-ins from one install take turns, so the second continues the
        # first rather than meeting it in the one-live-session index.
        await advisory_lock(
            system_session, LockNamespace.APP_INSTALL, f"{user_id}:{install}"
        )
        if replaces is None:
            previous = await session_service.latest_of_install(
                system_session, user_id=user_id, install_id=install
            )
    since = (
        await signed_in_since(system_session, session_id=replaces)
        if replaces is not None
        else None
    )
    # Revoked before the new row is written: an install holds one live session.
    for ended in (replaces, previous):
        if ended is not None:
            await session_service.revoke_chain(system_session, session_id=ended)
    issued = await session_service.create_session(
        system_session,
        user_id=user_id,
        amr=list(dict.fromkeys(amr)),
        satisfied_providers=sorted(set(satisfied_providers)),
        provider_auth=provider_auth,
        user_agent=audit_context.client_user_agent(),
        ip=audit_context.client_ip(),
        device_name=device_name,
        install_id=install,
        ends_by=ends_by,
    )
    issued.session.continues_since = since
    for ended in (replaces, previous):
        if ended is not None:
            await session_service.follow_devices(
                system_session, from_id=ended, to_id=issued.session.id
            )
    # The name the token will carry, in the same transaction as the session.
    subject = await subject_service.subject_for_user(system_session, user_id=user_id)
    return mint_for(issued, subject=subject, token_version=token_version)


async def open_session(
    request: Request,
    response: Response,
    system_session: AsyncSession,
    *,
    user_id: int,
    token_version: int,
    amr: Sequence[str],
    audit_detail: dict[str, Any],
    satisfied_providers: Sequence[int] = (),
    provider_auth: dict[str, Any] | None = None,
    device_name: str | None = None,
    device: bool | None = None,
    ends_by: datetime | None = None,
) -> Token:
    """Open the session a sign-in earned, and hand back its token.

    Every sign-in comes through here: it is recorded, the wrong answers counted
    against the account start over, and the session is written. The access
    token carries sid/amr/sat; the rotating refresh cookie carries the session.
    ``amr`` is what this sign-in proved, and ``satisfied_providers`` and
    ``provider_auth`` the providers it satisfied and their own account of it.

    A device's sign-in opens a device session and is handed the refresh token
    in the body too, since the app keeps its own; ``device_name`` labels it.
    ``device`` is read from the request (:func:`is_device`) unless the caller
    already knows the answer, and the install it names
    (:func:`~app.core.config.install_id`) is the one it continues. An app too
    old to name one is an install of its own.

    Anything the caller staged in ``system_session`` — a credential's counter,
    a spent challenge — commits with the session, or goes with it.

    ``ends_by`` is the latest the session may last, whatever the deployment's
    lifetimes would allow.
    """
    if device is None:
        device = is_device(request)
    async with session_store(system_session, user_id=user_id):
        await audit_service.record(
            system_session,
            event_type=AuditEventType.AUTH_SIGNED_IN,
            actor_user_id=user_id,
            detail=audit_detail,
        )
        # Signed in, so the wrong answers before this no longer add up to a lock.
        await sign_in_locks.record_success(system_session, user_id)
        issued = await issue_session(
            request,
            system_session,
            user_id=user_id,
            token_version=token_version,
            amr=amr,
            satisfied_providers=satisfied_providers,
            provider_auth=provider_auth,
            device_name=device_name if device else None,
            install=(install_id(request) or uuid.uuid4()) if device else None,
            ends_by=ends_by,
        )
    issued.set_cookies(response)
    return issued.to_token(include_refresh=device)


async def live_session_of(
    system_session: AsyncSession, *, session_id: uuid.UUID | None, user_id: int
) -> AuthSession | None:
    """The session ``session_id`` names, while it is live and ``user_id``'s."""
    if session_id is None:
        return None
    row = await system_session.get(AuthSession, session_id)
    if row is None or row.user_id != user_id or row.revoked_at is not None:
        return None
    return row


#: How a password came to be set, as its record says.
PasswordVia = Literal["self_service", "reset", "recovery_code"]


async def set_password(
    request: Request,
    system_session: AsyncSession,
    *,
    user: User,
    password: str | None,
    via: PasswordVia,
    response: Response | None = None,
    password_proved: bool = False,
) -> None:
    """Set, change, reset or give up the account's password.

    The one write for each of those, so every route does the same things in
    the same transaction: the new hash (or none, for ``password=None``) and
    when it was set, the record of it, and every credential the account held
    retired with :func:`~app.services.platform.user_tokens.revoke_user_sessions`.
    A reset and a recovery are each proved by a credential that stands in for
    the password, so those two also start over what was counted against the
    account (:func:`~app.services.auth.sign_in_locks.lift`); a change made from
    a session leaves the count as it is.

    ``user`` is written on the system engine, whichever session the caller read
    it on.

    ``response``, where given, keeps this device signed in: a session is opened
    in place of the one the request is on, and both cookies are set on it. A
    new password starts that session over: it claims the password where the
    caller re-checked the one the account held (``password_proved``), and no
    community's sign-in. Giving the password up leaves every other way in as it
    was, so that session carries what the one it replaces had proved, which
    communities asking for a sign-in of their own it had satisfied, and each
    provider's own account of that. It joins the same commit, so a failure
    leaves the account holding what it had and answers 503.

    Once that commit lands, open connections are closed — this device's too;
    its replacement session reconnects them — and the account is told.
    """
    user_id = user.id
    account = await system_session.get(User, user_id)
    if account is None:  # pragma: no cover - resolved by the caller
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )
    # Read before the revocation below retires it.
    prior = (
        await live_session_of(
            system_session, session_id=current_session_row(request), user_id=user_id
        )
        if response is not None
        else None
    )
    issued: OpenedSession | None = None
    async with session_store(system_session, user_id=user_id):
        now = datetime.now(timezone.utc)
        account.hashed_password = (
            get_password_hash(password) if password is not None else None
        )
        account.password_set_at = now if password is not None else None
        account.updated_at = now
        system_session.add(account)
        await audit_service.record(
            system_session,
            event_type=(
                AuditEventType.AUTH_PASSWORD_CHANGED
                if password is not None
                else AuditEventType.AUTH_PASSWORD_REMOVED
            ),
            actor_user_id=user_id,
            detail={"via": via},
        )
        if via != "self_service":
            await sign_in_locks.lift(system_session, user_id)
        await user_tokens.revoke_user_sessions(system_session, user=account)
        if response is not None:
            if password is None and prior is not None:
                amr, providers, provider_auth = (
                    prior.amr,
                    prior.satisfied_providers,
                    prior.provider_auth,
                )
            else:
                amr = ["pwd"] if password is not None and password_proved else []
                providers, provider_auth = [], None
            # Minted at the ``token_version`` the revocation just bumped.
            issued = await issue_session(
                request,
                system_session,
                user_id=user_id,
                token_version=account.token_version,
                amr=amr,
                satisfied_providers=providers,
                provider_auth=provider_auth,
                install=(
                    prior.install_id
                    if prior is not None
                    else (install_id(request) or uuid.uuid4())
                    if is_device(request)
                    else None
                ),
            )
            if prior is not None:
                await session_service.follow_devices(
                    system_session, from_id=prior.id, to_id=issued.session.id
                )
    if response is not None and issued is not None:
        issued.set_cookies(response)

    await content_sockets.revoke_user_everywhere(user_id)
    if password is None:
        await email_service.announce_password_removed(system_session, account)
    else:
        await email_service.announce_password_changed(system_session, account)


async def upgrade_session(
    request: Request,
    response: Response,
    system_session: AsyncSession,
    *,
    user: User,
    add_amr: Sequence[str],
    prior: AuthSession | None = None,
    add_providers: Sequence[int] = (),
    provider_auth: dict[str, Any] | None = None,
    audit_detail: dict[str, Any] | None = None,
) -> Token:
    """Add what was just proved to the session already signed in.

    A community that asks for something a session never presented refuses it,
    and signing out to sign back in would be a strange way to answer that. So
    the factor — a code, a passkey, a provider — is taken against the live
    session and this is what records it. The wrong answers counted against the
    account start over, as they do at a sign-in.

    The session is upgraded rather than replaced from nothing: its ``amr``, its
    satisfied providers and each provider's account of its own authentication
    carry forward, and the old chain is retired. Satisfying one community's
    requirement never un-satisfies another's. ``add_providers`` joins the
    satisfied set, and ``provider_auth``, where given, is the providers'
    account the upgraded session keeps in place of ``prior``'s. A provider
    step-up is a sign-in at that provider too, and records one from
    ``audit_detail``.

    ``prior`` is the session upgraded. Unless the caller found it, it is the
    one this request is *on*, named by its own access token: every client
    carries that, and only a browser also carries a refresh cookie. A
    credential that is not a session is refused — this upgrades one, and there
    is nothing else here to add to.
    """
    user_id, token_version = user.id, user.token_version
    if prior is None:
        prior = await live_session_of(
            system_session, session_id=require_session_row(request), user_id=user_id
        )
    if prior is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AuthMessages.SESSION_REQUIRED,
        )

    async with session_store(system_session, user_id=user_id):
        if audit_detail is not None:
            await audit_service.record(
                system_session,
                event_type=AuditEventType.AUTH_SIGNED_IN,
                actor_user_id=user_id,
                detail=audit_detail,
            )
        await sign_in_locks.record_success(system_session, user_id)
        issued = await issue_session(
            request,
            system_session,
            user_id=user_id,
            token_version=token_version,
            amr=sorted(set(prior.amr) | set(add_amr)),
            satisfied_providers=[*prior.satisfied_providers, *add_providers],
            provider_auth=(
                provider_auth if provider_auth is not None else prior.provider_auth
            ),
            install=prior.install_id,
            replaces=prior.id,
        )
    issued.set_cookies(response)
    # The app keeps its own refresh token; a browser reads one from the cookie
    # set above and is handed nothing here.
    return issued.to_token(
        include_refresh=request.cookies.get(REFRESH_COOKIE_NAME) is None
    )
