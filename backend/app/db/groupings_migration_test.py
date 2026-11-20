"""Migration 20261020_0529 names a list's groupings by their fields, in the
layouts every guild stores and in each person's view of a project.

Loaded by path and run on a guild the test builds, as
``tool_layouts_migration_test`` runs its revisions: rows as the last release
wrote them, up, and down again."""

from __future__ import annotations

import json

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.testing import create_guild, create_initiative, create_project, create_user
from app.testing.later_revisions import load_revision

_OLD_LAYOUT = {
    "groupings": [
        {"field": "status", "hidden": ["3"]},
        {"field": "date", "hidden": ["0_overdue", "4_later"]},
        {"field": "tags"},
        {"field": "property:9", "hidden": ["s1"]},
    ],
    "group_by": "tags",
}
_NEW_LAYOUT = {
    "groupings": [
        {"field": "task_status_id", "hidden": ["3"]},
        {"field": "date_group", "hidden": ["0", "4"]},
        {"field": "tag_ids"},
        {"field": "property:9", "hidden": ["s1"]},
    ],
    "group_by": "tag_ids",
}
_OLD_VIEW = {
    "layout": "table",
    "parts": {
        "table": {
            "grouping": ["tag group"],
            "sorting": [{"id": "status group", "desc": False}, {"id": "title"}],
            "columns": {"date group": False, "title": True},
        },
        # The table's own state on a device, which 0.76 carried in as a pick.
        "board": {"grouping": [], "filters": {"tag_ids": [3]}},
    },
}
_NEW_VIEW = {
    "layout": "table",
    "parts": {
        "table": {
            "grouping": ["tag_ids group"],
            "sorting": [{"id": "task_status_id group", "desc": False}, {"id": "title"}],
            "columns": {"date_group group": False, "title": True},
        },
        "board": {"filters": {"tag_ids": [3]}},
    },
}


async def test_groupings_name_their_fields_and_come_back(session) -> None:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    schema = f"guild_{guild.id}"
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user)
    migration = load_revision("20261020_0529_groupings_name_fields")
    scope = f"view:{guild.id}:project:{project.id}"

    async def sql(statement: str, **params):
        return await (await session.connection()).execute(text(statement), params)

    def run(step):
        def apply(sync_session) -> None:
            bind = sync_session.connection()
            bind.execute(
                text("SELECT set_config('search_path', :sp, true)"),
                {"sp": f"{schema}, public"},
            )
            with Operations.context(MigrationContext.configure(bind)):
                step()

        return apply

    await sql(
        f"INSERT INTO {schema}.tool_layouts (initiative_id, tool, tool_id, kind,"
        " definition, created_at, updated_at) VALUES (:i, 'project', :p, 'table',"
        " CAST(:d AS jsonb), now(), now())",
        i=initiative.id,
        p=project.id,
        d=json.dumps(_OLD_LAYOUT),
    )
    await sql(
        "INSERT INTO public.user_view_preferences (user_id, scope_key, value,"
        " updated_at) VALUES (:u, :s, CAST(:v AS json), now())",
        u=user.id,
        s=scope,
        v=json.dumps(_OLD_VIEW),
    )

    async def stored() -> tuple[dict, dict]:
        layout = (await sql(f"SELECT definition FROM {schema}.tool_layouts")).scalar()
        view = (
            await sql(
                "SELECT value FROM public.user_view_preferences WHERE scope_key = :s",
                s=scope,
            )
        ).scalar()
        return layout, view

    def both(forward: bool):
        def step() -> None:
            migration._rewrite_layouts(forward)
            migration._rewrite_views(forward)

        return step

    await session.run_sync(run(both(True)))
    assert await stored() == (_NEW_LAYOUT, _NEW_VIEW)

    await session.run_sync(run(both(False)))
    old_view = json.loads(json.dumps(_OLD_VIEW))
    # The older "tag group" comes back as the name it was moved to, and an
    # empty grouping stays gone.
    old_view["parts"]["table"]["grouping"] = ["tags group"]
    del old_view["parts"]["board"]["grouping"]
    assert await stored() == (_OLD_LAYOUT, old_view)


def test_the_downgrade_leaves_out_what_the_old_ids_cannot_name() -> None:
    migration = load_revision("20261020_0529_groupings_name_fields")
    definition = {
        "groupings": [
            {"field": "due_date", "bucket": "week"},
            {"field": "project_id"},
            {"field": "priority"},
        ],
        "group_by": "due_date",
    }
    assert migration._layout(definition, False) == {
        "groupings": [{"field": "priority"}]
    }
