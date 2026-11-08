"""Migration 20261027_0550 moves what plug-ins kept into the metadata store.
Loaded by path and run on a guild the test builds: down to ``plugin_metadata``,
an install's values written the way they were kept there, then up again as
the provisioning role a deployment migrates as, which row security binds, the
way ``task_types_migration_test`` runs its revision."""

from __future__ import annotations

import importlib.util
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import make_url, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

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


#: The tables the revision changes in a community's schema, as they are
#: named before it.
_TABLES = (
    "property_definitions",
    "property_values",
    "plugin_metadata",
    "guild_plugins",
    "projects",
    "dashboards",
)


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


def _migration():
    spec = importlib.util.spec_from_file_location(_REVISION.stem, _REVISION)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _apply(schema: str, forward: bool):
    """The revision one way on ``schema`` alone, on a connection."""

    def apply(bind: Connection) -> None:
        bind.execute(
            text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f"{schema}, public"},
        )
        with Operations.context(MigrationContext.configure(bind)):
            _migration()._apply(forward)

    return apply


async def _rows(session, sql: str, **params: Any) -> list[tuple]:
    result = await (await session.connection()).execute(text(sql), params)
    return [tuple(row) for row in result.all()]


async def test_a_plugins_values_move_into_the_metadata_store(
    session, provisioner
) -> None:
    """A definition per install and key, typed from the field the pinned
    version declares (a progress bar as a scale, which the pinned definition
    names it now too) or ``json`` where none does; each value in its column, a
    list's elements by ref, a state beside it; and a value not of its field's
    kind left behind, a link or a badge that is not an object among them. A
    dashboard's statement reads the datasets by their new names."""
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
                {"key": "ci", "kind": "link", "on": ["task"]},
                {"key": "health", "kind": "badge", "on": ["task"]},
            ],
        },
    )
    dashboard = await create_dashboard(session, initiative, owner)
    await session.commit()
    connection = await session.connection()
    await connection.run_sync(_apply(schema, False))
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
        ("task", task.id, "ci", "", "https://ci.test/1"),
        ("task", task.id, "health", "", "passing"),
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
    # The schema and its tables are the provisioning role's, as in a
    # deployment, and the revision runs as it.
    owner_role = make_url(settings.DATABASE_URL).username
    assert owner_role is not None
    quoted = session.get_bind().dialect.identifier_preparer.quote(owner_role)
    connection = await session.connection()
    await connection.execute(text(f"ALTER SCHEMA {s} OWNER TO {quoted}"))
    for table in _TABLES:
        await connection.execute(text(f"ALTER TABLE {s}.{table} OWNER TO {quoted}"))
    await session.commit()
    async with provisioner.begin() as migrating:
        await migrating.run_sync(_apply(schema, True))

    assert sorted(
        await _rows(
            session,
            "SELECT key, CAST(type AS text), list, shown_on, initiative_id "
            f"FROM {s}.metadata_definitions WHERE install_id = :i",
            i=plugin.id,
        )
    ) == [
        ("ci", "link", False, ["task"], None),
        ("done", "scale", False, ["task"], None),
        ("health", "badge", False, ["task"], None),
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
        f"SELECT definition #> '{{fields,0,kind}}' FROM {s}.guild_plugins "
        "WHERE id = :id",
        id=plugin.id,
    ) == [("scale",)]
    assert await _rows(
        session,
        f"SELECT definition FROM {s}.dashboards WHERE id = :id",
        id=dashboard.id,
    ) == [({"sql": "SELECT name FROM metadata_definitions"},)]
