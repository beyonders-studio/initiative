"""Tool plug-ins: the tool a manifest declares, and nothing else.

A ``tool`` plug-in declares one tool in its ``tool`` block and runs no code:
Initiative creates the tool's tables in each community that installs it and
serves the tool as it serves its own. So the definition is a description of
tables, and every key in it becomes a table or column name. It is held here to
the same rules the SDK's ``validateManifest`` holds it to, because the
publisher's own check is never taken on trust:

* **Keys** are a lower-case letter, then lower-case letters, digits and ``_``,
  at most ``toolKeyLength`` characters, checked one character at a time. A
  field's key is never a column every tool row has (``toolColumn``) and never
  ends in ``_id``, which the key to a parent row ends in.
* **Caps**: at most ``toolFields`` fields per table, ``toolItems`` item
  tables, two levels deep, and ``toolActions`` actions.
* **Fields** are of the contract's kinds, with options, a currency and a
  counter only where the kind has one, and a default of the kind's own shape.
* **``open_while``** is one condition on one of the item's fields, of a kind
  that condition reads.
* **Actions** run on the tool's rows or an item's, ask only for that table's
  fields, and write an expression that parses.
* **Layouts**: each table's list and item page, in the grammar the kit draws
  and ``tool_layouts`` stores (:mod:`app.schemas.tenant.tool_layout`),
  validated by its own models with the table's fields as the ids a layout
  names. A tool plug-in's lists are a grid or a table, its parts those every
  tool has, its looks those its field's kind has, and its size the kit's.

Beside the tool, a tool plug-in carries only the listing terms every plug-in
has (:func:`~app.services.marketplace.service_plugins.listing_terms`); a term
that serves or calls is refused rather than dropped.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ValidationError

from app.schemas.tenant.tool_layout import (
    TOOL_FIELDS,
    CardPart,
    DetailFieldPart,
    DetailLayoutDefinition,
    ListLayoutDefinition,
    OwnPart,
    PluginPart,
    parts_of,
    too_large,
)
from app.services.marketplace import contract
from app.services.marketplace.manifest_values import (
    check_identifier,
    check_json_size,
    fail,
    require_list,
    require_mapping,
)
from app.services.marketplace.service_plugins import (
    _CURRENCIES,
    MAX_SELECT_OPTIONS,
    MAX_SERVICE_DEFINITION_BYTES,
    _choice,
    _expression,
    _field_options,
    _label,
    listing_terms,
)
from app.services.marketplace.widget_meta import MAX_TEXT_LENGTH, localized_text

__all__ = [
    "TOOL_COLUMNS",
    "TOOL_FIELD_KINDS",
    "TOOL_ICONS",
    "TOOL_LAYOUT_FIELDS",
    "TOOL_LIST_LAYOUTS",
    "TOOL_PLUGIN_TERMS",
    "ToolChanges",
    "is_tool_plugin",
    "normalize_tool_plugin_definition",
    "tool_changes",
    "tool_kinds",
]

#: The plug-in kind, and the one feature, of a plug-in that declares a tool.
TOOL = "tool"

#: What a tool plug-in carries beside its tool. Every other term the contract
#: declares serves or calls something, and a tool plug-in runs no code.
TOOL_PLUGIN_TERMS: frozenset[str] = frozenset(
    {
        "plugin_kind",
        "tool",
        "features",
        "default_name",
        "min_plugin_api",
        "minimum_age",
        "availability",
        "help",
    }
)

TOOL_FIELD_KINDS: frozenset[str] = contract.enum("toolFieldKind")
TOOL_ICONS: frozenset[str] = contract.enum("toolIcon")
#: The columns every tool row has, which no declared field may be named.
TOOL_COLUMNS: frozenset[str] = contract.enum("toolColumn")
#: The fields every tool row has, which a layout names beside the table's own
#: and no declared field may be named.
TOOL_LAYOUT_FIELDS: frozenset[str] = contract.enum("toolLayoutField")
#: The page parts every tool has, which a tool plug-in's item page may place.
TOOL_PAGE_PARTS: frozenset[str] = contract.enum("toolDetailPart")
#: How a tool plug-in's table may be listed (``toolListKind``), and what each
#: holds beside its kind and ``displays``: a grid its card, a table its columns.
TOOL_LIST_LAYOUTS: dict[str, str] = {"grid": "card", "table": "columns"}
#: The looks a list draws a scale and a counter field in.
_LOOKS: dict[str, frozenset[str]] = {
    "scale": frozenset({"number", "stars", "bar"}),
    "counter": frozenset({"number", "bar", "clock"}),
}
#: The kinds of field that are never empty, so a layout never requires one.
_NEVER_EMPTY = frozenset({"counter", "checkbox"})

MAX_TOOL_KEY_LENGTH = contract.cap("toolKeyLength")
MAX_TOOL_FIELDS = contract.cap("toolFields")
MAX_TOOL_ITEMS = contract.cap("toolItems")
MAX_TOOL_ACTIONS = contract.cap("toolActions")
_KEY_CHARS = contract.charset("toolKey")
_KEY_START = frozenset("abcdefghijklmnopqrstuvwxyz")

#: The comparisons an open condition makes between a number or counter field
#: and an operand, and the kinds they read.
_COMPARISONS = ("below", "at_most", "above", "at_least", "equals", "not_equals")
_NUMBER_KINDS = frozenset({"number", "counter"})
_CONDITIONS = frozenset({*_COMPARISONS, "is", "in", "not_passed"})
_COUNTER_BOUNDS = ("min", "max", "step", "initial")


def is_tool_plugin(definition: Any) -> bool:
    """Whether a stored definition is a tool plug-in's."""
    return isinstance(definition, dict) and definition.get("plugin_kind") == TOOL


def tool_kinds(definition: dict[str, Any], *, listing_uid: str) -> list[str]:
    """The kinds a tool plug-in's definition declares: its tool's and each
    item's, as ``<key>.<uid in lower case>``. A built-in kind never holds a
    ``.``, so the two never meet, and two plug-ins declaring the same key
    differ by their uids."""
    tool = definition["tool"]
    suffix = listing_uid.lower()
    keys = [tool["key"], *(item["key"] for item in tool.get("items", []))]
    return [f"{key}.{suffix}" for key in keys]


# --- one version against another ----------------------------------------------


@dataclass(frozen=True)
class ToolChanges:
    """What one version of a tool plug-in changes in its tool against another,
    each named ``<table key>`` or ``<table key>.<field key>``.

    A field a version stops declaring, or declares as another kind, or whose
    options it narrows, is ``dropped``: its column goes, and a field declared
    again under the same key comes back empty. An item table it stops
    declaring, or puts under another table, is ``removed``."""

    added_tables: tuple[str, ...] = ()
    added_fields: tuple[str, ...] = ()
    added_options: tuple[str, ...] = ()
    added_actions: tuple[str, ...] = ()
    dropped_fields: tuple[str, ...] = ()
    removed_tables: tuple[str, ...] = ()

    @property
    def adds(self) -> bool:
        """Whether the version gives the tool anything new."""
        return bool(
            self.added_tables
            or self.added_fields
            or self.added_options
            or self.added_actions
        )


def _tables(definition: dict[str, Any]) -> dict[str, tuple[str | None, dict]]:
    """Each table of a definition's tool by key: its parent's key (None for
    the tool's own) and its fields by key."""
    tool = definition["tool"]
    tables = {tool["key"]: (None, {f["key"]: f for f in tool.get("fields", [])})}
    for item in tool.get("items", []):
        tables[item["key"]] = (
            item.get("parent", tool["key"]),
            {f["key"]: f for f in item["fields"]},
        )
    return tables


def _options(field: dict[str, Any]) -> set[str]:
    return {option["value"] for option in field.get("options", [])}


def tool_changes(before: dict[str, Any], after: dict[str, Any]) -> ToolChanges:
    """What moving from the definition ``before`` to ``after`` changes in the
    tool's tables and actions."""
    old, new = _tables(before), _tables(after)
    added_tables = [key for key in new if key not in old]
    removed = [
        key for key, (parent, _) in old.items() if new.get(key, (0,))[0] != parent
    ]
    added_fields: list[str] = []
    added_options: list[str] = []
    dropped: list[str] = []
    for key, (_, fields) in new.items():
        if key not in old or key in removed:
            continue
        held = old[key][1]
        for field_key, field in fields.items():
            was = held.get(field_key)
            if was is None:
                added_fields.append(f"{key}.{field_key}")
            elif was["kind"] != field["kind"] or _options(was) - _options(field):
                dropped.append(f"{key}.{field_key}")
            else:
                added_options += [
                    f"{key}.{field_key}.{value}"
                    for value in sorted(_options(field) - _options(was))
                ]
        dropped += [
            f"{key}.{field_key}" for field_key in held if field_key not in fields
        ]
    actions = {action["id"] for action in before["tool"].get("actions", [])}
    return ToolChanges(
        added_tables=tuple(added_tables),
        added_fields=tuple(added_fields),
        added_options=tuple(added_options),
        added_actions=tuple(
            action["id"]
            for action in after["tool"].get("actions", [])
            if action["id"] not in actions
        ),
        dropped_fields=tuple(sorted(dropped)),
        removed_tables=tuple(removed),
    )


# --- pieces -----------------------------------------------------------------


def _key(raw: Any, *, what: str) -> str:
    """A key a tool declares, checked one character at a time."""
    if not isinstance(raw, str) or not raw:
        fail(f"{what} is required")
    if len(raw) > MAX_TOOL_KEY_LENGTH:
        fail(f"{what} is longer than {MAX_TOOL_KEY_LENGTH} characters")
    if raw[0] not in _KEY_START:
        fail(f"{what} starts with a lower-case letter")
    for character in raw:
        if character not in _KEY_CHARS:
            fail(f"{what} holds lower-case letters, digits and '_', not {character!r}")
    return raw


def _number(raw: Any) -> bool:
    """Whether ``raw`` is a finite number a float holds: an integer too large
    for one is not."""
    if not isinstance(raw, int | float) or isinstance(raw, bool):
        return False
    try:
        return math.isfinite(raw)
    except OverflowError:
        return False


def _is_date(raw: Any) -> bool:
    if not isinstance(raw, str) or len(raw) != 10 or raw[4] != "-" or raw[7] != "-":
        return False
    if not all(raw[at].isdigit() for at in (0, 1, 2, 3, 5, 6, 8, 9)):
        return False
    try:
        date.fromisoformat(raw)
    except ValueError:
        return False
    return True


def _is_datetime(raw: Any) -> bool:
    if not isinstance(raw, str) or len(raw) < 11 or raw[10] != "T":
        return False
    if not _is_date(raw[:10]):
        return False
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _is_color(raw: Any) -> bool:
    return (
        isinstance(raw, str)
        and len(raw) == 7
        and raw[0] == "#"
        and all(character in "0123456789abcdefABCDEF" for character in raw[1:])
    )


def _is_address(raw: Any) -> bool:
    if not isinstance(raw, str) or len(raw) > MAX_TEXT_LENGTH:
        return False
    try:
        parts = urlsplit(raw)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def _default(field: dict[str, Any], raw: Any, *, what: str) -> Any:
    """A field's default, of its kind's own shape."""
    kind = field["kind"]
    options = {option["value"] for option in field.get("options", [])}
    if kind == "counter":
        fail(f"{what}: a counter field starts at its counter's 'initial'")
    if kind == "user_reference":
        fail(f"{what}: a person is never a default")
    fits = {
        "text": isinstance(raw, str) and len(raw) <= MAX_TEXT_LENGTH,
        "url": _is_address(raw),
        "date": _is_date(raw),
        "datetime": _is_datetime(raw),
        "color": _is_color(raw),
        "number": _number(raw),
        "currency": _number(raw),
        "scale": _number(raw) and 0 <= raw <= 100,
        "checkbox": isinstance(raw, bool),
        "select": isinstance(raw, str) and raw in options,
        "multi_select": isinstance(raw, list)
        and all(isinstance(value, str) and value in options for value in raw)
        and len(set(raw)) == len(raw),
    }[kind]
    if not fits:
        fail(f"{what}: the default is not a value of a {kind} field")
    return raw


def _field(raw: Any, *, what: str) -> dict[str, Any]:
    """One field of a table, on its own: its key, name and kind, and the
    options, currency and default that kind takes. A counter's bounds name
    other fields, so they are read with the whole table (:func:`_counter`)."""
    field = require_mapping(raw, what)
    key = _key(field.get("key"), what=f"{what} key")
    what = f"{what} {key!r}"
    if key in TOOL_COLUMNS:
        fail(f"{what}: {key!r} is a column every tool's rows have")
    if key in TOOL_LAYOUT_FIELDS:
        fail(f"{what}: {key!r} is a field every tool's rows have")
    if key.endswith("_id"):
        fail(f"{what}: a field's key does not end in '_id', as a key to a parent does")
    kind = _choice(field.get("kind"), TOOL_FIELD_KINDS, what=f"{what} kind")
    cleaned: dict[str, Any] = {
        "key": key,
        "name": _label(field.get("name"), what=what),
        "kind": kind,
    }
    if kind == "currency":
        cleaned["currency"] = _choice(
            field.get("currency"), _CURRENCIES, what=f"{what} currency"
        )
    elif field.get("currency") is not None:
        fail(f"{what}: only a currency field names a currency")
    if kind in ("select", "multi_select"):
        cleaned["options"] = _field_options(field.get("options"), what=what)
    elif field.get("options") is not None:
        fail(f"{what}: only a select or multi_select field has options")
    if field.get("counter") is not None and kind != "counter":
        fail(f"{what}: only a counter field has a counter")
    if field.get("default") is not None:
        cleaned["default"] = _default(cleaned, field["default"], what=what)
    return cleaned


def _counter(raw: Any, *, numbers: set[str], what: str) -> dict[str, Any]:
    """A counter's bounds: each a number, or the key of a number field of the
    same table, ``numbers``."""
    counter = require_mapping(raw, f"{what} counter")
    cleaned: dict[str, Any] = {}
    for name in _COUNTER_BOUNDS:
        bound = counter.get(name)
        if bound is None:
            continue
        if isinstance(bound, str):
            if bound not in numbers:
                fail(
                    f"{what} counter {name}: {bound!r} is not a number field of its table"
                )
        elif not _number(bound):
            fail(f"{what} counter {name}: a bound is a number or a number field's key")
        cleaned[name] = bound
    step = cleaned.get("step")
    if _number(step) and step <= 0:
        fail(f"{what} counter step: a step is above 0")
    low, high = cleaned.get("min"), cleaned.get("max")
    if _number(low) and _number(high) and low > high:
        fail(f"{what} counter: its min is above its max")
    return cleaned


def _fields(raw: Any, *, what: str, required: bool) -> list[dict[str, Any]]:
    """A table's fields, each key once, with each counter's bounds read
    against the table's number fields."""
    declared = require_list(raw, f"{what} fields", MAX_TOOL_FIELDS)
    if required and not declared:
        fail(f"{what} declares at least one field")
    fields = [_field(entry, what=f"{what} field") for entry in declared]
    keys: set[str] = set()
    for field in fields:
        if field["key"] in keys:
            fail(f"{what}: two fields share the key {field['key']!r}")
        keys.add(field["key"])
    numbers = {field["key"] for field in fields if field["kind"] == "number"}
    for entry, field in zip(declared, fields, strict=True):
        if field["kind"] == "counter" and entry.get("counter") is not None:
            field["counter"] = _counter(
                entry["counter"], numbers=numbers, what=f"{what} field {field['key']!r}"
            )
    return fields


def _operand(raw: Any, *, numbers: set[str], what: str) -> Any:
    """What a number or counter field is compared with: a number, or
    ``{"field": key}``, another such field of the same item."""
    if _number(raw):
        return raw
    operand = require_mapping(raw, what)
    if set(operand) != {"field"}:
        fail(f"{what} is a number or {{'field': key}}")
    if not isinstance(operand["field"], str) or operand["field"] not in numbers:
        fail(
            f"{what}: {operand['field']!r} is not a number or counter field of this item"
        )
    return {"field": operand["field"]}


def _open_while(raw: Any, *, fields: list[dict[str, Any]], what: str) -> dict[str, Any]:
    """One condition on one of the item's fields, of a kind it reads."""
    condition = require_mapping(raw, what)
    by_key = {field["key"]: field for field in fields}
    terms = [term for term in condition if term != "field"]
    for term in terms:
        if term not in _CONDITIONS:
            fail(f"{what}: {term!r} is not a condition")
    if len(terms) != 1:
        fail(f"{what} is one condition on its field")
    (term,) = terms
    key = condition.get("field")
    field = by_key.get(key) if isinstance(key, str) else None
    if field is None:
        fail(f"{what}: {key!r} is not a field of this item")
    kind = field["kind"]
    value = condition[term]

    def reads(kinds: frozenset[str], kind_names: str) -> None:
        if kind not in kinds:
            fail(f"{what}: {term!r} reads {kind_names}, and {key!r} is a {kind} field")

    if term in _COMPARISONS:
        reads(_NUMBER_KINDS, "a number or counter field")
        numbers = {k for k, f in by_key.items() if f["kind"] in _NUMBER_KINDS}
        value = _operand(value, numbers=numbers, what=f"{what} {term}")
    elif term == "is":
        reads(frozenset({"checkbox"}), "a checkbox field")
        if not isinstance(value, bool):
            fail(f"{what} is: true or false")
    elif term == "in":
        reads(frozenset({"select"}), "a select field")
        values = require_list(value, f"{what} in", MAX_SELECT_OPTIONS)
        options = {option["value"] for option in field["options"]}
        if not values:
            fail(f"{what} in names at least one option")
        for entry in values:
            if not isinstance(entry, str) or entry not in options:
                fail(f"{what} in: {entry!r} is not an option of {key!r}")
        if len(set(values)) != len(values):
            fail(f"{what} in names an option twice")
        value = list(values)
    else:
        reads(frozenset({"date", "datetime"}), "a date or datetime field")
        if value is not True:
            fail(f"{what} not_passed: true")
    return {"field": key, term: value}


def _validated[M: BaseModel](
    model: type[M], raw: Any, *, fields: frozenset[str], what: str
) -> tuple[M, dict[str, Any]]:
    """A layout read by the kit's own model, naming ``fields``, and the
    definition as ``tool_layouts`` stores it: what it sets, and nothing unset."""
    try:
        definition = model.model_validate(raw, context={TOOL_FIELDS: fields})
    except ValidationError as error:
        first = error.errors()[0]
        where = ".".join(str(step) for step in first["loc"])
        fail(f"{what} {where}: {first['msg']}")
    stored = {
        key: value
        for key, value in definition.model_dump(mode="json", exclude_unset=True).items()
        if value is not None
    }
    return definition, stored


def _list_layout(
    raw: Any, *, declared: dict[str, dict[str, Any]], names: frozenset[str], what: str
) -> dict[str, Any]:
    """How a table's rows are listed: a grid of its card or a table of its
    columns, with a look for each scale or counter field that has one."""
    layout = require_mapping(raw, what)
    kind = _choice(
        layout.get("kind"), frozenset(TOOL_LIST_LAYOUTS), what=f"{what} kind"
    )
    holds = TOOL_LIST_LAYOUTS[kind]
    if set(layout) - {"kind", holds, "displays"} or not layout.get(holds):
        fail(f"{what}: a {kind} holds its {holds}, and displays")
    definition, stored = _validated(
        ListLayoutDefinition,
        {key: value for key, value in layout.items() if key != "kind"},
        fields=names,
        what=what,
    )
    roots: list[CardPart] = [definition.card] if definition.card is not None else []
    if any(
        isinstance(part, PluginPart) for root in roots for part, _ in parts_of(root)
    ):
        fail(f"{what}: a card draws the tool's fields, not a plug-in's parts")
    for key, look in (definition.displays or {}).items():
        field_kind = declared[key]["kind"] if key in declared else ""
        looks = _LOOKS.get(field_kind)
        if looks is None:
            fail(
                f"{what} displays: {key!r} is not a scale or counter field it declares"
            )
        if look not in looks:
            fail(f"{what} displays: a {field_kind} field is not drawn as {look!r}")
    if too_large(stored, roots, len(definition.columns or ())):
        fail(f"{what} holds more parts, or nests them deeper, than a layout may")
    return {"kind": kind, **stored}


def _detail_layout(
    raw: Any, *, declared: dict[str, dict[str, Any]], names: frozenset[str], what: str
) -> dict[str, Any]:
    """How one of a table's rows is shown: its parts in three regions, each
    placing fields, the initiative's properties and the parts every tool's
    page has."""
    definition, stored = _validated(
        DetailLayoutDefinition, require_mapping(raw, what), fields=names, what=what
    )
    if not stored:
        fail(f"{what} places its parts in a header, main or side")
    roots = [
        part
        for region in (definition.header, definition.main, definition.side)
        for part in region or ()
    ]
    for part, _ in (found for root in roots for found in parts_of(root)):
        if isinstance(part, PluginPart) or (
            isinstance(part, OwnPart)
            and (part.type not in TOOL_PAGE_PARTS or part.props is not None)
        ):
            fail(f"{what}: {part.type!r} is not a part every tool's page has")
        if isinstance(part, DetailFieldPart) and part.props.required:
            field = declared.get(str(part.props.field))
            if field is None or field["kind"] in _NEVER_EMPTY:
                fail(
                    f"{what}: {part.props.field!r} is not a field it declares that a person can leave empty"
                )
    if too_large(stored, roots, 0):
        fail(f"{what} holds more parts, or nests them deeper, than a layout may")
    return stored


def _layouts(raw: Any, *, fields: list[dict[str, Any]], what: str) -> dict[str, Any]:
    """What a table draws: its list and its item page, each naming the
    table's fields and the fields every tool row has."""
    layouts = require_mapping(raw, f"{what} layouts")
    if set(layouts) != {"list", "detail"}:
        fail(f"{what} layouts: a list and a detail")
    declared = {field["key"]: field for field in fields}
    names = frozenset(declared) | TOOL_LAYOUT_FIELDS
    return {
        "list": _list_layout(
            layouts["list"], declared=declared, names=names, what=f"{what} list layout"
        ),
        "detail": _detail_layout(
            layouts["detail"],
            declared=declared,
            names=names,
            what=f"{what} detail layout",
        ),
    }


def _items(raw: Any, *, tool_key: str) -> list[dict[str, Any]]:
    """The item tables: each key once and never the tool's, each under the
    tool or under an item that is under the tool."""
    if raw is None:
        return []
    declared = require_list(raw, "tool items", MAX_TOOL_ITEMS)
    if not declared:
        fail("tool items: leave 'items' out for a tool with none")
    items: list[dict[str, Any]] = []
    keys = {tool_key}
    for entry in declared:
        item = require_mapping(entry, "tool item")
        key = _key(item.get("key"), what="tool item key")
        what = f"tool item {key!r}"
        if key in keys:
            fail(f"{what}: the key is the tool's or another item's")
        keys.add(key)
        fields = _fields(item.get("fields"), what=what, required=True)
        cleaned: dict[str, Any] = {
            "key": key,
            "name": _label(item.get("name"), what=what),
            "fields": fields,
            "layouts": _layouts(item.get("layouts"), fields=fields, what=what),
        }
        if item.get("parent") is not None:
            cleaned["parent"] = _key(item["parent"], what=f"{what} parent")
        if item.get("open_while") is not None:
            cleaned["open_while"] = _open_while(
                item["open_while"], fields=fields, what=f"{what} open_while"
            )
        items.append(cleaned)
    parents = {item["key"]: item.get("parent") for item in items}
    for item in items:
        parent = item.get("parent")
        what = f"tool item {item['key']!r} parent"
        if parent is None:
            continue
        if parent == item["key"]:
            fail(f"{what}: an item does not sit under itself")
        if parent not in parents:
            fail(f"{what}: {parent!r} is not one of the tool's items")
        if parents[parent] is not None:
            fail(
                f"{what}: {parent!r} sits under another item; items go two levels deep at most"
            )
    return items


def _actions(raw: Any, *, tables: dict[str, set[str]]) -> list[dict[str, Any]]:
    """What a reader runs on a row: each id once, on the tool's rows or an
    item's, asking only for that table's fields, and writing an expression
    that parses."""
    if raw is None:
        return []
    declared = require_list(raw, "tool actions", MAX_TOOL_ACTIONS)
    if not declared:
        fail("tool actions: leave 'actions' out for a tool with none")
    actions: list[dict[str, Any]] = []
    ids: set[str] = set()
    for entry in declared:
        action = require_mapping(entry, "tool action")
        action_id = check_identifier(action.get("id"), what="tool action id")
        what = f"tool action {action_id!r}"
        if action_id in ids:
            fail(f"tool actions: two actions share the id {action_id!r}")
        ids.add(action_id)
        on = action.get("on")
        if not isinstance(on, str) or on not in tables:
            fail(f"{what}: on names neither the tool's key nor one of its items' keys")
        _expression(action.get("write"), what=f"{what} write")
        cleaned: dict[str, Any] = {
            "id": action_id,
            "name": _label(action.get("name"), what=what),
            "on": on,
            "write": action["write"],
        }
        if action.get("params") is not None:
            params = require_list(action["params"], f"{what} params", MAX_TOOL_FIELDS)
            if not params:
                fail(f"{what}: leave 'params' out for an action that asks for none")
            for param in params:
                if not isinstance(param, str) or param not in tables[on]:
                    fail(f"{what} params: {param!r} is not a field of {on!r}")
            if len(set(params)) != len(params):
                fail(f"{what} params name a field twice")
            cleaned["params"] = list(params)
        confirm = localized_text(action.get("confirm"), MAX_TEXT_LENGTH)
        if confirm is not None:
            cleaned["confirm"] = confirm
        actions.append(cleaned)
    return actions


def _tool(raw: Any) -> dict[str, Any]:
    tool = require_mapping(raw, "tool")
    key = _key(tool.get("key"), what="tool key")
    fields = _fields(tool.get("fields"), what="tool", required=False)
    items = _items(tool.get("items"), tool_key=key)
    tables = {
        key: {field["key"] for field in fields},
        **{item["key"]: {field["key"] for field in item["fields"]} for item in items},
    }
    cleaned: dict[str, Any] = {
        "key": key,
        "name": _label(tool.get("name"), what="tool name"),
        "instance_name": _label(tool.get("instance_name"), what="tool instance_name"),
        "icon": _choice(tool.get("icon"), TOOL_ICONS, what="tool icon"),
    }
    # Empty means absent, as for every block.
    if fields:
        cleaned["fields"] = fields
    cleaned["layouts"] = _layouts(tool.get("layouts"), fields=fields, what="tool")
    if items:
        cleaned["items"] = items
    actions = _actions(tool.get("actions"), tables=tables)
    if actions:
        cleaned["actions"] = actions
    return cleaned


def normalize_tool_plugin_definition(definition: Any) -> dict[str, Any]:
    """Validate and canonicalize a tool plug-in's definition."""
    body = require_mapping(definition, "tool plug-in definition")
    for term in contract.fields("manifest"):
        if term not in TOOL_PLUGIN_TERMS and body.get(term) is not None:
            fail(
                f"tool plug-in: a tool plug-in runs no code, so it carries no {term!r}"
            )
    if body.get("features") != [TOOL]:
        fail("tool plug-in: its features are exactly ['tool']")
    if body.get("tool") is None:
        fail("tool plug-in: it declares its tool")
    cleaned: dict[str, Any] = {
        "plugin_kind": TOOL,
        "features": [TOOL],
        "tool": _tool(body["tool"]),
        **listing_terms(body),
    }
    check_json_size(
        cleaned, what="tool plug-in definition", limit=MAX_SERVICE_DEFINITION_BYTES
    )
    return cleaned
