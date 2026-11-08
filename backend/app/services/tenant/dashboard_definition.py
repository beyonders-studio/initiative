"""Validation and normalization for dashboard definitions.

A definition is a **presentation spec**: a grid layout plus widgets, each bound
to a data source by name. Most dashboards — hand-built or installed from the
marketplace — are simply a *composition* of the built-in widgets below: a
"sprint health" listing is several first-party widgets, arranged and pre-bound. The
marketplace download carries that definition; what this module owns is narrower,
and is the reason a downloaded definition is safe to store — a **capability
check**:

* a widget must name a ``type`` we have a renderer for, and
* a binding must name a ``source`` we have a fetcher for, and one that widget
  can draw.

That closed vocabulary is what stops a definition from naming its own endpoint
or carrying code: there is nowhere to put a URL and nothing generic that would
dereference one. It is also why dashboards are display-only — no source maps to
a mutating route, so no definition can cause a write.

What this module deliberately does **not** do is re-declare the shape of each
binding's parameters. Those belong to the fetcher that consumes them (a
``counter`` binding's ``counter_id``, a ``tasks`` binding's filter-DSL
``conditions``), and mirroring them here would mean maintaining every parameter
in two places. They are stored as given, bounded by the definition size cap, and
checked where they are used: the filter DSL parser enforces its own limits, and
every id is authorized against the viewer by RLS at fetch time.

Normalization mirrors ``files_spreadsheet``: unrecognized *structure* is
dropped rather than preserved, so a stored definition always has canonical shape.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal, Mapping

from app.core.errors import CodedError
from app.core.messages import DashboardMessages
from app.models.platform.marketplace import UID_ALPHABET, UID_LENGTH
from app.services.marketplace.manifest_values import (
    IDENTIFIER_CHARS,
    MAX_IDENTIFIER_LENGTH,
)
from app.services.fields.spec import FieldType
from app.services.marketplace.service_plugins import (
    PLUGIN_WIDGET_TYPE_PREFIX,
    ENDPOINT_ID_CHARS,
    MAX_ENDPOINT_ID_LENGTH,
)
from app.services.query.resolve import QueryError, resolve

SCHEMA_VERSION = 1

# Hard caps. A definition is small by nature; these bound both storage and the
# per-viewer fan-out a single dashboard can trigger.
MAX_DEFINITION_BYTES = 256 * 1024
MAX_WIDGETS = 50
MAX_GRID_COLUMNS = 12
MAX_GRID_ROWS = 500
MAX_TITLE_LENGTH = 200
#: A statement's own ceiling, matching what the query endpoint accepts. Stated
#: here too because a definition is checked before anything is run.
MAX_SQL_LENGTH = 20_000


class DashboardDefinitionError(CodedError, ValueError):
    """Raised when a definition cannot be normalized, with a stable machine
    code from ``app.core.messages``; answered as a 422."""

    status_code = 422


def _fail(code: str) -> None:
    raise DashboardDefinitionError(code)


# --- primitives ------------------------------------------------------------
#
# The widget kinds this app has renderers for. Each declares the size floor the
# canvas honors (so a layout can never squeeze it below legibility) and the
# sources it knows how to draw. The frontend renderer map mirrors this registry
# and a drift test keeps the two equal.
#
# Primitives are the *only* thing that maps to code. Everything a user or the
# marketplace can name resolves to one of these (see PRESETS below).


#: What an option takes: one of its listed values, a number, or a day.
OptionKind = Literal["choice", "number", "date"]


@dataclass(frozen=True)
class WidgetOptionSpec:
    """One display option: the values it may take, in the order the palette
    offers them, and the one a widget falls back to when a definition names
    none.

    Order is declared rather than sorted so a scale reads day → quarter instead
    of alphabetically, and the default is stated rather than implied by that
    order, so the two can differ (weeks are the useful default; days are the
    natural first entry). Serving both is what keeps the editor's pre-selected
    value equal to what the widget will actually draw.
    """

    values: tuple[str, ...]
    default: str
    #: ``choice`` takes one of ``values``. ``number`` and ``date`` take a value
    #: of that kind instead, such as a target and the day it is due, and have
    #: no values to offer and no default: unset, the widget draws without one.
    kind: OptionKind = "choice"

    def __contains__(self, value: object) -> bool:
        return value in self.values


def _option(*values: str, default: str | None = None) -> WidgetOptionSpec:
    return WidgetOptionSpec(values=values, default=default if default else values[0])


def _free(kind: OptionKind) -> WidgetOptionSpec:
    return WidgetOptionSpec(values=(), default="", kind=kind)


#: A goal for the widget's number, and the day it should be reached by. The
#: widget marks it and says whether the number is on its way there.
_TARGET_OPTIONS = {"target": _free("number"), "target_date": _free("date")}


#: What may fill a slot, by what the slot is for. Named sets rather than a set
#: written at each slot: "a thing with a name" is the same answer for a bar's
#: category, a card's title and a Gantt row's label, and stating it once is what
#: keeps them agreeing.
LABEL_TYPES = frozenset({FieldType.text, FieldType.enum, FieldType.reference})
NUMBER_TYPES = frozenset({FieldType.number})
DATE_TYPES = frozenset({FieldType.date})
BOOLEAN_TYPES = frozenset({FieldType.boolean})


@dataclass(frozen=True)
class Slot:
    """One column a widget needs, and what may fill it.

    A widget declares the *shape* it can draw rather than the sources it knows,
    so any query returning that shape drives it. The slot's name is what the
    author sees in the picker beside it and what a stored mapping keys on.
    """

    name: str
    types: frozenset[FieldType]
    #: A widget that draws without it — a chart needs a category and a value,
    #: and colours by a third column only if there is one.
    required: bool = True
    #: Several columns may fill it: a chart's measures are one series each.
    repeatable: bool = False


@dataclass(frozen=True)
class WidgetSpec:
    min_w: int
    min_h: int
    default_w: int
    default_h: int
    #: The columns this widget draws, in the order it reads them. Empty means it
    #: draws whatever it is given, which only a table can honestly claim.
    shape: tuple[Slot, ...] = ()
    # Widget-level options this primitive accepts, each with its allowed values.
    # A preset's params and a definition's own options are checked against this.
    options: Mapping[str, WidgetOptionSpec] = field(default_factory=dict)


WIDGET_SPECS: dict[str, WidgetSpec] = {
    # A timeline needs width to be readable at all.
    "gantt": WidgetSpec(
        min_w=6,
        min_h=3,
        default_w=12,
        default_h=6,
        shape=(
            Slot("label", LABEL_TYPES),
            Slot("start", DATE_TYPES),
            Slot("end", DATE_TYPES),
            Slot("group", LABEL_TYPES, required=False),
            # Whether the work is finished. Without it, nothing says how much is.
            Slot("done", BOOLEAN_TYPES, required=False),
        ),
        options={
            "scale": _option("day", "week", "month", "quarter", "year", default="week"),
            # Whether rows fold into summaries at all. What they fold *by*
            # is the column the author mapped to the group slot, not an option
            # this build could name in advance.
            "group": _option("on", "none"),
            # The total row above everything shown.
            "rollup": _option("on", "off"),
            # Whether groups arrive open or folded. A starting state only; which
            # rows are open afterwards belongs to whoever is reading.
            "start": _option("open", "folded"),
        },
    ),
    # One big number.
    "stat": WidgetSpec(
        min_w=2,
        min_h=2,
        default_w=3,
        default_h=2,
        shape=(
            Slot("value", NUMBER_TYPES),
            Slot("label", LABEL_TYPES, required=False),
        ),
        options={
            "format": _option("plain", "percent", "currency", "duration"),
            # Which count the number reports when its source is several
            # buckets rather than one value.
            "pick": _option("total", "largest", "first"),
            # A trend line under the number, and what its direction means. A
            # falling cycle time is good; falling revenue is not, so the widget
            # is told rather than guessing.
            "trend": _option("off", "on"),
            "direction": _option("up_good", "down_good"),
            **_TARGET_OPTIONS,
        },
    ),
    # A series drawn as bars/lines/area/slices.
    "chart": WidgetSpec(
        min_w=3,
        min_h=3,
        default_w=6,
        default_h=4,
        shape=(
            Slot("label", LABEL_TYPES | DATE_TYPES),
            Slot("value", NUMBER_TYPES, repeatable=True),
            # A second grouping: one series per value it holds, so points per
            # sprint can be split by status.
            Slot("series", LABEL_TYPES, required=False),
        ),
        options={
            "mark": _option("bar", "line", "area", "pie"),
            "stacked": _option("false", "true"),
            "sort": _option("source", "value_desc", "value_asc", "label"),
            # A ceiling on categories, with the tail folded into one "Other"
            # entry. The alternative — more colors — is the thing a categorical
            # palette cannot do past its slot count.
            "limit": _option("all", "5", "8", "12"),
            # Horizontal bars give long category names room to be read.
            "orientation": _option("columns", "bars"),
            # Direct labels, always selective: the extremes or the end of a
            # line, never a number on every point.
            "values": _option("none", "extremes", "end"),
            # One series in color and the rest in gray — the honest form when
            # the story is a single series and the others are context.
            "emphasis": _option("none", "largest", "last"),
            **_TARGET_OPTIONS,
        },
    ),
    # Staged counts, widest bucket first.
    "funnel": WidgetSpec(
        min_w=3,
        min_h=3,
        default_w=6,
        default_h=5,
        shape=(
            Slot("label", LABEL_TYPES),
            Slot("value", NUMBER_TYPES),
        ),
        options={
            # Stages are usually a workflow, so the order the source gave them
            # is meaningful; sorting is for when it is not.
            "order": _option("source", "descending"),
        },
    ),
    # A completion bar — a counter against its own min/max, or a done ratio.
    "progress": WidgetSpec(
        min_w=2,
        min_h=1,
        default_w=4,
        default_h=2,
        shape=(
            Slot("value", NUMBER_TYPES),
            Slot("total", NUMBER_TYPES, required=False),
            Slot("label", LABEL_TYPES, required=False),
        ),
        options={
            # One bar for the whole binding, or one per project/bucket.
            "breakdown": _option("total", "each"),
            "format": _option("percent", "plain"),
            **_TARGET_OPTIONS,
        },
    ),
    # Density over a calendar grid. Task counts bucketed by day is what it draws
    # at launch; nothing about the widget is specific to that source.
    "heatmap": WidgetSpec(
        min_w=4,
        min_h=2,
        default_w=8,
        default_h=3,
        shape=(
            Slot("at", DATE_TYPES),
            Slot("value", NUMBER_TYPES),
        ),
        options={"tone": _option("accent", "positive", "warning")},
    ),
    # Tasks in columns. Display only, like every widget: a card cannot be
    # dragged from one column to the next, because a dashboard reads and never
    # writes — moving work is a project view's job.
    "board": WidgetSpec(
        min_w=4,
        min_h=4,
        default_w=12,
        default_h=6,
        shape=(
            Slot("card", LABEL_TYPES),
            Slot("column", LABEL_TYPES),
            Slot("date", DATE_TYPES, required=False),
        ),
        options={
            # The order cards sit in within a column. Not the author's manual
            # order: that is a position inside one project's board, and a
            # statement spanning several has no single one to honour.
            "sort": _option("label", "date"),
            # How much of a task a card carries.
            "cards": _option("standard", "compact", "detailed"),
            # Mark cards that need attention, in the negative tone.
            "highlight": _option("overdue", "off"),
            # Which column comes first.
            "columns": _option("natural", "largest", "label"),
        },
    ),
    # A plain read-only table. Display only, like every widget: no row actions,
    # no inline editing — that is a project view's job, not a dashboard's.
    "table": WidgetSpec(
        min_w=4,
        min_h=3,
        default_w=12,
        default_h=5,
        shape=(),
        options={
            # How many of a row's fields to show. The envelope carries tags,
            # assignees, checklist progress and comment counts; "standard" is
            # the four columns that fit a half-width tile.
            "columns": _option("standard", "detailed"),
            "totals": _option("off", "on"),
        },
    ),
}

#: What a binding may name. Two, and only the first is ours to write: a
#: **query** is a statement over this guild's datasets, its spreadsheets'
#: ranges and its plug-ins' read endpoints, and **plugin** is an installed
#: listing's own widget's endpoint.
QUERY_SOURCE = "query"
TABULAR_SOURCES: frozenset[str] = frozenset({QUERY_SOURCE})


# --- plug-in widgets ------------------------------------------------------------
#
# A service plug-in contributes its own widgets and its own data sources (§7, §9.1).
# They are deliberately a *separate* vocabulary from the built-ins above rather
# than an addition to it:
#
# * a plug-in widget's type is namespaced ``plugin:<listing_uid>:<widget_id>``, so it
#   can never resolve to a built-in renderer, and a built-in can never resolve
#   to a plug-in's module;
# * ``plugin`` is the only source a plug-in widget binds, and no built-in binds it —
#   a plug-in's rows are opaque here, so nothing in this build could draw them.
#
# The binding names a listing and a source; it never names an address, and there
# is still nowhere in a definition to put one. What that source *is* — its
# parameters, its credentials, its freshness — lives in the installed plug-in's
# pinned definition and is enforced when the data is fetched, under the caller's
# own session.
#
# The check here is deliberately shape, not an install lookup: a well-formed
# ``plugin:<uid>:<widget>`` stores whether or not that plug-in is installed, so a
# stored dashboard outlives the plug-in it drew from. What a guild built is the
# guild's; the client renders the not-installed state and asks for the plug-in to
# be reconnected. Only a malformed type is a rejection.

#: The one binding source a plug-in widget may name.
PLUGIN_BINDING_SOURCE = "plugin"

#: Size floors for a plug-in widget. Uniform, because this build cannot know what
#: a vendor's module draws; the floor is simply "big enough to read". It
#: declares no shape: a plug-in's rows are its own, described in its manifest, and
#: the module that draws them ships alongside — there is nothing here to map.
PLUGIN_WIDGET_SPEC = WidgetSpec(min_w=2, min_h=2, default_w=6, default_h=4)

#: What one plug-in binding may carry, mirroring the manifest's per-source cap.
MAX_PLUGIN_BINDING_PARAMS = 12
#: A parameter value is a scalar the endpoint declared a type for, or several
#: of them where it declared ``list``. Checked again against that type at fetch
#: time; bounded here so a definition stays small.
MAX_PLUGIN_PARAM_LENGTH = 2_000
#: How many values one parameter may carry. A parameter declaring ``list`` is
#: still one answer on a form, so this bounds a definition rather than a query.
MAX_PLUGIN_PARAM_VALUES = 64


def _check_identifier(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_IDENTIFIER_LENGTH:
        _fail(DashboardMessages.BINDING_INVALID)
    for character in value:
        if character not in IDENTIFIER_CHARS:
            _fail(DashboardMessages.BINDING_INVALID)
    return value


def _check_endpoint_id(value: Any) -> str:
    """One endpoint id on a binding.

    A different character set from an identifier: an endpoint id is namespaced
    under its plug-in's service id, so it carries dots. The prefix itself is checked
    where the manifest is normalized — a dashboard definition is not the place
    that knows which plug-in it belongs to.
    """
    if not isinstance(value, str) or not value or len(value) > MAX_ENDPOINT_ID_LENGTH:
        _fail(DashboardMessages.BINDING_INVALID)
    for character in value:
        if character not in ENDPOINT_ID_CHARS:
            _fail(DashboardMessages.BINDING_INVALID)
    return value


def _check_uid(value: Any, code: str) -> str:
    if not isinstance(value, str) or len(value) != UID_LENGTH:
        _fail(code)
    for character in value:
        if character not in UID_ALPHABET:
            _fail(code)
    return value


def plugin_widget_parts(declared: str) -> tuple[str, str] | None:
    """Split ``plugin:<listing_uid>:<widget_id>``, or None if it is not one.

    ``:`` is outside the identifier character set on both halves, so the three
    parts stay unambiguous however a plug-in names its widget.
    """
    if not declared.startswith(PLUGIN_WIDGET_TYPE_PREFIX):
        return None
    remainder = declared[len(PLUGIN_WIDGET_TYPE_PREFIX) :]
    listing_uid, separator, widget_id = remainder.partition(":")
    if not separator:
        _fail(DashboardMessages.WIDGET_TYPE_UNKNOWN)
    _check_uid(listing_uid, DashboardMessages.WIDGET_TYPE_UNKNOWN)
    if (
        not widget_id
        or len(widget_id) > MAX_IDENTIFIER_LENGTH
        or any(character not in IDENTIFIER_CHARS for character in widget_id)
    ):
        _fail(DashboardMessages.WIDGET_TYPE_UNKNOWN)
    return listing_uid, widget_id


def _normalize_plugin_binding(
    binding: dict[str, Any], listing_uid: str
) -> dict[str, Any]:
    """A ``plugin`` binding: which installed plug-in, which source, which parameters.

    ``plugin_uid`` has to be the plug-in the widget came from. A widget is one plug-in's
    module and its endpoints are that plug-in's, so letting a definition point one
    plug-in's widget at another plug-in's data would be a definition choosing what
    crosses between two vendors.
    """
    declared_uid = _check_uid(
        binding.get("plugin_uid"), DashboardMessages.BINDING_INVALID
    )
    if declared_uid != listing_uid:
        _fail(DashboardMessages.BINDING_INVALID)
    endpoint_id = _check_endpoint_id(binding.get("endpoint_id"))

    raw_params = binding.get("params")
    params: dict[str, Any] = {}
    if raw_params is not None:
        if (
            not isinstance(raw_params, dict)
            or len(raw_params) > MAX_PLUGIN_BINDING_PARAMS
        ):
            _fail(DashboardMessages.BINDING_INVALID)
        for key, value in raw_params.items():
            params[_check_identifier(key)] = _check_plugin_param(value)

    cleaned: dict[str, Any] = {
        "source": PLUGIN_BINDING_SOURCE,
        "plugin_uid": listing_uid,
        "endpoint_id": endpoint_id,
    }
    if params:
        cleaned["params"] = params
    return cleaned


def _check_plugin_param(value: Any) -> Any:
    """One parameter value: a scalar, or several of them.

    Deliberately not coerced: the source's own ``params_schema`` declares the
    type, and turning a ``true`` into a ``1`` here would quietly satisfy a check
    the fetch path is supposed to refuse.

    An array is a stored value like any other because an endpoint may declare a
    parameter ``list`` — several labels, several assignees — and a binding that
    could hold only one of them could not express what such a parameter is for.
    Which parameters those are is the plug-in's declaration and is checked where it
    is enforced, at fetch time; what is checked here is only the shape and the
    bound, which is all a definition can know about somebody else's manifest.
    """
    if isinstance(value, list):
        if len(value) > MAX_PLUGIN_PARAM_VALUES:
            _fail(DashboardMessages.BINDING_INVALID)
        return [_check_plugin_scalar(entry) for entry in value]
    return _check_plugin_scalar(value)


def _check_plugin_scalar(value: Any) -> Any:
    """One value inside a parameter, of the types a manifest may declare."""
    if isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, str) and len(value) <= MAX_PLUGIN_PARAM_LENGTH:
        return value
    _fail(DashboardMessages.BINDING_INVALID)


# --- presets ---------------------------------------------------------------
#
# A preset is a *named widget* built from a primitive plus fixed options. It
# ships no code, so it is the safe extension point: a marketplace listing
# declares presets, they resolve to a first-party primitive at validation time,
# and a definition that names one is stored resolved. Nothing a listing supplies
# ever becomes a renderer.
#
# Presets are a *storage* concept, not a palette one — the picker offers each
# primitive's options directly, so "bar chart" is the chart widget with its mark
# chosen rather than a second entry saying the same thing. The built-ins below
# stay because a stored or downloaded definition may still name them.


@dataclass(frozen=True)
class WidgetPreset:
    primitive: str
    options: Mapping[str, str]


WIDGET_PRESETS: dict[str, WidgetPreset] = {
    "bar_chart": WidgetPreset("chart", {"mark": "bar"}),
    "line_chart": WidgetPreset("chart", {"mark": "line"}),
    "area_chart": WidgetPreset("chart", {"mark": "area"}),
    "pie_chart": WidgetPreset("chart", {"mark": "pie"}),
    "stacked_bar_chart": WidgetPreset("chart", {"mark": "bar", "stacked": "true"}),
    "timeline": WidgetPreset("gantt", {"scale": "week"}),
    "percent_stat": WidgetPreset("stat", {"format": "percent"}),
}

# Every name a definition may use for a widget.
WIDGET_TYPES: frozenset[str] = frozenset(WIDGET_SPECS) | frozenset(WIDGET_PRESETS)

# Fail at import time, not request time: a preset pointing at a primitive that
# doesn't exist (or setting an option it doesn't accept) is a programming error.
for _name, _preset in WIDGET_PRESETS.items():
    if _preset.primitive not in WIDGET_SPECS:
        raise RuntimeError(f"preset {_name!r} names unknown primitive")
    _allowed = WIDGET_SPECS[_preset.primitive].options
    for _key, _value in _preset.options.items():
        if _key not in _allowed or _value not in _allowed[_key].values:
            raise RuntimeError(f"preset {_name!r} sets invalid option {_key}={_value}")
if WIDGET_SPECS.keys() & WIDGET_PRESETS.keys():
    raise RuntimeError("a preset may not shadow a primitive name")
for _name, _spec in WIDGET_SPECS.items():
    for _key, _declared in _spec.options.items():
        if _declared.kind == "choice" and _declared.default not in _declared.values:
            raise RuntimeError(f"{_name}.{_key} defaults to a value it does not allow")


# --- normalization ---------------------------------------------------------


def _require_mapping(value: Any, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(code)
    return value


def _clean_text(value: Any) -> str | None:
    """Plain text only — never markup. Non-strings are dropped rather than
    coerced, so a nested object never ends up in a rendered label."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped[:MAX_TITLE_LENGTH] if stripped else None


def _grid_int(value: Any, *, low: int, high: int, default: int | None) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return default if value < low or value > high else value


def _normalize_grid(raw: Any, spec: WidgetSpec) -> dict[str, int]:
    grid = raw if isinstance(raw, dict) else {}
    w = _grid_int(grid.get("w"), low=1, high=MAX_GRID_COLUMNS, default=None)
    h = _grid_int(grid.get("h"), low=1, high=MAX_GRID_ROWS, default=None)
    w = spec.default_w if w is None else min(max(w, spec.min_w), MAX_GRID_COLUMNS)
    h = spec.default_h if h is None else max(h, spec.min_h)
    x = _grid_int(grid.get("x"), low=0, high=MAX_GRID_COLUMNS - 1, default=0) or 0
    y = _grid_int(grid.get("y"), low=0, high=MAX_GRID_ROWS, default=0) or 0
    # Keep the widget inside the grid rather than rejecting the definition.
    if x + w > MAX_GRID_COLUMNS:
        x = max(0, MAX_GRID_COLUMNS - w)
    return {"x": x, "y": y, "w": w, "h": h}


#: Binding parameters the *definition* does not carry, because the request
#: already establishes them: a dashboard is fetched under a guild and belongs to
#: an initiative, so those come from the row it lives on rather than from
#: something an author or an installed listing typed.
#:
#: Every source shipping at launch reads within one initiative, so a definition
#: has nothing to express here. A later source that genuinely spans initiatives
#: would state its scope as part of that source's own contract, decided then,
#: rather than by re-opening a free-form id here.
_CONTEXT_ONLY_PARAMS = frozenset({"initiative_id", "guild_id"})

#: Binding keys only a definition sets: what a widget reads, as opposed to the
#: values it reads it with. Instance config never carries them.
_DEFINITION_ONLY_KEYS = (
    frozenset({"source", "sql", "plugin_uid", "endpoint_id"}) | _CONTEXT_ONLY_PARAMS
)


def _normalize_binding(
    raw: Any,
    spec: WidgetSpec,
    *,
    plugin_listing_uid: str | None = None,
) -> dict[str, Any]:
    """Check the source is one we can fetch and this widget can draw, then keep
    its parameters as given for the fetcher to interpret."""
    binding = _require_mapping(raw, DashboardMessages.BINDING_INVALID)
    source = binding.get("source")

    if plugin_listing_uid is not None:
        # A plug-in widget draws its own plug-in's data and nothing else, so this is a
        # total branch rather than an extra allowed value.
        if source != PLUGIN_BINDING_SOURCE:
            _fail(DashboardMessages.BINDING_SOURCE_NOT_ALLOWED)
        return _normalize_plugin_binding(binding, plugin_listing_uid)

    if not isinstance(source, str) or source not in TABULAR_SOURCES:
        _fail(DashboardMessages.BINDING_SOURCE_UNKNOWN)
    params = {
        key: value
        for key, value in binding.items()
        if key != "source" and key not in _CONTEXT_ONLY_PARAMS
    }
    if source == QUERY_SOURCE:
        statement = _checked_statement(params.get("sql"))
        params.pop("sql", None)
        if statement is not None:
            params["sql"] = statement
    return {"source": source, **params}


def _checked_statement(raw: Any) -> str | None:
    """The statement, having been read the way the surface will read it.

    Checked here rather than at fetch time because a definition that cannot be
    fetched should not be storable: the author is looking at the query, and the
    validator says which word has to change. It is a pure read — no database, no
    planning — so it costs a parse.

    ``None`` for a widget that has no statement yet. That is a real state and
    not an error: a widget is placed before it is pointed anywhere, and an
    installed listing may ship one for its guild to fill in. It draws its own
    "not configured" panel rather than anything of anybody's, because there is
    nothing to run.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if not isinstance(raw, str):
        _fail(DashboardMessages.BINDING_SQL_MISSING)
        raise AssertionError  # unreachable; _fail raises
    if len(raw) > MAX_SQL_LENGTH:
        _fail(DashboardMessages.BINDING_SQL_TOO_LONG)
    try:
        resolve(raw)
    except QueryError as refused:
        raise DashboardDefinitionError(refused.code) from refused
    return raw


def _normalize_mapping(raw: Any, spec: WidgetSpec) -> dict[str, list[int]]:
    """Which of a statement's columns fill this widget's slots.

    Column *ordinals*, not names: ``SELECT t.id, p.id`` names both columns
    ``id``, so a name is not a key. A widget declaring no shape draws every
    column and has nothing to map.

    What is not checked here is whether the ordinals exist or hold the right
    type — that needs the statement described against a database, which a
    normalizer has no session for. The author's own editor checks it as they
    write (``/query/describe``), and a mapping that has gone stale draws as a
    table rather than as an error.
    """
    if raw is None or not spec.shape:
        return {}
    mapping = _require_mapping(raw, DashboardMessages.WIDGET_MAPPING_INVALID)
    slots = {slot.name: slot for slot in spec.shape}
    cleaned: dict[str, list[int]] = {}
    for name, value in mapping.items():
        slot = slots.get(name)
        if slot is None:
            _fail(DashboardMessages.WIDGET_MAPPING_INVALID)
            raise AssertionError  # unreachable; _fail raises
        ordinals = value if isinstance(value, list) else [value]
        if not ordinals or (len(ordinals) > 1 and not slot.repeatable):
            _fail(DashboardMessages.WIDGET_MAPPING_INVALID)
        for ordinal in ordinals:
            if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
                _fail(DashboardMessages.WIDGET_MAPPING_INVALID)
        cleaned[name] = list(ordinals)
    return cleaned


def _normalize_options(raw: Any, spec: WidgetSpec, preset: WidgetPreset | None) -> dict:
    """Widget-level display options, checked against the primitive's allow-list.

    A preset's own options are applied last: they are what make it that preset,
    so a definition can fill in the rest but not contradict its identity.
    """
    supplied = raw if isinstance(raw, dict) else {}
    options: dict[str, str] = {}
    for key, value in supplied.items():
        allowed = spec.options.get(key)
        if allowed is None:
            continue
        if allowed.kind != "choice":
            written = _free_value(allowed.kind, value)
            if written is not None:
                options[key] = written
            continue
        # Booleans are accepted for flag-shaped options and stored as strings so
        # the option vocabulary stays a flat set of literals.
        candidate = str(value).lower() if isinstance(value, bool) else value
        if not isinstance(candidate, str) or candidate not in allowed.values:
            _fail(DashboardMessages.WIDGET_OPTION_INVALID)
        options[key] = candidate
    if preset is not None:
        options.update(preset.options)
    return options


#: Longer than any number or day an author types.
_MAX_FREE_VALUE = 32

#: Below this a whole number is exact in a float, and short.
_EXACT_WHOLE = 10**15


def _free_value(kind: OptionKind, value: Any) -> str | None:
    """A number or a day, as it is stored: ``None`` when it is left empty.

    A number is written plainly (``50``, ``2.5``). A day is ``YYYY-MM-DD``,
    the form a date input gives.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if kind == "number":
        if isinstance(value, bool):
            _fail(DashboardMessages.WIDGET_OPTION_INVALID)
        if isinstance(value, str) and len(value) > _MAX_FREE_VALUE:
            _fail(DashboardMessages.WIDGET_OPTION_INVALID)
        try:
            number = float(value)
        except (TypeError, ValueError):
            _fail(DashboardMessages.WIDGET_OPTION_INVALID)
            raise AssertionError  # unreachable; _fail raises
        if not math.isfinite(number):
            _fail(DashboardMessages.WIDGET_OPTION_INVALID)
        # A whole number short enough to be exact is written as one; anything
        # else in the shortest form that reads back the same (``1e+32``), so a
        # stored value is always one that saves again.
        if number.is_integer() and abs(number) < _EXACT_WHOLE:
            return str(int(number))
        return repr(number)
    if not isinstance(value, str) or len(value) != len("2026-06-30"):
        _fail(DashboardMessages.WIDGET_OPTION_INVALID)
        raise AssertionError  # unreachable; _fail raises
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        _fail(DashboardMessages.WIDGET_OPTION_INVALID)
        raise AssertionError  # unreachable; _fail raises


def _normalize_widget(
    raw: Any,
    index: int,
    seen_ids: set[str],
) -> dict[str, Any]:
    widget = _require_mapping(raw, DashboardMessages.WIDGET_INVALID)
    declared = widget.get("type")
    if not isinstance(declared, str):
        _fail(DashboardMessages.WIDGET_TYPE_UNKNOWN)

    # A plug-in's widget keeps its namespaced type verbatim: the module that draws
    # it lives in the installed plug-in's pinned definition, and this build resolves
    # it there rather than in the built-in registry.
    plugin_parts = plugin_widget_parts(declared)
    if plugin_parts is not None:
        preset = None
        primitive = declared
        spec = PLUGIN_WIDGET_SPEC
    else:
        if declared not in WIDGET_TYPES:
            _fail(DashboardMessages.WIDGET_TYPE_UNKNOWN)
        # Resolve a preset to its primitive, so what gets stored (and what the
        # renderer sees) is always a first-party widget kind.
        preset = WIDGET_PRESETS.get(declared)
        primitive = preset.primitive if preset else declared
        spec = WIDGET_SPECS[primitive]

    widget_id = _clean_text(widget.get("id")) or f"w{index + 1}"
    if widget_id in seen_ids:
        _fail(DashboardMessages.WIDGET_ID_DUPLICATE)
    seen_ids.add(widget_id)

    cleaned: dict[str, Any] = {
        "id": widget_id,
        "type": primitive,
        "grid": _normalize_grid(widget.get("grid"), spec),
        "binding": _normalize_binding(
            widget.get("binding"),
            spec,
            plugin_listing_uid=plugin_parts[0] if plugin_parts else None,
        ),
    }
    if preset is not None:
        # Kept for round-tripping and for labelling the widget in the palette.
        cleaned["preset"] = declared
    title = _clean_text(widget.get("title"))
    if title is not None:
        cleaned["title"] = title
    options = _normalize_options(widget.get("options"), spec, preset)
    if options:
        cleaned["options"] = options
    mapping = _normalize_mapping(widget.get("mapping"), spec)
    if mapping:
        cleaned["mapping"] = mapping
    return cleaned


def normalize_dashboard_definition(payload: Any) -> dict[str, Any]:
    """Validate and canonicalize a dashboard definition.

    Raises ``DashboardDefinitionError`` with a machine code for a widget type or
    binding source this app has no renderer/fetcher for; returns a definition in
    canonical shape.
    """
    definition = _require_mapping(payload, DashboardMessages.DEFINITION_INVALID)

    if definition.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        _fail(DashboardMessages.DEFINITION_VERSION_UNSUPPORTED)

    raw_widgets = definition.get("widgets", [])
    if not isinstance(raw_widgets, list):
        _fail(DashboardMessages.DEFINITION_INVALID)
    if len(raw_widgets) > MAX_WIDGETS:
        _fail(DashboardMessages.TOO_MANY_WIDGETS)

    seen_ids: set[str] = set()
    widgets = [
        _normalize_widget(raw, index, seen_ids) for index, raw in enumerate(raw_widgets)
    ]

    raw_layout = definition.get("layout")
    layout = raw_layout if isinstance(raw_layout, dict) else {}
    columns = _grid_int(
        layout.get("columns"), low=1, high=MAX_GRID_COLUMNS, default=MAX_GRID_COLUMNS
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "dashboard",
        "layout": {"columns": columns},
        "widgets": widgets,
    }


def normalize_dashboard_config(
    payload: Any, definition: dict[str, Any]
) -> dict[str, Any]:
    """Validate instance config against a definition's widgets.

    Config fills the binding parameters a definition left open (the ids a
    catalog listing can't know), and nothing else: a key the definition set, or
    one that says what the widget reads rather than how (its source, statement,
    plug-in or endpoint), is dropped. What remains is checked by the same
    normalizer as the definition's own binding, laid over it. Entries naming a
    widget the definition doesn't have are dropped too, so updating to a
    version that removes a widget can't leave dangling config behind.
    """
    config = _require_mapping(payload, DashboardMessages.CONFIG_INVALID)
    raw_widgets = config.get("widgets")
    if raw_widgets is None:
        return {"widgets": {}}
    widget_config = _require_mapping(raw_widgets, DashboardMessages.CONFIG_INVALID)

    cleaned: dict[str, dict[str, Any]] = {}
    for widget in definition.get("widgets", []):
        values = widget_config.get(widget["id"])
        if not isinstance(values, dict):
            continue
        binding = widget["binding"]
        open_values = {
            key: value
            for key, value in values.items()
            if key not in _DEFINITION_ONLY_KEYS and binding.get(key) is None
        }
        if not open_values:
            continue
        plugin_parts = plugin_widget_parts(widget["type"])
        resolved = _normalize_binding(
            {**binding, **open_values},
            PLUGIN_WIDGET_SPEC if plugin_parts else WIDGET_SPECS[widget["type"]],
            plugin_listing_uid=plugin_parts[0] if plugin_parts else None,
        )
        kept = {key: resolved[key] for key in open_values if key in resolved}
        if kept:
            cleaned[widget["id"]] = kept
    return {"widgets": cleaned}
