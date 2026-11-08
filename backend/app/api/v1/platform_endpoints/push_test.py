"""Integration tests for /api/v1/push token registration.

These run through the real-role ``client`` (bare ``app_user`` login +
``SET ROLE platform_<tier>``), guarding the 0.54.0 regression where the
endpoints ran as the de-granted bare login role and failed with
``permission denied for table push_tokens``.
"""

from __future__ import annotations

from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.platform import push_tokens as push_tokens_service
from app.testing import signed_in_headers
from app.testing.factories import create_user, get_auth_headers


async def test_register_and_unregister_push_token(
    client: AsyncClient, session: AsyncSession
):
    """The device is recorded against the session that registered it."""
    user = await create_user(session)
    headers = await signed_in_headers(session, user)

    register = await client.post(
        "/api/v1/push/register",
        headers=headers,
        json={"push_token": "test-push-token-abc", "platform": "android"},
    )
    assert register.status_code == 200
    assert register.json() == {"status": "registered"}
    (row,) = await push_tokens_service.get_push_tokens_for_user(
        session, user_id=user.id
    )
    await session.refresh(row)
    assert row.session_id is not None

    unregister = await client.request(
        "DELETE",
        "/api/v1/push/unregister",
        headers=headers,
        json={"push_token": "test-push-token-abc"},
    )
    assert unregister.status_code == 200
    assert unregister.json() == {"status": "unregistered"}


async def test_a_key_does_not_register_a_device(
    client: AsyncClient, session: AsyncSession
):
    """A device is registered in the person's own sign-in."""
    user = await create_user(session)
    create = await client.post(
        "/api/v1/me/api-keys",
        headers=get_auth_headers(user),
        json={"name": "Pinned"},
    )
    assert create.status_code == 201, create.text

    response = await client.post(
        "/api/v1/push/register",
        headers={"Authorization": f"Bearer {create.json()['secret']}"},
        json={"push_token": "key-push-token", "platform": "ios"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "SESSION_REQUIRED"
    assert (
        await push_tokens_service.get_push_tokens_for_user(session, user_id=user.id)
        == []
    )


async def test_unregister_cannot_delete_other_users_token(
    client: AsyncClient, session: AsyncSession
):
    owner = await create_user(session)
    attacker = await create_user(session)
    token_value = "owner-push-token-xyz"

    register = await client.post(
        "/api/v1/push/register",
        headers=get_auth_headers(owner),
        json={"push_token": token_value, "platform": "ios"},
    )
    assert register.status_code == 200

    # Unregistering removes only the caller's own tokens.
    await client.request(
        "DELETE",
        "/api/v1/push/unregister",
        headers=get_auth_headers(attacker),
        json={"push_token": token_value},
    )

    remaining = await push_tokens_service.get_push_tokens_for_user(
        session, user_id=owner.id
    )
    assert [t.push_token for t in remaining] == [token_value]


async def test_a_sign_in_holds_one_registration(
    client: AsyncClient, session: AsyncSession
):
    """A new token from the same sign-in replaces the one it held, so one
    account cannot pile up tokens the push relay will answer as dead."""
    user = await create_user(session)
    headers = await signed_in_headers(session, user)

    for token in ("first-push-token-abc", "second-push-token-abc"):
        response = await client.post(
            "/api/v1/push/register",
            headers=headers,
            json={"push_token": token, "platform": "android"},
        )
        assert response.status_code == 200, response.text

    rows = await push_tokens_service.get_push_tokens_for_user(session, user_id=user.id)
    assert [row.push_token for row in rows] == ["second-push-token-abc"]


async def test_each_sign_in_keeps_its_own_registration(
    client: AsyncClient, session: AsyncSession
):
    """Two devices are two sign-ins; one registering leaves the other's."""
    user = await create_user(session)
    phone = await signed_in_headers(session, user)
    tablet = await signed_in_headers(session, user)

    for headers, token in (
        (phone, "phone-push-token-abc"),
        (tablet, "tablet-push-token-abc"),
    ):
        response = await client.post(
            "/api/v1/push/register",
            headers=headers,
            json={"push_token": token, "platform": "android"},
        )
        assert response.status_code == 200, response.text

    rows = await push_tokens_service.get_push_tokens_for_user(session, user_id=user.id)
    assert sorted(row.push_token for row in rows) == [
        "phone-push-token-abc",
        "tablet-push-token-abc",
    ]
