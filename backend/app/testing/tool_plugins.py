"""Counters, declared as a tool plug-in: the SDK's own example
(``test/support/counters.ts`` in initiative-plugin-sdk), as a manifest a
test registers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.core.tool_set import ToolSet
    from app.testing.actor import Actor

__all__ = [
    "COUNTERS_UID",
    "add_counter",
    "convert_counters",
    "counters_conversion",
    "counters_tool_manifest",
    "install_counters",
    "install_tool_plugin",
]

#: The uid the SDK's example names Counters by.
COUNTERS_UID = "TSJVTCM0S7GV2X"


def _field(key: str) -> dict[str, Any]:
    """A layout's part drawing one field."""
    return {"type": "field", "props": {"field": key}}


def _header() -> list[dict[str, Any]]:
    """An item page's name and its menu, across the top."""
    return [
        {
            "type": "stack",
            "props": {"direction": "row", "gap": "sm", "align": "start"},
            "children": [_field("name"), {"type": "actions"}],
        }
    ]


def counters_tool_manifest() -> dict[str, Any]:
    """A fresh copy of the Counters tool plug-in's manifest."""
    return {
        "plugin_kind": "tool",
        "features": ["tool"],
        "default_name": "Counters",
        "tool": {
            "key": "counter_group",
            "name": {"en": "Counters"},
            "instance_name": {"en": "Counter group"},
            "icon": "gauge",
            "fields": [
                {"key": "description", "name": {"en": "Description"}, "kind": "text"}
            ],
            "layouts": {
                "lists": [
                    {
                        "kind": "grid",
                        "card": {
                            "type": "card",
                            "children": [
                                {
                                    "type": "items",
                                    "props": {
                                        "item": "counter",
                                        "fields": ["name", "count"],
                                        "limit": 4,
                                        "tint": "color",
                                    },
                                },
                                _field("name"),
                                {
                                    "type": "stack",
                                    "props": {"tone": "muted"},
                                    "children": [_field("description")],
                                },
                            ],
                        },
                    },
                    {"kind": "table", "columns": ["name", "description", "updated_at"]},
                ],
                "detail": {
                    "header": _header(),
                    "main": [_field("description"), {"type": "relations"}],
                    "side": [
                        {"type": "section", "children": [{"type": "properties"}]},
                        {"type": "byline"},
                    ],
                },
            },
            "items": [
                {
                    "key": "counter",
                    "name": {"en": "Counter"},
                    "fields": [
                        {
                            "key": "count",
                            "name": {"en": "Count"},
                            "kind": "counter",
                            "counter": {
                                "min": "min",
                                "max": "max",
                                "step": "step",
                                "initial": "initial_count",
                            },
                        },
                        {"key": "min", "name": {"en": "Minimum"}, "kind": "number"},
                        {"key": "max", "name": {"en": "Maximum"}, "kind": "number"},
                        {
                            "key": "step",
                            "name": {"en": "Step"},
                            "kind": "number",
                            "default": 1,
                            "required": True,
                        },
                        {
                            "key": "initial_count",
                            "name": {"en": "Starting count"},
                            "kind": "number",
                            "default": 0,
                            "required": True,
                        },
                        {
                            "key": "color",
                            "name": {"en": "Colour"},
                            "kind": "color",
                            "default": "random",
                        },
                        {
                            "key": "view_mode",
                            "name": {"en": "Look"},
                            "kind": "select",
                            "default": "number",
                            "required": True,
                            "options": [
                                {"value": "number", "label": {"en": "Number"}},
                                {"value": "bar", "label": {"en": "Progress bar"}},
                                {"value": "clock", "label": {"en": "Segmented clock"}},
                            ],
                        },
                    ],
                    "checks": [
                        {"field": "min", "at_most": {"field": "max"}},
                        {"field": "step", "above": 0},
                    ],
                    "layouts": {
                        "lists": [
                            {
                                "kind": "grid",
                                "card": {
                                    "type": "card",
                                    "props": {"tint": "color"},
                                    "children": [_field("name"), _field("count")],
                                },
                                "displays": {"count": {"from": "view_mode"}},
                                "presets": [
                                    {
                                        "slug": "by-name",
                                        "name": {"en": "By name"},
                                        "sort": [{"field": "name"}],
                                    },
                                    {
                                        "slug": "by-count",
                                        "name": {"en": "By count"},
                                        "sort": [
                                            {"field": "count", "dir": "desc"},
                                            {"field": "name"},
                                        ],
                                    },
                                ],
                            },
                            {
                                "kind": "table",
                                "columns": ["name", "count", "min", "max"],
                                "displays": {"count": {"from": "view_mode"}},
                            },
                        ],
                        "detail": {
                            "header": _header(),
                            "main": [_field("count"), {"type": "relations"}],
                            "side": [
                                {
                                    "type": "section",
                                    "children": [
                                        _field(key)
                                        for key in (
                                            "color",
                                            "min",
                                            "max",
                                            "step",
                                            "initial_count",
                                            "view_mode",
                                        )
                                    ],
                                },
                                {
                                    "type": "section",
                                    "children": [{"type": "properties"}],
                                },
                            ],
                        },
                    },
                    "open_while": {"field": "count", "below": {"field": "max"}},
                }
            ],
            "actions": [
                {
                    "id": "reset_all",
                    "name": {"en": "Reset all"},
                    "on": "counter_group",
                    "confirm": {
                        "en": "Put every counter in this group back to its starting count?"
                    },
                    "write": '{"items": {"counter": [items.counter.{"id": id, '
                    '"set": {"count": initial_count}}]}}',
                }
            ],
        },
    }


async def install_tool_plugin(
    client: AsyncClient,
    session: AsyncSession,
    seat: Actor,
    *,
    uid: str = COUNTERS_UID,
    definition: dict[str, Any] | None = None,
    placements: str | list[int] = "all",
) -> dict[str, Any]:
    """List a tool plug-in (Counters unless ``definition`` says otherwise),
    give its kinds their codes as registering it does, and install it as
    ``seat``, the community's seat, placed in ``placements`` (every
    initiative there is, as the install dialog offers first). Returns the
    install as the API reads it.
    ``session`` is committed first, so it holds nothing the provisioning of
    the tool's tables waits on."""
    from app.db.kind_codes import assign_plugin_kind_codes
    from app.services.marketplace.tool_plugins import (
        normalize_tool_plugin_definition,
        tool_kinds,
    )
    from app.testing.factories import create_marketplace_listing

    declared = normalize_tool_plugin_definition(definition or counters_tool_manifest())
    await create_marketplace_listing(
        session,
        uid=uid,
        public_id=f"test.{uid.lower()}",
        kind="plugin",
        name=declared["default_name"],
        definition=declared,
    )
    await assign_plugin_kind_codes(session, tool_kinds(declared, listing_uid=uid))
    await session.commit()
    response = await client.post(
        seat.g("/plugins/"),
        headers=seat.headers,
        json={"listing_uid": uid, "placements": placements},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def install_counters(
    session: AsyncSession, guild_id: int, installer_id: int, placements: set[int]
) -> ToolSet:
    """Install the Counters this build's catalogue ships (``core.counters``)
    in ``guild_id`` as ``installer_id``, its seat, through the service the
    marketplace's install calls, placed in ``placements``; then make its
    tables and switch it on in every initiative, as the install route does
    once the install commits. Returns the community's tools. Committed."""
    from app.db.schema_provisioning import provision_community_tools
    from app.services.marketplace import catalog as catalog_service
    from app.services.marketplace.installs import resolve_listing_install
    from app.services.tenant import guild_plugins as guild_plugins_service
    from app.services.tenant.initiative_tools import write_installed_tools
    from app.testing.schema_harness import route_session_to_guild

    await route_session_to_guild(session, guild_id)
    found = await catalog_service.get_listing(session, "core.counters")
    assert found is not None, "core.counters is not in the catalogue"
    listing, version = await resolve_listing_install(session, found.uid, kind="plugin")
    definition = dict(version.definition)
    plugin = await guild_plugins_service.install_plugin(
        session,
        listing_uid=listing.uid,
        listing_version=version.version,
        definition=definition,
        guild_id=guild_id,
        name=definition["default_name"],
        created_by=installer_id,
        actor_user_id=installer_id,
    )
    await guild_plugins_service.set_placed_initiatives(session, plugin, placements)
    await session.commit()
    tools = await provision_community_tools(guild_id)
    await route_session_to_guild(session, guild_id)
    await write_installed_tools(session, tools)
    await session.commit()
    return tools


async def add_counter(
    session: AsyncSession, guild_id: int, initiative_id: int, **counter: Any
) -> tuple[ToolSet, int, int]:
    """A counter group of the installed Counters in ``initiative_id``, and a
    counter in it with ``counter``'s columns: the community's tool set, the
    group's id and the counter's id. Added on ``session`` as it is routed (a
    request's, whose person then makes and owns them), or routed into the
    community where it is not. Committed."""
    from app.db.plugin_tools import provisioned_tools
    from app.db.session import routed_guild_id
    from app.db.tool_rows import locate
    from app.services.tenant.plugin_tool_rows import insert
    from app.testing.schema_harness import route_session_to_guild

    tools = await provisioned_tools(guild_id)
    (tool,) = tools.installed
    (item,) = tool.children
    if routed_guild_id(session) is None:
        await route_session_to_guild(session, guild_id)
    group = await insert(
        session,
        locate(tools, tool.kind),
        {"initiative_id": initiative_id, "name": "Scores"},
    )
    row = await insert(
        session,
        locate(tools, item.value),
        {"counter_group_id": group, "name": "Laps", **counter},
    )
    await session.commit()
    return tools, group, row


#: The revision that turns the built-in Counters into its plug-in.
_CONVERSION = "20261119_0619_counters_become_a_plug_in.py"


def counters_conversion() -> Any:
    """The revision that turns the built-in Counters into its plug-in,
    loaded by path."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / _CONVERSION
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def convert_counters(
    session: AsyncSession, guild_id: int, *, between: Any = None
) -> int | None:
    """Turn ``guild_id``'s Counters back into the built-in tool and convert it
    again, as the revision does in each community, then provision what a start
    renders for it. ``between`` is awaited with ``session`` while the built-in
    tool is back, before the conversion. Returns the install's id afterwards,
    None where the community has none. ``session`` is committed."""
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlmodel import select

    from app.db import session as db_session
    from app.db.kind_codes import ensure_kind_codes
    from app.db.schema_provisioning import provision_community_tools
    from app.models.tenant.guild_plugin import GuildPlugin
    from app.testing.schema_harness import route_session_to_guild

    migration = counters_conversion()

    def step(forward: bool) -> Any:
        def apply(bind: Any) -> None:
            bind.execute(
                sa.text("SELECT set_config('search_path', :sp, true)"),
                {"sp": f"guild_{guild_id}, public"},
            )
            with Operations.context(MigrationContext.configure(bind)):
                if forward:
                    migration._apply_upgrade()
                else:
                    migration._apply_downgrade()

        return apply

    # As a revision runs: on the provisioning connection, which owns the
    # tables and is held to their row security.
    await session.commit()
    async with db_session.provisioning_engine.begin() as conn:
        await conn.run_sync(step(forward=False))
    if between is not None:
        await between(session)
        await session.commit()
    async with db_session.provisioning_engine.begin() as conn:
        await conn.run_sync(step(forward=True))
    await ensure_kind_codes()
    await provision_community_tools(guild_id)
    await route_session_to_guild(session, guild_id)
    found = await session.exec(
        select(GuildPlugin.id).where(GuildPlugin.listing_uid == COUNTERS_UID)
    )
    return found.first()
