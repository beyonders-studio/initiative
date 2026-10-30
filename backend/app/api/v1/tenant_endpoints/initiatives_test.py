"""
Integration tests for initiative endpoints.

Tests the initiative API endpoints at /api/v1/initiatives including:
- Listing initiatives
- Creating initiatives
- Updating initiatives
- Deleting initiatives
- Managing initiative members (add, remove, update roles)
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import GuildMessages, InitiativeMessages
from app.core.notification_categories import NotificationCategory
from app.core.tools import Tool
from app.models.platform.access_grant import AccessGrant
from app.models.platform.email_outbox import EmailOutboxItem
from app.models.platform.guild import CommunityRole
from app.models.platform.notification import Notification, NotificationType
from app.models.platform.user import Presence, UserStatus
from app.models.tenant.initiative import (
    Initiative,
    InitiativeJoinRequest,
    InitiativeMember,
)
from app.services.tenant.initiative_tools import tool_on_sql
from app.testing.schema_harness import route_session_to_guild
from app.models.tenant.resource_grant import ResourceGrant
from app.services import email as email_service
from app.services.platform import email_outbox
from app.services.content_sockets import sockets as content_sockets
from app.services.tenant import initiatives as initiatives_service
from app.testing import (
    create_resource_grant,
    create_tool_entity,
    enable_all_tools,
    set_notification_prefs,
    drain_notices,
)
from app.testing.factories import create_guild_membership, create_initiative
from app.testing.sockets import open_account_socket


async def _live_grant(
    session: AsyncSession,
    *,
    user,
    guild,
    approver,
    level: str,
    purpose: str = "content",
):
    """An approved, currently-live access grant — the PAM branch of GuildContext."""
    now = datetime.now(timezone.utc)
    session.add(
        AccessGrant(
            user_id=user.id,
            guild_id=guild.id,
            purpose=purpose,
            access_level=level,
            status="approved",
            reason="ticket",
            requested_duration_minutes=60,
            requested_by_id=user.id,
            approved_by_id=approver.id,
            decided_at=now,
            expires_at=now + timedelta(hours=1),
        )
    )
    await session.commit()


async def _initiative_with_owner(session: AsyncSession, acting_user, **overrides):
    """A plain guild member and the initiative they created — and therefore
    manage — in their guild."""
    overrides.setdefault("name", "Doorway")
    owner = await acting_user(guild_role=CommunityRole.member)
    initiative = await create_initiative(session, owner.guild, owner.user, **overrides)
    return owner, initiative


async def _caller(acting_user, kind: str, owner, initiative):
    """One of the three standings an initiative answers to: ``manager`` is the
    person who made it, ``admin`` a guild admin who never joined it, and
    ``member`` a plain member of it."""
    if kind == "manager":
        return owner
    if kind == "admin":
        return await acting_user(guild_role=CommunityRole.admin, guild=owner.guild)
    return await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=initiative,
        initiative_role="member",
    )


async def _roster(client: AsyncClient, actor, initiative_id: int, **params) -> dict:
    """One page of the initiative's roster as ``actor`` reads it."""
    response = await client.get(
        actor.g(f"/initiatives/{initiative_id}/members"),
        headers=actor.headers,
        params=params,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _project_shared_with_the_initiative(session: AsyncSession, initiative, owner):
    """A project every member of the initiative may read, so that the
    membership row is the only thing that changes when somebody joins."""
    from app.testing.factories import create_project

    project = await create_project(session, initiative, owner, name="Shared work")
    await create_resource_grant(session, project, all_initiative_members=True)
    return project


async def _notifications_for(
    session: AsyncSession, user_id: int, ntype: NotificationType
) -> list[Notification]:
    await drain_notices()
    result = await session.exec(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.type == ntype,
        )
    )
    return list(result.all())


async def _pending_mail_for(session: AsyncSession, user_id: int) -> int:
    """How much notification mail is waiting for this account."""
    await drain_notices()
    result = await session.exec(
        select(EmailOutboxItem).where(EmailOutboxItem.user_id == user_id)
    )
    return len(list(result.all()))


async def _requestable(session: AsyncSession, actor, **overrides):
    """A `request`-policy initiative managed by ``actor``."""
    return await create_initiative(
        session,
        actor.guild,
        actor.user,
        join_policy="request",
        **overrides,
    )


async def _knocked_on(
    client: AsyncClient, session: AsyncSession, acting_user, count: int = 2
):
    """A request-policy initiative with ``count`` guild members waiting at it.

    Returns its manager, the initiative, and each asker paired with the id of
    the request they left.
    """
    owner, initiative = await _initiative_with_owner(
        session, acting_user, name="Knockable", join_policy="request"
    )
    knocks = []
    for _ in range(count):
        asker = await acting_user(guild_role=CommunityRole.member, guild=owner.guild)
        created = await client.post(
            asker.g(f"/initiatives/{initiative.id}/join-requests"),
            headers=asker.headers,
            json={},
        )
        assert created.status_code == 201, created.text
        knocks.append((asker, created.json()["id"]))
    return owner, initiative, knocks


def _capture_join_request_emails(monkeypatch) -> list[dict]:
    """Record every join-request email as it is written to the outbox.

    Notification mail is a row the worker drains rather than a send inside the
    request, so what a test reads is the composed message the notifier handed
    over — subject and body, not the arguments that built them.
    """
    sent: list[dict] = []

    async def _fake_enqueue(
        _session,
        recipient,
        *,
        category,
        pieces,
        guild_id=None,
        **_rest,
    ):
        sent.append(
            {
                "recipient_id": recipient.id,
                "category": category,
                "guild_id": guild_id,
                "subject": pieces.subject,
                "body": pieces.body,
                "link": pieces.link,
            }
        )
        return True

    monkeypatch.setattr(email_outbox, "enqueue", _fake_enqueue)
    return sent


@pytest.mark.parametrize(
    "caller_role",
    [CommunityRole.admin, CommunityRole.member],
    ids=["a guild admin", "a plain member"],
)
async def test_the_default_listing_is_the_callers_own_memberships(
    client: AsyncClient, session: AsyncSession, acting_user, caller_role: CommunityRole
):
    """The default listing is navigation rather than authority: it is what the
    caller joined, for a guild admin exactly as for anyone else."""
    owner = await acting_user(guild_role=CommunityRole.admin)
    await create_initiative(session, owner.guild, owner.user, name="Theirs")
    caller = await acting_user(
        guild_role=caller_role, guild=owner.guild, initiative=True
    )

    response = await client.get(caller.g("/initiatives/"), headers=caller.headers)

    assert response.status_code == 200
    listed = {entry["name"] for entry in response.json()}
    assert caller.initiative.name in listed
    assert "Theirs" not in listed


@pytest.mark.parametrize(
    ("caller_role", "status_code"),
    [(CommunityRole.admin, 200), (CommunityRole.member, 403)],
    ids=["a guild admin", "a plain member"],
)
async def test_guild_scope_lists_the_whole_guild_for_admins_only(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    caller_role: CommunityRole,
    status_code: int,
):
    """``scope=community`` is the guild-settings management listing: every
    initiative in the guild, including the ones the caller never joined."""
    owner = await acting_user(guild_role=CommunityRole.admin)
    await create_initiative(session, owner.guild, owner.user, name="Theirs")
    caller = await acting_user(guild_role=caller_role, guild=owner.guild)

    response = await client.get(
        caller.g("/initiatives/?scope=community"), headers=caller.headers
    )

    assert response.status_code == status_code, response.text
    if status_code == 200:
        assert "Theirs" in {entry["name"] for entry in response.json()}
    else:
        assert response.json()["detail"] == GuildMessages.COMMUNITY_ADMIN_REQUIRED


@pytest.mark.parametrize(
    ("caller", "status_code"),
    [("grantee", 200), ("outsider", 403)],
    ids=["a live read grant", "a guild member outside it"],
)
async def test_reading_an_initiative_by_id_answers_each_caller(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    caller: str,
    status_code: int,
):
    """The initiative and its roles are addressable by id for a grantee — the
    pages that open one resolve it that way rather than from a roster. The
    grantee leg widened nothing for an ordinary member of the guild.
    """
    owner = await acting_user(guild_role=CommunityRole.admin)
    initiative = await create_initiative(
        session, owner.guild, owner.user, name="Apollo"
    )
    if caller == "grantee":
        actor = await acting_user("support")
        await _live_grant(
            session,
            user=actor.user,
            guild=owner.guild,
            approver=owner.user,
            level="read",
        )
    else:
        actor = await acting_user(guild_role=CommunityRole.member, guild=owner.guild)

    base = f"/api/v1/c/{owner.guild.id}/initiatives/{initiative.id}"
    detail = await client.get(base, headers=actor.headers)

    assert detail.status_code == status_code, detail.text
    if status_code != 200:
        assert detail.json()["detail"] == InitiativeMessages.NOT_A_MEMBER
        return

    assert detail.json()["name"] == "Apollo"
    roles = await client.get(f"{base}/roles", headers=actor.headers)
    assert roles.status_code == 200, roles.text
    assert "project_manager" in {role["name"] for role in roles.json()}


@pytest.mark.parametrize(
    ("tier", "level"),
    [("support", "read"), ("operator", "read_write")],
    ids=["a scoped read grant", "break-glass"],
)
async def test_a_live_grant_lists_the_whole_guild_it_reaches(
    client: AsyncClient, session: AsyncSession, acting_user, tier: str, level: str
):
    """A grantee holds no membership in the guild — the grant is what they
    navigate by, so the default listing stays the whole guild for its window.
    Break-glass reads it the same way: its content grant is one of these.
    """
    owner = await acting_user(guild_role=CommunityRole.admin)
    await create_initiative(session, owner.guild, owner.user, name="Apollo")
    grantee = await acting_user(tier)
    await _live_grant(
        session, user=grantee.user, guild=owner.guild, approver=owner.user, level=level
    )

    response = await client.get(
        f"/api/v1/c/{owner.guild.id}/initiatives/", headers=grantee.headers
    )

    assert response.status_code == 200, response.text
    assert "Apollo" in {entry["name"] for entry in response.json()}


@pytest.mark.parametrize(
    ("verb", "caller", "status_code", "detail"),
    [
        ("create", "admin", 201, None),
        ("create", "manager", 403, GuildMessages.COMMUNITY_ADMIN_REQUIRED),
        ("create", "member", 403, GuildMessages.COMMUNITY_ADMIN_REQUIRED),
        ("update", "admin", 200, None),
        ("update", "manager", 200, None),
        ("update", "member", 403, InitiativeMessages.MANAGER_REQUIRED),
        ("archive", "admin", 200, None),
        ("archive", "manager", 403, GuildMessages.COMMUNITY_ADMIN_REQUIRED),
        ("archive", "member", 403, GuildMessages.COMMUNITY_ADMIN_REQUIRED),
        ("delete", "admin", 204, None),
        ("delete", "manager", 403, GuildMessages.COMMUNITY_ADMIN_REQUIRED),
        ("delete", "member", 403, GuildMessages.COMMUNITY_ADMIN_REQUIRED),
    ],
)
async def test_initiative_crud_answers_each_caller(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    verb: str,
    caller: str,
    status_code: int,
    detail: str | None,
):
    """What an initiative answers to depends on what is being asked of it.

    Putting one in the guild, filing it away, or taking it out of the guild
    altogether is the guild's decision and takes a guild admin; editing what an
    initiative says is its managers' decision. A guild admin reaches every
    initiative in their guild without holding a membership row in it.
    """
    owner, initiative = await _initiative_with_owner(session, acting_user)
    actor = await _caller(acting_user, caller, owner, initiative)

    if verb == "create":
        response = await client.post(
            actor.g("/initiatives/"), headers=actor.headers, json={"name": "Fresh"}
        )
    elif verb == "update":
        response = await client.patch(
            actor.g(f"/initiatives/{initiative.id}"),
            headers=actor.headers,
            json={"name": "Renamed"},
        )
    elif verb == "archive":
        response = await client.post(
            actor.g(f"/archive/initiative/{initiative.id}"), headers=actor.headers
        )
    else:
        response = await client.delete(
            actor.g(f"/initiatives/{initiative.id}"), headers=actor.headers
        )

    assert response.status_code == status_code, response.text
    if detail is not None:
        assert response.json()["detail"] == detail


@pytest.mark.parametrize(
    ("asked_for", "expected_policy"),
    [({}, "private"), ({"join_policy": "open"}, "open")],
    ids=["a closed door by default", "an open one on request"],
)
async def test_creating_an_initiative_records_what_it_was_given(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    asked_for: dict,
    expected_policy: str,
):
    """The creation payload lands as given, and a join policy nobody mentioned
    settles on the closed one."""
    admin = await acting_user(guild_role=CommunityRole.admin)

    response = await client.post(
        admin.g("/initiatives/"),
        headers=admin.headers,
        json={
            "name": "New Initiative",
            "description": "A test initiative",
            "color": "#FF0000",
            **asked_for,
        },
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["name"] == "New Initiative"
    assert data["description"] == "A test initiative"
    assert data["color"] == "#FF0000"
    assert data["join_policy"] == expected_policy


async def test_create_initiative_makes_creator_manager(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Creating an initiative makes the creator a manager — the moderator role
    here, because the creator is a guild admin — and the read reports their
    role and the headcount rather than the roster."""
    admin = await acting_user(guild_role=CommunityRole.admin)

    payload = {"name": "New Initiative"}

    response = await client.post(
        admin.g("/initiatives/"), headers=admin.headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    assert "members" not in data
    assert (data["member_count"], data["role_display_name"]) == (1, "Moderator")
    rows = (await _roster(client, admin, data["id"]))["items"]
    assert [(row["user"]["id"], row["role_name"]) for row in rows] == [
        (admin.user.id, "moderator")
    ]


async def test_updating_an_initiative_records_the_new_name_and_description(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The patch lands as given."""
    owner, initiative = await _initiative_with_owner(session, acting_user)

    response = await client.patch(
        owner.g(f"/initiatives/{initiative.id}"),
        headers=owner.headers,
        json={"name": "Updated Initiative", "description": "Updated description"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Initiative"
    assert data["description"] == "Updated description"

    # A required field is omitted to keep it, never nulled.
    for field in ("name", "join_policy", "keep_content_in", "projects_enabled"):
        response = await client.patch(
            owner.g(f"/initiatives/{initiative.id}"),
            headers=owner.headers,
            json={field: None},
        )
        assert response.status_code == 422, field


@pytest.mark.parametrize("verb", ["create", "update"], ids=["creating", "renaming"])
async def test_an_initiative_name_is_taken_only_once(
    client: AsyncClient, session: AsyncSession, acting_user, verb: str
):
    """A guild's initiative names are unique, however the name arrives."""
    admin = await acting_user(guild_role=CommunityRole.admin)
    mine = await create_initiative(
        session, admin.guild, admin.user, name="Initiative 1"
    )
    await create_initiative(session, admin.guild, admin.user, name="Initiative 2")

    if verb == "create":
        response = await client.post(
            admin.g("/initiatives/"),
            headers=admin.headers,
            json={"name": "Initiative 2"},
        )
    else:
        response = await client.patch(
            admin.g(f"/initiatives/{mine.id}"),
            headers=admin.headers,
            json={"name": "Initiative 2"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == InitiativeMessages.NAME_EXISTS


# ── Archive ──────────────────────────────────────────────────────────────────


async def test_archiving_an_initiative_round_trips_and_keeps_it_listed(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A fresh initiative carries no archive stamp; a guild admin sets one
    through the polymorphic archive endpoint and takes it off again.

    It stays in the guild listing either way — only the sidebar filters
    archived initiatives client-side, and the settings table has to keep seeing
    them.
    """
    admin = await acting_user(guild_role=CommunityRole.admin)
    initiative = await create_initiative(
        session, admin.guild, admin.user, name="Archivable"
    )

    fresh = await client.get(
        admin.g(f"/initiatives/{initiative.id}"), headers=admin.headers
    )
    assert fresh.status_code == 200
    assert fresh.json()["archived_at"] is None

    archive = await client.post(
        admin.g(f"/archive/initiative/{initiative.id}"), headers=admin.headers
    )
    assert archive.status_code == 200
    assert archive.json()["archived_at"] is not None

    listing = await client.get(
        admin.g("/initiatives/?scope=community"), headers=admin.headers
    )
    assert listing.status_code == 200
    archived = next(i for i in listing.json() if i["id"] == initiative.id)
    assert archived["archived_at"] is not None

    unarchive = await client.post(
        admin.g(f"/unarchive/initiative/{initiative.id}"), headers=admin.headers
    )
    assert unarchive.status_code == 200
    assert unarchive.json()["archived_at"] is None


async def test_search_initiative_members_slim_and_filtered(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The slim members search returns a UserSummary envelope and filters by
    name, with the same membership gate as the full roster."""
    admin = await acting_user(guild_role=CommunityRole.admin)
    initiative = await create_initiative(
        session, admin.guild, admin.user, name="Search Initiative"
    )
    alice = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=initiative,
        initiative_role="member",
        email="alice@example.com",
        username="wonderland",
    )
    bob = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=initiative,
        initiative_role="member",
        email="bob@example.com",
    )

    # Unfiltered: slim envelope over every member (creator + 2).
    response = await client.get(
        admin.g(f"/initiatives/{initiative.id}/members/search"),
        headers=admin.headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 3
    assert set(body["items"][0].keys()) == {
        "id",
        "username",
        "discriminator",
        "display_name",
        "avatar_url",
        "status",
        "profile_decorations",
        "community_role",
    }
    # Asserted as a value, not only as a key: the schema leaves it unset, so a
    # key-set check passes just as happily on an endpoint that never fills it
    # in.
    by_id = {item["id"]: item for item in body["items"]}
    assert by_id[admin.user.id]["community_role"] == "admin"
    assert by_id[alice.user.id]["community_role"] == "member"
    assert by_id[bob.user.id]["community_role"] == "member"

    # Filtered by handle, which every guild has for every member.
    response = await client.get(
        admin.g(f"/initiatives/{initiative.id}/members/search"),
        headers=admin.headers,
        params={"search": "wonder"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 1
    assert body["items"][0]["username"] == "wonderland"

    # A term outside her handle finds nobody while she has no name here...
    response = await client.get(
        admin.g(f"/initiatives/{initiative.id}/members/search"),
        headers=admin.headers,
        params={"search": "Alice"},
    )
    assert response.json()["total_count"] == 0

    # ...and the display name she set here does: the search reaches exactly
    # what the guild renders.
    await create_guild_membership(
        session, user=alice.user, guild=admin.guild, display_name="Alice W"
    )
    response = await client.get(
        admin.g(f"/initiatives/{initiative.id}/members/search"),
        headers=admin.headers,
        params={"search": "Alice"},
    )
    assert response.json()["total_count"] == 1


async def test_search_initiative_members_filters_by_user_id(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """`user_id` resolves a known selection, narrowing the same member set —
    a guild member outside the initiative is never resolved through it."""
    admin = await acting_user(guild_role=CommunityRole.admin)
    initiative = await create_initiative(
        session, admin.guild, admin.user, name="Id Filter Initiative"
    )
    alice = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=initiative,
        initiative_role="member",
        email="alice-ids@example.com",
        username="alice-ids",
    )
    outsider = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        email="outsider-ids@example.com",
    )

    response = await client.get(
        admin.g(f"/initiatives/{initiative.id}/members/search"),
        headers=admin.headers,
        params={"user_id": [alice.user.id, outsider.user.id]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 1
    assert [item["username"] for item in body["items"]] == ["alice-ids"]


@pytest.mark.parametrize(
    ("endpoint", "caller", "status_code"),
    [
        ("/members", "insider", 200),
        ("/members", "admin", 200),
        ("/members", "outsider", 403),
        ("/members/search", "insider", 200),
        ("/members/search", "admin", 200),
        ("/members/search", "outsider", 403),
    ],
)
async def test_the_roster_answers_its_members_and_a_guild_admin(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    endpoint: str,
    caller: str,
    status_code: int,
):
    """The roster names everyone in the initiative, to everyone in it.

    A guild admin reads it too, without ever having joined — the same
    guild-admin override every other initiative read honors, and what the
    assignee and linked-member pickers run on. A plain guild member outside the
    initiative stays out. The slim search answers exactly as the full roster
    does.
    """
    owner, initiative = await _initiative_with_owner(session, acting_user)
    insider = await _caller(acting_user, "member", owner, initiative)
    if caller == "insider":
        actor = insider
    elif caller == "admin":
        actor = await _caller(acting_user, "admin", owner, initiative)
    else:
        actor = await acting_user(guild_role=CommunityRole.member, guild=owner.guild)

    response = await client.get(
        actor.g(f"/initiatives/{initiative.id}{endpoint}"), headers=actor.headers
    )

    assert response.status_code == status_code, response.text
    if status_code != 200:
        assert response.json()["detail"] == InitiativeMessages.NOT_A_MEMBER
        return

    # The roster nests each person beside their role; the search is people.
    rows = [row.get("user", row) for row in response.json()["items"]]
    # A roster names members by handle. An address is never a guild's to hand
    # out, so it is absent from the shape entirely.
    assert {row["username"] for row in rows} == {
        owner.user.username,
        insider.user.username,
    }
    assert all("email" not in row for row in rows)


async def test_the_roster_pages_and_narrows_to_managers_beside_a_slim_list(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The roster is read a page at a time and can be narrowed to the managers
    or to who is here, each member saying how they appear, while the initiative
    list carries each one's headcount and the caller's own role instead of
    everyone's. A suspended member is in neither."""
    owner, initiative = await _initiative_with_owner(session, acting_user)
    insider = await _caller(acting_user, "member", owner, initiative)
    await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=initiative,
        initiative_role="member",
        status=UserStatus.suspended,
    )

    first = await _roster(client, insider, initiative.id, page_size=1)
    managers = await _roster(client, insider, initiative.id, is_manager="true")
    others = await _roster(client, insider, initiative.id, is_manager="false")
    socket = open_account_socket(insider.user.id, chosen_presence=Presence.busy)
    try:
        here = await _roster(client, insider, initiative.id, online="true")
    finally:
        content_sockets.leave(socket)  # type: ignore[arg-type]
    listed = await client.get(insider.g("/initiatives/"), headers=insider.headers)

    assert (first["total_count"], len(first["items"]), first["has_next"]) == (
        2,
        1,
        True,
    )
    assert [row["user"]["id"] for row in managers["items"]] == [owner.user.id]
    assert [row["user"]["id"] for row in others["items"]] == [insider.user.id]
    assert [(row["user"]["id"], row["presence"]) for row in here["items"]] == [
        (insider.user.id, "busy")
    ]
    assert {row["presence"] for row in first["items"]} == {"offline"}
    assert listed.status_code == 200, listed.text
    assert [
        (row["id"], row["member_count"], row["role_display_name"])
        for row in listed.json()
    ] == [(initiative.id, 2, "Member")]


@pytest.mark.parametrize(
    ("caller", "status_code", "detail"),
    [
        ("manager", 200, None),
        ("member", 403, InitiativeMessages.MANAGER_REQUIRED),
    ],
)
async def test_adding_a_member_takes_manager_standing(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    caller: str,
    status_code: int,
    detail: str | None,
):
    """Staffing an initiative is its managers' to do."""
    owner, initiative = await _initiative_with_owner(session, acting_user)
    actor = await _caller(acting_user, caller, owner, initiative)
    newcomer = await acting_user(guild_role=CommunityRole.member, guild=owner.guild)

    response = await client.post(
        actor.g(f"/initiatives/{initiative.id}/members"),
        headers=actor.headers,
        json={"user_id": newcomer.user.id, "role": "member"},
    )

    assert response.status_code == status_code, response.text
    if detail is None:
        rows = (await _roster(client, actor, initiative.id))["items"]
        assert newcomer.user.id in {row["user"]["id"] for row in rows}
    else:
        assert response.json()["detail"] == detail


async def test_add_user_not_in_guild_fails(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that adding a user not in the guild fails."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    # An outsider with no membership in the admin's guild.
    outsider = await acting_user(email="outsider@example.com")

    payload = {"user_id": outsider.user.id, "role": "member"}

    response = await client.post(
        admin.g(f"/initiatives/{admin.initiative.id}/members"),
        headers=admin.headers,
        json=payload,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "USER_NOT_IN_COMMUNITY"


async def test_update_initiative_member_role(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test updating an initiative member's role."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )

    # Look up the PM role ID for this initiative
    from app.models.tenant.initiative import InitiativeRoleModel
    from sqlmodel import select

    pm_role_stmt = select(InitiativeRoleModel).where(
        InitiativeRoleModel.initiative_id == admin.initiative.id,
        InitiativeRoleModel.name == "project_manager",
    )
    pm_role = (await session.exec(pm_role_stmt)).one()

    payload = {"role_id": pm_role.id}

    response = await client.patch(
        admin.g(f"/initiatives/{admin.initiative.id}/members/{member.user.id}"),
        headers=admin.headers,
        json=payload,
    )

    assert response.status_code == 200
    rows = (await _roster(client, admin, admin.initiative.id))["items"]
    member_roles = {m["user"]["id"]: m["role_name"] for m in rows}
    assert member_roles[member.user.id] == "project_manager"


async def test_member_roster_reports_a_custom_role_as_itself(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A member's row carries the role they actually hold — its own name,
    display name, and manager standing — for custom roles too, and the role
    list counts each role's holders."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )

    role_response = await client.post(
        admin.g(f"/initiatives/{admin.initiative.id}/roles"),
        headers=admin.headers,
        json={"name": "leads", "display_name": "Leads", "is_manager": True},
    )
    assert role_response.status_code == 201, role_response.text

    response = await client.patch(
        admin.g(f"/initiatives/{admin.initiative.id}/members/{member.user.id}"),
        headers=admin.headers,
        json={"role_id": role_response.json()["id"]},
    )

    assert response.status_code == 200
    rows = (await _roster(client, admin, admin.initiative.id))["items"]
    row = next(m for m in rows if m["user"]["id"] == member.user.id)
    assert row["role_name"] == "leads"
    assert row["role_display_name"] == "Leads"
    assert row["is_manager"] is True

    roles = await client.get(
        admin.g(f"/initiatives/{admin.initiative.id}/roles"), headers=admin.headers
    )
    assert roles.status_code == 200, roles.text
    counts = {r["name"]: r["member_count"] for r in roles.json()}
    assert (counts["leads"], counts["member"], sum(counts.values())) == (1, 0, 2)


@pytest.mark.parametrize(
    ("inviter", "asked_role", "expected_role"),
    [
        ("guild admin", "member", "moderator"),
        ("project manager", None, "moderator"),
        ("guild admin", "project_manager", "project_manager"),
    ],
)
async def test_inviting_a_guild_admin_lands_them_on_a_manager_role(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    inviter: str,
    asked_role: str | None,
    expected_role: str,
):
    """An invite naming a standard role for a guild admin still succeeds.

    A guild admin's standing already reaches every initiative, so their row
    carries a manager role — the invite settles that rather than refusing,
    which is what lets a project manager add an admin without first checking
    who is one. Asking for the manager role outright is honored as asked, for
    the manager-style features that read off it.
    """
    from app.models.tenant.initiative import InitiativeRoleModel

    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    if inviter == "guild admin":
        actor = admin
    else:
        actor = await acting_user(
            guild_role=CommunityRole.member,
            guild=admin.guild,
            initiative=admin.initiative,
            initiative_role="project_manager",
        )
    target = await acting_user(guild_role=CommunityRole.admin, guild=admin.guild)

    payload: dict = {"user_id": target.user.id}
    if asked_role is not None:
        role = (
            await session.exec(
                select(InitiativeRoleModel).where(
                    InitiativeRoleModel.initiative_id == admin.initiative.id,
                    InitiativeRoleModel.name == asked_role,
                )
            )
        ).one()
        payload["role_id"] = role.id

    response = await client.post(
        actor.g(f"/initiatives/{admin.initiative.id}/members"),
        headers=actor.headers,
        json=payload,
    )

    assert response.status_code == 200, response.text
    rows = (await _roster(client, actor, admin.initiative.id))["items"]
    roles = {m["user"]["id"]: m["role_name"] for m in rows}
    assert roles[target.user.id] == expected_role


async def test_promotion_to_guild_admin_lifts_existing_initiative_roles(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A promotion reaches the rows the person already held.

    Their guild role changes underneath initiative memberships that already
    exist, and only this path can bring them up to the manager role an admin's
    row carries — everything that writes a row settles it for itself.
    """
    from app.testing.schema_harness import route_session_to_guild

    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    joiner = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )

    response = await client.patch(
        f"/api/v1/communities/{admin.guild.id}/members/{joiner.user.id}",
        headers=admin.headers,
        json={"role": "admin"},
    )
    assert response.status_code == 204, response.text

    await route_session_to_guild(session, admin.guild.id)
    membership = (
        await session.exec(
            select(InitiativeMember).where(
                InitiativeMember.initiative_id == admin.initiative.id,
                InitiativeMember.user_id == joiner.user.id,
            )
        )
    ).one()
    role = await initiatives_service.get_role_by_id(session, role_id=membership.role_id)
    assert role is not None and role.is_manager


@pytest.mark.parametrize("who", ["a member", "the last manager"])
async def test_removing_a_membership_ends_it(
    client: AsyncClient, session: AsyncSession, acting_user, who: str
):
    """An initiative may be left with no manager until an admin appoints one.

    Ending a membership is not blocked by it being the last manager's;
    ``test_cannot_demote_last_manager`` covers the case that still is, which
    edits a live membership rather than ending it. Every grant naming the
    person in the initiative goes with it, on every tool, owner grants included.
    """
    owner, initiative = await _initiative_with_owner(session, acting_user)
    target = (
        owner
        if who == "the last manager"
        else await _caller(acting_user, "member", owner, initiative)
    )
    await enable_all_tools(session, initiative)
    for tool in Tool:
        row = await create_tool_entity(session, tool, initiative, owner.user)
        if target is not owner:
            await create_resource_grant(session, row, user=target.user)

    response = await client.delete(
        owner.g(f"/initiatives/{initiative.id}/members/{target.user.id}"),
        headers=owner.headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["member_count"] == (0 if who == "the last manager" else 1)
    levels = (
        await session.exec(
            select(ResourceGrant.level).where(ResourceGrant.user_id == target.user.id)
        )
    ).all()
    assert levels == []


async def test_cannot_demote_last_manager(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that demoting the last manager fails."""
    manager = await acting_user(guild_role=CommunityRole.member, initiative=True)

    # Look up the member role ID for this initiative
    from app.models.tenant.initiative import InitiativeRoleModel
    from sqlmodel import select

    member_role_stmt = select(InitiativeRoleModel).where(
        InitiativeRoleModel.initiative_id == manager.initiative.id,
        InitiativeRoleModel.name == "member",
    )
    member_role = (await session.exec(member_role_stmt)).one()

    payload = {"role_id": member_role.id}

    response = await client.patch(
        manager.g(f"/initiatives/{manager.initiative.id}/members/{manager.user.id}"),
        headers=manager.headers,
        json=payload,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "INITIATIVE_MUST_HAVE_PM"


async def test_initiative_guild_isolation(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that initiatives are isolated by guild."""
    from app.testing.factories import create_guild, create_guild_membership

    # One user who is an admin of two distinct guilds.
    a = await acting_user(guild_role=CommunityRole.admin)
    guild2 = await create_guild(session)
    await create_guild_membership(
        session, user=a.user, guild=guild2, role=CommunityRole.admin
    )

    initiative1 = await create_initiative(
        session, a.guild, a.user, name="Guild 1 Initiative"
    )
    await create_initiative(session, guild2, a.user, name="Guild 2 Initiative")

    # Request with guild1 context
    response1 = await client.get(a.g("/initiatives/"), headers=a.headers)

    assert response1.status_code == 200
    data1 = response1.json()
    initiative_names1 = {init["name"] for init in data1}
    assert "Guild 1 Initiative" in initiative_names1
    assert "Guild 2 Initiative" not in initiative_names1

    # Cannot access guild1's initiative with guild2 context. Under schema-per-guild
    # ids are per-schema (not globally unique), so initiative1.id may collide with
    # a guild2 initiative — but it must never resolve to guild1's initiative.
    response2 = await client.get(
        f"/api/v1/c/{guild2.id}/initiatives/{initiative1.id}", headers=a.headers
    )

    if response2.status_code == 200:
        assert response2.json()["name"] != "Guild 1 Initiative"
    else:
        assert response2.status_code == 404


# ============================================================================
# Discovery: directory, self-join, join settings
# ============================================================================


@pytest.mark.parametrize(
    "caller_role",
    [CommunityRole.member, CommunityRole.admin],
    ids=["a plain member", "a guild admin"],
)
async def test_directory_lists_only_joinable_initiatives(
    client: AsyncClient, session: AsyncSession, acting_user, caller_role: CommunityRole
):
    """Listing is opt-in: `private` appears only to its own members, archived
    never appears.

    A guild admin's front page reads the same way — their authority over the
    guild is unchanged, the directory just stops standing in for it, and
    ``scope=community`` is where the whole guild is.

    RLS *would* permit listing a private initiative to any guild member (the
    `initiatives` table is structural), so this exclusion is an app-layer
    promise — pinned here rather than assumed.
    """
    admin = await acting_user(guild_role=CommunityRole.admin)

    await create_initiative(
        session, admin.guild, admin.user, name="Secret", join_policy="private"
    )
    await create_initiative(
        session, admin.guild, admin.user, name="Knockable", join_policy="request"
    )
    await create_initiative(
        session, admin.guild, admin.user, name="Anyone", join_policy="open"
    )
    await create_initiative(
        session,
        admin.guild,
        admin.user,
        name="Retired",
        join_policy="open",
        archived_at=datetime.now(timezone.utc),
    )

    caller = await acting_user(guild_role=caller_role, guild=admin.guild)
    response = await client.get(
        caller.g("/initiatives/directory"), headers=caller.headers
    )

    assert response.status_code == 200
    listed = {entry["name"]: entry for entry in response.json()}
    assert set(listed) == {"Knockable", "Anyone"}
    assert listed["Knockable"]["join_policy"] == "request"
    assert listed["Anyone"]["join_policy"] == "open"


async def test_directory_reports_the_callers_own_state(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The directory doubles as the caller's own initiative list.

    A private initiative appears to its own members — their sidebar already
    shows it — listed ahead of the joinable ones. Each card carries the roster
    size and where the caller stands with it, on which role.
    """
    admin = await acting_user(guild_role=CommunityRole.admin)
    mine = await create_initiative(
        session, admin.guild, admin.user, name="Zebra Ours", join_policy="private"
    )
    await create_initiative(
        session, admin.guild, admin.user, name="Askable", join_policy="open"
    )

    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=mine,
        initiative_role="member",
    )

    response = await client.get(
        member.g("/initiatives/directory"), headers=member.headers
    )

    assert response.status_code == 200
    entries = response.json()
    # Membership outranks the alphabet: "Zebra Ours" leads despite sorting last.
    assert [entry["name"] for entry in entries] == ["Zebra Ours", "Askable"]
    assert entries[0]["join_policy"] == "private"
    # The creator (PM) plus the member who joined.
    assert entries[0]["member_count"] == 2
    assert entries[0]["is_member"] is True
    assert entries[0]["role_display_name"] == "Member"
    assert entries[0]["has_pending_request"] is False
    assert entries[1]["member_count"] == 1
    assert entries[1]["is_member"] is False
    assert entries[1]["role_display_name"] is None
    assert entries[1]["has_pending_request"] is False


async def test_directory_rejects_non_guild_member(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The directory is guild-scoped: an outsider never reaches it."""
    admin = await acting_user(guild_role=CommunityRole.admin)
    await create_initiative(
        session, admin.guild, admin.user, name="Anyone", join_policy="open"
    )
    outsider = await acting_user(guild_role=CommunityRole.member)

    response = await client.get(
        f"/api/v1/c/{admin.guild.id}/initiatives/directory", headers=outsider.headers
    )

    assert response.status_code == 403


async def _joiner(acting_user, session: AsyncSession, kind: str, owner, initiative):
    """The caller trying the door."""
    if kind == "guild member":
        return await acting_user(guild_role=CommunityRole.member, guild=owner.guild)
    if kind == "existing member":
        return await acting_user(
            guild_role=CommunityRole.member,
            guild=owner.guild,
            initiative=initiative,
            initiative_role="member",
        )
    if kind == "guild admin":
        return await acting_user(guild_role=CommunityRole.admin, guild=owner.guild)
    grantee = await acting_user("support")
    await _live_grant(
        session,
        user=grantee.user,
        guild=owner.guild,
        approver=owner.user,
        level="read_write",
    )
    return grantee


@pytest.mark.parametrize(
    ("policy", "caller", "status_code", "outcome"),
    [
        ("open", "guild member", 200, ("member", False)),
        ("private", "guild member", 403, InitiativeMessages.NOT_JOINABLE),
        ("request", "guild member", 403, InitiativeMessages.NOT_JOINABLE),
        ("private", "guild admin", 200, ("moderator", True)),
        ("request", "guild admin", 200, ("moderator", True)),
        ("open", "existing member", 200, ("member", False)),
        ("open", "grantee", 403, InitiativeMessages.GRANT_CANNOT_MANAGE_MEMBERS),
    ],
)
async def test_self_join_answers_each_policy_and_caller(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    policy: str,
    caller: str,
    status_code: int,
    outcome,
):
    """Who walks in, and on which role.

    Self-join hands out the floor — the built-in member role, not managed by
    OIDC — and joining twice is a success rather than a second row. ``private``
    and ``request`` answer identically ("not by this route"), so the refusal
    says no more about one than the other. A guild admin's sidebar is their
    memberships, so walking in is how they put an initiative in it, and they
    land on the moderator role their standing already carries. A grant reaches
    the guild for a window; the membership row a join writes has no end date.
    """
    owner = await acting_user(guild_role=CommunityRole.admin)
    initiative = await create_initiative(
        session, owner.guild, owner.user, name="Doorway", join_policy=policy
    )
    actor = await _joiner(acting_user, session, caller, owner, initiative)

    response = await client.post(
        f"/api/v1/c/{owner.guild.id}/initiatives/{initiative.id}/join",
        headers=actor.headers,
    )

    assert response.status_code == status_code, response.text
    if isinstance(outcome, str):
        assert response.json()["detail"] == outcome
        return

    role_name, is_manager = outcome
    rows = [
        member
        for member in (await _roster(client, actor, initiative.id))["items"]
        if member["user"]["id"] == actor.user.id
    ]
    assert len(rows) == 1
    # The join answers with the joiner's own role on the initiative it returns.
    assert response.json()["role_display_name"] == rows[0]["role_display_name"]
    assert rows[0]["role_name"] == role_name
    assert rows[0]["is_manager"] is is_manager
    assert rows[0]["oidc_managed"] is False


async def test_self_join_absorbs_a_lost_insert_race(
    session: AsyncSession, acting_user, monkeypatch
):
    """Losing the insert race returns the winner's row, not a 500.

    Two overlapping joins both clear the membership lookup before either
    inserts, and the composite primary key then rejects the loser. Simulated
    here by making that lookup miss once while the row already exists — the
    interleaving a live race produces, without racing the test.
    """
    admin = await acting_user(guild_role=CommunityRole.admin)
    initiative = await create_initiative(
        session, admin.guild, admin.user, name="Anyone", join_policy="open"
    )
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)

    # The row the winning request already committed.
    winner = await initiatives_service.self_join(
        session, initiative=initiative, user_id=member.user.id
    )
    assert winner is not None

    real_lookup = initiatives_service.get_initiative_membership
    calls = {"n": 0}

    async def lookup_misses_once(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return await real_lookup(*args, **kwargs)

    monkeypatch.setattr(
        initiatives_service, "get_initiative_membership", lookup_misses_once
    )

    membership = await initiatives_service.self_join(
        session, initiative=initiative, user_id=member.user.id
    )

    assert membership is not None
    assert membership.user_id == member.user.id
    rows = (
        await session.exec(
            select(InitiativeMember).where(
                InitiativeMember.initiative_id == initiative.id,
                InitiativeMember.user_id == member.user.id,
            )
        )
    ).all()
    assert len(rows) == 1


@pytest.mark.parametrize(
    ("policy", "auto_join", "caller", "patch", "status_code", "expected"),
    [
        ("private", False, "manager", {"join_policy": "open"}, 200, ("open", False)),
        ("open", False, "admin", {"auto_join": True}, 200, ("open", True)),
        (
            "open",
            True,
            "admin",
            {"join_policy": "request", "auto_join": False},
            200,
            ("request", False),
        ),
        (
            "private",
            False,
            "member",
            {"join_policy": "open"},
            403,
            InitiativeMessages.MANAGER_REQUIRED,
        ),
        (
            "open",
            False,
            "manager",
            {"auto_join": True},
            403,
            InitiativeMessages.AUTO_JOIN_ADMIN_ONLY,
        ),
        (
            "private",
            False,
            "admin",
            {"auto_join": True},
            400,
            InitiativeMessages.AUTO_JOIN_REQUIRES_OPEN,
        ),
        (
            "open",
            True,
            "admin",
            {"join_policy": "request"},
            400,
            InitiativeMessages.AUTO_JOIN_REQUIRES_OPEN,
        ),
    ],
    ids=[
        "a manager opens the door",
        "a guild admin turns auto-join on",
        "closing the door together with auto-join",
        "a plain member of it may not open it",
        "a manager may not turn auto-join on",
        "auto-join needs an open door",
        "closing the door on its own is refused",
    ],
)
async def test_the_join_settings_answer_each_caller_and_pairing(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    policy: str,
    auto_join: bool,
    caller: str,
    patch: dict,
    status_code: int,
    expected,
):
    """``join_policy`` travels with the ordinary update permission, so any
    manager may open or close the door.

    Auto-join enrols every new guild member, which shapes onboarding for the
    whole guild — a guild admin's to set, and only coherent on an open door, so
    that anyone who leaves can walk back in. The two settings move together or
    not at all: an edit that would leave them at odds is refused rather than
    quietly dropping one of them.
    """
    owner, initiative = await _initiative_with_owner(
        session, acting_user, join_policy=policy, auto_join=auto_join
    )
    actor = await _caller(acting_user, caller, owner, initiative)

    response = await client.patch(
        actor.g(f"/initiatives/{initiative.id}"), headers=actor.headers, json=patch
    )

    assert response.status_code == status_code, response.text
    body = response.json()
    if isinstance(expected, str):
        assert body["detail"] == expected
    else:
        assert (body["join_policy"], body["auto_join"]) == expected


# ============================================================================
# Discovery: join requests
# ============================================================================


async def test_join_request_created_on_request_policy(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The happy path: a guild member knocks and the row lands pending."""
    manager = await acting_user(guild_role=CommunityRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    member = await acting_user(guild_role=CommunityRole.member, guild=manager.guild)

    response = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={"message": "I'd like to help out"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["message"] == "I'd like to help out"
    assert body["user"]["id"] == member.user.id
    assert body["initiative_id"] == initiative.id
    assert body["resolved_at"] is None
    assert body["resolved_by"] is None
    assert body["prior_denials"] == 0

    # No membership row yet — the knock grants nothing.
    assert (
        await initiatives_service.get_initiative_membership(
            session, initiative_id=initiative.id, user_id=member.user.id
        )
    ) is None


@pytest.mark.parametrize(
    ("policy", "caller", "knocked_first", "status_code", "detail"),
    [
        ("private", "guild member", False, 403, InitiativeMessages.NOT_REQUESTABLE),
        ("open", "guild member", False, 403, InitiativeMessages.NOT_REQUESTABLE),
        (
            "request",
            "guild member",
            True,
            409,
            InitiativeMessages.JOIN_REQUEST_ALREADY_PENDING,
        ),
        ("request", "existing member", False, 409, InitiativeMessages.ALREADY_A_MEMBER),
        (
            "request",
            "guild admin",
            False,
            409,
            InitiativeMessages.GUILD_ADMIN_NEED_NOT_REQUEST,
        ),
        (
            "request",
            "grantee",
            False,
            403,
            InitiativeMessages.GRANT_CANNOT_MANAGE_MEMBERS,
        ),
    ],
)
async def test_knocking_answers_each_policy_and_caller(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    policy: str,
    caller: str,
    knocked_first: bool,
    status_code: int,
    detail: str,
):
    """Who may leave a request at the door, and who has nothing to ask for.

    `private` and `open` answer identically — "not by this route" — so the
    refusal reveals no more about a private initiative than it did before.
    There is one live request per door. A guild admin already reaches every
    initiative in their guild and may only ever hold a manager role in one, so
    there is nothing for them to ask and no request to approve later. A grant
    reaches the guild for a window; a membership row has no end date.
    """
    owner, initiative = await _initiative_with_owner(
        session, acting_user, name="Doorway", join_policy=policy
    )
    actor = await _joiner(acting_user, session, caller, owner, initiative)
    url = f"/api/v1/c/{owner.guild.id}/initiatives/{initiative.id}/join-requests"

    if knocked_first:
        first = await client.post(url, headers=actor.headers, json={})
        assert first.status_code == 201, first.text

    response = await client.post(url, headers=actor.headers, json={})

    assert response.status_code == status_code, response.text
    assert response.json()["detail"] == detail


async def test_a_join_request_is_read_by_its_requester_and_the_queue(
    client: AsyncClient, session: AsyncSession, acting_user, reading_as
):
    """In the database, a request is read by whoever filed it and by the
    initiative's managers; another member of the community neither reads,
    answers nor files one in the requester's name."""
    from sqlalchemy import update
    from sqlalchemy.exc import DBAPIError

    manager = await acting_user(guild_role=CommunityRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    member, bystander = [
        await acting_user(guild_role=CommunityRole.member, guild=manager.guild)
        for _ in range(2)
    ]
    knocked = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={},
    )
    assert knocked.status_code == 201, knocked.text

    for reader in (member, manager):
        asking = await reading_as(reader.user.id, manager.guild.id)
        filed = (await asking.exec(select(InitiativeJoinRequest.user_id))).all()
        assert filed == [member.user.id]
    asking = await reading_as(bystander.user.id, manager.guild.id)
    assert (await asking.exec(select(InitiativeJoinRequest))).all() == []
    answered = await asking.exec(
        update(InitiativeJoinRequest).values(status="approved")
    )
    assert answered.rowcount == 0
    asking.add(
        InitiativeJoinRequest(
            initiative_id=initiative.id, user_id=member.user.id, status="pending"
        )
    )
    with pytest.raises(DBAPIError, match="row-level security"):
        await asking.flush()


async def test_denied_requester_may_ask_again(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Only a *pending* row blocks: a refusal is history, not a ban, and the
    second ask carries the first refusal for the manager to see."""
    manager = await acting_user(guild_role=CommunityRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    member = await acting_user(guild_role=CommunityRole.member, guild=manager.guild)

    first = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={},
    )
    assert first.status_code == 201
    denied = await client.post(
        manager.g(
            f"/initiatives/{initiative.id}/join-requests/{first.json()['id']}/deny"
        ),
        headers=manager.headers,
    )
    assert denied.status_code == 200

    again = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={},
    )

    assert again.status_code == 201
    assert again.json()["status"] == "pending"
    assert again.json()["prior_denials"] == 1


async def test_join_request_absorbs_a_lost_insert_race(
    session: AsyncSession, acting_user, monkeypatch
):
    """Losing the partial-unique race reads back the winner's row and reports the
    ordinary conflict, never a 500.

    Two overlapping knocks both clear the pending lookup before either inserts,
    and ``uq_initiative_join_requests_pending`` then rejects the loser.
    Simulated by making that lookup miss once while the row already exists — the
    interleaving a live race produces, without racing the test.
    """
    manager = await acting_user(guild_role=CommunityRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    member = await acting_user(guild_role=CommunityRole.member, guild=manager.guild)

    winner, created = await initiatives_service.create_join_request(
        session, initiative=initiative, user_id=member.user.id
    )
    assert created is True

    real_lookup = initiatives_service.get_pending_join_request
    calls = {"n": 0}

    async def lookup_misses_once(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return await real_lookup(*args, **kwargs)

    monkeypatch.setattr(
        initiatives_service, "get_pending_join_request", lookup_misses_once
    )

    loser, created_again = await initiatives_service.create_join_request(
        session, initiative=initiative, user_id=member.user.id
    )

    assert created_again is False
    assert loser.id == winner.id
    rows = (
        await session.exec(
            select(InitiativeJoinRequest).where(
                InitiativeJoinRequest.initiative_id == initiative.id,
                InitiativeJoinRequest.user_id == member.user.id,
            )
        )
    ).all()
    assert len(rows) == 1


async def test_the_pending_queue_carries_what_the_decision_needs(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Who is asking, what they said, and whether this initiative has turned
    them down before — with the settled rows kept out of the default view and
    reachable by asking for them."""
    manager = await acting_user(guild_role=CommunityRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    member = await acting_user(guild_role=CommunityRole.member, guild=manager.guild)

    first = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={"message": "first try"},
    )
    await client.post(
        manager.g(
            f"/initiatives/{initiative.id}/join-requests/{first.json()['id']}/deny"
        ),
        headers=manager.headers,
    )
    await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={"message": "second try"},
    )

    response = await client.get(
        manager.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=manager.headers,
    )

    assert response.status_code == 200
    queue = response.json()
    # Pending only by default: the denied row is history, not a decision.
    assert len(queue) == 1
    assert queue[0]["status"] == "pending"
    assert queue[0]["message"] == "second try"
    assert queue[0]["user"]["id"] == member.user.id
    # The queue names who is asking the way this guild names anyone —
    # by handle, since they set no name here.
    assert queue[0]["user"]["username"] == member.user.username
    assert queue[0]["prior_denials"] == 1

    history = await client.get(
        manager.g(f"/initiatives/{initiative.id}/join-requests?status=denied"),
        headers=manager.headers,
    )
    assert history.status_code == 200
    assert [row["status"] for row in history.json()] == ["denied"]


@pytest.mark.parametrize(
    ("caller", "status_code", "expected"),
    [
        ("manager", 200, "everyone waiting"),
        ("admin", 200, "everyone waiting"),
        ("member", 403, InitiativeMessages.MANAGER_REQUIRED),
        ("asker", 403, InitiativeMessages.MANAGER_REQUIRED),
    ],
    ids=[
        "its manager",
        "a guild admin",
        "a plain member of it",
        "somebody waiting at it",
    ],
)
async def test_the_join_queue_answers_each_caller(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    caller: str,
    status_code: int,
    expected: str,
):
    """Who asked to get in is manager business, and a guild admin's too — a
    non-manager member of the initiative has no more claim on it than the
    people waiting at it.

    ``initiative_join_requests`` is guild-level: the schema boundary is its
    only DB gate, so row visibility is an app-layer contract — pinned here.
    """
    owner, initiative, knocks = await _knocked_on(client, session, acting_user)
    actor = (
        knocks[0][0]
        if caller == "asker"
        else await _caller(acting_user, caller, owner, initiative)
    )

    response = await client.get(
        actor.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=actor.headers,
    )

    assert response.status_code == status_code, response.text
    if status_code != 200:
        assert response.json()["detail"] == expected
        return

    seen = {row["user"]["id"] for row in response.json()}
    assert seen == {asker.user.id for asker, _ in knocks}


@pytest.mark.parametrize(
    ("way_in", "policy"), [("join", "open"), ("approval", "request")]
)
async def test_joining_flips_content_visibility(
    client: AsyncClient, session: AsyncSession, acting_user, way_in: str, policy: str
):
    """The point of both doors: every way in writes the same membership row,
    and ``initiative_access`` does the rest — content that 404'd before the
    join resolves after it, with no RLS change at all."""
    manager = await acting_user(guild_role=CommunityRole.member)
    initiative = await create_initiative(
        session, manager.guild, manager.user, name="Doorway", join_policy=policy
    )
    project = await _project_shared_with_the_initiative(
        session, initiative, manager.user
    )
    member = await acting_user(guild_role=CommunityRole.member, guild=manager.guild)

    before = await client.get(
        member.g(f"/projects/{project.id}"), headers=member.headers
    )
    assert before.status_code == 404

    if way_in == "join":
        joined = await client.post(
            member.g(f"/initiatives/{initiative.id}/join"), headers=member.headers
        )
        assert joined.status_code == 200, joined.text
    else:
        created = await client.post(
            member.g(f"/initiatives/{initiative.id}/join-requests"),
            headers=member.headers,
            json={},
        )
        assert created.status_code == 201, created.text
        approved = await client.post(
            manager.g(
                f"/initiatives/{initiative.id}"
                f"/join-requests/{created.json()['id']}/approve"
            ),
            headers=manager.headers,
        )
        assert approved.status_code == 200, approved.text
        body = approved.json()
        assert body["status"] == "approved"
        assert body["resolved_by"] == manager.user.id
        assert body["resolved_at"] is not None

    membership = await initiatives_service.get_initiative_membership_with_role(
        session, initiative_id=initiative.id, user_id=member.user.id
    )
    assert membership is not None
    assert membership.role_ref.name == "member"
    assert membership.role_ref.is_manager is False
    assert membership.oidc_provider_id is None

    after = await client.get(
        member.g(f"/projects/{project.id}"), headers=member.headers
    )
    assert after.status_code == 200
    assert after.json()["name"] == "Shared work"


async def test_approving_an_already_resolved_request_conflicts(
    client: AsyncClient, session: AsyncSession, acting_user
):
    manager = await acting_user(guild_role=CommunityRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    member = await acting_user(guild_role=CommunityRole.member, guild=manager.guild)
    created = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={},
    )
    request_id = created.json()["id"]
    url = manager.g(f"/initiatives/{initiative.id}/join-requests/{request_id}/approve")
    assert (await client.post(url, headers=manager.headers)).status_code == 200

    again = await client.post(url, headers=manager.headers)

    assert again.status_code == 409
    assert again.json()["detail"] == "INITIATIVE_JOIN_REQUEST_ALREADY_RESOLVED"


async def test_resolving_a_request_someone_else_answered_conflicts(
    session: AsyncSession, acting_user
):
    """A decision is claimed before it is granted.

    The guard is the ``WHERE status = 'pending'`` on the write, not the check
    the caller did first — so a second answer matches no row and is refused,
    and nothing is granted behind it. That is what stops an approval creating a
    member that a simultaneous denial then records as refused.

    This drives the two answers sequentially rather than truly concurrently.
    It doesn't need to interleave them: the claim never consults the caller's
    in-memory snapshot, only the row's committed state, so a stale pending
    snapshot and an already-settled row take the same path. Serializing the
    two writers is Postgres's row lock, not this code.
    """
    manager = await acting_user(guild_role=CommunityRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    member = await acting_user(guild_role=CommunityRole.member, guild=manager.guild)
    request, _ = await initiatives_service.create_join_request(
        session, initiative=initiative, user_id=member.user.id, message=None
    )
    await session.commit()

    # The first manager settles it.
    await initiatives_service.resolve_join_request(
        session, request=request, resolver_id=manager.user.id, approved=False
    )
    await session.commit()

    # The second still holds the row it read while the request was pending.
    with pytest.raises(initiatives_service.JoinRequestAlreadyResolved):
        await initiatives_service.resolve_join_request(
            session, request=request, resolver_id=manager.user.id, approved=True
        )

    # The denial stands, and no membership was written behind it.
    assert request.status == "denied"
    assert (
        await initiatives_service.get_initiative_membership(
            session, initiative_id=initiative.id, user_id=member.user.id
        )
        is None
    )


async def test_approving_when_already_a_member_succeeds(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A requester who got in another way while the request sat in the queue is
    absorbed: the row resolves and the call succeeds instead of colliding with
    the membership primary key."""
    manager = await acting_user(guild_role=CommunityRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    member = await acting_user(guild_role=CommunityRole.member, guild=manager.guild)
    created = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={},
    )
    request_id = created.json()["id"]

    # Added by hand while the request waits.
    added = await client.post(
        manager.g(f"/initiatives/{initiative.id}/members"),
        headers=manager.headers,
        json={"user_id": member.user.id},
    )
    assert added.status_code == 200

    response = await client.post(
        manager.g(f"/initiatives/{initiative.id}/join-requests/{request_id}/approve"),
        headers=manager.headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    rows = (
        await session.exec(
            select(InitiativeMember).where(
                InitiativeMember.initiative_id == initiative.id,
                InitiativeMember.user_id == member.user.id,
            )
        )
    ).all()
    assert len(rows) == 1


async def test_deny_resolves_without_membership(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A denial changes nothing about what the requester can see."""
    from app.testing.factories import create_project

    manager = await acting_user(guild_role=CommunityRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    project = await create_project(
        session, initiative, manager.user, name="Shared work"
    )
    member = await acting_user(guild_role=CommunityRole.member, guild=manager.guild)
    created = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={},
    )
    request_id = created.json()["id"]

    response = await client.post(
        manager.g(f"/initiatives/{initiative.id}/join-requests/{request_id}/deny"),
        headers=manager.headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "denied"
    assert response.json()["resolved_by"] == manager.user.id
    assert (
        await initiatives_service.get_initiative_membership(
            session, initiative_id=initiative.id, user_id=member.user.id
        )
    ) is None
    still_hidden = await client.get(
        member.g(f"/projects/{project.id}"), headers=member.headers
    )
    assert still_hidden.status_code == 404


async def test_resolving_a_request_from_another_initiative_is_not_found(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The request id is only meaningful inside its own door."""
    manager = await acting_user(guild_role=CommunityRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    other = await create_initiative(
        session, manager.guild, manager.user, name="Elsewhere", join_policy="request"
    )
    member = await acting_user(guild_role=CommunityRole.member, guild=manager.guild)
    created = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={},
    )
    request_id = created.json()["id"]

    response = await client.post(
        manager.g(f"/initiatives/{other.id}/join-requests/{request_id}/approve"),
        headers=manager.headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "INITIATIVE_JOIN_REQUEST_NOT_FOUND"


async def _resolver(acting_user, session: AsyncSession, kind: str, owner, initiative):
    """The caller trying to answer somebody else's request."""
    if kind == "member":
        return await _caller(acting_user, "member", owner, initiative)

    holder = await acting_user("support" if kind == "support grant" else "operator")
    held = (
        (("content", "read_write"), ("settings", "superadmin"))
        if kind == "break-glass"
        else (("content", "read_write"),)
    )
    for purpose, level in held:
        await _live_grant(
            session,
            user=holder.user,
            guild=owner.guild,
            approver=owner.user,
            level=level,
            purpose=purpose,
        )
    return holder


@pytest.mark.parametrize("action", ["approve", "deny"])
@pytest.mark.parametrize(
    ("caller", "detail"),
    [
        ("member", InitiativeMessages.MANAGER_REQUIRED),
        ("support grant", InitiativeMessages.GRANT_CANNOT_MANAGE_MEMBERS),
        ("operator grant", InitiativeMessages.GRANT_CANNOT_MANAGE_MEMBERS),
        ("break-glass", InitiativeMessages.GRANT_CANNOT_MANAGE_MEMBERS),
    ],
)
async def test_answering_a_join_request_takes_manager_standing(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    caller: str,
    detail: str,
    action: str,
):
    """Answering a request grants access, so it takes exactly the authority
    that adding a member by hand takes.

    A grant reaches a community for a window; the membership on the other side
    of an approval has no end date, so the two are never traded for each other
    — and holding the highest grant there is does not change that.
    """
    owner, initiative, knocks = await _knocked_on(client, session, acting_user, count=1)
    asker, request_id = knocks[0]
    actor = await _resolver(acting_user, session, caller, owner, initiative)

    response = await client.post(
        f"/api/v1/c/{owner.guild.id}/initiatives/{initiative.id}"
        f"/join-requests/{request_id}/{action}",
        headers=actor.headers,
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == detail
    # The person knocking is still outside it.
    assert (
        await initiatives_service.get_initiative_membership(
            session, initiative_id=initiative.id, user_id=asker.user.id
        )
    ) is None


async def test_a_knock_reaches_the_managers_on_both_channels(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
):
    """Addressed to the people who can answer it, and carrying who asked and
    what they wrote — the two things the decision rests on — but never any of
    the initiative's content.

    A non-manager member of the initiative is not on the hook for answering, so
    neither the bell nor the mail reaches them.
    """
    sent = _capture_join_request_emails(monkeypatch)

    manager = await acting_user(guild_role=CommunityRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    bystander = await acting_user(
        guild_role=CommunityRole.member,
        guild=manager.guild,
        initiative=initiative,
        initiative_role="member",
    )
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=manager.guild,
        username="ada",
        discriminator=1815,
    )
    member.membership.display_name = "Ada Lovelace"
    session.add(member.membership)
    await session.commit()

    response = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={"message": "I maintain the parser"},
    )
    assert response.status_code == 201

    notes = await _notifications_for(
        session, manager.user.id, NotificationType.initiative_join_requested
    )
    assert len(notes) == 1
    assert notes[0].data["initiative_id"] == initiative.id
    assert notes[0].data["requester_id"] == member.user.id
    # Both name her as the community she asked in names her.
    assert notes[0].data["requester_name"] == "Ada Lovelace"
    assert notes[0].data["request_id"] == response.json()["id"]
    # It was sent to be acted on, so it opens the queue rather than the
    # initiative's front page. Only managers ever receive one.
    assert notes[0].data["target_path"] == f"/i/{initiative.id}/settings/members"

    assert [m["recipient_id"] for m in sent] == [manager.user.id]
    # Waiting on a decision, so it is filed under the category for things
    # somebody has to act on.
    assert sent[0]["category"] is NotificationCategory.approvals
    assert sent[0]["guild_id"] == manager.guild.id
    assert sent[0]["subject"] == "Request to join Knockable"
    assert "Ada Lovelace" in sent[0]["body"]
    assert "I maintain the parser" in sent[0]["body"]
    # Guild-scoped news, so the link carries the guild rather than being a bare
    # frontend path.
    assert f"community_id={manager.guild.id}" in sent[0]["link"]

    assert (
        await _notifications_for(
            session, bystander.user.id, NotificationType.initiative_join_requested
        )
        == []
    )
    assert bystander.user.id not in {m["recipient_id"] for m in sent}


@pytest.mark.parametrize(
    ("action", "expected_type", "subject"),
    [
        (
            "approve",
            NotificationType.initiative_join_approved,
            "You've joined Knockable",
        ),
        (
            "deny",
            NotificationType.initiative_join_denied,
            "Request to join Knockable declined",
        ),
    ],
)
async def test_a_resolution_reaches_the_requester_on_both_channels(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    monkeypatch,
    action: str,
    expected_type: NotificationType,
    subject: str,
):
    """The outcome goes back to the person who asked — and only to them."""
    manager = await acting_user(guild_role=CommunityRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    member = await acting_user(guild_role=CommunityRole.member, guild=manager.guild)
    created = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={},
    )
    request_id = created.json()["id"]

    # Capture only after the request's own notice is delivered, so the queue
    # mail is out of the way.
    await drain_notices()
    sent = _capture_join_request_emails(monkeypatch)

    resolved = await client.post(
        manager.g(f"/initiatives/{initiative.id}/join-requests/{request_id}/{action}"),
        headers=manager.headers,
    )
    assert resolved.status_code == 200

    notes = await _notifications_for(session, member.user.id, expected_type)
    assert len(notes) == 1
    assert notes[0].data["initiative_id"] == initiative.id
    assert "initiative_name" not in notes[0].data
    assert notes[0].data["request_id"] == request_id

    assert [m["recipient_id"] for m in sent] == [member.user.id]
    # Being told the answer is membership news, not something to act on.
    assert sent[0]["category"] is NotificationCategory.news
    assert sent[0]["subject"] == subject
    assert f"community_id={manager.guild.id}" in sent[0]["link"]


@pytest.mark.parametrize(
    ("viewer", "expected_count"),
    [
        ("manager", 1),
        ("admin inside it", 1),
        ("plain member of it", 0),
        ("guild admin outside it", 0),
        ("the requester", 0),
    ],
)
async def test_directory_badges_the_queue_for_whoever_could_answer_it(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    viewer: str,
    expected_count: int,
):
    """The pending count rides the directory the guild home already loads, and
    only for whoever could open the queue — a bystander reads a flat zero
    rather than a headcount of their peers' knocking.

    A guild admin inside the initiative reads the badge whatever their
    membership row says, because answering is authority they hold as admin; one
    outside it is a bystander like anyone else, and staffs themselves onto the
    initiative to take the queue. The person waiting sees their own request
    reflected back instead.
    """
    manager = await acting_user(guild_role=CommunityRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    requester = await acting_user(guild_role=CommunityRole.member, guild=manager.guild)
    created = await client.post(
        requester.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=requester.headers,
        json={},
    )
    assert created.status_code == 201

    if viewer == "manager":
        actor = manager
    elif viewer == "the requester":
        actor = requester
    elif viewer == "guild admin outside it":
        actor = await acting_user(guild_role=CommunityRole.admin, guild=manager.guild)
    else:
        actor = await acting_user(
            guild_role=(
                CommunityRole.admin
                if viewer == "admin inside it"
                else CommunityRole.member
            ),
            guild=manager.guild,
            initiative=initiative,
            initiative_role="member",
        )

    response = await client.get(
        actor.g("/initiatives/directory"), headers=actor.headers
    )

    assert response.status_code == 200
    entry = next(e for e in response.json() if e["id"] == initiative.id)
    assert entry["pending_join_request_count"] == expected_count
    assert entry["has_pending_request"] is (viewer == "the requester")


async def test_a_knock_writes_its_mail_down(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
):
    """The manager's mail reaches the queue the worker drains.

    Written on the guild-routed session the request is already holding, which
    is the path every notification email out of a community takes — and the
    half the tests either side of this one, both counting to zero, cannot show.
    """

    async def _email_configured(_session) -> bool:
        return True

    monkeypatch.setattr(email_service, "email_configured", _email_configured)

    manager = await acting_user(guild_role=CommunityRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    member = await acting_user(guild_role=CommunityRole.member, guild=manager.guild)

    response = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={"message": "I maintain the parser"},
    )

    assert response.status_code == 201, response.text
    assert await _pending_mail_for(session, manager.user.id) == 1


@pytest.mark.parametrize(
    "reason", ["the manager switched approvals off", "no SMTP configured"]
)
async def test_a_knock_lands_even_when_no_mail_goes_out(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch, reason: str
):
    """Mail is best effort, and the bell is not.

    A join request waits on the manager's decision, so it resolves under
    ``approvals`` — the category for things somebody has to act on — and a
    manager who turned that category's mail off still gets the in-app
    notification. So does one on a deployment with no SMTP at all, where
    nothing is written down for a worker that could never drain it.

    Two different gates, so both are read where the mail would be: the
    preference is answered before the queue, the missing mail server by the
    queue itself.
    """
    can_send = reason != "no SMTP configured"

    async def _email_configured(_session) -> bool:
        return can_send

    monkeypatch.setattr(email_service, "email_configured", _email_configured)

    manager = await acting_user(guild_role=CommunityRole.member)
    if can_send:
        await set_notification_prefs(
            session, manager.user, {"categories": {"approvals": {"email": False}}}
        )

    initiative = await _requestable(session, manager, name="Knockable")
    member = await acting_user(guild_role=CommunityRole.member, guild=manager.guild)

    response = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={},
    )

    assert response.status_code == 201
    assert await _pending_mail_for(session, manager.user.id) == 0
    assert (
        len(
            await _notifications_for(
                session, manager.user.id, NotificationType.initiative_join_requested
            )
        )
        == 1
    )


async def test_initiative_member_search_finds_a_misspelled_name(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """One rule for looking people up, wherever the picker is. An initiative's
    roster matches a near miss exactly as the guild's does."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
        username="moonwhisper",
    )

    response = await client.get(
        a.g(f"/initiatives/{a.initiative.id}/members/search"),
        headers=a.headers,
        params={"search": "moonwhsiper"},
    )
    assert response.status_code == 200, response.text
    assert member.user.username in {u["username"] for u in response.json()["items"]}


async def test_changing_what_an_initiative_allows_rechecks_its_members(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
):
    """Switching a tool off or changing what a role may do re-checks the open
    connections of the people it applies to once it commits."""
    from app.api.v1.tenant_endpoints import initiatives as initiatives_routes
    from app.models.tenant.initiative import InitiativeRoleModel

    manager = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    member = await acting_user(
        guild=manager.guild, initiative=manager.initiative, initiative_role="member"
    )
    initiative_id = manager.initiative.id
    rechecked: list[set[int]] = []

    async def _record(guild_id, user_ids):
        rechecked.append(set(user_ids))

    monkeypatch.setattr(initiatives_routes.content_sockets, "refresh_users", _record)

    switched = await client.patch(
        manager.g(f"/initiatives/{initiative_id}"),
        headers=manager.headers,
        json={"files_enabled": False},
    )
    assert switched.status_code == 200, switched.text
    assert rechecked.pop() == {manager.user.id, member.user.id}

    member_role = (
        await session.exec(
            select(InitiativeRoleModel).where(
                InitiativeRoleModel.initiative_id == initiative_id,
                InitiativeRoleModel.name == "member",
            )
        )
    ).one()
    roles = await client.get(
        manager.g(f"/initiatives/{initiative_id}/roles"), headers=manager.headers
    )
    (current,) = [r for r in roles.json() if r["id"] == member_role.id]
    flipped = not current["permissions"]["create_files"]
    changed = await client.patch(
        manager.g(f"/initiatives/{initiative_id}/roles/{member_role.id}"),
        headers=manager.headers,
        json={"permissions": {"create_files": flipped}},
    )
    assert changed.status_code == 200, changed.text
    assert rechecked.pop() == {member.user.id}


async def test_a_communitys_defaults_stand_over_every_initiative(
    client: AsyncClient, acting_user, session: AsyncSession
):
    """What a community's admins set for every initiative wins over each
    initiative's own, reaches its members' standing, is refused to its
    managers, and hands back the initiative's own value when cleared."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    initiative_id = admin.initiative.id
    pm = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="project_manager",
    )
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    defaults_url = admin.g("/initiatives/defaults")
    initiative_url = pm.g(f"/initiatives/{initiative_id}")
    own = await client.patch(
        initiative_url, headers=pm.headers, json={"posts_enabled": False}
    )
    assert own.status_code == 200, own.text
    # A custom role that predates the community keeping initiatives to their
    # built-in roles.
    editors = await client.post(
        f"{initiative_url}/roles",
        headers=pm.headers,
        json={"name": "editors", "display_name": "Editors"},
    )
    assert editors.status_code == 201, editors.text
    roles = (await client.get(f"{initiative_url}/roles", headers=pm.headers)).json()
    member_role = next(r for r in roles if r["name"] == "member")
    hidden = await client.patch(
        f"{initiative_url}/roles/{member_role['id']}",
        headers=pm.headers,
        json={"permissions": {"posts_enabled": False}},
    )
    assert hidden.status_code == 200, hidden.text

    async def members_view() -> dict:
        seen = await client.get(
            member.g(f"/initiatives/{initiative_id}"), headers=member.headers
        )
        assert seen.status_code == 200, seen.text
        return seen.json()

    refused = await client.patch(
        defaults_url, headers=pm.headers, json={"tools": {"post": True}}
    )
    assert refused.status_code == 403
    assert refused.json()["detail"] == InitiativeMessages.DEFAULTS_ADMIN_ONLY

    set_ = {
        "tools": {"post": True},
        "member_permissions": {"posts_enabled": True},
        "custom_roles": False,
    }
    made = await client.patch(defaults_url, headers=admin.headers, json=set_)
    assert made.status_code == 200, made.text
    assert made.json() == set_
    read = await client.get(member.g("/initiatives/defaults"), headers=member.headers)
    assert read.json() == set_
    seen = await members_view()
    assert seen["posts_enabled"] is True
    assert Tool.post.value in seen["can"]["view"]

    switch = await client.patch(
        initiative_url, headers=pm.headers, json={"posts_enabled": False}
    )
    assert switch.status_code == 409
    assert switch.json()["detail"] == InitiativeMessages.SET_BY_COMMUNITY
    roles = (await client.get(f"{initiative_url}/roles", headers=pm.headers)).json()
    member_role = next(r for r in roles if r["name"] == "member")
    assert member_role["permissions"]["posts_enabled"] is True
    # Held to the members' answer while custom roles are off.
    assert (
        next(r for r in roles if r["name"] == "editors")["permissions"]["posts_enabled"]
        is True
    )
    permission = await client.patch(
        f"{initiative_url}/roles/{member_role['id']}",
        headers=pm.headers,
        json={"permissions": {"posts_enabled": False}},
    )
    assert permission.status_code == 409
    # The grid sends the whole map; the community's keys in it are not kept
    # as the role's own.
    other = await client.patch(
        f"{initiative_url}/roles/{member_role['id']}",
        headers=pm.headers,
        json={"permissions": {**member_role["permissions"], "create_files": True}},
    )
    assert other.status_code == 200, other.text
    added = await client.post(
        f"{initiative_url}/roles",
        headers=pm.headers,
        json={"name": "editors", "display_name": "Editors"},
    )
    assert added.status_code == 403
    assert added.json()["detail"] == InitiativeMessages.CUSTOM_ROLES_OFF

    cleared = await client.patch(
        defaults_url,
        headers=admin.headers,
        json={
            "tools": {"post": None},
            "member_permissions": {"posts_enabled": None},
            "custom_roles": True,
        },
    )
    assert cleared.json() == {
        "tools": {},
        "member_permissions": {},
        "custom_roles": True,
    }
    seen = await members_view()
    assert seen["posts_enabled"] is False
    assert Tool.post.value not in seen["can"]["view"]
    roles = (await client.get(f"{initiative_url}/roles", headers=pm.headers)).json()
    member_role = next(r for r in roles if r["name"] == "member")
    assert member_role["permissions"]["posts_enabled"] is False
    assert member_role["permissions"]["create_files"] is True

    # A read with no standing (the system's own) takes the community's
    # switch from its row.
    await client.patch(
        defaults_url, headers=admin.headers, json={"tools": {"post": True}}
    )
    await route_session_to_guild(session, admin.guild.id)
    on = await session.scalar(
        select(Initiative.id).where(
            Initiative.id == initiative_id, tool_on_sql(Tool.post)
        )
    )
    assert on == initiative_id
