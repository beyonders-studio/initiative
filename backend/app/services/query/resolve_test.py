"""What the query surface accepts, and what it refuses.

The interesting assertion is never "this query works" — it is that everything
else is refused *by name*, so a construct nobody considered cannot arrive by
being unconsidered. Each refusal is checked for its code, because the code is
what a client shows the person who has to change the query.
"""

from __future__ import annotations

import json

import pytest
from pglast import ast, parse_sql

from app.core.messages import QueryMessages
from app.services.fields.spec import FieldType
from app.services.query import QueryError, resolve
from app.core.search import SearchEntityType
from app.services.query.resolve import (
    PluginCall,
    PluginRows,
    Sheet,
    SheetCall,
    remap_ids,
)

#: The function spellings this surface supports, as a reader writes them.
#: Postgres reports the name it resolved, so a spelling that is really a node
#: of its own (``coalesce``) or that arrives qualified (``extract``) is still
#: covered here — the assertion is that the spelling works, not what it
#: becomes.
SUPPORTED_CALLS = (
    "count(1)",
    "sum(1)",
    "avg(1)",
    "min(1)",
    "max(1)",
    "coalesce(1, 2)",
    "nullif(1, 2)",
    "greatest(1, 2)",
    "least(1, 2)",
    "abs(1)",
    "round(1)",
    "length('a')",
    "lower('a')",
    "upper('a')",
    "concat('a', 'b')",
    "date_trunc('day', now())",
    "extract(year from now())",
    "now()",
)


def refusal(sql: str) -> str:
    with pytest.raises(QueryError) as caught:
        resolve(sql)
    return caught.value.code


class TestOnlyAReadIsAdmitted:
    @pytest.mark.parametrize(
        "sql",
        [
            "DROP TABLE tasks",
            "DELETE FROM tasks",
            "UPDATE tasks SET title = 'x'",
            "INSERT INTO tasks (title) VALUES ('x')",
            "TRUNCATE tasks",
            "CREATE TABLE evil (id int)",
            "ALTER TABLE tasks ADD COLUMN evil int",
            "GRANT SELECT ON tasks TO PUBLIC",
        ],
    )
    def test_a_statement_that_is_not_a_select_is_refused(self, sql):
        assert refusal(sql) == QueryMessages.READ_ONLY

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT title FROM tasks; DROP TABLE tasks",
            "SELECT title FROM tasks; SELECT title FROM tasks",
        ],
    )
    def test_a_second_statement_is_refused(self, sql):
        assert refusal(sql) == QueryMessages.ONE_STATEMENT_ONLY

    def test_a_trailing_semicolon_is_not_a_second_statement(self):
        assert resolve("SELECT title FROM tasks;").sql

    @pytest.mark.parametrize(
        "sql",
        [
            "COPY tasks TO '/tmp/out'",
            "SET work_mem = '1GB'",
            "BEGIN",
        ],
    )
    def test_no_command_but_a_query(self, sql):
        assert refusal(sql) in {
            QueryMessages.READ_ONLY,
            QueryMessages.UNPARSEABLE,
        }

    def test_a_lock_is_not_a_read(self):
        assert refusal("SELECT title FROM tasks FOR UPDATE") == (
            QueryMessages.UNSUPPORTED_SYNTAX
        )

    def test_set_operations_are_not_accepted(self):
        """Read-only, but the surface admits one SELECT and this is two."""
        assert refusal("SELECT 1 UNION SELECT 2") == (QueryMessages.UNSUPPORTED_SYNTAX)


class TestNamesResolveThroughTheRegistry:
    def test_a_relation_the_registry_does_not_offer(self):
        assert refusal("SELECT id FROM users") == QueryMessages.UNKNOWN_RELATION

    def test_a_schema_qualified_relation(self):
        """A relation is named on its own; the search path decides where it
        lives, and it is set to one guild's schema."""
        assert refusal("SELECT usename FROM pg_catalog.pg_user") == (
            QueryMessages.QUALIFIED_RELATION
        )
        assert refusal("SELECT id FROM public.users") == (
            QueryMessages.QUALIFIED_RELATION
        )

    def test_a_field_the_dataset_does_not_have(self):
        assert refusal("SELECT nope FROM tasks") == QueryMessages.UNKNOWN_FIELD

    def test_a_computed_field_has_no_column_to_name(self):
        """``status_category`` is a subquery the filter path builds, not a
        column, so there is nothing for a SELECT to read yet."""
        assert refusal("SELECT status_category FROM tasks") == (
            QueryMessages.FIELD_NOT_SELECTABLE
        )

    def test_an_unqualified_column_with_two_relations_in_scope(self):
        sql = "SELECT id FROM tasks JOIN projects ON tasks.project_id = projects.id"
        assert refusal(sql) == QueryMessages.AMBIGUOUS_FIELD

    def test_one_relation_needs_no_qualifier(self):
        assert "title" in resolve("SELECT title FROM tasks").sql

    def test_a_table_joined_to_itself_is_two_relations(self):
        """Two aliases of one dataset are two relations in scope, so a bare
        column of it names both and has to say which."""
        sql = "SELECT title FROM tasks a JOIN tasks b ON a.id = b.id"
        assert refusal(sql) == QueryMessages.AMBIGUOUS_FIELD

    def test_a_self_join_reads_with_a_qualifier(self):
        sql = "SELECT a.title FROM tasks a JOIN tasks b ON a.id = b.id"
        assert "a.title" in resolve(sql).sql

    def test_two_relations_may_not_share_an_alias(self):
        sql = "SELECT t.id FROM tasks t JOIN projects t ON true"
        assert refusal(sql) == QueryMessages.DUPLICATE_ALIAS

    def test_a_wildcard_is_not_a_column_list(self):
        """``*`` means whatever the table happens to hold, which is not
        something a saved tile can rely on."""
        assert refusal("SELECT * FROM tasks") == QueryMessages.STAR_NOT_ALLOWED
        assert refusal("SELECT t.* FROM tasks t") == QueryMessages.STAR_NOT_ALLOWED

    def test_count_of_everything_names_no_column(self):
        assert resolve("SELECT count(*) AS n FROM tasks").sql

    def test_an_output_alias_is_a_name_where_the_output_exists(self):
        """``ORDER BY n`` names the count, and is written as its position."""
        resolved = resolve("SELECT count(*) AS n FROM tasks GROUP BY title ORDER BY n")
        assert "ORDER BY 1" in resolved.sql

    def test_a_grouping_names_an_output_only_where_no_field_has_the_name(self):
        """Postgres reads a bare ``GROUP BY`` name as a column first."""
        assert (
            "GROUP BY 1"
            in resolve(
                "SELECT name AS label, count(*) AS n FROM files GROUP BY label"
            ).sql
        )
        assert (
            "GROUP BY priority, title"
            in resolve(
                "SELECT title AS priority, count(*) AS n FROM tasks GROUP BY priority, title"
            ).sql
        )

    @pytest.mark.parametrize(
        "sql",
        [
            # Inside an expression, and inside a window, the word is a column.
            "SELECT name AS content FROM files ORDER BY lower(content)",
            "SELECT name AS content, count(*) AS n FROM files GROUP BY lower(content)",
            "SELECT count(*) AS n, sum(count(*)) OVER (ORDER BY n) AS t "
            "FROM tasks GROUP BY title",
        ],
    )
    def test_an_output_alias_inside_an_expression_is_a_column(self, sql):
        assert refusal(sql) == QueryMessages.UNKNOWN_FIELD

    def test_an_alias_two_outputs_share_orders_nothing(self):
        assert (
            refusal("SELECT title AS a, priority AS a FROM tasks ORDER BY a")
            == QueryMessages.AMBIGUOUS_FIELD
        )

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT title AS n FROM tasks WHERE n = 'x'",
            "SELECT count(*) AS n FROM tasks GROUP BY title HAVING n > 1",
        ],
    )
    def test_an_output_alias_is_a_column_everywhere_else(self, sql):
        """WHERE and HAVING are evaluated before the output exists, so a name
        there has to be a column and this one is not."""
        assert refusal(sql) == QueryMessages.UNKNOWN_FIELD

    def test_the_relations_read_are_reported(self):
        """The caller decides whether this reader may read them, so it has to
        be told which they are."""
        sql = "SELECT p.name FROM projects p JOIN tasks k ON k.project_id = p.id"
        assert resolve(sql).relations == ("projects", "tasks")


class TestStructuralCost:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT tasks.id FROM tasks, projects",
            "SELECT tasks.id FROM tasks CROSS JOIN projects",
            "SELECT tasks.id FROM tasks JOIN projects ON true",
        ],
    )
    def test_a_join_needs_something_joining_it(self, sql):
        """Every row against every row is the one shape whose cost grows
        faster than the data, and it is visible before anything is planned."""
        assert refusal(sql) in {
            QueryMessages.JOIN_WITHOUT_CONDITION,
            QueryMessages.UNSUPPORTED_SYNTAX,
        }

    def test_a_condition_that_pairs_nothing_is_not_a_join(self):
        """``ON true`` reads as a join and behaves as a cross product."""
        sql = "SELECT tasks.id FROM tasks JOIN projects ON true"
        assert refusal(sql) == QueryMessages.JOIN_WITHOUT_CONDITION

    def test_a_condition_naming_only_one_side_is_not_a_join(self):
        sql = "SELECT tasks.id FROM tasks JOIN projects ON tasks.id > 0"
        assert refusal(sql) == QueryMessages.JOIN_WITHOUT_CONDITION

    def test_naming_both_sides_without_relating_them_is_not_a_join(self):
        """Two predicates that each filter one relation still pair every
        surviving row with every other."""
        sql = "SELECT t.id FROM tasks t JOIN projects p ON t.id > 0 AND p.id > 0"
        assert refusal(sql) == QueryMessages.JOIN_WITHOUT_CONDITION

    def test_a_relating_predicate_alongside_a_filter_is_a_join(self):
        sql = (
            "SELECT t.id FROM tasks t JOIN projects p "
            "ON t.project_id = p.id AND p.archived_at IS NULL"
        )
        assert resolve(sql).relations == ("projects", "tasks")

    def test_a_later_join_must_tie_in_what_it_adds(self):
        """The third join's condition relates the first two relations, so the
        one it adds is joined to nothing and multiplies the result."""
        sql = (
            "SELECT a.id FROM tasks a "
            "JOIN tasks b ON a.id = b.id "
            "JOIN tasks c ON a.id = b.id"
        )
        assert refusal(sql) == QueryMessages.JOIN_WITHOUT_CONDITION

    def test_a_chain_of_joins_each_tying_in_is_accepted(self):
        sql = (
            "SELECT a.id FROM tasks a "
            "JOIN tasks b ON a.project_id = b.project_id "
            "JOIN projects c ON b.project_id = c.id"
        )
        assert resolve(sql).relations == ("projects", "tasks")

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT a.title FROM tasks a JOIN tasks b USING (id)",
            "SELECT a.title FROM tasks a JOIN tasks b USING (nope)",
            "SELECT a.title FROM tasks a JOIN tasks b USING (status_category)",
        ],
    )
    def test_using_is_not_accepted(self, sql):
        """It names columns positionally rather than as column references, so
        the resolving pass never sees them. ON says the same thing in a form
        that resolves."""
        assert refusal(sql) == QueryMessages.UNSUPPORTED_SYNTAX

    def test_a_join_that_pairs_rows_is_accepted(self):
        sql = "SELECT p.name FROM projects p JOIN tasks k ON k.project_id = p.id"
        assert resolve(sql).relations == ("projects", "tasks")

    def test_a_self_join_is_bound_by_its_aliases(self):
        sql = "SELECT a.title FROM tasks a JOIN tasks b ON a.project_id = b.project_id"
        assert resolve(sql).sql

    def test_a_statement_may_name_only_so_many_relations(self):
        joins = " ".join(
            f"JOIN tasks t{i} ON t{i}.project_id = p.id" for i in range(1, 6)
        )
        assert refusal(f"SELECT p.name FROM projects p {joins}") == (
            QueryMessages.TOO_MANY_RELATIONS
        )


class TestNothingOfTheOriginalTravels:
    def test_the_statement_is_generated_not_forwarded(self):
        """Physical names, and only names the registry produced."""
        resolved = resolve("SELECT title FROM tasks WHERE priority = 'urgent'")
        assert resolved.sql == "SELECT title FROM tasks WHERE priority = $1"
        assert resolved.parameters == ("urgent",)

    def test_comments_do_not_survive(self):
        """Comments are dropped when the statement is generated."""
        resolved = resolve("SELECT title /* a note */ FROM tasks -- trailing\n")
        assert "note" not in resolved.sql
        assert "trailing" not in resolved.sql

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT title /* /* x */ */ FROM tasks",
            "SELECT title /* /* */ , evil */ FROM tasks",
        ],
    )
    def test_a_nested_comment_is_read_the_way_the_server_reads_it(self, sql):
        """Postgres nests block comments, so all of that is one comment and
        ``evil`` is inside it. A parser that did not nest them would end the
        comment at the first ``*/`` and read the rest as part of the
        statement; this is the case the server's own grammar settles."""
        assert resolve(sql).sql == "SELECT title FROM tasks"

    def test_literals_leave_as_parameters(self):
        resolved = resolve("SELECT title FROM tasks WHERE title = 'x' AND id > 3")
        assert resolved.parameters == ("x", 3)
        assert "'x'" not in resolved.sql

    def test_a_quote_in_a_literal_is_a_value_not_syntax(self):
        resolved = resolve("SELECT title FROM tasks WHERE title = 'it''s; DROP--'")
        assert "DROP" not in resolved.sql
        assert resolved.parameters == ("it's; DROP--",)

    def test_a_constant_alone_in_the_select_list_stays_a_constant(self):
        """It has nothing to take a type from, and Postgres reads a bare
        parameter there as text. Compared against a column it keeps that
        column's type, which is what makes an enum comparison work."""
        resolved = resolve("SELECT 1 AS a FROM tasks")
        assert "1 AS a" in resolved.sql
        assert not resolved.parameters

        compared = resolve("SELECT title FROM tasks WHERE priority = 'urgent'")
        assert compared.parameters == ("urgent",)

    def test_an_ordinal_stays_an_ordinal(self):
        """``GROUP BY 1`` selects the first output column; a parameter there
        would be the number one."""
        resolved = resolve("SELECT title, count(*) AS n FROM tasks GROUP BY 1")
        assert "GROUP BY 1" in resolved.sql
        assert not resolved.parameters

    def test_a_function_argument_stays_a_constant(self):
        """``concat`` takes ``"any"``, so it gives its arguments no type to
        take and Postgres will not plan a parameter in one. The separator is
        written where the function can read it, and the value compared against
        a column beside it still binds."""
        resolved = resolve(
            "SELECT concat(title, ' · ', priority) AS card FROM tasks "
            "WHERE priority = 'high'"
        )
        assert "concat(title, ' · ', priority)" in resolved.sql
        assert resolved.parameters == ("high",)


class TestTheFunctionSurface:
    @pytest.mark.parametrize(
        "call",
        [
            "pg_read_file('/etc/passwd')",
            "pg_sleep(10)",
            "current_setting('app.current_user_id')",
            "pg_ls_dir('.')",
            "dblink('', '')",
            "query_to_xml('SELECT 1', true, true, '')",
            "lo_import('/etc/passwd')",
        ],
    )
    def test_a_function_nobody_listed_is_refused(self, call):
        assert refusal(f"SELECT {call} FROM tasks") == (
            QueryMessages.UNSUPPORTED_FUNCTION
        )

    @pytest.mark.parametrize("call", SUPPORTED_CALLS)
    def test_every_supported_call_is_accepted(self, call):
        """The declared spellings and the accepted node types are the same
        set, which is the point of deriving one from the other."""
        assert resolve(f"SELECT {call} AS v FROM tasks").sql

    def test_structure_that_the_parser_calls_a_function_still_works(self):
        """``AND`` and ``CASE`` are a kind of function to this parser, and
        they are plainly structure."""
        sql = (
            "SELECT CASE WHEN archived_at IS NOT NULL THEN 'old' ELSE 'live' END AS bucket "
            "FROM projects WHERE archived_at IS NULL AND is_template = false"
        )
        assert resolve(sql).sql


class TestShapesATileAsks:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT count(*) AS n FROM tasks",
            "SELECT title, due_date FROM tasks WHERE due_date < now() ORDER BY due_date",
            "SELECT date_trunc('month', created_at) AS m, count(*) AS n "
            "FROM tasks GROUP BY m ORDER BY m",
            "SELECT p.name, count(*) AS n FROM projects p "
            "JOIN tasks k ON k.project_id = p.id "
            "WHERE p.archived_at IS NULL GROUP BY p.name ORDER BY n DESC LIMIT 10",
            "SELECT title FROM tasks WHERE title ILIKE '%bug%' LIMIT 50",
            "SELECT count(*) AS n FROM tasks "
            "WHERE due_date BETWEEN '2026-01-01' AND '2026-12-31'",
        ],
    )
    def test_it_resolves(self, sql):
        assert resolve(sql).sql


class TestAGroupedExpressionKeepsItsShape:
    """``GROUP BY`` finds its output column by matching the expression, so both
    copies have to be written the same way. A parameter is numbered by where it
    is met, and the copies are met in different clauses — so a constant inside
    a grouped expression stays a constant, on both sides."""

    def test_a_bucket_is_written_the_same_way_twice(self):
        resolved = resolve(
            "SELECT date_trunc('day', completed_at) AS day, count(*) AS n "
            "FROM tasks GROUP BY date_trunc('day', completed_at) "
            "ORDER BY date_trunc('day', completed_at)"
        )
        assert resolved.parameters == ()
        assert resolved.sql.count("date_trunc('day', completed_at)") == 3

    def test_a_value_compared_against_a_column_is_still_bound(self):
        """The narrowing keeps its parameter: that is what lets an unadorned
        value take the column's type rather than reading as text."""
        resolved = resolve(
            "SELECT date_trunc('day', completed_at) AS day, count(*) AS n "
            "FROM tasks WHERE priority = 'high' "
            "GROUP BY date_trunc('day', completed_at)"
        )
        assert resolved.parameters == ("high",)
        assert "priority = $1" in resolved.sql

    def test_an_ordinal_still_selects_an_output_column(self):
        """``GROUP BY 1`` matches by position, so the expression it names has
        nothing to agree with — and the bucket it names is a function's
        argument, which stays written where the function can read it."""
        resolved = resolve(
            "SELECT date_trunc('month', due_date) AS m, count(*) AS n "
            "FROM tasks GROUP BY 1 ORDER BY 1"
        )
        assert resolved.parameters == ()
        assert "date_trunc('month', due_date)" in resolved.sql
        assert "GROUP BY 1" in resolved.sql


class TestReachingThroughADeclaredRelation:
    """A dataset says what it can be read alongside, so a name qualified by a
    relation is a join nobody had to write."""

    def test_a_person_is_two_joins_nobody_wrote(self):
        resolved = resolve(
            "SELECT assignee.display_name AS person, count(*) AS n "
            "FROM tasks GROUP BY 1"
        )
        assert set(resolved.relations) == {"tasks", "task_assignees", "members"}
        assert "INNER JOIN" in resolved.sql

    def test_the_joins_it_writes_are_bound(self):
        """Which is what the check on a join asks. Written from the declaration
        rather than by a reader, but held to the same rule."""
        assert (
            resolve("SELECT status.name AS s FROM tasks").sql.count("INNER JOIN") == 1
        )

    def test_an_unqualified_column_still_reads(self):
        """Reaching through a relation puts a second relation in scope, and a
        column of the first must not become ambiguous for it."""
        resolved = resolve("SELECT title, status.name AS stage FROM tasks")
        assert "title" in resolved.sql

    def test_a_name_two_relations_share_is_ambiguous(self):
        with pytest.raises(QueryError) as refused:
            resolve(
                "SELECT id FROM tasks JOIN projects ON projects.id = tasks.project_id"
            )
        assert refused.value.code == QueryMessages.AMBIGUOUS_FIELD

    def test_a_name_nothing_has_is_unknown_rather_than_ambiguous(self):
        with pytest.raises(QueryError) as refused:
            resolve("SELECT nowhere FROM tasks")
        assert refused.value.code == QueryMessages.UNKNOWN_FIELD

    def test_a_relation_nobody_declared_is_still_unknown(self):
        with pytest.raises(QueryError) as refused:
            resolve("SELECT nowhere.x FROM tasks")
        assert refused.value.code == QueryMessages.UNKNOWN_RELATION


class TestSubqueriesAreNotAcceptedYet:
    """Deny-by-default means these are refused rather than half-supported;
    admitting them is adding a scope to resolve against, not removing a check."""

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT title FROM tasks WHERE id IN (SELECT id FROM projects)",
            "WITH t AS (SELECT id FROM tasks) SELECT id FROM t",
            "SELECT (SELECT count(*) FROM tasks) AS n FROM projects",
        ],
    )
    def test_refused(self, sql):
        assert refusal(sql) in {
            QueryMessages.UNSUPPORTED_SYNTAX,
            QueryMessages.UNKNOWN_RELATION,
        }


class TestWindows:
    """``OVER (...)`` reads the rows the statement already reads."""

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT date_trunc('week', completed_at) AS week, "
            "sum(count(*)) OVER (ORDER BY date_trunc('week', completed_at)) AS total "
            "FROM tasks GROUP BY 1",
            "SELECT title, row_number() OVER (PARTITION BY priority ORDER BY due_date) "
            "AS r FROM tasks",
            "SELECT title, lag(title, 1) OVER w AS prev FROM tasks "
            "WINDOW w AS (ORDER BY due_date)",
        ],
    )
    def test_it_resolves(self, sql):
        assert resolve(sql).sql

    def test_its_constants_are_written_as_they_were(self):
        """A frame's offset is typed by the ordering it counts along, and an
        ordering has to match its twin in ``GROUP BY``."""
        resolved = resolve(
            "SELECT priority = 'high' AS hot, "
            "sum(count(*)) OVER (ORDER BY priority = 'high' "
            "RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS t "
            "FROM tasks GROUP BY priority = 'high'"
        )
        assert resolved.parameters == ()
        assert "OVER (ORDER BY priority = 'high'" in resolved.sql

    @pytest.mark.parametrize("grouping", ["hot", "1"])
    def test_an_output_grouped_by_position_matches_its_window(self, grouping):
        """``GROUP BY hot`` and ``GROUP BY 1`` group the whole comparison, so
        it has to be written the way the window repeats it."""
        resolved = resolve(
            "SELECT priority = 'high' AS hot, "
            "sum(count(*)) OVER (ORDER BY priority = 'high') AS t "
            f"FROM tasks GROUP BY {grouping}"
        )
        assert resolved.parameters == ()
        assert "SELECT priority = 'high' AS hot" in resolved.sql

    def test_a_window_reads_only_declared_fields(self):
        assert (
            refusal(
                "SELECT row_number() OVER (ORDER BY yjs_state) AS r FROM wiki_pages"
            )
            == QueryMessages.UNKNOWN_FIELD
        )


def test_an_output_that_is_a_field_carries_the_registrys_type():
    """Read before the names are rewritten, and by the name the reader wrote."""
    assert resolve("SELECT project_id, title FROM tasks").column_types == (
        FieldType.reference,
        FieldType.text,
    )


def test_a_qualified_field_carries_its_type_too():
    assert resolve("SELECT t.priority FROM tasks t").column_types == (FieldType.enum,)


def test_an_output_built_from_a_field_carries_nothing():
    """An expression has no field to ask about, and is left to the database."""
    assert resolve(
        "SELECT lower(title) AS t, length(title) AS n FROM tasks"
    ).column_types == (
        None,
        None,
    )


class TestAskingForThePlan:
    """``EXPLAIN`` takes a statement where a value would go, so there is no
    parameter to bind it as. What must hold instead is that wrapping a
    statement in it yields that statement and nothing more."""

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT '''; DROP TABLE tasks; --' AS c FROM tasks",
            'SELECT title AS "a"" ; DROP TABLE x; --" FROM tasks',
            "SELECT count(*) AS n FROM tasks GROUP BY '''; DROP --'",
            r"SELECT E'trailing backslash \\' AS c FROM tasks",
        ],
    )
    def test_the_readers_own_text_stays_one_statement(self, sql):
        """A constant standing alone in a select list, and an identifier a
        reader aliased, are the reader's own words carried through: they are
        not bound, they are written back out."""
        statements = parse_sql(resolve(sql).explain())
        assert len(statements) == 1
        root = statements[0].stmt
        assert isinstance(root, ast.ExplainStmt)
        assert isinstance(root.query, ast.SelectStmt)

    def test_the_plan_is_asked_for_as_json(self):
        assert "format json" in resolve("SELECT title FROM tasks").explain().lower()


class TestTheReaderIsANameAStatementMayUse:
    """``me`` is the one name a statement takes that is not a column.

    It stands where a value stands, so a saved statement holds no reader in it
    and answers from whoever is looking at the tile.
    """

    def test_it_becomes_the_requesting_user(self):
        resolved = resolve("SELECT count(*) AS n FROM tasks WHERE created_by = me")
        assert "app.current_user_id" in resolved.sql
        assert "me" not in resolved.sql.split("WHERE")[1].split("current_setting")[0]

    def test_it_is_not_a_value_the_reader_wrote(self):
        """Bound parameters are the reader's literals. The reader is not one of
        them: nothing of theirs is carried, so there is nothing to bind."""
        assert resolve("SELECT title FROM tasks WHERE created_by = me").parameters == ()

    def test_the_expansion_carries_no_parameters_of_its_own(self):
        """What it expands to is the surface's own text, written after the
        literals are bound rather than before, so its constants stay
        constants."""
        resolved = resolve(
            "SELECT title FROM tasks WHERE created_by = me AND priority = 'high'"
        )
        assert resolved.parameters == ("high",)
        assert "'app.current_user_id'" in resolved.sql

    def test_it_reads_beside_a_relation_it_was_reached_through(self):
        resolved = resolve("SELECT count(*) AS n FROM tasks WHERE assignee.id = me")
        assert "app.current_user_id" in resolved.sql
        assert "task_assignees" in resolved.sql

    def test_it_can_be_named_more_than_once(self):
        resolved = resolve(
            "SELECT count(*) AS n FROM tasks WHERE created_by = me OR assignee.id = me"
        )
        assert resolved.sql.count("app.current_user_id") == 2

    def test_it_stands_where_a_person_is_compared(self):
        for sql in (
            "SELECT count(*) AS n FROM tasks WHERE me = created_by",
            "SELECT count(*) AS n FROM tasks WHERE created_by IN (me, 3)",
            "SELECT CASE WHEN created_by = me THEN 'mine' ELSE 'theirs' END AS whose, "
            "count(*) AS n FROM tasks GROUP BY 1",
        ):
            assert "app.current_user_id" in resolve(sql).sql

    @pytest.mark.parametrize(
        "sql",
        [
            # A title is text, and the reader is a person.
            "SELECT count(*) AS n FROM tasks WHERE title = me",
            # Nothing to be a person beside.
            "SELECT me FROM tasks",
            "SELECT count(me) AS n FROM tasks",
            "SELECT count(*) AS n FROM tasks GROUP BY me",
            "SELECT count(*) AS n FROM tasks WHERE me IS NULL",
        ],
    )
    def test_anywhere_it_says_nothing_is_refused_while_it_is_written(self, sql):
        """The builder only writes the reader against a field that holds one.
        A statement somebody typed answers to the same rule, and hears about it
        at the keyboard rather than on the tile."""
        assert refusal(sql) == QueryMessages.VIEWER_NEEDS_A_PERSON

    def test_an_output_column_may_not_be_called_it(self):
        """``order by me`` has to mean one thing."""
        assert refusal("SELECT count(*) AS me FROM tasks") == (
            QueryMessages.RESERVED_NAME
        )

    def test_a_relation_may_not_be_called_it_either(self):
        assert refusal("SELECT me.title FROM tasks me") == QueryMessages.RESERVED_NAME


class TestAConstantACastNamesTheTypeOf:
    """``CAST('30 days' AS interval)`` and friends.

    A constant is normally bound as a parameter, which is what lets
    ``priority = $1`` take the column's type. A cast is the other way round:
    the constant has no column to take a type from, the cast IS the type, and
    binding it hands the driver a string where an interval wants a
    ``timedelta``. Nothing caught it earlier — planning the statement succeeds,
    and only running it binds anything — so a dashboard measuring a stretch of
    time saved fine, described fine, and failed every time it drew.
    """

    def test_the_constant_is_written_through_rather_than_bound(self):
        statement = resolve(
            "SELECT count(*) AS n FROM tasks "
            "WHERE completed_at >= now() - CAST('30 days' AS interval)"
        )
        assert "'30 days'" in statement.sql
        assert "30 days" not in [str(value) for value in statement.parameters]

    def test_a_constant_with_a_column_to_take_its_type_from_still_binds(self):
        """The rule is about casts, not about constants."""
        statement = resolve("SELECT title FROM tasks WHERE priority = 'high'")
        assert statement.parameters == ("high",)

    def test_both_in_one_statement(self):
        statement = resolve(
            "SELECT title FROM tasks WHERE priority = 'high' "
            "AND completed_at >= now() - CAST('7 days' AS interval)"
        )
        assert statement.parameters == ("high",)
        assert "'7 days'" in statement.sql


@pytest.mark.parametrize(
    ("sql", "grains"),
    [
        (
            "SELECT date_trunc('month', due_date) AS m, count(*) AS n "
            "FROM tasks GROUP BY 1",
            ("month", None),
        ),
        ("SELECT DATE_TRUNC('Quarter', due_date) FROM tasks", ("quarter",)),
        (
            "SELECT date_trunc('month', due_date)::date AS month, count(*) AS n "
            "FROM tasks GROUP BY 1",
            ("month", None),
        ),
        ("SELECT CAST(date_trunc('week', due_date) AS date) FROM tasks", ("week",)),
        ("SELECT due_date, title FROM tasks", (None, None)),
        ("SELECT date_trunc('hour', due_date) FROM tasks", (None,)),
    ],
)
def test_a_rounded_date_says_what_it_is_rounded_to(sql, grains):
    """A chart labels a period by the unit the statement rounded to, not by
    guessing from the dates that came back."""
    assert resolve(sql).column_grains == grains


_BUDGET = SheetCall("Budget", "Q3!A1:C")
_READ = {
    _BUDGET: Sheet.from_range(
        _BUDGET,
        {
            "columns": [
                {"name": "Region", "type": "text"},
                {"name": "Amount", "type": "number"},
                {"name": "Due", "type": "date"},
            ],
            "rows": [["North", 10, "2026-01-05"], ["South", 20, None]],
            "sheets": ["Q3"],
        },
    )
}


def test_a_sheet_is_read_like_a_dataset_once_its_cells_are():
    """Before its cells are read a sheet holds any name and the statement is not
    runnable; once read, its header names its columns ignoring case, the cells
    are one bound parameter, and an output keeps the header it named."""
    sql = (
        "SELECT region, sum(amount) AS total, date_trunc('month', s.due) AS m "
        "FROM sheet('Budget', 'Q3!A1:C') AS s GROUP BY region, m"
    )
    unread = resolve(sql)
    assert unread.unread == (_BUDGET,)
    assert unread.relations == ("files",)

    read = resolve(sql, _READ)
    assert read.unread == ()
    assert "json_to_recordset($1) AS s(c1 text, c2 numeric, c3 date)" in read.sql
    assert 's.c1 AS "Region"' in read.sql
    assert json.loads(read.parameters[-1])[0] == {
        "c1": "North",
        "c2": 10,
        "c3": "2026-01-05",
    }
    assert read.column_types[0] is FieldType.text
    assert read.column_grains[2] == "month"


@pytest.mark.parametrize(
    ("sql", "code"),
    [
        ("SELECT a FROM sheet('Budget', 'Q3!A1:C', 3)", QueryMessages.SHEET_ARGUMENTS),
        ("SELECT a FROM sheet(1.5)", QueryMessages.SHEET_ARGUMENTS),
        ("SELECT a FROM sheet(region)", QueryMessages.SHEET_ARGUMENTS),
        ("SELECT a FROM sheet('Budget', 7)", QueryMessages.SHEET_ARGUMENTS),
        ("SELECT a FROM generate_series(1, 2)", QueryMessages.UNSUPPORTED_FUNCTION),
        ("SELECT a FROM LATERAL sheet('Budget')", QueryMessages.UNSUPPORTED_SYNTAX),
        (
            "SELECT a FROM sheet('Budget') WITH ORDINALITY",
            QueryMessages.UNSUPPORTED_SYNTAX,
        ),
        ("SELECT a FROM sheet('Budget') AS s(a, b)", QueryMessages.UNSUPPORTED_SYNTAX),
        ("SELECT nope FROM sheet('Budget', 'Q3!A1:C')", QueryMessages.UNKNOWN_FIELD),
        (
            "SELECT region FROM sheet('Budget', 'Q3!A1:C') AS a "
            "JOIN sheet('Budget', 'Q3!A1:C') AS b ON a.region = b.region",
            QueryMessages.AMBIGUOUS_FIELD,
        ),
        (
            "SELECT a FROM sheet('Budget'), sheet('Budget')",
            QueryMessages.JOIN_WITHOUT_CONDITION,
        ),
    ],
)
def test_a_sheet_call_says_what_it_got_wrong(sql, code):
    with pytest.raises(QueryError) as refused:
        resolve(sql, _READ)
    assert refused.value.code == code


_ORDERS = PluginCall("acme.shop", "orders", (("range", "30d"), ("tags", ("a", "b"))))


def test_a_plugin_endpoint_is_read_like_a_dataset_once_it_answers():
    """Its parameters are named arguments; its rows are one bound parameter
    under the columns the endpoint declares, a value of another type read as
    nothing; and it joins what any relation joins."""
    sql = (
        "SELECT t.title, o.status, sum(o.total) AS total "
        "FROM plugin('acme.shop', 'orders', tags => ARRAY['a', 'b'], range => '30d') AS o "
        "JOIN tasks AS t ON t.title = o.status GROUP BY t.title, o.status"
    )
    unread = resolve(sql)
    assert unread.unread == (_ORDERS,)
    assert unread.relations == ("plugins", "tasks")

    rows = PluginRows.from_rows(
        _ORDERS,
        (("status", "string"), ("total", "int"), ("at", "datetime"), ("ok", "bool")),
        [
            {"status": "open", "total": 4, "at": "2026-11-01T10:00:00Z", "ok": True},
            {"status": "shut", "total": "four", "at": "soon", "ok": "yes"},
        ],
    )
    read = resolve(sql, {_ORDERS: rows})
    assert read.unread == ()
    assert (
        "json_to_recordset($1) AS o(c1 text, c2 numeric, c3 timestamptz, c4 boolean)"
        in read.sql
    )
    assert json.loads(read.parameters[-1]) == [
        {"c1": "open", "c2": 4, "c3": "2026-11-01T10:00:00Z", "c4": True},
        {"c1": "shut", "c2": None, "c3": None, "c4": None},
    ]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT a FROM plugin('acme.shop')",
        "SELECT a FROM plugin('acme.shop', 'orders', 'positional')",
        "SELECT a FROM plugin('acme.shop', range => '30d', 'orders')",
        "SELECT a FROM plugin('acme.shop', 'orders', range => status)",
        "SELECT a FROM plugin('acme.shop', 'orders', range => NULL)",
        "SELECT a FROM plugin('acme.shop', 'orders', tags => ARRAY[ARRAY['a']])",
        "SELECT a FROM plugin(1, 'orders')",
    ],
)
def test_a_plugin_call_takes_constants_by_name(sql):
    with pytest.raises(QueryError) as refused:
        resolve(sql)
    assert refused.value.code == QueryMessages.PLUGIN_ARGUMENTS


def test_a_name_both_a_dataset_and_a_read_sheet_hold_is_ambiguous():
    with pytest.raises(QueryError) as refused:
        resolve(
            "SELECT title FROM sheet('Budget', 'Q3!A1:C') AS s "
            "JOIN tasks AS t ON t.title = s.region",
            {
                _BUDGET: Sheet.from_range(
                    _BUDGET,
                    {
                        "columns": [
                            {"name": "title", "type": "text"},
                            {"name": "region", "type": "text"},
                        ]
                    },
                )
            },
        )
    assert refused.value.code == QueryMessages.AMBIGUOUS_FIELD


def test_a_statement_names_rows_by_id_where_a_column_holds_one():
    """Each constant a key column is compared with, and the file ``sheet()``
    reads, is put through the mapping in place; a person, a constant in a
    shape it does not read, and a statement that does not resolve are left
    as they were."""
    moved = {
        (SearchEntityType.project, 12): 120,
        (SearchEntityType.task, 7): 70,
        (SearchEntityType.file, 42): 420,
    }

    def remap(kind: SearchEntityType, entity_id: int) -> int:
        return moved.get((kind, entity_id), 0)

    for sql, expected in (
        (
            "SELECT count(*) AS n FROM tasks WHERE project_id = 12 AND created_by = 12",
            "SELECT count(*) AS n FROM tasks WHERE project_id = 120 AND created_by = 12",
        ),
        (
            "SELECT t.title FROM tasks t WHERE t.id IN (7, 8) LIMIT 12",
            "SELECT t.title FROM tasks t WHERE t.id IN (70, 0) LIMIT 12",
        ),
        (
            "SELECT title FROM tasks WHERE project.id <> 12 -- the old one",
            "SELECT title FROM tasks WHERE project.id <> 120 -- the old one",
        ),
        (
            "SELECT b.x FROM sheet(42, 'Q3!A1:D') AS b JOIN projects p ON p.name = b.x",
            "SELECT b.x FROM sheet(420, 'Q3!A1:D') AS b JOIN projects p ON p.name = b.x",
        ),
        (
            "SELECT title FROM tasks WHERE project_id = CAST(12 AS integer)",
            "SELECT title FROM tasks WHERE project_id = CAST(12 AS integer)",
        ),
        (
            "SELECT title FROM tasks WHERE project_id IN (1 + 12, NULL, 12)",
            "SELECT title FROM tasks WHERE project_id IN (1 + 12, NULL, 120)",
        ),
        ("SELECT a FROM nowhere WHERE id = 12", "SELECT a FROM nowhere WHERE id = 12"),
    ):
        assert remap_ids(sql, remap) == expected, sql
