"""Run a statement over rows that never came from Postgres.

An installed plug-in answers with rows of its own — JSON objects the proxy hands
back, bounded by the response cap. They are not in a table, so there is nothing
to plan and nothing to hand the server; but the question somebody wants to ask
of them is the same question they ask of a task list. Group these by that,
count them, take the ten largest.

So the statement is read by the same validator, against the same allow-lists,
and then *evaluated here* rather than deparsed. Two halves:

**Planning** checks the statement and resolves its names — against the columns
the endpoint declares it returns, rather than against the field registry, since
a plug-in's shape is the plug-in's to state. It is pure, so a widget whose statement
names a column its endpoint does not return is refused while its author is
looking at it, exactly as a Postgres one is.

**Evaluating** runs it: the residual ``WHERE``, then grouping and its
aggregates, then ordering, then the limit. Nothing here is a second opinion
about what a statement may contain — the node types and the functions are the
ones :mod:`app.services.query.resolve` already admits, so a construct reaches
this only by being on that list.

One relation, named ``rows``: the rows this binding fetched. Which plug-in, which
endpoint and with what parameters is the binding's to say and not the
statement's, so there is nothing here to join and nothing to look up.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from pglast import ast
from pglast.stream import RawStream
from pglast.enums import (
    A_Expr_Kind,
    SortByNulls,
    BoolExprType,
    BoolTestType,
    MinMaxOp,
    NullTestType,
    SortByDir,
)

from app.core.messages import QueryMessages
from app.services.fields.spec import FieldType
from app.services.query.resolve import (
    VIEWER,
    WINDOW_FUNCTIONS,
    QueryError,
    _check_nodes,
    _name_parts,
    _parse,
)

#: The one relation a statement over fetched rows may name.
RELATION = "rows"

#: What each aggregate answers, and what type it answers with. ``None`` means
#: the answer is whatever its argument was — the largest date is a date.
_AGGREGATE_TYPES: dict[str, Optional[FieldType]] = {
    "count": FieldType.number,
    "sum": FieldType.number,
    "avg": FieldType.number,
    "min": None,
    "max": None,
}

#: Scalar functions and the type each answers with, where it is fixed.
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
}

#: What each window function answers, for describing a statement over the
#: community's datasets. ``None``: whatever its argument was.
_WINDOW_TYPES: dict[str, Optional[FieldType]] = {
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
class RowColumn:
    """One column of the rows a statement reads, or of the ones it returns."""

    name: str
    type: FieldType


@dataclass(frozen=True)
class RowPlan:
    """A statement checked against a declared shape, ready to run over rows.

    Holds the parsed tree rather than a second intermediate form: the tree is
    what the validator already read, and inventing an IR beside it would be one
    more thing that can disagree with it.
    """

    select: ast.SelectStmt
    #: What the rows coming in hold, as the endpoint declared them.
    reads: tuple[RowColumn, ...]
    #: What the statement returns, in order. Known without running it, because
    #: every column it can name was declared.
    columns: tuple[RowColumn, ...]


# --- planning ----------------------------------------------------------------


def plan(sql: str, reads: Sequence[RowColumn]) -> RowPlan:
    """Read *sql* as a statement over rows shaped like *reads*.

    Raises :class:`QueryError` naming what has to change, the same way the
    Postgres path does.
    """
    select = _parse(sql)
    _check_nodes(select)
    _check_no_window(select)
    _check_relation(select)
    # ``DISTINCT`` is a list holding one ``None``; ``DISTINCT ON`` holds the
    # expressions it is distinct on, which picks a row per key by an ordering
    # this does not own.
    if select.distinctClause and any(
        entry is not None for entry in select.distinctClause
    ):
        raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, "DISTINCT ON")
    declared = {column.name: column for column in reads}
    _resolve_names(select, declared)
    _check_grouping(
        select,
        [
            target.name or ""
            for target in select.targetList or ()
            if isinstance(target, ast.ResTarget)
        ],
        [column.name for column in reads],
    )
    return RowPlan(
        select=select,
        reads=tuple(reads),
        columns=_output_columns(select, declared),
    )


def _check_no_window(select: ast.SelectStmt) -> None:
    """Fetched rows have no window to run a function over: a running total or
    a rank is a question for a statement over the community's datasets."""
    if select.windowClause:
        raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, "WINDOW")
    for call in _func_calls(select):
        if call.over is not None or _function_name(call) in WINDOW_FUNCTIONS:
            raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, "OVER")


def _check_grouping(
    select: ast.SelectStmt, outputs: Sequence[str], reads: Sequence[str]
) -> None:
    """Every column a grouped statement reads outside an aggregate is grouped.

    The rule Postgres states as *"column must appear in the GROUP BY clause or
    be used in an aggregate function"*. Without it a statement that a table
    would refuse answers here from whichever row of the group came first, which
    is the one difference between the two paths worth least.
    """
    if not select.groupClause and not _has_aggregate(select.targetList):
        return
    grouped = {
        RawStream()(_group_expression(entry, select, outputs, reads))
        for entry in select.groupClause or ()
    }
    for target in select.targetList or ():
        if not isinstance(target, ast.ResTarget) or target.val is None:
            continue
        if RawStream()(target.val) in grouped:
            continue
        for reference in _ungrouped_refs(target.val):
            if RawStream()(reference) not in grouped:
                names = _name_parts(reference.fields)
                raise QueryError(
                    QueryMessages.UNGROUPED_FIELD,
                    f"{RELATION}.{names[-1] if names else ''}",
                )


def _ungrouped_refs(node: Any) -> list[ast.ColumnRef]:
    """Column references outside any aggregate. What an aggregate reads is its
    own business — that is the whole point of reducing a group."""
    found: list[ast.ColumnRef] = []

    def walk(value: Any) -> None:
        if isinstance(value, ast.FuncCall) and _aggregate_name(value):
            return
        if isinstance(value, ast.ColumnRef):
            found.append(value)
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
            return
        if isinstance(value, ast.Node):
            for name in value.__slots__:
                walk(getattr(value, name, None))

    walk(node)
    return found


def _check_relation(select: ast.SelectStmt) -> None:
    """One relation, and it is the rows this binding fetched."""
    if not select.fromClause:
        raise QueryError(QueryMessages.MISSING_RELATION)
    if len(select.fromClause) > 1:
        raise QueryError(QueryMessages.JOIN_WITHOUT_CONDITION, "FROM")
    node = select.fromClause[0]
    if not isinstance(node, ast.RangeVar):
        # A join needs two things to join, and there is only ever one here.
        raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, type(node).__name__)
    if node.schemaname or node.catalogname:
        raise QueryError(QueryMessages.QUALIFIED_RELATION, node.relname)
    if node.relname != RELATION:
        raise QueryError(QueryMessages.UNKNOWN_RELATION, node.relname)


def _output_aliases(select: ast.SelectStmt) -> frozenset[str]:
    return frozenset(
        target.name
        for target in (select.targetList or ())
        if isinstance(target, ast.ResTarget) and target.name
    )


def _resolve_names(select: ast.SelectStmt, declared: Mapping[str, RowColumn]) -> None:
    """Every column named is one the endpoint says it returns.

    An output alias is allowed where Postgres allows one — ``ORDER BY n`` and
    ``GROUP BY n`` name the select list, which does not exist yet in a
    ``WHERE``.
    """
    aliases = _output_aliases(select)
    ordinal_scopes = {
        id(node)
        for clause in (select.sortClause or (), select.groupClause or ())
        for entry in clause
        for node in _column_refs(entry)
    }

    for node in _column_refs(select):
        names = _name_parts(node.fields)
        if not names:
            raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, "ColumnRef")
        if len(names) == 2:
            if names[0] != RELATION:
                raise QueryError(QueryMessages.UNKNOWN_RELATION, names[0])
            names = names[1:]
        elif len(names) > 2:
            raise QueryError(QueryMessages.QUALIFIED_RELATION, ".".join(names))
        name = names[0]
        if name == VIEWER:
            # The reader is a row of ours, and these rows are a plug-in's. There
            # is nothing here for the word to mean.
            raise QueryError(QueryMessages.RESERVED_NAME, VIEWER)
        if name in declared:
            continue
        if name in aliases and id(node) in ordinal_scopes:
            continue
        raise QueryError(QueryMessages.UNKNOWN_FIELD, f"{RELATION}.{name}")


def _column_refs(node: Any) -> list[ast.ColumnRef]:
    """Every column reference under *node*, in the order they are met."""
    found: list[ast.ColumnRef] = []

    def walk(value: Any) -> None:
        if isinstance(value, ast.ColumnRef):
            found.append(value)
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
            return
        if isinstance(value, ast.Node):
            for name in value.__slots__:
                walk(getattr(value, name, None))

    walk(node)
    return found


def _has_aggregate(targets: Any) -> bool:
    return any(_aggregate_name(target) for target in _func_calls(targets))


def _func_calls(node: Any) -> list[ast.FuncCall]:
    found: list[ast.FuncCall] = []

    def walk(value: Any) -> None:
        if isinstance(value, ast.FuncCall):
            found.append(value)
        if isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
        elif isinstance(value, ast.Node):
            for name in value.__slots__:
                walk(getattr(value, name, None))

    walk(node)
    return found


def _aggregate_name(call: ast.FuncCall) -> Optional[str]:
    names = _name_parts(call.funcname)
    name = names[-1] if names else ""
    return name if name in _AGGREGATE_TYPES else None


def _function_name(call: ast.FuncCall) -> str:
    names = _name_parts(call.funcname)
    return names[-1] if names else ""


def _output_columns(
    select: ast.SelectStmt, declared: Mapping[str, RowColumn]
) -> tuple[RowColumn, ...]:
    """What the statement returns, named and typed.

    Nothing runs to find this out and nothing describes it: every column it can
    name was declared, so the answer follows from the tree.
    """
    columns: list[RowColumn] = []
    for position, target in enumerate(select.targetList or ()):
        if not isinstance(target, ast.ResTarget):
            raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, type(target).__name__)
        columns.append(
            RowColumn(
                name=target.name or _implicit_name(target.val, position),
                type=_type_of(target.val, declared),
            )
        )
    if not columns:
        raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, "SELECT")
    return tuple(columns)


def _implicit_name(node: Any, position: int) -> str:
    """What Postgres would call an unaliased output."""
    if isinstance(node, ast.ColumnRef):
        names = _name_parts(node.fields)
        if names:
            return names[-1]
    if isinstance(node, ast.FuncCall):
        return _function_name(node) or f"column{position + 1}"
    return f"column{position + 1}"


def _type_of(node: Any, declared: Mapping[str, RowColumn]) -> FieldType:
    """What an output expression holds.

    Static, because there is no database to ask. Where a type cannot be worked
    out it reads as text, which is what an unrecognised value is to a reader.
    """
    if isinstance(node, ast.ColumnRef):
        names = _name_parts(node.fields)
        column = declared.get(names[-1]) if names else None
        return column.type if column else FieldType.text
    if isinstance(node, ast.A_Const):
        return _const_type(node)
    if isinstance(node, ast.FuncCall):
        name = _function_name(node)
        if name in _AGGREGATE_TYPES:
            fixed = _AGGREGATE_TYPES[name]
            if fixed is not None:
                return fixed
            arguments = node.args or ()
            return _type_of(arguments[0], declared) if arguments else FieldType.text
        for types in (_FUNCTION_TYPES, _WINDOW_TYPES):
            if name in types:
                fixed = types[name]
                if fixed is not None:
                    return fixed
                arguments = node.args or ()
                return _type_of(arguments[0], declared) if arguments else FieldType.text
        return FieldType.text
    if isinstance(node, ast.CoalesceExpr):
        arguments = node.args or ()
        return _type_of(arguments[0], declared) if arguments else FieldType.text
    if isinstance(node, ast.MinMaxExpr):
        arguments = node.args or ()
        return _type_of(arguments[0], declared) if arguments else FieldType.text
    if isinstance(node, ast.CaseExpr):
        for when in node.args or ():
            if isinstance(when, ast.CaseWhen):
                return _type_of(when.result, declared)
        return _type_of(node.defresult, declared) if node.defresult else FieldType.text
    if isinstance(node, (ast.A_Expr,)):
        # Arithmetic answers with a number; a comparison with a yes or no.
        return (
            FieldType.number
            if _operator(node) in {"+", "-", "*", "/", "%"}
            else FieldType.boolean
        )
    if isinstance(node, (ast.BoolExpr, ast.NullTest, ast.BooleanTest)):
        return FieldType.boolean
    return FieldType.text


def _const_type(node: ast.A_Const) -> FieldType:
    held = node.val
    if isinstance(held, (ast.Integer, ast.Float)):
        return FieldType.number
    if isinstance(held, ast.Boolean):
        return FieldType.boolean
    return FieldType.text


def _operator(node: ast.A_Expr) -> str:
    names = _name_parts(node.name)
    return names[-1] if names else ""


# --- evaluating --------------------------------------------------------------


def evaluate(
    plan: RowPlan, rows: Iterable[Mapping[str, Any]]
) -> tuple[tuple[Any, ...], ...]:
    """Run *plan* over *rows*, in the order a statement means.

    The residual ``WHERE``, then grouping and its aggregates, then ordering,
    then the limit. Rows arrive as the plug-in returned them — objects keyed by the
    names it declared — and leave positional against :attr:`RowPlan.columns`,
    which is the shape every other read of this surface answers with.
    """
    select = plan.select
    # A declared moment must already be a moment when WHERE, grouping and
    # aggregates read it. Converting only the output makes equivalent ISO
    # spellings compare as different text and picks the wrong min/max.
    temporal = {column.name for column in plan.reads if column.type is FieldType.date}
    normalized = rows
    if temporal:
        normalized = (
            {
                key: _as_datetime(value) if key in temporal else value
                for key, value in row.items()
            }
            for row in rows
        )
    kept = [row for row in normalized if _truthy(_value(select.whereClause, row, None))]
    groups = _grouped(
        select,
        kept,
        [column.name for column in plan.columns],
        [column.name for column in plan.reads],
    )
    if select.havingClause is not None:
        groups = [
            group
            for group in groups
            if _truthy(_value(select.havingClause, group[0] if group else {}, group))
        ]
    targets = [
        target
        for target in select.targetList or ()
        if isinstance(target, ast.ResTarget)
    ]
    produced = [
        tuple(
            _wire(_value(target.val, group[0] if group else {}, group), column.type)
            for target, column in zip(targets, plan.columns)
        )
        for group in groups
    ]
    produced = _ordered(select, plan, groups, produced)
    if select.distinctClause is not None:
        produced = _distinct(produced)
    # Offset before limit, the way the clauses read: skip, then take.
    offset = _count(select.limitOffset)
    if offset:
        produced = produced[offset:]
    limit = _count(select.limitCount)
    if limit is not None:
        produced = produced[:limit]
    return tuple(produced)


def _count(node: Any) -> Optional[int]:
    """A row count from ``LIMIT`` or ``OFFSET``, or ``None`` for no bound."""
    if node is None:
        return None
    value = _value(node, {}, None)
    return max(0, int(value)) if isinstance(value, (int, float)) else None


def _distinct(produced: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    """One row per distinct row, first kept — which is what ``DISTINCT`` means
    once the ordering has already been applied."""
    seen: set[tuple] = set()
    kept: list[tuple[Any, ...]] = []
    for row in produced:
        key = tuple(_sortable(value) for value in row)
        if key in seen:
            continue
        seen.add(key)
        kept.append(row)
    return kept


def _group_expression(
    entry: Any,
    select: ast.SelectStmt,
    outputs: Sequence[str],
    reads: Sequence[str],
) -> Any:
    """What a ``GROUP BY`` entry actually groups by.

    An ordinal names the select list, so ``GROUP BY 1`` groups by the first
    output's *expression* rather than by the number one.

    A name goes the other way round from ``ORDER BY``: an unqualified one is an
    **input column** wherever there is one, and only falls back to an output
    alias where there is not. So an alias shadowing a column of the rows groups
    by the column, which is what the same statement does against a table.
    """
    targets = [
        target
        for target in select.targetList or ()
        if isinstance(target, ast.ResTarget)
    ]
    if isinstance(entry, ast.A_Const) and isinstance(entry.val, ast.Integer):
        ordinal = entry.val.ival - 1
        if 0 <= ordinal < len(targets):
            return targets[ordinal].val
        raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, "GROUP BY")
    if isinstance(entry, ast.ColumnRef):
        parts = _name_parts(entry.fields)
        name = parts[-1] if parts else ""
        if name and name not in reads and name in outputs:
            return targets[list(outputs).index(name)].val
    return entry


def _grouped(
    select: ast.SelectStmt,
    rows: list[Mapping[str, Any]],
    outputs: Sequence[str] = (),
    reads: Sequence[str] = (),
) -> list[list[Mapping[str, Any]]]:
    """The rows, in the groups the statement asks for.

    No grouping and no aggregate is one group per row — a plain read. An
    aggregate with no ``GROUP BY`` is one group over everything, which is what
    makes ``count(*)`` answer once rather than per row. And a statement that
    groups over nothing answers nothing, the way Postgres does.
    """
    if not select.groupClause:
        if _has_aggregate(select.targetList):
            return [list(rows)]
        return [[row] for row in rows]

    grouping = [
        _group_expression(entry, select, outputs, reads) for entry in select.groupClause
    ]
    keys: dict[tuple, list[Mapping[str, Any]]] = {}
    for row in rows:
        key = tuple(_sortable(_value(entry, row, None)) for entry in grouping)
        keys.setdefault(key, []).append(row)
    return list(keys.values())


def _ordered(
    select: ast.SelectStmt,
    plan: RowPlan,
    groups: list[list[Mapping[str, Any]]],
    produced: list[tuple[Any, ...]],
) -> list[tuple[Any, ...]]:
    """The rows, sorted. Sorted here rather than while producing them because
    an ``ORDER BY`` may name an output the statement computed."""
    if not select.sortClause:
        return produced
    names = {column.name: index for index, column in enumerate(plan.columns)}
    paired = list(zip(produced, groups))
    for entry in reversed(list(select.sortClause)):
        if not isinstance(entry, ast.SortBy):
            continue
        descending = entry.sortby_dir == SortByDir.SORTBY_DESC
        # Absent sorts as though larger than anything, which is last going up
        # and first coming down — so the default follows the direction.
        nulls_first = entry.sortby_nulls == SortByNulls.SORTBY_NULLS_FIRST or (
            entry.sortby_nulls == SortByNulls.SORTBY_NULLS_DEFAULT and descending
        )
        # And the sort below is reversed for a descending one, which reverses
        # this too: to land first there, absent has to key highest.
        nulls_low = nulls_first != descending
        paired.sort(
            key=lambda pair, node=entry.node, low=nulls_low: _sortable(
                _sort_value(node, pair, names), nulls_low=low
            ),
            reverse=descending,
        )
    return [row for row, _group in paired]


def _sort_value(
    node: Any,
    pair: tuple[tuple[Any, ...], list[Mapping[str, Any]]],
    names: Mapping[str, int],
) -> Any:
    """What one row sorts by: an output it produced, or an expression over the
    rows behind it."""
    produced, group = pair
    if isinstance(node, ast.A_Const) and isinstance(node.val, ast.Integer):
        ordinal = node.val.ival - 1
        return produced[ordinal] if 0 <= ordinal < len(produced) else None
    if isinstance(node, ast.ColumnRef):
        parts = _name_parts(node.fields)
        if parts and parts[-1] in names:
            return produced[names[parts[-1]]]
    return _value(node, group[0] if group else {}, group)


def _sortable(value: Any, *, nulls_low: bool = False) -> tuple[int, Any]:
    """A key that orders mixed values without raising.

    Nothing sorts against ``None``, so it goes to one end or the other;
    anything that is not a number or a string is compared as its text, which is
    what a reader sees. ``nulls_low`` is where the *key* goes, not where the
    row ends up: a caller sorting descending works that out against its own
    direction.
    """
    if value is None:
        return (-1, "") if nulls_low else (2, "")
    if isinstance(value, bool):
        return (0, float(value))
    if isinstance(value, (int, float)):
        return (0, float(value))
    if isinstance(value, (datetime, date)):
        return (0, float(_epoch_ms(value)))
    return (1, str(value))


# --- expressions -------------------------------------------------------------


#: Comparisons, as the operators the grammar reports. ``~~`` and ``~~*`` are
#: what ``LIKE`` and ``ILIKE`` are called once parsed.
_COMPARISONS: dict[str, Callable[[Any, Any], bool]] = {
    "=": lambda a, b: _compare(a, b) == 0,
    "<>": lambda a, b: _compare(a, b) != 0,
    "!=": lambda a, b: _compare(a, b) != 0,
    "<": lambda a, b: _compare(a, b) < 0,
    "<=": lambda a, b: _compare(a, b) <= 0,
    ">": lambda a, b: _compare(a, b) > 0,
    ">=": lambda a, b: _compare(a, b) >= 0,
}

_ARITHMETIC: dict[str, Callable[[float, float], float]] = {
    "+": lambda a, b: a + b,
    "-": lambda a, b: a - b,
    "*": lambda a, b: a * b,
    "/": lambda a, b: a / b if b else float("nan"),
    "%": lambda a, b: a % b if b else float("nan"),
}


def _value(node: Any, row: Mapping[str, Any], group: Any) -> Any:
    """One expression, over one row — or over the group behind it.

    *group* is the rows an aggregate reduces, and ``None`` where an aggregate
    would be meaningless (a ``WHERE`` runs before there are groups).
    """
    if node is None:
        return True
    if isinstance(node, ast.ColumnRef):
        names = _name_parts(node.fields)
        return row.get(names[-1]) if names else None
    if isinstance(node, ast.A_Const):
        return _constant(node)
    if isinstance(node, ast.TypeCast):
        return _value(node.arg, row, group)
    if isinstance(node, ast.CoalesceExpr):
        for argument in node.args or ():
            found = _value(argument, row, group)
            if found is not None:
                return found
        return None
    if isinstance(node, ast.MinMaxExpr):
        values = [_value(a, row, group) for a in node.args or ()]
        present = [v for v in values if v is not None]
        if not present:
            return None
        pick = min if node.op == MinMaxOp.IS_LEAST else max
        return pick(present, key=_sortable)
    if isinstance(node, ast.CaseExpr):
        return _case(node, row, group)
    if isinstance(node, ast.NullTest):
        found = _value(node.arg, row, group)
        if node.nulltesttype == NullTestType.IS_NULL:
            return found is None
        return found is not None
    if isinstance(node, ast.BooleanTest):
        return _boolean_test(node, row, group)
    if isinstance(node, ast.BoolExpr):
        return _bool_expr(node, row, group)
    if isinstance(node, ast.A_Expr):
        return _a_expr(node, row, group)
    if isinstance(node, ast.FuncCall):
        return _call(node, row, group)
    raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, type(node).__name__)


def _constant(node: ast.A_Const) -> Any:
    if node.isnull:
        return None
    held = node.val
    if isinstance(held, ast.Integer):
        return held.ival
    if isinstance(held, ast.Float):
        return float(held.fval)
    if isinstance(held, ast.Boolean):
        return held.boolval
    if isinstance(held, ast.String):
        return held.sval
    raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, type(held).__name__)


def _case(node: ast.CaseExpr, row: Mapping[str, Any], group: Any) -> Any:
    subject = _value(node.arg, row, group) if node.arg is not None else None
    for when in node.args or ():
        if not isinstance(when, ast.CaseWhen):
            continue
        if node.arg is not None:
            matched = _compare(subject, _value(when.expr, row, group)) == 0
        else:
            matched = _truthy(_value(when.expr, row, group))
        if matched:
            return _value(when.result, row, group)
    return _value(node.defresult, row, group) if node.defresult is not None else None


def _boolean_test(node: ast.BooleanTest, row: Mapping[str, Any], group: Any) -> bool:
    found = _value(node.arg, row, group)
    tests: dict[BoolTestType, Callable[[Any], bool]] = {
        BoolTestType.IS_TRUE: lambda v: v is True,
        BoolTestType.IS_NOT_TRUE: lambda v: v is not True,
        BoolTestType.IS_FALSE: lambda v: v is False,
        BoolTestType.IS_NOT_FALSE: lambda v: v is not False,
        BoolTestType.IS_UNKNOWN: lambda v: v is None,
        BoolTestType.IS_NOT_UNKNOWN: lambda v: v is not None,
    }
    test = tests.get(node.booltesttype)
    if test is None:
        raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, "BooleanTest")
    return test(found)


def _bool_expr(node: ast.BoolExpr, row: Mapping[str, Any], group: Any) -> Any:
    """``AND``/``OR``/``NOT``, with unknown carried through.

    SQL has three truth values and the third is why this is not Python's
    ``and``. ``NOT unknown`` is unknown rather than true, and an ``AND`` with an
    unknown in it is false only if something else is false — which is what
    decides whether a row with a missing value survives a ``WHERE``.
    """
    values = [_value(a, row, group) for a in node.args or ()]
    if node.boolop == BoolExprType.AND_EXPR:
        if any(v is False or (v is not None and not _truthy(v)) for v in values):
            return False
        return None if any(v is None for v in values) else True
    if node.boolop == BoolExprType.OR_EXPR:
        if any(v is not None and _truthy(v) for v in values):
            return True
        return None if any(v is None for v in values) else False
    if not values:
        return True
    return None if values[0] is None else not _truthy(values[0])


def _a_expr(node: ast.A_Expr, row: Mapping[str, Any], group: Any) -> Any:
    operator = _operator(node)
    left = _value(node.lexpr, row, group) if node.lexpr is not None else None

    # ``IN`` is a list on the right, and ``NOT IN`` is the same node with the
    # operator negated — which is how the grammar says it, not a second kind.
    if node.kind == A_Expr_Kind.AEXPR_IN:
        candidates = [_value(item, row, group) for item in node.rexpr or ()]
        if left is None:
            return None
        found = any(
            candidate is not None and _compare(left, candidate) == 0
            for candidate in candidates
        )
        # No match, but something in the list was unknown: whether it would have
        # matched is unknown too, so the answer is.
        if not found and any(candidate is None for candidate in candidates):
            return None
        return found if operator == "=" else not found

    right = _value(node.rexpr, row, group)
    if operator in ("~~", "~~*"):
        return _like(left, right, insensitive=operator == "~~*")
    if operator in ("!~~", "!~~*"):
        return not _like(left, right, insensitive=operator == "!~~*")
    if operator in _COMPARISONS:
        if left is None or right is None:
            return None
        return _COMPARISONS[operator](left, right)
    if operator in _ARITHMETIC:
        if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
            return None
        return _ARITHMETIC[operator](float(left), float(right))
    raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, operator or "A_Expr")


def _like(value: Any, pattern: Any, *, insensitive: bool) -> bool:
    """``LIKE`` as the grammar means it: ``%`` any run, ``_`` any one."""
    if value is None or pattern is None:
        return False
    text, template = str(value), str(pattern)
    if insensitive:
        text, template = text.lower(), template.lower()
    return _like_match(text, template)


def _like_match(text: str, pattern: str) -> bool:
    """Matched by walking both, so a pattern is never compiled as a regex and
    nothing in it can mean anything but ``%`` and ``_``."""
    memo: dict[tuple[int, int], bool] = {}

    def walk(t: int, p: int) -> bool:
        key = (t, p)
        if key in memo:
            return memo[key]
        if p == len(pattern):
            answer = t == len(text)
        elif pattern[p] == "%":
            answer = walk(t, p + 1) or (t < len(text) and walk(t + 1, p))
        elif t < len(text) and (pattern[p] == "_" or pattern[p] == text[t]):
            answer = walk(t + 1, p + 1)
        else:
            answer = False
        memo[key] = answer
        return answer

    return walk(0, 0)


def _call(node: ast.FuncCall, row: Mapping[str, Any], group: Any) -> Any:
    name = _function_name(node)
    if name in _AGGREGATE_TYPES:
        if group is None:
            raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, name)
        return _aggregate(name, node, group)
    arguments = [_value(a, row, group) for a in node.args or ()]
    return _scalar(name, arguments)


def _aggregate(
    name: str, node: ast.FuncCall, group: Iterable[Mapping[str, Any]]
) -> Any:
    rows = list(group)
    if node.agg_filter is not None:
        # ``FILTER (WHERE …)`` keeps the rows its condition holds for, by the
        # rule a ``WHERE`` keeps them by.
        rows = [row for row in rows if _truthy(_value(node.agg_filter, row, None))]
    if name == "count" and node.agg_star:
        return len(rows)

    argument = (node.args or [None])[0]
    values = [_value(argument, row, None) for row in rows]
    present = [value for value in values if value is not None]
    if node.agg_distinct:
        # Each value once, compared the way ``SELECT DISTINCT`` compares rows.
        present = [row[0] for row in _distinct([(value,) for value in present])]
    if name == "count":
        return len(present)
    if not present:
        return None
    if name == "min":
        return min(present, key=_sortable)
    if name == "max":
        return max(present, key=_sortable)
    numbers = [float(v) for v in present if isinstance(v, (int, float))]
    if not numbers:
        return None
    if name == "sum":
        return sum(numbers)
    return sum(numbers) / len(numbers)


def _scalar(name: str, arguments: list[Any]) -> Any:
    first = arguments[0] if arguments else None
    if name == "now":
        return datetime.now(timezone.utc)
    if first is None and name != "concat":
        return None
    if name == "abs":
        return abs(float(first)) if isinstance(first, (int, float)) else None
    if name == "round":
        if not isinstance(first, (int, float)):
            return None
        digits = arguments[1] if len(arguments) > 1 else 0
        return round(
            float(first), int(digits) if isinstance(digits, (int, float)) else 0
        )
    if name == "length":
        return len(str(first))
    if name == "lower":
        return str(first).lower()
    if name == "upper":
        return str(first).upper()
    if name == "concat":
        return "".join("" if a is None else str(a) for a in arguments)
    if name == "date_trunc":
        return _date_trunc(first, arguments[1] if len(arguments) > 1 else None)
    if name == "extract":
        return _extract(first, arguments[1] if len(arguments) > 1 else None)
    raise QueryError(QueryMessages.UNSUPPORTED_FUNCTION, name)


#: What each bucket keeps of a moment.
_TRUNCATIONS: dict[str, Callable[[datetime], datetime]] = {
    "year": lambda m: m.replace(
        month=1, day=1, hour=0, minute=0, second=0, microsecond=0
    ),
    "quarter": lambda m: m.replace(
        month=((m.month - 1) // 3) * 3 + 1,
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    ),
    "month": lambda m: m.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
    "week": lambda m: (m - _days(m.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    ),
    "day": lambda m: m.replace(hour=0, minute=0, second=0, microsecond=0),
    "hour": lambda m: m.replace(minute=0, second=0, microsecond=0),
}


def _days(count: int):
    from datetime import timedelta

    return timedelta(days=count)


def _date_trunc(bucket: Any, value: Any) -> Any:
    moment = _as_datetime(value)
    truncate = _TRUNCATIONS.get(str(bucket).lower()) if bucket is not None else None
    return truncate(moment) if moment and truncate else None


def _extract(part: Any, value: Any) -> Any:
    moment = _as_datetime(value)
    if moment is None or part is None:
        return None
    field = str(part).lower()
    parts = {
        "year": moment.year,
        "month": moment.month,
        "day": moment.day,
        "hour": moment.hour,
        "minute": moment.minute,
        "dow": (moment.weekday() + 1) % 7,
        "doy": moment.timetuple().tm_yday,
    }
    return parts.get(field)


def _as_datetime(value: Any) -> Optional[datetime]:
    """A UTC moment, from whatever spelling the plug-in sent it in.

    A source's offset spells an instant, not a separate timezone in which to
    bucket it. The query surface groups moments on UTC boundaries.
    """
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        moment = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc)
    return None


def _compare(left: Any, right: Any) -> int:
    """Order two values the way a comparison means, without raising on a pair
    that has no order.

    Like against like: two numbers numerically, two moments in time, anything
    else as the text a reader would see. A pair with no shared footing compares
    as text rather than failing the whole read, because one odd value in one
    row is not a reason to refuse the statement.
    """
    if isinstance(left, bool) or isinstance(right, bool):
        return 0 if bool(left) == bool(right) else 1
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return (float(left) > float(right)) - (float(left) < float(right))
    # The other side may be a SQL literal. Only a typed temporal operand
    # triggers this coercion; two date-looking text values remain text.
    if isinstance(left, (datetime, date)) or isinstance(right, (datetime, date)):
        first, second = _as_datetime(left), _as_datetime(right)
        if first is not None and second is not None:
            return (first > second) - (first < second)
    first_text, second_text = str(left), str(right)
    return (first_text > second_text) - (first_text < second_text)


def _truthy(value: Any) -> bool:
    return value is True or (value is not None and value is not False and value != 0)


def _epoch_ms(value: Any) -> int:
    moment = _as_datetime(value)
    return int(moment.timestamp() * 1000) if moment else 0


def _wire(value: Any, declared: Optional[FieldType] = None) -> Any:
    """One value, in a spelling a client can hold.

    The same spellings the Postgres path answers with, so a widget cannot tell
    the two apart — which is why the *declared* type decides rather than the
    Python one. A plug-in sends a moment as whatever it likes, most often an ISO
    string; a column the endpoint called a date comes back as epoch
    milliseconds either way, because that is the one spelling the widgets take.
    """
    if isinstance(value, (datetime, date)):
        return _epoch_ms(value)
    if declared is FieldType.date and value is not None:
        moment = _as_datetime(value)
        return _epoch_ms(moment) if moment is not None else None
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


# --- a statement over the community's datasets, described without running it --


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


def describe_statement(
    sql: str,
) -> tuple[tuple[StatementColumn, ...], tuple[str, ...]]:
    """What a statement over the community's datasets returns, and which
    datasets it reads — worked out from the tree alone.

    The live path asks the database about any output the registry cannot name.
    A caller with no database to ask — a marketplace listing previewing on
    sample rows — reads the same tree the way this module reads a statement
    over a plug-in's rows: a field is the field the registry declares, and an
    expression is typed by what it is built from.
    """
    from app.services.query.resolve import (
        Sheet,
        _expand_relations,
        _relations,
        _field_named,
        _take_sheets,
    )

    select = _parse(sql)
    # A sheet is not read here, so its columns read as text.
    sheets = {
        key: Sheet.unread(call) for key, (_, call) in _take_sheets(select).items()
    }
    _check_nodes(select)
    _expand_relations(select)
    scope = _relations(select, sheets)
    declared: dict[str, RowColumn] = {}
    for source in scope.values():
        for field_name, spec in source.by_name.items():
            declared.setdefault(field_name, RowColumn(field_name, spec.type))
    columns = _output_columns(select, declared)
    described: list[StatementColumn] = []
    for target, column in zip(select.targetList or (), columns):
        spec = _field_named(scope, target.val)
        aggregate = (
            isinstance(target.val, ast.FuncCall)
            and _function_name(target.val) in _AGGREGATE_TYPES
        )
        described.append(
            StatementColumn(
                name=column.name,
                type=spec.type if spec is not None else column.type,
                options=tuple(spec.options) if spec is not None else (),
                aggregate=aggregate,
            )
        )
    return tuple(described), tuple(sorted({source.name for source in scope.values()}))
