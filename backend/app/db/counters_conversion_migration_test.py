"""Revision 20261119_0619 turns the built-in Counters into its tool plug-in in
each community that uses it, and drops the tables elsewhere.

Each test builds a community as this release has it, turns it back into the
built-in tool with the downgrade, and converts it again with the upgrade, on
the provisioning connection as a revision runs. A converted community then
holds what one that installed the plug-in afresh holds, row for row and
rule for rule."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.relationships import Provenance, RelationshipType
from app.core.tools import Tool
from app.db.schema_provisioning import guild_schema_name
from app.models.platform.guild import CommunityRole
from app.services.tenant import relationships
from app.testing import create_comment, create_initiative
from app.testing.actor import Actor
from app.testing.factories import create_task
from app.testing.schema_harness import route_session_to_guild
from app.testing.tool_plugins import (
    COUNTERS_UID,
    add_counter,
    convert_counters,
    counters_conversion,
    install_tool_plugin,
)

GROUP = "counter_group.tsjvtcm0s7gv2x"
COUNTER = "counter.tsjvtcm0s7gv2x"


async def _rows(session: AsyncSession, sql: str, **params: Any) -> list[tuple]:
    result = await (await session.connection()).execute(sa.text(sql), params)
    return [tuple(row) for row in result.all()]


def _shape(schema: str) -> str:
    """Everything the catalog says about the Counters tables of ``schema``,
    with the schema and its roles' community named alike."""
    return f"""
    SELECT 'column', c.relname, a.attname,
           format_type(a.atttypid, a.atttypmod) || ' ' || a.attnotnull::text
           || ' ' || coalesce(pg_get_expr(d.adbin, d.adrelid), '')
    FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid
    LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
    WHERE c.relnamespace = '{schema}'::regnamespace
      AND c.relname LIKE 'p\\_tsjvtcm0s7gv2x\\_%' AND c.relkind = 'r'
      AND a.attnum > 0 AND NOT a.attisdropped
    UNION ALL
    SELECT 'constraint', c.conrelid::regclass::text, c.conname,
           pg_get_constraintdef(c.oid) || ' ' || c.convalidated::text
    FROM pg_constraint c
    WHERE c.connamespace = '{schema}'::regnamespace
      AND c.conrelid::regclass::text LIKE '%p\\_tsjvtcm0s7gv2x\\_%'
    UNION ALL
    SELECT 'index', i.tablename, i.indexname, i.indexdef
    FROM pg_indexes i
    WHERE i.schemaname = '{schema}' AND i.tablename LIKE 'p\\_tsjvtcm0s7gv2x\\_%'
    UNION ALL
    SELECT 'trigger', t.tgrelid::regclass::text, t.tgname, pg_get_triggerdef(t.oid)
    FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
    WHERE c.relnamespace = '{schema}'::regnamespace
      AND c.relname LIKE 'p\\_tsjvtcm0s7gv2x\\_%' AND NOT t.tgisinternal
    UNION ALL
    SELECT 'policy', p.tablename, p.policyname,
           p.permissive || ' ' || p.cmd || ' ' || p.roles::text || ' '
           || coalesce(p.qual, '') || ' ' || coalesce(p.with_check, '')
    FROM pg_policies p
    WHERE p.schemaname = '{schema}' AND p.tablename LIKE 'p\\_tsjvtcm0s7gv2x\\_%'
    UNION ALL
    SELECT 'grant', c.relname, a.grantee::regrole::text, a.privilege_type
    FROM pg_class c, aclexplode(c.relacl) a
    WHERE c.relnamespace = '{schema}'::regnamespace
      AND c.relname LIKE 'p\\_tsjvtcm0s7gv2x\\_%'
    UNION ALL
    SELECT 'table', c.relname, c.relrowsecurity::text, c.relforcerowsecurity::text
    FROM pg_class c
    WHERE c.relnamespace = '{schema}'::regnamespace
      AND c.relname LIKE 'p\\_tsjvtcm0s7gv2x\\_%'
    """


async def _catalog(session: AsyncSession, guild_id: int) -> set[tuple]:
    schema = guild_schema_name(guild_id)
    # Every name qualified alike, whichever schema the session is routed to.
    await _rows(session, "SELECT set_config('search_path', 'public', true)")
    return {
        tuple(
            str(value)
            .replace(schema, "guild_N")
            .replace(f"guild_{guild_id}_", "guild_N_")
            for value in row
        )
        for row in await _rows(session, _shape(schema))
    }


async def _community(
    acting_user: Callable[..., Any], client: AsyncClient, session: AsyncSession
) -> tuple[Actor, Actor]:
    admin = await acting_user(
        guild_role=CommunityRole.admin, initiative=True, project=True
    )
    seat = await acting_user(guild=admin.guild, guild_role=CommunityRole.superadmin)
    await session.commit()
    return admin, seat


async def _as_released(session: AsyncSession, schema: str) -> None:
    """What a release's start rendered over the built-in tables: a view that
    reads them, and policies on other tables reading the view or the tables,
    which the revision drops so the tables can go and a start renders anew."""
    s = f'"{schema}"'
    for statement in (
        (
            f"CREATE VIEW {s}.counted AS SELECT c.id, g.initiative_id"
            f" FROM {s}.counters c JOIN {s}.counter_groups g ON g.id = c.counter_group_id"
        ),
        (
            f"CREATE POLICY counted_read ON {s}.metadata_values AS RESTRICTIVE FOR SELECT"
            f" USING (entity_type <> 'counter' OR EXISTS"
            f" (SELECT 1 FROM {s}.counted WHERE counted.id = entity_id))"
        ),
        (
            f"CREATE POLICY counted_group ON {s}.comments AS RESTRICTIVE FOR SELECT"
            f" USING (subject_type <> 'counter_group' OR EXISTS"
            f" (SELECT 1 FROM {s}.counter_groups WHERE counter_groups.id = subject_id))"
        ),
    ):
        await (await session.connection()).execute(sa.text(statement))


async def _rendered_again(session: AsyncSession, schema: str) -> None:
    """Nothing the revision dropped is left behind, and the schema's stamp
    asks a start to render everything."""
    assert await _rows(
        session,
        "SELECT to_regclass(:v), (SELECT count(*) FROM pg_policy"
        " WHERE polname IN ('counted_read', 'counted_group'))",
        v=f'"{schema}".counted',
    ) == [(None, 0)]


async def test_a_community_using_counters_keeps_them_as_the_plug_in(
    session: AsyncSession, acting_user: Callable[..., Any], client: AsyncClient
) -> None:
    admin, seat = await _community(acting_user, client, session)
    guild = admin.guild
    s = f'"{guild_schema_name(guild.id)}"'
    initiative_a = admin.initiative.id
    initiative_b = (await create_initiative(session, guild, admin.user)).id
    await session.commit()
    await install_tool_plugin(client, session, seat)
    tools, group, counter = await add_counter(
        session, guild.id, initiative_a, view_mode="bar", max=10, count=3
    )
    task = await create_task(session, admin.project)
    await route_session_to_guild(session, guild.id)
    await relationships.create(
        session,
        source=relationships.Endpoint.of(tools, "task", task.id),
        relationship_type=RelationshipType.attached,
        target=relationships.Endpoint.of(tools, COUNTER, counter),
        provenance=Provenance.manual,
    )
    await session.commit()
    await create_comment(
        session, admin.user, project=admin.project, subject_type=GROUP, subject_id=group
    )
    await (await session.connection()).execute(
        sa.text(
            f"INSERT INTO {s}.resource_grants (resource_type, resource_id,"
            " initiative_id, user_id, level, all_initiative_members, created_at)"
            " VALUES (:k, :g, :i, :u, 'owner', false, now())"
        ),
        {"k": GROUP, "g": group, "i": initiative_a, "u": admin.user.id},
    )
    # Someone laid out the group's counter page.
    await (await session.connection()).execute(
        sa.text(
            f"INSERT INTO {s}.tool_layouts (initiative_id, tool, tool_id, kind,"
            " definition, created_by, created_by_kind, created_at, updated_at)"
            " VALUES (:i, :t, :g, :k, CAST(:d AS jsonb), :u, 'member', now(), now())"
        ),
        {
            "i": initiative_a,
            "t": GROUP,
            "g": group,
            "k": COUNTER,
            "d": json.dumps({"header": [], "main": [], "side": []}),
            "u": admin.user.id,
        },
    )
    # Counters is switched off in B today, and A is where it is used.
    await (await session.connection()).execute(
        sa.text(
            f"UPDATE {s}.initiative_rules SET enabled = false"
            " WHERE initiative_id = :b AND initiative_role_id IS NULL AND key = :k"
        ),
        {"b": initiative_b, "k": f"{GROUP}:enabled"},
    )
    await session.commit()

    def snapshot_sql() -> dict[str, str]:
        return {
            "groups": f"SELECT id, initiative_id, name FROM {s}.p_tsjvtcm0s7gv2x_counter_group",
            "counters": (
                f"SELECT id, counter_group_id, name, count, max, step, view_mode, color"
                f" FROM {s}.p_tsjvtcm0s7gv2x_counter"
            ),
            "edges": (
                f"SELECT source_type, source_id, target_type, target_id, source_node,"
                f" target_node FROM {s}.relationships WHERE removed_at IS NULL"
            ),
            "comments": f"SELECT subject_type, subject_id FROM {s}.comments",
            "grants": (
                f"SELECT resource_type, resource_id, level FROM {s}.resource_grants"
                f" WHERE resource_type IN ('{GROUP}', '{COUNTER}')"
            ),
            "rules": (
                f"SELECT initiative_id, initiative_role_id, key, enabled"
                f" FROM {s}.initiative_rules WHERE key LIKE '{GROUP}%'"
            ),
            "layouts": f"SELECT tool, tool_id, kind, definition FROM {s}.tool_layouts",
            "search": (
                f"SELECT entity_type, entity_id, dac_tool FROM {s}.search_entries"
                f" WHERE entity_type IN ('{GROUP}', '{COUNTER}')"
            ),
        }

    before = {
        name: sorted(await _rows(session, sql), key=repr)
        for name, sql in snapshot_sql().items()
    }
    assert before["edges"] and before["comments"] and before["grants"]

    async def as_the_builtin_tool(session: AsyncSession) -> None:
        await _as_released(session, guild_schema_name(guild.id))
        # Back to the built-in tool: its tables, kinds and keys.
        assert await _rows(
            session,
            f"SELECT view_mode::text FROM {s}.counters WHERE id = :c",
            c=counter,
        ) == [("progress_bar",)]
        assert await _rows(
            session, f"SELECT source_type, target_type FROM {s}.relationships"
        ) in ([("task", "counter")], [("counter", "task")])
        assert await _rows(
            session,
            f"SELECT count(*) FROM {s}.guild_plugins WHERE listing_uid = :u",
            u=COUNTERS_UID,
        ) == [(0,)]
        assert await _rows(session, f"SELECT tool, kind FROM {s}.tool_layouts") == [
            ("counter_group", "counter")
        ]
        keys = {
            key
            for (key,) in await _rows(
                session, f"SELECT DISTINCT key FROM {s}.initiative_rules"
            )
        }
        assert {"counter_groups_enabled", "create_counter_groups"} <= keys

    install_id = await convert_counters(session, guild.id, between=as_the_builtin_tool)
    assert install_id is not None
    await _rendered_again(session, guild_schema_name(guild.id))

    after = {
        name: sorted(await _rows(session, sql), key=repr)
        for name, sql in snapshot_sql().items()
    }
    assert after == before
    # Placed where Counters was on, and nowhere else.
    assert await _rows(
        session,
        f"SELECT initiative_id FROM {s}.plugin_placements WHERE install_id = :p",
        p=install_id,
    ) == [(initiative_a,)]
    assert await _rows(
        session,
        "SELECT listing_uid FROM public.plugin_installs"
        " WHERE guild_id = :g AND install_id = :p",
        g=guild.id,
        p=install_id,
    ) == [(COUNTERS_UID,)]
    assert await _rows(
        session,
        "SELECT kind, code FROM public.plugin_kind_codes WHERE kind IN (:g, :c)"
        " ORDER BY code",
        g=GROUP,
        c=COUNTER,
    ) == [(COUNTER, 3), (GROUP, 4)]

    # The tables are the plug-in's as an install makes them.
    fresh_admin, fresh_seat = await _community(acting_user, client, session)
    await install_tool_plugin(client, session, fresh_seat)
    assert await _catalog(session, guild.id) == await _catalog(
        session, fresh_admin.guild.id
    )


async def test_a_community_without_counters_loses_the_tables(
    session: AsyncSession, acting_user: Callable[..., Any], client: AsyncClient
) -> None:
    admin, _ = await _community(acting_user, client, session)
    guild_id = admin.guild.id
    schema = guild_schema_name(guild_id)

    async def as_the_builtin_tool(session: AsyncSession) -> None:
        await _as_released(session, schema)
        # The built-in tool's empty tables, switched off.
        assert await _rows(
            session,
            "SELECT to_regclass(:g) IS NOT NULL, to_regclass(:c) IS NOT NULL",
            g=f"{schema}.counter_groups",
            c=f"{schema}.counters",
        ) == [(True, True)]

    assert (
        await convert_counters(session, guild_id, between=as_the_builtin_tool) is None
    )
    assert await _rows(
        session,
        "SELECT to_regclass(:g), to_regclass(:c), to_regclass(:p)",
        g=f"{schema}.counter_groups",
        c=f"{schema}.counters",
        p=f"{schema}.p_tsjvtcm0s7gv2x_counter_group",
    ) == [(None, None, None)]
    assert await _rows(
        session,
        f'SELECT count(*) FROM "{schema}".initiative_rules WHERE key LIKE :k',
        k="%counter_group%",
    ) == [(0,)]


@pytest.mark.parametrize(
    ("sql", "renamed"),
    [
        (
            "SELECT name, count FROM counters ORDER BY name",
            (
                "SELECT name, count FROM p_tsjvtcm0s7gv2x_counter AS counters"
                " ORDER BY name"
            ),
        ),
        (
            (
                "SELECT counters.name, g.name FROM counters"
                " JOIN counter_groups g ON g.id = counters.counter_group_id"
            ),
            (
                "SELECT counters.name, g.name"
                " FROM p_tsjvtcm0s7gv2x_counter AS counters"
                " INNER JOIN p_tsjvtcm0s7gv2x_counter_group AS g"
                " ON g.id = counters.counter_group_id"
            ),
        ),
        (
            "SELECT counters.name FROM counters AS counters",
            "SELECT counters.name FROM p_tsjvtcm0s7gv2x_counter AS counters",
        ),
        ("SELECT counters.title FROM tasks AS counters", None),
        ("WITH counters AS (SELECT 1 AS n) SELECT n FROM counters", None),
        ("SELECT name FROM tasks", None),
    ],
)
def test_a_dashboard_query_reads_the_plug_ins_tables(
    sql: str, renamed: str | None
) -> None:
    migration = counters_conversion()
    assert migration._rewrite_sql(sql, migration.TABLES) == renamed


def test_the_frozen_version_is_the_bundled_one() -> None:
    from app.services.marketplace.builtin import CATALOG_DIR

    migration = counters_conversion()
    bundled = json.loads(
        (CATALOG_DIR / "core.counters.json").read_text(encoding="utf-8")
    )
    if bundled["version"] == migration._FROZEN["version"]:
        assert bundled["definition"] == migration._FROZEN["definition"]
    assert bundled["uid"] == COUNTERS_UID == migration.UID
    assert Tool.__members__.keys().isdisjoint({"counter_group"})
