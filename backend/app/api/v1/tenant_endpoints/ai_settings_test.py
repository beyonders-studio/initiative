"""Integration tests for the mode-based AI config surface.

Proves the security properties end-to-end:
- A connection's key is never returned by the API (only ``has_api_key``).
- A member configures nothing: no connection of their own, no key, no choice.
  They read whether AI is available, and run on the owner's connection.
- A community can never persist a private/internal base_url.
"""

import pytest
from sqlmodel import update

from app.core.messages import AIMessages, GuildMessages
from app.db import post_commit
from app.models.platform.ai_connection import PlatformAIConnection
from app.models.platform.guild import CommunityRole, CommunityStatus, Guild
from app.services import ai_settings as ai_settings_service
from app.testing import billing_boundary, billing_guild_ref


PLATFORM_MODE = "/api/v1/settings/ai/platform/mode"
PLATFORM_CONNS = "/api/v1/settings/ai/platform/connections"


@pytest.fixture(autouse=True)
def _reset_ai_cache():
    """The platform config is cached in-process; drop it around each test so a
    mode/connection change in one test never leaks into the next."""
    ai_settings_service.invalidate_platform_ai_cache()
    yield
    ai_settings_service.invalidate_platform_ai_cache()


async def _set_mode(client, owner, mode: str):
    r = await client.put(PLATFORM_MODE, headers=owner.headers, json={"mode": mode})
    assert r.status_code == 200, r.text


async def test_platform_connection_key_never_returned(client, acting_user):
    owner = await acting_user()  # platform owner (config.manage)
    await _set_mode(client, owner, "platform")

    r = await client.post(
        PLATFORM_CONNS,
        headers=owner.headers,
        json={
            "label": "Company OpenAI",
            "provider": "openai",
            "model": "gpt-4o",
            "api_key": "sk-super-secret",
            "enabled": True,
            "is_default": True,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_api_key"] is True
    assert body["scope"] == "platform"
    # The ciphertext / plaintext key is never serialized.
    assert "api_key" not in body
    assert "api_key_encrypted" not in body

    # Listing likewise never exposes the key.
    r = await client.get(PLATFORM_CONNS, headers=owner.headers)
    assert r.status_code == 200
    for conn in r.json():
        assert "api_key" not in conn
        assert "api_key_encrypted" not in conn


async def test_member_reads_that_ai_is_available_without_the_key(client, acting_user):
    owner = await acting_user()
    await _set_mode(client, owner, "platform")
    await client.post(
        PLATFORM_CONNS,
        headers=owner.headers,
        json={
            "label": "Shared",
            "provider": "openai",
            "model": "gpt-4o",
            "api_key": "sk-secret",
            "is_default": True,
        },
    )

    member = await acting_user(guild_role=CommunityRole.member, initiative=True)
    r = await client.get(member.g("/settings/ai/resolved"), headers=member.headers)
    assert r.status_code == 200, r.text
    resolved = r.json()
    assert resolved["source"] == "platform"
    assert resolved["enabled"] is True
    assert resolved["has_api_key"] is True
    assert "api_key" not in resolved


async def test_member_cannot_set_a_destination(client, acting_user):
    """Exfil-impossible: a member has no endpoint to create a connection, so
    they can never point a key at a destination they chose."""
    owner = await acting_user()
    await _set_mode(client, owner, "platform")
    member = await acting_user(guild_role=CommunityRole.member, initiative=True)

    # There is no member connection-create route.
    r = await client.post(
        member.g("/settings/ai/connections"),
        headers=member.headers,
        json={"label": "evil", "provider": "custom", "base_url": "http://evil"},
    )
    assert r.status_code == 403  # the seat only


async def test_guild_admin_cannot_save_private_base_url(client, acting_user):
    owner = await acting_user()
    await _set_mode(client, owner, "community")

    admin = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)

    # A public custom endpoint is fine.
    r = await client.post(
        admin.g("/settings/ai/connections"),
        headers=admin.headers,
        json={"label": "ok", "provider": "openai", "model": "gpt-4o", "api_key": "k"},
    )
    assert r.status_code == 200, r.text

    # A private/internal base_url is rejected for a guild connection.
    r = await client.post(
        admin.g("/settings/ai/connections"),
        headers=admin.headers,
        json={
            "label": "evil",
            "provider": "ollama",
            "base_url": "http://169.254.169.254",
        },
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "AI_INVALID_BASE_URL"


async def test_a_member_runs_on_the_community_s_key(client, acting_user, reading_as):
    """A connection is used once it names a model. A member then reads that
    the seat's connection has a key, and their request resolves to it though
    they cannot read the key table. A key goes only where it was given for:
    sending the connection elsewhere clears it, which is seen the same way."""
    owner = await acting_user()
    await _set_mode(client, owner, "community")
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    r = await client.post(
        seat.g("/settings/ai/connections"),
        headers=seat.headers,
        json={
            "label": "Team",
            "provider": "openai",
            "api_key": "sk-team",
            "is_default": True,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["has_api_key"] is True
    conn_id = r.json()["id"]

    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=seat.guild,
        initiative=seat.initiative,
        initiative_role="member",
    )
    resolved = await client.get(
        member.g("/settings/ai/resolved"), headers=member.headers
    )
    assert resolved.json()["enabled"] is False
    r = await client.put(
        seat.g(f"/settings/ai/connections/{conn_id}"),
        headers=seat.headers,
        json={"model": "gpt-5-mini"},
    )
    assert r.status_code == 200, r.text
    resolved = await client.get(
        member.g("/settings/ai/resolved"), headers=member.headers
    )
    assert resolved.json()["enabled"] is True
    asking = await reading_as(member.user.id, seat.guild.id)
    with_key = await ai_settings_service.resolve_ai_settings(
        asking, seat.guild.id, with_key=True
    )
    assert with_key.api_key == "sk-team"

    r = await client.put(
        seat.g(f"/settings/ai/connections/{conn_id}"),
        headers=seat.headers,
        json={"provider": "anthropic", "model": "claude-haiku-5-5"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["has_api_key"] is False
    resolved = await client.get(
        member.g("/settings/ai/resolved"), headers=member.headers
    )
    assert resolved.json()["has_api_key"] is False


async def test_disabled_mode_hides_ai(client, acting_user):
    owner = await acting_user()
    await _set_mode(client, owner, "disabled")
    member = await acting_user(guild_role=CommunityRole.member, initiative=True)

    r = await client.get(member.g("/settings/ai/resolved"), headers=member.headers)
    assert r.status_code == 200
    assert r.json()["enabled"] is False


async def test_connecting_a_provider_is_the_seat_s(client, acting_user):
    """Which provider a community's work is sent to says what leaves it, so it
    answers to the seat rather than to running the community."""
    owner = await acting_user()
    await _set_mode(client, owner, "community")
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)

    listed = await client.get(
        admin.g("/settings/ai/connections"), headers=admin.headers
    )
    assert listed.status_code == 403, listed.text

    created = await client.post(
        admin.g("/settings/ai/connections"),
        headers=admin.headers,
        json={"label": "no", "provider": "openai", "model": "gpt-4o", "api_key": "k"},
    )
    assert created.status_code == 403, created.text


async def test_a_connection_given_to_a_community_serves_only_it(
    client, acting_user, reading_as, session
):
    """A division runs on the key given to it; the rest share the connections
    given to nobody. Giving a community to another connection takes it from
    the first, and a division whose own connection is off has no AI rather
    than the shared key."""
    owner = await acting_user()
    await _set_mode(client, owner, "platform")
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    b = await acting_user(guild_role=CommunityRole.member, initiative=True)

    async def connection(label: str, key: str, communities: list[int]) -> dict:
        r = await client.post(
            PLATFORM_CONNS,
            headers=owner.headers,
            json={
                "label": label,
                "provider": "openai",
                "model": "gpt-5-mini",
                "api_key": key,
                "is_default": not communities,
                "community_ids": communities,
            },
        )
        assert r.status_code == 200, r.text
        return r.json()

    division = await connection("Division", "sk-division", [a.guild.id])
    await connection("Everyone", "sk-shared", [])
    assert division["communities"] == [{"id": a.guild.id, "name": a.guild.name}]

    async def key_for(actor) -> str | None:
        asking = await reading_as(actor.user.id, actor.guild.id)
        resolved = await ai_settings_service.resolve_ai_settings(
            asking, actor.guild.id, with_key=True
        )
        return resolved.api_key

    assert await key_for(a) == "sk-division"
    assert await key_for(b) == "sk-shared"

    await connection("Reorganised", "sk-reorganised", [a.guild.id])
    listed = {
        c["label"]: c
        for c in (await client.get(PLATFORM_CONNS, headers=owner.headers)).json()
    }
    assert listed["Division"]["communities"] == []
    assert await key_for(a) == "sk-reorganised"

    off = await client.put(
        f"{PLATFORM_CONNS}/{listed['Reorganised']['id']}",
        headers=owner.headers,
        json={"enabled": False},
    )
    assert off.status_code == 200, off.text
    assert await key_for(a) is None
    assert await key_for(b) == "sk-shared"

    # A deleted community stays listed and kept until it is taken off, and one
    # gone entirely is listed without a name; neither can be given anew.
    reorganised = f"{PLATFORM_CONNS}/{listed['Reorganised']['id']}"
    both = await client.put(
        reorganised,
        headers=owner.headers,
        json={"community_ids": [a.guild.id, b.guild.id]},
    )
    assert both.status_code == 200, both.text
    await session.exec(
        update(Guild)
        .where(Guild.id == b.guild.id)
        .values(status=CommunityStatus.deleted)
    )
    await session.exec(
        update(PlatformAIConnection)
        .where(PlatformAIConnection.id == listed["Reorganised"]["id"])
        .values(community_ids=[a.guild.id, b.guild.id, 999_999])
    )
    await session.commit()
    kept = await client.put(reorganised, headers=owner.headers, json={"label": "Kept"})
    assert kept.status_code == 200, kept.text
    assert {(c["id"], c["name"]) for c in kept.json()["communities"]} == {
        (a.guild.id, a.guild.name),
        (b.guild.id, b.guild.name),
        (999_999, None),
    }
    regiven = await client.put(
        f"{PLATFORM_CONNS}/{listed['Division']['id']}",
        headers=owner.headers,
        json={"community_ids": [b.guild.id]},
    )
    assert regiven.status_code == 404
    assert regiven.json()["detail"] == GuildMessages.COMMUNITY_NOT_FOUND


async def test_a_community_can_switch_ai_off(client, acting_user):
    owner = await acting_user()
    await _set_mode(client, owner, "platform")
    await client.post(
        PLATFORM_CONNS,
        headers=owner.headers,
        json={
            "label": "Shared",
            "provider": "openai",
            "model": "gpt-5-mini",
            "api_key": "sk-shared",
            "is_default": True,
        },
    )
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    settings_path = f"/api/v1/communities/{seat.guild.id}/auth-settings"

    off = await client.patch(
        settings_path, headers=seat.headers, json={"allow_ai": False}
    )
    assert off.status_code == 200, off.text
    assert (off.json()["allow_ai"], off.json()["ai_offered_by_platform"]) == (
        False,
        True,
    )
    resolved = await client.get(seat.g("/settings/ai/resolved"), headers=seat.headers)
    assert resolved.json()["enabled"] is False

    await client.patch(settings_path, headers=seat.headers, json={"allow_ai": True})
    resolved = await client.get(seat.g("/settings/ai/resolved"), headers=seat.headers)
    assert resolved.json()["enabled"] is True


async def test_a_community_s_connections_are_off_while_its_ai_is(client, acting_user):
    owner = await acting_user()
    await _set_mode(client, owner, "community")
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    settings_path = f"/api/v1/communities/{seat.guild.id}/auth-settings"
    conns = seat.g("/settings/ai/connections")
    body = {"label": "Team", "provider": "openai", "model": "m", "api_key": "k"}
    first = (await client.post(conns, headers=seat.headers, json=body)).json()
    assert first["enabled"] is True

    await client.patch(settings_path, headers=seat.headers, json={"allow_ai": False})
    listed = (await client.get(conns, headers=seat.headers)).json()
    assert [c["enabled"] for c in listed] == [False]
    second = (
        await client.post(conns, headers=seat.headers, json={**body, "label": "B"})
    ).json()
    assert second["enabled"] is False
    refused = await client.put(
        f"{conns}/{first['id']}", headers=seat.headers, json={"enabled": True}
    )
    assert refused.status_code == 409
    assert refused.json()["detail"] == AIMessages.NOT_ENABLED

    # Back on, each connection is turned on again by itself.
    await client.patch(settings_path, headers=seat.headers, json={"allow_ai": True})
    turned_on = await client.put(
        f"{conns}/{first['id']}", headers=seat.headers, json={"enabled": True}
    )
    assert turned_on.json()["enabled"] is True


async def _connections_on(client, seat) -> list[bool]:
    """Whether each of the community's connections is on, once the work its
    last change left for after the commit has run."""
    await post_commit.settle_all()
    listed = await client.get(seat.g("/settings/ai/connections"), headers=seat.headers)
    return [c["enabled"] for c in listed.json()]


async def _a_connection(client, acting_user):
    owner = await acting_user()
    await _set_mode(client, owner, "community")
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    created = await client.post(
        seat.g("/settings/ai/connections"),
        headers=seat.headers,
        json={"label": "Team", "provider": "openai", "model": "m", "api_key": "k"},
    )
    return owner, seat, created.json()["id"]


async def test_the_server_turning_ai_off_turns_the_connections_off(
    client, acting_user, monkeypatch
):
    billing_boundary.configure(monkeypatch)
    _owner, seat, _ = await _a_connection(client, acting_user)
    restricted = {
        "tier_name": "Gold",
        "max_storage_bytes": 1024**3,
        "max_users": 50,
        "max_guests": 5,
        "feature_keys": ["security_standards"],
        "status": "active",
    }
    ref = await billing_guild_ref(seat.guild.id)

    async def sync(version: int, fields: dict) -> None:
        response = await billing_boundary.post(
            client,
            "communities/sync",
            {
                "communities": [
                    {"community_ref": ref, "version": version, "fields": fields}
                ]
            },
        )
        assert "error" not in response.json()["results"][0], response.text

    await sync(1, restricted)
    assert await _connections_on(client, seat) == [True]
    await sync(2, {**restricted, "rules": [{"key": "allow_ai", "value": False}]})
    assert await _connections_on(client, seat) == [False]


async def test_granting_restrictions_back_turns_the_connections_off(
    client, acting_user
):
    """A community's own no to AI stops applying while it has no
    restrictions, and its connections can be turned on; granted them back,
    the no applies again and the connections go off."""
    owner, seat, conn_id = await _a_connection(client, acting_user)
    community = f"/api/v1/settings/communities/{seat.guild.id}"
    await client.patch(
        f"/api/v1/communities/{seat.guild.id}/auth-settings",
        headers=seat.headers,
        json={"allow_ai": False},
    )
    withdrawn = await client.patch(
        community, headers=owner.headers, json={"auth_options": ["providers"]}
    )
    assert withdrawn.status_code == 200, withdrawn.text
    turned_on = await client.put(
        seat.g(f"/settings/ai/connections/{conn_id}"),
        headers=seat.headers,
        json={"enabled": True},
    )
    assert turned_on.status_code == 200, turned_on.text

    await client.patch(
        community,
        headers=owner.headers,
        json={"auth_options": ["providers", "restrictions"]},
    )
    assert await _connections_on(client, seat) == [False]


async def test_a_connection_shows_how_its_last_request_went(
    client, acting_user, monkeypatch
):
    from app.services import ai_provider
    from app.services.ai_provider import AIRequestError

    owner = await acting_user()
    await _set_mode(client, owner, "community")
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    created = await client.post(
        seat.g("/settings/ai/connections"),
        headers=seat.headers,
        json={"label": "Team", "provider": "openai", "model": "m", "api_key": "k"},
    )
    conn_id = created.json()["id"]
    assert created.json()["last_error"] is None

    async def refused(target):
        raise AIRequestError(AIMessages.OUT_OF_CREDIT)

    async def answered(target):
        return ["m"]

    async def test_and_list(answer) -> dict:
        monkeypatch.setattr(ai_provider, "list_models", answer)
        await client.post(
            seat.g(f"/settings/ai/connections/{conn_id}/test"), headers=seat.headers
        )
        listed = await client.get(
            seat.g("/settings/ai/connections"), headers=seat.headers
        )
        return listed.json()[0]

    failing = await test_and_list(refused)
    assert failing["last_error"] == AIMessages.OUT_OF_CREDIT
    assert failing["last_error_at"] is not None
    assert (await test_and_list(refused))["last_error_at"] == failing["last_error_at"]

    recovered = await test_and_list(answered)
    assert (recovered["last_error"], recovered["last_error_at"]) == (None, None)
