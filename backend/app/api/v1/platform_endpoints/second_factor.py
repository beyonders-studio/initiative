"""Enrolling, proving and removing the account's own second factor.

Mounted under ``/auth`` beside the sign-in it changes. The sign-in itself — the
challenge and the code answered against it — stays in ``auth.py``, with the
password leg it continues.

Every route here runs on the system engine: ``user_totp`` and its companions
are app_admin-only, because a factor is presented while signing in, before
there is anybody to scope a policy to.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import (
    NotDemoSample,
    FactorExemptUser,
    require_first_party_session,
    SystemSessionDep,
    CurrentUser,
)
from app.core.audit_events import AuditEventType
from app.core.login_methods import LoginMethod
from app.core.messages import AuthMessages
from app.core.rate_limit import limiter
from app.core.security import has_usable_password
from app.api.v1.platform_endpoints.password_recheck import (
    require_password_or_recent_proof,
)
from app.api.v1.platform_endpoints.change_assessment import is_risky
from app.api.v1.platform_endpoints.held_changes import (
    HELD_OUTCOME,
    held_response,
    hold_change,
)
from app.api.v1.platform_endpoints.session_opening import (
    prove_second_factor,
    upgrade_session,
)

from app.schemas.platform.token import Token
from app.schemas.platform.user import HeldChangeOutcome
from app.schemas.platform.second_factor import (
    SecondFactorStepUpAnswer,
    RecoveryCodes,
    RecoveryCodesRegenerate,
    SecondFactorConfirm,
    SecondFactorDisable,
    SecondFactorEnrolment,
    SecondFactorEnrolStart,
    SecondFactorStatus,
)
from app.services import audit as audit_service
from app.services import email as email_service
from app.services.auth import addresses
from app.models.platform.account_change_hold import HeldChangeKind
from app.services.auth import held_changes
from app.services.auth import totp as totp_service
from app.services.platform import auth_posture

router = APIRouter()


#: Setting a factor up and presenting one have to answer while the
#: deployment's own rule is unmet — they are how an account meets it. Removing
#: one, and replacing the recovery set, are ordinary and take ``CurrentUser``.
#: Enrolling and removing a factor change how the account is signed into, so
#: they are done by the person in a session of their own rather than through a
#: standing credential.
FirstPartyOnly = Depends(require_first_party_session)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


@router.get("/totp", response_model=SecondFactorStatus)
async def read_second_factor(
    current_user: FactorExemptUser,
    system_session: SystemSessionDep,
) -> SecondFactorStatus:
    """What the account holds. A started-but-unproved enrolment reads as not
    enrolled, because that is what the sign-in makes of it too."""
    offered = await auth_posture.login_method_allowed(system_session, LoginMethod.totp)
    password_required = await auth_posture.password_confirms(
        system_session, current_user
    )
    factor = await totp_service.get_factor(system_session, user_id=current_user.id)
    enrolled = factor is not None and factor.confirmed_at is not None
    # An account that signs in without a password keeps a recovery set whether
    # or not it is enrolled: the codes answer for the account there rather than
    # for a factor, and setting a password again is what they are for.
    passwordless = not has_usable_password(current_user.hashed_password)
    remaining = (
        await totp_service.remaining_recovery_codes(
            system_session, user_id=current_user.id
        )
        if enrolled or passwordless
        else 0
    )
    if factor is None or factor.confirmed_at is None:
        return SecondFactorStatus(
            password_required=password_required,
            offered=offered,
            passwordless=passwordless,
            recovery_codes_remaining=remaining,
        )
    return SecondFactorStatus(
        enrolled=True,
        password_required=password_required,
        offered=offered,
        passwordless=passwordless,
        confirmed_at=_iso(factor.confirmed_at),
        last_used_at=_iso(factor.last_used_at),
        recovery_codes_remaining=remaining,
    )


@router.post(
    "/totp/enroll", response_model=SecondFactorEnrolment, dependencies=[NotDemoSample]
)
@limiter.limit("10/hour")
async def begin_second_factor(
    request: Request,
    current_user: FactorExemptUser,
    system_session: SystemSessionDep,
    payload: SecondFactorEnrolStart,
    _first_party: str = FirstPartyOnly,
) -> SecondFactorEnrolment:
    """Mint a seed and hand it over, once.

    Nothing is asked for at sign-in until it is confirmed, so an enrolment
    begun and abandoned costs the account nothing. Beginning again replaces it.
    """
    if not await auth_posture.login_method_allowed(system_session, LoginMethod.totp):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AuthMessages.TOTP_NOT_PERMITTED,
        )
    if await totp_service.is_enrolled(system_session, user_id=current_user.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AuthMessages.TOTP_ALREADY_ENROLLED,
        )
    await require_password_or_recent_proof(
        request, system_session, current_user, payload.current_password
    )

    # What the authenticator app shows under the issuer. The address the
    # person signs in with where there is one, so an account with two entries
    # is told apart; the handle otherwise.
    account = (
        await addresses.primary_address(system_session, user_id=current_user.id)
        or current_user.username
    )
    enrolment = await totp_service.begin_enrolment(
        system_session,
        user_id=current_user.id,
        account=account,
        issuer=totp_service.issuer_name(),
    )
    await system_session.commit()
    return SecondFactorEnrolment(secret=enrolment.secret, otpauth_uri=enrolment.uri)


@router.post(
    "/totp/confirm", response_model=RecoveryCodes, dependencies=[NotDemoSample]
)
@limiter.limit("10/15minutes")
async def confirm_second_factor(
    request: Request,
    current_user: FactorExemptUser,
    system_session: SystemSessionDep,
    payload: SecondFactorConfirm,
    _first_party: str = FirstPartyOnly,
) -> RecoveryCodes:
    """Prove the enrolment with a code it produced, and hand back the recovery
    set — the one time those exist in the clear.

    Sessions are left alone: the person is where they are and has just proved
    it.
    """
    factor = await totp_service.get_factor(system_session, user_id=current_user.id)
    if factor is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.TOTP_NOT_ENROLLED,
        )
    if factor.confirmed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AuthMessages.TOTP_ALREADY_ENROLLED,
        )
    if not await totp_service.confirm_enrolment(
        system_session, user_id=current_user.id, code=payload.code
    ):
        await audit_service.record(
            system_session,
            event_type=AuditEventType.AUTH_SECOND_FACTOR_FAILED,
            actor_user_id=current_user.id,
            detail={"method": "totp", "during": "enrolment"},
        )
        await system_session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.TOTP_INVALID
        )

    codes = await totp_service.issue_recovery_codes(
        system_session, user_id=current_user.id
    )
    await audit_service.record(
        system_session,
        event_type=AuditEventType.AUTH_SECOND_FACTOR_ENROLLED,
        actor_user_id=current_user.id,
        detail={"method": "totp"},
    )
    await system_session.commit()
    await email_service.announce_second_factor_change(
        system_session, current_user, enabled=True
    )
    return RecoveryCodes(codes=codes)


@router.post(
    "/totp/disable",
    response_model=HeldChangeOutcome,
    responses=HELD_OUTCOME,
    dependencies=[NotDemoSample],
)
@limiter.limit("10/15minutes")
async def disable_second_factor(
    request: Request,
    current_user: CurrentUser,
    system_session: SystemSessionDep,
    payload: SecondFactorDisable,
    _first_party: str = FirstPartyOnly,
) -> HeldChangeOutcome | JSONResponse:
    """Remove the factor, its seed and its recovery codes.

    Asks for the password — or, where the password is not asked for, a
    recent sign-in — and for the factor itself: a live code, or one of the
    recovery codes. Every other session goes with it; this one stays. Asked
    for from somewhere the account does not yet know, it waits two days
    (``202``).
    """
    if not await totp_service.is_enrolled(system_session, user_id=current_user.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.TOTP_NOT_ENROLLED,
        )
    await require_password_or_recent_proof(
        request, system_session, current_user, payload.current_password
    )
    await prove_second_factor(
        system_session,
        user_id=current_user.id,
        code=payload.code,
        recovery_code=payload.recovery_code,
        during="removal",
        signed_in=True,
    )

    if await is_risky(request, system_session, current_user):
        held = await hold_change(
            request,
            system_session,
            current_user,
            kind=HeldChangeKind.second_factor_off,
        )
        return held_response(HeldChangeOutcome(held=held))
    # Every other session, and not this one: the change was made from a page
    # that should still be signed in when it finishes.
    await held_changes.turn_off_second_factor(
        system_session,
        current_user,
        kept_session_id=getattr(request.state, "session_id", None),
    )
    return HeldChangeOutcome()


@router.post("/step-up/totp", response_model=Token)
@limiter.limit("10/15minutes")
async def step_up_with_factor(
    request: Request,
    response: Response,
    current_user: FactorExemptUser,
    system_session: SystemSessionDep,
    payload: SecondFactorStepUpAnswer,
    _first_party: str = FirstPartyOnly,
) -> Token:
    """Add the account's second factor to the session already signed in.

    A community that asks for one refuses a session that never presented it,
    and signing out to sign back in would be a strange way to answer that. This
    takes the code against the live session instead.

    The session is upgraded rather than replaced from nothing: its factors and
    its satisfied providers carry forward and the old row is revoked, the same
    shape the provider step-up uses — satisfying one community's requirement
    never un-satisfies another's.
    """
    if not await totp_service.is_enrolled(system_session, user_id=current_user.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.TOTP_NOT_ENROLLED,
        )
    proof = await prove_second_factor(
        system_session,
        user_id=current_user.id,
        code=payload.code,
        recovery_code=payload.recovery_code,
        during="step_up",
        signed_in=True,
    )
    return await upgrade_session(
        request,
        response,
        system_session,
        user=current_user,
        add_amr=proof.amr,
    )


@router.post(
    "/recovery-codes/regenerate",
    response_model=RecoveryCodes,
    dependencies=[NotDemoSample],
)
@limiter.limit("5/hour")
async def regenerate_recovery_codes(
    request: Request,
    current_user: CurrentUser,
    system_session: SystemSessionDep,
    payload: RecoveryCodesRegenerate,
    _first_party: str = FirstPartyOnly,
) -> RecoveryCodes:
    """Retire the account's codes and hand over a fresh set, once.

    For an account that is enrolled, and for one that signs in without a
    password — there the codes answer for the account itself, and are how it
    sets a password again.
    """
    passwordless = not has_usable_password(current_user.hashed_password)
    if not passwordless and not await totp_service.is_enrolled(
        system_session, user_id=current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.TOTP_NOT_ENROLLED,
        )
    await require_password_or_recent_proof(
        request, system_session, current_user, payload.current_password
    )

    codes = await totp_service.issue_recovery_codes(
        system_session, user_id=current_user.id
    )
    await audit_service.record(
        system_session,
        event_type=AuditEventType.AUTH_RECOVERY_CODES_ISSUED,
        actor_user_id=current_user.id,
    )
    await system_session.commit()
    # Somebody holding a new set holds the account: its holder is told, with
    # the way to say it wasn't them.
    await email_service.announce_recovery_codes_issued(system_session, current_user)
    return RecoveryCodes(codes=codes)
