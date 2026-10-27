"""``notifications.notify``: who hears, and how often.

A notice names what it is about, so it goes to somebody who can open that
thing now. The comment fan-out is driven end to end; the rest are asked of the
service directly.
"""

from datetime import datetime, timedelta, timezone

from sqlmodel import select

from app.core.tools import Tool
from app.db.session import set_rls_context
from app.models.platform.guild import CommunityRole
from app.models.platform.notification import Notification, NotificationType
from app.services.platform import user_notifications
from app.services import notifications
from app.testing import (
    create_library,
    create_library_item,
    create_resource_grant,
    create_task,
    create_user,
    drain_notices,
    route_session_to_guild,
)
from app.db.request_context import SystemGuild, Unattributed


async def _mentions(user_id: int) -> list[Notification]:
    from app.db.session import SystemSessionLocal

    await drain_notices()

    async with SystemSessionLocal() as system_session:
        rows = (
            await system_session.exec(
                select(Notification).where(Notification.user_id == user_id)
            )
        ).all()
    return [row for row in rows if str(row.type) == NotificationType.mention.value]


async def _mention(client, actor, task_id: int, user) -> int:
    posted = await client.post(
        actor.g("/comments/"),
        json={"task_id": task_id, "content": f"hi @[{user.username}]({user.id})"},
        headers=actor.headers,
    )
    assert posted.status_code in (200, 201), posted.text
    return posted.json()["id"]


async def test_a_mention_reaches_only_people_the_project_is_shared_with(
    client, session, acting_user
):
    """…and opening the task marks what it named read, saying which comments
    were unread: the one that mentioned them, and every comment since the
    thread's rolled-up line opened."""
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    await route_session_to_guild(session, owner.guild.id)
    task = await create_task(session, owner.project, assignees=[member.user])
    await session.commit()

    # In the initiative, but the project is the owner's alone.
    await _mention(client, owner, task.id, member.user)
    assert await _mentions(member.user.id) == []

    # The control: once it is shared with them, the same mention arrives.
    await create_resource_grant(session, owner.project, all_initiative_members=True)
    mentioned = await _mention(client, owner, task.id, member.user)
    assert len(await _mentions(member.user.id)) == 1
    plain = await client.post(
        owner.g("/comments/"),
        json={"task_id": task.id, "content": "and another thing"},
        headers=owner.headers,
    )
    assert plain.status_code in (200, 201), plain.text
    await drain_notices()

    opened = await client.post(
        "/api/v1/notifications/read-subject",
        json={
            "community_id": owner.guild.id,
            "subject_type": "task",
            "subject_id": task.id,
        },
        headers=member.headers,
    )
    assert opened.status_code == 200, opened.text
    assert opened.json()["comment_ids"] == sorted([mentioned, plain.json()["id"]])
    assert opened.json()["since"] is not None
    places = await client.get("/api/v1/notifications/unread", headers=member.headers)
    assert places.json()["places"] == []


async def test_a_mention_of_somebody_outside_the_community_tells_nobody(
    client, session, acting_user
):
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await create_resource_grant(session, owner.project, all_initiative_members=True)
    stranger = await create_user(session)
    await route_session_to_guild(session, owner.guild.id)
    task = await create_task(session, owner.project)
    await session.commit()

    await _mention(client, owner, task.id, stranger)

    assert await _mentions(stranger.id) == []


async def test_a_community_admin_is_among_the_readers(
    session, acting_user, monkeypatch
):
    """…and another member is not. A notice with nobody left to tell looks
    nothing up."""
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    admin = await acting_user(guild_role=CommunityRole.admin, guild=owner.guild)
    member = await acting_user(guild_role=CommunityRole.member, guild=owner.guild)
    # Routed the way a request or a sweep is, which is what names the community.
    await set_rls_context(session, SystemGuild(owner.guild.id))
    about = (Tool.project.value, owner.project.id)

    subject = await notifications.resolve_subject(session, about)

    assert subject is not None
    assert admin.user.id not in subject.shared_with
    assert admin.user.id in subject.readers
    assert owner.user.id in subject.shared_with
    assert member.user.id not in subject.readers

    async def refuse(*_args, **_kwargs):
        raise AssertionError("resolved a notice nobody was to hear")

    monkeypatch.setattr(notifications, "resolve_subject", refuse)
    await notifications.notify(
        session,
        NotificationType.mention,
        [owner.user.id, None],
        about=about,
        key="mention.comment",
        actor=owner.user,
    )


async def test_a_notice_about_a_library_item_opens_the_item(session, acting_user):
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    library = await create_library(session, owner.initiative, owner.user)
    item = await create_library_item(session, library, owner.user, write_blob=False)
    await set_rls_context(session, SystemGuild(owner.guild.id))

    subject = await notifications.resolve_subject(session, ("library_item", item.id))

    assert subject is not None
    assert subject.target_path == f"/go/library-item/{item.id}"


async def test_repeated_file_mentions_fold_into_one_line(client, session, acting_user):
    """The editor reports mentions as it saves; an unread line absorbs the next
    report."""
    from app.testing import create_file

    author = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    file = await create_file(session, author.initiative, author.user)
    reader = await acting_user(guild_role=CommunityRole.admin, guild=author.guild)
    await session.commit()
    for _ in range(3):
        posted = await client.post(
            author.g(f"/files/{file.id}/mentions"),
            json={"mentioned_user_ids": [reader.user.id]},
            headers=author.headers,
        )
        assert posted.status_code == 204, posted.text

    reader = reader.user

    lines = await _mentions(reader.id)
    assert len(lines) == 1
    assert lines[0].data["comment_count"] == 3
    assert (lines[0].data["entity_type"], lines[0].data["entity_id"]) == (
        "file",
        file.id,
    )


async def test_read_notifications_are_kept_thirty_days_and_unread_forever(session):
    from app.db.session import SystemSessionLocal

    user = await create_user(session)
    now = datetime.now(timezone.utc)
    ages = {"old_read": 31, "recent_read": 29, "old_unread": 400}
    async with SystemSessionLocal() as system_session:
        await set_rls_context(system_session, Unattributed())
        for label, days in ages.items():
            system_session.add(
                Notification(
                    user_id=user.id,
                    type=NotificationType.avatar_removed,
                    data={"label": label},
                    created_at=now - timedelta(days=days + 1),
                    read_at=None
                    if label == "old_unread"
                    else now - timedelta(days=days),
                )
            )
        await system_session.commit()

        pruned = await user_notifications.prune_read(system_session, now=now)

        left = (
            await system_session.exec(
                select(Notification).where(Notification.user_id == user.id)
            )
        ).all()
    assert pruned == 1
    assert sorted(row.data["label"] for row in left) == ["old_unread", "recent_read"]
