"""What a member keeps about items: opens (the tabs bar), bookmarks and subscriptions.

Covers ``GET /api/v1/me/personal-items`` (every community's tabs or bookmarks),
a community's own list, one item's state, and the guild-addressed routes that
set and clear each mark. Opening and subscribing are proved over the whole
``Tool`` enum and over every kind inside one, so a new kind is exercised here
the moment it exists.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import DBAPIError
from sqlmodel import col, delete, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import CHILD_KINDS, KINDS, Tool
from app.models.platform.guild import CommunityRole
from app.models.tenant.initiative import InitiativeMember
from app.models.tenant.personal_item import PersonalItem
from app.models.tenant.project import Project
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.services.guild_sweeps import Scope, each_guild
from app.services.tenant import expiry
from app.services.tenant.personal_items import DEFAULT_RECENT_VIEWS, WINDOW
from app.testing import (
    create_calendar,
    create_child_entity,
    create_counter_group,
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_project,
    create_resource_grant,
    create_task,
    create_tool_entity,
    create_user,
    enable_all_tools,
    route_as,
    route_session_to_guild,
)

TABS = "/api/v1/me/personal-items?mark=view"
MY_BOOKMARKS = "/api/v1/me/personal-items?mark=bookmark"
BOOKMARKS = "/personal-items?mark=bookmark"

#: Every tool, as its own test case.
TOOLS = pytest.mark.parametrize("tool", list(Tool), ids=[t.value for t in Tool])


async def test_recents_mixed_ordering(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Items from different entity types are ordered by their latest open."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    project = await create_project(session, a.initiative, a.user, name="Older project")
    group = await create_counter_group(
        session, a.initiative, a.user, name="Newer counter group"
    )

    r1 = await client.put(
        a.g(f"/personal-items/view/project/{project.id}"), headers=a.headers
    )
    assert r1.status_code == 200
    # Small delay so timestamps differ deterministically.
    await asyncio.sleep(0.05)
    r2 = await client.put(
        a.g(f"/personal-items/view/counter_group/{group.id}"), headers=a.headers
    )
    assert r2.status_code == 200

    r = await client.get(TABS, headers=a.headers)
    items = r.json()
    # Newer counter group must come first.
    assert items[0]["entity_type"] == "counter_group"
    assert items[0]["entity_id"] == group.id
    assert items[1]["entity_type"] == "project"
    assert items[1]["entity_id"] == project.id


async def test_recents_are_cross_guild_names_only(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The tabs bar shows entities from ANY of the user's guilds, from any
    context — render metadata only, tagged with the owning guild. Another
    user never sees them."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    project_a = await create_project(session, a.initiative, a.user, name="A's project")

    # The same user also belongs to a second guild.
    guild_b = await create_guild(session)
    await create_guild_membership(session, user=a.user, guild=guild_b)
    assert guild_b.id != a.guild.id

    # A different member of guild A.
    other = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    # Record the view while in guild A...
    r = await client.put(
        a.g(f"/personal-items/view/project/{project_a.id}"), headers=a.headers
    )
    assert r.status_code == 200

    # ...then enter guild B: the tab still renders (name + owning guild).
    r = await client.get(TABS, headers=a.headers)
    assert r.status_code == 200
    items = r.json()
    assert [(i["entity_type"], i["entity_id"], i["community_id"]) for i in items] == [
        ("project", project_a.id, a.guild.id)
    ]
    assert items[0]["name"] == "A's project"

    # The list is the user's own: another member of guild A sees nothing.
    r = await client.get(TABS, headers=other.headers)
    assert r.status_code == 200
    assert r.json() == []


async def test_a_recent_view_is_its_owners_row(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    """Neither another member who can edit the same project nor the
    community's admin reads or writes someone's recent view of it in the
    database."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    project = await create_project(session, a.initiative, a.user)
    other = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_resource_grant(
        session, project, user=other.user, level=ResourceAccessLevel.write
    )
    admin = await acting_user(guild_role=CommunityRole.admin, guild=a.guild)
    r = await client.put(
        a.g(f"/personal-items/view/project/{project.id}"), headers=a.headers
    )
    assert r.status_code == 200

    for outsider in (other, admin):
        asking = await role_session("app_user")
        await route_as(asking, user_id=outsider.user.id, guild_id=a.guild.id)
        assert (await asking.exec(select(Project.id))).all() == [project.id]
        assert (await asking.exec(select(PersonalItem))).all() == []
        asking.add(
            PersonalItem(
                user_id=a.user.id,
                entity_type="project",
                entity_id=project.id,
                bookmarked_at=datetime.now(UTC),
            )
        )
        with pytest.raises(DBAPIError, match="row-level security"):
            await asking.flush()


async def test_recent_tabs_limit_caps_list_and_prune(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The user's ``recent_tabs_limit`` bounds what the tabs-bar endpoint
    returns. The hourly pass keeps every open for ``WINDOW``; past it, each
    person keeps that many tabs, the default for whoever never set one,
    whether or not anyone else did, and nothing that is not a tab."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    b = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    c = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    # Rows name real things: a view is reached through what it names.
    opened = [
        await create_project(session, a.initiative, a.user)
        for _ in range(DEFAULT_RECENT_VIEWS + 1)
    ]
    past = datetime.now(UTC) - WINDOW - timedelta(hours=1)
    for person, count in ((b, len(opened)), (c, 4)):
        for i, project in enumerate(opened[:count]):
            session.add(
                PersonalItem(
                    user_id=person.user.id,
                    entity_type="project",
                    entity_id=project.id,
                    viewed_at=past - timedelta(minutes=i),
                    view_source="direct",
                )
            )
    await session.commit()
    newest = sorted(p.id for p in opened)

    async def kept(person) -> list[int]:
        rows = await session.exec(
            select(PersonalItem.entity_id).where(
                PersonalItem.user_id == person.user.id,
                col(PersonalItem.viewed_at).is_not(None),
            )
        )
        return sorted(rows.all())

    async def expire() -> None:
        await each_guild(
            [(Scope.PROVISIONED, await expiry.prepare())],
            name="test",
            only=[a.guild.id],
        )

    # Everyone on the default: each keeps their newest twenty.
    await expire()
    assert await kept(b) == newest[:DEFAULT_RECENT_VIEWS]
    assert await kept(c) == newest[:4]

    # Lower the user's recents cap to 2 via self-update.
    r = await client.patch(
        "/api/v1/me", json={"recent_tabs_limit": 2}, headers=a.headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["recent_tabs_limit"] == 2

    # Open four projects, oldest first.
    projects = [
        await create_project(session, a.initiative, a.user, name=f"P{i}")
        for i in range(4)
    ]
    for project in projects:
        rv = await client.put(
            a.g(f"/personal-items/view/project/{project.id}"), headers=a.headers
        )
        assert rv.status_code == 200
        await asyncio.sleep(0.02)

    # Only the two most-recently-opened show; something inside a tool never
    # does.
    task = await create_task(session, projects[0])
    rv = await client.put(
        a.g(f"/personal-items/view/task/{task.id}"), headers=a.headers
    )
    assert rv.status_code == 200
    r = await client.get(TABS, headers=a.headers)
    assert r.status_code == 200
    items = r.json()
    assert [i["entity_id"] for i in items] == [projects[3].id, projects[2].id]

    # Inside the window, the pass keeps every open.
    opens = sorted([*(p.id for p in projects), task.id])
    await expire()
    assert await kept(a) == opens

    # Past it, each person keeps their own number of tabs, the default for
    # whoever never set one, and nothing inside a tool.
    await session.exec(
        update(PersonalItem)
        .where(col(PersonalItem.user_id) == a.user.id)
        .values(viewed_at=col(PersonalItem.viewed_at) - WINDOW - timedelta(hours=1))
    )
    c.user.recent_tabs_limit = 3
    session.add(c.user)
    await session.commit()
    # A bookmark keeps its row when the open it shared the row with goes.
    bookmarked = await client.put(
        a.g(f"/personal-items/bookmark/project/{projects[0].id}"), headers=a.headers
    )
    assert bookmarked.status_code == 200, bookmarked.text
    await expire()
    assert await kept(a) == sorted([projects[3].id, projects[2].id])
    assert await kept(b) == newest[:DEFAULT_RECENT_VIEWS]
    assert await kept(c) == newest[:3]
    left = (
        await session.exec(
            select(PersonalItem).where(
                PersonalItem.user_id == a.user.id,
                PersonalItem.entity_id == projects[0].id,
                PersonalItem.entity_type == "project",
            )
        )
    ).one()
    assert (left.viewed_at, left.view_source, left.bookmarked_at is not None) == (
        None,
        None,
        True,
    )


async def test_recent_tabs_limit_rejects_out_of_range(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The cap is validated to [1, 100]."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)

    r = await client.patch(
        "/api/v1/me", json={"recent_tabs_limit": 0}, headers=a.headers
    )
    assert r.status_code == 422
    r = await client.patch(
        "/api/v1/me", json={"recent_tabs_limit": 101}, headers=a.headers
    )
    assert r.status_code == 422


async def test_clear_recent_is_guild_addressed(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Closing a tab works from any context via the guild path segment."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    project = await create_project(session, a.initiative, a.user, name="P")

    other_guild = await create_guild(session)
    await create_guild_membership(session, user=a.user, guild=other_guild)

    await client.put(
        a.g(f"/personal-items/view/project/{project.id}"), headers=a.headers
    )

    # Close guild A's tab while in guild B — addressed by the guild path.
    r = await client.delete(
        f"/api/v1/c/{a.guild.id}/personal-items/view/project/{project.id}",
        headers=a.headers,
    )
    assert r.status_code == 204

    r = await client.get(TABS, headers=a.headers)
    assert r.status_code == 200
    assert r.json() == []


async def test_recent_guild_level_calendar_has_no_initiative(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild-level calendar reports ``initiative_id: None`` — the tabs bar
    reads that as "address me at the guild route", not as missing data."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    a.initiative.calendars_enabled = True
    session.add(a.initiative)
    await session.commit()
    calendar = await create_calendar(session, a.initiative, a.user, name="GuildCal")
    calendar.initiative_id = None
    session.add(calendar)
    await session.commit()

    r = await client.put(
        a.g(f"/personal-items/view/calendar/{calendar.id}"), headers=a.headers
    )
    assert r.status_code == 200, r.text

    r = await client.get(TABS, headers=a.headers)
    assert r.status_code == 200
    row = next(i for i in r.json() if i["entity_id"] == calendar.id)
    assert row["initiative_id"] is None


@TOOLS
async def test_opening_a_tab_puts_the_tool_in_the_tabs_bar(
    client: AsyncClient, session: AsyncSession, acting_user, tool: Tool
):
    """Recording a view reads the entity as its own page does, and a guild
    member outside the initiative is refused in the tool's own words."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    await enable_all_tools(session, a.initiative)
    entity = await create_tool_entity(session, tool, a.initiative, a.user)

    response = await client.put(
        a.g(f"/personal-items/view/{tool.value}/{entity.id}"), headers=a.headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["entity_type"], body["entity_id"]) == (tool.value, entity.id)
    assert body["viewed_at"]

    listed = await client.get(TABS, headers=a.headers)
    assert listed.status_code == 200, listed.text
    assert [(i["entity_type"], i["entity_id"]) for i in listed.json()] == [
        (tool.value, entity.id)
    ]

    outsider = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    refused = await client.put(
        outsider.g(f"/personal-items/view/{tool.value}/{entity.id}"),
        headers=outsider.headers,
    )
    assert refused.status_code == 404, refused.text
    assert refused.json() == tool.not_found().body
    assert (await client.get(TABS, headers=outsider.headers)).json() == []


@pytest.mark.parametrize("kind", CHILD_KINDS)
async def test_opening_something_inside_a_tool_is_recorded_and_never_a_tab(
    client: AsyncClient, session: AsyncSession, acting_user, kind: str
):
    """Something inside a tool is recorded with where the open came from, is
    read as its own page reads it, and never becomes a tab. A guild member
    outside the initiative is refused in its tool's own words."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    await enable_all_tools(session, a.initiative)
    parent = KINDS[kind].parent
    assert parent is not None
    tool = await create_tool_entity(session, parent, a.initiative, a.user)
    entity = await create_child_entity(session, kind, tool, a.user)

    response = await client.put(
        a.g(f"/personal-items/view/{kind}/{entity.id}?source=search"), headers=a.headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["entity_type"], body["entity_id"], body["view_source"]) == (
        kind,
        entity.id,
        "search",
    )
    row = (
        await session.exec(
            select(PersonalItem).where(
                PersonalItem.user_id == a.user.id, PersonalItem.entity_type == kind
            )
        )
    ).one()
    assert (row.entity_id, row.view_source) == (entity.id, "search")
    assert (await client.get(TABS, headers=a.headers)).json() == []

    outsider = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    refused = await client.put(
        outsider.g(f"/personal-items/view/{kind}/{entity.id}"), headers=outsider.headers
    )
    assert refused.status_code == 404, refused.text
    assert refused.json() == KINDS[kind].not_found().body

    # Subscribed too, and the subscription comes off leaving the open.
    subscribed = await client.put(
        a.g(f"/personal-items/subscribe/{kind}/{entity.id}"), headers=a.headers
    )
    assert subscribed.status_code == 200, subscribed.text
    assert subscribed.json()["subscribed_at"]
    unsubscribed = await client.delete(
        a.g(f"/personal-items/subscribe/{kind}/{entity.id}"), headers=a.headers
    )
    assert unsubscribed.status_code == 204
    state = await client.get(
        a.g(f"/personal-items/{kind}/{entity.id}"), headers=a.headers
    )
    assert (
        state.json()["subscribed_at"],
        state.json()["subscribed"],
        state.json()["view_source"],
    ) == (None, False, "search")
    refused = await client.put(
        outsider.g(f"/personal-items/subscribe/{kind}/{entity.id}"),
        headers=outsider.headers,
    )
    assert refused.status_code == 404, refused.text
    # Only a tool is bookmarked.
    bookmark = await client.put(
        a.g(f"/personal-items/bookmark/{kind}/{entity.id}"), headers=a.headers
    )
    assert bookmark.status_code == 422


async def test_any_tool_can_be_bookmarked_and_listed_newest_first(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    project = await create_project(
        session, a.initiative, a.user, name="Fete", icon="🎪"
    )
    group = await create_counter_group(session, a.initiative, a.user, name="Tally")

    first = await client.put(
        a.g(f"/personal-items/bookmark/project/{project.id}"), headers=a.headers
    )
    assert first.status_code == 200, first.text
    await asyncio.sleep(0.02)
    second = await client.put(
        a.g(f"/personal-items/bookmark/counter_group/{group.id}"), headers=a.headers
    )
    assert second.status_code == 200, second.text
    # Bookmarking again keeps the bookmark, and its time.
    again = await client.put(
        a.g(f"/personal-items/bookmark/project/{project.id}"), headers=a.headers
    )
    assert again.json()["bookmarked_at"] == first.json()["bookmarked_at"]

    listed = await client.get(a.g(BOOKMARKS), headers=a.headers)
    assert listed.status_code == 200, listed.text
    items = listed.json()
    assert [(i["entity_type"], i["entity_id"], i["name"]) for i in items] == [
        ("counter_group", group.id, "Tally"),
        ("project", project.id, "Fete"),
    ]
    assert items[1]["icon"] == "🎪"
    assert items[1]["initiative_id"] == a.initiative.id
    assert items[1]["community_id"] == a.guild.id


async def test_a_bookmark_and_a_subscription_come_off(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """One item's state says what the reader keeps; each mark comes off on its
    own, idempotently. Unsubscribing is kept: they made it, which subscribes
    them, until they say otherwise."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    project = await create_project(session, a.initiative, a.user)
    state_path = a.g(f"/personal-items/project/{project.id}")

    for mark in ("bookmark", "subscribe"):
        response = await client.put(
            a.g(f"/personal-items/{mark}/project/{project.id}"), headers=a.headers
        )
        assert response.status_code == 200, response.text
    state = (await client.get(state_path, headers=a.headers)).json()
    assert (
        state["bookmarked_at"] and state["subscribed_at"] and state["viewed_at"] is None
    )

    for _ in range(2):
        removed = await client.delete(
            a.g(f"/personal-items/bookmark/project/{project.id}"), headers=a.headers
        )
        assert removed.status_code == 204
    assert (await client.get(a.g(BOOKMARKS), headers=a.headers)).json() == []
    state = (await client.get(state_path, headers=a.headers)).json()
    assert state["bookmarked_at"] is None and state["subscribed_at"]

    await client.delete(
        a.g(f"/personal-items/subscribe/project/{project.id}"), headers=a.headers
    )
    state = (await client.get(state_path, headers=a.headers)).json()
    assert (state["subscribed_at"], state["subscribed"]) == (None, False)
    await route_session_to_guild(session, a.guild.id)
    (row,) = (await session.exec(select(PersonalItem))).all()
    assert (row.subscribed_at, row.bookmarked_at) == (None, None)
    assert row.unsubscribed_at is not None


async def test_making_or_being_named_on_something_subscribes(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Nobody subscribed by hand: the maker of a project, and the assignee of
    a task in it, are subscribed to the task, and an unsubscription from it
    holds whatever ties them."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    project = await create_project(session, a.initiative, a.user)
    await create_resource_grant(session, project, user=b.user)
    task = await create_task(session, project, assignees=[b.user])
    path = f"/personal-items/task/{task.id}"

    for actor in (a, b):
        state = (await client.get(actor.g(path), headers=actor.headers)).json()
        assert (state["subscribed"], state["subscribed_at"]) == (True, None)

    off = await client.delete(
        b.g(f"/personal-items/subscribe/task/{task.id}"), headers=b.headers
    )
    assert off.status_code == 204, off.text
    assert (await client.get(b.g(path), headers=b.headers)).json()[
        "subscribed"
    ] is False
    on = await client.put(
        b.g(f"/personal-items/subscribe/task/{task.id}"), headers=b.headers
    )
    assert on.json()["subscribed"] is True


async def test_a_tool_the_reader_cannot_open_cannot_be_bookmarked_or_subscribed_to(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Both take read access, as the tool's own page does: a counter group in
    an initiative the reader is not in is not there for them."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    owner = await create_user(session)
    elsewhere = await create_initiative(session, a.guild, owner)
    hidden = await create_counter_group(session, elsewhere, owner)

    for mark in ("bookmark", "subscribe"):
        response = await client.put(
            a.g(f"/personal-items/{mark}/counter_group/{hidden.id}"),
            headers=a.headers,
        )
        assert response.status_code == 404
    assert (await client.get(a.g(BOOKMARKS), headers=a.headers)).json() == []


async def test_my_bookmarks_gather_every_community(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    # A second community, which the same person then joins.
    second = await acting_user(guild_role=CommunityRole.member, initiative=True)
    first_project = await create_project(session, a.initiative, a.user, name="Here")
    await client.put(
        a.g(f"/personal-items/bookmark/project/{first_project.id}"), headers=a.headers
    )

    await create_guild_membership(session, user=a.user, guild=second.guild)
    await create_initiative_member(session, second.initiative, a.user)
    there = await create_counter_group(session, second.initiative, a.user, name="There")
    bookmarked = await client.put(
        f"/api/v1/c/{second.guild.id}/personal-items/bookmark/counter_group/{there.id}",
        headers=a.headers,
    )
    assert bookmarked.status_code == 200, bookmarked.text

    mine = await client.get(MY_BOOKMARKS, headers=a.headers)
    assert mine.status_code == 200, mine.text
    assert [(i["community_id"], i["name"]) for i in mine.json()] == [
        (second.guild.id, "There"),
        (a.guild.id, "Here"),
    ]


async def test_leaving_a_community_takes_what_they_kept(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    project = await create_project(session, a.initiative, a.user)
    for mark in ("bookmark", "subscribe", "view"):
        await client.put(
            a.g(f"/personal-items/{mark}/project/{project.id}"), headers=a.headers
        )

    left = await client.delete(
        f"/api/v1/communities/{a.guild.id}/leave", headers=a.headers
    )
    assert left.status_code == 204, left.text

    # Back in, nothing is waiting for them.
    await create_guild_membership(session, user=a.user, guild=a.guild)
    await create_initiative_member(session, a.initiative, a.user)
    state = await client.get(
        a.g(f"/personal-items/project/{project.id}"), headers=a.headers
    )
    assert [
        state.json()[k] for k in ("viewed_at", "bookmarked_at", "subscribed_at")
    ] == [
        None,
        None,
        None,
    ]


async def test_marks_come_off_a_tool_the_reader_has_lost(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Out of the initiative, a bookmark and a subscription still come off rather than
    waiting for them to be let back in."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    project = await create_project(session, a.initiative, b.user)
    for mark in ("bookmark", "subscribe"):
        response = await client.put(
            b.g(f"/personal-items/{mark}/project/{project.id}"), headers=b.headers
        )
        assert response.status_code == 200, response.text

    await route_session_to_guild(session, a.guild.id)
    await session.exec(
        delete(InitiativeMember).where(  # type: ignore[arg-type]
            col(InitiativeMember.user_id) == b.user.id
        )
    )
    await session.commit()

    # Out of reach now.
    gone = await client.get(b.g(f"/projects/{project.id}"), headers=b.headers)
    assert gone.status_code == 404, gone.text

    for mark in ("bookmark", "subscribe"):
        removed = await client.delete(
            b.g(f"/personal-items/{mark}/project/{project.id}"), headers=b.headers
        )
        assert removed.status_code == 204

    session.expunge_all()
    await route_session_to_guild(session, a.guild.id)
    (row,) = (await session.exec(select(PersonalItem))).all()
    assert (row.bookmarked_at, row.subscribed_at) == (None, None)
    assert row.unsubscribed_at is not None
