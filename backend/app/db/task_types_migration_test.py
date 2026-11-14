"""Revision ``20261020_0531`` against a community that already has projects.

The chain test builds every database from empty, where the backfill has nothing
to do. Here the revision is taken back and run again over projects made by
people in different languages, with tasks in every lifecycle state and a task
page the project had already changed.
"""

import importlib.util
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.tenant._mixins import ActorKind
from app.services.tenant import archive as archive_service
from app.services.tenant.soft_delete import soft_delete_entity
from app.testing import (
    create_project,
    create_task,
    create_user,
    make_operations_community,
)

#: The tables the revision changes in a community's schema.
_TABLES = ("projects", "tasks", "tool_layouts", "task_types", "intake_bindings")


@pytest.fixture
async def provisioner() -> AsyncIterator[AsyncEngine]:
    from conftest import TEST_DB_NAME

    engine = create_async_engine(
        make_url(settings.DATABASE_URL).set(database=TEST_DB_NAME), poolclass=NullPool
    )
    try:
        yield engine
    finally:
        await engine.dispose()


def _migration() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20261020_0531_a_task_has_a_type.py"
    )
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _run(connection: Connection, step: Callable[[], None]) -> None:
    with Operations.context(MigrationContext.configure(connection)):
        step()


async def _hand_to_provisioner(session: AsyncSession, guild_id: int) -> None:
    # The fixture builds the schema on its setup connection; a migration runs
    # as the provisioning owner, as it does in a deployment.
    owner = make_url(settings.DATABASE_URL).username
    assert owner is not None
    quoted = session.get_bind().dialect.identifier_preparer.quote(owner)
    connection = await session.connection()
    await connection.execute(text(f'ALTER SCHEMA "guild_{guild_id}" OWNER TO {quoted}'))
    for table in _TABLES:
        await connection.execute(
            text(f'ALTER TABLE "guild_{guild_id}".{table} OWNER TO {quoted}')
        )
    await session.commit()


async def test_every_project_gets_its_types_and_every_task_and_page_its_task_type(
    session, acting_user, provisioner
):
    a = await acting_user(guild_role="member", initiative=True, project=True)
    # The intake tables the revision types are the operations community's now.
    await make_operations_community(session, a.guild.id)
    german = await create_user(session, locale="de")
    gone = await create_user(session)
    german_project = await create_project(
        session, a.initiative, german, name="Umzug", created_by=german.id
    )
    nobodys = await create_project(session, a.initiative, gone, name="Orphaned")
    nobodys.created_by = None
    nobodys.created_by_kind = ActorKind.system
    session.add(nobodys)
    await session.commit()

    live = await create_task(session, german_project)
    archived = await create_task(session, german_project)
    await archive_service.archive_entity(session, archived)
    trashed = await create_task(session, german_project)
    await soft_delete_entity(
        session, trashed, deleted_by_user_id=a.user.id, retention_days=None
    )
    await create_task(session, nobodys)
    await session.commit()

    await _hand_to_provisioner(session, a.guild.id)
    migration = _migration()
    page = {"main": [{"type": "comments"}]}
    async with provisioner.begin() as connection:
        await connection.execute(
            text("SELECT set_config('search_path', :path, true)"),
            {"path": f"guild_{a.guild.id}, public"},
        )
        # The operations community renders its ideas policies over a column
        # the revision adds; they come back with the schema after the test.
        for policy in ("ideas_read", "ideas_only"):
            await connection.execute(text(f"DROP POLICY IF EXISTS {policy} ON tasks"))
        await connection.run_sync(_run, migration._apply_downgrade)
        # As before the revision: one task page per project, and one left
        # behind by a project that is gone. Written as the owner, with the
        # table's policies held as a migration holds them.
        await connection.execute(
            text("ALTER TABLE tool_layouts NO FORCE ROW LEVEL SECURITY")
        )
        for tool_id in (german_project.id, 999_999):
            await connection.execute(
                text(
                    "INSERT INTO tool_layouts"
                    " (initiative_id, tool, tool_id, kind, definition,"
                    "  created_at, updated_at)"
                    " VALUES (:initiative, 'project', :tool_id, 'task',"
                    "  CAST(:page AS jsonb), now(), now())"
                ),
                {
                    "initiative": a.initiative.id,
                    "tool_id": tool_id,
                    "page": '{"main": [{"type": "comments"}]}',
                },
            )
        await connection.execute(
            text("ALTER TABLE tool_layouts FORCE ROW LEVEL SECURITY")
        )
        locales = await connection.run_sync(migration._creator_locales)
        await connection.run_sync(
            _run, lambda: migration._apply_upgrade(connection.sync_connection, locales)
        )

    types = (
        await session.exec(
            text(
                "SELECT project_id, name, position, is_default, layout_preset, id,"
                " starting_values"
                " FROM task_types ORDER BY project_id, position"
            )
        )
    ).all()
    by_project: dict[int, list] = {}
    for row in types:
        by_project.setdefault(row[0], []).append(row)
    assert [row[1] for row in by_project[german_project.id]] == [
        "Aufgabe",
        "Fehler",
        "Idee",
        "Meilenstein",
    ]
    assert [row[1] for row in by_project[nobodys.id]] == [
        "Task",
        "Bug",
        "Idea",
        "Milestone",
    ]
    assert [row[3] for row in by_project[german_project.id]] == [
        True,
        False,
        False,
        False,
    ]
    assert [row[4] for row in by_project[german_project.id]] == [
        "plain",
        "fix",
        "discussion",
        "dates",
    ]
    # Bug starts with an outline of a report, in its maker's language.
    starts = [row[6] for row in by_project[german_project.id]]
    assert starts[0] is None and starts[2:] == [None, None]
    assert starts[1]["description"].startswith("**Was ist passiert?**")

    defaults = {project: rows[0][5] for project, rows in by_project.items()}
    tasks = (
        await session.exec(text("SELECT id, project_id, task_type_id FROM tasks"))
    ).all()
    assert {row[0] for row in tasks} >= {live.id, archived.id, trashed.id}
    assert all(row[2] == defaults[row[1]] for row in tasks)

    pages = (
        await session.exec(
            text(
                "SELECT tool_id, task_type_id, definition FROM tool_layouts"
                " WHERE kind = 'task'"
            )
        )
    ).all()
    assert [(row[0], row[1], row[2]) for row in pages] == [
        (german_project.id, defaults[german_project.id], page)
    ]
