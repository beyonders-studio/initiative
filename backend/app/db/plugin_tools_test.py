"""A tool plug-in's tool: built from its declaration, created in the
community that installs it, and ruled as a built-in tool is."""

from __future__ import annotations

import copy
from typing import Any

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import GuildPluginMessages
from app.core.tool_set import BUILTIN_TOOLS
from app.db.guild_ddl import render_guild_rls_ddl
from app.db.plugin_tools import (
    InstalledTool,
    PluginToolError,
    community_tool_set,
    provisioned_tools,
)
from app.db.schema_provisioning import (
    GuildRoleKind,
    _backfill_guild,
    get_provisioning_bundle,
    guild_role_name,
    guild_schema_name,
    stamp_has_tools,
)
from app.models.platform.guild import CommunityRole
from app.models.tenant.initiative import InitiativeRule
from app.services.marketplace.tool_plugins import (
    normalize_tool_plugin_definition,
    tool_kinds,
)
from app.testing import (
    COUNTERS_UID,
    counters_tool_manifest,
    create_initiative,
    install_tool_plugin,
    route_session_to_guild,
)

#: A second plug-in declaring the same key as Counters (owner ruling: both
#: install side by side).
OTHER_UID = "ZZ11TXXKPMG2NB"

_UNIVERSAL_TOOL = {
    "id", "initiative_id", "name", "position", "created_at", "updated_at",
    "created_by", "created_by_kind", "deleted_at", "deleted_by",
    "deleted_by_kind", "purge_at", "archived_at", "held_at", "hold_id",
    "listing_uid", "listing_version", "comments_enabled", "comments_locked_at",
}  # fmt: skip
_UNIVERSAL_ITEM = {
    "id", "counter_group_id", "name", "position", "created_at", "updated_at",
    "created_by", "created_by_kind", "deleted_at", "deleted_by",
    "deleted_by_kind", "purge_at", "held_at", "hold_id",
}  # fmt: skip


def _counters() -> dict[str, Any]:
    return normalize_tool_plugin_definition(counters_tool_manifest())


def _kinds(definition: dict[str, Any], uid: str) -> list[str]:
    """The kinds a declaration names, whether or not its keys are good."""
    tool = definition["tool"]
    keys = [tool["key"], *(item["key"] for item in tool.get("items", []))]
    return [f"{key}.{str(uid).lower()}" for key in keys]


def _set(definition: dict[str, Any], uid: str = COUNTERS_UID, install_id: int = 1):
    codes = {kind: 1024 + i for i, kind in enumerate(_kinds(definition, uid))}
    return community_tool_set([InstalledTool(install_id, uid, definition)], codes)


async def _columns(session: AsyncSession, schema: str) -> dict[str, set[str]]:
    rows = await session.exec(
        sa.text(
            "SELECT table_name, column_name FROM information_schema.columns"
            " WHERE table_schema = :s AND table_name LIKE 'p\\_%'"
        ),
        params={"s": schema},
    )
    found: dict[str, set[str]] = {}
    for table, column in rows.all():
        found.setdefault(table, set()).add(column)
    return found


@pytest.mark.parametrize(
    ("where", "value"),
    [
        ("key", "Counter_group"),
        ("key", 'counter"; DROP TABLE tasks; --'),
        ("key", "a" * 41),
        ("field", "id"),
        ("field", "parent_id"),
        ("field", "view mode"),
        ("uid", "tsjvtcm0s7gv2x"),
        ("uid", "TSJVTCM0S7GV2'"),
    ],
)
def test_the_builder_refuses_a_hostile_name(where: str, value: str):
    """Every name is built from the declaration, so the builder checks each
    key and the uid again, whatever registration let through."""
    definition = copy.deepcopy(_counters())
    uid = COUNTERS_UID
    if where == "key":
        definition["tool"]["key"] = value
    elif where == "field":
        definition["tool"]["items"][0]["fields"][1]["key"] = value
    else:
        uid = value
    with pytest.raises(PluginToolError):
        _set(definition, uid)


def test_the_render_with_a_tool_rules_its_tables_and_without_one_names_none():
    group, counter = "p_tsjvtcm0s7gv2x_counter_group", "p_tsjvtcm0s7gv2x_counter"
    ddl = render_guild_rls_ddl(_set(_counters()))
    for table in (group, counter):
        for policy in (
            "initiative_member_select",
            "initiative_member_insert",
            "initiative_member_update",
            "initiative_member_delete",
            "frozen_ancestor_insert",
            "trashed_read",
            "soft_delete_admin_purge",
            "held_restrict",
        ):
            assert f"CREATE POLICY {policy} ON {table} " in ddl, (policy, table)
    assert f"'counter_group.{COUNTERS_UID.lower()}:enabled'" in ddl
    assert "p_tsjvtcm0s7gv2x" not in render_guild_rls_ddl(BUILTIN_TOOLS)


async def test_a_community_with_no_tool_plugin_keeps_the_bundle():
    bundle = await get_provisioning_bundle()
    assert bundle.for_tools(BUILTIN_TOOLS) is bundle
    assert not stamp_has_tools(bundle.stamp)


def test_an_item_under_an_item_walks_two_hops():
    definition = _counters()
    definition["tool"]["items"].append(
        {
            "key": "tally",
            "name": {"en": "Tally"},
            "parent": "counter",
            "fields": [{"key": "note", "name": {"en": "Note"}, "kind": "text"}],
        }
    )
    ddl = render_guild_rls_ddl(_set(definition))
    assert "CREATE POLICY initiative_member_select ON p_tsjvtcm0s7gv2x_tally " in ddl
    assert (
        "FROM p_tsjvtcm0s7gv2x_counter dmid JOIN p_tsjvtcm0s7gv2x_counter_group dpar"
        in ddl
    )


async def test_install_creates_exactly_the_declared_tables(
    client: AsyncClient, session: AsyncSession, acting_user
):
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    await install_tool_plugin(client, session, seat)
    schema = guild_schema_name(seat.guild.id)
    columns = await _columns(session, schema)
    assert columns == {
        "p_tsjvtcm0s7gv2x_counter_group": _UNIVERSAL_TOOL | {"description"},
        "p_tsjvtcm0s7gv2x_counter": _UNIVERSAL_ITEM
        | {"count", "min", "max", "step", "initial_count", "color", "view_mode"},
    }
    types = dict(
        (
            await session.exec(
                sa.text(
                    "SELECT attname::text, format_type(atttypid, atttypmod)"
                    " FROM pg_attribute WHERE attrelid = to_regclass(:t)"
                    " AND attnum > 0"
                ),
                params={"t": f'"{schema}".p_tsjvtcm0s7gv2x_counter'},
            )
        ).all()
    )
    assert types["count"] == "numeric(20,10)"
    assert types["view_mode"] == "text"
    # The community's stamp names its tools, and a back-fill finds nothing to
    # do for a community that is current.
    stamp = await session.scalar(
        sa.text("SELECT obj_description(to_regnamespace(:s), 'pg_namespace')"),
        {"s": schema},
    )
    assert stamp_has_tools(stamp)
    await session.commit()
    assert await _backfill_guild(seat.guild.id, wait=True) is False
    # No installed plug-in reaches the tables: the plug-in role holds no
    # grant on them, whatever scope an install is given.
    plugin_role = guild_role_name(seat.guild.id, GuildRoleKind.plugin)
    for table in columns:
        assert not await session.scalar(
            sa.text("SELECT has_table_privilege(:r, :t, 'SELECT, INSERT')"),
            {"r": plugin_role, "t": f'"{schema}".{table}'},
        )


async def test_the_tool_is_on_in_every_initiative_then_and_later(
    client: AsyncClient, session: AsyncSession, acting_user
):
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    install = await install_tool_plugin(client, session, seat)
    later = await create_initiative(session, seat.guild, seat.user)
    await route_session_to_guild(session, seat.guild.id)
    rows = (
        await session.exec(
            sa.select(InitiativeRule.initiative_id, InitiativeRule.enabled).where(
                InitiativeRule.key == f"counter_group.{COUNTERS_UID.lower()}:enabled",
                InitiativeRule.initiative_role_id.is_(None),
                InitiativeRule.install_id == install["id"],
            )
        )
    ).all()
    assert dict(rows) == {seat.initiative.id: True, later.id: True}


async def test_two_plugins_with_one_key_install_side_by_side(
    client: AsyncClient, session: AsyncSession, acting_user
):
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    first = await install_tool_plugin(client, session, seat)
    second = await install_tool_plugin(client, session, seat, uid=OTHER_UID)
    tools = await provisioned_tools(seat.guild.id)
    assert [(tool.kind, tool.install_id) for tool in tools.installed] == [
        (f"counter_group.{COUNTERS_UID.lower()}", first["id"]),
        (f"counter_group.{OTHER_UID.lower()}", second["id"]),
    ]
    columns = await _columns(session, guild_schema_name(seat.guild.id))
    assert set(columns) == {
        f"p_{uid.lower()}_{key}"
        for uid in (COUNTERS_UID, OTHER_UID)
        for key in ("counter_group", "counter")
    }
    await route_session_to_guild(session, seat.guild.id)
    switches = (
        await session.exec(
            sa.select(InitiativeRule.key, InitiativeRule.install_id).where(
                InitiativeRule.initiative_id == seat.initiative.id,
                InitiativeRule.initiative_role_id.is_(None),
                InitiativeRule.install_id.is_not(None),
            )
        )
    ).all()
    assert sorted(switches) == sorted(
        [
            (f"counter_group.{COUNTERS_UID.lower()}:enabled", first["id"]),
            (f"counter_group.{OTHER_UID.lower()}:enabled", second["id"]),
        ]
    )
    assert tool_kinds(_counters(), listing_uid=OTHER_UID)[0] == tools.installed[1].kind


async def test_a_tool_plugin_is_not_removed_or_updated_yet(
    client: AsyncClient, session: AsyncSession, acting_user
):
    seat = await acting_user(guild_role=CommunityRole.superadmin)
    install = await install_tool_plugin(client, session, seat)
    path = seat.g(f"/plugins/{install['id']}")
    for response in (
        await client.delete(path, headers=seat.headers),
        await client.patch(path, headers=seat.headers, json={"enabled": False}),
        await client.post(f"{path}/upgrade", headers=seat.headers),
    ):
        assert response.status_code == 409, response.text
        assert response.json()["detail"] == GuildPluginMessages.TOOL_UNCHANGEABLE
