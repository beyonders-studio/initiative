"""
Integration tests for user-scoped API key endpoints.

Tests the API key endpoints at /api/v1/me/api-keys including:
- Listing API keys
- Creating API keys
- Deleting API keys
- Authentication with API keys
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx2 import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.models.platform.api_key import UserApiKey
from app.models.platform.guild import CommunityRole
from app.testing.audit import emitted
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
)


async def test_list_api_keys_empty(client: AsyncClient, session: AsyncSession):
    """Test listing API keys when user has none."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    response = await client.get("/api/v1/me/api-keys", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["keys"] == []


async def test_create_api_key(client: AsyncClient, session: AsyncSession):
    """Test creating a new API key."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    payload = {
        "name": "Test API Key",
        "expires_at": None,
    }

    response = await client.post("/api/v1/me/api-keys", headers=headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    assert "secret" in data
    assert "api_key" in data
    assert data["api_key"]["name"] == "Test API Key"
    assert data["api_key"]["is_active"] is True
    assert data["secret"].startswith("ppk_")
    assert len(data["secret"]) > 20


async def test_create_api_key_with_expiration(
    client: AsyncClient, session: AsyncSession
):
    """A future expiry within the max-TTL window is honored verbatim."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    expires = datetime.now(UTC) + timedelta(days=30)
    payload = {
        "name": "Expiring Key",
        "expires_at": expires.isoformat(),
    }

    response = await client.post("/api/v1/me/api-keys", headers=headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    returned = datetime.fromisoformat(data["api_key"]["expires_at"])
    # Within the 90-day ceiling, so preserved (allow ~1s of round-trip drift).
    assert abs((returned - expires).total_seconds()) < 5


async def test_list_api_keys_after_creation(client: AsyncClient, session: AsyncSession):
    """Test that created API keys appear in list."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    # Create two API keys
    await client.post(
        "/api/v1/me/api-keys",
        headers=headers,
        json={"name": "Key 1"},
    )
    await client.post(
        "/api/v1/me/api-keys",
        headers=headers,
        json={"name": "Key 2"},
    )

    # List keys
    response = await client.get("/api/v1/me/api-keys", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data["keys"]) == 2
    key_names = {key["name"] for key in data["keys"]}
    assert "Key 1" in key_names
    assert "Key 2" in key_names


async def test_delete_api_key(client: AsyncClient, session: AsyncSession):
    """Test deleting an API key."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    # Create a key
    create_response = await client.post(
        "/api/v1/me/api-keys",
        headers=headers,
        json={"name": "To Delete"},
    )
    api_key_id = create_response.json()["api_key"]["id"]

    # Delete it
    delete_response = await client.delete(
        f"/api/v1/me/api-keys/{api_key_id}",
        headers=headers,
    )

    assert delete_response.status_code == 204

    # Verify it's gone
    list_response = await client.get("/api/v1/me/api-keys", headers=headers)
    assert len(list_response.json()["keys"]) == 0


async def test_delete_nonexistent_api_key(client: AsyncClient, session: AsyncSession):
    """Test deleting an API key that doesn't exist."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    response = await client.delete("/api/v1/me/api-keys/99999", headers=headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "USER_API_KEY_NOT_FOUND"


async def test_cannot_delete_other_users_api_key(
    client: AsyncClient, session: AsyncSession
):
    """Test that users cannot delete other users' API keys."""
    user1 = await create_user(session, email="user1@example.com")
    user2 = await create_user(session, email="user2@example.com")

    headers1 = get_auth_headers(user1)
    headers2 = get_auth_headers(user2)

    # User 1 creates a key
    create_response = await client.post(
        "/api/v1/me/api-keys",
        headers=headers1,
        json={"name": "User 1 Key"},
    )
    api_key_id = create_response.json()["api_key"]["id"]

    # User 2 tries to delete User 1's key
    delete_response = await client.delete(
        f"/api/v1/me/api-keys/{api_key_id}",
        headers=headers2,
    )

    assert delete_response.status_code == 404


async def test_authenticate_with_api_key(client: AsyncClient, session: AsyncSession):
    """Test that API keys can be used for authentication."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    # Create an API key
    create_response = await client.post(
        "/api/v1/me/api-keys",
        headers=headers,
        json={"name": "Auth Test Key"},
    )
    api_key_secret = create_response.json()["secret"]

    # Use API key to authenticate
    api_key_headers = {"Authorization": f"Bearer {api_key_secret}"}
    auth_response = await client.get("/api/v1/me", headers=api_key_headers)

    assert auth_response.status_code == 200
    data = auth_response.json()
    assert data["email"] == "test@example.com"

    # Use is recorded, but a key used again within the hour is not rewritten.
    key = (
        await session.exec(select(UserApiKey).where(UserApiKey.user_id == user.id))
    ).one()
    first_use = key.last_used_at
    assert first_use is not None
    await client.get("/api/v1/me", headers=api_key_headers)
    await session.refresh(key)
    assert key.last_used_at == first_use

    key.last_used_at = first_use - timedelta(hours=2)
    session.add(key)
    await session.commit()
    await client.get("/api/v1/me", headers=api_key_headers)
    await session.refresh(key)
    assert key.last_used_at > first_use


async def test_api_key_works_for_platform_members(
    client: AsyncClient, session: AsyncSession
):
    """A platform member with no staff role can create and use API keys."""
    # Create a regular member user (no staff role)
    from app.models.platform.user import UserRole

    user = await create_user(
        session,
        email="member@example.com",
        role=UserRole.member,
    )
    headers = get_auth_headers(user)

    # Member creates an API key
    create_response = await client.post(
        "/api/v1/me/api-keys",
        headers=headers,
        json={"name": "Member Key"},
    )

    assert create_response.status_code == 201
    api_key_secret = create_response.json()["secret"]

    # Use the API key to authenticate
    api_key_headers = {"Authorization": f"Bearer {api_key_secret}"}
    auth_response = await client.get("/api/v1/me", headers=api_key_headers)

    assert auth_response.status_code == 200
    assert auth_response.json()["email"] == "member@example.com"


async def test_create_api_key_requires_authentication(client: AsyncClient):
    """Test that creating API keys requires authentication."""
    payload = {"name": "Unauthorized Key"}

    response = await client.post("/api/v1/me/api-keys", json=payload)

    assert response.status_code == 401


async def test_list_api_keys_requires_authentication(client: AsyncClient):
    """Test that listing API keys requires authentication."""
    response = await client.get("/api/v1/me/api-keys")

    assert response.status_code == 401


async def test_delete_api_key_requires_authentication(client: AsyncClient):
    """Test that deleting API keys requires authentication."""
    response = await client.delete("/api/v1/me/api-keys/1")

    assert response.status_code == 401


async def test_api_key_prefix_is_masked_in_list(
    client: AsyncClient, session: AsyncSession
):
    """Test that API key secrets are not exposed in list, only prefix."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    # Create a key
    create_response = await client.post(
        "/api/v1/me/api-keys",
        headers=headers,
        json={"name": "Test Key"},
    )
    full_secret = create_response.json()["secret"]
    expected_prefix = full_secret[:12]  # ppk_ plus 8 chars

    # List keys
    list_response = await client.get("/api/v1/me/api-keys", headers=headers)
    keys = list_response.json()["keys"]

    assert len(keys) == 1
    assert keys[0]["token_prefix"] == expected_prefix
    assert "secret" not in keys[0]  # Full secret should not be exposed


# --- Least-privilege scoping (read_only / guild_id) -------------------------


async def test_create_api_key_without_expiry_never_expires(
    client: AsyncClient, session: AsyncSession
):
    """A key created without an expiry never expires, and a far-future expiry
    is kept verbatim (no enforced ceiling) — revocation is the kill switch."""
    user = await create_user(session, email="ttl@example.com")
    headers = get_auth_headers(user)

    forever = await client.post(
        "/api/v1/me/api-keys", headers=headers, json={"name": "Forever"}
    )
    assert forever.status_code == 201
    assert forever.json()["api_key"]["expires_at"] is None

    far = (datetime.now(UTC) + timedelta(days=3650)).isoformat()
    long_lived = await client.post(
        "/api/v1/me/api-keys",
        headers=headers,
        json={"name": "Far", "expires_at": far},
    )
    returned = datetime.fromisoformat(long_lived.json()["api_key"]["expires_at"])
    expected = datetime.fromisoformat(far)
    assert abs((returned - expected).total_seconds()) < 5


async def test_read_only_key_blocks_writes_allows_reads(
    client: AsyncClient, session: AsyncSession, capfd
):
    """A read_only key may issue safe reads but is refused on any write."""
    user = await create_user(session, email="ro@example.com")
    headers = get_auth_headers(user)

    create = await client.post(
        "/api/v1/me/api-keys",
        headers=headers,
        json={"name": "RO", "read_only": True},
    )
    assert create.status_code == 201
    assert create.json()["api_key"]["read_only"] is True
    ro_headers = {"Authorization": f"Bearer {create.json()['secret']}"}

    # Safe read works.
    read = await client.get("/api/v1/me", headers=ro_headers)
    assert read.status_code == 200

    # A write (creating another key) is refused at the auth layer.
    emitted(capfd)
    write = await client.post(
        "/api/v1/me/api-keys", headers=ro_headers, json={"name": "nope"}
    )
    assert write.status_code == 403
    assert write.json()["detail"] == "USER_API_KEY_READ_ONLY"
    # Written down, against the key that overreached.
    (line,) = emitted(capfd, AuditEventType.API_KEY_SCOPE_VIOLATION)
    assert line["target"] == {"type": "api_key", "id": create.json()["api_key"]["id"]}
    assert line["detail"]["scope"] == "read_only"


async def test_guild_bound_key_is_pinned_to_its_guild(
    client: AsyncClient, session: AsyncSession
):
    """A guild-bound key reaches only its own guild; a different guild the user
    is otherwise a member of is refused (proving the block is the key pin)."""
    user = await create_user(session, email="pinned@example.com")
    guild_a = await create_guild(session, creator=user)
    guild_b = await create_guild(session, creator=user)
    await create_guild_membership(
        session, user=user, guild=guild_a, role=CommunityRole.member
    )
    await create_guild_membership(
        session, user=user, guild=guild_b, role=CommunityRole.member
    )
    headers = get_auth_headers(user)

    create = await client.post(
        "/api/v1/me/api-keys",
        headers=headers,
        json={"name": "GuildA", "community_id": guild_a.id},
    )
    assert create.json()["api_key"]["community_id"] == guild_a.id
    key_headers = {"Authorization": f"Bearer {create.json()['secret']}"}

    # Reaches its own guild.
    own = await client.get(f"/api/v1/c/{guild_a.id}/initiatives/", headers=key_headers)
    assert own.status_code == 200

    # Refused on a different guild the user *is* a member of.
    other = await client.get(
        f"/api/v1/c/{guild_b.id}/initiatives/", headers=key_headers
    )
    assert other.status_code == 403
    assert other.json()["detail"] == "COMMUNITY_ACCESS_DENIED"

    # The same user's session JWT reaches guild B — so the block was the key
    # pin, not a membership problem.
    jwt_other = await client.get(
        f"/api/v1/c/{guild_b.id}/initiatives/", headers=headers
    )
    assert jwt_other.status_code == 200


async def test_create_guild_bound_key_rejects_non_member(
    client: AsyncClient, session: AsyncSession
):
    """Scoping a key to a guild the caller doesn't belong to is refused, rather
    than minting a key that could never reach its claimed scope."""
    user = await create_user(session, email="outsider@example.com")
    # A guild the user is NOT a member of (the factory adds no membership).
    guild = await create_guild(session)
    headers = get_auth_headers(user)

    response = await client.post(
        "/api/v1/me/api-keys",
        headers=headers,
        json={"name": "Sneaky", "community_id": guild.id},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "USER_API_KEY_COMMUNITY_FORBIDDEN"


async def test_create_guild_bound_key_rejects_unknown_guild(
    client: AsyncClient, session: AsyncSession
):
    """An unknown guild id returns 403, not a 500 from the FK constraint."""
    user = await create_user(session, email="ghost@example.com")
    headers = get_auth_headers(user)

    response = await client.post(
        "/api/v1/me/api-keys",
        headers=headers,
        json={"name": "Ghost", "community_id": 999999},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "USER_API_KEY_COMMUNITY_FORBIDDEN"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/api/v1/me/api-keys", {"name": "Wider"}),
        ("DELETE", "/api/v1/me/api-keys/1", None),
        ("POST", "/api/v1/me/emails", {"email": "elsewhere@example.com"}),
        ("POST", "/api/v1/me/emails/1/remove", {}),
        ("PUT", "/api/v1/me/emails/1/primary", {}),
    ],
)
async def test_a_key_does_not_manage_keys_or_addresses(
    client: AsyncClient,
    session: AsyncSession,
    method: str,
    path: str,
    body: dict | None,
):
    """Keys and account addresses are managed in the person's own sign-in."""
    user = await create_user(session, email="key-manages@example.com")
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    create = await client.post(
        "/api/v1/me/api-keys",
        headers=get_auth_headers(user),
        json={"name": "Pinned", "community_id": guild.id},
    )
    assert create.status_code == 201, create.text
    key_headers = {"Authorization": f"Bearer {create.json()['secret']}"}

    response = await client.request(method, path, headers=key_headers, json=body)

    assert response.status_code == 403
    assert response.json()["detail"] == "SESSION_REQUIRED"


async def test_password_change_deactivates_api_keys(
    client: AsyncClient, session: AsyncSession
):
    """Changing the password (a credential-reset) deactivates outstanding API
    keys too."""
    user = await create_user(session, email="rotate@example.com")
    headers = get_auth_headers(user)

    create = await client.post(
        "/api/v1/me/api-keys", headers=headers, json={"name": "Doomed"}
    )
    key_headers = {"Authorization": f"Bearer {create.json()['secret']}"}

    # The key works before the reset.
    before = await client.get("/api/v1/me", headers=key_headers)
    assert before.status_code == 200

    # Reset the password with the required current password.
    changed = await client.patch(
        "/api/v1/me",
        headers=headers,
        json={
            "password": "brand-new-secret-123",
            "current_password": "testpassword123",
        },
    )
    assert changed.status_code == 200

    # The key no longer authenticates.
    after = await client.get("/api/v1/me", headers=key_headers)
    assert after.status_code == 401


async def test_a_key_names_one_resource_only_of_a_tool_with_a_feed(
    client: AsyncClient, session: AsyncSession
):
    """In its community, and for a tool in ``FEED_TOOLS``; a resource without
    a community, or of a tool with no feed, is refused before any key is
    made."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    headers = get_auth_headers(user)

    for body in (
        {"resource_type": "calendar", "resource_id": 1},
        {"community_id": guild.id, "resource_type": "project", "resource_id": 1},
        {"community_id": guild.id, "resource_type": "calendar"},
    ):
        refused = await client.post(
            "/api/v1/me/api-keys", headers=headers, json={"name": "k", **body}
        )
        assert refused.status_code == 422, body
    keys = (
        await session.exec(select(UserApiKey).where(UserApiKey.user_id == user.id))
    ).all()
    assert keys == []
