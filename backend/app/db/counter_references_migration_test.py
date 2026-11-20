"""Revision 20261120_0620 spells the references stored before 20261119_0619
with the Counters plug-in's kinds, ``counter_group.tsjvtcm0s7gv2x`` and
``counter.tsjvtcm0s7gv2x``, and its downgrade spells them the built-in way
again.

The test builds a community that uses the plug-in, writes into it what a
build before 0619 stored (``#counter-group[…](4)`` in a comment, a task's
description and the group's own text, a chip and a link in a post, a link
and an embed in a file's body and its Yjs state), and runs the revision on
the provisioning connection as a revision runs."""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.references import references_in_body, references_in_text
from app.db import session as db_session
from app.db.schema_provisioning import guild_schema_name
from app.models.platform.guild import CommunityRole
from app.services import editor_engine
from app.testing import create_comment, create_file, create_post, create_task
from app.testing.tool_plugins import add_counter, install_tool_plugin

GROUP = "counter_group.tsjvtcm0s7gv2x"
COUNTER = "counter.tsjvtcm0s7gv2x"

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20261120_0620_counter_references_name_the_plug_in.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(_MIGRATION.stem, _MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _run(session: AsyncSession, schema: str, forward: bool) -> None:
    """The revision one way or the other in ``schema`` alone."""
    migration = _load()

    def apply(bind: Any) -> None:
        bind.execute(
            sa.text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f"{schema}, public"},
        )
        with Operations.context(MigrationContext.configure(bind)):
            migration._apply(forward)

    await session.commit()
    async with db_session.provisioning_engine.begin() as conn:
        await conn.run_sync(apply)


def _body(*nodes: dict[str, Any]) -> dict[str, Any]:
    return {
        "root": {
            "type": "root",
            "version": 1,
            "direction": None,
            "format": "",
            "indent": 0,
            "children": [
                {
                    "type": "paragraph",
                    "version": 1,
                    "direction": None,
                    "format": "",
                    "indent": 0,
                    "textFormat": 0,
                    "textStyle": "",
                    "children": list(nodes),
                }
            ],
        }
    }


def _link(kind: str, entity_id: int, words: str) -> dict[str, Any]:
    return {
        "type": "entity-mention",
        "version": 1,
        "entityType": kind,
        "entityId": entity_id,
        "text": words,
    }


def _chip(entity_id: int, words: str) -> dict[str, Any]:
    return {
        "type": "smart-chip",
        "version": 1,
        "chipKind": "counter:value",
        "entityId": entity_id,
        "text": words,
    }


def _kinds(value: Any) -> list[str]:
    """Every ``entityType`` a body's nodes name, as stored."""
    if isinstance(value, list):
        return [kind for item in value for kind in _kinds(item)]
    if not isinstance(value, dict):
        return []
    own = [value["entityType"]] if "entityType" in value else []
    return own + [kind for item in value.values() for kind in _kinds(item)]


async def test_references_stored_before_counters_moved_name_the_plug_in(
    session: AsyncSession, acting_user: Callable[..., Any], client: AsyncClient
) -> None:
    admin = await acting_user(
        guild_role=CommunityRole.admin, initiative=True, project=True
    )
    seat = await acting_user(guild=admin.guild, guild_role=CommunityRole.superadmin)
    await session.commit()
    await install_tool_plugin(client, session, seat)
    _tools, group, counter = await add_counter(
        session, admin.guild.id, admin.initiative.id
    )
    schema = guild_schema_name(admin.guild.id)
    s = f'"{schema}"'

    said = f"see #counter-group[Scores]({group}) and #counter[Laps]({counter})"
    task = await create_task(session, admin.project, description=said)
    comment = await create_comment(session, admin.user, task=task, content=said)
    post = await create_post(
        session,
        admin.initiative,
        admin.user,
        body=_body(_link("counter_group", group, "Scores"), _chip(counter, "Laps")),
    )
    filed = _body(_link("counter", counter, "Laps"))
    file = await create_file(session, admin.initiative, admin.user)
    state = await editor_engine.bootstrap(filed)
    connection = await session.connection()
    await connection.execute(
        sa.text(
            f"UPDATE {s}.files SET content = CAST(:c AS jsonb), yjs_state = :y"
            " WHERE id = :f"
        ),
        {"c": json.dumps(filed), "y": state, "f": file.id},
    )
    await connection.execute(
        sa.text(
            f"UPDATE {s}.p_tsjvtcm0s7gv2x_counter_group SET description = :d"
            " WHERE id = :g"
        ),
        {"d": f"#counter[Laps]({counter})", "g": group},
    )
    await session.commit()

    async def stored() -> dict[str, Any]:
        connection = await session.connection()

        async def one(sql: str, **params: Any) -> Any:
            return (await connection.execute(sa.text(sql), params)).scalar_one()

        content, yjs = (
            await connection.execute(
                sa.text(f"SELECT content, yjs_state FROM {s}.files WHERE id = :f"),
                {"f": file.id},
            )
        ).one()
        return {
            "comment": await one(
                f"SELECT content FROM {s}.comments WHERE id = :c", c=comment.id
            ),
            "task": await one(
                f"SELECT description FROM {s}.tasks WHERE id = :t", t=task.id
            ),
            "group": await one(
                f"SELECT description FROM {s}.p_tsjvtcm0s7gv2x_counter_group"
                " WHERE id = :g",
                g=group,
            ),
            "post": await one(f"SELECT body FROM {s}.posts WHERE id = :p", p=post.id),
            "file": content,
            "live": await editor_engine.render(bytes(yjs)),
        }

    await _run(session, schema, forward=True)
    after = await stored()
    assert (
        after["comment"]
        == after["task"]
        == (
            f"see #counter-group.tsjvtcm0s7gv2x[Scores]({group})"
            f" and #counter.tsjvtcm0s7gv2x[Laps]({counter})"
        )
    )
    assert references_in_text(after["comment"]) == {(GROUP, group), (COUNTER, counter)}
    assert after["group"] == f"#counter.tsjvtcm0s7gv2x[Laps]({counter})"
    # The chip of a fact the plug-in does not offer is a link to the counter.
    assert after["post"]["root"]["children"][0]["children"] == [
        _link(GROUP, group, "Scores"),
        _link(COUNTER, counter, "Laps"),
    ]
    assert references_in_body(after["file"]) == {(COUNTER, counter)}
    assert references_in_body(after["live"]) == {(COUNTER, counter)}

    # Twice changes nothing more.
    await _run(session, schema, forward=True)
    assert await stored() == after

    await _run(session, schema, forward=False)
    before = await stored()
    assert before["comment"] == before["task"] == said
    assert before["group"] == f"#counter[Laps]({counter})"
    assert before["post"]["root"]["children"][0]["children"] == [
        _link("counter_group", group, "Scores"),
        _link("counter", counter, "Laps"),
    ]
    assert _kinds(before["file"]) == _kinds(before["live"]) == ["counter"]
    await _run(session, schema, forward=True)
