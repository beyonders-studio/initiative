"""Fixed anchors and hourly limits preserve each series' recurrence behavior."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import TaskMessages
from app.core.user_display import handle_of
from app.models.platform.guild import CommunityRole
from app.models.tenant.task import Task, TaskStatusCategory
from app.schemas.tenant.task import TaskCreate
from app.services.tenant import (
    project_export,
    project_import,
    task_series,
    task_statuses,
)
from app.services.tenant.project_grants import get_project_hydrated
from app.services.tenant.task_series import advance_recurrence_if_needed
from app.testing import create_task, route_as


@pytest.mark.parametrize("operation", ["complete", "skip"])
@pytest.mark.parametrize(
    ("rule", "expected_dates"),
    [
        ("RRULE:FREQ=WEEKLY\nRDATE:20261007T090000Z", [7, 12, 19]),
        ("RRULE:FREQ=WEEKLY;COUNT=3\nRDATE:20261007T090000Z", [7, 12, 19]),
        (
            (
                "RRULE:FREQ=DAILY;INTERVAL=3\nRDATE:20261007T090000Z\n"
                "EXDATE:20261008T090000Z"
            ),
            [7, 11, 14],
        ),
    ],
)
async def test_fixed_task_keeps_its_phase_after_an_extra_date(
    client, session, acting_user, operation, rule, expected_dates
):
    a = await acting_user(guild_role="member", initiative=True, project=True)
    first = await create_task(
        session,
        a.project,
        due_date=datetime(2026, 10, 5, 9, tzinfo=UTC),
        recurrence=rule,
    )
    task_id = first.id
    for day in expected_dates:
        if operation == "skip":
            response = await client.post(
                a.g(f"/tasks/{task_id}/skip"), headers=a.headers
            )
            assert response.status_code == 200, response.text
            current = response.json()
        else:
            response = await client.patch(
                a.g(f"/tasks/{task_id}"),
                headers=a.headers,
                json={"status_category": "done"},
            )
            assert response.status_code == 200, response.text
            conditions = json.dumps(
                [{"field": "project_id", "op": "eq", "value": a.project.id}]
            )
            response = await client.get(
                a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
            )
            assert response.status_code == 200, response.text
            (current,) = [row for row in response.json()["items"] if row["recurrence"]]
            task_id = current["id"]
        assert datetime.fromisoformat(current["due_date"]) == datetime(
            2026, 10, day, 9, tzinfo=UTC
        )


@pytest.mark.parametrize("operation", ["complete", "skip"])
async def test_zero_date_span_survives_the_next_task(
    client, session, acting_user, operation
):
    a = await acting_user(guild_role="member", initiative=True, project=True)
    due = datetime(2026, 10, 5, 9, tzinfo=UTC)
    first = await create_task(
        session, a.project, start_date=due, due_date=due, recurrence="RRULE:FREQ=DAILY"
    )
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
        conditions = json.dumps(
            [{"field": "project_id", "op": "eq", "value": a.project.id}]
        )
        response = await client.get(
            a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
        )
        assert response.status_code == 200, response.text
        (current,) = [row for row in response.json()["items"] if row["recurrence"]]
    assert current["start_date"] == current["due_date"]
    assert datetime.fromisoformat(current["due_date"]) == datetime(
        2026, 10, 6, 9, tzinfo=UTC
    )


async def test_resubmitting_unchanged_repeat_keeps_phase_and_calendar_projection(
    client, session, acting_user
):
    from app.schemas.tenant.task import TaskListRead
    from app.services.tenant.task_queries import projected_occurrences

    a = await acting_user(guild_role="member", initiative=True, project=True)
    rule = "RRULE:FREQ=WEEKLY;COUNT=3\nRDATE:20261007T090000Z,20261101T090000Z"
    first = await create_task(
        session,
        a.project,
        due_date=datetime(2026, 10, 5, 9, tzinfo=UTC),
        recurrence=rule,
    )
    response = await client.post(a.g(f"/tasks/{first.id}/skip"), headers=a.headers)
    assert response.status_code == 200, response.text
    response = await client.patch(
        a.g(f"/tasks/{first.id}"),
        headers=a.headers,
        json={"title": "Renamed", "recurrence": rule, "recurrence_strategy": "fixed"},
    )
    assert response.status_code == 200, response.text
    assert datetime.fromisoformat(response.json()["recurrence_anchor"]) == datetime(
        2026, 10, 5, 9, tzinfo=UTC
    )
    conditions = json.dumps(
        [{"field": "project_id", "op": "eq", "value": a.project.id}]
    )
    response = await client.get(
        a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
    )
    assert response.status_code == 200, response.text
    current = TaskListRead.model_validate(response.json()["items"][0])
    _, projected = projected_occurrences(
        [current],
        datetime(2026, 10, 8, tzinfo=UTC),
        datetime(2026, 11, 2, tzinfo=UTC),
    )
    assert [row.due_date for row in projected] == [
        datetime(2026, 10, 12, 9, tzinfo=UTC),
        datetime(2026, 10, 19, 9, tzinfo=UTC),
        datetime(2026, 11, 1, 9, tzinfo=UTC),
    ]
    response = await client.post(a.g(f"/tasks/{first.id}/skip"), headers=a.headers)
    assert response.status_code == 200, response.text
    assert datetime.fromisoformat(response.json()["due_date"]) == datetime(
        2026, 10, 12, 9, tzinfo=UTC
    )


async def test_retained_anchor_does_not_restart_a_consumed_count(
    client, session, acting_user
):
    a = await acting_user(guild_role="member", initiative=True, project=True)
    due = datetime(2026, 10, 5, 9, tzinfo=UTC)
    task = await create_task(
        session,
        a.project,
        due_date=due,
        recurrence="RRULE:FREQ=DAILY;COUNT=3",
        recurrence_occurrence_count=2,
        recurrence_anchor=due,
        recurrence_anchor_count=2,
    )
    response = await client.post(a.g(f"/tasks/{task.id}/skip"), headers=a.headers)
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == TaskMessages.NO_LATER_OCCURRENCE


@pytest.mark.parametrize("operation", ["complete", "skip"])
@pytest.mark.parametrize(
    "edit", ["resubmitted_rule_and_date", "repeat_after_this_only_date"]
)
async def test_task_edits_reanchor_the_effective_series_date(
    client, session, acting_user, operation, edit
):
    a = await acting_user(guild_role="member", initiative=True, project=True)
    first = await create_task(
        session,
        a.project,
        due_date=datetime(2026, 10, 5, 9, tzinfo=UTC),
        recurrence="RRULE:FREQ=WEEKLY"
        if edit == "resubmitted_rule_and_date"
        else "RRULE:FREQ=DAILY",
    )
    if edit == "resubmitted_rule_and_date":
        payload = {
            "due_date": "2026-10-06T09:00:00Z",
            "recurrence": "FREQ=WEEKLY",
            "tz": "UTC",
        }
        expected = datetime(2026, 10, 13, 9, tzinfo=UTC)
    else:
        response = await client.patch(
            a.g(f"/tasks/{first.id}"),
            headers=a.headers,
            json={"due_date": "2026-10-07T09:00:00Z", "scope": "this"},
        )
        assert response.status_code == 200, response.text
        payload = {"recurrence": "FREQ=WEEKLY", "tz": "UTC"}
        expected = datetime(2026, 10, 12, 9, tzinfo=UTC)
    response = await client.patch(
        a.g(f"/tasks/{first.id}"), headers=a.headers, json=payload
    )
    assert response.status_code == 200, response.text
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
        conditions = json.dumps(
            [{"field": "project_id", "op": "eq", "value": a.project.id}]
        )
        response = await client.get(
            a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
        )
        assert response.status_code == 200, response.text
        (current,) = [row for row in response.json()["items"] if row["recurrence"]]
    assert datetime.fromisoformat(current["due_date"]) == expected


async def test_fixed_to_rolling_count_keeps_the_remaining_series_end(
    client, session, acting_user
):
    from datetime import timedelta

    a = await acting_user(guild_role="member", initiative=True, project=True)
    first = await create_task(
        session,
        a.project,
        due_date=datetime(2026, 10, 5, 9, tzinfo=UTC),
        recurrence="RRULE:FREQ=DAILY;COUNT=3",
    )
    response = await client.patch(
        a.g(f"/tasks/{first.id}"),
        headers=a.headers,
        json={"recurrence_strategy": "rolling"},
    )
    assert response.status_code == 200, response.text
    task_id = first.id
    conditions = json.dumps(
        [{"field": "project_id", "op": "eq", "value": a.project.id}]
    )
    for consumed in (1, 2, 3):
        response = await client.patch(
            a.g(f"/tasks/{task_id}"),
            headers=a.headers,
            json={"status_category": "done"},
        )
        assert response.status_code == 200, response.text
        response = await client.get(
            a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
        )
        assert response.status_code == 200, response.text
        active = [row for row in response.json()["items"] if row["recurrence"]]
        if consumed == 3:
            assert active == []
            break
        (current,) = active
        task_id = current["id"]
        assert current["recurrence_occurrence_count"] == consumed
        assert datetime.fromisoformat(current["recurrence_until"]) == (
            datetime.fromisoformat(current["due_date"]) + timedelta(days=2 - consumed)
        )


async def _remove_saved_anchor(session, task):
    from sqlalchemy import text

    connection = await session.connection()
    await connection.execute(
        text(
            "UPDATE tasks SET recurrence_anchor = NULL, recurrence_anchor_count = 0 WHERE id = :id"
        ),
        {"id": task.id},
    )
    await session.commit()
    await session.refresh(
        task, attribute_names=["recurrence_anchor", "recurrence_anchor_count"]
    )
    assert task not in session.dirty


@pytest.mark.parametrize("has_carried_dates", [False, True])
async def test_next_dates_without_a_saved_anchor_leaves_the_orm_task_clean(
    session, acting_user, has_carried_dates
):
    from app.services.tenant.task_series import next_dates

    a = await acting_user(guild_role="member", initiative=True, project=True)
    baseline = datetime(2026, 10, 5, 9, tzinfo=UTC)
    displayed = datetime(2026, 10, 9, 9, tzinfo=UTC) if has_carried_dates else baseline
    task = await create_task(
        session,
        a.project,
        start_date=displayed,
        due_date=displayed,
        recurrence="RRULE:FREQ=WEEKLY;COUNT=4\nRDATE:20261007T090000Z",
        recurrence_occurrence_count=2,
        recurrence_carry={
            "due_date": baseline.isoformat(),
            "start_date": baseline.isoformat(),
        }
        if has_carried_dates
        else None,
    )
    await _remove_saved_anchor(session, task)
    before = (task.recurrence_anchor, task.recurrence_anchor_count)
    dates = await next_dates(session, task, now=baseline, user_timezone="UTC")
    expected = datetime(2026, 10, 7, 9, tzinfo=UTC)
    assert dates == (expected, expected)
    assert (task.recurrence_anchor, task.recurrence_anchor_count) == before
    assert task not in session.dirty
    assert not session.is_modified(task, include_collections=False)


@pytest.mark.parametrize("operation", ["complete", "skip"])
@pytest.mark.parametrize("has_carried_dates", [False, True])
async def test_advancing_without_a_saved_anchor_preserves_the_original_phase(
    client, session, acting_user, operation, has_carried_dates
):
    a = await acting_user(guild_role="member", initiative=True, project=True)
    baseline = datetime(2026, 10, 5, 9, tzinfo=UTC)
    displayed = datetime(2026, 10, 9, 9, tzinfo=UTC) if has_carried_dates else baseline
    task = await create_task(
        session,
        a.project,
        start_date=displayed,
        due_date=displayed,
        recurrence="RRULE:FREQ=WEEKLY;COUNT=4\nRDATE:20261007T090000Z",
        recurrence_occurrence_count=2,
        recurrence_carry={
            "due_date": baseline.isoformat(),
            "start_date": baseline.isoformat(),
        }
        if has_carried_dates
        else None,
    )
    await _remove_saved_anchor(session, task)
    task_id = task.id
    conditions = json.dumps(
        [{"field": "project_id", "op": "eq", "value": a.project.id}]
    )
    for day in (7, 12):
        if operation == "skip":
            response = await client.post(
                a.g(f"/tasks/{task_id}/skip"), headers=a.headers
            )
            assert response.status_code == 200, response.text
            current = response.json()
        else:
            response = await client.patch(
                a.g(f"/tasks/{task_id}"),
                headers=a.headers,
                json={"status_category": "done"},
            )
            assert response.status_code == 200, response.text
            response = await client.get(
                a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
            )
            assert response.status_code == 200, response.text
            (current,) = [row for row in response.json()["items"] if row["recurrence"]]
            task_id = current["id"]
        assert datetime.fromisoformat(current["due_date"]) == datetime(
            2026, 10, day, 9, tzinfo=UTC
        )
        assert current["start_date"] == current["due_date"]
        assert datetime.fromisoformat(current["recurrence_anchor"]) == baseline
        assert current["recurrence_anchor_count"] == 2
    from app.services.tenant.task_series import next_dates

    await session.refresh(task)
    if operation == "complete":
        from app.models.tenant.task import Task

        task = await session.get(Task, task_id)
        assert task is not None
    assert await next_dates(session, task, now=baseline, user_timezone="UTC") is None


def instant(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


@pytest.fixture
async def hourly_task(session, acting_user):
    actor = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(
        session,
        actor.project,
        title="Routine check",
        due_date=instant("2026-10-20T08:00"),
        recurrence="RRULE:FREQ=HOURLY;INTERVAL=4",
        recurrence_strategy="rolling",
        recurrence_limit=3,
    )
    await session.refresh(task, attribute_names=["task_status", "assignees"])
    return actor, task


async def history(session, actor, task, *, due: str, completed: str, deleted=False):
    row = await create_task(
        session,
        actor.project,
        series_id=task.series_id or task.id,
        due_date=instant(due),
        status_category=TaskStatusCategory.done,
        completed_at=instant(completed),
    )
    if deleted:
        row.deleted_at = instant(completed) + timedelta(minutes=1)
        await session.commit()
    return row


@pytest.mark.parametrize(
    ("now", "limit", "expected"),
    [
        ("2026-10-20T10:30:59", 3, "2026-10-20T14:30"),
        ("2026-10-20T23:00", 3, "2026-10-21T08:00"),
        ("2026-10-20T23:00", None, "2026-10-21T03:00"),
        ("2026-10-20T01:00", 3, "2026-10-20T05:00"),
    ],
)
async def test_hourly_counts_from_actual_completion_minute(
    hourly_task, session, now, limit, expected
):
    _, task = hourly_task
    task.recurrence_limit = limit
    dates = await task_series.next_dates(
        session, task, now=instant(now), user_timezone="UTC"
    )
    assert dates is not None
    assert dates[1] == instant(expected)


async def test_daily_count_and_anchor_come_from_completion_history(
    hourly_task, session
):
    actor, task = hourly_task
    await history(
        session,
        actor,
        task,
        due="2026-10-20T08:00",
        completed="2026-10-20T10:00",
        deleted=True,
    )
    await history(
        session, actor, task, due="2026-10-20T14:00", completed="2026-10-20T15:00"
    )
    # An unrelated series does not consume this series' limit.
    await create_task(
        session,
        actor.project,
        status_category=TaskStatusCategory.done,
        completed_at=instant("2026-10-20T16:00"),
    )
    task.due_date = instant("2026-10-20T19:00")
    dates = await task_series.next_dates(
        session, task, now=instant("2026-10-20T20:00"), user_timezone="UTC"
    )
    assert dates is not None
    assert dates[1] == instant("2026-10-21T08:00")


async def test_completion_day_not_due_day_selects_history(hourly_task, session):
    actor, task = hourly_task
    task.recurrence_limit = 2
    await history(
        session, actor, task, due="2026-10-19T08:00", completed="2026-10-20T10:00"
    )
    await history(
        session, actor, task, due="2026-10-20T09:00", completed="2026-10-19T22:00"
    )
    dates = await task_series.next_dates(
        session, task, now=instant("2026-10-20T15:00"), user_timezone="UTC"
    )
    assert dates is not None
    assert dates[1] == instant("2026-10-21T08:00")


async def test_completers_timezone_changes_day_and_anchor(hourly_task, session):
    actor, task = hourly_task
    task.recurrence_limit = 2
    await history(
        session, actor, task, due="2026-10-20T08:00", completed="2026-10-20T23:00"
    )
    # 23:00 UTC yesterday is 01:00 today in Amsterdam, but yesterday in UTC.
    now = instant("2026-10-21T06:00")
    utc = await task_series.next_dates(session, task, now=now, user_timezone="UTC")
    amsterdam = await task_series.next_dates(
        session, task, now=now, user_timezone="Europe/Amsterdam"
    )
    assert utc is not None and amsterdam is not None
    assert utc[1] == instant("2026-10-21T10:00")
    assert amsterdam[1] == instant("2026-10-22T08:00")


@pytest.mark.parametrize(
    ("now", "due", "zone", "interval", "expected"),
    [
        (
            "2026-03-29T00:30",
            "2026-03-29T00:30",
            "Europe/Amsterdam",
            4,
            "2026-03-29T04:30",
        ),
        (
            "2026-10-25T00:30",
            "2026-10-25T00:30",
            "Europe/Amsterdam",
            4,
            "2026-10-25T04:30",
        ),
        ("2026-10-20T23:00", "2026-10-20T08:00", "UTC", 12, "2026-10-21T11:00"),
    ],
)
async def test_dst_and_overnight_never_shorten_hourly_gap(
    hourly_task, session, now, due, zone, interval, expected
):
    _, task = hourly_task
    task.recurrence = f"RRULE:FREQ=HOURLY;INTERVAL={interval}"
    task.due_date = instant(due)
    task.recurrence_limit = 1 if interval == 12 else 3
    dates = await task_series.next_dates(
        session, task, now=instant(now), user_timezone=zone
    )
    assert dates is not None
    assert dates[1] == instant(expected)
    assert dates[1] - instant(now) >= timedelta(hours=interval)


async def test_skip_uses_future_due_without_counting_a_completion(hourly_task, session):
    actor, task = hourly_task
    task.due_date = instant("2026-10-23T08:00")
    assert await task_series.skip(
        session, task, now=instant("2026-10-20T10:00"), user_timezone="UTC"
    )
    assert task.due_date == instant("2026-10-23T12:00")
    assert task.completed_at is None
    assert task.recurrence_occurrence_count == 1
    assert (
        await session.exec(select(Task).where(Task.project_id == actor.project.id))
    ).all() == [task]


@pytest.mark.parametrize(
    ("rule", "limit", "expected"),
    [
        ("RRULE:FREQ=HOURLY;INTERVAL=4;COUNT=1", 3, None),
        ("RRULE:FREQ=HOURLY;INTERVAL=4;UNTIL=20261020", 3, "2026-10-20T14:00"),
        ("RRULE:FREQ=HOURLY;INTERVAL=4;UNTIL=20261020", 1, None),
        ("RRULE:FREQ=HOURLY;INTERVAL=4;UNTIL=20261020T150000Z", 1, None),
    ],
)
async def test_count_and_until_also_bound_daily_rollover(
    hourly_task, session, rule, limit, expected
):
    _, task = hourly_task
    task.recurrence = rule
    task.recurrence_limit = limit
    dates = await task_series.next_dates(
        session, task, now=instant("2026-10-20T10:00"), user_timezone="UTC"
    )
    assert (dates[1] if dates else None) == (instant(expected) if expected else None)


async def test_completion_copies_limit_but_never_stores_daily_state(
    hourly_task, session
):
    actor, task = hourly_task
    statuses = await task_statuses.list_statuses(session, actor.project.id)
    done = next(
        status for status in statuses if status.category == TaskStatusCategory.done
    )
    task.task_status = done
    task.task_status_id = done.id
    now = instant("2026-10-20T10:00")
    task.completed_at = now
    assert await advance_recurrence_if_needed(
        session,
        task,
        previous_status_category=TaskStatusCategory.todo,
        now=now,
        user_timezone="UTC",
    )
    assert not await advance_recurrence_if_needed(
        session,
        task,
        previous_status_category=TaskStatusCategory.done,
        now=now,
        user_timezone="UTC",
    )
    successor = (
        await session.exec(
            select(Task).where(Task.project_id == actor.project.id, Task.id != task.id)
        )
    ).one()
    assert successor.recurrence_limit == 3
    assert successor.due_date == instant("2026-10-20T14:00")
    assert successor.completed_at is None
    assert task.recurrence is None and task.recurrence_limit is None


@pytest.mark.parametrize(
    "changes",
    [
        {"recurrence_strategy": "fixed"},
        {"recurrence_limit": 0},
        {"recurrence_limit": 25},
        {"recurrence_limit": True},
        {"recurrence": "RRULE:FREQ=DAILY"},
        {"due_date": None},
    ],
)
def test_hourly_validation_checks_rule_strategy_due_and_limit(changes):
    with pytest.raises(ValidationError):
        TaskCreate.model_validate(
            {
                "title": "Routine check",
                "project_id": 1,
                "due_date": "2026-10-20T08:00:00Z",
                "recurrence": "RRULE:FREQ=HOURLY;INTERVAL=4",
                "recurrence_strategy": "rolling",
                "recurrence_limit": 3,
                **changes,
            }
        )


async def test_api_create_effective_patch_duplicate_and_disable(
    hourly_task, client, session
):
    actor, task = hourly_task
    response = await client.post(
        actor.g("/tasks/"),
        headers=actor.headers,
        json={
            "title": "Routine check",
            "project_id": actor.project.id,
            "due_date": "2026-10-20T08:00:00Z",
            "recurrence": "RRULE:FREQ=HOURLY;INTERVAL=4",
            "recurrence_strategy": "rolling",
            "recurrence_limit": 3,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["recurrence_limit"] == 3
    for update in (
        {"recurrence_strategy": "fixed"},
        {"due_date": None},
        {"recurrence": "RRULE:FREQ=DAILY"},
    ):
        response = await client.patch(
            actor.g(f"/tasks/{task.id}"), headers=actor.headers, json=update
        )
        assert response.status_code == 422, response.text
    response = await client.post(
        actor.g(f"/tasks/{task.id}/duplicate"), headers=actor.headers
    )
    assert response.status_code == 201, response.text
    assert response.json()["recurrence_limit"] == 3
    copy = await session.get(Task, response.json()["id"])
    assert copy is not None and copy.series_id is None
    response = await client.patch(
        actor.g(f"/tasks/{task.id}"),
        headers=actor.headers,
        json={"recurrence_limit": None},
    )
    assert response.status_code == 200, response.text
    assert response.json()["recurrence_limit"] is None
    response = await client.patch(
        actor.g(f"/tasks/{task.id}"), headers=actor.headers, json={"recurrence": None}
    )
    assert response.status_code == 200, response.text
    assert response.json()["recurrence_limit"] is None


async def test_export_import_preserves_rule_limit_and_real_history(
    hourly_task, session
):
    actor, task = hourly_task
    task.series_id = task.id
    await history(
        session, actor, task, due="2026-10-20T08:00", completed="2026-10-20T10:00"
    )
    task.due_date = instant("2026-10-20T14:00")
    await session.commit()
    envelope = await project_export.build_project_export(
        session,
        await get_project_hydrated(session, actor.project.id),
        exported_by_handle=handle_of(actor.user),
    )
    pending = next(item for item in envelope.tasks if item.recurrence is not None)
    assert pending.recurrence_limit == 3
    result = await project_import.import_project(
        session,
        envelope=envelope,
        target_initiative=actor.initiative,
        importer=actor.user,
    )
    imported = (
        await session.exec(
            select(Task).where(
                Task.project_id == result.entity_id, Task.recurrence.isnot(None)
            )
        )
    ).one()
    imported.recurrence_limit = 2
    dates = await task_series.next_dates(
        session, imported, now=instant("2026-10-20T15:00"), user_timezone="UTC"
    )
    assert dates is not None
    assert dates[1] == instant("2026-10-21T08:00")


@pytest.mark.parametrize(
    ("rule", "now", "expected"),
    [
        (
            "RRULE:FREQ=HOURLY;INTERVAL=4;BYDAY=MO",
            "2026-10-19T18:00",
            "2026-10-26T08:00",
        ),
        (
            "RRULE:FREQ=HOURLY;INTERVAL=7;BYDAY=MO",
            "2026-10-19T18:00",
            "2026-10-26T08:00",
        ),
        (
            "RRULE:FREQ=HOURLY;INTERVAL=23;BYDAY=MO",
            "2026-10-19T18:00",
            "2026-10-26T08:00",
        ),
        (
            "RRULE:FREQ=HOURLY;INTERVAL=4\nEXDATE:20261021T080000Z",
            "2026-10-20T18:00",
            "2026-10-21T12:00",
        ),
    ],
)
async def test_daily_reset_obeys_normal_rrule_filters(
    hourly_task, session, rule, now, expected
):
    _, task = hourly_task
    task.recurrence = rule
    task.recurrence_limit = 1
    task.due_date = instant(now).replace(hour=8)
    dates = await task_series.next_dates(
        session, task, now=instant(now), user_timezone="UTC"
    )
    assert dates is not None
    assert dates[1] == instant(expected)


async def test_rule_patch_uses_last_completion_without_counting_a_new_one(
    hourly_task, session, client
):
    actor, task = hourly_task
    await history(
        session, actor, task, due="2026-10-20T08:00", completed="2026-10-20T08:00"
    )
    task.due_date = instant("2026-10-20T12:00")
    task.start_date = task.due_date
    await session.commit()
    response = await client.patch(
        actor.g(f"/tasks/{task.id}"),
        headers=actor.headers,
        json={"recurrence": "RRULE:FREQ=HOURLY;INTERVAL=8"},
    )
    assert response.status_code == 200, response.text
    assert datetime.fromisoformat(response.json()["due_date"]) == instant(
        "2026-10-20T16:00"
    )
    assert response.json()["start_date"] == response.json()["due_date"]
    response = await client.patch(
        actor.g(f"/tasks/{task.id}"),
        headers=actor.headers,
        json={"due_date": "2026-10-20T12:00:00Z"},
    )
    assert response.status_code == 422, response.text
    response = await client.patch(
        actor.g(f"/tasks/{task.id}"),
        headers=actor.headers,
        json={"recurrence_limit": 1},
    )
    assert response.status_code == 200, response.text
    assert datetime.fromisoformat(response.json()["due_date"]) == instant(
        "2026-10-21T08:00"
    )


async def test_pending_day_after_skip_survives_rule_edit(hourly_task, session, client):
    actor, task = hourly_task
    await history(
        session, actor, task, due="2026-10-20T08:00", completed="2026-10-20T08:00"
    )
    task.due_date = instant("2026-10-23T12:00")
    await session.commit()
    response = await client.patch(
        actor.g(f"/tasks/{task.id}"),
        headers=actor.headers,
        json={"recurrence": "RRULE:FREQ=HOURLY;INTERVAL=5"},
    )
    assert response.status_code == 200, response.text
    assert datetime.fromisoformat(response.json()["due_date"]) == instant(
        "2026-10-23T13:00"
    )


async def test_last_counted_pending_task_can_change_interval(
    hourly_task, session, client
):
    actor, task = hourly_task
    await history(
        session, actor, task, due="2026-10-20T08:00", completed="2026-10-20T08:00"
    )
    task.recurrence_occurrence_count = 1
    task.recurrence = "RRULE:FREQ=HOURLY;INTERVAL=4;COUNT=2"
    task.due_date = instant("2026-10-20T12:00")
    await session.commit()
    response = await client.patch(
        actor.g(f"/tasks/{task.id}"),
        headers=actor.headers,
        json={"recurrence": "RRULE:FREQ=HOURLY;INTERVAL=5;COUNT=2"},
    )
    assert response.status_code == 200, response.text
    assert datetime.fromisoformat(response.json()["due_date"]) == instant(
        "2026-10-20T13:00"
    )
    await session.refresh(task)
    assert (
        await task_series.next_dates(
            session, task, now=instant("2026-10-20T13:00"), user_timezone="UTC"
        )
        is None
    )


@pytest.mark.parametrize(
    "rule",
    [
        "RRULE:FREQ=HOURLY;INTERVAL=5;BYDAY=MO",
        "RRULE:FREQ=HOURLY;INTERVAL=5\nEXDATE:20261025T130000Z",
    ],
)
async def test_rule_edit_obeys_filters_after_pending_day_clamp(
    hourly_task, session, client, rule
):
    actor, task = hourly_task
    await history(
        session, actor, task, due="2026-10-19T08:00", completed="2026-10-19T08:00"
    )
    task.due_date = instant("2026-10-25T12:00")
    await session.commit()
    response = await client.patch(
        actor.g(f"/tasks/{task.id}"), headers=actor.headers, json={"recurrence": rule}
    )
    assert response.status_code == 200, response.text
    due = datetime.fromisoformat(response.json()["due_date"])
    assert due >= instant("2026-10-25T12:00")
    if "BYDAY" in rule:
        assert due.weekday() == 0
    else:
        assert due == instant("2026-10-25T18:00")


async def test_rule_patch_applies_picked_zone_before_rescheduling(
    hourly_task, session, client
):
    actor, task = hourly_task
    await history(
        session, actor, task, due="2026-10-18T18:00", completed="2026-10-18T21:00"
    )
    task.recurrence_shift = 0
    task.recurrence_limit = None
    task.recurrence = "RRULE:FREQ=HOURLY;INTERVAL=1"
    task.due_date = instant("2026-10-18T22:00")
    await session.commit()
    response = await client.patch(
        actor.g(f"/tasks/{task.id}"),
        headers=actor.headers,
        json={"recurrence": "RRULE:FREQ=HOURLY;BYDAY=MO", "tz": "Europe/Amsterdam"},
    )
    assert response.status_code == 200, response.text
    assert datetime.fromisoformat(response.json()["due_date"]) == instant(
        "2026-10-18T22:00"
    )
    assert response.json()["recurrence_shift"] == 120


async def test_history_stays_in_request_guild_under_rls(
    hourly_task, session, acting_user
):
    actor, task = hourly_task
    source_id = task.id
    user_id, guild_id = actor.user.id, actor.guild.id
    session.expunge_all()
    foreign = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    for hour in (8, 12, 16):
        await create_task(
            session,
            foreign.project,
            series_id=source_id,
            status_category=TaskStatusCategory.done,
            due_date=instant("2026-10-20T02:00"),
            completed_at=instant(f"2026-10-20T{hour:02d}:00"),
        )
    await route_as(session, user_id=user_id, guild_id=guild_id)
    dates = await task_series.next_dates(
        session, task, now=instant("2026-10-20T18:00"), user_timezone="UTC"
    )
    assert dates is not None
    assert dates[1] == instant("2026-10-20T22:00")


async def test_filtered_daily_anchor_for_every_supported_hourly_interval(hourly_task):
    _, task = hourly_task
    mocked = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.all.return_value = []
    mocked.exec.return_value = result
    task.recurrence_limit = 1
    task.due_date = instant("2026-10-19T08:00")
    now = instant("2026-10-19T18:00")
    for interval in range(1, 367):
        task.recurrence = f"RRULE:FREQ=HOURLY;INTERVAL={interval};BYDAY=MO"
        earliest = now + timedelta(hours=interval)
        expected = instant("2026-10-26T08:00")
        while expected.date() < earliest.date():
            expected += timedelta(days=7)
        expected = max(expected, earliest)
        dates = await task_series.next_dates(mocked, task, now=now, user_timezone="UTC")
        assert dates is not None
        assert dates[1] == expected, interval


@pytest.mark.parametrize(
    "changes",
    [
        {"recurrence_strategy": "fixed", "recurrence_limit": None},
        {"recurrence": "RRULE:FREQ=DAILY", "recurrence_limit": 2},
        {"due_date": None},
    ],
)
async def test_invalid_import_recurrence_is_a_file_validation_error(
    hourly_task, session, client, changes
):
    actor, _ = hourly_task
    envelope = await project_export.build_project_export(
        session,
        await get_project_hydrated(session, actor.project.id),
        exported_by_handle=handle_of(actor.user),
    )
    payload = envelope.model_dump(mode="json")
    payload["tasks"][0].update(changes)
    response = await client.post(
        actor.g("/imports/envelope"),
        headers=actor.headers,
        json={"initiative_id": actor.initiative.id, "envelope": payload},
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "IMPORT_INVALID_ENVELOPE"
