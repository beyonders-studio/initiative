"""Subscribers hear of what other people change on what they are subscribed
to, read as themselves: whoever made it or its tool, whoever is named on it,
and whoever subscribed by hand, from then on; never their own changes, nothing
after they unsubscribe, and nothing the platform holds."""

from datetime import UTC, datetime
from typing import cast

from sqlalchemy import text, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import cohorts
from app.db.request_context import SystemGuild
from app.db.session import set_rls_context
from app.models.platform.guild import CommunityRole
from app.models.platform.notification import Notification, NotificationType
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.services.tenant import subscription_notices
from app.testing import (
    create_calendar,
    create_calendar_event,
    create_post,
    create_resource_grant,
    create_task,
    drain_notices,
)

SUBSCRIBED = NotificationType.subscription_activity
ASSIGNED = NotificationType.assigned_activity


async def _tell(guild_id: int) -> None:
    """Run the sweep's visit as the sweep does, then deliver what it wrote."""
    async with cohorts.system_session(guild_id) as system:
        await subscription_notices.tell_subscribers(system, guild_id)
        await system.commit()
    await drain_notices()


async def _lines(
    session: AsyncSession, user_id: int, kind: NotificationType
) -> list[Notification]:
    return list(
        await session.exec(
            select(Notification)
            .where(Notification.user_id == user_id, Notification.type == kind)
            .execution_options(populate_existing=True)
        )
    )


async def test_subscribers_hear_of_what_others_change(
    client, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    b, c = [
        await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        for _ in range(2)
    ]
    for other in (b, c):
        await create_resource_grant(
            session, a.project, user=other.user, level=ResourceAccessLevel.write
        )
    task_id = cast(
        int,
        (await create_task(session, a.project, title="Hall", assignees=[b.user])).id,
    )
    guild_id = cast(int, a.guild.id)
    a_id, b_id, c_id = (cast(int, x.user.id) for x in (a, b, c))
    path = f"/tasks/{task_id}"
    await _tell(guild_id)  # what the factories wrote names nobody

    # Before c subscribed: b, its assignee, hears; a made the change.
    edited = await client.patch(a.g(path), headers=a.headers, json={"title": "Book"})
    assert edited.status_code == 200, edited.text
    subscribed = await client.put(
        c.g(f"/personal-items/subscribe/project/{a.project.id}"), headers=c.headers
    )
    assert subscribed.status_code == 200, subscribed.text
    await _tell(guild_id)
    (line,) = await _lines(session, b_id, ASSIGNED)
    assert (line.data["entity_type"], line.data["entity_id"], line.data["verb"]) == (
        "task",
        task_id,
        "edited",
    )
    assert await _lines(session, c_id, SUBSCRIBED) == []
    assert await _lines(session, a_id, ASSIGNED) == []

    # b's own change: a, who made the project, and c, subscribed to it, hear.
    edited = await client.patch(b.g(path), headers=b.headers, json={"title": "Hire"})
    assert edited.status_code == 200, edited.text
    await _tell(guild_id)
    for person in (a_id, c_id):
        (line,) = await _lines(session, person, SUBSCRIBED)
        assert line.data["verb"] == "edited"
    assert len(await _lines(session, b_id, ASSIGNED)) == 1

    # A comment joins the line it is told on: the assignee's one line for the
    # task, beside its changes.
    commented = await client.post(
        a.g("/comments/"), headers=a.headers, json={"task_id": task_id, "content": "Ok"}
    )
    assert commented.status_code == 201, commented.text
    await drain_notices()
    (line,) = await _lines(session, c_id, SUBSCRIBED)
    assert line.data["verb"] == "commented"
    (line,) = await _lines(session, b_id, ASSIGNED)
    assert line.data["verb"] == "commented"
    assert await _lines(session, b_id, SUBSCRIBED) == []

    # Unsubscribed from the task, c hears no more of it; b still does.
    off = await client.delete(
        c.g(f"/personal-items/subscribe/task/{task_id}"), headers=c.headers
    )
    assert off.status_code == 204, off.text
    await session.exec(
        update(Notification)
        .where(Notification.user_id.in_([b_id, c_id]))  # type: ignore[attr-defined]
        .values(read_at=datetime.now(UTC))
    )
    await session.commit()
    edited = await client.patch(a.g(path), headers=a.headers, json={"title": "Rent"})
    assert edited.status_code == 200, edited.text
    await _tell(guild_id)
    assert [n.read_at is None for n in await _lines(session, c_id, SUBSCRIBED)] == [
        False
    ]
    assert sum(n.read_at is None for n in await _lines(session, b_id, ASSIGNED)) == 1

    # Held before the sweep came round: it reads as absent to b, so nothing.
    await session.exec(
        update(Notification)
        .where(Notification.user_id == b_id)
        .values(read_at=datetime.now(UTC))
    )
    await session.commit()
    edited = await client.patch(a.g(path), headers=a.headers, json={"title": "Lend"})
    assert edited.status_code == 200, edited.text
    async with cohorts.system_session(guild_id) as system:
        await set_rls_context(system, SystemGuild(guild_id))
        await system.exec(  # type: ignore[call-overload]
            text("UPDATE tasks SET held_at = now() WHERE id = :id"),
            params={"id": task_id},
        )
        await system.commit()
    await _tell(guild_id)
    assert all(n.read_at for n in await _lines(session, b_id, ASSIGNED))


async def test_somebody_named_outside_the_initiative_hears_nothing(
    client, session: AsyncSession, acting_user
):
    """An assignee who is not in the task's initiative is told nothing of it;
    one who can open it is."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    inside = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_resource_grant(
        session, a.project, user=inside.user, level=ResourceAccessLevel.read
    )
    outside = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    task_id = cast(
        int,
        (
            await create_task(
                session, a.project, title="Hall", assignees=[inside.user, outside.user]
            )
        ).id,
    )
    guild_id = cast(int, a.guild.id)
    await _tell(guild_id)  # what the factories wrote names nobody

    edited = await client.patch(
        a.g(f"/tasks/{task_id}"), headers=a.headers, json={"title": "Book"}
    )
    assert edited.status_code == 200, edited.text
    await _tell(guild_id)
    assert len(await _lines(session, cast(int, inside.user.id), ASSIGNED)) == 1
    assert await _lines(session, cast(int, outside.user.id), ASSIGNED) == []


async def test_an_attendee_hears_of_an_event_moving_unless_they_declined(
    client, session: AsyncSession, acting_user
):
    """Going to it is being named on it; declining it is not. An answer goes
    to whoever made the event, not to the other people going."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    b, c = [
        await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        for _ in range(2)
    ]
    calendar = await create_calendar(session, a.initiative, a.user)
    for other in (b, c):
        await create_resource_grant(session, calendar, user=other.user)
    event = await create_calendar_event(
        session, calendar, a.user, title="Review", attendees=[b.user, c.user]
    )
    guild_id = cast(int, a.guild.id)
    await _tell(guild_id)

    declined = await client.patch(
        c.g(f"/calendar-events/{event.id}/rsvp"),
        headers=c.headers,
        json={"rsvp_status": "declined"},
    )
    assert declined.status_code == 200, declined.text
    await drain_notices()
    assert (
        len(await _lines(session, cast(int, a.user.id), NotificationType.event_rsvp))
        == 1
    )
    assert (
        await _lines(session, cast(int, b.user.id), NotificationType.event_rsvp) == []
    )

    moved = await client.patch(
        a.g(f"/calendar-events/{event.id}"),
        headers=a.headers,
        json={"start_at": "2026-08-01T15:00:00Z", "end_at": "2026-08-01T16:00:00Z"},
    )
    assert moved.status_code == 200, moved.text
    await _tell(guild_id)
    (line,) = await _lines(session, cast(int, b.user.id), ASSIGNED)
    assert (line.data["entity_type"], line.data["entity_id"]) == (
        "calendar_event",
        event.id,
    )
    assert await _lines(session, cast(int, c.user.id), ASSIGNED) == []
    assert await _lines(session, cast(int, c.user.id), SUBSCRIBED) == []


async def test_a_reaction_on_a_post_reaches_its_subscribers(
    client, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    a.initiative.posts_enabled = True
    session.add(a.initiative)
    await session.commit()
    post = await create_post(session, a.initiative, a.user)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_resource_grant(session, post, user=b.user)

    reacted = await client.put(
        b.g(f"/reactions/post/{post.id}"), headers=b.headers, json={"emoji": "👍"}
    )
    assert reacted.status_code == 200, reacted.text
    await drain_notices()
    (line,) = await _lines(session, cast(int, a.user.id), SUBSCRIBED)
    assert (line.data["entity_id"], line.data["verb"]) == (post.id, "reacted")
    assert await _lines(session, cast(int, b.user.id), SUBSCRIBED) == []
