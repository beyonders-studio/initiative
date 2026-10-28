"""Migration 20261027_0550 moves what plug-ins kept into the metadata store.
Loaded by path and run on a guild the test builds: down to ``plugin_metadata``,
an install's values written the way they were kept there, then up again, the
way ``galleries_collections_migration_test`` runs its revision."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.testing import (
    create_dashboard,
    create_guild,
    create_guild_plugin,
    create_initiative,
    create_project,
    create_task,
    create_user,
)

_REVISION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20261027_0550_metadata_is_one_store.py"
)


def _runner(schema: str):
    spec = importlib.util.spec_from_file_location(_REVISION.stem, _REVISION)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def run(forward: bool):
        def apply(sync_session) -> None:
            bind = sync_session.connection()
            bind.execute(
                text("SELECT set_config('search_path', :sp, true)"),
                {"sp": f"{schema}, public"},
            )
            with Operations.context(MigrationContext.configure(bind)):
                migration._apply(forward)

        return apply

    return run


async def _rows(session, sql: str, **params: Any) -> list[tuple]:
    result = await (await session.connection()).execute(text(sql), params)
    return [tuple(row) for row in result.all()]


async def test_a_plugins_values_move_into_the_metadata_store(session) -> None:
    """A definition per install and key, typed from the field the pinned
    version declares (a progress bar as a scale) or ``json`` where none does;
    each value in its column, a list's elements by ref, a state beside it;
    and a value not of its field's kind left behind. A dashboard's statement
    reads the datasets by their new names."""
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    schema = f"guild_{guild.id}"
    s = f'"{schema}"'
    initiative = await create_initiative(session, guild, owner)
    task = await create_task(session, await create_project(session, initiative, owner))
    plugin = await create_guild_plugin(
        session,
        guild,
        owner,
        definition={
            "plugin_kind": "service",
            "service": {"public_id": "tests.kept"},
            "fields": [
                {"key": "done", "kind": "progress", "on": ["task"]},
                {"key": "pulls", "kind": "link", "list": True, "on": ["task"]},
                {"key": "issue", "kind": "number", "on": ["task"]},
            ],
        },
    )
    dashboard = await create_dashboard(session, initiative, owner)
    await session.commit()
    run = _runner(schema)
    await session.run_sync(run(False))
    await session.commit()
    # A statement written against the datasets' old names.
    await (await session.connection()).execute(
        text(
            f"UPDATE {s}.dashboards SET definition = CAST(:d AS jsonb) WHERE id = :id"
        ),
        {
            "d": json.dumps({"sql": "SELECT name FROM property_definitions"}),
            "id": dashboard.id,
        },
    )

    for entity_type, entity_id, key, ref, value in (
        ("task", task.id, "done", "", {"value": 3, "max": 4}),
        (
            "task",
            task.id,
            "pulls",
            "812",
            {"ref": "812", "url": "https://x.test/812", "state": {"s": "open"}},
        ),
        ("task", task.id, "issue", "", "not a number"),
        ("plugin", plugin.id, "sync.cursor", "", {"page": 2}),
    ):
        await (await session.connection()).execute(
            text(
                f"INSERT INTO {s}.plugin_metadata (install_id, entity_type, "
                "entity_id, key, ref, value, updated_at) VALUES (:install, :kind, "
                ":id, :key, :ref, CAST(:value AS jsonb), now())"
            ),
            {
                "install": plugin.id,
                "kind": entity_type,
                "id": entity_id,
                "key": key,
                "ref": ref,
                "value": json.dumps(value),
            },
        )
    await session.commit()
    await session.run_sync(run(True))
    await session.commit()

    assert sorted(
        await _rows(
            session,
            "SELECT key, CAST(type AS text), list, shown_on, initiative_id "
            f"FROM {s}.metadata_definitions WHERE install_id = :i",
            i=plugin.id,
        )
    ) == [
        ("done", "scale", False, ["task"], None),
        ("issue", "number", False, ["task"], None),
        ("pulls", "link", True, ["task"], None),
        ("sync.cursor", "json", False, [], None),
    ]
    assert sorted(
        await _rows(
            session,
            "SELECT md.key, mv.entity_type, mv.ref, mv.value_number, mv.value_text, "
            f"mv.value_json, mv.state FROM {s}.metadata_values mv "
            f"JOIN {s}.metadata_definitions md ON md.id = mv.property_id",
        )
    ) == [
        ("done", "task", "", 75, None, None, None),
        (
            "pulls",
            "task",
            "812",
            None,
            "https://x.test/812",
            {"url": "https://x.test/812"},
            {"s": "open"},
        ),
        ("sync.cursor", "plugin", "", None, None, {"page": 2}, None),
    ]
    assert await _rows(session, f"SELECT to_regclass('{s}.plugin_metadata')") == [
        (None,)
    ]
    assert await _rows(
        session,
        f"SELECT definition FROM {s}.dashboards WHERE id = :id",
        id=dashboard.id,
    ) == [({"sql": "SELECT name FROM metadata_definitions"},)]
