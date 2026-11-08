"""Re-checking the account's password before it changes how it is signed into.

Shared by the routes that add or take away a way in — the second factor, the
passkeys, the password itself — and by the two that end something for good, so
all of them ask the same question in the same words.

An account that holds no password has nothing to re-check, so what stands in
for it is the sign-in itself: :func:`require_password_or_recent_proof` asks
such an account to be on a session opened within the last few minutes. The
same goes for a password on a deployment that signs nobody in with one: it is
not a way in there, so it is not asked for
(``auth_posture.password_confirms``). A step-up — a passkey, a code sent to a
proved address — opens that session without signing out.

A wrong password here counts against the account as one at sign-in does, the
right one starts the count over, and an account whose password is turned off
is refused here too.
"""

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.platform_endpoints.session_opening import (
    chain_started_at,
    count_wrong_answer,
    refuse_if_locked,
    require_session_row,
)
from app.core.messages import AuthMessages, UserMessages
from app.core.security import verify_password
from app.models.platform.auth_session import AuthSession
from app.models.platform.user import User
from app.services.auth import sign_in_locks
from app.services.platform import auth_posture

#: How long after a sign-in that sign-in still answers for the account. Short
#: enough that the person is still the one at the keyboard, long enough to read
#: a confirmation form and type a phrase into it.
RECENT_PROOF_MINUTES = 10


async def require_password(
    system_session: AsyncSession,
    user: User,
    supplied: str | None,
    *,
    detail: str | None = None,
) -> None:
    """Re-check the password, as a password change does.

    The exemption is for an account that holds no password to re-check — one
    provisioned through an identity provider, one that signs in with a passkey.
    Holding a federated identity is not the same question: an account can have
    both, and one that has a password is asked for it. Nor is "the column is
    NULL": a hash no scheme verifies is not a password either, and asking for
    one nobody can supply would shut the account out of its own settings.

    ``detail`` is the one code to answer with, for a form that reads a missing
    password and a wrong one as the same refusal. Left unset, the two are told
    apart — which is what a field asking for the current password wants.

    Where ``auth_posture.password_confirms`` says the password is not asked
    for, this asks nothing: the caller that needs a proof all the same takes
    :func:`require_password_or_recent_proof` instead.

    Commits ``system_session`` when it counts a wrong password. The right one
    starts the count over, as a sign-in does, staged for the caller to commit.
    """
    if not await auth_posture.password_confirms(system_session, user):
        return
    await refuse_if_locked(system_session, user.id)
    if not supplied:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail or UserMessages.CURRENT_PASSWORD_REQUIRED,
        )
    if not verify_password(supplied, user.hashed_password):
        await count_wrong_answer(system_session, user.id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail or UserMessages.CURRENT_PASSWORD_INCORRECT,
        )
    await sign_in_locks.record_success(system_session, user.id)


def _recent_proof_required() -> HTTPException:
    # The account holds no password to re-check, and the session is not fresh
    # enough to stand in for one.
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=AuthMessages.RECENT_PROOF_REQUIRED,
    )


async def require_password_or_recent_proof(
    request: Request,
    system_session: AsyncSession,
    user: User,
    supplied: str | None,
    *,
    detail: str | None = None,
) -> bool:
    """Ask for the password, or for a sign-in recent enough to speak for it.

    An account whose password ``auth_posture.password_confirms`` answers the
    question :func:`require_password` asks, in the same words and with the
    same ``detail``. Any other answers a different question: it has to be
    on a server-side session of its own that records how it signed in — a
    standing credential is not somebody signing in — and that session's chain
    has to have begun within :data:`RECENT_PROOF_MINUTES`.

    The chain, not the row: a refresh mints a new row every so often and the
    sign-in is at the root of them, so the age read is the sign-in's. A step-up
    and a replacement each open a chain of their own, which is what lets a
    person prove themselves again and carry on.

    Answers whether it was the password that was checked.
    """
    if await auth_posture.password_confirms(system_session, user):
        await require_password(system_session, user, supplied, detail=detail)
        return True

    session_id = require_session_row(request)
    row = await system_session.get(AuthSession, session_id)
    if (
        row is None
        or row.user_id != user.id
        or row.revoked_at is not None
        or not row.amr
    ):
        raise _recent_proof_required()
    started = await chain_started_at(system_session, session_id=session_id)
    if started is None or datetime.now(UTC) - started > timedelta(
        minutes=RECENT_PROOF_MINUTES
    ):
        raise _recent_proof_required()
    return False
