"""
Integration tests for user endpoints.

Tests the user API endpoints at /api/v1/users including:
- Getting current user info
- Listing users in a guild
- Updating user profile
- User deletion
"""

import uuid

import pytest
from sqlalchemy import text, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.profile_decorations import SHIPPED_DECORATIONS
from app.db.query import MAX_ID_FILTER_VALUES
from app.models.platform.guild import CommunityRole, GuildMembership
from app.models.platform.user import Presence, User, UserStatus
from app.models.platform.user_decoration import UserDecoration
from app.models.platform.user_dm_settings import DmPolicy
from app.models.platform.user_passkey import UserPasskey
from app.models.tenant.task_assignment_digest import TaskAssignmentDigestItem
from app.schemas.platform.user import STATUS_TEXT_MAX_LENGTH
from app.services.marketplace import catalog as marketplace_catalog
from app.services.marketplace.builtin import load_builtin_manifests
from app.services.platform import rules
from app.services.platform import profile_decorations as profile_decorations_service
from app.services.content_sockets import sockets as content_sockets
from app.testing.sockets import (
    FakeWebSocket,
    open_account_socket,
    watch_events_bus,
)
from app.testing.factories import (
    create_federated_identity,
    create_guild,
    create_guild_membership,
    create_initiative,
    create_marketplace_listing,
    create_profile_pack,
    create_project,
    create_task,
    create_user,
    get_auth_token,
)
from app.testing import route_as

#: Every test here drives the API through the real app and a real database.


PROFILE_URL = "/api/v1/users/{handle}/profile"


def _profile_url(user: User) -> str:
    return PROFILE_URL.format(handle=f"{user.username}{user.discriminator:04d}")


async def test_get_current_user(client, acting_user):
    """The account read answers with the account's own details."""
    a = await acting_user(email="test@example.com")

    response = await client.get("/api/v1/me", headers=a.headers)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == a.user.id
    assert data["email"] == "test@example.com"
    assert data["status"] == "active"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        pytest.param("GET", "/api/v1/me", id="my-account"),
        pytest.param("GET", "/api/v1/users/nobody0001/profile", id="a-profile"),
    ],
)
async def test_the_users_router_answers_401_to_a_signed_out_caller(
    client, method, path
):
    """Every read of a person is a signed-in read."""
    response = await client.request(method, path)

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "who"),
    [
        pytest.param("GET", "/users/search", "outsider", id="search-from-outside"),
        pytest.param("GET", "/users/roster", "outsider", id="roster-from-outside"),
        pytest.param("GET", "/users/export.csv", "member", id="export-as-a-member"),
        pytest.param("DELETE", "/users/{target}", "member", id="remove-as-a-member"),
    ],
)
async def test_the_users_router_answers_403_without_the_standing(
    client, acting_user, method, path, who
):
    """403 for a caller signed in without the standing the route asks for: a
    non-member reaching into the guild, and a plain member on a route that is
    a guild admin's. The path is a selector, not a trust boundary."""
    admin = await acting_user(guild_role=CommunityRole.admin)
    caller = (
        await acting_user()
        if who == "outsider"
        else await acting_user(guild_role=CommunityRole.member, guild=admin.guild)
    )
    target = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)

    response = await client.request(
        method,
        admin.g(path.format(target=target.user.id)),
        headers=caller.headers,
    )

    assert response.status_code == 403


async def test_update_current_user_profile(client, acting_user):
    """Test updating current user's profile."""
    a = await acting_user()

    # An older client that still sends an account name is not refused; the
    # name has nowhere to go.
    response = await client.patch(
        "/api/v1/me",
        headers=a.headers,
        json={"full_name": "New Name", "timezone": "America/New_York"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "full_name" not in data
    assert data["timezone"] == "America/New_York"


async def test_every_mutable_channel_can_be_switched_off(client, acting_user):
    """Every switch the grid renders actually moves.

    The grid is rendered from the registry the response carries, so this walks
    that same registry rather than a list of its own — a category added
    tomorrow is covered without editing this test.
    """
    a = await acting_user()

    registry = (
        await client.get("/api/v1/me/notification-preferences", headers=a.headers)
    ).json()["categories"]
    changes = [
        {"category": row["category"], "channel": channel, "enabled": False}
        for row in registry
        for channel in row["mutable_channels"]
    ]
    assert changes
    defaults = {row["category"]: row["defaults"] for row in registry}

    response = await client.put(
        "/api/v1/me/notification-preferences",
        headers=a.headers,
        json={"channels": changes},
    )

    assert response.status_code == 200
    settings = response.json()["settings"]
    missing = [
        (change["category"], change["channel"])
        for change in changes
        # What the account now has: what it stored, or the default where it
        # stored nothing, as a channel that starts off does.
        if settings.get(change["category"], {}).get(
            change["channel"], defaults[change["category"]][change["channel"]]
        )
        is not False
    ]
    assert missing == []


async def test_a_channel_that_cannot_be_switched_off_stays_on(client, acting_user):
    """Being told your account was acted on is not a preference."""
    a = await acting_user()

    response = await client.put(
        "/api/v1/me/notification-preferences",
        headers=a.headers,
        json={
            "channels": [{"category": "account", "channel": "in_app", "enabled": False}]
        },
    )

    assert response.status_code == 200
    assert "in_app" not in response.json()["settings"].get("account", {})


async def test_returning_a_switch_to_its_default_leaves_no_trace(client, acting_user):
    """Sparseness is what makes "on by default" true by construction."""
    a = await acting_user()

    off = await client.put(
        "/api/v1/me/notification-preferences",
        headers=a.headers,
        json={
            "channels": [
                {"category": "subscriptions", "channel": "push", "enabled": False}
            ]
        },
    )
    assert off.json()["settings"]["subscriptions"]["push"] is False

    back_on = await client.put(
        "/api/v1/me/notification-preferences",
        headers=a.headers,
        json={
            "channels": [
                {"category": "subscriptions", "channel": "push", "enabled": True}
            ]
        },
    )
    assert back_on.json()["settings"] == {}


async def test_a_community_can_say_less_or_nothing(client, acting_user):
    """A row switched off in one community, and a community muted; a row a
    community cannot switch on its own does not move."""
    a = await acting_user(guild_role=CommunityRole.member)

    response = await client.put(
        "/api/v1/me/notification-preferences",
        headers=a.headers,
        json={
            "rows": [
                {"community_id": a.guild.id, "category": "news", "enabled": False},
                {"community_id": a.guild.id, "category": "approvals", "enabled": False},
            ]
        },
    )

    assert response.status_code == 200, response.text
    listed = {g["community_id"]: g for g in response.json()["communities"]}
    assert listed[a.guild.id] == {
        "community_id": a.guild.id,
        "community_name": a.guild.name,
        "muted": False,
        "off": ["news"],
    }

    response = await client.put(
        "/api/v1/me/notification-preferences",
        headers=a.headers,
        json={
            "rows": [{"community_id": a.guild.id, "category": "news", "enabled": True}],
            "mutes": [{"community_id": a.guild.id, "muted": True}],
        },
    )

    listed = {g["community_id"]: g for g in response.json()["communities"]}
    assert listed[a.guild.id]["muted"] is True
    assert listed[a.guild.id]["off"] == []


async def test_quiet_hours_round_trip(client, acting_user):
    a = await acting_user()

    saved = await client.put(
        "/api/v1/me/notification-preferences",
        headers=a.headers,
        json={"quiet_hours": {"start": "22:00", "end": "07:00"}},
    )
    assert saved.json()["quiet_hours"] == {"start": "22:00", "end": "07:00"}

    cleared = await client.put(
        "/api/v1/me/notification-preferences",
        headers=a.headers,
        json={"clear_quiet_hours": True},
    )
    assert cleared.json()["quiet_hours"] is None


async def _queue_assignment_item(session: AsyncSession, user, guild) -> None:
    """Put one pending digest item in ``guild``'s schema for ``user``."""
    initiative = await create_initiative(session, guild, user, name="Queue")
    project = await create_project(session, initiative, user, name="Queue Project")
    task = await create_task(session, project, title="Queued")
    await route_as(session, user_id=user.id, guild_id=guild.id)
    session.add(
        TaskAssignmentDigestItem(
            user_id=user.id,
            task_id=task.id,
            project_id=project.id,
            task_title="Queued",
            project_name=project.name,
            assigned_by_name="Assigner",
        )
    )
    await session.commit()


async def _pending_assignment_items(session: AsyncSession, user, guild) -> int:
    session.expunge_all()
    await route_as(session, user_id=user.id, guild_id=guild.id)
    rows = (
        await session.exec(
            select(TaskAssignmentDigestItem).where(
                TaskAssignmentDigestItem.processed_at.is_(None)
            )
        )
    ).all()
    return len(rows)


@pytest.mark.parametrize(
    ("switched_off", "still_queued"),
    [
        pytest.param(["email"], 1, id="the-push-digest-is-still-going-to-send-them"),
        pytest.param(["email", "push"], 0, id="nothing-is-left-that-would-send-them"),
    ],
)
async def test_switching_assignment_channels_off_keeps_the_queue_while_one_is_on(
    client, session, acting_user, switched_off, still_queued
):
    """One queue backs both channels: the items stay while either channel is
    on and go with the last one."""
    a = await acting_user(guild_role=CommunityRole.member)
    await _queue_assignment_item(session, a.user, a.guild)

    response = await client.put(
        "/api/v1/me/notification-preferences",
        headers=a.headers,
        json={
            "channels": [
                {"category": "assignments", "channel": channel, "enabled": False}
                for channel in switched_off
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["settings"]["assignments"]["email"] is False
    assert await _pending_assignment_items(session, a.user, a.guild) == still_queued


async def test_list_users_lists_this_guilds_members(client, acting_user):
    """The roster is this guild's members and nobody else's, a page at a time.

    Members are named by handle. An address is never a guild's to hand out, so
    it is absent from the shape entirely. Pages are ordered by name, and a
    search narrows them the way the picker's does.
    """
    caller = await acting_user(
        guild_role=CommunityRole.member,
        username="user-one",
        initiative=True,
    )
    await acting_user(
        guild_role=CommunityRole.member,
        guild=caller.guild,
        username="zed-two",
    )
    await acting_user(guild_role=CommunityRole.member)  # somebody in another guild

    response = await client.get(caller.g("/users/"), headers=caller.headers)

    assert response.status_code == 200
    data = response.json()
    assert data["total_count"] == 2
    assert {user["username"] for user in data["items"]} == {"user-one", "zed-two"}
    assert all("email" not in user for user in data["items"])
    [roles] = [
        u["initiative_roles"] for u in data["items"] if u["id"] == caller.user.id
    ]
    assert [(r["initiative_id"], r["role"]) for r in roles] == [
        (caller.initiative.id, "project_manager")
    ]

    pages = [
        (
            await client.get(
                caller.g(f"/users/?page={page}&page_size=1"), headers=caller.headers
            )
        ).json()
        for page in (1, 2)
    ]
    assert [p["items"][0]["username"] for p in pages] == ["user-one", "zed-two"]
    assert [(p["has_next"], p["has_prev"]) for p in pages] == [
        (True, False),
        (False, True),
    ]

    searched = await client.get(caller.g("/users/?search=zed"), headers=caller.headers)
    assert [u["username"] for u in searched.json()["items"]] == ["zed-two"]


async def test_search_users_returns_slim_paginated_envelope(client, acting_user):
    """The slim search endpoint returns a UserSummary envelope (no email /
    role / initiative_roles) and honours page_size."""
    caller = await acting_user(guild_role=CommunityRole.member, username="aaa-caller")
    await acting_user(guild=caller.guild, username="bbb-other")
    await acting_user(guild=caller.guild, username="ccc-third")

    response = await client.get(
        caller.g("/users/search"),
        headers=caller.headers,
        params={"page_size": 2, "page": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 3
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert body["has_next"] is True
    assert body["has_prev"] is False
    assert len(body["items"]) == 2
    assert [item["username"] for item in body["items"]] == ["aaa-caller", "bbb-other"]
    # Slim projection: no email, no platform tier, no initiative_roles. What
    # stays is what it takes to draw a person and say where they stand here —
    # the avatar, what is worn around it, and the guild role — none of which
    # costs a query beyond the one already run.
    summary = body["items"][0]
    assert set(summary.keys()) == {
        "id",
        "username",
        "discriminator",
        "display_name",
        "avatar_url",
        "status",
        "profile_decorations",
        "community_role",
    }
    # Asserted as a value, not only as a key. The schema leaves it unset, so a
    # key-set check passes just as happily on an endpoint that never fills it
    # in -- which is the state this test was written against.
    assert summary["community_role"] == "member"
    # Nobody set a name in this guild.
    assert summary["display_name"] is None


async def test_search_users_can_list_the_caller_first(client, acting_user):
    """``self_first`` puts the caller at the top of page one, wherever their
    handle would sort; everyone else keeps their order."""
    caller = await acting_user(guild_role=CommunityRole.member, username="zzz-caller")
    await acting_user(guild=caller.guild, username="aaa-other")
    await acting_user(guild=caller.guild, username="bbb-other")

    response = await client.get(
        caller.g("/users/search"),
        headers=caller.headers,
        params={"self_first": True, "page_size": 2},
    )

    assert response.status_code == 200, response.text
    assert [item["username"] for item in response.json()["items"]] == [
        "zzz-caller",
        "aaa-other",
    ]


async def test_search_users_says_where_each_member_stands(client, acting_user):
    """The roster says who runs the place.

    A page listing people so somebody can reach one of them has to be able to
    say which of them to reach about the community itself, and the role comes
    off the join the query already makes.
    """
    admin = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)

    response = await client.get(admin.g("/users/search"), headers=admin.headers)
    assert response.status_code == 200, response.text

    roles = {
        item["username"]: item["community_role"] for item in response.json()["items"]
    }
    assert roles[admin.user.username] == "admin"
    assert roles[member.user.username] == "member"


async def _dm_policy(session, policy: DmPolicy, *users) -> None:
    await session.exec(
        text(
            "UPDATE public.user_dm_settings "
            "SET dm_policy = CAST(:p AS user_dm_policy) "
            "WHERE user_id = ANY(CAST(:ids AS int[]))"
        ).bindparams(p=policy.value, ids=[user.id for user in users])
    )
    await session.commit()


async def test_roster_groups_by_presence_and_leaves_out_private_accounts(
    client, session, acting_user
):
    """Who is here comes first, a group at a time. Somebody whose direct
    messages are private is not listed at all, the reader included, and nor is
    somebody on "My communities" who switched this one off."""
    reader = await acting_user(guild_role=CommunityRole.member, username="reader")
    here = await acting_user(guild=reader.guild, username="zed-here")
    busy = await acting_user(guild=reader.guild, username="amy-busy")
    away = await acting_user(guild=reader.guild, username="bob-away")
    hidden = await acting_user(guild=reader.guild, username="cat-hidden")
    opted_out = await acting_user(guild=reader.guild, username="dan-opted-out")
    await _dm_policy(session, DmPolicy.community, here.user, busy.user, opted_out.user)
    await _dm_policy(session, DmPolicy.public, away.user)
    await session.exec(
        text(
            "INSERT INTO public.user_dm_guild_optouts (user_id, guild_id, created_at) "
            "VALUES (:u, :g, now())"
        ).bindparams(u=opted_out.user.id, g=reader.guild.id)
    )
    await session.commit()

    sockets = [
        open_account_socket(here.user.id),
        open_account_socket(busy.user.id, chosen_presence=Presence.busy),
        open_account_socket(hidden.user.id),
    ]
    try:
        response = await client.get(reader.g("/users/roster"), headers=reader.headers)
    finally:
        for socket in sockets:
            content_sockets.leave(socket)  # type: ignore[arg-type]

    assert response.status_code == 200, response.text
    body = response.json()
    assert [(item["username"], item["presence"]) for item in body["items"]] == [
        ("zed-here", "online"),
        ("amy-busy", "busy"),
        ("bob-away", "offline"),
    ]
    assert body["presence_counts"] == {"online": 1, "idle": 0, "busy": 1, "offline": 1}
    assert body["total_count"] == 3


async def test_roster_lists_everyone_where_direct_messages_are_off(
    client, session, acting_user
):
    """With no direct messages on the deployment there is no policy to keep."""
    reader = await acting_user(guild_role=CommunityRole.member)
    other = await acting_user(guild=reader.guild)
    await rules.put(session, "community_directory_enabled", False)
    await rules.put(session, "direct_messages_enabled", False)
    await session.commit()

    response = await client.get(reader.g("/users/roster"), headers=reader.headers)

    assert response.status_code == 200, response.text
    assert {item["id"] for item in response.json()["items"]} == {
        reader.user.id,
        other.user.id,
    }


@pytest.mark.parametrize(
    ("typed", "expect"),
    [
        pytest.param("SMITH", {"asmith"}, id="case-insensitive-substring"),
        pytest.param("irnforge", {"thorn-ironforge"}, id="a-dropped-letter"),
        pytest.param("ironfroge", {"thorn-ironforge"}, id="a-transposition"),
    ],
)
async def test_search_users_finds_the_name_that_was_typed(
    client, acting_user, typed, expect
):
    """`search` matches the part of the handle this guild renders, without
    regard to case. Reading a roster is how you learn a colleague's spelling,
    so a dropped letter and a transposition both still find the person."""
    caller = await acting_user(guild_role=CommunityRole.member, username="asmith")
    await acting_user(guild=caller.guild, username="bjones")
    await acting_user(guild=caller.guild, username="thorn-ironforge")

    response = await client.get(
        caller.g("/users/search"), headers=caller.headers, params={"search": typed}
    )

    assert response.status_code == 200, response.text
    found = {item["username"] for item in response.json()["items"]}
    assert found == expect


async def test_search_users_never_reaches_another_guild(client, acting_user):
    """Matching a name more loosely must not widen WHOSE names are matched.
    Only this guild's members are ever searched, exact spelling or not."""
    caller = await acting_user(guild_role=CommunityRole.member, username="asmith")
    await acting_user(guild_role=CommunityRole.member, username="thorn-ironforge")

    for typed in ("ironforge", "irnforge", "thorn"):
        response = await client.get(
            caller.g("/users/search"),
            headers=caller.headers,
            params={"search": typed},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total_count"] == 0, f"{typed} reached {body['items']}"


async def test_search_users_filters_by_user_id(client, acting_user):
    """`user_id` resolves a known selection, and only ever narrows the roster
    the caller can already see — an id from another guild returns nothing."""
    caller = await acting_user(guild_role=CommunityRole.member)
    bob = await acting_user(guild=caller.guild)
    stranger = await acting_user(guild_role=CommunityRole.member)

    response = await client.get(
        caller.g("/users/search"),
        headers=caller.headers,
        params={"user_id": [bob.user.id]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 1
    assert [item["username"] for item in body["items"]] == [bob.user.username]

    # An id outside the guild is filtered out, not resolved.
    response = await client.get(
        caller.g("/users/search"),
        headers=caller.headers,
        params={"user_id": [bob.user.id, stranger.user.id]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 1
    assert [item["id"] for item in body["items"]] == [bob.user.id]


async def test_search_users_rejects_oversized_user_id_list(client, acting_user):
    """The id filter is bounded so one request can't submit an unbounded list."""
    caller = await acting_user(guild_role=CommunityRole.member)

    response = await client.get(
        caller.g("/users/search"),
        headers=caller.headers,
        params={"user_id": list(range(MAX_ID_FILTER_VALUES + 1))},
    )

    assert response.status_code == 422


async def test_self_service_password_change_revokes_sessions_on_every_device(
    client, session, acting_user
):
    """Changing your own password via PATCH /me invalidates other outstanding
    JWTs and every session, the app's included, as every password write
    does."""
    from app.models.platform.auth_session import AuthSession
    from app.services.auth import sessions as session_service

    a = await acting_user()
    old_jwt = get_auth_token(a.user)
    phone = await session_service.create_session(
        session,
        user_id=a.user.id,
        amr=["pwd"],
        satisfied_providers=[],
        install_id=uuid.uuid4(),
    )
    phone_id = phone.session.id
    await session.commit()

    response = await client.patch(
        "/api/v1/me",
        json={
            "password": "brand-new-secret-123",
            "current_password": "testpassword123",
        },
        headers={"Authorization": f"Bearer {old_jwt}"},
    )
    assert response.status_code == 200

    # The pre-change JWT is rejected (token_version bumped).
    stale = await client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {old_jwt}"},
    )
    assert stale.status_code == 401

    # The phone's session was ended too.
    session.expire_all()
    ended = await session.get(AuthSession, phone_id)
    assert ended is not None
    assert ended.revoked_at is not None


async def test_deletion_eligibility_surfaces_the_services_answer(client, acting_user):
    """The endpoint hands back the verdict and what is behind it. What makes a
    community's sole seat is proved at the service
    (``app/services/platform/users_test.py``); the last platform owner is
    answered here as the delete route refuses it."""
    a = await acting_user(guild_role=CommunityRole.member)

    response = await client.get("/api/v1/me/deletion-eligibility", headers=a.headers)

    assert response.status_code == 200
    body = response.json()
    assert body["can_delete"] is True
    assert body["last_owner"] is False
    assert body["sole_superadmin_communities"] == []

    owner = await acting_user("owner")
    alone = await client.get("/api/v1/me/deletion-eligibility", headers=owner.headers)
    assert alone.status_code == 200
    assert alone.json()["can_delete"] is False
    assert alone.json()["last_owner"] is True


async def test_delete_user_as_admin(client, session, acting_user, monkeypatch):
    """A guild admin removes a member from the guild the way leaving removes
    them: billing hears of it, the member's account stream is told their
    memberships changed, and their contact channels are re-tested. The
    member's platform role plays no part: here they are the platform owner."""
    from app.services.platform import account_stream
    from app.services.platform import contact_grants as contact_grants_service
    from app.testing.billing_boundary import change_rows
    from app.testing.billing_managed import billing_manages_plans

    admin = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(
        "owner", guild_role=CommunityRole.member, guild=admin.guild
    )
    guild_id, member_id = admin.guild.id, member.user.id
    signalled: list[tuple[int | None, str]] = []
    swept: list[int | None] = []
    monkeypatch.setattr(
        account_stream,
        "queue_account_signal",
        lambda _session, user_id, action="changed": signalled.append((user_id, action)),
    )
    monkeypatch.setattr(
        contact_grants_service,
        "queue_stale_grant_sweep",
        lambda _session, user_id: swept.append(user_id),
    )

    async with billing_manages_plans(session):
        response = await client.delete(
            admin.g(f"/users/{member_id}"), headers=admin.headers
        )
        assert response.status_code == 204
        session.expire_all()
        assert await session.get(GuildMembership, (guild_id, member_id)) is None
        # Billing is told the count changed; it is counted when served.
        assert await change_rows(session, guild_id, kinds=("community.members",)) == [
            ("community.members", {})
        ]
    assert signalled == [(member_id, "membership")]
    assert swept == [member_id]


async def test_user_cannot_update_email_via_patch(client, acting_user):
    """Test that users cannot change their email via PATCH /me."""
    a = await acting_user(email="original@example.com")

    response = await client.patch(
        "/api/v1/me",
        headers=a.headers,
        json={"email": "hacked@example.com"},
    )

    # Should succeed but email should not change
    assert response.status_code == 200
    assert response.json()["email"] == "original@example.com"


async def test_user_can_change_password(client, acting_user):
    """Changing your own password is confirmed with the current one."""
    a = await acting_user()

    # Missing current password is refused.
    missing = await client.patch(
        "/api/v1/me",
        headers=a.headers,
        json={"password": "newpassword123"},
    )
    assert missing.status_code == 400
    assert missing.json()["detail"] == "USER_CURRENT_PASSWORD_REQUIRED"

    # Wrong current password is refused.
    wrong = await client.patch(
        "/api/v1/me",
        headers=a.headers,
        json={"password": "newpassword123", "current_password": "not-it"},
    )
    assert wrong.status_code == 400
    assert wrong.json()["detail"] == "USER_CURRENT_PASSWORD_INCORRECT"

    # Correct current password succeeds.
    ok = await client.patch(
        "/api/v1/me",
        headers=a.headers,
        json={"password": "newpassword123", "current_password": "testpassword123"},
    )
    assert ok.status_code == 200


async def test_changing_a_password_records_when_it_was_set(
    client, session, acting_user
):
    a = await acting_user()
    a.user.password_set_at = None
    session.add(a.user)
    await session.commit()
    user_id = a.user.id

    response = await client.patch(
        "/api/v1/me",
        headers=a.headers,
        json={
            "current_password": "testpassword123",
            "password": "a-new-and-longer-secret-1",
        },
    )
    assert response.status_code == 200

    session.expire_all()
    refreshed = await session.get(User, user_id)
    assert refreshed.password_set_at is not None


async def test_inactive_user_cannot_access_endpoints(client, acting_user):
    """Test that inactive users cannot access protected endpoints."""
    a = await acting_user(status=UserStatus.deactivated)

    response = await client.get("/api/v1/me", headers=a.headers)

    # Should be rejected because user is inactive
    assert response.status_code == 400
    assert "inactive" in response.json()["detail"].lower()


@pytest.mark.parametrize(
    ("payload", "accepted", "in_detail"),
    [
        pytest.param(
            {"timezone": "Invalid/Timezone"}, (400,), "timezone", id="not-a-timezone"
        ),
        pytest.param({"week_starts_on": 7}, (400, 422), None, id="weekday-outside-0-6"),
    ],
)
async def test_a_setting_outside_its_range_is_refused(
    client, acting_user, payload, accepted, in_detail
):
    """A timezone the library doesn't know and a weekday past Saturday."""
    a = await acting_user()

    response = await client.patch("/api/v1/me", headers=a.headers, json=payload)

    assert response.status_code in accepted
    if in_detail:
        assert in_detail in response.json()["detail"].lower()


async def test_time_format_round_trip(client, acting_user):
    """Each clock convention round-trips, and a new account answers "system"."""
    a = await acting_user()

    me = await client.get("/api/v1/me", headers=a.headers)
    assert me.status_code == 200
    assert me.json()["time_format"] == "system"

    for value in ("12", "24", "system"):
        response = await client.patch(
            "/api/v1/me", headers=a.headers, json={"time_format": value}
        )
        assert response.status_code == 200, value
        assert response.json()["time_format"] == value


async def test_time_format_rejects_unknown(client, acting_user):
    """A convention the app has no name for never reaches the column."""
    a = await acting_user()

    response = await client.patch(
        "/api/v1/me", headers=a.headers, json={"time_format": "48"}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "USER_INVALID_TIME_FORMAT"


async def test_task_completion_visual_feedback_round_trip(client, acting_user):
    """Each known visual-feedback option round-trips through PATCH /me."""
    a = await acting_user()

    # Default value before any update
    me = await client.get("/api/v1/me", headers=a.headers)
    assert me.status_code == 200
    assert me.json()["task_completion_visual_feedback"] == "none"

    for value in ("confetti", "heart", "d20", "gold_coin", "random", "none"):
        response = await client.patch(
            "/api/v1/me",
            headers=a.headers,
            json={"task_completion_visual_feedback": value},
        )
        assert response.status_code == 200, value
        assert response.json()["task_completion_visual_feedback"] == value


async def test_task_completion_visual_feedback_rejects_unknown(client, acting_user):
    """Unknown values are rejected with 422 so garbage doesn't reach the column."""
    a = await acting_user()

    response = await client.patch(
        "/api/v1/me",
        headers=a.headers,
        json={"task_completion_visual_feedback": "fireworks"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "USER_INVALID_TASK_COMPLETION_VISUAL_FEEDBACK"


async def test_task_completion_audio_and_haptic_round_trip(client, acting_user):
    """Audio + haptic boolean prefs round-trip and default to True."""
    a = await acting_user()

    # Both default to True for new users.
    me = await client.get("/api/v1/me", headers=a.headers)
    assert me.status_code == 200
    body = me.json()
    assert body["task_completion_audio_feedback"] is True
    assert body["task_completion_haptic_feedback"] is True

    # Toggle both off, then both on.
    for value in (False, True):
        response = await client.patch(
            "/api/v1/me",
            headers=a.headers,
            json={
                "task_completion_audio_feedback": value,
                "task_completion_haptic_feedback": value,
            },
        )
        assert response.status_code == 200, value
        result = response.json()
        assert result["task_completion_audio_feedback"] is value
        assert result["task_completion_haptic_feedback"] is value


async def test_smart_task_titles_round_trip(client, acting_user):
    """Reading a new task's title is on until the account turns it off."""
    a = await acting_user()

    me = await client.get("/api/v1/me", headers=a.headers)
    assert me.status_code == 200
    assert me.json()["smart_task_titles"] is True

    for value in (False, True):
        response = await client.patch(
            "/api/v1/me", headers=a.headers, json={"smart_task_titles": value}
        )
        assert response.status_code == 200, value
        assert response.json()["smart_task_titles"] is value

    # Left out of a write, it stays as it was.
    await client.patch(
        "/api/v1/me", headers=a.headers, json={"smart_task_titles": False}
    )
    response = await client.patch(
        "/api/v1/me", headers=a.headers, json={"locale": "en"}
    )
    assert response.json()["smart_task_titles"] is False


def _parse_csv(body: bytes) -> tuple[list[str], list[list[str]]]:
    """Strip the UTF-8 BOM and parse the CSV body into (headers, rows)."""
    import csv
    import io

    text = body.decode("utf-8")
    if text.startswith("﻿"):
        text = text[1:]
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    return rows[0], rows[1:]


#: Ids no account in the fixture below has.
_NO_SUCH_USER = {"missing": 99998, "gone": 99999}


@pytest.fixture
async def csv_guild(acting_user):
    """A guild with an admin and two members to export, plus somebody who
    belongs to a different guild."""
    admin = await acting_user(guild_role=CommunityRole.admin)
    return {
        "admin": admin,
        "one": await acting_user(guild=admin.guild),
        "two": await acting_user(guild=admin.guild),
        "outsider": await acting_user(guild_role=CommunityRole.member),
    }


def _export_id(members: dict, name: str) -> int:
    return _NO_SUCH_USER.get(name) or members[name].user.id


async def test_export_users_csv_as_admin(client, session, csv_guild):
    """A guild admin exports its members: a BOM'd CSV attachment carrying one
    row per member of this guild it lists, each named by handle."""
    admin = csv_guild["admin"]
    suspended = await session.get(User, csv_guild["two"].user.id)
    suspended.status = UserStatus.suspended
    session.add(suspended)
    await session.commit()

    response = await client.get(admin.g("/users/export.csv"), headers=admin.headers)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=" in response.headers["content-disposition"]
    assert response.content.startswith("﻿".encode("utf-8"))

    header_row, data_rows = _parse_csv(response.content)
    # No platform tier and no verification state: both are the platform's
    # business rather than this guild's.
    assert header_row == [
        "user_id",
        "handle",
        "display_name",
        "community_role",
        "oidc_managed",
        "status",
        "created_at",
        "initiative_roles",
    ]
    assert {row[1] for row in data_rows} == {
        f"{who.user.username}#{who.user.discriminator:04d}"
        for who in (admin, csv_guild["one"])
    }
    # No address anywhere in the file.
    assert not any("@" in cell for row in data_rows for cell in row)


@pytest.mark.parametrize(
    ("ask", "expect"),
    [
        pytest.param(["one"], ["one"], id="one-id-is-that-member"),
        pytest.param(["one", "two"], ["one", "two"], id="two-ids-are-both-of-them"),
        pytest.param(["one", "missing"], ["one"], id="an-id-that-is-nobody-is-dropped"),
        pytest.param(["missing", "gone"], [], id="no-id-resolves-so-there-is-no-file"),
        pytest.param(["outsider"], [], id="an-id-outside-the-guild-resolves-to-nobody"),
    ],
)
async def test_export_users_csv_returns_the_members_it_was_asked_for(
    client, csv_guild, ask, expect
):
    """``user_id`` narrows the export to the members it names, and a name only
    resolves from inside the guild. A request that resolves to nobody is a 404;
    one that resolves to a single member is filed under them, and any wider
    export under the guild."""
    admin = csv_guild["admin"]
    query = "&".join(f"user_id={_export_id(csv_guild, name)}" for name in ask)

    response = await client.get(
        f"{admin.g('/users/export.csv')}?{query}", headers=admin.headers
    )

    if not expect:
        assert response.status_code == 404
        return

    assert response.status_code == 200
    _, data_rows = _parse_csv(response.content)
    assert {row[0] for row in data_rows} == {
        str(csv_guild[name].user.id) for name in expect
    }

    disposition = response.headers["content-disposition"]
    if len(expect) == 1:
        only = csv_guild[expect[0]].user
        assert f"user-{only.id}-{only.username}" in disposition
        assert data_rows[0][1] == f"{only.username}#{only.discriminator:04d}"
    else:
        assert "-users-" in disposition


async def test_password_change_keeps_this_device_signed_in(client, session):
    """Changing the password revokes every other session, but THIS device gets
    a fresh server-side session: both cookies are re-issued, the new refresh
    chain rotates, and it claims the password just re-checked and no
    provider's sign-in. A change sent with another field is refused and leaves
    the password and the sessions as they were."""
    from app.models.platform.auth_session import AuthSession

    user = await create_user(session, email="pwkeep@example.com")
    user_id = user.id

    login = await client.post(
        "/api/v1/auth/token",
        data={"username": "pwkeep@example.com", "password": "testpassword123"},
    )
    assert login.status_code == 200
    await session.exec(
        update(AuthSession)
        .where(AuthSession.user_id == user_id)
        .values(satisfied_providers=[7])
    )
    await session.commit()

    refused = await client.patch(
        "/api/v1/me",
        json={
            "password": "newpassword456",
            "current_password": "testpassword123",
            "locale": "fr",
        },
    )
    assert refused.status_code == 422
    assert refused.json()["detail"][0]["msg"].endswith("USER_PASSWORD_CHANGED_ALONE")
    assert not refused.cookies.get("refresh_token")

    change = await client.patch(
        "/api/v1/me",
        json={"password": "newpassword456", "current_password": "testpassword123"},
    )
    assert change.status_code == 200
    assert change.cookies.get("refresh_token")  # fresh chain for this device
    assert change.json()["has_password"] is True

    session.expire_all()
    live = (
        await session.exec(
            select(AuthSession).where(
                AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
            )
        )
    ).all()
    assert [(row.amr, row.satisfied_providers) for row in live] == [(["pwd"], [])]

    rotated = await client.post("/api/v1/auth/refresh")
    assert rotated.status_code == 200
    me = await client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {rotated.json()['access_token']}"},
    )
    assert me.status_code == 200


async def test_a_password_change_that_cannot_open_a_session_is_refused(
    client, session, monkeypatch
):
    """The change keeps this device signed in by opening a fresh session. With
    no session to open the request ends there — signing in again is the way
    back, and it is the same session store either way."""
    await create_user(session, email="pwfall@example.com")

    login = await client.post(
        "/api/v1/auth/token",
        data={"username": "pwfall@example.com", "password": "testpassword123"},
    )
    assert login.status_code == 200
    assert login.cookies.get("refresh_token")

    async def _boom(*args, **kwargs):
        raise RuntimeError("session store down")

    monkeypatch.setattr("app.services.auth.sessions.create_session", _boom)

    change = await client.patch(
        "/api/v1/me",
        json={"password": "newpassword456", "current_password": "testpassword123"},
    )
    assert change.status_code == 503
    assert change.json()["detail"] == "SESSION_STORE_UNAVAILABLE"

    # The revocations were staged alongside the replacement, so the account
    # still holds what it had. The session opened before the attempt is the
    # thing to ask: it rotates, which it could not do if its chain had been
    # revoked on its own. Signing in afresh would pass either way.
    monkeypatch.undo()
    refreshed = await client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200, refreshed.text

    # And the password is the one it always was.
    again = await client.post(
        "/api/v1/auth/token",
        data={"username": "pwfall@example.com", "password": "testpassword123"},
    )
    assert again.status_code == 200


async def test_users_me_reports_linked_identity(client, session, acting_user):
    """/me carries has_federated_identity — the signal the profile and
    deletion dialogs use to hide the password confirmation for SSO accounts."""
    linked = await acting_user()
    await create_federated_identity(session, linked.user)
    plain = await acting_user()

    response = await client.get("/api/v1/me", headers=linked.headers)
    assert response.status_code == 200
    assert response.json()["has_federated_identity"] is True

    response = await client.get("/api/v1/me", headers=plain.headers)
    assert response.status_code == 200
    assert response.json()["has_federated_identity"] is False


async def test_updating_yourself_reports_your_own_linked_identity(
    client, session, acting_user
):
    """PATCH /me reads the caller's own identity links on their platform
    tier and carries the answer back, for an empty update and a real one."""
    linked = await acting_user()
    await create_federated_identity(session, linked.user)
    plain = await acting_user()

    for body in ({}, {"timezone": "Europe/Berlin"}):
        response = await client.patch("/api/v1/me", headers=linked.headers, json=body)
        assert response.status_code == 200, response.text
        assert response.json()["has_federated_identity"] is True

    response = await client.patch(
        "/api/v1/me", headers=plain.headers, json={"timezone": "Europe/Berlin"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["has_federated_identity"] is False


async def _just_signed_in(session: AsyncSession, user: User) -> dict[str, str]:
    """Headers naming a session row opened a moment ago — what an account with
    no password to re-check answers a confirmation with."""
    from app.services.auth import sessions as session_service

    issued = await session_service.create_session(
        session, user_id=user.id, amr=["webauthn"], satisfied_providers=[]
    )
    await session.commit()
    return {
        "Authorization": "Bearer "
        + get_auth_token(user, session_id=issued.session.id, amr=["webauthn"])
    }


async def test_oidc_user_can_self_delete_without_password(client, session):
    """An SSO-provisioned account holds no usable password, so there is none
    for the gate to ask for: it deletes with the confirmation phrase alone."""
    user = await create_user(session, hashed_password=None)
    await create_federated_identity(session, user, subject="oidc-subject-123")

    response = await client.post(
        "/api/v1/me/delete-account",
        headers=await _just_signed_in(session, user),
        json={
            "action": "soft_delete",
            "password": "",
            "confirmation_text": "DELETE MY ACCOUNT",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["action"] == "soft_delete"


async def test_a_passkey_only_account_can_self_delete_without_a_password(
    client, session
):
    """The account signs in with a credential and holds no password at all.
    What it is asked for is the phrase."""
    user = await create_user(session, hashed_password=None)
    session.add(
        UserPasskey(
            user_id=user.id,
            credential_id=b"delete-account-key",
            public_key=b"public-key-bytes",
            rp_id="localhost",
            sign_count=0,
            transports=["internal"],
            name="Laptop",
        )
    )
    await session.commit()

    response = await client.post(
        "/api/v1/me/delete-account",
        headers=await _just_signed_in(session, user),
        json={
            "action": "soft_delete",
            "password": "",
            "confirmation_text": "DELETE MY ACCOUNT",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["action"] == "soft_delete"


@pytest.mark.parametrize(
    "linked", [False, True], ids=["a-password-account", "one-with-an-identity-linked"]
)
async def test_self_delete_asks_a_password_account_for_its_password(
    client, session, acting_user, linked
):
    """An account that holds a password confirms with it. An identity link is
    not the question — an account can hold both. The answer is 400, not 401:
    the caller is signed in, and it is the password they typed that is wrong.
    """
    # A plain account, so the answer is about the password and nothing else:
    # the last holder of a platform capability is stopped a step earlier.
    a = await acting_user("member")
    if linked:
        await create_federated_identity(session, a.user, subject="linked-local-1")

    response = await client.post(
        "/api/v1/me/delete-account",
        headers=a.headers,
        json={
            "action": "soft_delete",
            "password": "wrong-password",
            "confirmation_text": "DELETE MY ACCOUNT",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "USER_INVALID_PASSWORD"


async def test_profile_carries_the_basics(client, session, acting_user):
    """A profile: the handle, the face, the line they wrote, the look they
    picked, and when they joined.

    The handle is the name here, and the page is the same one for everyone, so
    it carries nothing a guild decides the visibility of — the name somebody
    set in a guild included.
    """
    caller = await acting_user()
    subject = await create_user(
        session,
        username="tinker",
        avatar_url="https://example.com/tinker.png",
        custom_status={"emoji": "\N{GAME DIE}", "text": "rolling for initiative"},
        profile_decorations={"banner": "core.aurora", "trophies": ["core.fan"]},
    )

    response = await client.get(_profile_url(subject), headers=caller.headers)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == subject.id
    assert body["username"] == "tinker"
    assert body["avatar_url"] == "https://example.com/tinker.png"
    assert body["custom_status"] == {
        "emoji": "\N{GAME DIE}",
        "text": "rolling for initiative",
    }
    assert body["profile_decorations"] == {
        "banner": "core.aurora",
        "frame_tint": [],
        "grad_year": None,
        "frame": None,
        "trophies": ["core.fan"],
    }
    assert body["presence"] == "offline"
    assert body["joined_at"]
    # Nothing the account keeps to itself.
    assert set(body.keys()) == {
        "id",
        "username",
        "discriminator",
        "avatar_url",
        "status",
        "custom_status",
        "profile_decorations",
        "presence",
        "joined_at",
    }


async def test_profile_hides_a_suspended_account(client, session, acting_user):
    """A suspended account vanishes from rosters, and from the page they lead
    to."""
    caller = await acting_user()
    subject = await create_user(session, status=UserStatus.suspended)

    response = await client.get(_profile_url(subject), headers=caller.headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "USER_NOT_FOUND"


async def _open_guild_events(session: AsyncSession, subject: User):
    """A tab sitting inside a guild. Returns how to close it."""
    guild = await create_guild(session)
    await create_guild_membership(session, user=subject, guild=guild)
    socket = FakeWebSocket()
    watch_events_bus(guild.id, [], socket, user_id=subject.id)

    async def close() -> None:
        content_sockets.leave(socket)  # type: ignore[arg-type]

    return close


async def _open_notification_stream(session: AsyncSession, subject: User):
    """A tab anywhere in the app: the bell has no guild in its address."""
    socket = open_account_socket(subject.id)

    async def close() -> None:
        content_sockets.leave(socket)  # type: ignore[arg-type]

    return close


@pytest.mark.parametrize(
    "open_socket",
    [_open_guild_events, _open_notification_stream],
    ids=["a-guild-events-socket", "the-notification-stream"],
)
async def test_profile_says_when_someone_is_online(
    client, session, acting_user, open_socket
):
    """How someone appears is a fact about the person, not about a guild: a
    reader who shares no guild with them still sees it, and every channel a tab
    can hold open answers for it — including the notification stream, which is
    the only one open while a tab sits outside a guild. It reads offline again
    once the socket closes.
    """
    caller = await acting_user()
    subject = await create_user(session)

    close = await open_socket(session, subject)
    try:
        response = await client.get(_profile_url(subject), headers=caller.headers)
    finally:
        await close()

    assert response.status_code == 200
    assert response.json()["presence"] == "online"

    after = await client.get(_profile_url(subject), headers=caller.headers)
    assert after.json()["presence"] == "offline"


async def test_profile_stays_online_while_any_socket_is_open(
    client, session, acting_user
):
    """Two channels feed one roll, so closing one tab does not sign the other
    one out."""
    caller = await acting_user()
    subject = await create_user(session)
    guild = await create_guild(session)
    await create_guild_membership(session, user=subject, guild=guild)

    bell, events = open_account_socket(subject.id), FakeWebSocket()
    watch_events_bus(guild.id, [], events, user_id=subject.id)
    try:
        content_sockets.leave(events)  # type: ignore[arg-type]
        response = await client.get(_profile_url(subject), headers=caller.headers)
    finally:
        content_sockets.leave(bell)  # type: ignore[arg-type]

    assert response.json()["presence"] == "online"


@pytest.mark.parametrize("chosen", ["idle", "busy", "offline"])
async def test_profile_shows_what_someone_picked(
    client, session, acting_user, chosen: str
):
    """Each is shown as itself rather than flattened to online — the choice to
    appear offline included, which holds with a tab open."""
    caller = await acting_user()
    subject = await create_user(session)

    socket = open_account_socket(subject.id, chosen_presence=Presence(chosen))
    try:
        response = await client.get(_profile_url(subject), headers=caller.headers)
    finally:
        content_sockets.leave(socket)  # type: ignore[arg-type]

    assert response.json()["presence"] == chosen


async def test_presence_change_reaches_readers_without_a_reconnect(client, acting_user):
    """The socket carried the old choice; setting a new one is followed live."""
    caller = await acting_user()
    subject = await acting_user()
    profile_url = _profile_url(subject.user)

    socket = open_account_socket(subject.user.id)
    try:
        assert (await client.get(profile_url, headers=caller.headers)).json()[
            "presence"
        ] == "online"

        saved = await client.patch(
            "/api/v1/me",
            headers=subject.headers,
            json={"presence": "offline"},
        )
        assert saved.status_code == 200
        assert saved.json()["presence"] == "offline"

        assert (await client.get(profile_url, headers=caller.headers)).json()[
            "presence"
        ] == "offline"
    finally:
        content_sockets.leave(socket)  # type: ignore[arg-type]


async def test_presence_outlives_the_socket_that_set_it(client, session, acting_user):
    """The choice is a column, so a new tab appears the way the last one did."""
    caller = await acting_user()
    subject = await acting_user()

    saved = await client.patch(
        "/api/v1/me",
        headers=subject.headers,
        json={"presence": "busy"},
    )
    assert saved.status_code == 200

    await session.refresh(subject.user)
    socket = open_account_socket(subject.user.id, chosen_presence=subject.user.presence)
    try:
        response = await client.get(_profile_url(subject.user), headers=caller.headers)
    finally:
        content_sockets.leave(socket)  # type: ignore[arg-type]

    assert response.json()["presence"] == "busy"


async def test_presence_rejects_a_value_that_is_not_one(client, acting_user):
    a = await acting_user()

    response = await client.patch(
        "/api/v1/me",
        headers=a.headers,
        json={"presence": "invisible"},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("username", "discriminator", "handle"),
    [
        pytest.param("jordan", 1234, "jordan1234", id="a-name-and-its-four-digits"),
        pytest.param("user2", 7, "user20007", id="a-name-that-ends-in-a-digit"),
    ],
)
async def test_profile_is_addressed_by_handle(
    client, session, acting_user, username, discriminator, handle
):
    """``jordan1234`` is the handle as one URL segment — the name and the four
    digits it is always written with, run together, because ``#`` never
    survives a URL. The number is always four wide, which is what keeps
    ``user2`` + ``0007`` from reading as ``user`` + ``20007``."""
    caller = await acting_user()
    subject = await create_user(session, username=username, discriminator=discriminator)

    response = await client.get(
        f"/api/v1/users/{handle}/profile", headers=caller.headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == subject.id
    assert body["username"] == username
    assert body["discriminator"] == discriminator


@pytest.mark.parametrize("handle", ["jordan", "jordan12a4", "ab0001", "jordan1234x"])
async def test_profile_404s_on_something_that_is_not_a_handle(
    client, acting_user, handle: str
):
    """No number, a number with a letter in it, too short a name, and a name
    where the number should be."""
    caller = await acting_user()

    response = await client.get(
        f"/api/v1/users/{handle}/profile", headers=caller.headers
    )

    assert response.status_code == 404


async def test_custom_status_round_trips_as_one_object(client, acting_user):
    """One column, one write: the emoji and the line are set together."""
    a = await acting_user()

    response = await client.patch(
        "/api/v1/me",
        headers=a.headers,
        json={"custom_status": {"emoji": "\N{ROCKET}", "text": "  shipping  "}},
    )

    assert response.status_code == 200
    assert response.json()["custom_status"] == {
        "emoji": "\N{ROCKET}",
        "text": "shipping",
    }

    cleared = await client.patch(
        "/api/v1/me", headers=a.headers, json={"custom_status": None}
    )

    assert cleared.status_code == 200
    assert cleared.json()["custom_status"] == {"emoji": None, "text": None}


async def test_custom_status_holds_the_line_to_its_length(client, acting_user):
    """A status is a line, so the longest one it takes is a short one."""
    a = await acting_user()

    at_the_bound = await client.patch(
        "/api/v1/me",
        headers=a.headers,
        json={"custom_status": {"text": "x" * STATUS_TEXT_MAX_LENGTH}},
    )

    assert at_the_bound.status_code == 200

    over_it = await client.patch(
        "/api/v1/me",
        headers=a.headers,
        json={"custom_status": {"text": "x" * (STATUS_TEXT_MAX_LENGTH + 1)}},
    )

    assert over_it.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"custom_status": {"emoji": "not an emoji"}},
        {"custom_status": {"mood": "chipper"}},
        {"profile_decorations": {"banner": "../../etc/passwd"}},
        {"profile_decorations": {"hat": "core.aurora"}},
        {"profile_decorations": {"trophies": ["a", "b", "c", "d", "e", "f", "g"]}},
        {"profile_decorations": {"frame": "core.gold", "frame_tint": ["puce"]}},
    ],
)
async def test_profile_writes_reject_a_shape_that_is_not_the_shape(
    client, acting_user, payload: dict
):
    """Text where an emoji goes, a key nothing wears, a path where an id goes,
    more trophies than a profile has room for, and a colour that is not one."""
    a = await acting_user()

    response = await client.patch("/api/v1/me", headers=a.headers, json=payload)

    assert response.status_code == 422


async def test_library_lists_what_ships_with_the_app(client, acting_user):
    """A fresh account has the shipped set and nothing else, and none of it
    names a pack — nobody granted it."""
    a = await acting_user()

    response = await client.get("/api/v1/me/decorations", headers=a.headers)

    assert response.status_code == 200
    items = response.json()["items"]
    assert {item["id"] for item in items} == set(SHIPPED_DECORATIONS)
    assert all(item["source"] is None for item in items)
    assert {item["kind"] for item in items} == {"banner", "frame", "trophy"}


async def test_library_carries_what_a_pack_granted(client, session, acting_user):
    """An acquired decoration joins the shipped set and says where it came
    from, so a picker can group by pack — and somebody else's acquisitions are
    not in it."""
    a = await acting_user()
    other = await create_user(session)
    session.add(
        UserDecoration(
            user_id=a.user.id,
            decoration_id="pack.midnight",
            kind="banner",
            source="studio.midnight-pack",
        )
    )
    session.add(
        UserDecoration(user_id=other.id, decoration_id="pack.elsewhere", kind="banner")
    )
    await session.commit()

    response = await client.get("/api/v1/me/decorations", headers=a.headers)

    assert response.status_code == 200
    items = response.json()["items"]
    granted = next(item for item in items if item["id"] == "pack.midnight")
    assert granted == {
        "id": "pack.midnight",
        "kind": "banner",
        # No listing behind this row in this test, so no name to carry.
        "name": None,
        "source": "studio.midnight-pack",
        # Nor a picture of its own.
        "image_url": None,
    }
    assert len(items) == len(SHIPPED_DECORATIONS) + 1
    assert "pack.elsewhere" not in {item["id"] for item in items}


@pytest.mark.parametrize(
    ("worn", "on_the_shelf"),
    [
        pytest.param(
            {"banner": "pack.midnight"}, False, id="a-decoration-nobody-granted"
        ),
        pytest.param(
            {"banner": "core.gold"}, False, id="a-shipped-frame-in-the-banner-slot"
        ),
        pytest.param(
            {"trophies": ["tt.trophy"]}, True, id="a-pack-in-the-store-never-taken"
        ),
    ],
)
async def test_you_wear_what_you_have(client, session, acting_user, worn, on_the_shelf):
    """You wear what you have, in the slot you have it for: a decoration
    nobody granted, a frame worn as a banner, and a pack that is on the shelf
    but not in this library."""
    a = await acting_user()
    if on_the_shelf:
        await create_profile_pack(session, uid="PACKTABTP00001", slug="tt")

    response = await client.patch(
        "/api/v1/me",
        headers=a.headers,
        json={"profile_decorations": worn},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "USER_DECORATION_NOT_OWNED"


async def test_wearing_what_a_pack_granted(client, session, acting_user):
    """The acquired half of the library is wearable on the same terms as the
    shipped half."""
    a = await acting_user()
    session.add(
        UserDecoration(
            user_id=a.user.id,
            decoration_id="pack.midnight",
            kind="banner",
            source="studio.midnight-pack",
        )
    )
    await session.commit()

    response = await client.patch(
        "/api/v1/me",
        headers=a.headers,
        json={
            "profile_decorations": {
                "banner": "pack.midnight",
                "frame": "core.gold",
                "trophies": ["core.fan", "core.fan"],
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["profile_decorations"] == {
        "banner": "pack.midnight",
        "frame": "core.gold",
        "frame_tint": [],
        "grad_year": None,
        # The same trophy twice is a duplicate, not a second trophy.
        "trophies": ["core.fan"],
    }


@pytest.mark.parametrize(
    ("frame", "tint", "kept"),
    [
        pytest.param("core.gold", ["#AA0011", "#223344"], ["#aa0011"], id="one-colour"),
        pytest.param("pack.ironwork", ["#AA0011"], [], id="no-colour"),
    ],
)
async def test_a_frame_keeps_as_many_colours_as_it_takes(
    client, session, acting_user, frame, tint, kept
):
    """The colours a wearer picks are stored beside the frame they picked them
    for: each frame keeps as many as it takes, and the frame worn before it
    leaves none of its own behind. Every frame that ships takes at least one,
    so the frame that takes none is one a pack granted."""
    a = await acting_user()
    session.add(
        UserDecoration(
            user_id=a.user.id,
            decoration_id="pack.ironwork",
            kind="frame",
            source="studio.ironwork-pack",
        )
    )
    await session.commit()

    # A frame that takes two, wearing two.
    primed = await client.patch(
        "/api/v1/me",
        headers=a.headers,
        json={
            "profile_decorations": {
                "frame": "core.split",
                "frame_tint": ["#1B5E32", "#F2C230"],
            }
        },
    )
    assert primed.status_code == 200
    assert primed.json()["profile_decorations"]["frame_tint"] == [
        "#1b5e32",
        "#f2c230",
    ]

    response = await client.patch(
        "/api/v1/me",
        headers=a.headers,
        json={"profile_decorations": {"frame": frame, "frame_tint": tint}},
    )

    assert response.status_code == 200
    assert response.json()["profile_decorations"]["frame_tint"] == kept


async def test_a_pack_that_grew_gives_the_new_piece_to_whoever_has_it(
    client, session, acting_user
):
    """A pack is not frozen at the moment it was installed: what it carries is
    the catalog's answer, and a piece added in a later version is in the library
    on the next read rather than only for whoever installs it after today."""
    a = await acting_user()
    listing = await create_profile_pack(
        session, uid="PACKGREW000001", public_id="studio.grew", slug="grew"
    )
    pack = await profile_decorations_service.pack_by_uid(session, listing.uid)
    await profile_decorations_service.install_pack(
        session, user_id=a.user.id, pack=pack
    )

    # The pack publishes a version with one more piece in it.
    await marketplace_catalog.upsert_listing(
        session,
        {
            "uid": listing.uid,
            "public_id": listing.public_id,
            "kind": "profile_pack",
            "name": listing.name,
            "publisher": "Studio",
            "description": listing.description,
            "version": "2.0.0",
            "definition": {
                "schema_version": 1,
                "kind": "profile_pack",
                "decorations": [
                    {"id": "grew.banner", "slot": "banner", "name": "A banner"},
                    {"id": "grew.frame", "slot": "frame", "name": "A frame"},
                    {"id": "grew.trophy", "slot": "trophy", "name": "A trophy"},
                    {"id": "grew.later", "slot": "trophy", "name": "Added later"},
                ],
            },
        },
        source="builtin",
    )
    await session.commit()

    response = await client.get("/api/v1/me/decorations", headers=a.headers)

    assert response.status_code == 200
    held = {item["id"] for item in response.json()["items"]}
    assert "grew.later" in held


async def test_decoration_packs_list_the_store(client, session, acting_user):
    """The shelf is the marketplace catalog: a pack is a listing, named by its
    publisher and identified by the uid a granted row records."""
    a = await acting_user()
    listing = await create_profile_pack(session, uid="PACKTABTP00001", slug="tt")

    response = await client.get("/api/v1/me/decoration-packs", headers=a.headers)

    assert response.status_code == 200
    entry = next(
        item for item in response.json()["items"] if item["uid"] == listing.uid
    )
    assert entry["installed"] is False
    assert entry["public_id"] == listing.public_id
    assert entry["name"] == listing.name
    assert entry["publisher"] == listing.publisher
    # A pack is a set you take together: one of each slot.
    assert {content["kind"] for content in entry["contents"]} == {
        "banner",
        "frame",
        "trophy",
    }
    assert all(content["source"] == listing.uid for content in entry["contents"])


async def test_the_shipped_packs_are_on_the_shelf(client, session, acting_user):
    """The packs this build ships reach the store the way any listing does —
    through the catalog, seeded from their manifests."""
    a = await acting_user()
    for manifest in load_builtin_manifests():
        if manifest.get("kind") == "profile_pack":
            await marketplace_catalog.upsert_listing(
                session, manifest, source="builtin"
            )
    await session.commit()

    response = await client.get("/api/v1/me/decoration-packs", headers=a.headers)

    assert response.status_code == 200
    shipped = {item["public_id"] for item in response.json()["items"]}
    assert {"core.gaming", "core.soundcheck", "core.observatory"} <= shipped


async def test_installing_a_pack_puts_it_in_the_library(client, session, acting_user):
    """What the store grants is what the pickers then offer, and what the
    profile may then wear — the whole point of taking one."""
    a = await acting_user()
    listing = await create_profile_pack(session, uid="PACKTABTP00001", slug="tt")

    install = await client.post(
        f"/api/v1/me/decoration-packs/{listing.uid}", headers=a.headers
    )

    assert install.status_code == 200
    assert install.json()["installed"] is True

    library = await client.get("/api/v1/me/decorations", headers=a.headers)
    owned = {item["id"]: item for item in library.json()["items"]}
    assert owned["tt.trophy"]["kind"] == "trophy"
    # The grant records the listing uid — the one name for this pack anywhere.
    assert owned["tt.trophy"]["source"] == listing.uid

    listed = await client.get("/api/v1/me/decoration-packs", headers=a.headers)
    installed = {item["uid"] for item in listed.json()["items"] if item["installed"]}
    assert installed == {listing.uid}

    worn = await client.patch(
        "/api/v1/me",
        headers=a.headers,
        json={
            "profile_decorations": {
                "banner": "tt.banner",
                "frame": "tt.frame",
                "trophies": ["tt.trophy"],
            }
        },
    )
    assert worn.status_code == 200
    assert worn.json()["profile_decorations"]["trophies"] == ["tt.trophy"]


async def test_installing_a_pack_twice_changes_nothing(client, session, acting_user):
    """A second click on a slow connection is not a second copy."""
    a = await acting_user()
    listing = await create_profile_pack(session, uid="PACKBAND000001", slug="mu")

    for _ in range(2):
        assert (
            await client.post(
                f"/api/v1/me/decoration-packs/{listing.uid}", headers=a.headers
            )
        ).status_code == 200

    library = await client.get("/api/v1/me/decorations", headers=a.headers)
    ids = [item["id"] for item in library.json()["items"]]
    assert ids.count("mu.frame") == 1


async def test_removing_a_pack_takes_off_what_was_worn(client, session, acting_user):
    """Giving a pack back undresses the profile of its pieces, and leaves
    another pack's alone."""
    a = await acting_user()
    tabletop = await create_profile_pack(session, uid="PACKTABTP00001", slug="tt")
    music = await create_profile_pack(
        session, uid="PACKBAND000001", public_id="test.music", slug="mu"
    )
    for listing in (tabletop, music):
        await client.post(
            f"/api/v1/me/decoration-packs/{listing.uid}", headers=a.headers
        )
    await client.patch(
        "/api/v1/me",
        headers=a.headers,
        json={
            "profile_decorations": {
                "banner": "tt.banner",
                "frame": "mu.frame",
                "trophies": ["tt.trophy", "mu.trophy"],
            }
        },
    )

    removed = await client.delete(
        f"/api/v1/me/decoration-packs/{tabletop.uid}", headers=a.headers
    )

    assert removed.status_code == 200
    assert removed.json()["installed"] is False

    me = await client.get("/api/v1/me", headers=a.headers)
    worn = me.json()["profile_decorations"]
    # The tabletop pieces came off; the other pack's stayed on.
    assert worn["banner"] is None
    assert worn["frame"] == "mu.frame"
    assert worn["trophies"] == ["mu.trophy"]

    library = await client.get("/api/v1/me/decorations", headers=a.headers)
    assert "tt.trophy" not in {item["id"] for item in library.json()["items"]}


async def test_removing_a_pack_leaves_someone_elses_library_alone(
    client, session, acting_user
):
    a = await acting_user()
    other = await acting_user()
    listing = await create_profile_pack(session, uid="PACKTABTP00001", slug="tt")
    for who in (a, other):
        await client.post(
            f"/api/v1/me/decoration-packs/{listing.uid}", headers=who.headers
        )

    await client.delete(f"/api/v1/me/decoration-packs/{listing.uid}", headers=a.headers)

    library = await client.get("/api/v1/me/decorations", headers=other.headers)
    assert "tt.trophy" in {item["id"] for item in library.json()["items"]}


@pytest.mark.parametrize(
    "other_kind",
    [False, True],
    ids=["a-uid-that-names-nothing", "a-uid-that-names-another-kind"],
)
async def test_installing_something_that_is_not_a_pack_is_a_404(
    client, session, acting_user, other_kind
):
    """A uid names a listing; only a profile pack installs to a person."""
    a = await acting_user()
    uid = "NSCHPACK000001"
    if other_kind:
        uid = (await create_marketplace_listing(session, uid="DASHBRD0000001")).uid

    response = await client.post(
        f"/api/v1/me/decoration-packs/{uid}", headers=a.headers
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "USER_DECORATION_PACK_NOT_FOUND"


async def test_installing_a_pack_survives_two_requests_at_once(session: AsyncSession):
    """Two installs that cannot see each other's rows.

    The real race is two requests in flight together, neither's insert visible
    to the other's read. Calling the service twice before anything is flushed
    reproduces exactly that, deterministically: a read-then-insert would have
    both conclude the same row was missing and collide on the primary key.
    """
    user = await create_user(session)
    listing = await create_profile_pack(session, uid="PACKTABTP00001", slug="tt")
    pack = await profile_decorations_service.pack_by_uid(session, listing.uid)

    assert (
        await profile_decorations_service.install_pack(
            session, user_id=user.id, pack=pack
        )
        == []
    )
    # The second install finds every row already there and attributed to this
    # same pack, which is not a conflict.
    assert (
        await profile_decorations_service.install_pack(
            session, user_id=user.id, pack=pack
        )
        == []
    )
    await session.commit()

    held = (
        await session.exec(
            select(UserDecoration).where(UserDecoration.user_id == user.id)
        )
    ).all()
    assert sorted(row.decoration_id for row in held) == sorted(pack.decorations)


@pytest.fixture
async def wearing_a_pack(session):
    """An account that took the tabletop pack and is wearing its banner and its
    trophy. Yields ``(user_id, pack)`` — the id rather than the instance,
    because a rollback in the test expires every instance.
    """
    user = await create_user(session)
    user_id = user.id
    listing = await create_profile_pack(session, uid="PACKTABTP00001", slug="tt")
    pack = await profile_decorations_service.pack_by_uid(session, listing.uid)
    await profile_decorations_service.install_pack(session, user_id=user_id, pack=pack)
    user.profile_decorations = {
        "banner": "tt.banner",
        "frame": None,
        "trophies": ["tt.trophy"],
    }
    session.add(user)
    await session.commit()
    return user_id, pack


async def test_giving_a_pack_back_is_all_or_nothing(session, wearing_a_pack):
    """The library and the profile move together: rolling back before the
    commit leaves both exactly as they were, which two transactions could not
    do."""
    user_id, pack = wearing_a_pack

    await profile_decorations_service.remove_pack(session, user_id=user_id, pack=pack)
    await session.rollback()

    still_held = (
        await session.exec(
            select(UserDecoration).where(UserDecoration.user_id == user_id)
        )
    ).all()
    fresh = (await session.exec(select(User).where(User.id == user_id))).one()
    assert len(still_held) == len(pack.decorations)
    assert fresh.profile_decorations["banner"] == "tt.banner"


async def test_giving_a_pack_back_reads_what_is_worn_now(session, wearing_a_pack):
    """Undressing works from the value in the database, not one read earlier:
    the read happens inside the transaction, under a row lock, so a look
    changed in between survives minus only the given-back pack's piece."""
    user_id, pack = wearing_a_pack
    music = await create_profile_pack(
        session, uid="PACKBAND000001", public_id="test.music", slug="mu"
    )
    music_pack = await profile_decorations_service.pack_by_uid(session, music.uid)
    await profile_decorations_service.install_pack(
        session, user_id=user_id, pack=music_pack
    )
    await session.commit()

    # Somebody changes their look after that value was last read anywhere.
    await session.exec(
        update(User)
        .where(User.id == user_id)
        .values(
            profile_decorations={
                "banner": "mu.banner",
                "frame": "tt.frame",
                "trophies": ["mu.trophy"],
            }
        )
    )
    await session.commit()

    await profile_decorations_service.remove_pack(session, user_id=user_id, pack=pack)
    await session.commit()

    fresh = (await session.exec(select(User).where(User.id == user_id))).one()
    # The newer choice survived; only the given-back pack's pieces came off.
    assert fresh.profile_decorations["banner"] == "mu.banner"
    assert fresh.profile_decorations["frame"] is None
    assert fresh.profile_decorations["trophies"] == ["mu.trophy"]


async def test_giving_back_an_older_pack_undresses_what_it_gave(
    session, wearing_a_pack
):
    """Install grants what the version of the day lists, so giving the pack
    back takes off what *its rows* gave — not what its current definition
    happens to list."""
    user_id, pack = wearing_a_pack

    # The pack publishes again without the banner it had granted.
    thinner = profile_decorations_service.Pack(
        listing=pack.listing, decorations={"tt.frame": "frame", "tt.trophy": "trophy"}
    )
    await profile_decorations_service.remove_pack(
        session, user_id=user_id, pack=thinner
    )
    await session.commit()

    fresh = (await session.exec(select(User).where(User.id == user_id))).one()
    held = (
        await session.exec(
            select(UserDecoration).where(UserDecoration.user_id == user_id)
        )
    ).all()
    assert held == []
    # The banner came off even though the pack no longer lists it.
    assert fresh.profile_decorations["banner"] is None


async def test_giving_a_pack_back_keeps_what_ships_with_the_app(session: AsyncSession):
    """A pack may include a decoration that also ships. Handing the pack back
    does not take that one off — it was never the pack's to take."""
    user = await create_user(session)
    user_id = user.id
    listing = await create_marketplace_listing(
        session,
        uid="PACKSHPS000001",
        public_id="test.ships",
        kind="profile_pack",
        definition={
            "schema_version": 1,
            "kind": "profile_pack",
            "decorations": [
                {"id": "sh.banner", "slot": "banner", "name": "A banner"},
                {"id": "core.gold", "slot": "frame", "name": "The default frame"},
            ],
        },
    )
    pack = await profile_decorations_service.pack_by_uid(session, listing.uid)
    await profile_decorations_service.install_pack(session, user_id=user_id, pack=pack)
    user.profile_decorations = {
        "banner": "sh.banner",
        "frame": "core.gold",
        "trophies": [],
    }
    session.add(user)
    await session.commit()

    await profile_decorations_service.remove_pack(session, user_id=user_id, pack=pack)
    await session.commit()

    fresh = (await session.exec(select(User).where(User.id == user_id))).one()
    # The pack's own banner comes off; a slot emptied is the default a bare
    # profile has always had.
    assert fresh.profile_decorations["banner"] is None
    # The frame stays: every account has it, pack or no pack.
    assert fresh.profile_decorations["frame"] == "core.gold"


async def test_a_pack_claiming_another_packs_decoration_is_refused(
    client, session, acting_user
):
    """A decoration id names one thing, so a row can only be attributed to one
    pack. The second install says so rather than half-succeeding."""
    a = await acting_user()
    first = await create_profile_pack(session, uid="PACKTABTP00001", slug="tt")
    # A second pack claiming an id the first already grants.
    squatter = await create_marketplace_listing(
        session,
        uid="PACKSQAT000001",
        public_id="test.squatter",
        kind="profile_pack",
        definition={
            "schema_version": 1,
            "kind": "profile_pack",
            "decorations": [
                {"id": "tt.trophy", "slot": "trophy", "name": "Also a trophy"}
            ],
        },
    )
    await client.post(f"/api/v1/me/decoration-packs/{first.uid}", headers=a.headers)

    response = await client.post(
        f"/api/v1/me/decoration-packs/{squatter.uid}", headers=a.headers
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "USER_DECORATION_ALREADY_GRANTED"

    # And the first pack's grant is untouched, still attributed to it.
    library = await client.get("/api/v1/me/decorations", headers=a.headers)
    owned = {item["id"]: item for item in library.json()["items"]}
    assert owned["tt.trophy"]["source"] == first.uid

    listed = await client.get("/api/v1/me/decoration-packs", headers=a.headers)
    installed = {item["uid"] for item in listed.json()["items"] if item["installed"]}
    assert installed == {first.uid}


async def test_member_search_narrows_to_one_initiative(client, acting_user):
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    inside = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    outside = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)

    narrowed = await client.get(
        admin.g("/users/search"),
        headers=admin.headers,
        params={"initiative_id": admin.initiative.id},
    )
    assert narrowed.status_code == 200, narrowed.text
    names = {item["username"] for item in narrowed.json()["items"]}
    assert inside.user.username in names
    assert outside.user.username not in names

    # Somebody outside the initiative cannot list who is in it.
    refused = await client.get(
        outside.g("/users/search"),
        headers=outside.headers,
        params={"initiative_id": admin.initiative.id},
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == "INITIATIVE_NOT_A_MEMBER"


async def test_the_shipped_home_layouts_are_on_the_shelf(client, session, acting_user):
    """Home layouts reach a person the way packs do: through the catalog,
    seeded from their manifests, each with the widgets it places."""
    a = await acting_user()
    for manifest in load_builtin_manifests():
        if manifest.get("kind") == "home_layout":
            await marketplace_catalog.upsert_listing(
                session, manifest, source="builtin"
            )
    await session.commit()

    response = await client.get("/api/v1/me/home-layouts", headers=a.headers)

    assert response.status_code == 200
    items = {item["public_id"]: item for item in response.json()["items"]}
    assert {"core.home-week-ahead", "core.home-study-session"} <= set(items)
    timer = next(
        w for w in items["core.home-study-session"]["widgets"] if w["type"] == "clock"
    )
    assert timer["options"] == {"mode": "timer", "timer": {"duration": 1500}}
    # Only home layouts: a pack is not a page.
    assert not any(
        public_id.startswith("core.") and "home" not in public_id for public_id in items
    )
