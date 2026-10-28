"""The hourly pass that works out each community's engagement levels, and the
gates on what it writes."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, update
from sqlalchemy.exc import DBAPIError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import CommunityRole, CommunityStatus
from app.models.tenant.engagement_level import EngagementLevel
from app.models.tenant.event_outbox import EventOutbox
from app.models.tenant.personal_item import PersonalItem, ViewSource
from app.services.guild_sweeps import Scope, each_guild
from app.services.tenant import engagement_levels
from app.services.tenant.engagement_levels import HALF_LIFE
from app.services.tenant.personal_items import WINDOW
from app.testing import create_task, guild_administration
from app.testing.routing import route_as
from app.services.platform import rules


async def _pass(guild_id: int) -> None:
    await each_guild(
        [(Scope.PROVISIONED, await engagement_levels.prepare())],
        name="test",
        only=[guild_id],
    )


async def _levels(session: AsyncSession) -> dict[tuple[str, int], int]:
    rows = (await session.exec(select(EngagementLevel))).all()
    return {(row.entity_type, row.entity_id): row.level for row in rows}


async def _three_people(session: AsyncSession, acting_user):
    """Three members of one initiative, and a task in its project."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    others = [
        await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        for _ in range(2)
    ]
    task = await create_task(session, a.project)
    return [a, *others], task


async def _all_opened(
    session: AsyncSession, people, task, source: ViewSource = ViewSource.direct
) -> None:
    now = datetime.now(timezone.utc)
    for person in people:
        session.add(
            PersonalItem(
                user_id=person.user.id,
                entity_type="task",
                entity_id=task.id,
                viewed_at=now,
                view_source=source.value,
            )
        )
    await session.commit()


async def test_an_item_has_a_level_once_three_people_engaged(
    session: AsyncSession, acting_user
):
    """Two opens and changes nobody made are not enough. A comment counts for
    the task it is on, and only the level is kept."""
    (a, b, c), task = await _three_people(session, acting_user)
    await _all_opened(session, (a, b), task)

    def change(actor: int | None, install: int | None = None) -> EventOutbox:
        return EventOutbox(
            txn_id=1,
            actor_user_id=actor,
            actor_install_id=install,
            initiative_id=a.initiative.id,
            resource_type="comments",
            resource_id=1,
            action="created",
            parents=[
                {"type": "tasks", "id": task.id},
                {"type": "projects", "id": a.project.id},
            ],
        )

    session.add(change(c.user.id, install=1))
    session.add(change(None))
    await session.commit()
    await _pass(a.guild.id)
    assert await _levels(session) == {}

    session.add(change(c.user.id))
    await session.commit()
    await _pass(a.guild.id)
    # Two opens at 1 and a change at 2: log2(1 + 4), floored.
    assert await _levels(session) == {("task", task.id): 2}


async def test_somebody_who_asked_not_to_be_counted_is_left_out(
    client, session: AsyncSession, acting_user
):
    """Turned off from their own settings, a person's opens count for nothing,
    so three opens become two people and no level."""
    people, task = await _three_people(session, acting_user)
    await _all_opened(session, people, task)
    await _pass(people[0].guild.id)
    assert await _levels(session) == {("task", task.id): 1}

    response = await client.patch(
        "/api/v1/me",
        json={"count_toward_engagement_ranking": False},
        headers=people[2].headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["count_toward_engagement_ranking"] is False
    await _pass(people[0].guild.id)
    assert await _levels(session) == {}


async def test_an_open_from_search_or_the_feed_counts_for_less(
    session: AsyncSession, acting_user
):
    """Search and the feed order by the level, so an open they led to weighs
    half."""
    (a, b, c), task = await _three_people(session, acting_user)
    await _all_opened(session, (a,), task, source=ViewSource.search)
    await _all_opened(session, (b,), task, source=ViewSource.feed)
    session.add(
        EventOutbox(
            txn_id=1,
            actor_user_id=c.user.id,
            initiative_id=a.initiative.id,
            resource_type="tasks",
            resource_id=task.id,
            action="updated",
        )
    )
    await session.commit()
    await _pass(a.guild.id)
    # 0.5 + 0.5 + 2 a moment old, where two direct opens make 4: log2(1 + just
    # under 3), floored.
    assert await _levels(session) == {("task", task.id): 1}


async def test_each_person_counts_once_and_old_engagement_fades(
    session: AsyncSession, acting_user
):
    """However often one person acts, they count once, at their weightiest. An
    engagement halves every two days, and an item left with fewer than three
    people inside the window loses its level."""
    (a, b, c), task = await _three_people(session, acting_user)
    await _all_opened(session, (b, c), task)
    for _ in range(5):
        session.add(
            EventOutbox(
                txn_id=1,
                actor_user_id=a.user.id,
                initiative_id=a.initiative.id,
                resource_type="tasks",
                resource_id=task.id,
                action="updated",
            )
        )
    await session.commit()
    await _pass(a.guild.id)
    # 2 + 1 + 1, not 5 × 2 + 1 + 1: log2(1 + 4), floored.
    assert await _levels(session) == {("task", task.id): 2}

    async def opened_ago(person, age: timedelta) -> None:
        await session.exec(
            update(PersonalItem)  # type: ignore[arg-type]
            .where(PersonalItem.user_id == person.user.id)  # type: ignore[arg-type]
            .values(viewed_at=datetime.now(timezone.utc) - age)
        )
        await session.commit()

    await opened_ago(b, 2 * HALF_LIFE)
    await opened_ago(c, 2 * HALF_LIFE)
    await _pass(a.guild.id)
    # 2 + 0.25 + 0.25: log2(3.5), floored.
    assert await _levels(session) == {("task", task.id): 1}

    await opened_ago(c, WINDOW + timedelta(hours=1))
    await _pass(a.guild.id)
    assert await _levels(session) == {}


async def test_a_purge_holds_the_pass_off_until_it_commits(
    session: AsyncSession, acting_user, role_session
):
    """The purge drops the levels in a transaction of its own, so the pass
    waits for the purge's to end rather than levelling what it is removing."""
    people, task = await _three_people(session, acting_user)
    owner = people[0]
    await _all_opened(session, people, task)
    await _pass(owner.guild.id)
    assert await _levels(session) == {("task", task.id): 1}

    purging = await role_session("app_user")
    await route_as(purging, user_id=owner.user.id, guild_id=owner.guild.id)
    await engagement_levels.purge_for_entities(purging, "task", [task.id])
    assert await _levels(session) == {}
    await _pass(owner.guild.id)
    assert await _levels(session) == {}

    # This purge never removed the task, so once it ends the level comes back.
    await purging.rollback()
    await _pass(owner.guild.id)
    assert await _levels(session) == {("task", task.id): 1}


async def test_turning_ranking_off_clears_the_levels(
    session: AsyncSession, acting_user
):
    """A community's answer applies while it holds ``restrictions``; the
    deployment's applies to every community."""
    people, task = await _three_people(session, acting_user)
    guild = people[0].guild
    await _all_opened(session, people, task)
    await _pass(guild.id)
    # Three opens a moment old come to just under 3: log2(1 + 3), floored.
    assert await _levels(session) == {("task", task.id): 1}

    await rules.put(session, "allow_engagement_ranking", False, guild_id=guild.id)
    await session.commit()
    await guild_administration(session, guild, auth_options=[])
    await _pass(guild.id)
    assert await _levels(session) == {("task", task.id): 1}

    await guild_administration(session, guild, auth_options=["restrictions"])
    await _pass(guild.id)
    assert await _levels(session) == {}

    await rules.put(session, "allow_engagement_ranking", True, guild_id=guild.id)
    await session.commit()
    await _pass(guild.id)
    assert await _levels(session) == {("task", task.id): 1}

    # A read-only community is still cleared when the deployment turns it off.
    guild.status = CommunityStatus.read_only
    session.add(guild)
    await rules.put(session, "engagement_ranking_enabled", False)
    await session.commit()
    await _pass(guild.id)
    assert await _levels(session) == {}


async def test_a_level_is_read_like_its_item_and_written_by_nobody(
    session: AsyncSession, acting_user, role_session
):
    """The project's owner reads the task's level; a member it isn't shared
    with, and a member of the community outside the initiative, read none. Not
    even the owner writes one."""
    people, task = await _three_people(session, acting_user)
    owner, unshared = people[0], people[1]
    outsider = await acting_user(guild_role=CommunityRole.member, guild=owner.guild)
    await _all_opened(session, people, task)
    await _pass(owner.guild.id)

    for who, reads in ((owner, True), (unshared, False), (outsider, False)):
        s = await role_session("app_user")
        await route_as(s, user_id=who.user.id, guild_id=owner.guild.id)
        assert bool((await s.exec(select(EngagementLevel))).all()) is reads

    s = await role_session("app_user")
    await route_as(s, user_id=owner.user.id, guild_id=owner.guild.id)
    await s.exec(update(EngagementLevel).values(level=7))  # type: ignore[arg-type]
    await s.exec(delete(EngagementLevel))  # type: ignore[arg-type]
    assert await _levels(s) == {("task", task.id): 1}
    with pytest.raises(DBAPIError):
        s.add(EngagementLevel(entity_type="task", entity_id=task.id + 1, level=7))
        await s.flush()
