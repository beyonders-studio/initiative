"""The registry expresses what the task filter path already did.

This phase re-points an existing surface at a new declaration, so the only
interesting question is whether anything changed. Two halves answer it: the set
of filterable names has to match what the endpoint's builder produced, and each
virtual field has to compile to the same clause it always did.

The endpoint tests are the other half — they exercise these fields through real
requests, and they were not touched.
"""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql

from app.core.tools import Tool
from app.models.tenant.task import Task, TaskAssignee
from app.schemas.query import FilterOp
from app.services.fields import (
    FieldContext,
    allowed_fields,
    allowed_ops,
    dataset,
    default_filters,
    describe,
    sort_fields,
)
from app.services.fields.derive import derive_fields
from app.services.fields.grouping import groupable
from app.services.fields.registry import dataset_names
from app.services.fields.spec import ControlKind, FieldType
from app.services.query.resolve import resolve

pytestmark = pytest.mark.always


def _names() -> list[str]:
    """The datasets, for parametrising. Read at collection so a new one is
    covered by the checks below without an edit here."""
    return sorted(dataset_names())


def _ctx(
    *,
    guild_id: int = 7,
    user_id: int = 42,
    property_definitions: dict | None = None,
    tz: str | None = None,
) -> FieldContext:
    """Named explicitly rather than **kwargs: a context this helper does not
    know about should be a TypeError, not a silently dropped argument."""
    return FieldContext(
        guild_id=guild_id,
        user_id=user_id,
        property_definitions=property_definitions or {},
        tz=tz,
    )


def _sql(clause) -> str:
    return str(
        clause.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


#: The fields beyond the model's own columns.
VIRTUAL_FIELDS = {
    "status_category",
    "assignee_ids",
    "tag_ids",
    "initiative_ids",
    "property_values",
    "plugin_values",
}


#: Columns a comparison cannot be built against, and why. Everything else on
#: the model becomes a field without anybody listing it.
NOT_FILTERABLE = {
    "checklist": "a JSON list of steps — no operator means anything against it",
    "recurrence_carry": "a JSON object of values kept for the next task in a "
    "series — no operator means anything against it",
    "guild_id": "references a table no picker browses, and a request is "
    "already scoped to one guild",
}


class TestCoverage:
    def test_the_fields_are_the_fillable_columns_plus_the_virtual_ones(self):
        """Derived from the model, so a column added tomorrow is filterable
        the day it is added — including a decorated ``str`` column — and a
        field nobody asked for is as much a change as a missing one. A column
        resolves to itself; a virtual field to its resolver."""
        resolved = allowed_fields("tasks", _ctx())
        columns = {c.name for c in Task.__table__.columns} - set(NOT_FILTERABLE)
        assert set(resolved) == columns | VIRTUAL_FIELDS
        assert resolved["title"] is Task.title
        for name in VIRTUAL_FIELDS:
            assert callable(resolved[name])

    def test_a_taggable_model_gets_its_tag_filter_without_asking(self):
        """Nearly everything is taggable and everything taggable binds the same
        way, so no dataset declares that it has tags. The model's entry in the
        tag registry is the whole of the difference between one and the next."""
        assert "tag_ids" in {spec.name for spec in derive_fields(Task)}
        assert "tag_ids" not in {spec.name for spec in derive_fields(TaskAssignee)}


class TestVirtualFields:
    """Each compiles to the clause it compiled to before."""

    def test_status_category_matches_statuses_in_those_categories(self):
        resolve = allowed_fields("tasks", _ctx())["status_category"]
        sql = _sql(resolve(FilterOp.in_, ["done"]))
        assert "task_status_id IN" in sql
        assert "'done'" in sql
        assert resolve(FilterOp.in_, []) is None

    def test_assignee_resolves_me_ids_and_emptiness(self):
        from fastapi import HTTPException

        resolve = allowed_fields("tasks", _ctx(user_id=99))["assignee_ids"]
        assert "99" in _sql(resolve(FilterOp.in_, ["me"]))
        mixed = _sql(resolve(FilterOp.in_, ["me", "5"]))
        assert "99" in mixed and "5" in mixed
        assert "NOT" in _sql(resolve(FilterOp.is_null, True)).upper()
        assert "NOT" not in _sql(resolve(FilterOp.is_null, False)).upper()
        with pytest.raises(HTTPException) as excinfo:
            resolve(FilterOp.in_, ["nope"])
        assert excinfo.value.status_code == 400

    def test_tags_resolve_within_the_routed_community(self):
        """A tag id names a row in the routed schema and nothing else: the
        clause walks the relationship edges and carries no guild leg, because
        the schema the statement runs in is the community."""
        clause = allowed_fields("tasks", _ctx(guild_id=1234))["tag_ids"](
            FilterOp.in_, [1]
        )
        sql = _sql(clause)
        assert "relationships" in sql and "tags" in sql
        assert "1234" not in sql

    def test_initiative_ids_resolve_through_projects(self):
        clause = allowed_fields("tasks", _ctx())["initiative_ids"](FilterOp.in_, [3])
        sql = _sql(clause)
        assert "project_id IN" in sql
        assert "initiative_id IN" in sql

    def test_an_unknown_or_malformed_property_contributes_nothing(self):
        resolve = allowed_fields("tasks", _ctx())["property_values"]
        assert resolve(FilterOp.eq, {"property_id": 1, "value": "x"}) is None
        assert resolve(FilterOp.eq, "not a dict") is None
        assert resolve(FilterOp.eq, {"property_id": "abc"}) is None


#: The orderings a caller relies on. Ordering is read off the column's type,
#: which admits a few more; none of these may go.
SORTABLE_FIELDS = {
    "position",
    "title",
    "due_date",
    "start_date",
    "priority",
    "created_at",
    "updated_at",
    "date_group",
}


class TestSorting:
    def test_what_orders_and_what_does_not(self):
        """A foreign key would sort by row id and a body of prose by its first
        character, so neither orders; most columns narrow without ordering, and
        ``date_group`` orders without narrowing."""
        sortable = sort_fields("tasks", _ctx())
        filterable = set(allowed_fields("tasks", _ctx()))
        assert SORTABLE_FIELDS <= set(sortable)
        assert set(sortable).isdisjoint(
            {"project_id", "task_status_id", "created_by", "description"}
        )
        assert sortable["title"] is Task.title
        assert SORTABLE_FIELDS - {"date_group"} < filterable
        assert "date_group" not in filterable

    def test_date_group_follows_the_readers_timezone(self):
        """A CASE over two dates, so there is no column to hand back; the same
        row groups differently depending on whose day it is."""
        naive = _sql(sort_fields("tasks", _ctx())["date_group"])
        aware = _sql(sort_fields("tasks", _ctx(tz="America/New_York"))["date_group"])
        assert "CASE" in naive
        assert "AT TIME ZONE" not in naive
        assert "America/New_York" in aware


#: What a filter control is offered for tasks: operators, whether it takes
#: several values, its control and its type. Bookkeeping (``id``, the tenant
#: key, ``position``, the trash columns) is hidden, and so is a field no control
#: can supply a value for (``property_values``), which a stored definition can
#: still use.
OFFERED = {
    "status_category": (["in_"], True, "select", "enum"),
    "task_status_id": (["in_"], True, "task_status", "reference"),
    "task_type_id": (["in_"], True, "task_type", "reference"),
    "priority": (["in_"], True, "select", "enum"),
    "assignee_ids": (["in_", "is_null"], True, "member", "reference"),
    "created_by": (["in_", "is_null"], True, "member", "reference"),
    "tag_ids": (["in_"], True, "tag", "reference"),
    "project_id": (["eq"], False, "project", "reference"),
    "due_date": (["gt", "gte", "is_null", "lt", "lte"], False, "date", "date"),
    "start_date": (["gt", "gte", "is_null", "lt", "lte"], False, "date", "date"),
    "completed_at": (["gt", "gte", "is_null", "lt", "lte"], False, "date", "date"),
    "archived_at": (["gt", "gte", "is_null", "lt", "lte"], False, "date", "date"),
    "created_at": (["gt", "gte", "lt", "lte"], False, "date", "date"),
    "updated_at": (["gt", "gte", "lt", "lte"], False, "date", "date"),
    "title": (["ilike"], False, "text", "text"),
    "description": (["ilike", "is_null"], False, "text", "text"),
}


class TestDescription:
    def test_what_a_control_is_offered(self):
        """A reference takes its control from the table its foreign key points
        at; a closed vocabulary carries its values straight off the column, so
        a client keeps no copy; nothing else carries options, and no entry
        carries a resolver."""
        entries = describe(dataset("tasks"))
        by_name = {entry["name"]: entry for entry in entries}
        assert {
            name: (e["ops"], e["multiple"], e["kind"], e["type"])
            for name, e in by_name.items()
        } == OFFERED
        assert by_name["priority"]["options"] == list(
            Task.__table__.columns["priority"].type.enums
        )
        assert by_name["status_category"]["options"] == [
            "backlog",
            "todo",
            "in_progress",
            "done",
        ]
        assert by_name["due_date"]["options"] == []
        assert by_name["assignee_ids"]["options"] == []
        for entry in entries:
            assert not any(callable(value) for value in entry.values())

    def test_the_author_groups_by_member(self):
        """``created_by`` is read only where its kind is ``member``, and still
        groups by the member it names."""
        tasks = dataset("tasks")
        assert groupable(tasks, tasks.by_name["created_by"])


class TestOperatorEnforcement:
    def test_a_field_declares_only_operators_its_resolver_handles(self):
        """The status-category and tag resolvers each build an ``IN`` over
        their value, so ``in_`` is the one operator each of them answers; the
        assignee resolver handles emptiness too."""
        ops = allowed_ops("tasks")
        assert ops["status_category"] == {FilterOp.in_}
        assert ops["tag_ids"] == {FilterOp.in_}
        assert FilterOp.is_null in ops["assignee_ids"]

    def test_a_control_never_offers_an_operator_the_engine_refuses(self):
        engine = allowed_ops("tasks")
        for entry in describe(dataset("tasks")):
            offered = {FilterOp(op) for op in entry["ops"]}
            assert offered <= engine[entry["name"]], entry["name"]


class TestDeclaration:
    def test_a_field_is_used_only_in_ways_it_can_perform(self):
        """A column or a computation, never both; some way to be used; and no
        claim to a use it has nothing to perform with."""
        for spec in dataset("tasks").fields:
            assert not (spec.column is not None and spec.resolve is not None)
            assert spec.filterable or spec.sortable or spec.groups is not None
            if spec.filterable:
                assert spec.column is not None or spec.resolve is not None
            if spec.sortable:
                assert spec.column is not None or spec.sort is not None

    def test_a_view_says_what_it_points_at_where_the_schema_cannot(self):
        """The member dataset reads a view, and a view records no foreign keys.
        Its ``id`` is nonetheless a person, which is what decides the picker —
        and a number box in its place is what a reader would have had to type
        an account id into."""

        spec = dataset("members").by_name["id"]
        assert spec.kind is ControlKind.member
        assert spec.type is FieldType.reference
        assert dataset("tasks").tool is Tool.project


class TestEveryToolIsQueryable:
    """A tool nobody can ask about is a tool a dashboard cannot draw.

    Derived from the ``Tool`` enum rather than from a list here, so an eighth
    tool shows up as a failure the day its enum entry exists.
    """

    def test_every_tool_has_a_dataset(self):
        governed = {
            dataset(name).tool for name in dataset_names() if dataset(name).tool
        }
        assert governed == set(Tool), f"no dataset for {set(Tool) - governed}"

    @pytest.mark.parametrize("name", sorted(_names()))
    def test_a_dataset_can_be_read(self, name):
        """Named with a field it declares, because a join table has no id."""
        field = next(
            spec.name for spec in dataset(name).fields if spec.column is not None
        )
        resolve(f"SELECT {field} FROM {name}")

    @pytest.mark.parametrize("name", sorted(_names()))
    def test_every_relation_it_declares_can_be_reached(self, name):
        """A relation names a dataset that exists, and a field on each side of
        every hop — so a declaration cannot point at nothing."""
        for relation in dataset(name).relations:
            previous = name
            for hop in relation.hops:
                assert hop.dataset in dataset_names(), f"{name}.{relation.name}"
                assert hop.left in dataset(previous).by_name, (
                    f"{name}.{relation.name}: {previous} has no {hop.left}"
                )
                assert hop.right in dataset(hop.dataset).by_name, (
                    f"{name}.{relation.name}: {hop.dataset} has no {hop.right}"
                )
                previous = hop.dataset

    @pytest.mark.parametrize("name", sorted(_names()))
    def test_reaching_through_a_relation_reads(self, name):
        """The join the declaration produces is one the validator accepts."""
        for relation in dataset(name).relations:
            field = next(
                spec.name
                for spec in dataset(relation.dataset).fields
                if spec.column is not None
            )
            resolve(f"SELECT {relation.name}.{field} AS v FROM {name}")


class TestWhatANewStatementLeavesOut:
    """The conditions the builder seeds a new statement with.

    Derived from the declarations rather than listed, so the test asks what a
    dataset carries rather than restating the answer beside the code that
    computes it.
    """

    def test_the_lifecycle_flags_each_dataset_starts_with(self):
        """Archived rows are left out; a template flag is read directly where a
        dataset has its own, and through the project that governs a task —
        never through a relation to something governed by nothing, like a
        task's assignee. A dataset with neither lifecycle starts clean."""
        tasks = default_filters("tasks")
        assert {"field": "archived_at", "op": "is_null", "value": True} in tasks
        assert {"field": "project.is_template", "op": "eq", "value": False} in tasks
        assert not any(c["field"].startswith("assignee.") for c in tasks)
        assert {"field": "is_template", "op": "eq", "value": False} in (
            default_filters("projects")
        )
        assert default_filters("members") == []

    def test_every_archivable_dataset_says_so(self):
        from app.db.frozen import ARCHIVABLE_TABLES

        for name in dataset_names():
            spec = dataset(name)
            table = getattr(spec.model, "__tablename__", None)
            if table is None or str(table) not in ARCHIVABLE_TABLES:
                continue
            fields = [condition["field"] for condition in default_filters(name)]
            assert "archived_at" in fields, name

    def test_the_trash_is_not_one_of_them(self):
        """It is removed in the database, not offered as a filter to delete."""
        for name in dataset_names():
            fields = [condition["field"] for condition in default_filters(name)]
            assert not any("deleted_at" in field for field in fields), name

    def test_what_it_produces_is_a_statement_the_builder_accepts(self):
        """The point of the shape: it is an ordinary condition, so it compiles."""
        from app.schemas.query import FilterOp
        from app.services.query.build import Column, Condition, QuerySpec, build

        for name in ("tasks", "projects", "files"):
            spec = QuerySpec(
                dataset=name,
                columns=(Column(field="*", aggregate="count", alias="count"),),
                where=tuple(
                    Condition(
                        field=condition["field"],
                        op=FilterOp(condition["op"]),
                        value=condition["value"],
                    )
                    for condition in default_filters(name)
                ),
            )
            assert build(spec).startswith("SELECT count(*) AS count FROM ")


def test_a_tool_plugins_tables_are_its_communitys_datasets():
    """A community's installed tool and its items are datasets of their own
    tables, their fields the declared ones beside every tool's, an item
    reaching its tool as a counter reaches its group; a community without the
    plug-in has none of them, and a statement naming one resolves only where
    it is installed."""
    from app.services.marketplace.tool_plugins import (
        normalize_tool_plugin_definition,
    )
    from app.services.query.resolve import QueryError
    from app.testing.tool_plugins import counters_tool_manifest, counters_tool_set

    manifest = counters_tool_manifest()
    # A declared person, which no foreign key marks as one.
    manifest["tool"]["items"][0]["fields"].append(
        {"key": "keeper", "name": {"en": "Keeper"}, "kind": "user_reference"}
    )
    tools = counters_tool_set(normalize_tool_plugin_definition(manifest))
    (tool,) = tools.installed
    (counters,) = tool.items

    assert {tool.table.name, counters.name} <= set(dataset_names(tools))
    assert counters.name not in dataset_names()
    items = dataset(counters.name, tools)
    assert {"count", "max", "view_mode", "name", "created_by", "archived_at"} <= set(
        items.by_name
    )
    assert items.by_relation["counter_group"].dataset == tool.table.name
    assert items.by_name["keeper"].kind is ControlKind.member
    assert items.by_name["tag_ids"].kind is ControlKind.tag
    statement = resolve(
        f"SELECT c.name, counter_group.description FROM {counters.name} AS c",
        tools=tools,
    )
    assert statement.relations == tuple(sorted({counters.name, tool.table.name}))
    with pytest.raises(QueryError):
        resolve(f"SELECT name FROM {counters.name}")
