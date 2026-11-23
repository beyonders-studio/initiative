"""Unit tests for the reusable query utility functions.

The statements are compiled and inspected, never run. A field name resolves to
a mapped column or is dropped, and a value is bound as a parameter.
"""

import json
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
)
from sqlmodel import select

from app.db.query import (
    FETCH_ALL_WINDOW,
    apply_filters,
    apply_pagination,
    apply_sorting,
    build_paginated_response,
    clamp_page,
    effective_page_size,
    extract_condition_value,
    iter_leaf_conditions,
    page_has_next,
    paginate_sequence,
    parse_conditions,
    parse_sort_fields,
)
from app.schemas.query import FilterCondition, FilterGroup, FilterOp, SortDir, SortField

_test_metadata = MetaData()
_dummy_table = Table(
    "dummy_items",
    _test_metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(100)),
    Column("priority", String(20)),
    Column("score", Float),
    Column("is_active", Boolean),
    Column("due_at", DateTime(timezone=True)),
    Column("due_on", Date),
)


class _DummyModel:
    """Attribute-access wrapper around the dummy table columns."""

    id = _dummy_table.c.id
    name = _dummy_table.c.name
    priority = _dummy_table.c.priority
    score = _dummy_table.c.score
    is_active = _dummy_table.c.is_active
    due_at = _dummy_table.c.due_at
    due_on = _dummy_table.c.due_on


#: A field name that names no column.
_UNKNOWN = "name); DROP TABLE dummy_items; --"
_NAME_ONLY = {"name": _DummyModel.name}
_WINDOW = "app.db.query.FETCH_ALL_WINDOW"

C = FilterCondition
G = FilterGroup


def _tail(stmt) -> str:
    """The compiled statement after its FROM: the WHERE, ORDER BY and LIMIT."""
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    return sql.split("FROM dummy_items", 1)[1]


# ---------------------------------------------------------------------------
# apply_filters
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("conditions", "allowed", "present", "absent"),
    [
        pytest.param(
            [C(field="name", value="alice")], None, ["name = 'alice'"], [], id="eq"
        ),
        # SA turns NOT(x = y) into x != y, and NOT(x > y) into x <= y.
        pytest.param(
            [C(field="name", value="bob", negate=True)],
            None,
            ["name != 'bob'"],
            [],
            id="negated eq",
        ),
        pytest.param(
            [
                C(
                    field="priority",
                    op=FilterOp.in_,
                    value=["low", "medium"],
                    negate=True,
                )
            ],
            None,
            ["NOT IN", "'low'"],
            [],
            id="negated in",
        ),
        pytest.param(
            [C(field="score", op=FilterOp.gt, value=5, negate=True)],
            None,
            ["score <= 5"],
            [],
            id="negated gt",
        ),
        pytest.param(
            [
                C(field="score", op=FilterOp.gt, value=5),
                C(field="score", op=FilterOp.lte, value=100),
            ],
            None,
            ["score > 5", "score <= 100"],
            [],
            id="comparisons",
        ),
        pytest.param(
            [C(field="priority", op=FilterOp.in_, value=["high", "urgent"])],
            None,
            ["IN", "'high'", "'urgent'"],
            [],
            id="in",
        ),
        pytest.param(
            [C(field="priority", op=FilterOp.in_, value=[])],
            None,
            [],
            ["WHERE"],
            id="empty in is skipped",
        ),
        pytest.param(
            [C(field="name", op=FilterOp.ilike, value="test")],
            None,
            ["LIKE"],
            [],
            id="ilike",
        ),
        pytest.param(
            [C(field="name", op=FilterOp.is_null, value=True)],
            None,
            ["IS NULL"],
            [],
            id="is null",
        ),
        pytest.param(
            [C(field="name", op=FilterOp.is_null, value=False)],
            None,
            ["IS NOT NULL"],
            [],
            id="is not null",
        ),
        pytest.param(
            [C(field=_UNKNOWN, value="x")],
            _NAME_ONLY,
            [],
            ["WHERE", "DROP TABLE"],
            id="unknown field is dropped",
        ),
        pytest.param(
            [C(field="name", value="alice"), C(field="priority", value="high")],
            _NAME_ONLY,
            ["name = 'alice'"],
            ["priority"],
            id="allowlist",
        ),
        pytest.param(
            [
                C(field="name", value="alice"),
                C(field="score", op=FilterOp.gte, value=10),
                C(field="is_active", value=True),
            ],
            None,
            ["name = 'alice'", "score >= 10", "is_active"],
            [],
            id="several",
        ),
        pytest.param([], None, [], ["WHERE"], id="none"),
        # A date filter arrives as a string and binds as a date.
        pytest.param(
            [C(field="due_on", op=FilterOp.in_, value=["2026-06-01", "2026-06-02"])],
            None,
            ["'2026-06-01'"],
            [],
            id="each date of an in list",
        ),
        pytest.param(
            [C(field="due_at", op=FilterOp.is_null, value=True)],
            None,
            ["IS NULL"],
            [],
            id="is null on a date column",
        ),
        # Groups.
        pytest.param(
            [
                G(
                    logic="or",
                    conditions=[
                        C(field="name", value="alice"),
                        C(field="name", value="bob"),
                    ],
                )
            ],
            None,
            ["OR", "'alice'", "'bob'"],
            ["NOT"],
            id="or group",
        ),
        pytest.param(
            [
                G(
                    logic="and",
                    conditions=[
                        C(field="name", value="alice"),
                        C(field="score", op=FilterOp.gt, value=5),
                    ],
                )
            ],
            None,
            ["name = 'alice'", "score > 5"],
            [],
            id="and group",
        ),
        pytest.param(
            [
                G(
                    logic="or",
                    conditions=[
                        C(field="name", value="alice"),
                        C(field="score", op=FilterOp.gt, value=5),
                    ],
                )
            ],
            _NAME_ONLY,
            ["'alice'"],
            ["score"],
            id="group keeps to the allowlist",
        ),
        pytest.param(
            [
                C(field="is_active", value=True),
                G(
                    logic="or",
                    conditions=[
                        C(field="name", value="alice"),
                        C(field="name", value="bob"),
                    ],
                ),
            ],
            None,
            ["is_active", "OR", "'alice'", "'bob'"],
            [],
            id="beside a group",
        ),
        pytest.param(
            [
                G(
                    logic="or",
                    conditions=[
                        C(field="score", op=FilterOp.gt, value=90),
                        C(field="score", op=FilterOp.is_null, value=True),
                    ],
                )
            ],
            None,
            ["OR", "score > 90", "IS NULL"],
            [],
            id="or across operators",
        ),
        pytest.param(
            [
                G(
                    logic="or",
                    conditions=[
                        C(field="unknown1", value="x"),
                        C(field="unknown2", value="y"),
                    ],
                )
            ],
            _NAME_ONLY,
            [],
            ["WHERE"],
            id="empty group is skipped",
        ),
        pytest.param(
            [G(logic="or", conditions=[C(field="name", value="alice")])],
            None,
            ["name = 'alice'"],
            ["OR"],
            id="one-condition group is unwrapped",
        ),
        pytest.param(
            [
                G(
                    logic="or",
                    negate=True,
                    conditions=[
                        C(field="name", value="archived"),
                        C(field="name", value="deleted"),
                    ],
                )
            ],
            None,
            ["NOT", "OR", "'archived'", "'deleted'"],
            [],
            id="negated or group",
        ),
        pytest.param(
            [
                G(
                    logic="and",
                    negate=True,
                    conditions=[
                        C(field="name", value="alice"),
                        C(field="score", op=FilterOp.gt, value=5),
                    ],
                )
            ],
            None,
            ["NOT", "'alice'", "score > 5"],
            [],
            id="negated and group",
        ),
        pytest.param(
            [G(logic="or", negate=True, conditions=[C(field="name", value="alice")])],
            None,
            ["name != 'alice'"],
            [],
            id="negated one-condition group",
        ),
        # Callable handlers in the allowlist.
        pytest.param(
            [C(field="status_category", op=FilterOp.in_, value=["active", "done"])],
            {
                "status_category": lambda op, value: _dummy_table.c.priority.in_(
                    tuple(value)
                )
            },
            ["IN", "'active'", "'done'"],
            [],
            id="handler",
        ),
        pytest.param(
            [C(field="custom", value="alice", negate=True)],
            {"custom": lambda op, value: _dummy_table.c.name == value},
            ["name != 'alice'"],
            [],
            id="negated handler",
        ),
        pytest.param(
            [C(field="custom", value="x")],
            {"custom": lambda op, value: None},
            [],
            ["WHERE"],
            id="handler answering nothing is skipped",
        ),
        pytest.param(
            [
                G(
                    logic="or",
                    conditions=[
                        C(field="name", value="alice"),
                        C(field="high_score", op=FilterOp.gt, value=90),
                    ],
                )
            ],
            {
                "name": _DummyModel.name,
                "high_score": lambda op, value: _dummy_table.c.score > value,
            },
            ["OR", "'alice'", "score > 90"],
            [],
            id="handler in a group",
        ),
        pytest.param(
            [
                C(field="name", value="bob"),
                C(field="min_score", op=FilterOp.gte, value=50),
            ],
            {
                "name": _DummyModel.name,
                "min_score": lambda op, value: _dummy_table.c.score >= value,
            },
            ["name = 'bob'", "score >= 50"],
            [],
            id="handler beside a column",
        ),
    ],
)
def test_apply_filters(conditions, allowed, present, absent):
    tail = _tail(
        apply_filters(
            select(_dummy_table), _DummyModel, conditions, allowed_fields=allowed
        )
    )
    for want in present:
        assert want in tail
    for unwanted in absent:
        assert unwanted not in tail


def test_a_handler_receives_the_conditions_op_and_value():
    received = {}

    def handler(op, value):
        received.update(op=op, value=value)
        return _dummy_table.c.id == 1

    conditions = [C(field="custom", op=FilterOp.in_, value=[10, 20])]
    apply_filters(
        select(_dummy_table),
        _DummyModel,
        conditions,
        allowed_fields={"custom": handler},
    )
    assert received == {"op": FilterOp.in_, "value": [10, 20]}


def test_a_filter_value_is_bound_as_a_parameter():
    """The wrapped ILIKE term is present only as a bound parameter value."""
    cond = C(field="name", op=FilterOp.ilike, value=_UNKNOWN)
    compiled = apply_filters(
        select(_dummy_table), _DummyModel, [cond], allowed_fields=_NAME_ONLY
    ).compile()
    assert "DROP TABLE" not in str(compiled)
    assert f"%{_UNKNOWN}%" in compiled.params.values()


@pytest.mark.parametrize(
    ("field", "op", "value", "bound"),
    [
        pytest.param(
            "due_at",
            FilterOp.gte,
            "2026-06-01T00:00:00+00:00",
            datetime(2026, 6, 1, tzinfo=UTC),
            id="timestamp",
        ),
        # The shape JS toISOString() produces.
        pytest.param(
            "due_at",
            FilterOp.lte,
            "2026-06-30T23:59:59.999Z",
            datetime(2026, 6, 30, 23, 59, 59, 999000, tzinfo=UTC),
            id="z suffix",
        ),
        pytest.param("due_on", FilterOp.eq, "2026-06-01", date(2026, 6, 1), id="date"),
        # A caller windowing a date column sends a full timestamp.
        pytest.param(
            "due_on",
            FilterOp.gte,
            "2026-06-01T12:30:00.000Z",
            date(2026, 6, 1),
            id="date from a timestamp",
        ),
        pytest.param(
            "due_at",
            FilterOp.gte,
            "2026-06-01",
            datetime(2026, 6, 1),
            id="timestamp from a date",
        ),
        # Passed through rather than dropped: ignoring a filter the caller
        # asked for would widen the result set.
        pytest.param("due_at", FilterOp.gte, "whenever", "whenever", id="unparseable"),
        pytest.param(
            "name", FilterOp.eq, "2026-06-01", "2026-06-01", id="not a date column"
        ),
    ],
)
def test_a_date_string_binds_as_a_date(field, op, value, bound):
    """JSON has no date type, and a str binds as VARCHAR even against a
    timestamp column, which Postgres refuses to compare."""
    stmt = apply_filters(
        select(_dummy_table), _DummyModel, [C(field=field, op=op, value=value)]
    )
    bind = list(stmt.whereclause.get_children())[1]
    assert bind.value == bound
    assert type(bind.value) is type(bound)
    if isinstance(bound, datetime):
        assert isinstance(bind.type, DateTime)


# ---------------------------------------------------------------------------
# apply_sorting
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "present", "absent"),
    [
        pytest.param(
            {"sort_by": "name", "sort_dir": "asc"},
            ["ORDER BY dummy_items.name ASC NULLS LAST, dummy_items.id ASC"],
            [],
            id="asc, id breaks ties",
        ),
        pytest.param(
            {"sort_by": "score", "sort_dir": "desc"},
            ["ORDER BY", "DESC"],
            [],
            id="desc",
        ),
        pytest.param(
            {"sort_by": "name,score", "sort_dir": "asc,desc"},
            ["ORDER BY", "name", "score"],
            [],
            id="several",
        ),
        pytest.param(
            {
                "sort_fields": [
                    SortField(field="name", dir=SortDir.asc),
                    SortField(field="score", dir=SortDir.desc),
                ]
            },
            ["ORDER BY", "name", "score"],
            [],
            id="structured",
        ),
        pytest.param(
            {"default_sort": [(_DummyModel.score, "desc"), (_DummyModel.id, "asc")]},
            ["ORDER BY", "score"],
            [],
            id="default",
        ),
        pytest.param(
            {
                "sort_by": "name",
                "sort_dir": "asc",
                "default_sort": [(_DummyModel.score, "desc")],
            },
            ["name"],
            ["score"],
            id="default only without fields",
        ),
        pytest.param(
            {
                "sort_by": _UNKNOWN,
                "sort_dir": "asc",
                "allowed_fields": _NAME_ONLY,
                "default_sort": [(_DummyModel.id, "asc")],
            },
            ["ORDER BY"],
            ["DROP TABLE"],
            id="unknown field falls back to the default",
        ),
        pytest.param(
            {"sort_by": _UNKNOWN, "allowed_fields": _NAME_ONLY},
            [],
            ["ORDER BY", "DROP TABLE"],
            id="unknown field is dropped",
        ),
        # getattr(model, field) resolves an unknown attribute to None.
        pytest.param(
            {"sort_by": _UNKNOWN},
            [],
            ["DROP TABLE"],
            id="unknown field without an allowlist",
        ),
        pytest.param(
            {
                "sort_by": f"name,{_UNKNOWN}",
                "sort_dir": "asc,asc",
                "allowed_fields": _NAME_ONLY,
            },
            ["ORDER BY"],
            ["DROP TABLE"],
            id="known field beside an unknown one",
        ),
        pytest.param({}, [], ["ORDER BY"], id="nothing to sort by"),
    ],
)
def test_apply_sorting(kwargs, present, absent):
    tail = _tail(apply_sorting(select(_dummy_table), _DummyModel, **kwargs))
    for want in present:
        assert want in tail
    for unwanted in absent:
        assert unwanted not in tail


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("page", "page_size", "window", "expected"),
    [
        (1, 20, None, "LIMIT 20 OFFSET 0"),
        (2, 10, None, "LIMIT 10 OFFSET 10"),
        # "Fetch all" is bounded by the window, never an unbounded scan.
        (1, 0, None, f"LIMIT {FETCH_ALL_WINDOW}"),
        (1, -1, None, f"LIMIT {FETCH_ALL_WINDOW}"),
        # Page N of "fetch all" serves window N.
        (3, 0, 7, "LIMIT 7 OFFSET 14"),
        # A positive size never exceeds the window either.
        (1, 50, 7, "LIMIT 7"),
    ],
)
def test_apply_pagination(monkeypatch, page, page_size, window, expected):
    if window:
        monkeypatch.setattr(_WINDOW, window)
    assert expected in _tail(
        apply_pagination(select(_dummy_table), page=page, page_size=page_size)
    )


@pytest.mark.parametrize(
    ("items", "total", "page", "page_size", "window", "has_next", "has_prev"),
    [
        (["a", "b", "c"], 50, 2, 20, None, True, True),
        (["a", "b"], 5, 1, 3, None, True, False),
        (["e"], 5, 2, 4, None, False, True),
        (["a", "b"], 2, 1, 20, None, False, False),
        ([], 0, 1, 20, None, False, False),
        # "Fetch all": one window holds a small set, and a set larger than
        # the window says so rather than truncating silently.
        (["a"], 1, 1, 0, None, False, False),
        (["a", "b"], 5, 1, 0, 2, True, False),
        (["c", "d"], 5, 2, 0, 2, True, True),
        (["e"], 5, 3, 0, 2, False, True),
        (list(range(1000)), 1500, 1, 0, None, True, False),
        (list(range(42)), 42, 1, 0, None, False, False),
    ],
)
def test_build_paginated_response(
    monkeypatch, items, total, page, page_size, window, has_next, has_prev
):
    if window:
        monkeypatch.setattr(_WINDOW, window)
    assert build_paginated_response(
        items=items,
        total_count=total,
        page=page,
        page_size=page_size,
        sort_by="name",
        sort_dir="asc",
    ) == {
        "items": items,
        "total_count": total,
        "page": page,
        "page_size": page_size,
        "has_next": has_next,
        "has_prev": has_prev,
        "sort_by": "name",
        "sort_dir": "asc",
    }


@pytest.mark.parametrize(
    ("page", "page_size", "total", "expected"),
    [
        (2, 10, 50, 2),
        (5, 20, 50, 1),  # three pages: page 5 is out of range
        (3, 20, 50, 3),
        (3, 20, 0, 1),
        (1, 20, 1, 1),
        (1, 20, 20, 1),
        (2, 20, 20, 1),
        # "Fetch all" pages are checked against windows of 10.
        (5, 0, 100, 5),
        (11, 0, 100, 1),
    ],
)
def test_clamp_page(monkeypatch, page, page_size, total, expected):
    if page_size == 0:
        monkeypatch.setattr(_WINDOW, 10)
    assert clamp_page(page, page_size, total) == expected


def test_effective_page_size(monkeypatch):
    monkeypatch.setattr(_WINDOW, 10)
    assert effective_page_size(0) == 10
    assert effective_page_size(-5) == 10
    assert effective_page_size(3) == 3
    assert effective_page_size(50) == 10


@pytest.mark.parametrize(
    ("page", "page_size", "expected"),
    [
        (1, 4, [0, 1, 2, 3]),
        (2, 4, [4, 5, 6, 7]),
        (3, 4, [8, 9]),
        (4, 4, []),
        (1, 0, [0, 1, 2, 3]),
        (2, 0, [4, 5, 6, 7]),
        (3, 0, [8, 9]),
    ],
)
def test_paginate_sequence(monkeypatch, page, page_size, expected):
    monkeypatch.setattr(_WINDOW, 4)
    assert (
        paginate_sequence(list(range(10)), page=page, page_size=page_size) == expected
    )


def test_window_walk_reassembles_complete_set(monkeypatch):
    """The invariant the SPA relies on: concatenating windows until
    page_has_next is false yields exactly the full set, no gaps, no dupes."""
    monkeypatch.setattr(_WINDOW, 3)
    items = list(range(8))
    collected: list[int] = []
    page = 1
    while True:
        collected.extend(paginate_sequence(items, page=page, page_size=0))
        if not page_has_next(page, 0, len(items)):
            break
        page += 1
    assert collected == items
    assert page == 3

    assert page_has_next(1, 3, 5) is True
    assert page_has_next(2, 3, 5) is False
    assert page_has_next(1, 20, 2) is False


# ---------------------------------------------------------------------------
# parse_conditions / parse_sort_fields
# ---------------------------------------------------------------------------


def _many(count: int) -> str:
    return json.dumps([{"field": "f", "value": i} for i in range(count)])


def test_parse_conditions():
    assert parse_conditions(None) == [] == parse_conditions("")
    single, defaulted, negated = parse_conditions(
        '[{"field": "name", "op": "gt", "value": "alice"},'
        ' {"field": "name", "value": "test"},'
        ' {"field": "name", "op": "eq", "value": "x", "negate": true}]'
    )
    assert (single.field, single.op, single.value) == ("name", FilterOp.gt, "alice")
    assert (defaulted.op, defaulted.negate) == (FilterOp.eq, False)
    assert negated.negate is True
    assert len(parse_conditions(_many(50))) == 50

    flat, group, defaulted_group, nested = parse_conditions(
        '[{"field": "priority", "op": "in_", "value": ["high"]},'
        ' {"logic": "or", "conditions": ['
        '  {"field": "start_date", "op": "gte", "value": "2026-01-01"},'
        '  {"field": "due_date", "op": "gte", "value": "2026-01-01"}]},'
        ' {"conditions": [{"field": "a", "value": 1}]},'
        ' {"logic": "or", "conditions": [{"logic": "and", "conditions": ['
        '  {"field": "start_date", "op": "gte", "value": "a"}]}]}]'
    )
    assert isinstance(flat, FilterCondition)
    assert isinstance(group, FilterGroup)
    assert group.logic == "or"
    assert [c.field for c in group.conditions] == ["start_date", "due_date"]
    assert defaulted_group.logic == "and"
    assert isinstance(nested.conditions[0], FilterGroup)


@pytest.mark.parametrize(
    ("raw", "kwargs", "problem"),
    [
        pytest.param("x" * 10_001, {}, "size limit", id="oversized"),
        pytest.param(
            "x" * 101, {"max_length": 100}, "size limit", id="past a set size"
        ),
        pytest.param("{not json}", {}, "not valid JSON", id="not JSON"),
        pytest.param(
            '{"field": "name"}', {}, "must be a JSON array", id="not an array"
        ),
        pytest.param(
            '[{"bad_key": "value"}]',
            {},
            "invalid condition structure",
            id="not a condition",
        ),
        pytest.param(
            '[{"field": "name", "op": "DROP TABLE", "value": "x"}]',
            {},
            "invalid condition structure",
            id="an operator nobody serves",
        ),
        pytest.param(_many(51), {}, "too many conditions", id="too many"),
        pytest.param(
            _many(3),
            {"max_conditions": 2},
            "too many conditions",
            id="past a set count",
        ),
        # The count is of leaves, so conditions inside a group count too.
        pytest.param(
            json.dumps([{"conditions": json.loads(_many(51))}]),
            {},
            "too many conditions",
            id="too many inside a group",
        ),
        pytest.param(
            '[{"conditions": [{"conditions": [{"conditions": [{"field": "a", "value": 1}]}]}]}]',
            {},
            "nested too deeply",
            id="too deep",
        ),
        pytest.param(
            '[{"conditions": [{"conditions": [{"field": "a", "value": 1}]}]}]',
            {"max_depth": 1},
            "nested too deeply",
            id="past a set depth",
        ),
        pytest.param(
            '[{"conditions": [{"bad_key": "value"}]}]',
            {},
            "invalid condition structure",
            id="not a condition inside a group",
        ),
    ],
)
def test_a_conditions_payload_is_refused(raw, kwargs, problem):
    """Each refusal names what the payload was instead."""
    with pytest.raises(ValueError, match=problem):
        parse_conditions(raw, **kwargs)


def test_parse_sort_fields():
    assert parse_sort_fields(None) == [] == parse_sort_fields("")
    first, second = parse_sort_fields(
        '[{"field": "date_group", "dir": "desc"}, {"field": "title"}]'
    )
    assert (first.field, first.dir) == ("date_group", SortDir.desc)
    assert (second.field, second.dir) == ("title", SortDir.asc)
    assert (
        len(parse_sort_fields(json.dumps([{"field": f"f{i}"} for i in range(10)])))
        == 10
    )


@pytest.mark.parametrize(
    ("raw", "kwargs", "problem"),
    [
        pytest.param("x" * 10_001, {}, "size limit", id="oversized"),
        pytest.param("{not json}", {}, "not valid JSON", id="not JSON"),
        pytest.param(
            '{"field": "name"}', {}, "must be a JSON array", id="not an array"
        ),
        pytest.param(
            '[{"bad_key": "value"}]',
            {},
            "invalid sort field structure",
            id="not a sort field",
        ),
        pytest.param(
            '[{"field": "name", "dir": "RANDOM"}]',
            {},
            "invalid sort field structure",
            id="a direction that is not one",
        ),
        pytest.param(
            json.dumps([{"field": f"f{i}"} for i in range(11)]),
            {},
            "too many sort fields",
            id="too many",
        ),
        pytest.param(
            json.dumps([{"field": f"f{i}"} for i in range(3)]),
            {"max_fields": 2},
            "too many sort fields",
            id="past a set count",
        ),
    ],
)
def test_a_sort_payload_is_refused(raw, kwargs, problem):
    with pytest.raises(ValueError, match=problem):
        parse_sort_fields(raw, **kwargs)


# ---------------------------------------------------------------------------
# extract_condition_value / iter_leaf_conditions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("conditions", "field", "expected"),
    [
        (
            [
                C(field="status", value="active"),
                C(field="priority", op=FilterOp.in_, value=["high"]),
            ],
            "priority",
            ["high"],
        ),
        (
            [C(field="name", value="first"), C(field="name", value="second")],
            "name",
            "first",
        ),
        ([C(field="name", value="test")], "missing", None),
        ([], "anything", None),
        # A grouped field doesn't hold for every row, so it is not read as a
        # narrowing of the result set.
        (
            [G(logic="or", conditions=[C(field="project_id", value=7)])],
            "project_id",
            None,
        ),
        (
            [G(conditions=[C(field="a", value=1)]), C(field="project_id", value=7)],
            "project_id",
            7,
        ),
    ],
)
def test_extract_condition_value(conditions, field, expected):
    assert extract_condition_value(conditions, field) == expected


def test_iter_leaf_conditions():
    conditions = [
        C(field="a", value=1),
        G(
            logic="or",
            conditions=[C(field="b", value=2), G(conditions=[C(field="c", value=3)])],
        ),
    ]
    assert [c.field for c in iter_leaf_conditions(conditions)] == ["a", "b", "c"]
    assert list(iter_leaf_conditions([])) == []
