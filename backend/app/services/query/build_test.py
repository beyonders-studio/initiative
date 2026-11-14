"""What a builder describes, and the statement it becomes.

The point of building in the parse tree rather than as text is that quoting and
spelling stop being ours to get right. So the assertions that matter are the
hostile ones: a literal that would close a string early, and an alias somebody
chose, both come out as one statement the validator accepts.
"""

from __future__ import annotations

import pytest

from app.core.messages import QueryMessages
from app.schemas.query import FilterOp
from app.services.query import QueryError
from app.services.query.build import (
    Column,
    Condition,
    Group,
    QuerySpec,
    Sort,
    build,
)
from app.services.query.resolve import PluginCall, ResolvedQuery, SheetCall, resolve


def build_and_resolve(spec: QuerySpec) -> tuple[str, ResolvedQuery]:
    """The statement, and proof that the surface will run it."""
    sql = build(spec)
    return sql, resolve(sql)


def test_a_grouped_count_is_the_shape_a_chart_wants():
    sql, _ = build_and_resolve(
        QuerySpec(
            dataset="tasks",
            columns=(
                Column(field="priority"),
                Column(field="*", aggregate="count", alias="tasks"),
            ),
            group_by=("priority",),
            order_by=Sort(field="tasks", descending=True),
            limit=10,
        )
    )
    assert "count(*) AS tasks" in sql
    assert "GROUP BY 1" in sql
    assert "ORDER BY 2 DESC" in sql
    assert "LIMIT 10" in sql


def test_a_bare_column_is_not_aliased_to_itself():
    """Postgres names an output after the column it read, so an alias there
    would read as ``priority AS priority``."""
    assert build(QuerySpec(dataset="tasks", columns=(Column(field="priority"),))) == (
        "SELECT priority FROM tasks"
    )


def test_a_date_is_rounded_before_it_is_grouped():
    sql, _ = build_and_resolve(
        QuerySpec(
            dataset="tasks",
            columns=(
                Column(field="completed_at", bucket="day", alias="day"),
                Column(field="*", aggregate="count", alias="done"),
            ),
            where=(Condition(field="completed_at", op=FilterOp.is_null, value=False),),
            group_by=("day",),
        )
    )
    assert "date_trunc('day', completed_at) AS day" in sql
    assert "completed_at IS NOT NULL" in sql


@pytest.mark.parametrize("bucket", ["day", "week", "month", "quarter", "year"])
def test_a_grouped_series_comes_back_in_order(bucket):
    """Without an order of its own, a grouped statement reads in the order of
    what it is grouped by — a time series left to right, at every grain."""
    sql, _ = build_and_resolve(
        QuerySpec(
            dataset="tasks",
            columns=(
                Column(field="due_date", bucket=bucket),
                Column(field="*", aggregate="count"),
            ),
            group_by=("due_date",),
        )
    )
    assert f"date_trunc('{bucket}', due_date) AS due_date" in sql
    assert "GROUP BY 1 ORDER BY 1 ASC" in sql


def test_one_date_rounded_two_ways_is_grouped_both_ways():
    """The two roundings share the date's name, and both have to be grouped
    or the statement is refused."""
    sql, _ = build_and_resolve(
        QuerySpec(
            dataset="tasks",
            columns=(
                Column(field="due_date", bucket="month"),
                Column(field="due_date", bucket="day"),
                Column(field="*", aggregate="count"),
            ),
            group_by=("due_date",),
        )
    )
    assert "GROUP BY 1, 2 ORDER BY 1 ASC NULLS LAST, 2 ASC NULLS LAST" in sql


def test_a_count_sharing_a_columns_name_is_not_grouped():
    sql, _ = build_and_resolve(
        QuerySpec(
            dataset="tasks",
            columns=(
                Column(field="priority", alias="bucket"),
                Column(field="*", aggregate="count", alias="bucket"),
            ),
            group_by=("bucket",),
        )
    )
    assert "GROUP BY 1 ORDER BY 1 ASC NULLS LAST" in sql


def test_a_running_count_adds_up_along_the_grouping():
    sql, _ = build_and_resolve(
        QuerySpec(
            dataset="tasks",
            columns=(
                Column(field="completed_at", bucket="week"),
                Column(field="*", aggregate="count", running=True),
            ),
            group_by=("completed_at",),
        )
    )
    assert (
        "sum(count(*)) OVER (ORDER BY date_trunc('week', completed_at) ASC NULLS LAST)"
        " AS running_count" in sql
    )


def test_a_running_total_restarts_for_each_series():
    """The first grouped column is the axis and the rest split the series, so
    each series climbs on its own."""
    sql, _ = build_and_resolve(
        QuerySpec(
            dataset="tasks",
            columns=(
                Column(field="due_date", bucket="month"),
                Column(field="priority"),
                Column(field="*", aggregate="count", running=True),
            ),
            group_by=("due_date", "priority"),
        )
    )
    assert "OVER (PARTITION BY priority ORDER BY date_trunc('month', due_date)" in sql


@pytest.mark.parametrize(
    ("columns", "code"),
    [
        # Nothing grouped: one row has nothing to add up along.
        ((Column(field="*", aggregate="count", running=True),), "UNSUPPORTED_SYNTAX"),
        # A running average is not a running total.
        (
            (
                Column(field="priority"),
                Column(field="*", aggregate="avg", running=True),
            ),
            "UNSUPPORTED_FUNCTION",
        ),
    ],
)
def test_a_running_total_needs_a_grouping_and_a_total(columns, code):
    with pytest.raises(QueryError) as refused:
        build(
            QuerySpec(
                dataset="tasks",
                columns=columns,
                group_by=tuple(c.field for c in columns if not c.aggregate),
            )
        )
    assert refused.value.code == getattr(QueryMessages, code)


@pytest.mark.parametrize(
    "value",
    [
        "it's",
        "'; DROP TABLE tasks; --",
        "'''",
        "line\nbreak",
        "trailing backslash \\",
    ],
)
def test_a_value_stays_one_value(value):
    """A literal is written into the tree, not into the text, so what it
    contains is the deparser's business. Each of these comes back as one
    statement the surface will run."""
    sql, resolved = build_and_resolve(
        QuerySpec(
            dataset="tasks",
            columns=(Column(field="title"),),
            where=(Condition(field="title", op=FilterOp.ilike, value=value),),
        )
    )
    assert sql.startswith("SELECT title FROM tasks WHERE")
    # Resolution binds it, so the value reaches Postgres as a parameter.
    assert resolved.parameters == (value,)


def test_an_alias_somebody_chose_stays_one_name():
    sql, _ = build_and_resolve(
        QuerySpec(
            dataset="tasks",
            columns=(Column(field="title", alias='weird" name'),),
        )
    )
    assert sql.count("SELECT") == 1
    assert '"weird"" name"' in sql


def test_several_conditions_are_all_required():
    sql, _ = build_and_resolve(
        QuerySpec(
            dataset="tasks",
            columns=(Column(field="title"),),
            where=(
                Condition(field="archived_at", op=FilterOp.is_null, value=True),
                Condition(field="priority", op=FilterOp.in_, value=["high", "urgent"]),
            ),
        )
    )
    assert "AND" in sql
    assert "IN" in sql


class TestWhatItRefuses:
    def test_a_dataset_nobody_declared(self):
        with pytest.raises(QueryError) as refused:
            build(QuerySpec(dataset="pg_shadow", columns=(Column(field="usename"),)))
        assert refused.value.code == QueryMessages.UNKNOWN_RELATION

    def test_a_field_the_dataset_does_not_have(self):
        with pytest.raises(QueryError) as refused:
            build(QuerySpec(dataset="tasks", columns=(Column(field="nope"),)))
        assert refused.value.code == QueryMessages.UNKNOWN_FIELD

    def test_a_function_that_is_not_an_aggregate(self):
        with pytest.raises(QueryError) as refused:
            build(
                QuerySpec(
                    dataset="tasks",
                    columns=(Column(field="title", aggregate="pg_sleep"),),
                )
            )
        assert refused.value.code == QueryMessages.UNSUPPORTED_FUNCTION

    def test_a_bucket_that_is_not_a_bucket(self):
        with pytest.raises(QueryError) as refused:
            build(
                QuerySpec(
                    dataset="tasks",
                    columns=(Column(field="due_date", bucket="fortnight"),),
                )
            )
        assert refused.value.code == QueryMessages.UNSUPPORTED_SYNTAX

    def test_grouping_by_something_the_statement_does_not_return(self):
        with pytest.raises(QueryError) as refused:
            build(
                QuerySpec(
                    dataset="tasks",
                    columns=(Column(field="title"),),
                    group_by=("priority",),
                )
            )
        assert refused.value.code == QueryMessages.UNKNOWN_FIELD

    def test_a_statement_with_nothing_in_it(self):
        with pytest.raises(QueryError):
            build(QuerySpec(dataset="tasks", columns=()))


class TestReachingThroughARelation:
    """A dataset declares what it can be read alongside, and both ways of
    asking write the same joins from the same declaration."""

    def test_a_related_field_writes_its_joins(self):
        sql = build(
            QuerySpec(
                dataset="tasks",
                columns=(
                    Column(field="assignee.display_name", alias="person"),
                    Column(field="*", aggregate="count", alias="tasks"),
                ),
                group_by=("person",),
            )
        )
        assert "JOIN task_assignees" in sql
        assert "JOIN members AS assignee" in sql
        assert "assignee.display_name AS person" in sql

    def test_what_it_writes_is_a_statement_the_surface_runs(self):
        """The point of building the tree rather than the text: the validator
        reads what comes out, joins and all."""
        _sql, resolved = build_and_resolve(
            QuerySpec(
                dataset="tasks",
                columns=(
                    Column(field="assignee.display_name", alias="person"),
                    Column(field="*", aggregate="count", alias="n"),
                ),
                group_by=("person",),
            )
        )
        assert set(resolved.relations) == {"tasks", "task_assignees", "members"}

    def test_a_relation_nobody_declared_is_refused(self):
        with pytest.raises(QueryError) as refused:
            build(
                QuerySpec(
                    dataset="tasks",
                    columns=(Column(field="nowhere.name"),),
                )
            )
        assert refused.value.code == QueryMessages.UNKNOWN_RELATION

    def test_a_field_the_relation_does_not_reach_is_refused(self):
        with pytest.raises(QueryError) as refused:
            build(
                QuerySpec(
                    dataset="tasks",
                    columns=(Column(field="assignee.nonsense"),),
                )
            )
        assert refused.value.code == QueryMessages.UNKNOWN_FIELD

    def test_a_relation_is_joined_once_however_often_it_is_named(self):
        sql = build(
            QuerySpec(
                dataset="tasks",
                columns=(
                    Column(field="assignee.display_name", alias="person"),
                    Column(field="assignee.username", alias="handle"),
                ),
            )
        )
        assert sql.count("JOIN members AS assignee") == 1

    def test_a_filter_may_reach_through_one_too(self):
        sql = build(
            QuerySpec(
                dataset="tasks",
                columns=(Column(field="title"),),
                where=(Condition(field="status.category", value="done"),),
            )
        )
        assert "JOIN task_statuses AS status" in sql
        assert "status.category" in sql


class TestPickingYourself:
    """A member picker offers the reader themselves, and what that builds is
    the token rather than a value — so the tile answers per person."""

    def test_a_person_field_takes_the_reader(self):
        sql = build(
            QuerySpec(
                dataset="tasks",
                columns=(Column(field="*", aggregate="count", alias="n"),),
                where=(Condition(field="created_by", op=FilterOp.eq, value="me"),),
            )
        )
        assert sql.endswith("WHERE created_by = me")

    def test_it_reaches_through_a_relation(self):
        sql = build(
            QuerySpec(
                dataset="tasks",
                columns=(Column(field="*", aggregate="count", alias="n"),),
                where=(Condition(field="assignee.id", op=FilterOp.eq, value="me"),),
            )
        )
        assert sql.endswith("WHERE assignee.id = me")

    def test_a_list_takes_it_beside_real_people(self):
        sql = build(
            QuerySpec(
                dataset="tasks",
                columns=(Column(field="*", aggregate="count", alias="n"),),
                where=(
                    Condition(field="created_by", op=FilterOp.in_, value=["me", 7]),
                ),
            )
        )
        assert sql.endswith("WHERE created_by IN (me, 7)")

    def test_anywhere_else_it_is_just_a_word(self):
        """A title may be the word "me", and comparing against it is a text
        comparison like any other."""
        sql = build(
            QuerySpec(
                dataset="tasks",
                columns=(Column(field="title"),),
                where=(Condition(field="title", op=FilterOp.eq, value="me"),),
            )
        )
        assert sql.endswith("WHERE title = 'me'")

    def test_what_it_builds_is_a_statement_the_validator_takes(self):
        _, resolved = build_and_resolve(
            QuerySpec(
                dataset="tasks",
                columns=(Column(field="*", aggregate="count", alias="n"),),
                where=(Condition(field="created_by", op=FilterOp.eq, value="me"),),
            )
        )
        assert "app.current_user_id" in resolved.sql
        assert resolved.parameters == ()


class TestBracketingWhatItAsks:
    """A flat list of ANDs cannot say "high or urgent, and mine", which is an
    ordinary thing to want of a tile. A description brackets, in the shape the
    filter builder has always written."""

    def where(self, *nodes):
        return (
            build(
                QuerySpec(
                    dataset="tasks",
                    columns=(Column(field="*", aggregate="count", alias="n"),),
                    where=nodes,
                )
            )
            .split("FROM tasks", 1)[1]
            .strip()
        )

    def test_a_group_says_its_own_word(self):
        assert (
            self.where(
                Group(
                    logic="or",
                    conditions=(
                        Condition(field="priority", op=FilterOp.eq, value="high"),
                        Condition(field="priority", op=FilterOp.eq, value="urgent"),
                    ),
                ),
                Condition(field="created_by", op=FilterOp.eq, value="me"),
            )
            == "WHERE (priority = 'high' OR priority = 'urgent') AND created_by = me"
        )

    def test_lines_beside_each_other_are_still_and(self):
        assert (
            self.where(
                Condition(field="priority", op=FilterOp.eq, value="high"),
                Condition(field="archived_at", op=FilterOp.is_null, value=True),
            )
            == "WHERE priority = 'high' AND archived_at IS NULL"
        )

    def test_a_condition_can_be_answered_the_other_way(self):
        assert (
            self.where(
                Condition(field="priority", op=FilterOp.eq, value="high", negate=True)
            )
            == "WHERE NOT priority = 'high'"
        )

    def test_a_bracket_nobody_filled_asks_nothing(self):
        """Saving half-written work beats refusing it."""
        assert self.where(Group(logic="or", conditions=())) == ""

    def test_a_bracket_around_one_thing_is_not_a_bracket(self):
        assert (
            self.where(
                Group(
                    logic="or",
                    conditions=(
                        Condition(field="priority", op=FilterOp.eq, value="high"),
                    ),
                )
            )
            == "WHERE priority = 'high'"
        )

    def test_a_field_inside_a_bracket_is_checked_like_any_other(self):
        with pytest.raises(QueryError) as refused:
            self.where(
                Group(conditions=(Condition(field="nope", op=FilterOp.eq, value=1),))
            )
        assert refused.value.code == QueryMessages.UNKNOWN_FIELD

    def test_a_relation_reached_from_inside_one_is_still_joined(self):
        assert "INNER JOIN" in self.where(
            Group(
                conditions=(Condition(field="assignee.id", op=FilterOp.eq, value="me"),)
            )
        )

    def test_bracketing_has_a_bottom(self):
        node = Condition(field="priority", op=FilterOp.eq, value="high")
        for _ in range(6):
            node = Group(conditions=(node,))
        with pytest.raises(QueryError) as refused:
            self.where(node)
        assert refused.value.code == QueryMessages.UNSUPPORTED_SYNTAX

    def test_the_bottom_is_reached_before_anything_reads_it(self):
        """Depth is checked on its own, ahead of the walks that look at fields
        and relations, so how deep a description may go does not depend on
        which of them happens to reach it."""
        node = Condition(field="nope", op=FilterOp.eq, value=1)
        for _ in range(200):
            node = Group(conditions=(node,))
        with pytest.raises(QueryError) as refused:
            self.where(node)
        # The depth, not the unknown field two hundred levels down.
        assert refused.value.code == QueryMessages.UNSUPPORTED_SYNTAX
        assert refused.value.subject == "group depth"

    def test_what_it_brackets_is_a_statement_the_validator_takes(self):
        _, resolved = build_and_resolve(
            QuerySpec(
                dataset="tasks",
                columns=(Column(field="*", aggregate="count", alias="n"),),
                where=(
                    Group(
                        logic="or",
                        conditions=(
                            Condition(field="priority", op=FilterOp.eq, value="high"),
                            Condition(field="created_by", op=FilterOp.eq, value="me"),
                        ),
                    ),
                ),
            )
        )
        assert "app.current_user_id" in resolved.sql


class TestADateStaysADistance:
    """A dashboard is a standing question. "Due in the next 30 days" has to
    still mean that next month, so the distance is what is written."""

    def where(self, value, op=FilterOp.lte):
        return (
            build(
                QuerySpec(
                    dataset="tasks",
                    columns=(Column(field="*", aggregate="count", alias="n"),),
                    where=(Condition(field="due_date", op=op, value=value),),
                )
            )
            .split("WHERE", 1)[1]
            .strip()
        )

    def test_ahead_of_now(self):
        assert self.where({"relative": 30}) == (
            "due_date <= now() + CAST('30 days' AS interval)"
        )

    def test_behind_it(self):
        assert self.where({"relative": -30}, FilterOp.gte) == (
            "due_date >= now() - CAST('30 days' AS interval)"
        )

    def test_today(self):
        assert "0 days" in self.where({"relative": 0})

    @pytest.mark.parametrize("value", ["soon", None, 1.9, True, [1]])
    def test_a_distance_that_is_not_a_whole_number_of_days(self, value):
        """``int()`` would read 1.9 as one day and ``True`` as one day. A
        boundary quietly one place from the one somebody asked for is worse
        than being told the value cannot be read."""
        with pytest.raises(QueryError) as refused:
            self.where({"relative": value})
        assert refused.value.code == QueryMessages.UNSUPPORTED_SYNTAX

    def test_the_statement_it_writes_is_one_the_validator_takes(self):
        _, resolved = build_and_resolve(
            QuerySpec(
                dataset="tasks",
                columns=(Column(field="*", aggregate="count", alias="n"),),
                where=(
                    Condition(
                        field="due_date", op=FilterOp.lte, value={"relative": 30}
                    ),
                ),
            )
        )
        assert "interval" in resolved.sql.lower()


class TestAJoinedStatementSaysWhichSide:
    """A bare column name with two tables in scope.

    Every tool carries ``archived_at`` and ``created_at``, so filtering one of
    those alongside any related field named a column Postgres could not resolve
    — the builder produced a statement the validator then refused, which is the
    one thing a builder must never do.
    """

    def test_a_filter_on_the_base_names_the_base(self):
        sql = build(
            QuerySpec(
                dataset="tasks",
                columns=(Column(field="*", aggregate="count", alias="n"),),
                where=(
                    Condition(field="archived_at", op=FilterOp.is_null, value=True),
                    Condition(field="project.is_template", value=False),
                ),
            )
        )
        assert "tasks.archived_at IS NULL" in sql
        assert resolve(sql).relations == ("projects", "tasks")

    def test_a_selected_column_does_too(self):
        sql = build(
            QuerySpec(
                dataset="tasks",
                columns=(
                    Column(field="created_at"),
                    Column(field="assignee.display_name", alias="person"),
                ),
            )
        )
        assert "tasks.created_at" in sql
        resolve(sql)

    def test_a_statement_about_one_table_is_left_unqualified(self):
        """Nothing to disambiguate, and the stored statement reads better."""
        sql = build(
            QuerySpec(
                dataset="tasks",
                columns=(Column(field="title"),),
                where=(
                    Condition(field="archived_at", op=FilterOp.is_null, value=True),
                ),
            )
        )
        assert sql == "SELECT title FROM tasks WHERE archived_at IS NULL"


def test_a_range_is_built_with_its_headers_whole():
    """A range's columns are its headers, which may hold a dot, so none of them
    is read as a relation; the range itself is a constant of the call."""
    sql, resolved = build_and_resolve(
        QuerySpec(
            sheet=SheetCall(42, "Q3 Actuals!A1:D"),
            columns=(Column(field="Region"), Column(field="No. sold", aggregate="sum")),
            where=(Condition(field="Region", op=FilterOp.ilike, value="%no%"),),
            group_by=("Region",),
        )
    )
    assert sql.startswith(
        """SELECT "Region", sum("No. sold") AS "No. sold_sum" """
        """FROM sheet(42, 'Q3 Actuals!A1:D') WHERE "Region" ~~* '%no%'"""
    )
    assert resolved.unread == (SheetCall(42, "Q3 Actuals!A1:D"),)


def test_a_plugin_endpoint_is_built_with_its_parameters_by_name():
    orders = PluginCall("acme.shop", "orders", (("range", "30d"), ("tags", ("a", "b"))))
    sql, resolved = build_and_resolve(
        QuerySpec(
            plugin=orders,
            columns=(Column(field="status"), Column(field="total", aggregate="sum")),
            group_by=("status",),
        )
    )
    assert sql.startswith(
        "SELECT status, sum(total) AS total_sum FROM plugin('acme.shop', 'orders', "
        "range => '30d', tags => ARRAY['a', 'b'])"
    )
    assert resolved.unread == (orders,)


def test_a_description_reads_one_dataset_or_one_range():
    for spec in (
        QuerySpec(columns=(Column(field="*", aggregate="count"),)),
        QuerySpec(
            dataset="tasks",
            sheet=SheetCall(42),
            columns=(Column(field="*", aggregate="count"),),
        ),
        QuerySpec(
            sheet=SheetCall(42),
            plugin=PluginCall("acme.shop", "orders"),
            columns=(Column(field="*", aggregate="count"),),
        ),
    ):
        with pytest.raises(QueryError) as refused:
            build(spec)
        assert refused.value.code == QueryMessages.MISSING_RELATION
