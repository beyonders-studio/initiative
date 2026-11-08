"""A member's reminder of a task: set and cleared on their own row, carried on to
the next task of a repeating series, and told to them once when it comes due."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import post_commit
from app.db.request_context import Unattributed
from app.db.session import set_rls_context
from app.models.platform.notification import Notification, NotificationType
from app.models.tenant.personal_item import PersonalItem
from app.services.guild_sweeps import each_guild
from app.services.notifications import task_reminder_scan
from app.testing import (
    create_task,
    drain_notices,
    guild_of,
    route_session_to_guild,
    set_notification_prefs,
)


async def _rows(session: AsyncSession, guild_id: int) -> list[PersonalItem]:
    # A repeat's reminders move once its request commits.
    await post_commit.settle_all()
    await route_session_to_guild(session, guild_id)
    return list(
        (
            await session.exec(
                select(PersonalItem)
                .where(col(PersonalItem.remind_at).is_not(None))
                .order_by(col(PersonalItem.entity_id))
            )
        ).all()
    )


async def _sweep(session: AsyncSession, now: datetime) -> None:
    await set_rls_context(session, Unattributed())
    await each_guild([], name="test", scans=[task_reminder_scan(now=now)])
    await drain_notices()


async def _reminders(session: AsyncSession, user_id: int) -> list[Notification]:
    await set_rls_context(session, Unattributed())
    return list(
        (
            await session.exec(
                select(Notification).where(
                    Notification.user_id == user_id,
                    Notification.type == NotificationType.task_reminder,
                )
            )
        ).all()
    )


async def _set(client, a, task_id: int, remind_at: datetime) -> dict:
    response = await client.put(
        a.g(f"/personal-items/reminder/task/{task_id}"),
        headers=a.headers,
        json={"remind_at": remind_at.isoformat()},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_reminder_is_set_moved_and_cleared(client, session, acting_user):
    a = await acting_user(guild_role="member", initiative=True, project=True)
    task = await create_task(session, a.project)
    at = datetime(2026, 11, 2, 9, tzinfo=timezone.utc)

    state = await _set(client, a, task.id, at)
    assert datetime.fromisoformat(state["remind_at"]) == at
    assert state["reminded_at"] is None

    later = at + timedelta(hours=2)
    await _set(client, a, task.id, later)
    response = await client.get(
        a.g(f"/personal-items/task/{task.id}"), headers=a.headers
    )
    assert datetime.fromisoformat(response.json()["remind_at"]) == later

    response = await client.delete(
        a.g(f"/personal-items/reminder/task/{task.id}"), headers=a.headers
    )
    assert response.status_code == 204
    # The reminder was all the row held, so the row goes with it.
    await route_session_to_guild(session, a.guild.id)
    assert (await session.exec(select(PersonalItem))).all() == []


async def test_a_reminder_is_only_for_a_task_the_reader_can_open(
    client, session, acting_user
):
    a = await acting_user(guild_role="member", initiative=True, project=True)
    task = await create_task(session, a.project)
    outsider = await acting_user(guild_role="member", guild=a.guild)
    response = await client.put(
        outsider.g(f"/personal-items/reminder/task/{task.id}"),
        headers=outsider.headers,
        json={"remind_at": datetime.now(timezone.utc).isoformat()},
    )
    assert response.status_code == 404


async def _next(client, a) -> dict:
    conditions = json.dumps(
        [{"field": "project_id", "op": "eq", "value": a.project.id}]
    )
    response = await client.get(
        a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
    )
    assert response.status_code == 200, response.text
    (current,) = [row for row in response.json()["items"] if row["recurrence"]]
    return current


@pytest.mark.parametrize("operation", ["complete", "skip"])
async def test_a_repeating_task_carries_its_reminder_at_the_same_distance(
    client, session, acting_user, operation
):
    a = await acting_user(guild_role="member", initiative=True, project=True)
    due = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)
    first = await create_task(
        session,
        a.project,
        start_date=due - timedelta(days=2),
        due_date=due,
        recurrence="RRULE:FREQ=WEEKLY",
    )
    # A day and a half before it is due, as the start date is two days before.
    await _set(client, a, first.id, due - timedelta(hours=36))
    # Already sent: the next task's is its own to send.
    await route_session_to_guild(session, a.guild.id)
    row = (await session.exec(select(PersonalItem))).one()
    row.reminded_at = due - timedelta(hours=36)
    session.add(row)
    await session.commit()

    if operation == "skip":
        response = await client.post(a.g(f"/tasks/{first.id}/skip"), headers=a.headers)
        assert response.status_code == 200, response.text
        current = response.json()
    else:
        response = await client.patch(
            a.g(f"/tasks/{first.id}"),
            headers=a.headers,
            json={"status_category": "done"},
        )
        assert response.status_code == 200, response.text
        current = await _next(client, a)

    next_due = datetime.fromisoformat(current["due_date"])
    assert next_due == due + timedelta(weeks=1)
    assert datetime.fromisoformat(current["start_date"]) == next_due - timedelta(days=2)
    (moved,) = await _rows(session, a.guild.id)
    assert moved.entity_id == current["id"]
    assert moved.remind_at == next_due - timedelta(hours=36)
    assert moved.reminded_at is None


async def test_a_completed_repeat_leaves_other_marks_on_the_finished_task(
    client, session, acting_user
):
    a = await acting_user(guild_role="member", initiative=True, project=True)
    due = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)
    first = await create_task(
        session, a.project, due_date=due, recurrence="RRULE:FREQ=DAILY"
    )
    await _set(client, a, first.id, due - timedelta(hours=1))
    response = await client.put(
        a.g(f"/personal-items/subscribe/task/{first.id}"), headers=a.headers
    )
    assert response.status_code == 200, response.text
    response = await client.patch(
        a.g(f"/tasks/{first.id}"), headers=a.headers, json={"status_category": "done"}
    )
    assert response.status_code == 200, response.text

    await post_commit.settle_all()
    await route_session_to_guild(session, a.guild.id)
    kept = (
        await session.exec(
            select(PersonalItem).where(PersonalItem.entity_id == first.id)
        )
    ).one()
    assert kept.subscribed_at is not None and kept.remind_at is None


async def test_a_due_reminder_is_told_once(client, session, acting_user):
    a = await acting_user(guild_role="member", initiative=True, project=True)
    task = await create_task(session, a.project, title="Water the plants")
    now = datetime.now(timezone.utc)
    await _set(client, a, task.id, now - timedelta(minutes=1))
    future = await create_task(session, a.project, title="Later")
    await _set(client, a, future.id, now + timedelta(hours=1))

    await _sweep(session, now)
    await _sweep(session, now)

    (told,) = await _reminders(session, a.user.id)
    assert told.data["task_id"] == task.id
    rows = {row.entity_id: row for row in await _rows(session, guild_of(task))}
    assert rows[task.id].reminded_at is not None
    assert rows[future.id].reminded_at is None


async def test_setting_a_sent_reminder_again_arms_it(client, session, acting_user):
    a = await acting_user(guild_role="member", initiative=True, project=True)
    task = await create_task(session, a.project)
    now = datetime.now(timezone.utc)
    await _set(client, a, task.id, now - timedelta(minutes=1))
    await _sweep(session, now)
    await _set(client, a, task.id, now - timedelta(seconds=30))
    await _sweep(session, now)
    assert len(await _reminders(session, a.user.id)) == 2


async def test_a_finished_task_reminds_of_nothing(client, session, acting_user):
    a = await acting_user(guild_role="member", initiative=True, project=True)
    task = await create_task(session, a.project)
    now = datetime.now(timezone.utc)
    await _set(client, a, task.id, now - timedelta(minutes=1))
    response = await client.patch(
        a.g(f"/tasks/{task.id}"), headers=a.headers, json={"status_category": "done"}
    )
    assert response.status_code == 200, response.text

    await _sweep(session, now)
    assert await _reminders(session, a.user.id) == []


async def test_a_reminder_is_switched_off_with_subscriptions(
    client, session, acting_user
):
    a = await acting_user(guild_role="member", initiative=True, project=True)
    task = await create_task(session, a.project)
    now = datetime.now(timezone.utc)
    await _set(client, a, task.id, now - timedelta(minutes=1))
    await set_rls_context(session, Unattributed())
    await set_notification_prefs(
        session,
        a.user,
        {
            "categories": {
                "subscriptions": {
                    "in_app": False,
                    "email": False,
                    "push": False,
                    "desktop": False,
                }
            }
        },
    )

    await _sweep(session, now)
    assert await _reminders(session, a.user.id) == []


async def test_a_series_moved_on_twice_at_once_follows_each_move(
    client, session, acting_user
):
    a = await acting_user(guild_role="member", initiative=True, project=True)
    due = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)
    task = await create_task(
        session, a.project, due_date=due, recurrence="RRULE:FREQ=WEEKLY"
    )
    await _set(client, a, task.id, due - timedelta(hours=3))

    # Both skips commit before either's move has run.
    for _ in range(2):
        response = await client.post(a.g(f"/tasks/{task.id}/skip"), headers=a.headers)
        assert response.status_code == 200, response.text
    next_due = datetime.fromisoformat(response.json()["due_date"])
    assert next_due == due + timedelta(weeks=2)

    (moved,) = await _rows(session, a.guild.id)
    assert moved.entity_id == task.id
    assert moved.remind_at == next_due - timedelta(hours=3)
