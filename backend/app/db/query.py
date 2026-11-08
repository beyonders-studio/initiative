"""Reusable query utilities for filtering, sorting, and pagination.

Provides composable functions that transform SQLAlchemy Select statements:
- parse_conditions: safely parses a JSON string into a FilterCondition/FilterGroup list
- apply_filters: adds WHERE clauses from FilterCondition/FilterGroup lists
- apply_sorting: adds ORDER BY clauses from SortField list or comma-separated strings
- apply_pagination: adds OFFSET/LIMIT
- paginated_query: executes count + data queries, clamps page, returns (items, total, page)
- ids_in: ``column = ANY(:ids)`` with the ids bound as one array
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from datetime import date, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Select, and_, any_, asc, bindparam, desc, not_, or_
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel.ext.asyncio.session import AsyncSession

from app.schemas.query import FilterCondition, FilterGroup, FilterOp, SortDir, SortField

# Hard limits to prevent abuse via oversized payloads.
_MAX_CONDITIONS = 50
_MAX_SORT_FIELDS = 10
_MAX_RAW_LENGTH = 10_000
# How deeply groups may nest. A group counts as one level, so the default
# admits ``or_(and_(a, b), and_(c, d))`` — the shape a two-field date window
# needs — without letting a payload nest arbitrarily.
_MAX_GROUP_DEPTH = 3


def iter_leaf_conditions(
    conditions: list[FilterCondition | FilterGroup],
) -> Iterator[FilterCondition]:
    """Yield every :class:`FilterCondition` in *conditions*, groups included.

    For callers that need to see each leaf wherever it sits (loading the
    property definitions a filter references, counting against a limit).
    Callers that read a value to *narrow* a query must not use this — see
    :func:`extract_condition_value`.
    """
    for cond in conditions:
        if isinstance(cond, FilterGroup):
            yield from iter_leaf_conditions(cond.conditions)
        else:
            yield cond


def _parse_condition_item(item: Any) -> FilterCondition | FilterGroup:
    """Build a condition or group from one raw JSON item.

    A ``conditions`` key marks a group; anything else is a leaf comparison.
    """
    if not isinstance(item, dict):
        raise TypeError("condition must be an object")
    if "conditions" in item:
        return FilterGroup(**item)
    return FilterCondition(**item)


def _check_group_depth(
    conditions: list[FilterCondition | FilterGroup],
    max_depth: int,
    depth: int = 1,
) -> None:
    for cond in conditions:
        if isinstance(cond, FilterGroup):
            if depth >= max_depth:
                raise ValueError(f"conditions nested too deeply (max {max_depth})")
            _check_group_depth(cond.conditions, max_depth, depth + 1)


def parse_conditions(
    raw: str | None,
    *,
    max_conditions: int = _MAX_CONDITIONS,
    max_length: int = _MAX_RAW_LENGTH,
    max_depth: int = _MAX_GROUP_DEPTH,
) -> list[FilterCondition | FilterGroup]:
    """Safely parse a JSON-encoded list of filter conditions.

    Designed for use with query parameters that carry structured filters as a
    JSON string.  Applies size and count limits before parsing the payload.

    Items are flat :class:`FilterCondition` comparisons (implicitly AND-ed) or
    :class:`FilterGroup` objects for explicit AND/OR logic, which
    :func:`apply_filters` resolves recursively.  A group is any item carrying a
    ``conditions`` key::

        [{"logic": "or", "conditions": [
            {"field": "start_date", "op": "gte", "value": "..."},
            {"field": "due_date", "op": "gte", "value": "..."}]}]

    Returns an empty list when *raw* is ``None`` or empty.

    Raises :class:`ValueError` on any validation failure — callers should catch
    this and convert to an appropriate HTTP error.
    """
    if not raw:
        return []

    if len(raw) > max_length:
        raise ValueError("conditions payload exceeds size limit")

    try:
        items = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("conditions is not valid JSON") from exc

    if not isinstance(items, list):
        raise ValueError("conditions must be a JSON array")

    if len(items) > max_conditions:
        raise ValueError(f"too many conditions (max {max_conditions})")

    try:
        parsed = [_parse_condition_item(item) for item in items]
    except (ValidationError, TypeError) as exc:
        raise ValueError("invalid condition structure") from exc

    # Depth and leaf count are checked after parsing: the payload limit above
    # only bounds the top level, and a group's leaves cost the same to compile
    # as top-level ones.
    _check_group_depth(parsed, max_depth)

    leaf_count = sum(1 for _ in iter_leaf_conditions(parsed))
    if leaf_count > max_conditions:
        raise ValueError(f"too many conditions (max {max_conditions})")

    return parsed


def parse_sort_fields(
    raw: str | None,
    *,
    max_fields: int = _MAX_SORT_FIELDS,
    max_length: int = _MAX_RAW_LENGTH,
) -> list[SortField]:
    """Safely parse a JSON-encoded list of sort fields.

    Mirrors :func:`parse_conditions` with the same security hardening.
    Returns an empty list when *raw* is ``None`` or empty.

    Raises :class:`ValueError` on any validation failure.
    """
    if not raw:
        return []

    if len(raw) > max_length:
        raise ValueError("sort fields payload exceeds size limit")

    try:
        items = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("sorting is not valid JSON") from exc

    if not isinstance(items, list):
        raise ValueError("sorting must be a JSON array")

    if len(items) > max_fields:
        raise ValueError(f"too many sort fields (max {max_fields})")

    try:
        return [SortField(**item) for item in items]
    except (ValidationError, TypeError) as exc:
        raise ValueError("invalid sort field structure") from exc


def extract_condition_value(
    conditions: list[FilterCondition | FilterGroup],
    field: str,
) -> Any:
    """Return the ``value`` for the first top-level condition matching *field*,
    or ``None``.

    Deliberately does not descend into groups: callers use the returned value as
    a guaranteed narrowing of the result set (which projects to check access on,
    which initiatives to query), and only a top-level condition is AND-ed into
    every row. A field inside an ``or`` group holds for some rows, not all.
    """
    for cond in conditions:
        if isinstance(cond, FilterGroup):
            continue
        if cond.field == field:
            return cond.value
    return None


def apply_filters(
    statement: Select,
    model: Any,
    conditions: list[FilterCondition | FilterGroup],
    allowed_fields: dict[str, Any] | None = None,
    allowed_ops: dict[str, frozenset[FilterOp]] | None = None,
) -> Select:
    """Apply filter conditions to a Select statement.

    ``conditions`` can contain flat :class:`FilterCondition` items (implicitly
    AND-ed) or :class:`FilterGroup` items for explicit AND/OR logic.

    Both :class:`FilterCondition` and :class:`FilterGroup` support a ``negate``
    flag that wraps the resulting clause in ``NOT(...)``.

    ``allowed_fields`` maps field names to SQLAlchemy column expressions **or
    callables**.  A callable value receives ``(op, value)`` and must return a
    SA clause element (or *None* to skip).  Negation is still handled
    uniformly by ``_resolve_condition``.

    If *None*, uses ``getattr(model, field)`` directly.
    Unknown fields are silently skipped (defense in depth).

    ``allowed_ops`` maps a field name to the operators it accepts. A condition
    using any other operator raises :class:`ValueError`, so every condition a
    caller sends is either applied or reported back. Omitting the map keeps the
    historical behaviour of accepting whatever operator arrives.
    """
    check_ops(conditions, allowed_ops)
    for cond in conditions:
        clause = _resolve_condition(cond, model, allowed_fields)
        if clause is not None:
            statement = statement.where(clause)

    return statement


def check_ops(
    conditions: list[FilterCondition | FilterGroup],
    allowed_ops: dict[str, frozenset[FilterOp]] | None,
) -> None:
    """Refuse an operator a field does not accept, groups included.

    Public so a caller can run it at parse time, alongside the payload checks,
    and answer with the same 400 every other malformed filter gets — reaching
    :func:`apply_filters` with a bad operator would surface as a server error
    from deep inside query construction instead.
    """
    if allowed_ops is None:
        return
    for cond in iter_leaf_conditions(conditions):
        permitted = allowed_ops.get(cond.field)
        # An unknown field is still silently skipped downstream; only a known
        # field with an operator it does not accept is an error.
        if permitted is not None and cond.op not in permitted:
            raise ValueError(
                f"field '{cond.field}' does not support operator '{cond.op.value}'"
            )


def _resolve_condition(
    cond: FilterCondition | FilterGroup,
    model: Any,
    allowed_fields: dict[str, Any] | None,
):
    """Recursively resolve a condition or group into a SA clause element."""
    if isinstance(cond, FilterGroup):
        return _resolve_group(cond, model, allowed_fields)

    # Leaf FilterCondition
    if allowed_fields is not None:
        col_or_handler = allowed_fields.get(cond.field)
    else:
        col_or_handler = getattr(model, cond.field, None)

    if col_or_handler is None:
        return None

    if callable(col_or_handler):
        clause = col_or_handler(cond.op, cond.value)
    else:
        clause = _build_filter_clause(col_or_handler, cond.op, cond.value)

    if clause is None:
        return None

    return not_(clause) if cond.negate else clause


def _resolve_group(
    group: FilterGroup,
    model: Any,
    allowed_fields: dict[str, Any] | None,
):
    """Resolve a FilterGroup into a SA and_()/or_() expression, optionally negated."""
    clauses = []
    for cond in group.conditions:
        clause = _resolve_condition(cond, model, allowed_fields)
        if clause is not None:
            clauses.append(clause)

    if not clauses:
        return None

    if len(clauses) == 1:
        combined = clauses[0]
    elif group.logic == "or":
        combined = or_(*clauses)
    else:
        combined = and_(*clauses)

    return not_(combined) if group.negate else combined


def _column_python_type(col: Any) -> type | None:
    """The Python type *col* stores, or ``None`` if it doesn't declare one."""
    try:
        return col.type.python_type
    except (AttributeError, NotImplementedError):
        return None


def _coerce_value(col: Any, value: Any) -> Any:
    """Parse an ISO-8601 string into the date/datetime *col* expects.

    Conditions arrive as JSON, which has no date type, so a caller can only
    send a string. SQLAlchemy binds a Python ``str`` as VARCHAR even when it is
    compared against a timestamp column, which Postgres then refuses to compare
    — so the parse has to happen here.

    Anything that isn't an ISO string for a date/datetime column is passed
    through untouched: a value this can't read is one the caller shouldn't
    quietly have filtered away.
    """
    py_type = _column_python_type(col)
    if py_type not in (datetime, date) or not isinstance(value, str):
        return value
    try:
        return py_type.fromisoformat(value)
    except ValueError:
        pass
    if py_type is date:
        # A date column narrowed with a full timestamp — the shape JS
        # toISOString() produces, which date.fromisoformat() won't read. The
        # caller means the calendar day, so take it.
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            pass
    return value


def _build_filter_clause(col: Any, op: FilterOp, value: Any):
    """Return a single WHERE clause for *col* with the given operator.

    Negation is handled by the caller via ``FilterCondition.negate``,
    not by separate operators.
    """
    if op not in (FilterOp.is_null, FilterOp.ilike):
        value = (
            [_coerce_value(col, v) for v in value]
            if op == FilterOp.in_ and isinstance(value, (list, tuple))
            else _coerce_value(col, value)
        )

    if op == FilterOp.eq:
        return col == value
    if op == FilterOp.lt:
        return col < value
    if op == FilterOp.lte:
        return col <= value
    if op == FilterOp.gt:
        return col > value
    if op == FilterOp.gte:
        return col >= value
    if op == FilterOp.in_:
        if not value:
            return None
        return col.in_(tuple(value) if not isinstance(value, tuple) else value)
    if op == FilterOp.ilike:
        return col.ilike(f"%{value}%")
    if op == FilterOp.is_null:
        return col.is_(None) if value else col.is_not(None)
    return None


def apply_sorting(
    statement: Select,
    model: Any,
    sort_fields: list[SortField] | None = None,
    allowed_fields: dict[str, Any] | None = None,
    default_sort: list[tuple[Any, str]] | None = None,
    *,
    sort_by: str | None = None,
    sort_dir: str | None = None,
) -> Select:
    """Apply ORDER BY clauses to a Select statement.

    Accepts either structured ``sort_fields`` or comma-separated ``sort_by``/``sort_dir``
    strings (the current endpoint convention). When both are provided, ``sort_fields`` wins.

    ``allowed_fields`` maps field names to SA column expressions. If *None*, uses
    ``getattr(model, field)`` directly.

    ``default_sort`` is applied when no valid sort fields are found.
    """
    fields_to_apply = _resolve_sort_fields(sort_fields, sort_by, sort_dir)

    has_valid = False
    for sf in fields_to_apply:
        if allowed_fields is not None:
            col = allowed_fields.get(sf.field)
        else:
            col = getattr(model, sf.field, None)

        if col is None:
            continue

        order = desc(col) if sf.dir == SortDir.desc else asc(col)
        statement = statement.order_by(order.nulls_last())
        has_valid = True

    if not has_valid and default_sort:
        for col, direction in default_sort:
            order = desc(col) if direction == "desc" else asc(col)
            statement = statement.order_by(order)
        return statement

    if has_valid:
        # Add model PK as tiebreaker if model has an 'id' attribute
        pk = getattr(model, "id", None)
        if pk is not None:
            statement = statement.order_by(asc(pk))

    return statement


def _resolve_sort_fields(
    sort_fields: list[SortField] | None,
    sort_by: str | None,
    sort_dir: str | None,
) -> list[SortField]:
    """Convert comma-separated sort_by/sort_dir into SortField list, or use sort_fields."""
    if sort_fields:
        return sort_fields

    if not sort_by:
        return []

    fields = [f.strip() for f in sort_by.split(",") if f.strip()]
    dirs = [d.strip() for d in (sort_dir or "").split(",")]

    result = []
    for i, field_name in enumerate(fields):
        direction = dirs[i] if i < len(dirs) else "asc"
        try:
            dir_enum = SortDir(direction)
        except ValueError:
            dir_enum = SortDir.asc
        result.append(SortField(field=field_name, dir=dir_enum))

    return result


# Server-side window applied to a ``page_size<=0`` ("give me everything") list
# request. Deliberately a constant, not a setting: clients retrieve arbitrarily
# large sets by walking ``page=1,2,...`` until ``has_next`` is false, so nothing
# is unreachable through this bound and there is nothing for an operator to
# tune — it only keeps any single response's row count finite.
FETCH_ALL_WINDOW = 1000

# How many ids one request may pass to an ``id``-filtered list endpoint. Matches
# the ``page_size`` ceiling those endpoints declare, since a longer id list can
# never yield more rows than a single page returns anyway.
MAX_ID_FILTER_VALUES = 100


def effective_page_size(page_size: int) -> int:
    """The row window a request actually gets for its requested ``page_size``.

    ``page_size<=0`` resolves to :data:`FETCH_ALL_WINDOW`; a positive
    ``page_size`` is clamped to the same bound as defense in depth (endpoints
    also validate with ``le=`` at the parameter layer, but the ceiling must not
    depend on every endpoint remembering to declare it).
    """
    return FETCH_ALL_WINDOW if page_size <= 0 else min(page_size, FETCH_ALL_WINDOW)


def apply_pagination(
    statement: Select,
    page: int = 1,
    page_size: int = 20,
) -> Select:
    """Apply OFFSET/LIMIT.

    ``page_size<=0`` means "everything, in server-window-sized pages": the
    response is bounded by :data:`FETCH_ALL_WINDOW`, and ``page``
    selects which window, so a caller can walk ``page=1,2,...`` until
    ``has_next`` is false and retrieve the complete set — a single request can
    never dump an unbounded table, but no result is unreachable either.
    """
    eff = effective_page_size(page_size)
    return statement.offset((max(page, 1) - 1) * eff).limit(eff)


def paginate_sequence(items: list, page: int = 1, page_size: int = 20) -> list:
    """Slice an in-memory result list the same way :func:`apply_pagination`
    windows a query — the single slicing rule for endpoints that must build
    their result in Python (cross-guild merges, post-query permission
    filtering) before paginating."""
    eff = effective_page_size(page_size)
    start = (max(page, 1) - 1) * eff
    return items[start : start + eff]


def clamp_page(page: int, page_size: int, total_count: int) -> int:
    """Reset page to 1 if it overshoots the available results.

    This handles the case where filters/sort changed and the current page
    no longer exists (e.g. user was on page 5, but new filters only yield 2 pages).
    """
    if total_count == 0:
        return 1
    import math

    total_pages = math.ceil(total_count / effective_page_size(page_size))
    if page > total_pages:
        return 1
    return max(page, 1)


async def paginated_query(
    session: AsyncSession,
    data_stmt: Select,
    count_stmt: Select,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list, int, int]:
    """Execute count + data queries with automatic page clamping.

    Returns ``(items, total_count, actual_page)`` where *actual_page* may
    differ from the requested *page* if it overshot the result set.
    """
    total_count = (await session.exec(count_stmt)).one()

    page = clamp_page(page, page_size, total_count)

    data_stmt = apply_pagination(data_stmt, page, page_size)
    result = await session.exec(data_stmt)
    items = list(result.all())

    return items, total_count, page


def page_has_next(page: int, page_size: int, total_count: int) -> bool:
    """Whether rows remain beyond the given window.

    The single truth for ``has_next`` across DB-windowed and in-memory-sliced
    endpoints, including the ``page_size<=0`` cap-window pages — so a client
    can always walk ``page=1,2,...`` until this reports False and know it has
    the complete set.
    """
    return max(page, 1) * effective_page_size(page_size) < total_count


def build_paginated_response(
    items: list,
    total_count: int,
    page: int,
    page_size: int,
    **extra: Any,
) -> dict:
    """Build a dict suitable for unpacking into a ``PageMeta`` response model.

    Computes ``has_next`` and ``has_prev`` automatically from the inputs.
    ``page_size<=0`` responses window through the server cap, so
    ``page`` is echoed as requested and ``has_next`` tells the caller whether
    another window remains — truncation is always visible, never silent.
    """
    page = max(page, 1)
    return {
        "items": items,
        "total_count": total_count,
        "page": page,
        "page_size": page_size,
        "has_next": page_has_next(page, page_size, total_count),
        "has_prev": page > 1,
        **extra,
    }


def ids_in(column: Any, ids: Iterable[Any]) -> Any:
    """``column = ANY(:ids)`` — one bound array of the column's type, however
    many ids there are.

    For id sets that grow with the data (a whole roster, a subtree): ``in_``
    binds one parameter per value, and a statement carries at most 32,767.
    """
    return column == any_(bindparam(None, list(ids), type_=ARRAY(column.type)))
