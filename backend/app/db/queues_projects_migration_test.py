"""Migration 20261105_0581 turns queues into projects and their items into
tasks. Loaded by path and run on a guild the test builds: down to empty queue
tables, a queue written the way 0.77 stored one, then up again, the way
``galleries_collections_migration_test`` runs its revision."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.testing import (
    create_guild,
    create_initiative,
    create_project,
    create_tag,
    create_user,
)

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20261105_0581_queues_are_projects.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(_MIGRATION.stem, _MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _rows(session, sql: str, **params: Any) -> list[tuple]:
    result = await (await session.connection()).execute(text(sql), params)
    return [tuple(row) for row in result.all()]


async def _one(session, sql: str, **params: Any) -> Any:
    return (await _rows(session, sql, **params))[0][0]


def _runner(schema: str):
    """Revision 0581 one way or the other, on one guild's schema only."""
    migration = _load()

    def run(forward: bool):
        def apply(sync_session) -> None:
            bind = sync_session.connection()

            def in_schema(step) -> None:
                bind.execute(
                    text("SELECT set_config('search_path', :sp, true)"),
                    {"sp": f"{schema}, public"},
                )
                step()

            with Operations.context(MigrationContext.configure(bind)):
                migration._convert(bind, forward, in_schema)

        return apply

    return run


async def test_a_queue_becomes_a_project_of_tasks(session) -> None:
    owner = await create_user(session)
    member = await create_user(session)
    guild = await create_guild(session, creator=owner)
    schema = f"guild_{guild.id}"
    s = f'"{schema}"'
    initiative = await create_initiative(session, guild, owner)
    project = await create_project(session, initiative, owner)
    tag = await create_tag(session, guild)
    await session.commit()
    run = _runner(schema)
    await session.run_sync(run(False))
    await session.commit()

    # A running queue as 0.77 stored one, on its third round: the item it is
    # on, a held one, a hidden one and one linked to a member whose notes name
    # the first. Queues on and projects off, a role that reaches queues alone,
    # a grant, a comment, a tag and links, and a notice about an item.
    connection = await session.connection()
    await connection.execute(text("SET LOCAL session_replication_role = replica"))
    for check in ("ck_relationships_source_type", "ck_relationships_target_type"):
        await connection.execute(
            text(f"ALTER TABLE {s}.relationships DROP CONSTRAINT {check}")
        )
    await connection.execute(
        text(
            f"ALTER TABLE {s}.initiative_rules DROP CONSTRAINT ck_initiative_rules_key"
        )
    )
    await connection.execute(
        text(
            f"UPDATE {s}.initiatives SET queues_enabled = true, "
            "projects_enabled = false WHERE id = :i"
        ),
        {"i": initiative.id},
    )
    role = await _one(
        session,
        f"SELECT id FROM {s}.initiative_roles WHERE initiative_id = :i "
        "ORDER BY id DESC LIMIT 1",
        i=initiative.id,
    )
    await connection.execute(
        text(
            f"INSERT INTO {s}.initiative_rules (initiative_id, initiative_role_id, "
            "key, enabled) VALUES (:i, :r, 'queues_enabled', true), "
            "(:i, :r, 'create_queues', true)"
        ),
        {"i": initiative.id, "r": role},
    )
    queue = await _one(
        session,
        f"INSERT INTO {s}.queues (initiative_id, name, description, created_by, "
        "current_round, is_active, created_at, updated_at) VALUES (:i, 'Chores', "
        "'Whose week it is', :u, 3, true, '2026-01-01', '2026-01-02') RETURNING id",
        i=initiative.id,
        u=owner.id,
    )
    items = {}
    for label, position, held, visible, person in (
        ("Dishes", 3, None, True, None),
        ("Bins", 2, 2, True, None),
        ("Laundry", 1, None, False, None),
        ("Hoover", 0, None, True, member.id),
    ):
        items[label] = await _one(
            session,
            f"INSERT INTO {s}.queue_items (queue_id, label, position, "
            "held_at_round, is_visible, user_id, color, created_by, created_at) "
            "VALUES (:q, :l, :p, :h, :v, :u, '#FF0000', :c, now()) RETURNING id",
            q=queue,
            l=label,
            p=position,
            h=held,
            v=visible,
            u=person,
            c=owner.id,
        )
    await connection.execute(
        text(f"UPDATE {s}.queue_items SET notes = :n WHERE id = :i"),
        {"n": f"After #queue-item[Dishes]({items['Dishes']})", "i": items["Hoover"]},
    )
    await connection.execute(
        text(f"UPDATE {s}.queues SET current_item_id = :d WHERE id = :q"),
        {"d": items["Dishes"], "q": queue},
    )
    await connection.execute(
        text(
            f"INSERT INTO {s}.resource_grants (initiative_id, resource_type, "
            "resource_id, user_id, level, created_at, all_initiative_members) "
            "VALUES (:i, 'queue', :q, :u, 'owner', now(), false)"
        ),
        {"i": initiative.id, "q": queue, "u": owner.id},
    )
    comment = await _one(
        session,
        f"INSERT INTO {s}.comments (content, created_by, queue_id, created_at) "
        "VALUES ('Swap with me?', :u, :q, now()) RETURNING id",
        u=member.id,
        q=queue,
    )
    for source, relationship, target in (
        (("queue", queue), "tagged_with", ("tag", tag.id)),
        (("project", project.id), "references", ("queue_item", items["Bins"])),
    ):
        await connection.execute(
            text(
                f"INSERT INTO {s}.relationships (source_type, source_id, "
                "relationship_type, target_type, target_id, provenance, created_at) "
                "VALUES (:st, :si, :r, :tt, :ti, 'manual', now())"
            ),
            {
                "st": source[0],
                "si": source[1],
                "r": relationship,
                "tt": target[0],
                "ti": target[1],
            },
        )
    notice = await _one(
        session,
        "INSERT INTO public.notifications (user_id, type, data, guild_id, tool, "
        "resource_id, subject_type, subject_id, created_at) VALUES (:u, 'mention', "
        "CAST(:d AS json), :guild, 'queue', :q, 'queue_item', :i, now()) "
        "RETURNING id",
        u=member.id,
        d=json.dumps({"target_path": f"/go/queue-item/{items['Hoover']}"}),
        guild=guild.id,
        q=queue,
        i=items["Hoover"],
    )
    await connection.execute(text("SET LOCAL session_replication_role = origin"))
    await session.commit()

    await session.run_sync(run(True))
    await session.commit()

    converted, description, projects_on = (
        await _rows(
            session,
            f"SELECT p.id, p.description, i.projects_enabled FROM {s}.projects p "
            f"JOIN {s}.initiatives i ON i.id = p.initiative_id WHERE p.name = 'Chores'",
        )
    )[0]
    assert description == "Whose week it is\n\nRound 3 when this was a queue."
    assert projects_on
    tasks = await _rows(
        session,
        f"SELECT t.id, t.title, s.name, ty.name, t.description FROM {s}.tasks t "
        f"JOIN {s}.task_statuses s ON s.id = t.task_status_id "
        f"JOIN {s}.task_types ty ON ty.id = t.task_type_id "
        "WHERE t.project_id = :p ORDER BY t.position",
        p=converted,
    )
    by_title = {title: task_id for task_id, title, *_ in tasks}
    assert [(title, status, kind) for _, title, status, kind, _ in tasks] == [
        ("Dishes", "Up now", "Turn"),
        ("Bins", "Held", "Turn"),
        ("Laundry", "Sitting out", "Turn"),
        ("Hoover", "Waiting", "Turn"),
    ]
    assert tasks[-1][4] == f"After #task[Dishes]({by_title['Dishes']})"
    assert await _rows(
        session,
        f"SELECT name, category::text, is_default FROM {s}.task_statuses "
        "WHERE project_id = :p ORDER BY position",
        p=converted,
    ) == [
        ("Waiting", "todo", True),
        ("Up now", "in_progress", False),
        ("Held", "in_progress", False),
        ("Sitting out", "todo", False),
        ("Done", "done", False),
    ]

    assert sorted(
        await _rows(
            session,
            f"SELECT source_type, source_id, relationship_type, target_type, "
            f"target_id FROM {s}.relationships",
        )
    ) == sorted(
        [
            ("project", converted, "tagged_with", "tag", tag.id),
            ("project", project.id, "references", "task", by_title["Bins"]),
            ("task", by_title["Hoover"], "related_to", "user", member.id),
        ]
    )
    assert await _rows(
        session,
        f"SELECT resource_type, resource_id, user_id, level FROM {s}.resource_grants "
        "WHERE resource_type IN ('queue', 'project') AND resource_id = :p",
        p=converted,
    ) == [("project", converted, owner.id, "owner")]
    assert await _rows(
        session, f"SELECT project_id FROM {s}.comments WHERE id = :c", c=comment
    ) == [(converted,)]
    assert sorted(
        await _rows(
            session,
            f"SELECT key, enabled FROM {s}.initiative_rules "
            "WHERE initiative_role_id = :r AND key IN ('projects_enabled', "
            "'create_projects', 'queues_enabled', 'create_queues')",
            r=role,
        )
    ) == [("create_projects", True), ("projects_enabled", True)]
    assert await _rows(
        session,
        f"SELECT kind, definition FROM {s}.tool_layouts "
        "WHERE tool = 'project' AND tool_id = :p ORDER BY kind",
        p=converted,
    ) == [
        ("calendar", {"hidden": True}),
        ("default", {"kind": "board"}),
        ("gantt", {"hidden": True}),
    ]
    assert await _rows(
        session,
        "SELECT tool, resource_id, subject_type, subject_id, CAST(data AS jsonb) "
        "FROM public.notifications WHERE id = :n",
        n=notice,
    ) == [
        (
            "project",
            converted,
            "task",
            by_title["Hoover"],
            {"target_path": f"/go/task/{by_title['Hoover']}"},
        )
    ]
    for table in ("queues", "queue_items"):
        assert (
            await _one(session, "SELECT to_regclass(:t)", t=f"{schema}.{table}") is None
        )
