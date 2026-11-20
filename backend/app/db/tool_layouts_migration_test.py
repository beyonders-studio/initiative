"""Migration 20261009_0478 turns a project's filter presets into its views,
20261009_0479 drops the default view mode they no longer need, and
20261010_0493 turns the views into layouts.
Loaded by path and run on a guild the test builds, the way
``file_versions_by_pointer_migration_test`` runs its revision: down to the old
shape, rows written as an older release wrote them, up, and down again."""

from __future__ import annotations

import json

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.testing import create_guild, create_initiative, create_project, create_user
from app.testing.later_revisions import load_revision

_SEEDS = (
    ("all", "All", True, "{}"),
    (
        "incomplete",
        "Incomplete",
        False,
        '{"status_categories": ["backlog", "todo", "in_progress"]}',
    ),
    ("unassigned", "Unassigned", False, '{"assignees": ["none"]}'),
    ("mine", "Mine", False, '{"assignees": ["me"]}'),
)
_TABLE = {"layout": {"type": "table"}}
_BOARD = {"layout": {"type": "board"}}
_CALENDAR = {"layout": {"type": "calendar"}}
_INCOMPLETE = {
    "layout": {"type": "table"},
    "filters": {"status_categories": ["backlog", "todo", "in_progress"]},
}
_UNASSIGNED = {"layout": {"type": "table"}, "filters": {"assignees": ["none"]}}
_MINE = {"layout": {"type": "table"}, "filters": {"assignees": ["me"]}}


async def test_presets_become_views_and_come_back(session) -> None:
    """A project as it was seeded stores nothing and keeps the shipped views.
    Every other stores the shipped six with its changes: an edited seed in its
    place, a deleted one left out, its own presets (a changed All among them)
    after them on its default layout, and the default it chose. A preset holding a shipped layout
    view's slug keeps it. The downgrade puts back the presets and re-seeds
    the projects that stored nothing."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    schema = f"guild_{guild.id}"
    initiative = await create_initiative(session, guild, user)
    names = (
        "Seeded",
        "Table mode",
        "Edited",
        "Deleted",
        "Custom",
        "Kanban",
        "Clash",
        "Renamed All",
        "Refiltered All",
    )
    projects = {
        name: (await create_project(session, initiative, user, name=name)).id
        for name in names
    }
    migration = load_revision("20261009_0478_tool_views")
    drop_mode = load_revision("20261009_0479_a_project_opens_on_its_default_view")
    layouts = load_revision("20261010_0493_views_become_layouts")

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

    async def sql(statement: str, **params):
        return await (await session.connection()).execute(text(statement), params)

    async def presets(project: str, *rows: tuple[str, str, bool, str]) -> None:
        for position, (slug, name, is_default, filters) in enumerate(rows):
            await sql(
                f"INSERT INTO {schema}.project_filter_presets"
                " (project_id, slug, name, position, is_default, filters,"
                " created_at, updated_at) VALUES"
                " (:p, :slug, :name, :position, :is_default, CAST(:f AS jsonb),"
                " now(), now())",
                p=projects[project],
                slug=slug,
                name=name,
                position=position,
                is_default=is_default,
                f=filters,
            )

    async def mode(project: str, value: str) -> None:
        await sql(
            f"UPDATE {schema}.projects SET default_view_mode = :m WHERE id = :p",
            m=value,
            p=projects[project],
        )

    await session.run_sync(run(layouts._apply_downgrade))
    await session.run_sync(run(drop_mode._apply_downgrade))
    await session.run_sync(run(migration._apply_downgrade))
    await sql(f"DELETE FROM {schema}.project_filter_presets")
    # Listed out of order: the order of a project's presets is no change.
    await presets("Seeded", *reversed(_SEEDS))
    await presets("Table mode", *_SEEDS)
    await mode("Table mode", "table")
    await presets(
        "Edited",
        _SEEDS[0],
        _SEEDS[1],
        _SEEDS[2],
        ("mine", "My work", False, '{"assignees": ["me"], "due": "overdue"}'),
    )
    await presets("Deleted", _SEEDS[0], _SEEDS[1], _SEEDS[3])
    await presets(
        "Custom",
        *_SEEDS,
        ("blocked", "Blocked", False, '{"tag_ids": [7]}'),
    )
    await mode("Custom", "calendar")
    await presets("Kanban", *_SEEDS)
    await mode("Kanban", "kanban")
    await presets(
        "Clash",
        ("all", "All", False, "{}"),
        *_SEEDS[1:],
        ("board", "Board", True, '{"assignees": ["me"]}'),
    )
    await mode("Clash", "kanban")
    await presets("Renamed All", ("all", "Everything", True, "{}"), *_SEEDS[1:])
    await mode("Renamed All", "kanban")
    await presets(
        "Refiltered All", ("all", "All", False, '{"due": "overdue"}'), *_SEEDS[1:]
    )

    await session.run_sync(run(migration._apply_upgrade))
    rows = (
        await sql(
            f"SELECT tool_id, slug, name, is_default, definition"
            f" FROM {schema}.tool_views ORDER BY tool_id, position"
        )
    ).all()
    stored: dict[int, list[tuple]] = {}
    for row in rows:
        stored.setdefault(row.tool_id, []).append(tuple(row)[1:])
    shipped = [
        ("table", "Table", True, _TABLE),
        ("board", "Board", False, _BOARD),
        ("calendar", "Calendar", False, _CALENDAR),
        ("incomplete", "Incomplete", False, _INCOMPLETE),
        ("unassigned", "Unassigned", False, _UNASSIGNED),
        ("mine", "Mine", False, _MINE),
    ]
    default_board = [
        (slug, name, slug == "board", definition)
        for slug, name, _, definition in shipped
    ]
    assert stored == {
        projects["Edited"]: [
            *shipped[:5],
            (
                "mine",
                "My work",
                False,
                {
                    "layout": {"type": "table"},
                    "filters": {"assignees": ["me"], "due": "overdue"},
                },
            ),
        ],
        projects["Deleted"]: [*shipped[:4], shipped[5]],
        projects["Custom"]: [
            ("table", "Table", False, _TABLE),
            *shipped[1:2],
            ("calendar", "Calendar", True, _CALENDAR),
            *shipped[3:],
            (
                "blocked",
                "Blocked",
                False,
                {"layout": {"type": "calendar"}, "filters": {"tag_ids": [7]}},
            ),
        ],
        projects["Kanban"]: default_board,
        projects["Clash"]: [
            ("table", "Table", False, _TABLE),
            ("board-2", "Board", False, _BOARD),
            *[(slug, name, False, d) for slug, name, _, d in shipped[2:]],
            (
                "board",
                "Board",
                True,
                {"layout": {"type": "board"}, "filters": {"assignees": ["me"]}},
            ),
        ],
        # All changed is kept, as any other preset of the project's.
        projects["Renamed All"]: [
            *[(slug, name, False, d) for slug, name, _, d in shipped],
            ("all", "Everything", True, {"layout": {"type": "board"}, "filters": {}}),
        ],
        projects["Refiltered All"]: [
            *shipped,
            (
                "all",
                "All",
                False,
                {"layout": {"type": "table"}, "filters": {"due": "overdue"}},
            ),
        ],
    }

    # 0478 drops the mode; its downgrade reads it back off each default view.
    await session.run_sync(run(drop_mode._apply_upgrade))
    column = await sql(
        "SELECT 1 FROM information_schema.columns WHERE table_schema = :s"
        " AND table_name = 'projects' AND column_name = 'default_view_mode'",
        s=schema,
    )
    assert column.first() is None
    await session.run_sync(run(drop_mode._apply_downgrade))
    refilled = dict(
        (await sql(f"SELECT id, default_view_mode FROM {schema}.projects")).all()
    )
    assert refilled[projects["Kanban"]] == "kanban"
    assert refilled[projects["Custom"]] == "calendar"
    assert refilled[projects["Seeded"]] is None

    await session.run_sync(run(migration._apply_downgrade))
    back = (
        await sql(
            f"SELECT project_id, slug, name, is_default, filters"
            f" FROM {schema}.project_filter_presets ORDER BY project_id, position"
        )
    ).all()
    restored: dict[int, list[tuple]] = {}
    for row in back:
        restored.setdefault(row.project_id, []).append(tuple(row)[1:])
    seeds = [
        (slug, name, is_default, json.loads(filters))
        for slug, name, is_default, filters in _SEEDS
    ]
    assert restored[projects["Seeded"]] == seeds
    assert restored[projects["Table mode"]] == seeds
    assert restored[projects["Deleted"]] == [seeds[1], seeds[3]]
    assert restored[projects["Clash"]] == [
        *[(slug, name, False, f) for slug, name, _, f in seeds[1:]],
        ("board", "Board", True, {"assignees": ["me"]}),
    ]
    assert restored[projects["Renamed All"]] == [
        *seeds[1:],
        ("all", "Everything", True, {}),
    ]
    modes = dict(
        (await sql(f"SELECT id, default_view_mode FROM {schema}.projects")).all()
    )
    assert modes[projects["Kanban"]] == "kanban"

    await session.run_sync(run(migration._apply_upgrade))
    await session.run_sync(run(drop_mode._apply_upgrade))
    await session.run_sync(run(layouts._apply_upgrade))


async def test_views_become_layouts_and_come_back(session) -> None:
    """A project keeps what each of its list views drew and its task layout,
    and opens where it did; the views that only filtered become the presets of
    their list, a shipped one unrenamed by its slug alone and a sort only on a
    table. A project whose presets are the shipped ones stores nothing. The
    downgrade gives each project holding a layout the shipped views again,
    drawn as its layouts say."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    schema = f"guild_{guild.id}"
    initiative = await create_initiative(session, guild, user)
    drawn = (await create_project(session, initiative, user, name="Drawn")).id
    filtered = (await create_project(session, initiative, user, name="Filtered")).id
    seeded = (await create_project(session, initiative, user, name="Seeded")).id
    layouts = load_revision("20261010_0493_views_become_layouts")

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

    async def sql(statement: str, **params):
        return await (await session.connection()).execute(text(statement), params)

    async def view(project: int, position: int, slug: str, **values) -> None:
        await sql(
            f"INSERT INTO {schema}.tool_views (initiative_id, tool, tool_id, kind,"
            " item_kind, name, slug, position, is_default, definition, created_at,"
            " updated_at) VALUES (:i, 'project', :p, :kind, :item_kind, :name,"
            " :slug, :position, :is_default, CAST(:d AS jsonb), now(), now())",
            i=initiative.id,
            p=project,
            kind=values.get("kind", "view"),
            item_kind=values.get("item_kind"),
            name=values.get("name", slug and slug.title()),
            slug=slug,
            position=position,
            is_default=values.get("is_default", False),
            d=json.dumps(values["definition"]),
        )

    card = {
        "type": "card",
        "children": [{"type": "field", "props": {"field": "title"}}],
    }
    task = {"main": [{"type": "comments"}]}
    await session.run_sync(run(layouts._apply_downgrade))
    await view(drawn, 0, "table", definition={**_TABLE, "columns": ["title"]})
    await view(drawn, 1, "board", definition={**_BOARD, "card": card}, is_default=True)
    await view(drawn, 2, "calendar", definition=_CALENDAR)
    await view(drawn, 3, "mine", definition=_MINE)
    await view(drawn, 4, None, kind="item_layout", item_kind="task", definition=task)
    # A project whose views only filtered, opening on one of them.
    await view(filtered, 0, "table", definition=_TABLE)
    await view(filtered, 1, "mine", definition=_MINE, is_default=True)
    await view(
        filtered,
        2,
        "blocked",
        definition={
            **_TABLE,
            "filters": {"tag_ids": [7], "status_ids": [], "include_archived": False},
            "sort": [{"field": "dueDate", "direction": "desc"}],
        },
    )
    await view(
        filtered,
        3,
        "my-board",
        name="My board",
        definition={**_MINE, "layout": {"type": "board"}, "sort": [{"field": "title"}]},
    )
    # A project that kept the shipped views as they were.
    for position, (slug, definition) in enumerate(
        (
            ("table", _TABLE),
            ("board", _BOARD),
            ("calendar", _CALENDAR),
            ("incomplete", _INCOMPLETE),
            ("unassigned", _UNASSIGNED),
            ("mine", _MINE),
        )
    ):
        await view(
            seeded, position, slug, definition=definition, is_default=not position
        )

    await session.run_sync(run(layouts._apply_upgrade))
    rows = (
        await sql(
            f"SELECT tool_id, kind, definition FROM {schema}.tool_layouts"
            " ORDER BY tool_id, kind"
        )
    ).all()
    mine = {"slug": "mine", "filters": {"assignees": ["me"]}}
    assert [tuple(row) for row in rows] == [
        (drawn, "board", {"card": card}),
        (drawn, "default", {"kind": "board"}),
        (drawn, "table", {"columns": ["title"], "presets": [mine]}),
        (drawn, "task", task),
        (
            filtered,
            "board",
            {"presets": [{**mine, "slug": "my-board", "name": "My board"}]},
        ),
        (
            filtered,
            "table",
            {
                "presets": [
                    mine,
                    {
                        "slug": "blocked",
                        "name": "Blocked",
                        "filters": {"tag_ids": [7]},
                        "sort": [{"field": "due_date", "dir": "desc"}],
                    },
                ]
            },
        ),
    ]

    await session.run_sync(run(layouts._apply_downgrade))
    back = (
        await sql(
            f"SELECT slug, is_default, definition, item_kind FROM {schema}.tool_views"
            " WHERE tool_id = :p ORDER BY kind DESC, position",
            p=drawn,
        )
    ).all()
    assert [tuple(row) for row in back] == [
        ("table", False, {**_TABLE, "columns": ["title"]}, None),
        ("board", True, {**_BOARD, "card": card}, None),
        ("calendar", False, _CALENDAR, None),
        ("incomplete", False, _INCOMPLETE, None),
        ("unassigned", False, _UNASSIGNED, None),
        ("mine", False, _MINE, None),
        (None, False, task, "task"),
    ]

    await session.run_sync(run(layouts._apply_upgrade))
