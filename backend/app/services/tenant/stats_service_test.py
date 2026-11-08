"""Tests for user stats — schema-per-guild routing.

The stats service reads guild-scoped tasks/projects/initiatives, which live in
per-guild schemas. These tests assert it routes into the guild schema rather
than reading the empty ``public`` backup (which returned all-zero dashboards).
"""

from datetime import UTC, datetime, timedelta

from app.models.platform.guild import CommunityRole
from app.models.tenant.task import TaskStatusCategory
from app.services.tenant import stats_service
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_task,
    create_task_status,
    create_user,
    platform_session,
)


async def test_user_stats_reads_guild_schema(session):
    """A guild with completed tasks must report non-zero stats. If stats read
    the unrouted (public) schema this is 0 — the dashboard-zeros regression."""
    user = await create_user(session, email="stats-user@example.com")
    guild = await create_guild(session, creator=user)
    await create_guild_membership(
        session, user=user, guild=guild, role=CommunityRole.admin
    )
    initiative = await create_initiative(session, guild, user, name="Stats Init")
    project = await create_project(session, initiative, user)

    # Two completed tasks assigned to the user (written into the guild schema).
    await create_task(
        session,
        project,
        status_category=TaskStatusCategory.done,
        assignees=[user],
    )
    await create_task(
        session,
        project,
        status_category=TaskStatusCategory.done,
        assignees=[user],
    )

    async with platform_session(user) as caller:
        stats = await stats_service.get_user_stats(caller, user=user, guild_id=guild.id)
    assert stats.tasks_completed_total == 2
    assert any(
        g.community_id == guild.id and g.completed_count == 2
        for g in stats.community_breakdown
    )


async def test_user_stats_all_guilds_aggregates(session):
    """guild_id=None aggregates completed counts across the user's guilds."""
    user = await create_user(session, email="multi-guild@example.com")
    totals = 0
    for n, count in (("A", 1), ("B", 2)):
        guild = await create_guild(session, creator=user)
        await create_guild_membership(
            session, user=user, guild=guild, role=CommunityRole.admin
        )
        initiative = await create_initiative(session, guild, user, name=f"Init {n}")
        project = await create_project(session, initiative, user)
        for _ in range(count):
            await create_task(
                session,
                project,
                status_category=TaskStatusCategory.done,
                assignees=[user],
            )
        totals += count

    async with platform_session(user) as caller:
        stats = await stats_service.get_user_stats(caller, user=user, guild_id=None)
    assert stats.tasks_completed_total == totals  # 3, summed across both guilds
    assert len(stats.community_breakdown) == 2


async def test_completion_stats_follow_completion_not_later_edits(
    client, session, acting_user
):
    """Editing or moving between done columns preserves historical completion;
    reopening removes it and completing again records the new completion."""
    actor = await acting_user(
        guild_role=CommunityRole.admin, initiative=True, project=True
    )
    finished = datetime.now(UTC) - timedelta(days=14)
    task = await create_task(
        session,
        actor.project,
        status_category=TaskStatusCategory.done,
        assignees=[actor.user],
        created_at=finished - timedelta(days=1),
        start_date=finished - timedelta(days=1),
        due_date=finished + timedelta(days=1),
        completed_at=finished,
        updated_at=finished,
    )
    other_done = await create_task_status(
        session, actor.project, name="Shipped", category=TaskStatusCategory.done
    )

    async def stats():
        response = await client.get(
            "/api/v1/me/stats",
            headers=actor.headers,
            params={"community_id": actor.guild.id},
        )
        assert response.status_code == 200, response.text
        return response.json()

    async def edit(payload):
        response = await client.patch(
            actor.g(f"/tasks/{task.id}"), headers=actor.headers, json=payload
        )
        assert response.status_code == 200, response.text
        return response.json()

    before = await stats()
    assert before["on_time_rate"] == 100
    assert before["avg_completion_days"] == 1
    assert before["tasks_completed_this_week"] == 0
    for payload in ({"title": "Corrected title"}, {"task_status_id": other_done.id}):
        changed = await edit(payload)
        assert datetime.fromisoformat(changed["completed_at"]) == finished
        after = await stats()
        for field in (
            "on_time_rate",
            "avg_completion_days",
            "tasks_completed_this_week",
            "velocity_data",
        ):
            assert after[field] == before[field], field

    reopened = await edit({"status_category": "todo"})
    assert reopened["completed_at"] is None
    open_stats = await stats()
    assert open_stats["tasks_completed_total"] == 0
    assert open_stats["avg_completion_days"] is None

    completed = await edit({"status_category": "done"})
    assert datetime.fromisoformat(completed["completed_at"]) > finished
    latest = await stats()
    assert latest["on_time_rate"] == 0
    assert latest["tasks_completed_this_week"] == 1
    assert latest["avg_completion_days"] >= 14
