"""Migration 20261021_0534 leaves every existing project's layouts as they were,
as a project ships showing every list, takes the Gantt away on the way down,
and leaves My Tasks a table.

Loaded by path and run on a guild the test builds, as
``groupings_migration_test`` runs its revision: rows as the last release wrote
them, up, and down again."""

from __future__ import annotations

import json

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.db.tool_layouts_migration_test import _load
from app.testing import create_guild, create_initiative, create_project, create_user

_PRESETS = {"presets": [{"slug": "mine", "filters": {"assignees": ["me"]}}]}
_MY_TASKS = {"layout": "calendar", "mode": "month", "parts": {"list": {"grouping": []}}}


async def test_existing_projects_keep_their_layouts_and_come_back(session) -> None:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    schema = f"guild_{guild.id}"
    initiative = await create_initiative(session, guild, user)
    # One that stored its calendar, one that opens on its calendar, and one
    # that stored nothing.
    saved, opens, plain = [
        (await create_project(session, initiative, user, name=name)).id
        for name in ("Saved", "Opens", "Plain")
    ]
    migration = _load("20261021_0534_a_project_draws_a_gantt")

    async def sql(statement: str, **params):
        return await (await session.connection()).execute(text(statement), params)

    def run(forward: bool):
        def apply(sync_session) -> None:
            bind = sync_session.connection()
            bind.execute(
                text("SELECT set_config('search_path', :sp, true)"),
                {"sp": f"{schema}, public"},
            )
            with Operations.context(MigrationContext.configure(bind)):
                migration._rewrite_layouts(forward)
                if forward:
                    migration._rewrite_my_tasks()

        return apply

    for project, kind, definition in (
        (saved, "calendar", _PRESETS),
        (opens, "default", {"kind": "calendar"}),
    ):
        await sql(
            f"INSERT INTO {schema}.tool_layouts (initiative_id, tool, tool_id, kind,"
            " definition, created_at, updated_at) VALUES (:i, 'project', :p, :k,"
            " CAST(:d AS jsonb), now(), now())",
            i=initiative.id,
            p=project,
            k=kind,
            d=json.dumps(definition),
        )
    await sql(
        "INSERT INTO public.user_view_preferences (user_id, scope_key, value,"
        " updated_at) VALUES (:u, 'view:me:tasks', CAST(:v AS json), now())",
        u=user.id,
        v=json.dumps(_MY_TASKS),
    )

    async def stored() -> dict[int, dict[str, dict]]:
        rows = (
            await sql(
                f"SELECT tool_id, kind, definition FROM {schema}.tool_layouts"
                " WHERE tool = 'project'"
            )
        ).all()
        found: dict[int, dict[str, dict]] = {}
        for project, kind, definition in rows:
            found.setdefault(project, {})[kind] = definition
        return found

    await session.run_sync(run(True))
    before = {
        saved: {"calendar": _PRESETS},
        opens: {"default": {"kind": "calendar"}},
    }
    assert await stored() == before
    my_tasks = (
        await sql(
            "SELECT value FROM public.user_view_preferences WHERE user_id = :u",
            u=user.id,
        )
    ).scalar()
    assert my_tasks == {"parts": {"list": {"grouping": []}}}

    # Down again, a Gantt, what opens on one and what a list hid go.
    for kind, definition in (
        ("gantt", {}),
        ("default", {"kind": "gantt"}),
        ("table", {"hidden": True}),
    ):
        await sql(
            f"INSERT INTO {schema}.tool_layouts (initiative_id, tool, tool_id, kind,"
            " definition, created_at, updated_at) VALUES (:i, 'project', :p, :k,"
            " CAST(:d AS jsonb), now(), now())",
            i=initiative.id,
            p=plain,
            k=kind,
            d=json.dumps(definition),
        )
    await session.run_sync(run(False))
    assert await stored() == {**before, plain: {"table": {}}}
