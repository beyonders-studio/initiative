"""Signing in with a one-time code sent to an address.

Two routes. :func:`send_sign_in_code` opens a challenge and posts the code;
:func:`verify_sign_in_code` takes the code back and opens the session. Two more
do the same against a session already open — :func:`send_step_up_code` and
:func:`verify_step_up_code` — which is how an account confirms a change to how
it signs in without signing out.

Asking about an address answers the same way whoever holds it — a challenge
is opened either way, and only whether a letter goes out differs. The handle
in that answer is half the proof; the code in the mailbox is the other half,
and neither is a sign-in alone.

Everything runs on the system engine, like the rest of the sign-in routes:
there is nobody to scope a policy to until one of them returns.
"""

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import FactorExemptUser, SystemSessionDep, require_first_party_session
from app.api.v1.platform_endpoints.session_opening import (
    EMAIL_CODE_LEG,
    count_wrong_answer,
    open_session,
    record_sign_in_failure,
    refuse_if_locked,
    require_login_method,
    require_session_row,
    second_factor_outstanding,
    upgrade_session,
)
from app.core import audit_context
from app.core.config import is_device
from app.core.email_i18n import SUPPORTED_EMAIL_LOCALES
from app.core.encryption import normalize_email
from app.core.login_methods import LoginMethod
from app.core.messages import AuthMessages
from app.core.rate_limit import MAIL_SENDS, limiter
from app.db import session as db_session
from app.db.session import get_session
from app.models.platform.user import User, may_sign_in
from app.models.platform.user_email import UserEmail
from app.schemas.platform.email_otp import (
    EmailOtpRegister,
    EmailOtpSend,
    EmailOtpSent,
    EmailOtpVerify,
)
from app.schemas.platform.token import Token
from app.services import captcha as captcha_service
from app.services import email as email_service
from app.services.auth import addresses
from app.services.auth import challenges as challenge_service
from app.services.auth import email_otp as email_otp_service

logger = logging.getLogger(__name__)

router = APIRouter()

SessionDep = Annotated[AsyncSession, Depends(get_session)]
#: Confirming a session is done by the person in it, not a standing credential.
FirstPartyOnly = Depends(require_first_party_session)


def _requested_locale(request: Request) -> str:
    """The language to write to somebody who has no account to have set one.

    The first tag of ``Accept-Language``, narrowed to the languages this
    deployment writes in; English where it names none of them.
    """
    header = request.headers.get("accept-language", "")
    for part in header.split(","):
        tag = part.split(";")[0].strip().lower()[:2]
        if tag in SUPPORTED_EMAIL_LOCALES:
            return tag
    return "en"


async def _registration_open(
    request: Request, session: AsyncSession, *, address: str, invite: str | None
) -> bool:
    """Whether a sign-up at this address would be taken.

    The registration gates, asked here so that a code is only posted where an
    account could follow from it. The captcha among them was answered by the
    route above, and a token is spent by being checked, so it is not asked for
    a second time.

    A refusal is an answer, not an error: the route says the same thing either
    way, and only whether a letter goes out differs.
    """
    from app.api.v1.platform_endpoints.auth import _registration_gate

    try:
        await _registration_gate(
            request,
            session,
            email=address,
            invite=invite,
            captcha_token=None,
            check_captcha=False,
        )
    except HTTPException:
        return False
    return True


async def _post_code_letter(
    *, user_id: int | None, email: str, code: str, minutes: int, locale: str
) -> None:
    """Post a sign-in or sign-up code once the response has gone.

    After the response, on a session of its own, so the answer takes the same
    time whichever address it names. A letter that cannot be posted is logged;
    the person asks again.
    """
    try:
        async with db_session.SystemSessionLocal() as letter_session:
            if user_id is None:
                await email_service.send_sign_up_code_email(
                    letter_session,
                    email=email,
                    code=code,
                    minutes=minutes,
                    locale=locale,
                )
                return
            user = await letter_session.get(User, user_id)
            if user is not None:
                await email_service.send_sign_in_code_email(
                    letter_session, user, email=email, code=code, minutes=minutes
                )
    except Exception:
        logger.exception("Could not post a sign-in code")


@router.post("/email-otp/send", response_model=EmailOtpSent)
async def send_sign_in_code(
    request: Request,
    payload: EmailOtpSend,
    background: BackgroundTasks,
    session: SessionDep,
    system_session: SystemSessionDep,
) -> EmailOtpSent:
    """Post a code to an address, and hand back the handle that names it.

    The captcha is answered before the address is resolved: it says something
    about the request, not about the address. Past it, the one refusal is the
    address's mail allowance, taken whether or not anybody holds the address.
    """
    await require_login_method(session, LoginMethod.email_otp)
    await captcha_service.verify_or_raise(
        payload.captcha_token, remote_ip=audit_context.client_ip()
    )
    if not await email_service.email_configured(system_session):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.EMAIL_OTP_CANNOT_SEND,
        )

    address = normalize_email(payload.email)
    if not await MAIL_SENDS.take(address):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=AuthMessages.RATE_LIMITED,
        )
    user = await addresses.account_holding(system_session, address)
    # An account that cannot sign in is not one to send a code to, and reads
    # from here exactly like an address nobody holds.
    recipient = user if user is not None and may_sign_in(user) else None
    row = (
        await addresses.row_for(system_session, address)
        if recipient is not None
        else None
    )
    # An address nobody holds is a sign-up, where this deployment takes one.
    # Asked with the captcha already spent, because it was answered above.
    signing_up = user is None and await _registration_open(
        request, system_session, address=address, invite=payload.invite_code
    )

    issued = await email_otp_service.issue(
        system_session,
        user_id=recipient.id if recipient is not None else None,
        user_email_id=row.id if row is not None else None,
        native=is_device(request),
        email=address if signing_up else None,
    )
    await system_session.commit()
    if recipient is not None or signing_up:
        background.add_task(
            _post_code_letter,
            user_id=recipient.id if recipient is not None else None,
            email=address,
            code=issued.code,
            minutes=int(email_otp_service.CODE_TTL.total_seconds() // 60),
            locale=_requested_locale(request),
        )
    return EmailOtpSent(challenge=issued.handle)


@router.post("/email-otp/verify", response_model=Token)
async def verify_sign_in_code(
    request: Request,
    response: Response,
    payload: EmailOtpVerify,
    session: SessionDep,
    system_session: SystemSessionDep,
) -> Token | Response:
    """Take the code back and open the session it earned."""
    await require_login_method(session, LoginMethod.email_otp)
    claimed = await email_otp_service.claim(
        system_session, handle=payload.challenge, code=payload.code
    )
    owner_id = claimed.challenge.user_id if claimed.challenge is not None else None
    if owner_id is not None:
        try:
            await refuse_if_locked(system_session, owner_id)
        except HTTPException:
            # The attempt the claim took stands.
            await system_session.commit()
            raise
    challenge = claimed.challenge
    if challenge is None or not claimed.answered:
        # The attempt is counted whether or not the code was any good, so the
        # commit comes before the refusal.
        if owner_id is not None:
            await count_wrong_answer(system_session, owner_id)
        await system_session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.EMAIL_OTP_INVALID,
        )

    if challenge.user_id is None:
        pending = challenge_service.address_of(challenge)
        if pending is None:
            # A code was asked for at an address nobody holds and no sign-up
            # followed from. There is nothing for it to open.
            await system_session.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=AuthMessages.EMAIL_OTP_INVALID,
            )
        if not await challenge_service.consume(system_session, challenge):
            await system_session.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=AuthMessages.EMAIL_OTP_INVALID,
            )
        ticket = await email_otp_service.issue_ticket(
            system_session,
            email=pending,
            native=email_otp_service.is_native(challenge),
        )
        await system_session.commit()
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"registration_ticket": ticket},
        )

    user_id = challenge.user_id
    user = await system_session.get(User, user_id)
    if user is None or not may_sign_in(user):
        await record_sign_in_failure(
            system_session, user, method="email_otp", reason="inactive"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER
        )

    if not await challenge_service.consume(system_session, challenge):
        # Spent between the claim and here, so the session it bought is not
        # this request's to open a second time.
        await system_session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.EMAIL_OTP_INVALID,
        )

    # Arriving at the address is what proves it, so an address the account had
    # never proved is proved now — and what the account held before that goes.
    if challenge.user_email_id is not None:
        await addresses.prove_at_sign_in(
            system_session, user=user, address_id=challenge.user_email_id
        )
        row = await system_session.get(UserEmail, challenge.user_email_id)
        if row is not None:
            row.last_login_at = datetime.now(UTC)
            system_session.add(row)

    native = email_otp_service.is_native(challenge)
    # The code proved the address; an account holding a second factor still
    # presents it, the same way a password sign-in does.
    token_version = user.token_version
    challenge_response = await second_factor_outstanding(
        session, system_session, user_id=user_id, leg=EMAIL_CODE_LEG, native=native
    )
    if challenge_response is not None:
        return challenge_response

    return await open_session(
        request,
        response,
        system_session,
        user_id=user_id,
        token_version=token_version,
        amr=EMAIL_CODE_LEG.amr,
        audit_detail={"method": EMAIL_CODE_LEG.method},
    )


@router.post(
    "/email-otp/register",
    response_model=Token,
    status_code=status.HTTP_201_CREATED,
)
async def register_with_code(
    request: Request,
    response: Response,
    payload: EmailOtpRegister,
    session: SessionDep,
    system_session: SystemSessionDep,
) -> Token:
    """Make the account a proved address earned, and sign it in.

    The gates are asked again here — the ticket says which address, and
    nothing else about the registration was settled when it was issued. The
    captcha is not among them: it was answered when the code was asked for,
    and a token is spent by being checked.

    The account is made with no password. Its way in is the address it just
    proved; it sets a password afterwards if it wants one.
    """
    from app.api.v1.platform_endpoints.auth import (
        RegistrationDetails,
        _register_account,
    )

    await require_login_method(session, LoginMethod.email_otp)
    ticket = await email_otp_service.claim_ticket(
        system_session, ticket=payload.registration_ticket
    )
    address = challenge_service.address_of(ticket) if ticket is not None else None
    if ticket is None or address is None:
        await system_session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.EMAIL_OTP_INVALID,
        )
    if not await challenge_service.consume(system_session, ticket):
        await system_session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.EMAIL_OTP_INVALID,
        )

    registered = await _register_account(
        request,
        system_session,
        details=RegistrationDetails(
            email=address,
            username=payload.username,
            timezone=payload.timezone,
            community=payload.community,
            birthdate=payload.birthdate,
            username_offer=payload.username_offer,
            accepted_documents=tuple(payload.accepted_documents),
        ),
        invite_code=payload.invite_code,
        hashed_password=None,
        check_captcha=False,
        address_proved=True,
    )
    return await open_session(
        request,
        response,
        system_session,
        user_id=registered.user.id,
        token_version=registered.user.token_version,
        amr=EMAIL_CODE_LEG.amr,
        audit_detail={"method": EMAIL_CODE_LEG.method, "during": "registration"},
    )


@router.post("/step-up/email-otp/send", response_model=EmailOtpSent)
@limiter.limit("5/15minutes")
async def send_step_up_code(
    request: Request,
    background: BackgroundTasks,
    session: SessionDep,
    current_user: FactorExemptUser,
    system_session: SystemSessionDep,
    _first_party: str = FirstPartyOnly,
) -> EmailOtpSent:
    """Post a code confirming the session already open.

    To the account's primary proved address, or its first proved one: an
    address that was added and never proved is not known to be the account's.
    """
    await require_login_method(session, LoginMethod.email_otp)
    # What the answer would be added to, asked for before a letter goes out.
    require_session_row(request)
    if not await email_service.email_configured(system_session):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.EMAIL_OTP_CANNOT_SEND,
        )
    proved = await addresses.proved_only(system_session, user_id=current_user.id)
    if not proved:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.EMAIL_OTP_NO_PROVED_ADDRESS,
        )

    issued = await email_otp_service.issue_step_up(
        system_session, user_id=current_user.id
    )
    await system_session.commit()
    background.add_task(
        _post_code_letter,
        user_id=current_user.id,
        email=proved[0],
        code=issued.code,
        minutes=int(email_otp_service.CODE_TTL.total_seconds() // 60),
        locale=_requested_locale(request),
    )
    return EmailOtpSent(challenge=issued.handle)


@router.post("/step-up/email-otp/verify", response_model=Token)
@limiter.limit("10/15minutes")
async def verify_step_up_code(
    request: Request,
    response: Response,
    payload: EmailOtpVerify,
    session: SessionDep,
    current_user: FactorExemptUser,
    system_session: SystemSessionDep,
    _first_party: str = FirstPartyOnly,
) -> Token:
    """Take the code back and confirm the session with it.

    The session is upgraded as the other step-ups upgrade it, which opens a
    new chain: a change asking for a recent sign-in takes it from here.
    """
    await require_login_method(session, LoginMethod.email_otp)
    await refuse_if_locked(system_session, current_user.id)
    claimed = await email_otp_service.claim(
        system_session,
        handle=payload.challenge,
        code=payload.code,
        purposes=email_otp_service.STEP_UP_PURPOSES,
    )
    challenge = claimed.challenge
    if (
        challenge is None
        or challenge.user_id != current_user.id
        or not claimed.answered
        or not await challenge_service.consume(system_session, challenge)
    ):
        # Counted whether or not the handle was any good, so the commit comes
        # before the refusal.
        await count_wrong_answer(system_session, current_user.id)
        await system_session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.EMAIL_OTP_INVALID,
        )

    return await upgrade_session(
        request,
        response,
        system_session,
        user=current_user,
        add_amr=EMAIL_CODE_LEG.amr,
    )
