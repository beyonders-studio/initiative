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


def _where(row: dict) -> tuple:
    return (
        row["actor_user_id"],
        row["target_user_id"],
        row["guild_id"],
        row["target"],
    )


async def test_create_list_and_delete_api_key(
    client: AsyncClient, session: AsyncSession, capfd
):
    """A key is minted, listed by its prefix only, and dropped; the audit
    record of each carries its scope and never the key's name."""
    user = await create_user(session, email="test@example.com")
    user_id = user.id
    headers = get_auth_headers(user)

    empty = await client.get("/api/v1/me/api-keys", headers=headers)
    assert empty.status_code == 200
    assert empty.json()["keys"] == []
    capfd.readouterr()

    response = await client.post(
        "/api/v1/me/api-keys",
        headers=headers,
        json={"name": "Test API Key", "expires_at": None},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["api_key"]["name"] == "Test API Key"
    assert data["api_key"]["is_active"] is True
    assert data["secret"].startswith("ppk_")
    assert len(data["secret"]) > 20
    key_id = data["api_key"]["id"]

    created = emitted(capfd, AuditEventType.API_KEY_CREATED)
    assert [_where(row) for row in created] == [
        (user_id, user_id, None, {"type": "user_api_key", "id": key_id})
    ]
    assert created[0]["detail"] == {
        "read_only": False,
        "expires_at": None,
        "guild_bound": False,
        "resource_type": None,
    }

    await client.post("/api/v1/me/api-keys", headers=headers, json={"name": "Key 2"})
    listed = await client.get("/api/v1/me/api-keys", headers=headers)
    assert listed.status_code == 200
    keys = {key["name"]: key for key in listed.json()["keys"]}
    assert set(keys) == {"Test API Key", "Key 2"}
    assert keys["Test API Key"]["token_prefix"] == data["secret"][:12]
    assert "secret" not in keys["Test API Key"]
    capfd.readouterr()

    delete_response = await client.delete(
        f"/api/v1/me/api-keys/{key_id}", headers=headers
    )
    assert delete_response.status_code == 204
    deleted = emitted(capfd, AuditEventType.API_KEY_DELETED)
    assert [_where(row) for row in deleted] == [
        (user_id, user_id, None, {"type": "user_api_key", "id": key_id})
    ]

    list_response = await client.get("/api/v1/me/api-keys", headers=headers)
    assert [key["name"] for key in list_response.json()["keys"]] == ["Key 2"]


async def test_delete_nonexistent_api_key(client: AsyncClient, session: AsyncSession):
    """Test deleting an API key that doesn't exist."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    response = await client.delete("/api/v1/me/api-keys/99999", headers=headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "USER_API_KEY_NOT_FOUND"


async def test_cannot_delete_other_users_api_key(
    client: AsyncClient, session: AsyncSession, capfd
):
    """Another user's key reads as absent, and nothing is recorded."""
    user1 = await create_user(session, email="user1@example.com")
    user2 = await create_user(session, email="user2@example.com")

    create_response = await client.post(
        "/api/v1/me/api-keys",
        headers=get_auth_headers(user1),
        json={"name": "User 1 Key"},
    )
    api_key_id = create_response.json()["api_key"]["id"]
    capfd.readouterr()

    delete_response = await client.delete(
        f"/api/v1/me/api-keys/{api_key_id}",
        headers=get_auth_headers(user2),
    )

    assert delete_response.status_code == 404
    assert emitted(capfd, AuditEventType.API_KEY_DELETED) == []


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


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/me/api-keys"),
        ("GET", "/api/v1/me/api-keys"),
        ("DELETE", "/api/v1/me/api-keys/1"),
    ],
)
async def test_api_key_endpoints_require_authentication(
    client: AsyncClient, method: str, path: str
):
    body = {"name": "Unauthorized Key"} if method == "POST" else None
    response = await client.request(method, path, json=body)

    assert response.status_code == 401


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
    client: AsyncClient, session: AsyncSession, capfd
):
    """A guild-bound key reaches only its own guild; a different guild the user
    is otherwise a member of is refused (proving the block is the key pin).
    Its audit record says which community it is bound to."""
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
    user_id, guild_a_id = user.id, guild_a.id
    capfd.readouterr()

    create = await client.post(
        "/api/v1/me/api-keys",
        headers=headers,
        json={"name": "GuildA", "community_id": guild_a.id, "read_only": True},
    )
    assert create.json()["api_key"]["community_id"] == guild_a.id
    key_id = create.json()["api_key"]["id"]
    created = emitted(capfd, AuditEventType.API_KEY_CREATED)
    assert [_where(row) for row in created] == [
        (user_id, user_id, guild_a_id, {"type": "user_api_key", "id": key_id})
    ]
    assert created[0]["detail"] == {
        "read_only": True,
        "expires_at": None,
        "guild_bound": True,
        "resource_type": None,
    }
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


@pytest.mark.parametrize("known", [True, False])
async def test_create_guild_bound_key_rejects_non_member(
    client: AsyncClient, session: AsyncSession, known: bool
):
    """Scoping a key to a guild the caller doesn't belong to, or to no guild at
    all, is refused rather than minting a key that could never reach its
    claimed scope."""
    user = await create_user(session, email="outsider@example.com")
    # A guild the user is NOT a member of (the factory adds no membership).
    community_id = (await create_guild(session)).id if known else 999999
    headers = get_auth_headers(user)

    response = await client.post(
        "/api/v1/me/api-keys",
        headers=headers,
        json={"name": "Sneaky", "community_id": community_id},
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
    """In its community, and for a tool that serves a feed; a resource without
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
