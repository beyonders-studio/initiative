"""A tool plug-in's definition, held to the checks the SDK makes.

Every key becomes a table or column name once a community installs the tool,
so a refusal here is the deployment's own check, not the publisher's."""

from collections.abc import Callable

import pytest

from app.services.marketplace.definitions import normalize_listing_definition
from app.services.marketplace.manifest_values import ListingDefinitionError
from app.services.marketplace.tool_plugins import tool_kinds
from app.testing import COUNTERS_UID, counters_tool_manifest


def _normalize(body: dict) -> dict:
    return normalize_listing_definition("plugin", body, public_id="beyonders.counters")


def _counter(body: dict) -> dict:
    return body["tool"]["items"][0]


def _field(body: dict, key: str) -> dict:
    return next(f for f in _counter(body)["fields"] if f["key"] == key)


def test_counters_registers_as_declared():
    stored = _normalize(counters_tool_manifest())
    assert stored["plugin_kind"] == "tool"
    assert stored["features"] == ["tool"]
    assert stored["default_name"] == "Counters"
    assert stored["tool"] == counters_tool_manifest()["tool"]


def test_a_republish_stores_the_same_document():
    assert _normalize(_normalize(counters_tool_manifest())) == _normalize(
        counters_tool_manifest()
    )


def test_its_kinds_are_its_keys_and_its_uid():
    stored = _normalize(counters_tool_manifest())
    assert tool_kinds(stored, listing_uid=COUNTERS_UID) == [
        "counter_group.tsjvtcm0s7gv2x",
        "counter.tsjvtcm0s7gv2x",
    ]


def test_a_term_nobody_declared_is_dropped():
    body = counters_tool_manifest()
    body["tool"]["layout"] = {"columns": 3}
    body["tool"]["items"][0]["fields"][1]["width"] = 4
    stored = _normalize(body)
    assert "layout" not in stored["tool"]
    assert "width" not in stored["tool"]["items"][0]["fields"][1]


def _set(path: Callable[[dict], dict], key: str, value) -> Callable[[dict], None]:
    def change(body: dict) -> None:
        path(body)[key] = value

    return change


def _add_field(field: dict) -> Callable[[dict], None]:
    return lambda body: _counter(body)["fields"].append(field)


def _items(count: int) -> Callable[[dict], None]:
    def change(body: dict) -> None:
        body["tool"]["items"] = [
            {
                "key": f"item_{n}",
                "name": {"en": "Item"},
                "fields": [{"key": "note", "name": {"en": "Note"}, "kind": "text"}],
            }
            for n in range(count)
        ]

    return change


def _nested(body: dict) -> None:
    items = body["tool"]["items"]
    for key, parent in (("a", None), ("b", "a"), ("c", "b")):
        items.append(
            {
                "key": key,
                "name": {"en": key},
                "fields": [{"key": "note", "name": {"en": "Note"}, "kind": "text"}],
                **({"parent": parent} if parent else {}),
            }
        )


def _tool(body: dict) -> dict:
    return body["tool"]


def _open(condition: dict) -> Callable[[dict], None]:
    return _set(_counter, "open_while", condition)


REFUSALS: dict[str, tuple[Callable[[dict], None], str]] = {
    # What a tool plug-in carries.
    "a service block": (
        _set(lambda b: b, "service", {"public_id": "a.b"}),
        "runs no code",
    ),
    "hosts": (_set(lambda b: b, "hosts", ["api.example.com"]), "runs no code"),
    "endpoints": (_set(lambda b: b, "endpoints", [{"id": "x"}]), "runs no code"),
    "settings": (_set(lambda b: b, "settings", [{"key": "x"}]), "runs no code"),
    "another feature": (_set(lambda b: b, "features", ["tool", "widgets"]), "exactly"),
    "no tool": (_set(lambda b: b, "tool", None), "declares its tool"),
    # Keys.
    "a key starting with a digit": (_set(_tool, "key", "1group"), "lower-case letter"),
    "an upper-case key": (_set(_tool, "key", "Group"), "lower-case letter"),
    "a key with a hyphen": (_set(_tool, "key", "counter-group"), "not '-'"),
    "a key with a quote": (_set(_tool, "key", "a'b"), 'not "\'"'),
    "a key over 40 characters": (_set(_tool, "key", "a" * 41), "longer than 40"),
    "a universal column": (
        _add_field({"key": "position", "name": {"en": "P"}, "kind": "number"}),
        "every tool's rows have",
    ),
    "a key to a parent": (
        _add_field({"key": "owner_id", "name": {"en": "O"}, "kind": "number"}),
        "'_id'",
    ),
    "a field twice": (
        _add_field({"key": "min", "name": {"en": "M"}, "kind": "number"}),
        "share the key",
    ),
    "an item with the tool's key": (
        _set(_counter, "key", "counter_group"),
        "the tool's or another item's",
    ),
    "an unknown icon": (_set(_tool, "icon", "rocket"), "tool icon"),
    "no name": (_set(_tool, "name", None), "label"),
    # Caps and depth.
    "33 fields": (
        _set(
            _counter,
            "fields",
            [{"key": f"f{n}", "name": {"en": "F"}, "kind": "text"} for n in range(33)],
        ),
        "more than 32",
    ),
    "5 items": (_items(5), "more than 4"),
    "three levels": (_nested, "two levels deep"),
    "an item under itself": (_set(_counter, "parent", "counter"), "under itself"),
    "an item under nothing": (
        _set(_counter, "parent", "ghost"),
        "not one of the tool's items",
    ),
    "an item with no fields": (_set(_counter, "fields", []), "at least one field"),
    "17 actions": (
        lambda body: _tool(body).__setitem__(
            "actions",
            [
                {"id": f"a{n}", "name": {"en": "A"}, "on": "counter", "write": "{}"}
                for n in range(17)
            ],
        ),
        "more than 16",
    ),
    # Field kinds.
    "an unknown kind": (
        _add_field({"key": "photo", "name": {"en": "P"}, "kind": "image"}),
        "kind must be one of",
    ),
    "a select with no options": (
        _add_field({"key": "pick", "name": {"en": "P"}, "kind": "select"}),
        "at least one option",
    ),
    "options on a number": (
        lambda body: _field(body, "min").__setitem__(
            "options", [{"value": "a", "label": {"en": "A"}}]
        ),
        "only a select",
    ),
    "a currency field with none": (
        _add_field({"key": "price", "name": {"en": "P"}, "kind": "currency"}),
        "currency",
    ),
    "a currency on a number": (
        lambda body: _field(body, "min").__setitem__("currency", "EUR"),
        "only a currency field",
    ),
    "a counter on a number": (
        lambda body: _field(body, "min").__setitem__("counter", {"step": 1}),
        "only a counter field",
    ),
    "a bound naming no number field": (
        lambda body: _field(body, "count")["counter"].__setitem__("max", "color"),
        "not a number field",
    ),
    "a step of 0": (
        lambda body: _field(body, "count")["counter"].__setitem__("step", 0),
        "above 0",
    ),
    "a min above its max": (
        lambda body: _field(body, "count").__setitem__("counter", {"min": 5, "max": 1}),
        "min is above its max",
    ),
    "a counter's default": (
        lambda body: _field(body, "count").__setitem__("default", 3),
        "'initial'",
    ),
    "a person as a default": (
        _add_field(
            {"key": "who", "name": {"en": "W"}, "kind": "user_reference", "default": 1}
        ),
        "never a default",
    ),
    "a select default that is not an option": (
        lambda body: _field(body, "view_mode").__setitem__("default", "dial"),
        "not a value",
    ),
    "a colour default that is not #rrggbb": (
        lambda body: _field(body, "color").__setitem__("default", "red"),
        "not a value",
    ),
    "a date default that does not exist": (
        _add_field(
            {"key": "due", "name": {"en": "D"}, "kind": "date", "default": "2026-02-30"}
        ),
        "not a value",
    ),
    "a scale default over 100": (
        _add_field(
            {"key": "mood", "name": {"en": "M"}, "kind": "scale", "default": 101}
        ),
        "not a value",
    ),
    # Open conditions.
    "an open condition on no field": (
        _open({"field": "ghost", "below": 3}),
        "not a field of this item",
    ),
    "two open conditions": (
        _open({"field": "count", "below": 3, "above": 1}),
        "one condition",
    ),
    "an unknown condition": (_open({"field": "count", "near": 3}), "not a condition"),
    "a comparison on a colour": (
        _open({"field": "color", "below": 3}),
        "reads a number",
    ),
    "a comparison with a colour field": (
        _open({"field": "count", "below": {"field": "color"}}),
        "not a number or counter field",
    ),
    "a comparison with a field that is not a key": (
        _open({"field": "count", "below": {"field": []}}),
        "not a number or counter field",
    ),
    "a bound too large for a number": (
        lambda body: _field(body, "count")["counter"].__setitem__("max", 10**400),
        "a bound is a number",
    ),
    "a default too large for a number": (
        lambda body: _field(body, "step").__setitem__("default", 10**400),
        "not a value",
    ),
    "'is' on a number": (_open({"field": "count", "is": True}), "reads a checkbox"),
    "'in' an option that is not one": (
        _open({"field": "view_mode", "in": ["dial"]}),
        "not an option",
    ),
    "'not_passed' on a number": (
        _open({"field": "count", "not_passed": True}),
        "reads a date",
    ),
    # Actions.
    "an action on nothing": (
        lambda body: _tool(body)["actions"][0].__setitem__("on", "ghost"),
        "neither the tool's key",
    ),
    "an action asking for another table's field": (
        lambda body: _tool(body)["actions"][0].__setitem__("params", ["count"]),
        "not a field of 'counter_group'",
    ),
    "a write that does not parse": (
        lambda body: _tool(body)["actions"][0].__setitem__("write", '{"set": '),
        "does not parse",
    ),
    "an action twice": (
        lambda body: _tool(body)["actions"].append(dict(_tool(body)["actions"][0])),
        "share the id",
    ),
}


@pytest.mark.parametrize("change", list(REFUSALS), ids=list(REFUSALS))
def test_what_the_sdk_refuses_is_refused_here(change):
    mutate, problem = REFUSALS[change]
    body = counters_tool_manifest()
    mutate(body)
    with pytest.raises(ListingDefinitionError, match=problem):
        _normalize(body)


def test_only_a_tool_plugin_declares_a_tool():
    with pytest.raises(ListingDefinitionError, match="only a tool plug-in"):
        normalize_listing_definition(
            "plugin",
            {
                "plugin_kind": "service",
                "service": {"public_id": "tests.widget-co"},
                "features": [],
                "tool": counters_tool_manifest()["tool"],
            },
        )
