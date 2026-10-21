"""An account that signs in without a password.

Mounted under ``/auth`` beside the passkeys that make it possible. Two routes:
giving the password up, for an account that holds another way in, and getting
one back with a recovery code, for an account that holds none.

Every route runs on the system engine for the same reason the second-factor
routes do: the tables they read are app_admin-only.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    NotDemoSample,
    require_first_party_session,
    SystemSessionDep,
    CurrentUser,
)
from app.api.v1.platform_endpoints.password_recheck import (
    require_password_or_recent_proof,
)
from app.api.v1.platform_endpoints.session_opening import (
    prove_second_factor,
    refuse_if_locked,
    require_login_method,
    set_password,
)
from app.core.audit_events import AuditEventType
from app.core.config import is_device
from app.core.login_methods import LoginMethod
from app.core.messages import AuthMessages
from app.core.password_policy import validate_new_password
from app.core.rate_limit import SIGN_IN_FAILURES, limiter
from app.core.security import has_usable_password
from app.db.session import get_session
from app.models.platform.user import UserStatus
from app.schemas.platform.auth import VerificationSendResponse
from app.schemas.platform.passwordless import PasswordRecover, PasswordRemove
from app.schemas.platform.second_factor import RecoveryCodes
from app.services import audit as audit_service
from app.services.auth import addresses
from app.services.auth import identity as identity_service
from app.services.auth import totp as totp_service

router = APIRouter()

SessionDep = Annotated[AsyncSession, Depends(get_session)]
#: Giving up a way in is done by the person in a session of their own rather
#: than through a standing credential.
FirstPartyOnly = Depends(require_first_party_session)


def _recovery_code_invalid() -> HTTPException:
    """The one answer every miss gets: an address nobody holds, an account that
    is not active, an account that holds a password, and a code that did not
    match are all the same refusal."""
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=AuthMessages.RECOVERY_CODE_INVALID,
    )


async def _record_recovery_refusal(
    system_session: AsyncSession, *, user_id: int
) -> None:
    """Write down a refused recovery, against the account it named.

    No actor: the request is unauthenticated, the same shape the sign-in's own
    second-factor leg records. Its own commit, because the request is about to
    refuse.
    """
    await audit_service.record(
        system_session,
        event_type=AuditEventType.AUTH_SECOND_FACTOR_FAILED,
        actor_user_id=None,
        target_user_id=user_id,
        target_type="user",
        target_id=user_id,
        detail={"method": "recovery_code", "during": "recover"},
    )
    await system_session.commit()


@router.post(
    "/password/remove", response_model=RecoveryCodes, dependencies=[NotDemoSample]
)
@limiter.limit("5/15minutes")
async def remove_password(
    request: Request,
    response: Response,
    system_session: SystemSessionDep,
    current_user: CurrentUser,
    payload: PasswordRemove,
    _first_party: str = FirstPartyOnly,
) -> RecoveryCodes:
    """Give up the password, keeping the passkey or the sign-in provider that
    will open sessions from now on.

    Hands back a fresh recovery set where the account is down to fewer than a
    handful of codes — the one time those exist in the clear, and the ones it
    held stop working — and an empty list where it still holds enough.

    Done from a browser. The answer retires every credential the account holds
    and hands this caller a replacement session in cookies, which is not what
    the native app carries, so the app is told to do this on the web instead.
    """
    if is_device(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AuthMessages.SESSION_REQUIRED,
        )
    if not has_usable_password(current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.PASSWORD_NOT_HELD,
        )
    await require_password_or_recent_proof(
        request, system_session, current_user, payload.current_password
    )

    # What the account would be left with. The deployment's posture is half of
    # that answer: a credential it does not accept opens nothing, so an account
    # holding only one keeps its password.
    remaining = await identity_service.ways_in(
        system_session, user_id=current_user.id
    ) - {LoginMethod.password}
    if not remaining:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AuthMessages.PASSWORD_IS_LAST_METHOD,
        )

    # A recovery set exists from the moment the account becomes passwordless,
    # because a code is now how it gets a password back — on a deployment with
    # no mail configured, which is the self-hosted case, it is the only way.
    # An account that already holds a set keeps it; they are still good. One
    # down to its last few is given a fresh set instead, at the same count the
    # settings page has been calling low.
    codes: list[str] = []
    held = await totp_service.remaining_recovery_codes(
        system_session, user_id=current_user.id
    )
    if held < totp_service.LOW_ON_RECOVERY_CODES:
        codes = await totp_service.issue_recovery_codes(
            system_session, user_id=current_user.id
        )
        await audit_service.record(
            system_session,
            event_type=AuditEventType.AUTH_RECOVERY_CODES_ISSUED,
            actor_user_id=current_user.id,
        )

    # The codes are staged beside the password's removal and land on its
    # commit, with the session that keeps this device signed in.
    await set_password(
        request,
        system_session,
        user=current_user,
        password=None,
        via="self_service",
        response=response,
    )
    return RecoveryCodes(codes=codes)


@router.post("/password/recover", response_model=VerificationSendResponse)
async def recover_with_code(
    request: Request,
    session: SessionDep,
    system_session: SystemSessionDep,
    payload: PasswordRecover,
) -> VerificationSendResponse:
    """Set a password with a recovery code, for an account that holds none.

    The way back in when the passkey is gone and no mail can be sent. An
    account that holds a password recovers it through the mailed reset instead.

    No session is opened here. The password is what the account signs in with
    afterwards, and the authenticator is still asked for where one is enrolled.
    """
    await require_login_method(session, LoginMethod.password)
    # The policy runs before anything is spent: a candidate this deployment
    # would not take must not cost the account one of its codes.
    await validate_new_password(payload.password)

    # Counted by the address typed in as well as by the account, the same way
    # a password is, so an address nobody holds runs out like one somebody does.
    if not await SIGN_IN_FAILURES.left(payload.email):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=AuthMessages.SIGN_IN_LOCKED,
        )
    user = await addresses.find_user_by_address(system_session, payload.email)
    if user is None:
        await SIGN_IN_FAILURES.take(payload.email)
        raise _recovery_code_invalid()
    await refuse_if_locked(system_session, user.id)
    if user.status != UserStatus.active or has_usable_password(user.hashed_password):
        await SIGN_IN_FAILURES.take(payload.email)
        await _record_recovery_refusal(system_session, user_id=user.id)
        raise _recovery_code_invalid()
    try:
        await prove_second_factor(
            system_session,
            user_id=user.id,
            code=None,
            recovery_code=payload.recovery_code,
            during="recover",
            signed_in=False,
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_400_BAD_REQUEST:
            await SIGN_IN_FAILURES.take(payload.email)
        raise

    # The spent code and its record land on the commit that sets the password.
    await set_password(
        request,
        system_session,
        user=user,
        password=payload.password,
        via="recovery_code",
    )
    return VerificationSendResponse(status="reset")
