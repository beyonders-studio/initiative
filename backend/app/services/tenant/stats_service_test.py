"""A person's stats, read through ``/me/stats`` from their guild schemas."""

from datetime import UTC, datetime, timedelta

from app.models.platform.guild import CommunityRole
from app.models.tenant.task import TaskStatusCategory
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_task,
    create_task_status,
)


async def test_completion_stats_follow_completion_not_later_edits(
    client, session, acting_user
):
    """Stats read the guild schema, one community or all of them summed.
    Editing or moving between done columns preserves historical completion;
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

    async def stats(community_id: int | None = actor.guild.id):
        params = {"community_id": community_id} if community_id else {}
        response = await client.get(
            "/api/v1/me/stats", headers=actor.headers, params=params
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
    assert before["tasks_completed_total"] == 1
    assert [
        (g["community_id"], g["completed_count"]) for g in before["community_breakdown"]
    ] == [(actor.guild.id, 1)]
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

    other = await create_guild(session, creator=actor.user)
    await create_guild_membership(
        session, user=actor.user, guild=other, role=CommunityRole.admin
    )
    project = await create_project(
        session, await create_initiative(session, other, actor.user), actor.user
    )
    for _ in range(2):
        await create_task(
            session,
            project,
            status_category=TaskStatusCategory.done,
            assignees=[actor.user],
        )
    everywhere = await stats(None)
    assert everywhere["tasks_completed_total"] == 3
    assert len(everywhere["community_breakdown"]) == 2
