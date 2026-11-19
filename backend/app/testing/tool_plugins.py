"""Counters, declared as a tool plug-in: the SDK's own example
(``test/support/counters.ts`` in initiative-plugin-sdk), as a manifest a
test registers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.testing.actor import Actor

__all__ = ["COUNTERS_UID", "counters_tool_manifest", "install_tool_plugin"]

#: The uid the SDK's example names Counters by.
COUNTERS_UID = "TSJVTCM0S7GV2X"


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
                        },
                        {
                            "key": "initial_count",
                            "name": {"en": "Starting count"},
                            "kind": "number",
                            "default": 0,
                        },
                        {"key": "color", "name": {"en": "Colour"}, "kind": "color"},
                        {
                            "key": "view_mode",
                            "name": {"en": "Look"},
                            "kind": "select",
                            "default": "number",
                            "options": [
                                {"value": "number", "label": {"en": "Number"}},
                                {
                                    "value": "progress_bar",
                                    "label": {"en": "Progress bar"},
                                },
                                {
                                    "value": "segmented_clock",
                                    "label": {"en": "Segmented clock"},
                                },
                            ],
                        },
                    ],
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
) -> dict[str, Any]:
    """List a tool plug-in (Counters unless ``definition`` says otherwise),
    give its kinds their codes as registering it does, and install it as
    ``seat``, the community's seat. Returns the install as the API reads it.
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
        seat.g("/plugins/"), headers=seat.headers, json={"listing_uid": uid}
    )
    assert response.status_code == 201, response.text
    return response.json()
