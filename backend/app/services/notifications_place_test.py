"""A notification records where it happened.

The three columns are what light the navigation, so a notifier that does not
fill them leaves its community's dot saying "somewhere in here" and nothing
below it lighting at all.
"""

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.db.request_context import SystemGuild, Unattributed
from app.models.platform.notification import Notification, NotificationType
from app.services import notifications as notifications_service
from app.services.platform import user_notifications
from app.testing import create_guild, create_user, drain_notices


async def _only(session: AsyncSession, user_id: int) -> Notification:
    rows = (
        await session.exec(select(Notification).where(Notification.user_id == user_id))
    ).all()
    assert len(rows) == 1
    return rows[0][0] if isinstance(rows[0], tuple) else rows[0]


def test_the_place_is_read_off_the_payload():
    """An explicit tool wins over the entity type — they differ for a task
    comment, whose entity is the task and whose tool is the project list it
    lives in; the entity type stands in when no tool is stated; and a payload
    naming nowhere carries no place."""
    nowhere = dict.fromkeys(
        (
            "guild_id",
            "initiative_id",
            "tool",
            "resource_id",
            "subject_type",
            "subject_id",
        )
    )
    assert user_notifications._place(
        {
            "community_id": 3,
            "initiative_id": 9,
            "tool": "project",
            "entity_type": "task",
            "resource_id": 4,
            "subject_type": "task",
            "subject_id": 7,
        }
    ) == {
        "guild_id": 3,
        "initiative_id": 9,
        "tool": "project",
        "resource_id": 4,
        "subject_type": "task",
        "subject_id": 7,
    }
    assert user_notifications._place(
        {"community_id": 3, "entity_type": "counter_group"}
    ) == {
        **nowhere,
        "guild_id": 3,
        "tool": "counter_group",
    }
    assert user_notifications._place({}) == nowhere


async def test_a_notification_with_no_initiative_still_names_its_community(
    session: AsyncSession,
):
    """A membership notice belongs to a community and to nothing inside it, so
    the community lights and nothing below it does."""
    member = await create_user(session, email="place-guildonly@example.com")
    guild = await create_guild(session, creator=member)

    await user_notifications.create_notification(
        session,
        user_id=member.id,
        notification_type=NotificationType.initiative_added,
        data={"community_id": guild.id},
    )
    await session.commit()

    line = await _only(session, member.id)
    assert line.guild_id == guild.id
    assert line.initiative_id is None
    assert line.tool is None


async def _thing(session: AsyncSession, kind: str, initiative, creator):
    """One row of ``kind`` in ``initiative``, the tool that governs it and that
    tool's row."""
    from app.testing import (
        create_calendar,
        create_calendar_event,
        create_file,
        create_project,
        create_task,
        create_wiki,
        create_wiki_page,
    )

    if kind == "task":
        project = await create_project(session, initiative, creator)
        return await create_task(session, project), Tool.project, project.id
    if kind == "file":
        file = await create_file(session, initiative, creator)
        return file, Tool.file, file.id
    if kind == "calendar_event":
        calendar = await create_calendar(session, initiative, creator)
        event = await create_calendar_event(session, calendar, creator)
        return event, Tool.calendar, calendar.id
    wiki = await create_wiki(session, initiative, creator)
    return await create_wiki_page(session, wiki, creator), Tool.wiki, wiki.id


@pytest.mark.parametrize("kind", ["task", "file", "calendar_event", "wiki_page"])
async def test_a_notice_is_placed_by_what_it_is_about(session: AsyncSession, kind: str):
    """Every notice records where it sits all the way down — the initiative, the
    tool and the tool's row that govern the thing it names (a task's project,
    an event's calendar, a page's wiki) and the thing itself — because
    ``notify`` reads them off that thing rather than being told."""
    from app.db.session import set_rls_context
    from app.testing import create_initiative

    owner = await create_user(session, email=f"place-{kind}@example.com")
    guild = await create_guild(session, creator=owner)
    initiative = await create_initiative(session, guild, owner)
    row, tool, resource_id = await _thing(session, kind, initiative, owner)
    actor = await create_user(session, email=f"place-actor-{kind}@example.com")
    await session.commit()

    await set_rls_context(session, SystemGuild(guild.id))
    await notifications_service.notify(
        session,
        NotificationType.mention,
        [owner.id],
        about=(kind, row.id),
        key="mention.comment",
        values={"actor": "someone", "context": "it"},
        actor=actor,
    )
    await session.commit()
    await drain_notices()
    await set_rls_context(session, Unattributed())

    line = await _only(session, owner.id)
    assert line.guild_id == guild.id
    assert line.initiative_id == initiative.id
    assert line.tool == tool.value
    assert (line.resource_id, line.subject_type, line.subject_id) == (
        resource_id,
        kind,
        row.id,
    )
