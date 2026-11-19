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
    "counters_tool_manifest",
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
