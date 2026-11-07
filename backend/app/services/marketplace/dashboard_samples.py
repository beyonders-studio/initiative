"""Sample data for a dashboard listing, generated from its queries.

A dashboard is queries over the community it sits in, so its listing cannot
show the publisher's results: those are their community's numbers, not
something they made for the listing. It shows generated rows instead, shaped
like each query's answer — the columns the statement returns, named and typed
from the field registry (:func:`describe_statement`), with plausible
values of each type: dates around a fixed day, statuses from the default set,
names from a neutral list.

Generated from the listing alone and seeded by it, so the same listing always
previews the same way, and nothing here reads any community.

A widget this cannot describe — a plug-in's own widget, one with no statement yet,
a statement this build cannot read — gets no sample and previews as the widget
does without one.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from pglast import ast

from app.core.messages import QueryMessages
from app.services.fields.spec import FieldType
from app.services.query.resolve import (
    QueryError,
    _check_nodes,
    _expand_relations,
    _field_named,
    _name_parts,
    _parse,
    _read_by,
    _relations,
    _take_calls,
)

__all__ = [
    "MAX_SAMPLE_BYTES",
    "MAX_SAMPLE_ROWS",
    "SAMPLE_NOW",
    "generate_dashboard_sample",
    "normalize_dashboard_sample",
]

#: The day samples are drawn around — the same one the canvas's own
#: placeholder rows use, so a preview reads as one moment.
SAMPLE_NOW = datetime(2026, 8, 3, tzinfo=timezone.utc)

#: How many rows a sample widget shows, grouped or not.
_GROUPED_ROWS = 5
_PLAIN_ROWS = 8

#: A publisher's own sample data is held to these.
MAX_SAMPLE_ROWS = 200
MAX_SAMPLE_BYTES = 256 * 1024

_PEOPLE = ("Avery", "Blake", "Casey", "Drew", "Emery", "Finley", "Harper", "Kai")
_TITLES = (
    "Draft the brief",
    "Review the budget",
    "Book the venue",
    "Update the roadmap",
    "Plan the launch",
    "Write the release notes",
    "Order supplies",
    "Test the sign-up flow",
)
_GROUPS = (
    "Website refresh",
    "Spring event",
    "Onboarding",
    "Data migration",
    "Mobile app",
)
_STATUSES = ("To Do", "In Progress", "Done")
_LABELS = ("Planning", "Design", "Build", "Review", "Launch", "Support")

#: Which neutral list a text column draws from, by what its name says it holds.
#: Checked in order; the first word the name contains wins.
_TEXT_VOCABULARY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("display_name", _PEOPLE),
    ("assignee", _PEOPLE),
    ("member", _PEOPLE),
    ("author", _PEOPLE),
    ("status", _STATUSES),
    ("title", _TITLES),
    ("project", _GROUPS),
    ("initiative", _GROUPS),
    ("calendar", _GROUPS),
    ("group", _GROUPS),
)


def _vocabulary(column_name: str) -> tuple[str, ...]:
    lowered = column_name.lower()
    for word, vocabulary in _TEXT_VOCABULARY:
        if word in lowered:
            return vocabulary
    return _LABELS


def _epoch_ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _value(column: Any, rng: random.Random, row: int, grouped: bool) -> Any:
    """One plausible value for one column, as the query surface writes it."""
    if column.type is FieldType.number:
        if column.aggregate:
            if column.name.startswith(("avg", "average")):
                return round(rng.uniform(1, 10), 1)
            if column.name.startswith("sum"):
                return rng.randint(10, 200)
            return rng.randint(2, 24)
        return rng.randint(0, 100)
    if column.type is FieldType.date:
        if grouped:
            # A grouped date is a bucket: consecutive weeks, oldest first.
            return _epoch_ms(SAMPLE_NOW - timedelta(weeks=_GROUPED_ROWS - 1 - row))
        return _epoch_ms(SAMPLE_NOW + timedelta(days=rng.randint(-14, 21)))
    if column.type is FieldType.boolean:
        return rng.random() < 0.5
    if column.type is FieldType.reference:
        return rng.randint(1, 50)
    options = tuple(column.options) or (
        _vocabulary(column.name) if column.type is not FieldType.enum else ()
    )
    if not options:
        return f"Item {row + 1}"
    if grouped:
        return options[row % len(options)]
    return rng.choice(options)


#: What each aggregate answers. ``None``: whatever its argument was — the
#: largest date is a date.
_AGGREGATE_TYPES: dict[str, Optional[FieldType]] = {
    "count": FieldType.number,
    "sum": FieldType.number,
    "avg": FieldType.number,
    "min": None,
    "max": None,
}

#: What each other function answers, where it is fixed.
_FUNCTION_TYPES: dict[str, Optional[FieldType]] = {
    "abs": FieldType.number,
    "round": FieldType.number,
    "length": FieldType.number,
    "lower": FieldType.text,
    "upper": FieldType.text,
    "concat": FieldType.text,
    "date_trunc": FieldType.date,
    "extract": FieldType.number,
    "now": FieldType.date,
    "coalesce": None,
    "row_number": FieldType.number,
    "rank": FieldType.number,
    "dense_rank": FieldType.number,
    "percent_rank": FieldType.number,
    "cume_dist": FieldType.number,
    "ntile": FieldType.number,
    "lag": None,
    "lead": None,
    "first_value": None,
    "last_value": None,
    "nth_value": None,
}


@dataclass(frozen=True)
class StatementColumn:
    """One column a statement returns, as far as the tree says."""

    name: str
    type: FieldType
    #: The closed vocabulary the column draws from, when it is a field that has
    #: one (a status category, a priority).
    options: tuple[str, ...] = ()
    #: Whether it is an aggregate over rows rather than a value of one row.
    aggregate: bool = False


def _function_name(call: ast.FuncCall) -> str:
    names = _name_parts(call.funcname)
    return names[-1] if names else ""


def _type_of(node: Any, declared: Mapping[str, FieldType]) -> FieldType:
    """What an output expression holds, worked out from the tree. Where a type
    cannot be, it reads as text, which is what an unrecognised value is to a
    reader."""
    first = getattr(node, "args", None) or ()
    if isinstance(node, ast.ColumnRef):
        names = _name_parts(node.fields)
        return declared.get(names[-1], FieldType.text) if names else FieldType.text
    if isinstance(node, ast.A_Const):
        if isinstance(node.val, (ast.Integer, ast.Float)):
            return FieldType.number
        return (
            FieldType.boolean if isinstance(node.val, ast.Boolean) else FieldType.text
        )
    if isinstance(node, ast.FuncCall):
        name = _function_name(node)
        fixed = {**_AGGREGATE_TYPES, **_FUNCTION_TYPES}.get(name, FieldType.text)
        if fixed is not None:
            return fixed
        return _type_of(first[0], declared) if first else FieldType.text
    if isinstance(node, (ast.CoalesceExpr, ast.MinMaxExpr)):
        return _type_of(first[0], declared) if first else FieldType.text
    if isinstance(node, ast.CaseExpr):
        for when in first:
            if isinstance(when, ast.CaseWhen):
                return _type_of(when.result, declared)
        return _type_of(node.defresult, declared) if node.defresult else FieldType.text
    if isinstance(node, ast.A_Expr):
        # Arithmetic answers with a number; a comparison with a yes or no.
        operator = _name_parts(node.name)
        return (
            FieldType.number
            if operator and operator[-1] in {"+", "-", "*", "/", "%"}
            else FieldType.boolean
        )
    if isinstance(node, (ast.BoolExpr, ast.NullTest, ast.BooleanTest)):
        return FieldType.boolean
    return FieldType.text


def describe_statement(
    sql: str,
) -> tuple[tuple[StatementColumn, ...], tuple[str, ...]]:
    """What a statement over the community's datasets returns, and which
    datasets it reads — worked out from the tree alone.

    The live path asks the database about any output the registry cannot name.
    A listing previewing on sample rows has no database to ask, so a field is
    the field the registry declares, and an expression is typed by what it is
    built from. A spreadsheet or a plug-in is not read here, so its columns
    read as text.
    """
    select = _parse(sql)
    recordsets = {
        key: _read_by(None, call) for key, (_, call) in _take_calls(select).items()
    }
    _check_nodes(select)
    _expand_relations(select)
    scope = _relations(select, recordsets)
    declared: dict[str, FieldType] = {}
    for source in scope.values():
        for field_name, spec in source.by_name.items():
            declared.setdefault(field_name, spec.type)
    described: list[StatementColumn] = []
    for position, target in enumerate(select.targetList or ()):
        if not isinstance(target, ast.ResTarget):
            raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, type(target).__name__)
        spec = _field_named(scope, target.val)
        names = _name_parts(getattr(target.val, "fields", None))
        described.append(
            StatementColumn(
                name=target.name
                or (names[-1] if names else "")
                or (isinstance(target.val, ast.FuncCall) and _function_name(target.val))
                or f"column{position + 1}",
                type=spec.type if spec is not None else _type_of(target.val, declared),
                options=tuple(spec.options) if spec is not None else (),
                aggregate=isinstance(target.val, ast.FuncCall)
                and _function_name(target.val) in _AGGREGATE_TYPES,
            )
        )
    if not described:
        raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, "SELECT")
    return tuple(described), tuple(sorted({source.name for source in scope.values()}))


def _query_sample(sql: str, rng: random.Random) -> dict[str, Any] | None:
    try:
        columns, relations = describe_statement(sql)
    except QueryError:
        return None
    has_aggregate = any(column.aggregate for column in columns)
    grouped = has_aggregate and not all(column.aggregate for column in columns)
    if has_aggregate and not grouped:
        count = 1
    elif grouped:
        # One row per group, and no more groups than the grouping column has
        # distinct values to give.
        vocabularies = [
            len(column.options) or len(_vocabulary(column.name))
            for column in columns
            if not column.aggregate and column.type in (FieldType.enum, FieldType.text)
        ]
        count = min([_GROUPED_ROWS, *vocabularies])
    else:
        count = _PLAIN_ROWS
    rows = [
        [_value(column, rng, row, grouped) for column in columns]
        for row in range(count)
    ]
    return {
        "columns": [
            {"name": column.name, "type": column.type.value} for column in columns
        ],
        "rows": rows,
        "truncated": False,
        "relations": list(relations),
    }


def _widgets(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    canvas = envelope.get("definition") or {}
    return [w for w in canvas.get("widgets") or [] if isinstance(w, dict)]


def generate_dashboard_sample(
    envelope: dict[str, Any], *, seed: str
) -> dict[str, dict[str, Any]]:
    """Sample answers for a dashboard listing's widgets, by widget id.

    ``envelope`` is the stored listing (the dashboard's envelope); ``seed``
    names the listing and version, so each draws the same sample every time.
    """
    samples: dict[str, dict[str, Any]] = {}
    for widget in _widgets(envelope):
        widget_id = widget.get("id")
        binding = widget.get("binding") or {}
        if not isinstance(widget_id, str) or not isinstance(binding, dict):
            continue
        rng = random.Random(
            int.from_bytes(
                hashlib.sha256(f"{seed}:{widget_id}".encode()).digest()[:8], "big"
            )
        )
        source = binding.get("source")
        sample = (
            _query_sample(binding["sql"], rng)
            if source == "query" and isinstance(binding.get("sql"), str)
            else None
        )
        if sample is not None:
            samples[widget_id] = sample
    return samples


def normalize_dashboard_sample(
    envelope: dict[str, Any], sample: Any
) -> dict[str, dict[str, Any]]:
    """A publisher's own sample data for a dashboard listing, checked.

    The same shape the generator writes: per widget of the listing, the columns
    it answers with and the rows. Only the listing's own widgets, and nothing
    larger than a preview needs.
    """
    from app.services.marketplace.manifest_values import ListingDefinitionError

    if not isinstance(sample, dict):
        raise ListingDefinitionError("a dashboard's sample data must be an object")
    widget_ids = {w.get("id") for w in _widgets(envelope)}
    types = {member.value for member in FieldType}
    cleaned: dict[str, dict[str, Any]] = {}
    for widget_id, answer in sample.items():
        if widget_id not in widget_ids:
            raise ListingDefinitionError(f"sample data names no widget {widget_id!r}")
        if not isinstance(answer, dict):
            raise ListingDefinitionError(
                f"sample data for {widget_id!r} is not an object"
            )
        columns = answer.get("columns")
        rows = answer.get("rows")
        if not isinstance(columns, list) or not isinstance(rows, list):
            raise ListingDefinitionError(
                f"sample data for {widget_id!r} needs columns and rows"
            )
        if len(rows) > MAX_SAMPLE_ROWS:
            raise ListingDefinitionError(
                f"sample data for {widget_id!r} has more than {MAX_SAMPLE_ROWS} rows"
            )
        clean_columns = []
        for column in columns:
            if (
                not isinstance(column, dict)
                or not isinstance(column.get("name"), str)
                or column.get("type") not in types
            ):
                raise ListingDefinitionError(
                    f"sample data for {widget_id!r} has a column that is not one"
                )
            clean_columns.append({"name": column["name"], "type": column["type"]})
        if any(
            not isinstance(row, list) or len(row) != len(clean_columns) for row in rows
        ):
            raise ListingDefinitionError(
                f"sample data for {widget_id!r} has a row that does not fit its columns"
            )
        cleaned[widget_id] = {
            "columns": clean_columns,
            "rows": rows,
            "truncated": False,
            "relations": [],
        }
    if len(json.dumps(cleaned).encode("utf-8")) > MAX_SAMPLE_BYTES:
        raise ListingDefinitionError("sample data is larger than a preview takes")
    return cleaned
