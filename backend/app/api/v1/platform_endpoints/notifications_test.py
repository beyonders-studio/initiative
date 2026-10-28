"""Integration tests for /api/v1/notifications.

These run through the real-role ``client`` (bare ``app_user`` login +
``SET ROLE platform_<tier>``), guarding the 0.54.0 regression where the
endpoints ran as the de-granted bare login role and every request failed
with ``permission denied for table notifications``.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.notification_categories import category_of
from app.core.tools import COMMENT_TARGETS, Tool
from app.models.platform.guild import CommunityRole
from app.models.platform.notification import NotificationType
from app.services.platform import notification_policy, user_notifications
from app.testing.factories import (
    create_guild,
    create_task,
    create_tool_entity,
    create_user,
    create_collection,
    create_wiki_page,
    enable_all_tools,
    get_auth_headers,
    set_notification_prefs,
)
from app.services.platform import rules


async def _seed_notification(session: AsyncSession, user_id: int) -> int:
    notification = await user_notifications.create_notification(
        session,
        user_id=user_id,
        notification_type=NotificationType.task_assignment,
        data={"task_title": "Ship it"},
    )
    await session.commit()
    assert notification.id is not None
    return notification.id


async def test_list_notifications(client: AsyncClient, session: AsyncSession):
    user = await create_user(session)
    await _seed_notification(session, user.id)

    response = await client.get(
        "/api/v1/notifications/", headers=get_auth_headers(user)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["unread_count"] == 1
    assert len(body["notifications"]) == 1
    assert body["notifications"][0]["type"] == "task_assignment"


#: A place naming nothing at any level.
_NOWHERE = dict.fromkeys(
    (
        "community_id",
        "initiative_id",
        "tool",
        "resource_id",
        "subject_type",
        "subject_id",
    )
)


async def test_unread_places(client: AsyncClient, session: AsyncSession):
    """Where the dots go. A notification with no community is still a place —
    that is what makes "anything unread at all" the same question."""
    user = await create_user(session)
    await _seed_notification(session, user.id)

    response = await client.get(
        "/api/v1/notifications/unread", headers=get_auth_headers(user)
    )
    assert response.status_code == 200
    assert response.json() == {"places": [_NOWHERE]}


async def test_unread_places_carries_the_whole_tree(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.comment_on_task,
        data={
            "community_id": guild.id,
            "initiative_id": 9,
            "entity_type": "project",
            "resource_id": 4,
            "subject_type": "task",
            "subject_id": 7,
        },
    )
    await session.commit()

    response = await client.get(
        "/api/v1/notifications/unread", headers=get_auth_headers(user)
    )
    assert response.json()["places"] == [
        {
            "community_id": guild.id,
            "initiative_id": 9,
            "tool": "project",
            "resource_id": 4,
            "subject_type": "task",
            "subject_id": 7,
        }
    ]


async def test_reading_everything_empties_the_places(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    await _seed_notification(session, user.id)
    headers = get_auth_headers(user)

    await client.post("/api/v1/notifications/read-all", headers=headers)

    response = await client.get("/api/v1/notifications/unread", headers=headers)
    assert response.json() == {"places": []}


async def test_the_popover_can_take_every_unread_page(
    client: AsyncClient, session: AsyncSession
):
    """No cap: the popover follows the cursor to the end, which is what makes
    a number on the bell unnecessary."""
    user = await create_user(session)
    for _ in range(5):
        await _seed_notification(session, user.id)
    headers = get_auth_headers(user)

    seen: list[int] = []
    counts: list[int | None] = []
    cursor: str | None = None
    for _ in range(10):  # bounded so a broken cursor cannot spin forever
        params = {"limit": 2, "unread_only": "true"}
        if cursor:
            params["cursor"] = cursor
        body = (
            await client.get("/api/v1/notifications/", headers=headers, params=params)
        ).json()
        seen.extend(n["id"] for n in body["notifications"])
        counts.append(body["unread_count"])
        cursor = body["next_cursor"]
        if not cursor:
            break

    assert cursor is None
    assert len(seen) == 5
    assert len(set(seen)) == 5
    # The total is the first page's; the pages after it do not count again.
    assert counts == [5, None, None]


async def test_marking_unread_puts_a_line_back(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    notification_id = await _seed_notification(session, user.id)
    headers = get_auth_headers(user)

    await client.post(f"/api/v1/notifications/{notification_id}/read", headers=headers)
    response = await client.post(
        f"/api/v1/notifications/{notification_id}/unread", headers=headers
    )

    assert response.status_code == 200
    assert response.json()["read_at"] is None


async def test_dismissing_removes_the_line(client: AsyncClient, session: AsyncSession):
    user = await create_user(session)
    notification_id = await _seed_notification(session, user.id)
    headers = get_auth_headers(user)

    response = await client.delete(
        f"/api/v1/notifications/{notification_id}", headers=headers
    )
    assert response.status_code == 204

    body = (await client.get("/api/v1/notifications/", headers=headers)).json()
    assert body["notifications"] == []
    assert body["unread_count"] == 0


async def test_read_all_can_clear_one_community(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    cleared = await create_guild(session, creator=user, name="Cleared")
    kept = await create_guild(session, creator=user, name="Kept")
    for guild in (cleared, kept):
        await user_notifications.create_notification(
            session,
            user_id=user.id,
            notification_type=NotificationType.comment_on_task,
            data={"community_id": guild.id},
        )
    await session.commit()
    headers = get_auth_headers(user)

    await client.post(
        "/api/v1/notifications/read-all",
        headers=headers,
        params={"community_id": cleared.id},
    )

    places = (await client.get("/api/v1/notifications/unread", headers=headers)).json()[
        "places"
    ]
    assert places == [{**_NOWHERE, "community_id": kept.id}]


async def test_the_bell_can_be_switched_off_for_a_category(
    client: AsyncClient, session: AsyncSession
):
    """The whole point of in_app being a channel."""
    user = await create_user(session)
    await set_notification_prefs(
        session, user, {"categories": {"assignments": {"in_app": False}}}
    )
    written = await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.task_assignment,
        data={"task_title": "Ship it"},
    )
    await session.commit()

    assert written is None
    body = (
        await client.get("/api/v1/notifications/", headers=get_auth_headers(user))
    ).json()
    assert body["notifications"] == []


async def test_mark_notification_read(client: AsyncClient, session: AsyncSession):
    user = await create_user(session)
    notification_id = await _seed_notification(session, user.id)
    headers = get_auth_headers(user)

    response = await client.post(
        f"/api/v1/notifications/{notification_id}/read", headers=headers
    )
    assert response.status_code == 200
    assert response.json()["read_at"] is not None

    listed = await client.get("/api/v1/notifications/", headers=headers)
    assert listed.json()["unread_count"] == 0


async def test_mark_all_notifications_read(client: AsyncClient, session: AsyncSession):
    user = await create_user(session)
    await _seed_notification(session, user.id)
    await _seed_notification(session, user.id)

    response = await client.post(
        "/api/v1/notifications/read-all", headers=get_auth_headers(user)
    )
    assert response.status_code == 200
    assert response.json() == {"unread_count": 0}


async def test_cannot_read_other_users_notification(
    client: AsyncClient, session: AsyncSession
):
    owner = await create_user(session)
    other = await create_user(session)
    notification_id = await _seed_notification(session, owner.id)

    for request in (
        client.post(
            f"/api/v1/notifications/{notification_id}/read",
            headers=get_auth_headers(other),
        ),
        client.get(
            f"/api/v1/notifications/{notification_id}/alert",
            headers=get_auth_headers(other),
        ),
    ):
        assert (await request).status_code == 404


async def test_the_desktop_alert_is_the_line_unless_its_community_redacts(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    line = await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.mention,
        data={"community_id": guild.id, "context": "Q3 budget"},
    )
    await session.commit()
    assert line is not None
    url = f"/api/v1/notifications/{line.id}/alert"

    body = (await client.get(url, headers=get_auth_headers(user))).json()
    assert body["notification"]["id"] == line.id
    assert body["redacted"] is None

    await rules.put(session, "redact_notification_content", True, guild_id=guild.id)
    await session.commit()
    body = (await client.get(url, headers=get_auth_headers(user))).json()
    title, text = notification_policy.redacted_line(
        category_of(NotificationType.mention), "en"
    )
    assert body["redacted"] == {"title": title, "body": text}


async def test_the_bell_reads_the_title_back_from_the_community(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A line stores the reference; the title comes from the task, when read.

    Renaming the task changes what the bell says, which is the whole reason the
    title is not kept on the line.
    """
    actor = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, actor.project)
    await user_notifications.create_notification(
        session,
        user_id=actor.user.id,
        notification_type=NotificationType.task_assignment,
        data={
            "task_id": task.id,
            "community_id": actor.guild.id,
            "initiative_id": actor.initiative.id,
        },
    )
    await session.commit()

    async def _line() -> dict:
        response = await client.get("/api/v1/notifications/", headers=actor.headers)
        assert response.status_code == 200
        return response.json()["notifications"][0]

    assert (await _line())["data"]["task_title"] == task.title

    task.title = "Renamed after the fact"
    session.add(task)
    await session.commit()

    assert (await _line())["data"]["task_title"] == "Renamed after the fact"

    # A comment's line names whatever the comment is on — every tool, and each
    # extra that carries a thread of its own — by that thing's own label.
    await enable_all_tools(session, actor.initiative)
    subjects = {
        tool.value: await create_tool_entity(
            session, tool, actor.initiative, actor.user
        )
        for tool in Tool
    }
    subjects["task"] = task
    subjects["wiki_page"] = await create_wiki_page(
        session, subjects[Tool.wiki.value], actor.user
    )
    subjects["collection"] = await create_collection(
        session, actor.initiative, actor.user, files=[subjects[Tool.file.value]]
    )
    assert set(subjects) == set(COMMENT_TARGETS)
    for kind, entity in subjects.items():
        await user_notifications.create_notification(
            session,
            user_id=actor.user.id,
            notification_type=NotificationType.comment_on_resource,
            data={
                "entity_type": kind,
                "entity_id": entity.id,
                "community_id": actor.guild.id,
            },
        )
    await session.commit()

    response = await client.get("/api/v1/notifications/", headers=actor.headers)
    assert response.status_code == 200
    named = {
        line["data"]["entity_type"]: line["data"].get("entity_name")
        for line in response.json()["notifications"]
        if "entity_type" in line["data"]
    }
    assert named == {
        kind: getattr(entity, type(entity).display_field())
        for kind, entity in subjects.items()
    }
