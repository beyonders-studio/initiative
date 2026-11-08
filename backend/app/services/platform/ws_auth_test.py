"""Tests for the shared WebSocket auth helper (``authenticate_ws_token``).

The realtime WebSocket authenticators must honour ``token_version`` so that
logout / password reset / password change (which revoke purely by bumping the
counter) also close realtime sockets.
"""

from datetime import UTC, datetime, timedelta

import jwt as pyjwt
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import auth_context
from app.core.config import settings
from app.core.security import JWT_ALGORITHM
from app.models.platform.user import UserStatus
from app.services.platform.ws_auth import authenticate_ws_token
from app.testing import create_user, get_auth_token


async def test_valid_token_authenticates(session: AsyncSession):
    user = await create_user(session)
    token = get_auth_token(user)

    result = await authenticate_ws_token(token, session)

    assert result is not None
    assert result.id == user.id


async def test_the_pre_session_token_no_longer_opens_a_socket(
    session: AsyncSession,
):
    """A socket answers the same as the HTTP path, which is what this helper
    exists to keep true — and both now know one shape of session credential."""
    user = await create_user(session)
    legacy = pyjwt.encode(
        {
            "sub": str(user.id),
            "ver": user.token_version,
            "exp": datetime.now(UTC) + timedelta(minutes=10),
        },
        settings.jwt_signing_key,
        algorithm=JWT_ALGORITHM,
    )

    assert await authenticate_ws_token(legacy, session) is None


async def test_token_version_bump_revokes_token(session: AsyncSession):
    """A token minted at the old version must be rejected after the user's
    ``token_version`` is bumped (the logout / reset revocation mechanism)."""
    user = await create_user(session)
    token = get_auth_token(user)

    # Sanity: the freshly minted token works.
    assert await authenticate_ws_token(token, session) is not None

    # Logout / password reset / password change bumps the counter.
    user.token_version += 1
    session.add(user)
    await session.commit()
    await session.refresh(user)

    assert await authenticate_ws_token(token, session) is None


async def test_token_with_stale_version_claim_rejected(session: AsyncSession):
    """A token carrying an out-of-date ``ver`` (here 0 vs the user's 5) must
    never authenticate, even if the signature is otherwise valid."""
    user = await create_user(session)
    user.token_version = 5
    session.add(user)
    await session.commit()
    await session.refresh(user)

    stale_token = get_auth_token(user, token_version=0)

    assert await authenticate_ws_token(stale_token, session) is None


async def test_inactive_user_rejected(session: AsyncSession):
    user = await create_user(session, status=UserStatus.deactivated)
    token = get_auth_token(user)

    assert await authenticate_ws_token(token, session) is None


async def test_garbage_token_rejected(session: AsyncSession):
    assert await authenticate_ws_token("not-a-jwt", session) is None


async def test_token_without_version_claim_rejected(session: AsyncSession):
    """A valid-signature JWT with NO ``ver`` claim at all (e.g. a legacy token
    minted before versioning existed) exercises the ``ver is not None`` guard
    and must be rejected."""
    from datetime import datetime, timedelta

    import jwt as pyjwt

    from app.core.config import settings

    user = await create_user(session)
    legacy_token = pyjwt.encode(
        {
            "sub": str(user.id),
            "exp": datetime.now(UTC) + timedelta(minutes=10),
        },
        settings.jwt_signing_key,
        algorithm=JWT_ALGORITHM,
    )

    assert await authenticate_ws_token(legacy_token, session) is None


async def test_jwt_without_sub_rejected(session: AsyncSession):
    """A valid-signature JWT carrying no ``sub`` names nobody."""
    from datetime import datetime, timedelta

    import jwt as pyjwt

    from app.core.config import settings

    subless_token = pyjwt.encode(
        {"exp": datetime.now(UTC) + timedelta(minutes=10)},
        settings.jwt_signing_key,
        algorithm=JWT_ALGORITHM,
    )

    assert await authenticate_ws_token(subless_token, session) is None


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
