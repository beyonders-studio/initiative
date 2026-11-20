"""Tests for the auto-purge background worker and what a purge takes."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.db.request_context import SystemGuild
from app.db.session import set_rls_context
from app.db.soft_delete_filter import select_including_deleted
from app.models.platform.guild import CommunityStatus
from app.models.tenant.initiative import Initiative
from app.services.guild_sweeps import Scope, each_guild
from app.services.tenant.soft_delete import hard_purge_entity, soft_delete_entity
from app.services.tenant.trash_purge import purge_guild
from app.testing import emitted
from app.testing.factories import (
    create_comment,
    create_guild,
    create_initiative,
    create_project,
    create_task,
    create_user,
)


async def _trash_due(session: AsyncSession, user, row, *under) -> None:
    """Trash ``row`` and back-date the purge of it and of the rows ``under`` it
    that the trash stamped with it, so the next sweep finds every one."""
    await soft_delete_entity(session, row, deleted_by_user_id=user.id, retention_days=1)
    await session.commit()
    for item in (row, *under):
        model = type(item)
        stored = (
            await session.exec(
                select_including_deleted(model).where(model.id == item.id)
            )
        ).one()
        stored.purge_at = datetime.now(UTC) - timedelta(days=2)
        session.add(stored)
    await session.commit()


async def test_the_sweep_purges_what_is_due_in_every_active_guild(
    session: AsyncSession, role_session, capfd
):
    """Expired trash lives in each guild's own schema, so the sweep visits every
    guild, on real ``app_admin`` connections like production. An initiative
    goes with the project under it, and the projects pass does not find that
    project again; a trashed content row clears the admin-only purge guard.
    Each pass that took something records it once, with its counts and no
    actor; a guild with nothing due records nothing. A suspended guild is
    frozen: its trash stays until it is active again, then goes with its
    original ``purge_at``."""
    user = await create_user(session)
    swept, content, frozen, idle = [
        await create_guild(session, creator=user) for _ in range(4)
    ]

    initiative = await create_initiative(session, swept, user)
    under = await create_project(session, initiative, user)
    await _trash_due(session, user, initiative, under)

    project = await create_project(
        session, await create_initiative(session, content, user), user
    )
    await _trash_due(session, user, project)

    held = await create_initiative(session, frozen, user)
    await _trash_due(session, user, held)
    frozen.status = CommunityStatus.suspended.value
    session.add(frozen)
    await session.commit()

    await create_initiative(session, idle, user)

    admin = await role_session("app_admin")

    async def count(guild, table: str, row) -> int:
        await set_rls_context(admin, SystemGuild(guild.id))
        return (
            await admin.exec(
                text(f"SELECT COUNT(*) FROM {table} WHERE id = :id"),
                params={"id": row.id},
            )
        ).scalar_one()

    capfd.readouterr()
    await each_guild([(Scope.ACTIVE, purge_guild)], name="trash-purge")
    records = emitted(capfd, AuditEventType.TRASH_PURGED)

    assert await count(swept, "initiatives", initiative) == 0
    assert await count(swept, "projects", under) == 0
    assert await count(content, "projects", project) == 0
    assert await count(frozen, "initiatives", held) == 1

    (row,) = [r for r in records if r["guild_id"] == swept.id]
    assert row["actor_user_id"] is None
    assert row["target"] is None
    assert row["detail"] == {"via": "sweep", "counts": {"initiative": 1}}
    assert not [r for r in records if r["guild_id"] in (frozen.id, idle.id)]

    frozen.status = CommunityStatus.active.value
    session.add(frozen)
    await session.commit()
    await each_guild([(Scope.ACTIVE, purge_guild)], name="trash-purge")
    assert await count(frozen, "initiatives", held) == 0


async def test_purging_an_initiative_takes_everything_under_it(session: AsyncSession):
    """One purge clears the whole subtree: tools, their children, every thread
    and reply, and the rows that hang off them without being in the trash
    themselves (members, a project's columns, a task's assignees — the foreign
    key takes those, as ``Task.assignees`` is read-only to the ORM)."""
    from app.models.tenant.comment import Comment

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user)
    task = await create_task(session, project, assignees=[user])
    on_project = await create_comment(session, user, project=project)
    on_task = await create_comment(session, user, task=task)
    await create_comment(session, user, task=task, parent_comment_id=on_task.id)

    await soft_delete_entity(
        session, initiative, deleted_by_user_id=user.id, retention_days=1
    )
    await session.commit()
    trashed = (
        await session.exec(
            select_including_deleted(Initiative).where(Initiative.id == initiative.id)
        )
    ).one()

    await hard_purge_entity(session, trashed)
    await session.commit()

    async def count(table: str, column: str, value: int) -> int:
        result = await session.exec(
            text(f"SELECT count(*) FROM {table} WHERE {column} = :v").bindparams(
                v=value
            )
        )
        return result.one()[0]

    assert await count("initiatives", "id", initiative.id) == 0
    assert await count("initiative_members", "initiative_id", initiative.id) == 0
    assert await count("projects", "id", project.id) == 0
    assert await count("task_statuses", "project_id", project.id) == 0
    assert await count("tasks", "id", task.id) == 0
    assert await count("task_assignees", "task_id", task.id) == 0
    assert await count("comments", "subject_id", project.id) == 0
    assert await count("comments", "subject_id", task.id) == 0
    assert (
        await session.exec(
            select_including_deleted(Comment).where(Comment.id == on_project.id)
        )
    ).one_or_none() is None
