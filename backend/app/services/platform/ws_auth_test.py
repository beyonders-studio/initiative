"""Tests for the shared WebSocket auth helper (``authenticate_ws_token``).

The realtime WebSocket authenticators must honour ``token_version`` so that
logout / password reset / password change (which revoke purely by bumping the
counter) also close realtime sockets.
"""

from datetime import UTC, datetime, timedelta

import jwt as pyjwt
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import auth_context
from app.core.config import settings
from app.core.security import JWT_ALGORITHM
from app.models.platform.user import UserStatus
from app.services.platform.ws_auth import authenticate_ws_token
from app.testing import create_user, get_auth_token


@pytest.mark.parametrize(
    "claims",
    [
        # The pre-session shape: a socket answers the same as the HTTP path,
        # which is what this helper exists to keep true.
        {"sub": True, "ver": True},
        # No ``ver`` claim at all, as minted before versioning existed.
        {"sub": True},
        # No ``sub``: it names nobody.
        {},
    ],
    ids=["pre-session", "no-version", "no-subject"],
)
async def test_a_signed_token_missing_a_claim_opens_no_socket(
    session: AsyncSession, claims: dict[str, bool]
):
    user = await create_user(session)
    payload: dict = {"exp": datetime.now(UTC) + timedelta(minutes=10)}
    if "sub" in claims:
        payload["sub"] = str(user.id)
    if "ver" in claims:
        payload["ver"] = user.token_version
    token = pyjwt.encode(payload, settings.jwt_signing_key, algorithm=JWT_ALGORITHM)

    assert await authenticate_ws_token(token, session) is None


async def test_inactive_user_rejected(session: AsyncSession):
    user = await create_user(session, status=UserStatus.deactivated)
    token = get_auth_token(user)

    assert await authenticate_ws_token(token, session) is None


async def test_a_socket_records_what_the_session_proved(session: AsyncSession):
    """The guild gate the socket goes through next reads the account's second
    factor and its passkey off the auth context, as the HTTP path does — so a
    community that asks for either answers a socket the way it answers a page.
    """
    user = await create_user(session)

    with_a_key = await authenticate_ws_token(
        get_auth_token(user, amr=["pwd", "hwk", "mfa"]), session
    )
    assert with_a_key is not None
    assert auth_context.current().session_amr == frozenset({"mfa", "hwk"})

    with_a_password = await authenticate_ws_token(
        get_auth_token(user, amr=["pwd"]), session
    )
    assert with_a_password is not None
    assert auth_context.current().session_amr == frozenset()
