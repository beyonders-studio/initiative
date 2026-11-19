"""A tool plug-in's definition, held to the checks the SDK makes.

Every key becomes a table or column name once a community installs the tool,
so a refusal here is the deployment's own check, not the publisher's."""

from collections.abc import Callable

import pytest

from app.services.marketplace.definitions import normalize_listing_definition
from app.services.marketplace.manifest_values import ListingDefinitionError
from app.services.marketplace.tool_plugins import tool_kinds, tool_row_problems
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


def test_a_layout_names_the_table_s_fields_and_every_row_s():
    body = counters_tool_manifest()
    _counter(body)["fields"].append(
        {"key": "mood", "name": {"en": "Mood"}, "kind": "scale"}
    )
    _layouts(body)["lists"][1] = {
        "kind": "table",
        "columns": ["name", "count", "mood", "created_by", "updated_at", "tags"],
        "displays": {"count": "clock", "mood": "stars"},
    }
    _detail(body)["main"].append(_required("color"))
    stored = _normalize(body)
    assert _layouts(stored) == _layouts(body)


def test_a_masonry_wall_is_a_list_a_tool_draws():
    body = counters_tool_manifest()
    _layouts(body)["lists"].append({**_list(body), "kind": "masonry"})
    assert _layouts(_normalize(body))["lists"][2]["kind"] == "masonry"


def test_a_row_is_held_to_its_required_fields_and_checks():
    counter = _counter(_normalize(counters_tool_manifest()))
    row = {"step": 1, "initial_count": 0, "view_mode": "bar", "min": 0, "max": 9}
    assert tool_row_problems(counter, row) == []
    # An empty side holds, as the table's CHECK does.
    assert tool_row_problems(counter, {**row, "max": None}) == []
    assert tool_row_problems(counter, {**row, "step": None, "min": 10}) == [
        ("step", "required"),
        ("min", "at_most"),
    ]
    assert tool_row_problems(counter, {**row, "step": 0}) == [("step", "above")]


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


#: An item's one field, and its layouts showing it.
_NOTE = {
    "fields": [{"key": "note", "name": {"en": "Note"}, "kind": "text"}],
    "layouts": {
        "lists": [{"kind": "table", "columns": ["name", "note"]}],
        "detail": {"main": [{"type": "field", "props": {"field": "note"}}]},
    },
}


def _items(count: int) -> Callable[[dict], None]:
    def change(body: dict) -> None:
        body["tool"]["items"] = [
            {"key": f"item_{n}", "name": {"en": "Item"}, **_NOTE} for n in range(count)
        ]

    return change


def _nested(body: dict) -> None:
    items = body["tool"]["items"]
    for key, parent in (("a", None), ("b", "a"), ("c", "b")):
        items.append(
            {
                "key": key,
                "name": {"en": key},
                **_NOTE,
                **({"parent": parent} if parent else {}),
            }
        )


def _tool(body: dict) -> dict:
    return body["tool"]


def _open(condition: dict) -> Callable[[dict], None]:
    return _set(_counter, "open_while", condition)


def _layouts(body: dict) -> dict:
    """The counter's layouts."""
    return _counter(body)["layouts"]


def _list(body: dict) -> dict:
    """The counter's grid."""
    return _layouts(body)["lists"][0]


def _preview(body: dict) -> dict:
    """The props of the counters a group's card previews."""
    return _tool(body)["layouts"]["lists"][0]["card"]["children"][0]["props"]


def _checks(*checks: dict) -> Callable[[dict], None]:
    return _set(_counter, "checks", list(checks))


def _sorts(*fields: str) -> Callable[[dict], None]:
    return lambda body: _list(body)["presets"][0].__setitem__(
        "sort", [{"field": field} for field in fields]
    )


def _detail(body: dict) -> dict:
    return _layouts(body)["detail"]


def _place(part: dict) -> Callable[[dict], None]:
    """Puts a part in the counter's page."""
    return lambda body: _detail(body)["main"].append(part)


def _on_card(part: dict) -> Callable[[dict], None]:
    return lambda body: _list(body)["card"]["children"].append(part)


def _required(key: str) -> dict:
    return {"type": "field", "props": {"field": key, "required": True}}


def _deep(depth: int) -> dict:
    part: dict = {"type": "field", "props": {"field": "name"}}
    for _ in range(depth - 1):
        part = {"type": "section", "children": [part]}
    return part


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
    "a key over 17 characters": (_set(_tool, "key", "a" * 18), "longer than 17"),
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
    "a required field with no default": (
        _add_field(
            {"key": "note", "name": {"en": "N"}, "kind": "text", "required": True}
        ),
        "has a default",
    ),
    "a required person": (
        _add_field(
            {
                "key": "who",
                "name": {"en": "W"},
                "kind": "user_reference",
                "required": True,
            }
        ),
        "never required",
    ),
    "required that is not true or false": (
        lambda body: _field(body, "step").__setitem__("required", "yes"),
        "true or false",
    ),
    "no checks": (_checks(), "leave 'checks' out"),
    "nine checks": (_checks(*[{"field": "step", "above": 0}] * 9), "more than 8"),
    "a check on a colour": (_checks({"field": "color", "above": 0}), "reads a number"),
    "a check on no field": (
        _checks({"field": "ghost", "above": 0}),
        "not a field of this table",
    ),
    "a check that is not a comparison": (
        _checks({"field": "count", "is": True}),
        "not a condition",
    ),
    "a check with another table's field": (
        _checks({"field": "min", "below": {"field": "description"}}),
        "not a number or counter field of this table",
    ),
    "a check the defaults break": (
        _checks({"field": "initial_count", "at_least": {"field": "step"}}),
        "defaults do not hold",
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
    # Layouts.
    "no layouts": (_set(_tool, "layouts", None), "layouts must be an object"),
    "an item with no page": (
        lambda body: _layouts(body).pop("detail"),
        "lists and a detail",
    ),
    "a field named tags": (
        _add_field({"key": "tags", "name": {"en": "T"}, "kind": "text"}),
        "a field every tool's rows have",
    ),
    "another table's field": (
        _on_card({"type": "field", "props": {"field": "description"}}),
        "'description' is not a field of this table",
    ),
    "a task's field": (
        _set(
            lambda b: _tool(b)["layouts"],
            "lists",
            [{"kind": "table", "columns": ["title"]}],
        ),
        "'title' is not a field of this table",
    ),
    "a property": (
        _place({"type": "field", "props": {"field": "property:3"}}),
        "'property:3' is not a field of this table",
    ),
    "a board": (_set(_list, "kind", "board"), "kind must be one of"),
    "a grid of columns": (
        _set(_layouts, "lists", [{"kind": "grid", "columns": ["name"]}]),
        "a grid holds its card",
    ),
    "a table with no columns": (
        _set(_layouts, "lists", [{"kind": "table", "columns": []}]),
        "a table holds its columns",
    ),
    "no presets": (_set(_list, "presets", []), "leave 'presets' out"),
    "no lists": (_set(_layouts, "lists", []), "one way at least"),
    "two grids": (
        lambda body: _layouts(body)["lists"].append(dict(_list(body))),
        "a different kind",
    ),
    "four lists": (
        lambda body: _layouts(body)["lists"].extend([_list(body)] * 2),
        "more than 3",
    ),
    "a card tinted by a number": (
        lambda body: _list(body)["card"].__setitem__("props", {"tint": "min"}),
        "'min' is not a color field",
    ),
    "a card tinted by nothing": (
        lambda body: _list(body)["card"].__setitem__("props", {"tint": "ghost"}),
        "'ghost' is not a field of this table",
    ),
    "a preview of no item under it": (
        lambda body: _list(body)["card"]["children"].append(
            {
                "type": "items",
                "props": {"item": "counter", "fields": ["name"], "limit": 1},
            }
        ),
        "not an item table directly under it",
    ),
    "a preview of another table's field": (
        lambda body: _preview(body).__setitem__("fields", ["description"]),
        "'description' is not a field of 'counter'",
    ),
    "a preview showing a field twice": (
        lambda body: _preview(body).__setitem__("fields", ["name", "name"]),
        "each field once",
    ),
    "a preview of five fields": (
        lambda body: _preview(body).__setitem__(
            "fields", ["name", "count", "min", "max", "step"]
        ),
        "at most 4 items",
    ),
    "a preview of nine items": (
        lambda body: _preview(body).__setitem__("limit", 9),
        "less than or equal to 8",
    ),
    "a preview tinted by a number": (
        lambda body: _preview(body).__setitem__("tint", "min"),
        "'min' is not a color field",
    ),
    "a look from a number": (
        _set(_list, "displays", {"count": {"from": "min"}}),
        "'min' is not a select field",
    ),
    "a look from a select offering what is no look": (
        lambda body: _field(body, "view_mode")["options"].append(
            {"value": "dial", "label": {"en": "Dial"}}
        ),
        "offers an option",
    ),
    "a sort by a colour": (_sorts("color"), "'color' does not sort"),
    "a sort by who made it": (_sorts("created_by"), "'created_by' does not sort"),
    "a sort by another table's field": (
        _sorts("description"),
        "'description' is not a field of this table",
    ),
    "a sort by a field twice": (_sorts("count", "count"), "a field twice"),
    "five sorts": (
        _sorts("count", "min", "max", "step", "initial_count"),
        "sorts by 1 to 4",
    ),
    "a preset with no languages": (
        lambda body: _list(body)["presets"][0].__setitem__("name", "By name"),
        "label",
    ),
    "a preset slug in capitals": (
        lambda body: _list(body)["presets"][0].__setitem__("slug", "By-name"),
        "pattern",
    ),
    "a preset slug twice": (
        lambda body: _list(body)["presets"][1].__setitem__("slug", "by-name"),
        "own slug",
    ),
    "a plug-in's part on a card": (
        _on_card({"type": "plugin", "props": {"plugin": 1, "part": "badge"}}),
        "not a plug-in's parts",
    ),
    "a task's own part": (_place({"type": "status"}), "'status' is not a part"),
    "a plug-in's part on a page": (
        _place({"type": "plugin", "props": {"plugin": 1, "part": "badge"}}),
        "'plugin' is not a part",
    ),
    "an own part's props": (
        _place({"type": "byline", "props": {"required": True}}),
        "'byline' is not a part",
    ),
    "a look on a number": (
        _set(_list, "displays", {"min": "bar"}),
        "'min' is not a scale or counter field",
    ),
    "a look on every row's field": (
        _set(_list, "displays", {"name": "number"}),
        "'name' is not a scale or counter field",
    ),
    "a look a counter lacks": (
        _set(_list, "displays", {"count": "stars"}),
        "a counter field is not drawn as 'stars'",
    ),
    "a look the kit lacks": (
        _set(_list, "displays", {"count": "dial"}),
        "displays.count",
    ),
    "requiring every row's field": (_place(_required("name")), "leave empty"),
    "requiring a counter": (_place(_required("count")), "leave empty"),
    "a page with nothing placed": (_set(_layouts, "detail", {}), "places its parts"),
    "a fourth region": (_set(_detail, "footer", []), "Extra inputs"),
    "a stack gap the kit lacks": (
        _on_card({"type": "stack", "props": {"gap": "lg"}}),
        "gap",
    ),
    "a section title over 100": (
        _place({"type": "section", "props": {"title": "x" * 101}}),
        "at most 100 characters",
    ),
    "a part 7 deep": (_place(_deep(7)), "nests them deeper"),
    "301 parts": (
        _set(_detail, "side", [{"type": "byline"}] * 296),
        "more parts",
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
