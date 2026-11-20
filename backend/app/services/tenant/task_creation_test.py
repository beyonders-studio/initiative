"""Who is on a task, changed by the change rather than by a new list."""

from sqlalchemy import text
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.request_context import SystemGuild
from app.db.session import set_rls_context
from app.models.platform.guild import CommunityRole
from app.models.tenant.task import Task
from app.services.tenant.task_creation import change_task_assignees
from app.testing import create_resource_grant, create_task


async def _team(session: AsyncSession, acting_user):
    """A project's owner and two more members it is shared with."""
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    others = [
        await acting_user(
            guild_role=CommunityRole.member,
            guild=owner.guild,
            initiative=owner.initiative,
            initiative_role="member",
        )
        for _ in range(2)
    ]
    for other in others:
        await create_resource_grant(session, owner.project, user=other.user)
    return owner, others


async def _loaded(session: AsyncSession, task_id: int) -> Task:
    return (
        await session.exec(
            select(Task)
            .where(Task.id == task_id)
            .options(selectinload(Task.assignees), selectinload(Task.project))
        )
    ).one()


async def test_adding_keeps_someone_put_on_since_the_task_was_read(
    session: AsyncSession, acting_user
):
    """Two people taking a task at once both end up on it: the second change
    does not write back the list the first one had not reached yet."""
    owner, (first, second) = await _team(session, acting_user)
    task = await create_task(session, owner.project)
    await set_rls_context(session, SystemGuild(owner.guild.id))
    stale = await _loaded(session, task.id)
    assert stale.assignees == []

    # The first one lands after this task was read.
    await session.exec(
        text(
            "INSERT INTO task_assignees (task_id, user_id) VALUES (:task, :user)"
        ).bindparams(task=task.id, user=first.user.id)  # type: ignore[call-overload]
    )

    added = await change_task_assignees(
        session, stale, add=[second.user.id], project=stale.project
    )

    assert {a.id for a in stale.assignees} == {first.user.id, second.user.id}
    # Only who this change put on it is told they were assigned by it.
    assert added == [second.user.id]
