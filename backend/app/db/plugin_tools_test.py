"""A tool plug-in's tool: built from its declaration, created in the
community that installs it, and ruled as a built-in tool is."""

from __future__ import annotations

import copy
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import GuildPluginMessages
from app.core.tool_set import BUILTIN_TOOLS
from app.db.event_capture import render_guild_capture_ddl
from app.db.guild_ddl import render_guild_rls_ddl
from app.db.kind_codes import assign_plugin_kind_codes
from app.db.plugin_tools import (
    InstalledTool,
    PluginToolError,
    community_tool_set,
    provisioned_tools,
    structure_ddl,
)
from app.db.schema_provisioning import (
    GuildRoleKind,
    _backfill_guild,
    get_provisioning_bundle,
    guild_role_name,
    guild_schema_name,
    stamp_tools,
)
from app.db.search_index import render_guild_search_ddl
from app.db.timers import render_guild_timer_ddl
from app.models.platform.guild import CommunityRole
from app.models.platform.plugin_install import PluginInstall, PluginInstallStatus
from app.models.tenant._mixins import ActorKind
from app.models.tenant.comment import Comment
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.initiative import InitiativeRule
from app.models.tenant.reaction import Reaction
from app.models.tenant.tool_layout import ToolLayout
from app.services.marketplace.tool_plugins import (
    normalize_tool_plugin_definition,
    tool_kinds,
)
from app.services.platform import guild_purge
from app.services.platform.retention import PLUGIN_INSTALL_DELETION_DAYS
from app.services.tenant import plugin_updates
from app.testing import (
    COUNTERS_UID,
    counters_tool_manifest,
    create_marketplace_listing,
    create_reaction,
    install_tool_plugin,
    route_as,
    route_session_to_guild,
)

#: A second plug-in declaring the same key as Counters (owner ruling: both
#: install side by side).
OTHER_UID = "ZZ11TXXKPMG2NB"

_GROUP = f"p_{COUNTERS_UID.lower()}_counter_group"
_COUNTER = f"p_{COUNTERS_UID.lower()}_counter"
_KIND = f"counter_group.{COUNTERS_UID.lower()}"


_UNIVERSAL_TOOL = {
    "id", "initiative_id", "name", "position", "created_at", "updated_at",
    "created_by", "created_by_kind", "deleted_at", "deleted_by",
    "deleted_by_kind", "purge_at", "archived_at", "held_at", "hold_id",
    "listing_uid", "listing_version", "comments_enabled", "comments_locked_at",
}  # fmt: skip
_UNIVERSAL_ITEM = {
    "id", "counter_group_id", "name", "position", "created_at", "updated_at",
    "created_by", "created_by_kind", "deleted_at", "deleted_by",
    "deleted_by_kind", "purge_at", "archived_at", "held_at", "hold_id",
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


def test_a_tool_plugins_tables_are_captured_indexed_and_timed():
    """Its tables take the change capture, search and timer triggers a
    built-in tool's do, and a render without it names none of them."""
    tools = _set(_counters())
    for table in ("p_tsjvtcm0s7gv2x_counter_group", "p_tsjvtcm0s7gv2x_counter"):
        assert f"CREATE TRIGGER capture_{table}\n" in render_guild_capture_ddl(tools)
        assert f"  AFTER INSERT OR DELETE ON {table}\n" in render_guild_search_ddl(
            None, tools
        )
        assert f"CREATE TRIGGER tr_{table}_timer_trash\n" in render_guild_timer_ddl(
            tools
        )
    for render in (
        render_guild_capture_ddl(BUILTIN_TOOLS),
        render_guild_search_ddl(None, BUILTIN_TOOLS),
        render_guild_timer_ddl(BUILTIN_TOOLS),
    ):
        assert "p_tsjvtcm0s7gv2x" not in render
    # The change capture reads a tool plug-in's kind off its table's name, so
    # no built-in table may be named like one.
    assert not [name for name in BUILTIN_TOOLS.tables if name.startswith("p_")]


async def test_a_community_with_no_tool_plugin_keeps_the_bundle():
    bundle = await get_provisioning_bundle()
    assert bundle.for_tools(BUILTIN_TOOLS) is bundle
    assert stamp_tools(bundle.stamp) is None


def test_an_item_under_an_item_walks_two_hops():
    definition = _counters()
    # Declared before the item it sits under.
    definition["tool"]["items"].insert(
        0,
        {
            "key": "tally",
            "name": {"en": "Tally"},
            "parent": "counter",
            "fields": [{"key": "note", "name": {"en": "Note"}, "kind": "text"}],
        },
    )
    tools = _set(definition)
    structure = structure_ddl(tools)
    assert structure.index("CREATE TABLE IF NOT EXISTS p_tsjvtcm0s7gv2x_counter (") < (
        structure.index("CREATE TABLE IF NOT EXISTS p_tsjvtcm0s7gv2x_tally (")
    )
    ddl = render_guild_rls_ddl(tools)
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
    assert stamp_tools(stamp) is not None
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


async def test_a_tool_plugins_rows_are_heard_found_and_purged_on_time(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """An item's change is told under the sharing of its tool, as a task's is
    under its project's; it is indexed under its own kind; and its trash arms
    the community's purge."""
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    await install_tool_plugin(client, session, seat)
    await route_session_to_guild(session, seat.guild.id)
    group = (
        await session.exec(
            sa.text(
                "INSERT INTO p_tsjvtcm0s7gv2x_counter_group (initiative_id, name)"
                " VALUES (:i, 'Scores') RETURNING id"
            ),
            params={"i": seat.initiative.id},
        )
    ).scalar_one()
    counter = (
        await session.exec(
            sa.text(
                "INSERT INTO p_tsjvtcm0s7gv2x_counter (counter_group_id, name)"
                " VALUES (:g, 'Laps') RETURNING id"
            ),
            params={"g": group},
        )
    ).scalar_one()
    events = (
        await session.exec(
            sa.text(
                "SELECT resource_type, resource_id, initiative_id, dac_tool, dac_id"
                " FROM event_outbox WHERE resource_type LIKE 'p\\_%' ORDER BY id"
            )
        )
    ).all()
    kind = f"counter_group.{COUNTERS_UID.lower()}"
    initiative = seat.initiative.id
    assert [tuple(e) for e in events] == [
        ("p_tsjvtcm0s7gv2x_counter_group", group, initiative, kind, group),
        ("p_tsjvtcm0s7gv2x_counter", counter, initiative, kind, group),
    ]
    entries = (
        await session.exec(
            sa.text(
                "SELECT entity_type, entity_id, dac_tool, dac_id, title"
                " FROM search_entries WHERE entity_type LIKE '%.%' ORDER BY entity_id"
            )
        )
    ).all()
    assert sorted(tuple(e) for e in entries) == sorted(
        [
            (kind, group, kind, group, "Scores"),
            (f"counter.{COUNTERS_UID.lower()}", counter, kind, group, "Laps"),
        ]
    )
    armed = await session.exec(
        sa.text(
            "SELECT tgname FROM pg_trigger WHERE tgrelid IN"
            " (to_regclass('p_tsjvtcm0s7gv2x_counter_group'),"
            " to_regclass('p_tsjvtcm0s7gv2x_counter')) AND tgname LIKE '%timer%'"
        )
    )
    assert sorted(armed.scalars()) == [
        "tr_p_tsjvtcm0s7gv2x_counter_group_timer_trash",
        "tr_p_tsjvtcm0s7gv2x_counter_timer_trash",
    ]
    # The trash sweep's next visit, as a visit and the reconcile read it,
    # counts the item in the bin.
    from app.services.sweep_timers import _due, sweeps

    purge_at = datetime(2030, 1, 1, tzinfo=UTC)
    await session.exec(
        sa.text(
            "UPDATE p_tsjvtcm0s7gv2x_counter SET deleted_at = now(),"
            " deleted_by_kind = 'system', purge_at = :at WHERE id = :c"
        ),
        params={"at": purge_at, "c": counter},
    )
    trash = next(sweep for sweep in sweeps() if sweep.kind == "trash")
    tools = await provisioned_tools(seat.guild.id)
    due = await session.exec(
        _due(trash, datetime.now(UTC), tools).execution_options(include_deleted=True)
    )
    assert due.first() == purge_at
    # Its retention past, the sweep purges it.
    from app.services.tenant.trash_purge import _run_purge_pass

    await _run_purge_pass(session, now=purge_at + timedelta(days=1), tools=tools)
    gone = await session.scalar(
        sa.text("SELECT count(*) FROM p_tsjvtcm0s7gv2x_counter WHERE id = :c"),
        {"c": counter},
    )
    assert gone == 0


async def test_the_tool_is_on_in_every_initiative_then_and_later(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Switched on, with each table's starting layouts, in every initiative
    there is and every one made later: a list and an item page per table."""
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    install = await install_tool_plugin(client, session, seat)
    made = await client.post(
        seat.g("/initiatives/"), headers=seat.headers, json={"name": "Later"}
    )
    assert made.status_code == 201, made.text
    later = made.json()["id"]
    await route_session_to_guild(session, seat.guild.id)
    rows = (
        await session.exec(
            sa.select(InitiativeRule.initiative_id, InitiativeRule.enabled).where(
                InitiativeRule.key == f"{_KIND}:enabled",
                InitiativeRule.initiative_role_id.is_(None),
                InitiativeRule.install_id == install["id"],
            )
        )
    ).all()
    assert dict(rows) == {seat.initiative.id: True, later: True}
    layouts = (
        await session.exec(
            sa.select(ToolLayout.initiative_id, ToolLayout.tool, ToolLayout.kind).where(
                ToolLayout.tool.endswith(COUNTERS_UID.lower())
            )
        )
    ).all()
    assert sorted(layouts) == sorted(
        (initiative, f"{key}.{COUNTERS_UID.lower()}", kind)
        for initiative in (seat.initiative.id, later)
        for key in ("counter_group", "counter")
        for kind in ("grid", "detail")
    )


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


async def _index_row(session: AsyncSession, guild_id: int, install_id: int):
    return (
        await session.exec(
            sa.select(PluginInstall)
            .where(
                PluginInstall.guild_id == guild_id,
                PluginInstall.install_id == install_id,
            )
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def _publish(session: AsyncSession, version: str, change) -> None:
    """Publish ``version`` of Counters, its tool as ``change`` leaves it."""
    manifest = counters_tool_manifest()
    change(manifest["tool"])
    await create_marketplace_listing(
        session,
        uid=COUNTERS_UID,
        public_id=f"test.{COUNTERS_UID.lower()}",
        kind="plugin",
        name="Counters",
        version=version,
        definition=manifest,
    )


async def test_uninstalling_keeps_the_tool_until_its_window_ends(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Removing asks the seat to consent to the content's deletion; the tool
    is then gone from the community and its tables, rows and rules stay.
    Installing it again in the window brings back the same install."""
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    install = await install_tool_plugin(client, session, seat)
    path = seat.g(f"/plugins/{install['id']}")
    refused = await client.delete(path, headers=seat.headers)
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == GuildPluginMessages.TOOL_DELETION_UNCONFIRMED

    removed = await client.delete(
        path, headers=seat.headers, params={"delete_content": "true"}
    )
    assert removed.status_code == 204, removed.text
    assert (await client.get(path, headers=seat.headers)).status_code == 404
    listed = await client.get(seat.g("/plugins/"), headers=seat.headers)
    assert install["id"] not in {plugin["id"] for plugin in listed.json()["items"]}
    schema = guild_schema_name(seat.guild.id)
    assert set(await _columns(session, schema)) == {_GROUP, _COUNTER}
    row = await _index_row(session, seat.guild.id, install["id"])
    assert row.status == PluginInstallStatus.deleted.value
    assert row.uninstalled_at == row.status_changed_at
    await route_session_to_guild(session, seat.guild.id)
    rules = await session.scalar(
        sa.select(sa.func.count()).where(InitiativeRule.install_id == install["id"])
    )
    assert rules
    await session.commit()

    back = await client.post(
        seat.g("/plugins/"), headers=seat.headers, json={"listing_uid": COUNTERS_UID}
    )
    assert back.status_code == 201, back.text
    assert back.json()["id"] == install["id"]
    row = await _index_row(session, seat.guild.id, install["id"])
    assert (row.status, row.uninstalled_at) == (PluginInstallStatus.active.value, None)
    again = await client.post(
        seat.g("/plugins/"), headers=seat.headers, json={"listing_uid": COUNTERS_UID}
    )
    assert again.json()["detail"] == GuildPluginMessages.ALREADY_INSTALLED


async def test_the_window_ending_takes_the_tool_and_what_names_it(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Past its window, the sweep deletes the rows that name the tool, the
    install and its rules, then drops its tables and renders the community
    without it, and no further step is asked of anyone."""
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    install = await install_tool_plugin(client, session, seat)
    await route_session_to_guild(session, seat.guild.id)
    group = (
        await session.exec(
            sa.text(
                f"INSERT INTO {_GROUP} (initiative_id, name) VALUES (:i, 'Scores')"
                " RETURNING id"
            ),
            params={"i": seat.initiative.id},
        )
    ).scalar_one()
    comment = Comment(
        content="Nice",
        created_by=seat.user.id,
        created_by_kind=ActorKind.member,
        subject_type=_KIND,
        subject_id=group,
    )
    session.add(comment)
    await session.commit()
    comment_id = comment.id
    await create_reaction(session, seat.user, comment=comment)
    layouts = await session.scalar(
        sa.select(sa.func.count()).where(ToolLayout.tool == _KIND)
    )
    assert layouts == 2
    removed = await client.delete(
        seat.g(f"/plugins/{install['id']}"),
        headers=seat.headers,
        params={"delete_content": "true"},
    )
    assert removed.status_code == 204, removed.text

    within = datetime.now(UTC) + timedelta(days=PLUGIN_INSTALL_DELETION_DAYS - 1)
    assert await guild_purge.uninstall_deleted_plugins(session, now=within) == 0
    past = datetime.now(UTC) + timedelta(days=PLUGIN_INSTALL_DELETION_DAYS + 1)

    async def hold(held: datetime | None) -> None:
        """Hold the group, or let it go, past its own guards."""
        await route_session_to_guild(session, seat.guild.id)
        await session.exec(sa.text("SET LOCAL session_replication_role = replica"))
        await session.exec(
            sa.text(f"UPDATE {_GROUP} SET held_at = :held WHERE id = :id"),
            params={"held": held, "id": group},
        )
        await session.commit()

    # Held by the platform, it waits for the next sweep, deleting nothing.
    await hold(datetime.now(UTC))
    assert await guild_purge.uninstall_deleted_plugins(session, now=past) == 0
    assert set(await _columns(session, guild_schema_name(seat.guild.id))) == {
        _GROUP,
        _COUNTER,
    }
    await route_session_to_guild(session, seat.guild.id)
    assert await session.scalar(
        sa.select(sa.func.count()).where(Comment.id == comment_id)
    )
    await session.commit()
    await hold(None)
    assert await guild_purge.uninstall_deleted_plugins(session, now=past) == 1

    schema = guild_schema_name(seat.guild.id)
    assert await _columns(session, schema) == {}
    assert await _index_row(session, seat.guild.id, install["id"]) is None
    await route_session_to_guild(session, seat.guild.id)
    for table, where in (
        (GuildPlugin, GuildPlugin.id == install["id"]),
        (InitiativeRule, InitiativeRule.install_id == install["id"]),
        (Comment, Comment.subject_type == _KIND),
        (Reaction, Reaction.target_id == comment_id),
        (ToolLayout, ToolLayout.tool.startswith("counter")),
    ):
        assert not await session.scalar(
            sa.select(sa.func.count()).select_from(table).where(where)
        ), table
    stamp = await session.scalar(
        sa.text("SELECT obj_description(to_regnamespace(:s), 'pg_namespace')"),
        {"s": schema},
    )
    assert stamp_tools(stamp) is None
    await session.commit()
    assert await _backfill_guild(seat.guild.id, wait=True) is False

    # Installing it now is a new install, with new tables.
    again = await client.post(
        seat.g("/plugins/"), headers=seat.headers, json={"listing_uid": COUNTERS_UID}
    )
    assert again.status_code == 201, again.text
    assert set(await _columns(session, schema)) == {_GROUP, _COUNTER}


async def test_turning_a_tool_plugin_off_is_its_switch(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    """Off, the tool is on in no initiative, and still there for the
    community's admin as a switched-off tool is."""
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    install = await install_tool_plugin(client, session, seat)
    path = seat.g(f"/plugins/{install['id']}")
    user_id, guild_id = seat.user.id, seat.guild.id
    pair = f"{seat.initiative.id}:{_KIND}"
    for enabled in (False, True):
        response = await client.patch(
            path, headers=seat.headers, json={"enabled": enabled}
        )
        assert response.status_code == 200, response.text
        reader = await role_session("app_user")
        context = await route_as(reader, user_id=user_id, guild_id=guild_id)
        assert (pair in context.enabled_tools) is enabled
        assert {f"*:{_KIND}", f"+:{_KIND}"} <= set(context.enabled_tools)
        await reader.rollback()


async def test_a_version_adding_to_the_tool_waits_for_the_seat(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A version adding a field, an option, an item table and an action is
    held until the seat takes it; taking it adds the column and the table,
    lays the new table out, and keeps every row."""
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    install = await install_tool_plugin(client, session, seat)
    await route_session_to_guild(session, seat.guild.id)
    await session.exec(
        sa.text(f"INSERT INTO {_GROUP} (initiative_id, name) VALUES (:i, 'Kept')"),
        params={"i": seat.initiative.id},
    )
    await session.commit()

    def grow(tool: dict[str, Any]) -> None:
        counter = tool["items"][0]
        counter["fields"].append(
            {"key": "unit", "name": {"en": "Unit"}, "kind": "text"}
        )
        view_mode = next(f for f in counter["fields"] if f["key"] == "view_mode")
        view_mode["options"].append({"value": "dial", "label": {"en": "Dial"}})
        tally = copy.deepcopy(counter)
        tally.update(key="tally", name={"en": "Tally"})
        del tally["open_while"]
        tool["items"].append(tally)
        tool["actions"].append(
            {**tool["actions"][0], "id": "reset_again", "name": {"en": "Again"}}
        )

    await _publish(session, "1.1.0", grow)
    path = seat.g(f"/plugins/{install['id']}")
    detail = (await client.get(path, headers=seat.headers)).json()
    asks = detail["pending_update"]
    assert asks["version"] == "1.1.0"
    assert asks["added_tables"] == ["tally"]
    assert asks["added_fields"] == ["counter.unit"]
    assert asks["added_options"] == ["counter.view_mode.dial"]
    assert asks["added_actions"] == ["reset_again"]
    assert asks["dropped_fields"] == []
    waiting = await client.post(f"{path}/upgrade", headers=seat.headers)
    assert waiting.status_code == 409, waiting.text
    assert waiting.json()["detail"]["code"] == GuildPluginMessages.UPGRADE_NEEDS_CONSENT

    taken = await client.post(
        f"{path}/upgrade", headers=seat.headers, json={"version": "1.1.0"}
    )
    assert taken.status_code == 200, taken.text
    columns = await _columns(session, guild_schema_name(seat.guild.id))
    tally = f"p_{COUNTERS_UID.lower()}_tally"
    assert "unit" in columns[_COUNTER] and tally in columns
    await route_session_to_guild(session, seat.guild.id)
    assert await session.scalar(sa.text(f"SELECT name FROM {_GROUP}")) == "Kept"
    await session.exec(
        sa.text(
            f"INSERT INTO {_COUNTER} (counter_group_id, name, view_mode)"
            f" SELECT id, 'Dial', 'dial' FROM {_GROUP}"
        )
    )
    laid_out = await session.scalar(
        sa.select(sa.func.count()).where(
            ToolLayout.tool == f"tally.{COUNTERS_UID.lower()}",
            ToolLayout.initiative_id == seat.initiative.id,
        )
    )
    assert laid_out == 2


async def test_the_sweep_takes_a_version_asking_nothing_and_holds_the_rest(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A version renaming a field adds nothing and is applied, with the
    community rendered from it; one adding a field waits for the seat."""
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    install = await install_tool_plugin(client, session, seat)
    guild_id = seat.guild.id

    def rename(tool: dict[str, Any]) -> None:
        tool["fields"][0]["name"] = {"en": "About"}

    def grow(tool: dict[str, Any]) -> None:
        rename(tool)
        tool["fields"].append({"key": "notes", "name": {"en": "Notes"}, "kind": "text"})

    for version, change in (("1.0.1", rename), ("1.1.0", grow)):
        await _publish(session, version, change)
        await route_session_to_guild(session, guild_id)
        await plugin_updates.update_guild(session, guild_id)
    await route_session_to_guild(session, guild_id)
    plugin = await session.get(GuildPlugin, install["id"], populate_existing=True)
    assert (plugin.listing_version, plugin.pending_version) == ("1.0.1", "1.1.0")
    stamp = await session.scalar(
        sa.text("SELECT obj_description(to_regnamespace(:s), 'pg_namespace')"),
        {"s": guild_schema_name(guild_id)},
    )
    assert stamp_tools(stamp) == (await provisioned_tools(guild_id)).digest
    assert "notes" not in (await _columns(session, guild_schema_name(guild_id)))[_GROUP]


async def test_a_major_drops_what_the_seat_confirms_and_keeps_the_rest(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A new major dropping a field and a select's option is applied once the
    seat names both: the field's column goes, the cells holding the option are
    emptied, and every other value stays."""
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    install = await install_tool_plugin(client, session, seat)
    await route_session_to_guild(session, seat.guild.id)
    await session.exec(
        sa.text(
            f"WITH g AS (INSERT INTO {_GROUP} (initiative_id, name)"
            " VALUES (:i, 'Looks') RETURNING id)"
            f" INSERT INTO {_COUNTER} (counter_group_id, name, view_mode, color)"
            " SELECT g.id, v.name, v.mode, '#112233' FROM g, (VALUES"
            " ('Clock', 'segmented_clock'), ('Bar', 'progress_bar')) AS v(name, mode)"
        ),
        params={"i": seat.initiative.id},
    )
    await session.commit()

    def shed(tool: dict[str, Any]) -> None:
        counter = tool["items"][0]
        counter["fields"] = [f for f in counter["fields"] if f["key"] != "color"]
        view_mode = next(f for f in counter["fields"] if f["key"] == "view_mode")
        view_mode["options"].pop()
        detail = counter["layouts"]["detail"]["side"][0]
        detail["children"] = [
            part for part in detail["children"] if part["props"]["field"] != "color"
        ]

    await _publish(session, "2.0.0", shed)
    path = seat.g(f"/plugins/{install['id']}")
    for partial in (
        {"version": "2.0.0"},
        {"version": "2.0.0", "drop_fields": ["counter.color"]},
    ):
        unconfirmed = await client.post(
            f"{path}/upgrade", headers=seat.headers, json=partial
        )
        assert unconfirmed.status_code == 409, unconfirmed.text
    asks = unconfirmed.json()["detail"]
    assert asks["dropped_fields"] == ["counter.color"]
    assert asks["dropped_options"] == ["counter.view_mode.segmented_clock"]
    columns = await _columns(session, guild_schema_name(seat.guild.id))
    assert "color" in columns[_COUNTER]

    taken = await client.post(
        f"{path}/upgrade",
        headers=seat.headers,
        json={
            "version": "2.0.0",
            "drop_fields": ["counter.color"],
            "drop_options": ["counter.view_mode.segmented_clock"],
        },
    )
    assert taken.status_code == 200, taken.text
    columns = await _columns(session, guild_schema_name(seat.guild.id))
    assert "color" not in columns[_COUNTER]
    await route_session_to_guild(session, seat.guild.id)
    looks = dict(
        (await session.exec(sa.text(f"SELECT name, view_mode FROM {_COUNTER}"))).all()
    )
    assert looks == {"Clock": None, "Bar": "progress_bar"}
    refused = await session.exec(
        sa.text(
            f"SELECT relforcerowsecurity FROM pg_class WHERE oid = '{_COUNTER}'::regclass"
        )
    )
    assert refused.scalar_one() is True


async def test_boot_brings_an_older_item_table_up_to_its_shape(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """An item table made before items were archived has no stamp column. The
    back-fill of a community whose render moved adds it, and what reads it."""
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    await install_tool_plugin(client, session, seat)
    schema = guild_schema_name(seat.guild.id)
    counter = f'"{schema}".p_tsjvtcm0s7gv2x_counter'
    stamp = await session.scalar(
        sa.text("SELECT obj_description(to_regnamespace(:s), 'pg_namespace')"),
        {"s": schema},
    )
    await session.exec(
        sa.text(f"ALTER TABLE {counter} DROP COLUMN archived_at CASCADE")
    )
    behind = re.sub(r"schema=[^,]*", "schema=older", stamp)
    await session.exec(sa.text(f"COMMENT ON SCHEMA \"{schema}\" IS '{behind}'"))
    await session.commit()

    assert await _backfill_guild(seat.guild.id, wait=True) is True

    assert (
        "archived_at" in (await _columns(session, schema))["p_tsjvtcm0s7gv2x_counter"]
    )
    frozen = await session.scalar(
        sa.text(
            "SELECT count(*) FROM pg_trigger WHERE tgrelid = to_regclass(:t)"
            " AND tgname LIKE '%frozen%'"
        ),
        {"t": counter},
    )
    assert frozen > 0


async def test_a_tool_plugins_search_is_current_by_its_own_sources(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A community whose tool plug-in's rows were written before they were
    indexed is behind its own search generation, not the built-in one, and
    the back-fill indexes them."""
    from app.db.schema_provisioning import backfill_guild_search
    from app.db.search_index import search_generation

    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    await install_tool_plugin(client, session, seat)
    schema = guild_schema_name(seat.guild.id)
    await route_session_to_guild(session, seat.guild.id)
    await session.exec(sa.text("SET LOCAL session_replication_role = replica"))
    group = (
        await session.exec(
            sa.text(
                "INSERT INTO p_tsjvtcm0s7gv2x_counter_group"
                " (initiative_id, name, created_by_kind)"
                " VALUES (:i, 'Unindexed', 'system') RETURNING id"
            ),
            params={"i": seat.initiative.id},
        )
    ).scalar_one()
    await session.exec(
        sa.text(
            f"COMMENT ON TABLE \"{schema}\".search_entries IS '{search_generation()}'"
        )
    )
    await session.commit()
    tools = await provisioned_tools(seat.guild.id)
    assert search_generation(tools) != search_generation()

    await backfill_guild_search()

    await route_session_to_guild(session, seat.guild.id)
    found = await session.scalar(
        sa.text(
            "SELECT count(*) FROM search_entries WHERE entity_id = :g"
            " AND entity_type = :k"
        ),
        {"g": group, "k": f"counter_group.{COUNTERS_UID.lower()}"},
    )
    assert found == 1
    marker = await session.scalar(
        sa.text("SELECT obj_description(to_regclass(:t), 'pg_class')"),
        {"t": f'"{schema}".search_entries'},
    )
    assert marker == search_generation(tools)


async def test_boot_provisions_an_install_whose_provisioning_never_ran(
    session: AsyncSession, acting_user
):
    """An install row committed without its tables, its rules or its switch
    rows, and a stamp naming no tools: the back-fill provisions all of it."""
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    definition = _counters()
    await assign_plugin_kind_codes(
        session, tool_kinds(definition, listing_uid=COUNTERS_UID)
    )
    await route_session_to_guild(session, seat.guild.id)
    install = GuildPlugin(
        listing_uid=COUNTERS_UID,
        listing_version="1.0.0",
        plugin_kind="tool",
        name="Counters",
        definition=definition,
        config={},
        granted_scopes=[],
        created_by=seat.user.id,
        created_by_kind=ActorKind.member,
    )
    session.add(install)
    await session.commit()
    schema = guild_schema_name(seat.guild.id)
    stamp = await session.scalar(
        sa.text("SELECT obj_description(to_regnamespace(:s), 'pg_namespace')"),
        {"s": schema},
    )
    assert stamp_tools(stamp) is None
    assert await _columns(session, schema) == {}

    assert await _backfill_guild(seat.guild.id, wait=True) is True

    assert set(await _columns(session, schema)) == {
        "p_tsjvtcm0s7gv2x_counter_group",
        "p_tsjvtcm0s7gv2x_counter",
    }
    stamp = await session.scalar(
        sa.text("SELECT obj_description(to_regnamespace(:s), 'pg_namespace')"),
        {"s": schema},
    )
    assert stamp_tools(stamp) == (await provisioned_tools(seat.guild.id)).digest
    policies = await session.scalar(
        sa.text(
            "SELECT count(*) FROM pg_policy"
            " WHERE polrelid = to_regclass(:t) AND polname LIKE 'initiative_member_%'"
        ),
        {"t": f'"{schema}".p_tsjvtcm0s7gv2x_counter_group'},
    )
    assert policies == 4
    await route_session_to_guild(session, seat.guild.id)
    switch = await session.scalar(
        sa.select(InitiativeRule.enabled).where(
            InitiativeRule.initiative_id == seat.initiative.id,
            InitiativeRule.initiative_role_id.is_(None),
            InitiativeRule.install_id == install.id,
        )
    )
    assert switch is True
    # Once current, the next boot leaves it alone.
    await session.commit()
    assert await _backfill_guild(seat.guild.id, wait=True) is False
