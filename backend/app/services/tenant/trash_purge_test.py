"""Tests for the auto-purge background worker.

Focus: the per-row skip guard correctly identifies rows that an earlier
cascade pass already queued for deletion, so we don't double-purge them.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.request_context import SystemGuild
from app.db.soft_delete_filter import select_including_deleted
from app.models.tenant.initiative import Initiative
from app.models.tenant.project import Project
from app.models.tenant.task import Task
from app.services.guild_sweeps import Scope, each_guild
from app.services.tenant.soft_delete import soft_delete_entity
from app.services.tenant.trash_purge import _run_purge_pass, purge_guild
from app.testing.factories import (
    create_guild,
    create_initiative,
    create_project,
    create_task,
    create_user,
)


async def test_auto_purge_does_not_double_purge_cascaded_descendants(
    session: AsyncSession,
):
    """When an Initiative purge cascades through its Projects, the later
    pass over projects must not find them again and purge them a second
    time."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user)

    # Soft-delete the initiative; the cascade stamps the project too.
    await soft_delete_entity(
        session, initiative, deleted_by_user_id=user.id, retention_days=1
    )
    await session.commit()

    # Backdate purge_at so the auto-purge picks both up.
    past = datetime.now(UTC) - timedelta(days=2)
    refreshed_initiative = (
        await session.exec(
            select_including_deleted(Initiative).where(Initiative.id == initiative.id)
        )
    ).one()
    refreshed_initiative.purge_at = past
    refreshed_project = (
        await session.exec(
            select_including_deleted(Project).where(Project.id == project.id)
        )
    ).one()
    refreshed_project.purge_at = past
    session.add(refreshed_initiative)
    session.add(refreshed_project)
    await session.commit()

    initiative_id = initiative.id
    project_id = project.id

    # One pass — should sweep both rows without raising. Drive the inner
    # loop with the test session.
    await _run_purge_pass(session, now=datetime.now(UTC))
    await session.commit()

    # Verify against the DB directly: the test session's identity map is
    # stale for these rows.
    initiative_count = (
        await session.exec(
            text("SELECT COUNT(*) FROM initiatives WHERE id = :id"),
            params={"id": initiative_id},
        )
    ).scalar_one()
    project_count = (
        await session.exec(
            text("SELECT COUNT(*) FROM projects WHERE id = :id"),
            params={"id": project_id},
        )
    ).scalar_one()
    assert initiative_count == 0
    assert project_count == 0


async def test_auto_purge_sweeps_every_guild_schema(
    session: AsyncSession, role_session
):
    """Expired trash lives in each guild's own schema, so the purge worker must
    visit every guild — the old single public-scoped pass would purge nothing.
    Stage expired trash in two guilds and assert the hourly pass's visit clears
    both.

    Run through the runner, on real ``app_admin`` connections like production,
    so the purge runs under the same privilege boundary that has to clear the
    admin-only purge guard."""
    from app.db.session import set_rls_context

    user = await create_user(session)
    past = datetime.now(UTC) - timedelta(days=2)
    targets: list[tuple[int, int]] = []  # (guild_id, initiative_id)

    for label in ("Gamma", "Delta"):
        guild = await create_guild(session, creator=user)
        initiative = await create_initiative(session, guild, user, name=label)
        await soft_delete_entity(
            session, initiative, deleted_by_user_id=user.id, retention_days=1
        )
        await session.commit()
        # Backdate purge_at so this initiative is due (same guild context).
        refreshed = (
            await session.exec(
                select_including_deleted(Initiative).where(
                    Initiative.id == initiative.id
                )
            )
        ).one()
        refreshed.purge_at = past
        session.add(refreshed)
        await session.commit()
        targets.append((guild.id, initiative.id))

    admin = await role_session("app_admin")
    await each_guild([(Scope.ACTIVE, purge_guild)], name="trash-purge")

    for guild_id, initiative_id in targets:
        await set_rls_context(admin, SystemGuild(guild_id))
        count = (
            await admin.exec(
                text("SELECT COUNT(*) FROM initiatives WHERE id = :id"),
                params={"id": initiative_id},
            )
        ).scalar_one()
        assert count == 0, f"guild {guild_id} initiative {initiative_id} not purged"


async def test_auto_purge_clears_content_table_guard(
    session: AsyncSession, role_session
):
    """A trashed CONTENT row (project) is purged via the routed worker pass too.

    Content tables carry both the initiative-member delete policy AND the
    soft_delete_admin_purge RESTRICTIVE guard; the worker clears both by routing
    as a guild admin. Regression: routing in without the admin guild-role GUC
    cleared neither, so the DELETE silently matched 0 rows."""

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user)

    # Trash only the project (initiative stays active), then make it due.
    await soft_delete_entity(
        session, project, deleted_by_user_id=user.id, retention_days=1
    )
    await session.commit()
    refreshed = (
        await session.exec(
            select_including_deleted(Project).where(Project.id == project.id)
        )
    ).one()
    refreshed.purge_at = datetime.now(UTC) - timedelta(days=2)
    session.add(refreshed)
    await session.commit()
    project_id = project.id

    from app.db.session import set_rls_context

    admin = await role_session("app_admin")
    await each_guild([(Scope.ACTIVE, purge_guild)], name="trash-purge")

    await set_rls_context(admin, SystemGuild(guild.id))
    count = (
        await admin.exec(
            text("SELECT COUNT(*) FROM projects WHERE id = :id"),
            params={"id": project_id},
        )
    ).scalar_one()
    assert count == 0, "trashed project was not hard-purged by the worker"


async def test_auto_purge_skips_non_active_guilds(session: AsyncSession, role_session):
    """A guild in ``read_only``/``suspended`` status is frozen: the worker must
    not keep destroying its trashed rows while a billing/moderation hold is
    unresolved. Purging resumes (original ``purge_at`` stamps) once the guild
    returns to active."""
    from app.models.platform.guild import CommunityStatus

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)

    await soft_delete_entity(
        session, initiative, deleted_by_user_id=user.id, retention_days=1
    )
    await session.commit()
    refreshed = (
        await session.exec(
            select_including_deleted(Initiative).where(Initiative.id == initiative.id)
        )
    ).one()
    refreshed.purge_at = datetime.now(UTC) - timedelta(days=2)
    session.add(refreshed)

    guild.status = CommunityStatus.suspended.value
    session.add(guild)
    await session.commit()
    initiative_id = initiative.id

    admin = await role_session("app_admin")
    await each_guild([(Scope.ACTIVE, purge_guild)], name="trash-purge")

    from app.db.session import set_rls_context

    await set_rls_context(admin, SystemGuild(guild.id))
    count = (
        await admin.exec(
            text("SELECT COUNT(*) FROM initiatives WHERE id = :id"),
            params={"id": initiative_id},
        )
    ).scalar_one()
    assert count == 1, "suspended guild's trash must NOT be purged"

    # Back to active: the same due row is swept on the next pass.
    guild.status = CommunityStatus.active.value
    session.add(guild)
    await session.commit()

    await each_guild([(Scope.ACTIVE, purge_guild)], name="trash-purge")
    await set_rls_context(admin, SystemGuild(guild.id))
    count = (
        await admin.exec(
            text("SELECT COUNT(*) FROM initiatives WHERE id = :id"),
            params={"id": initiative_id},
        )
    ).scalar_one()
    assert count == 0, "reactivated guild's due trash must purge again"


async def test_a_task_with_assignees_can_be_purged(session: AsyncSession):
    """``task_assignees`` rows go with the task.

    ``Task.assignees`` is read-only, so the ORM clears nothing there; the
    foreign key is what takes them. Without the cascade a purge — by hand from
    the trash, or by this worker on retention — dies on
    ``task_assignees_task_id_fkey`` and comes back to the same task every hour.
    """
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user)
    task = await create_task(session, project, assignees=[user])

    await soft_delete_entity(
        session, task, deleted_by_user_id=user.id, retention_days=1
    )
    await session.commit()

    refreshed = (
        await session.exec(select_including_deleted(Task).where(Task.id == task.id))
    ).one()
    refreshed.purge_at = datetime.now(UTC) - timedelta(days=2)
    session.add(refreshed)
    await session.commit()

    await _run_purge_pass(session, now=datetime.now(UTC))
    await session.commit()

    assert (
        await session.exec(select_including_deleted(Task).where(Task.id == task.id))
    ).one_or_none() is None
    left = await session.exec(
        text("SELECT count(*) FROM task_assignees WHERE task_id = :t").bindparams(
            t=task.id
        )
    )
    assert left.one()[0] == 0


async def test_purging_an_initiative_takes_everything_under_it(session: AsyncSession):
    """One purge clears the whole subtree: tools, their children, every thread
    and reply, and the rows that hang off them without being in the trash
    themselves (members, a project's columns)."""
    from app.models.tenant.comment import Comment
    from app.services.tenant.soft_delete import hard_purge_entity
    from app.testing.factories import create_comment

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user)
    task = await create_task(session, project)
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
    assert await count("comments", "project_id", project.id) == 0
    assert await count("comments", "task_id", task.id) == 0
    assert (
        await session.exec(
            select_including_deleted(Comment).where(Comment.id == on_project.id)
        )
    ).one_or_none() is None
