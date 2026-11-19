"""Counters, declared as a tool plug-in: the SDK's own example
(``test/support/counters.ts`` in initiative-plugin-sdk), as a manifest a
test registers."""

from __future__ import annotations

from typing import Any

__all__ = ["COUNTERS_UID", "counters_tool_manifest"]

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
                "list": {
                    "kind": "grid",
                    "card": {
                        "type": "card",
                        "children": [
                            _field("name"),
                            {
                                "type": "stack",
                                "props": {"tone": "muted"},
                                "children": [_field("description")],
                            },
                        ],
                    },
                },
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
                    "layouts": {
                        "list": {
                            "kind": "grid",
                            "card": {
                                "type": "card",
                                "children": [_field("name"), _field("count")],
                            },
                            "displays": {"count": "bar"},
                        },
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
