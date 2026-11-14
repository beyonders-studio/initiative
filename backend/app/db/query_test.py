"""Unit tests for the reusable query utility functions."""

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
    apply_filters,
    apply_pagination,
    apply_sorting,
    build_paginated_response,
    clamp_page,
    extract_condition_value,
    iter_leaf_conditions,
    parse_conditions,
    parse_sort_fields,
)
from app.schemas.query import FilterCondition, FilterGroup, FilterOp, SortDir, SortField

# ---------------------------------------------------------------------------
# Dummy table for testing (not persisted — we only inspect generated SQL)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# apply_filters
# ---------------------------------------------------------------------------


class TestApplyFilters:
    """Tests for apply_filters."""

    def test_eq_filter(self):
        stmt = select(_dummy_table)
        conditions = [FilterCondition(field="name", op=FilterOp.eq, value="alice")]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "name = 'alice'" in sql

    def test_negate_eq(self):
        """negate=True on eq negates the comparison."""
        stmt = select(_dummy_table)
        conditions = [
            FilterCondition(field="name", op=FilterOp.eq, value="bob", negate=True)
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        # SA optimizes NOT(x = y) into x != y
        assert "name != 'bob'" in sql

    def test_negate_in(self):
        """negate=True on in negates the IN clause."""
        stmt = select(_dummy_table)
        conditions = [
            FilterCondition(
                field="priority", op=FilterOp.in_, value=["low", "medium"], negate=True
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True})).upper()
        # SA may render as NOT IN or NOT (... IN ...)
        assert "NOT" in sql or "NOT IN" in sql
        assert "'LOW'" in sql

    def test_negate_gt(self):
        """negate=True on gt negates to <= (SA optimizes)."""
        stmt = select(_dummy_table)
        conditions = [
            FilterCondition(field="score", op=FilterOp.gt, value=5, negate=True)
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        # SA optimizes NOT(score > 5) into score <= 5
        assert "score <= 5" in sql

    def test_negate_false_is_normal(self):
        """negate=False (default) behaves like a normal filter."""
        stmt = select(_dummy_table)
        conditions = [
            FilterCondition(field="name", op=FilterOp.eq, value="alice", negate=False)
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "name = 'alice'" in sql

    def test_lt_lte_gt_gte_filters(self):
        stmt = select(_dummy_table)
        conditions = [
            FilterCondition(field="score", op=FilterOp.gt, value=5),
            FilterCondition(field="score", op=FilterOp.lte, value=100),
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "score > 5" in sql
        assert "score <= 100" in sql

    def test_in_filter(self):
        stmt = select(_dummy_table)
        conditions = [
            FilterCondition(field="priority", op=FilterOp.in_, value=["high", "urgent"])
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "IN" in sql
        assert "'high'" in sql
        assert "'urgent'" in sql

    def test_in_filter_empty_list_skipped(self):
        """An in_ filter with an empty list should produce no WHERE clause."""
        stmt = select(_dummy_table)
        conditions = [FilterCondition(field="priority", op=FilterOp.in_, value=[])]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "WHERE" not in sql

    def test_ilike_filter(self):
        stmt = select(_dummy_table)
        conditions = [FilterCondition(field="name", op=FilterOp.ilike, value="test")]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True})).lower()
        assert "ilike" in sql or "like" in sql

    def test_is_null_true(self):
        stmt = select(_dummy_table)
        conditions = [FilterCondition(field="name", op=FilterOp.is_null, value=True)]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "IS NULL" in sql.upper()

    def test_is_null_false(self):
        stmt = select(_dummy_table)
        conditions = [FilterCondition(field="name", op=FilterOp.is_null, value=False)]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "IS NOT NULL" in sql.upper()

    def test_unknown_field_skipped(self):
        """Fields not in allowed_fields should be silently ignored."""
        stmt = select(_dummy_table)
        conditions = [FilterCondition(field="nonexistent", op=FilterOp.eq, value="x")]
        allowed = {"name": _DummyModel.name}
        result = apply_filters(stmt, _DummyModel, conditions, allowed_fields=allowed)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "WHERE" not in sql

    def test_allowed_fields_whitelist(self):
        """Only fields in the whitelist should be applied."""
        stmt = select(_dummy_table)
        conditions = [
            FilterCondition(field="name", op=FilterOp.eq, value="alice"),
            FilterCondition(field="priority", op=FilterOp.eq, value="high"),
        ]
        allowed = {"name": _DummyModel.name}  # priority not allowed
        result = apply_filters(stmt, _DummyModel, conditions, allowed_fields=allowed)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "name = 'alice'" in sql
        # priority should appear in SELECT but not in WHERE
        where_clause = sql.split("WHERE", 1)[1] if "WHERE" in sql else ""
        assert "priority" not in where_clause

    def test_multiple_conditions(self):
        stmt = select(_dummy_table)
        conditions = [
            FilterCondition(field="name", op=FilterOp.eq, value="alice"),
            FilterCondition(field="score", op=FilterOp.gte, value=10),
            FilterCondition(field="is_active", op=FilterOp.eq, value=True),
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "name" in sql
        assert "score" in sql
        assert "is_active" in sql

    def test_no_conditions_returns_original(self):
        stmt = select(_dummy_table)
        result = apply_filters(stmt, _DummyModel, [])
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "WHERE" not in sql


# ---------------------------------------------------------------------------
# FilterGroup (and / or)
# ---------------------------------------------------------------------------


class TestFilterGroup:
    """Tests for AND/OR grouping via FilterGroup."""

    def test_or_same_field(self):
        """OR two values for the same field: name = 'alice' OR name = 'bob'."""
        stmt = select(_dummy_table)
        conditions = [
            FilterGroup(
                logic="or",
                conditions=[
                    FilterCondition(field="name", op=FilterOp.eq, value="alice"),
                    FilterCondition(field="name", op=FilterOp.eq, value="bob"),
                ],
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "OR" in sql
        assert "'alice'" in sql
        assert "'bob'" in sql

    def test_and_group(self):
        """Explicit AND group: name = 'alice' AND score > 5."""
        stmt = select(_dummy_table)
        conditions = [
            FilterGroup(
                logic="and",
                conditions=[
                    FilterCondition(field="name", op=FilterOp.eq, value="alice"),
                    FilterCondition(field="score", op=FilterOp.gt, value=5),
                ],
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "name = 'alice'" in sql
        assert "score > 5" in sql

    def test_or_with_allowed_fields(self):
        """OR group respects allowed_fields whitelist."""
        stmt = select(_dummy_table)
        allowed = {"name": _DummyModel.name}
        conditions = [
            FilterGroup(
                logic="or",
                conditions=[
                    FilterCondition(field="name", op=FilterOp.eq, value="alice"),
                    FilterCondition(
                        field="score", op=FilterOp.gt, value=5
                    ),  # not allowed
                ],
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions, allowed_fields=allowed)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        # Only name should be in the WHERE clause, score is filtered out
        assert "'alice'" in sql
        where_clause = sql.split("WHERE", 1)[1] if "WHERE" in sql else ""
        assert "score" not in where_clause

    def test_nested_groups(self):
        """Nested: is_active = true AND (name = 'alice' OR name = 'bob')."""
        stmt = select(_dummy_table)
        conditions = [
            FilterCondition(field="is_active", op=FilterOp.eq, value=True),
            FilterGroup(
                logic="or",
                conditions=[
                    FilterCondition(field="name", op=FilterOp.eq, value="alice"),
                    FilterCondition(field="name", op=FilterOp.eq, value="bob"),
                ],
            ),
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "is_active" in sql
        assert "OR" in sql
        assert "'alice'" in sql
        assert "'bob'" in sql

    def test_or_three_values(self):
        """OR across three values for the same field."""
        stmt = select(_dummy_table)
        conditions = [
            FilterGroup(
                logic="or",
                conditions=[
                    FilterCondition(field="priority", op=FilterOp.eq, value="low"),
                    FilterCondition(field="priority", op=FilterOp.eq, value="medium"),
                    FilterCondition(field="priority", op=FilterOp.eq, value="high"),
                ],
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "OR" in sql
        assert "'low'" in sql
        assert "'medium'" in sql
        assert "'high'" in sql

    def test_or_different_ops(self):
        """OR with different operators: score > 90 OR score IS NULL."""
        stmt = select(_dummy_table)
        conditions = [
            FilterGroup(
                logic="or",
                conditions=[
                    FilterCondition(field="score", op=FilterOp.gt, value=90),
                    FilterCondition(field="score", op=FilterOp.is_null, value=True),
                ],
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True})).upper()
        assert "OR" in sql
        assert "SCORE > 90" in sql
        assert "IS NULL" in sql

    def test_empty_group_skipped(self):
        """A group with no valid conditions should not add a WHERE clause."""
        stmt = select(_dummy_table)
        allowed = {"name": _DummyModel.name}
        conditions = [
            FilterGroup(
                logic="or",
                conditions=[
                    FilterCondition(field="unknown1", op=FilterOp.eq, value="x"),
                    FilterCondition(field="unknown2", op=FilterOp.eq, value="y"),
                ],
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions, allowed_fields=allowed)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "WHERE" not in sql

    def test_single_condition_group_unwrapped(self):
        """A group with one valid condition should not wrap in AND/OR."""
        stmt = select(_dummy_table)
        conditions = [
            FilterGroup(
                logic="or",
                conditions=[
                    FilterCondition(field="name", op=FilterOp.eq, value="alice"),
                ],
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "name = 'alice'" in sql
        assert "OR" not in sql

    def test_negate_or_group(self):
        """NOT (status = 'archived' OR status = 'deleted')."""
        stmt = select(_dummy_table)
        conditions = [
            FilterGroup(
                logic="or",
                negate=True,
                conditions=[
                    FilterCondition(field="name", op=FilterOp.eq, value="archived"),
                    FilterCondition(field="name", op=FilterOp.eq, value="deleted"),
                ],
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True})).upper()
        assert "NOT" in sql
        assert "OR" in sql
        assert "'ARCHIVED'" in sql
        assert "'DELETED'" in sql

    def test_negate_and_group(self):
        """NOT (name = 'alice' AND score > 5) — negate an AND group."""
        stmt = select(_dummy_table)
        conditions = [
            FilterGroup(
                logic="and",
                negate=True,
                conditions=[
                    FilterCondition(field="name", op=FilterOp.eq, value="alice"),
                    FilterCondition(field="score", op=FilterOp.gt, value=5),
                ],
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True})).upper()
        assert "NOT" in sql
        assert "'ALICE'" in sql
        assert "SCORE > 5" in sql

    def test_negate_single_condition_group(self):
        """NOT (name = 'alice') via a negated group with one condition."""
        stmt = select(_dummy_table)
        conditions = [
            FilterGroup(
                logic="or",
                negate=True,
                conditions=[
                    FilterCondition(field="name", op=FilterOp.eq, value="alice"),
                ],
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        # SA optimizes NOT(name = 'alice') into name != 'alice'
        assert "name != 'alice'" in sql

    def test_negate_false_group_is_normal(self):
        """negate=False (default) on a group behaves normally."""
        stmt = select(_dummy_table)
        conditions = [
            FilterGroup(
                logic="or",
                negate=False,
                conditions=[
                    FilterCondition(field="name", op=FilterOp.eq, value="alice"),
                    FilterCondition(field="name", op=FilterOp.eq, value="bob"),
                ],
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "OR" in sql
        assert "NOT" not in sql.upper()


# ---------------------------------------------------------------------------
# Callable filter handlers
# ---------------------------------------------------------------------------


class TestCallableFilterHandler:
    """Tests for callable handler support in allowed_fields."""

    def test_callable_handler_basic(self):
        """A callable handler returning an IN clause is applied."""

        def status_handler(op, value):
            return _dummy_table.c.priority.in_(tuple(value))

        stmt = select(_dummy_table)
        conditions = [
            FilterCondition(
                field="status_category", op=FilterOp.in_, value=["active", "done"]
            )
        ]
        allowed = {"status_category": status_handler}
        result = apply_filters(stmt, _DummyModel, conditions, allowed_fields=allowed)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "IN" in sql
        assert "'active'" in sql
        assert "'done'" in sql

    def test_callable_handler_negate(self):
        """negate=True wraps the handler result in NOT."""

        def handler(op, value):
            return _dummy_table.c.name == value

        stmt = select(_dummy_table)
        conditions = [
            FilterCondition(field="custom", op=FilterOp.eq, value="alice", negate=True)
        ]
        allowed = {"custom": handler}
        result = apply_filters(stmt, _DummyModel, conditions, allowed_fields=allowed)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "name != 'alice'" in sql

    def test_callable_handler_returns_none_skipped(self):
        """When handler returns None, no WHERE clause is added."""

        def handler(op, value):
            return None

        stmt = select(_dummy_table)
        conditions = [FilterCondition(field="custom", op=FilterOp.eq, value="x")]
        allowed = {"custom": handler}
        result = apply_filters(stmt, _DummyModel, conditions, allowed_fields=allowed)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "WHERE" not in sql

    def test_callable_handler_in_or_group(self):
        """Callable inside a FilterGroup with OR logic."""

        def handler(op, value):
            return _dummy_table.c.score > value

        stmt = select(_dummy_table)
        conditions = [
            FilterGroup(
                logic="or",
                conditions=[
                    FilterCondition(field="name", op=FilterOp.eq, value="alice"),
                    FilterCondition(field="high_score", op=FilterOp.gt, value=90),
                ],
            )
        ]
        allowed = {"name": _DummyModel.name, "high_score": handler}
        result = apply_filters(stmt, _DummyModel, conditions, allowed_fields=allowed)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "OR" in sql
        assert "'alice'" in sql
        assert "score > 90" in sql

    def test_callable_mixed_with_column(self):
        """Dict with both column refs and callables works together."""

        def handler(op, value):
            return _dummy_table.c.score >= value

        stmt = select(_dummy_table)
        conditions = [
            FilterCondition(field="name", op=FilterOp.eq, value="bob"),
            FilterCondition(field="min_score", op=FilterOp.gte, value=50),
        ]
        allowed = {"name": _DummyModel.name, "min_score": handler}
        result = apply_filters(stmt, _DummyModel, conditions, allowed_fields=allowed)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "name = 'bob'" in sql
        assert "score >= 50" in sql

    def test_callable_receives_correct_args(self):
        """Handler receives the exact op and value from the FilterCondition."""
        received = {}

        def handler(op, value):
            received["op"] = op
            received["value"] = value
            return _dummy_table.c.id == 1  # dummy clause

        stmt = select(_dummy_table)
        conditions = [FilterCondition(field="custom", op=FilterOp.in_, value=[10, 20])]
        allowed = {"custom": handler}
        apply_filters(stmt, _DummyModel, conditions, allowed_fields=allowed)
        assert received["op"] == FilterOp.in_
        assert received["value"] == [10, 20]


class TestDateValueCoercion:
    """ISO strings in conditions must reach the DB as real dates.

    JSON has no date type, so a date filter can only arrive as a string, and
    SQLAlchemy binds a str as VARCHAR even against a timestamp column —
    Postgres then refuses to compare the two.
    """

    def test_iso_string_binds_as_timestamp_not_varchar(self):
        stmt = select(_dummy_table)
        conditions = [
            FilterCondition(
                field="due_at", op=FilterOp.gte, value="2026-06-01T00:00:00+00:00"
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        bind = list(result.whereclause.get_children())[1]
        assert isinstance(bind.type, DateTime)
        assert bind.value == datetime(2026, 6, 1, tzinfo=UTC)

    def test_parses_z_suffix(self):
        """The shape JS toISOString() produces."""
        stmt = select(_dummy_table)
        conditions = [
            FilterCondition(
                field="due_at", op=FilterOp.lte, value="2026-06-30T23:59:59.999Z"
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        bind = list(result.whereclause.get_children())[1]
        assert bind.value.tzinfo is not None
        assert bind.value.year == 2026

    def test_date_column_gets_a_date(self):
        stmt = select(_dummy_table)
        conditions = [
            FilterCondition(field="due_on", op=FilterOp.eq, value="2026-06-01")
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        bind = list(result.whereclause.get_children())[1]
        assert bind.value == date(2026, 6, 1)

    def test_date_column_narrowed_by_a_full_timestamp_takes_the_day(self):
        """date.fromisoformat() won't read a time component, but a caller
        windowing a date column sends exactly that (JS toISOString())."""
        stmt = select(_dummy_table)
        conditions = [
            FilterCondition(
                field="due_on", op=FilterOp.gte, value="2026-06-01T12:30:00.000Z"
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        bind = list(result.whereclause.get_children())[1]
        assert bind.value == date(2026, 6, 1)

    def test_coerces_each_value_of_an_in_list(self):
        stmt = select(_dummy_table)
        conditions = [
            FilterCondition(
                field="due_on", op=FilterOp.in_, value=["2026-06-01", "2026-06-02"]
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        # Rendered as dates, not quoted strings needing a cast.
        assert "'2026-06-01'" in sql

    def test_datetime_column_accepts_a_date_only_string(self):
        stmt = select(_dummy_table)
        conditions = [
            FilterCondition(field="due_at", op=FilterOp.gte, value="2026-06-01")
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        bind = list(result.whereclause.get_children())[1]
        assert bind.value == datetime(2026, 6, 1)

    def test_unparseable_string_is_left_alone(self):
        """Passed through rather than dropped: silently ignoring a filter the
        caller asked for would widen the result set."""
        stmt = select(_dummy_table)
        conditions = [
            FilterCondition(field="due_at", op=FilterOp.gte, value="whenever")
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        bind = list(result.whereclause.get_children())[1]
        assert bind.value == "whenever"

    def test_non_date_columns_are_untouched(self):
        stmt = select(_dummy_table)
        conditions = [FilterCondition(field="name", op=FilterOp.eq, value="2026-06-01")]
        result = apply_filters(stmt, _DummyModel, conditions)
        bind = list(result.whereclause.get_children())[1]
        assert bind.value == "2026-06-01"

    def test_is_null_value_is_not_coerced(self):
        """is_null reads its value as a boolean flag, not a comparand."""
        stmt = select(_dummy_table)
        conditions = [FilterCondition(field="due_at", op=FilterOp.is_null, value=True)]
        result = apply_filters(stmt, _DummyModel, conditions)
        assert "IS NULL" in str(result.compile()).upper()


# ---------------------------------------------------------------------------
# apply_sorting
# ---------------------------------------------------------------------------


class TestApplySorting:
    """Tests for apply_sorting."""

    def test_sort_by_string_asc(self):
        stmt = select(_dummy_table)
        result = apply_sorting(stmt, _DummyModel, sort_by="name", sort_dir="asc")
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "ORDER BY" in sql
        assert "name" in sql

    def test_sort_by_string_desc(self):
        stmt = select(_dummy_table)
        result = apply_sorting(stmt, _DummyModel, sort_by="score", sort_dir="desc")
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "ORDER BY" in sql
        assert "DESC" in sql

    def test_multi_sort_by_string(self):
        stmt = select(_dummy_table)
        result = apply_sorting(
            stmt, _DummyModel, sort_by="name,score", sort_dir="asc,desc"
        )
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "ORDER BY" in sql
        assert "name" in sql
        assert "score" in sql

    def test_sort_fields_structured(self):
        stmt = select(_dummy_table)
        fields = [
            SortField(field="name", dir=SortDir.asc),
            SortField(field="score", dir=SortDir.desc),
        ]
        result = apply_sorting(stmt, _DummyModel, sort_fields=fields)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "ORDER BY" in sql
        assert "name" in sql
        assert "score" in sql

    def test_default_sort_used_when_no_fields(self):
        stmt = select(_dummy_table)
        default = [(_DummyModel.score, "desc"), (_DummyModel.id, "asc")]
        result = apply_sorting(stmt, _DummyModel, default_sort=default)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "ORDER BY" in sql
        assert "score" in sql

    def test_default_sort_not_used_when_fields_provided(self):
        stmt = select(_dummy_table)
        default = [(_DummyModel.score, "desc")]
        result = apply_sorting(
            stmt,
            _DummyModel,
            sort_by="name",
            sort_dir="asc",
            default_sort=default,
        )
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "name" in sql

    def test_unknown_sort_field_falls_back_to_default(self):
        stmt = select(_dummy_table)
        allowed = {"name": _DummyModel.name}
        default = [(_DummyModel.id, "asc")]
        result = apply_sorting(
            stmt,
            _DummyModel,
            sort_by="nonexistent",
            sort_dir="asc",
            allowed_fields=allowed,
            default_sort=default,
        )
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "ORDER BY" in sql

    def test_id_tiebreaker_added(self):
        stmt = select(_dummy_table)
        result = apply_sorting(stmt, _DummyModel, sort_by="name", sort_dir="asc")
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        # Should have id as tiebreaker at the end
        assert "id" in sql

    def test_no_sort_no_default_returns_unmodified(self):
        stmt = select(_dummy_table)
        result = apply_sorting(stmt, _DummyModel)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "ORDER BY" not in sql


# ---------------------------------------------------------------------------
# apply_pagination
# ---------------------------------------------------------------------------


class TestApplyPagination:
    """Tests for apply_pagination."""

    def test_first_page(self):
        stmt = select(_dummy_table)
        result = apply_pagination(stmt, page=1, page_size=20)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "LIMIT" in sql
        assert "OFFSET" in sql

    def test_second_page(self):
        stmt = select(_dummy_table)
        result = apply_pagination(stmt, page=2, page_size=10)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "LIMIT" in sql
        assert "10" in sql

    def test_page_size_zero_bounded_by_window(self):
        """page_size=0 ("fetch all") is bounded by FETCH_ALL_WINDOW:
        a hard LIMIT is always applied, never an unbounded scan."""
        from app.db.query import FETCH_ALL_WINDOW

        stmt = select(_dummy_table)
        result = apply_pagination(stmt, page=1, page_size=0)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert f"LIMIT {FETCH_ALL_WINDOW}" in sql

    def test_negative_page_size_bounded_by_window(self):
        """A negative page_size is treated as "fetch all" and window-bounded,
        never left unbounded."""
        from app.db.query import FETCH_ALL_WINDOW

        stmt = select(_dummy_table)
        result = apply_pagination(stmt, page=1, page_size=-1)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert f"LIMIT {FETCH_ALL_WINDOW}" in sql

    def test_page_size_zero_pages_through_windows(self, monkeypatch):
        """page_size=0 honors ``page``: page N serves window N, so a caller can
        walk pages until has_next is false and retrieve the complete set."""
        monkeypatch.setattr("app.db.query.FETCH_ALL_WINDOW", 7)
        stmt = select(_dummy_table)
        result = apply_pagination(stmt, page=3, page_size=0)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "LIMIT 7" in sql
        assert "OFFSET 14" in sql

    def test_positive_page_size_clamped_to_window(self, monkeypatch):
        """Defense in depth: even if an endpoint forgets its ``le=`` parameter
        bound, a positive page_size can never exceed FETCH_ALL_WINDOW."""
        monkeypatch.setattr("app.db.query.FETCH_ALL_WINDOW", 7)
        stmt = select(_dummy_table)
        result = apply_pagination(stmt, page=1, page_size=50)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "LIMIT 7" in sql


# ---------------------------------------------------------------------------
# build_paginated_response
# ---------------------------------------------------------------------------


class TestBuildPaginatedResponse:
    """Tests for build_paginated_response helper."""

    def test_basic_response(self):
        result = build_paginated_response(
            items=["a", "b", "c"],
            total_count=50,
            page=2,
            page_size=20,
        )
        assert result["items"] == ["a", "b", "c"]
        assert result["total_count"] == 50
        assert result["page"] == 2
        assert result["page_size"] == 20
        assert result["has_next"] is True
        assert result["has_prev"] is True

    def test_first_page_no_prev(self):
        result = build_paginated_response(
            items=["a", "b"],
            total_count=5,
            page=1,
            page_size=3,
        )
        assert result["has_next"] is True
        assert result["has_prev"] is False

    def test_last_page_no_next(self):
        result = build_paginated_response(
            items=["e"],
            total_count=5,
            page=2,
            page_size=4,
        )
        assert result["has_next"] is False
        assert result["has_prev"] is True

    def test_single_page(self):
        result = build_paginated_response(
            items=["a", "b"],
            total_count=2,
            page=1,
            page_size=20,
        )
        assert result["has_next"] is False
        assert result["has_prev"] is False

    def test_extra_fields(self):
        result = build_paginated_response(
            items=[],
            total_count=0,
            page=1,
            page_size=20,
            sort_by="name",
            sort_dir="asc",
        )
        assert result["sort_by"] == "name"
        assert result["sort_dir"] == "asc"
        assert result["has_next"] is False
        assert result["has_prev"] is False

    def test_page_size_zero_single_window_complete(self):
        """A set smaller than the window is complete in one response."""
        result = build_paginated_response(
            items=["a"],
            total_count=1,
            page=1,
            page_size=0,
        )
        assert result["page"] == 1
        assert result["has_next"] is False
        assert result["has_prev"] is False

    def test_page_size_zero_truncation_is_visible(self, monkeypatch):
        """When the set exceeds the window, has_next says so — truncation is
        never silent (the regression that motivated the window protocol)."""
        monkeypatch.setattr("app.db.query.FETCH_ALL_WINDOW", 2)
        result = build_paginated_response(
            items=["a", "b"],
            total_count=5,
            page=1,
            page_size=0,
        )
        assert result["has_next"] is True
        assert result["page"] == 1

    def test_page_size_zero_window_walk_terminates(self, monkeypatch):
        """Walking page=1,2,3 over a 5-row set with window 2 ends exactly at
        the last window."""
        monkeypatch.setattr("app.db.query.FETCH_ALL_WINDOW", 2)
        middle = build_paginated_response(
            items=["c", "d"], total_count=5, page=2, page_size=0
        )
        assert middle["has_next"] is True
        assert middle["has_prev"] is True
        last = build_paginated_response(items=["e"], total_count=5, page=3, page_size=0)
        assert last["has_next"] is False


# ---------------------------------------------------------------------------
# clamp_page
# ---------------------------------------------------------------------------


class TestClampPage:
    """Tests for page clamping when page overshoots results."""

    def test_valid_page_unchanged(self):
        assert clamp_page(2, 10, 50) == 2

    def test_page_beyond_total_resets_to_1(self):
        # 50 items, 20 per page = 3 pages. Page 5 is out of range.
        assert clamp_page(5, 20, 50) == 1

    def test_last_page_is_valid(self):
        # 50 items, 20 per page = 3 pages. Page 3 is valid.
        assert clamp_page(3, 20, 50) == 3

    def test_zero_total_resets_to_1(self):
        assert clamp_page(3, 20, 0) == 1

    def test_page_size_zero_clamps_against_windows(self, monkeypatch):
        """page_size=0 pages are validated against FETCH_ALL_WINDOW-sized
        windows: in-range window pages survive, overshoot resets to 1."""
        monkeypatch.setattr("app.db.query.FETCH_ALL_WINDOW", 10)
        assert clamp_page(5, 0, 100) == 5  # 10 windows of 10 — page 5 valid
        assert clamp_page(11, 0, 100) == 1  # beyond the last window

    def test_page_1_always_valid(self):
        assert clamp_page(1, 20, 1) == 1

    def test_exact_boundary(self):
        # 20 items, 20 per page = 1 page. Page 1 is valid, page 2 is not.
        assert clamp_page(1, 20, 20) == 1
        assert clamp_page(2, 20, 20) == 1


# ---------------------------------------------------------------------------
# effective_page_size / paginate_sequence / page_has_next
# ---------------------------------------------------------------------------


class TestWindowHelpers:
    """The window seam shared by DB-windowed and in-memory-sliced endpoints."""

    def test_effective_page_size(self, monkeypatch):
        from app.db.query import effective_page_size

        monkeypatch.setattr("app.db.query.FETCH_ALL_WINDOW", 10)
        assert effective_page_size(0) == 10
        assert effective_page_size(-5) == 10
        assert effective_page_size(3) == 3
        assert effective_page_size(50) == 10  # defense-in-depth clamp

    def test_paginate_sequence_positive_pages(self):
        from app.db.query import paginate_sequence

        items = list(range(10))
        assert paginate_sequence(items, page=1, page_size=4) == [0, 1, 2, 3]
        assert paginate_sequence(items, page=2, page_size=4) == [4, 5, 6, 7]
        assert paginate_sequence(items, page=3, page_size=4) == [8, 9]
        assert paginate_sequence(items, page=4, page_size=4) == []

    def test_paginate_sequence_windows_fetch_all(self, monkeypatch):
        from app.db.query import paginate_sequence

        monkeypatch.setattr("app.db.query.FETCH_ALL_WINDOW", 4)
        items = list(range(10))
        assert paginate_sequence(items, page=1, page_size=0) == [0, 1, 2, 3]
        assert paginate_sequence(items, page=2, page_size=0) == [4, 5, 6, 7]
        assert paginate_sequence(items, page=3, page_size=0) == [8, 9]

    def test_window_walk_reassembles_complete_set(self, monkeypatch):
        """The invariant the SPA relies on: concatenating windows until
        page_has_next is false yields exactly the full set, no gaps, no dupes."""
        from app.db.query import page_has_next, paginate_sequence

        monkeypatch.setattr("app.db.query.FETCH_ALL_WINDOW", 3)
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

    def test_page_has_next_positive_sizes(self):
        from app.db.query import page_has_next

        assert page_has_next(1, 3, 5) is True
        assert page_has_next(2, 3, 5) is False
        assert page_has_next(1, 20, 2) is False


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestSchemas:
    """Tests for query schema validation."""

    def test_filter_condition_defaults(self):
        cond = FilterCondition(field="name", value="test")
        assert cond.op == FilterOp.eq
        assert cond.negate is False

    def test_sort_field_defaults(self):
        sf = SortField(field="name")
        assert sf.dir == SortDir.asc


# ---------------------------------------------------------------------------
# parse_conditions (security & validation)
# ---------------------------------------------------------------------------


class TestParseConditions:
    """Tests for parse_conditions including security hardening."""

    def test_none_returns_empty(self):
        assert parse_conditions(None) == []

    def test_empty_string_returns_empty(self):
        assert parse_conditions("") == []

    def test_valid_single_condition(self):
        raw = '[{"field": "name", "op": "eq", "value": "alice"}]'
        result = parse_conditions(raw)
        assert len(result) == 1
        assert result[0].field == "name"
        assert result[0].op == FilterOp.eq
        assert result[0].value == "alice"

    def test_valid_multiple_conditions(self):
        raw = '[{"field": "a", "op": "eq", "value": 1}, {"field": "b", "op": "gt", "value": 5}]'
        result = parse_conditions(raw)
        assert len(result) == 2

    def test_defaults_applied(self):
        """op defaults to eq, negate defaults to False."""
        raw = '[{"field": "name", "value": "test"}]'
        result = parse_conditions(raw)
        assert result[0].op == FilterOp.eq
        assert result[0].negate is False

    def test_negate_preserved(self):
        raw = '[{"field": "name", "op": "eq", "value": "x", "negate": true}]'
        result = parse_conditions(raw)
        assert result[0].negate is True

    def test_rejects_oversized_payload(self):
        with pytest.raises(ValueError, match="size limit"):
            parse_conditions("x" * 10_001)

    def test_custom_max_length(self):
        with pytest.raises(ValueError, match="size limit"):
            parse_conditions("x" * 101, max_length=100)

    @pytest.mark.parametrize(
        ("raw", "problem"),
        [
            ("{not json}", "not valid JSON"),
            ('{"field": "name"}', "must be a JSON array"),
            ('[{"bad_key": "value"}]', "invalid condition structure"),
            (
                '[{"field": "name", "op": "DROP TABLE", "value": "x"}]',
                "invalid condition structure",
            ),
        ],
        ids=[
            "not JSON",
            "not an array",
            "not a condition",
            "an operator nobody serves",
        ],
    )
    def test_a_payload_that_is_not_a_list_of_conditions_is_refused(self, raw, problem):
        """Each refusal names what the payload was instead."""
        with pytest.raises(ValueError, match=problem):
            parse_conditions(raw)

    def test_rejects_too_many_conditions(self):
        items = [{"field": "f", "value": i} for i in range(51)]
        import json

        with pytest.raises(ValueError, match="too many conditions"):
            parse_conditions(json.dumps(items))

    def test_custom_max_conditions(self):
        items = [{"field": "f", "value": i} for i in range(3)]
        import json

        with pytest.raises(ValueError, match="too many conditions"):
            parse_conditions(json.dumps(items), max_conditions=2)

    def test_at_exact_limit_succeeds(self):
        items = [{"field": "f", "value": i} for i in range(50)]
        import json

        result = parse_conditions(json.dumps(items))
        assert len(result) == 50

    def test_parses_group(self):
        raw = (
            '[{"logic": "or", "conditions": ['
            '{"field": "start_date", "op": "gte", "value": "2026-01-01"},'
            '{"field": "due_date", "op": "gte", "value": "2026-01-01"}]}]'
        )
        result = parse_conditions(raw)
        assert len(result) == 1
        group = result[0]
        assert isinstance(group, FilterGroup)
        assert group.logic == "or"
        assert [c.field for c in group.conditions] == ["start_date", "due_date"]

    def test_parses_group_alongside_flat_conditions(self):
        raw = (
            '[{"field": "priority", "op": "in_", "value": ["high"]},'
            '{"logic": "or", "conditions": [{"field": "a", "value": 1}]}]'
        )
        result = parse_conditions(raw)
        assert isinstance(result[0], FilterCondition)
        assert isinstance(result[1], FilterGroup)

    def test_group_logic_defaults_to_and(self):
        result = parse_conditions('[{"conditions": [{"field": "a", "value": 1}]}]')
        assert result[0].logic == "and"

    def test_parses_nested_group(self):
        raw = (
            '[{"logic": "or", "conditions": ['
            '{"logic": "and", "conditions": ['
            '{"field": "start_date", "op": "gte", "value": "a"},'
            '{"field": "start_date", "op": "lte", "value": "b"}]}]}]'
        )
        result = parse_conditions(raw)
        assert isinstance(result[0].conditions[0], FilterGroup)

    def test_rejects_group_nested_too_deeply(self):
        raw = (
            '[{"conditions": [{"conditions": [{"conditions": ['
            '{"field": "a", "value": 1}]}]}]}]'
        )
        with pytest.raises(ValueError, match="nested too deeply"):
            parse_conditions(raw)

    def test_custom_max_depth(self):
        raw = '[{"conditions": [{"conditions": [{"field": "a", "value": 1}]}]}]'
        assert parse_conditions(raw)  # depth 2 is fine by default
        with pytest.raises(ValueError, match="nested too deeply"):
            parse_conditions(raw, max_depth=1)

    def test_rejects_too_many_conditions_inside_a_group(self):
        """The count is of leaves, so conditions inside a group count too."""
        import json

        items = [{"conditions": [{"field": "f", "value": i} for i in range(51)]}]
        with pytest.raises(ValueError, match="too many conditions"):
            parse_conditions(json.dumps(items))

    def test_rejects_invalid_structure_inside_a_group(self):
        with pytest.raises(ValueError, match="invalid condition structure"):
            parse_conditions('[{"conditions": [{"bad_key": "value"}]}]')


# ---------------------------------------------------------------------------
# extract_condition_value
# ---------------------------------------------------------------------------


class TestExtractConditionValue:
    """Tests for extract_condition_value helper."""

    def test_finds_matching_field(self):
        conditions = [
            FilterCondition(field="status", op=FilterOp.eq, value="active"),
            FilterCondition(field="priority", op=FilterOp.in_, value=["high"]),
        ]
        assert extract_condition_value(conditions, "priority") == ["high"]

    def test_returns_first_match(self):
        conditions = [
            FilterCondition(field="name", value="first"),
            FilterCondition(field="name", value="second"),
        ]
        assert extract_condition_value(conditions, "name") == "first"

    def test_returns_none_when_not_found(self):
        conditions = [FilterCondition(field="name", value="test")]
        assert extract_condition_value(conditions, "missing") is None

    def test_ignores_values_inside_groups(self):
        """A grouped field doesn't hold for every row, so it must not be read
        as a narrowing of the result set."""
        conditions = [
            FilterGroup(
                logic="or",
                conditions=[FilterCondition(field="project_id", value=7)],
            )
        ]
        assert extract_condition_value(conditions, "project_id") is None

    def test_finds_top_level_match_past_a_group(self):
        conditions = [
            FilterGroup(conditions=[FilterCondition(field="a", value=1)]),
            FilterCondition(field="project_id", value=7),
        ]
        assert extract_condition_value(conditions, "project_id") == 7


# ---------------------------------------------------------------------------
# iter_leaf_conditions
# ---------------------------------------------------------------------------


class TestIterLeafConditions:
    def test_yields_flat_conditions(self):
        conditions = [
            FilterCondition(field="a", value=1),
            FilterCondition(field="b", value=2),
        ]
        assert [c.field for c in iter_leaf_conditions(conditions)] == ["a", "b"]

    def test_descends_into_nested_groups(self):
        conditions = [
            FilterCondition(field="a", value=1),
            FilterGroup(
                logic="or",
                conditions=[
                    FilterCondition(field="b", value=2),
                    FilterGroup(conditions=[FilterCondition(field="c", value=3)]),
                ],
            ),
        ]
        assert [c.field for c in iter_leaf_conditions(conditions)] == ["a", "b", "c"]

    def test_empty(self):
        assert list(iter_leaf_conditions([])) == []

    def test_empty_list_returns_none(self):
        assert extract_condition_value([], "anything") is None


# ---------------------------------------------------------------------------
# parse_sort_fields (security & validation)
# ---------------------------------------------------------------------------


class TestParseSortFields:
    """Tests for parse_sort_fields including security hardening."""

    def test_none_returns_empty(self):
        assert parse_sort_fields(None) == []

    def test_empty_string_returns_empty(self):
        assert parse_sort_fields("") == []

    def test_valid_single_field(self):
        raw = '[{"field": "due_date", "dir": "desc"}]'
        result = parse_sort_fields(raw)
        assert len(result) == 1
        assert result[0].field == "due_date"
        assert result[0].dir == SortDir.desc

    def test_valid_multiple_fields(self):
        raw = '[{"field": "date_group", "dir": "asc"}, {"field": "due_date", "dir": "desc"}]'
        result = parse_sort_fields(raw)
        assert len(result) == 2
        assert result[0].field == "date_group"
        assert result[1].dir == SortDir.desc

    def test_defaults_dir_to_asc(self):
        raw = '[{"field": "title"}]'
        result = parse_sort_fields(raw)
        assert result[0].dir == SortDir.asc

    def test_rejects_oversized_payload(self):
        with pytest.raises(ValueError, match="size limit"):
            parse_sort_fields("x" * 10_001)

    @pytest.mark.parametrize(
        ("raw", "problem"),
        [
            ("{not json}", "not valid JSON"),
            ('{"field": "name"}', "must be a JSON array"),
            ('[{"bad_key": "value"}]', "invalid sort field structure"),
            ('[{"field": "name", "dir": "RANDOM"}]', "invalid sort field structure"),
        ],
        ids=[
            "not JSON",
            "not an array",
            "not a sort field",
            "a direction that is not one",
        ],
    )
    def test_a_payload_that_is_not_a_list_of_sort_fields_is_refused(self, raw, problem):
        """Each refusal names what the payload was instead."""
        with pytest.raises(ValueError, match=problem):
            parse_sort_fields(raw)

    def test_rejects_too_many_fields(self):
        items = [{"field": f"f{i}"} for i in range(11)]
        import json

        with pytest.raises(ValueError, match="too many sort fields"):
            parse_sort_fields(json.dumps(items))

    def test_at_exact_limit_succeeds(self):
        items = [{"field": f"f{i}"} for i in range(10)]
        import json

        result = parse_sort_fields(json.dumps(items))
        assert len(result) == 10

    def test_custom_max_fields(self):
        items = [{"field": f"f{i}"} for i in range(3)]
        import json

        with pytest.raises(ValueError, match="too many sort fields"):
            parse_sort_fields(json.dumps(items), max_fields=2)


class TestBuildPaginatedResponseUnbounded:
    """A capped "all rows" response must signal truncation."""

    def test_truncated_unbounded_result_sets_has_next(self):
        from app.db.query import build_paginated_response

        # 1000-row cap hit: 1000 items of a 1500-row total.
        resp = build_paginated_response(
            items=list(range(1000)), total_count=1500, page=1, page_size=0
        )
        assert resp["has_next"] is True
        assert resp["has_prev"] is False
        assert resp["page"] == 1

    def test_complete_unbounded_result_has_no_next(self):
        from app.db.query import build_paginated_response

        resp = build_paginated_response(
            items=list(range(42)), total_count=42, page=1, page_size=0
        )
        assert resp["has_next"] is False
