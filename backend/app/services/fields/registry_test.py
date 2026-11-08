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


#: What ``_build_task_filter_fields`` produced before the registry: every column
#: on the model, plus these five. Spelled out rather than derived, so a field
#: quietly disappearing from the declaration fails here.
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
    def test_every_model_column_a_control_can_fill_is_filterable(self):
        """Derived from the model, so a column added tomorrow is filterable
        the day it is added."""
        resolved = allowed_fields("tasks", _ctx())
        for col in Task.__table__.columns:
            if col.name in NOT_FILTERABLE:
                continue
            assert col.name in resolved, f"{col.name} lost its filter field"

    def test_the_columns_left_out_are_left_out_for_a_reason(self):
        resolved = allowed_fields("tasks", _ctx())
        assert set(NOT_FILTERABLE).isdisjoint(resolved)

    def test_a_taggable_model_gets_its_tag_filter_without_asking(self):
        """Nearly everything is taggable and everything taggable binds the same
        way, so no dataset declares that it has tags. The model's entry in the
        tag registry is the whole of the difference between one and the next."""
        assert "tag_ids" in {spec.name for spec in derive_fields(Task)}

    def test_a_model_with_no_tags_gets_no_tag_filter(self):
        assert "tag_ids" not in {spec.name for spec in derive_fields(TaskAssignee)}

    def test_a_decorated_string_column_is_still_a_column(self):
        """SQLModel wraps a plain ``str`` field in its own type rather than
        subclassing the SQL one, so a deriver that asks without unwrapping
        loses every string on the model."""
        assert "title" in allowed_fields("tasks", _ctx())

    def test_the_virtual_fields_are_all_present(self):
        resolved = allowed_fields("tasks", _ctx())
        assert VIRTUAL_FIELDS <= set(resolved)

    def test_nothing_else_crept_in(self):
        """The set is exactly the fillable columns plus the five — a field
        nobody asked for is as much a change as a missing one."""
        resolved = set(allowed_fields("tasks", _ctx()))
        columns = {c.name for c in Task.__table__.columns} - set(NOT_FILTERABLE)
        assert resolved == columns | VIRTUAL_FIELDS

    def test_columns_pass_through_and_virtuals_are_callable(self):
        resolved = allowed_fields("tasks", _ctx())
        assert resolved["title"] is Task.title
        for name in VIRTUAL_FIELDS:
            assert callable(resolved[name])


class TestVirtualFields:
    """Each compiles to the clause it compiled to before."""

    def test_status_category_matches_statuses_in_those_categories(self):
        clause = allowed_fields("tasks", _ctx())["status_category"](
            FilterOp.in_, ["done"]
        )
        sql = _sql(clause)
        assert "task_status_id IN" in sql
        assert "'done'" in sql

    def test_status_category_ignores_an_empty_list(self):
        assert (
            allowed_fields("tasks", _ctx())["status_category"](FilterOp.in_, []) is None
        )

    def test_assignee_me_resolves_to_the_requesting_user(self):
        clause = allowed_fields("tasks", _ctx(user_id=99))["assignee_ids"](
            FilterOp.in_, ["me"]
        )
        assert "99" in _sql(clause)

    def test_assignee_mixes_me_with_real_ids(self):
        clause = allowed_fields("tasks", _ctx(user_id=99))["assignee_ids"](
            FilterOp.in_, ["me", "5"]
        )
        sql = _sql(clause)
        assert "99" in sql and "5" in sql

    def test_assignee_is_null_true_means_unassigned(self):
        clause = allowed_fields("tasks", _ctx())["assignee_ids"](FilterOp.is_null, True)
        assert "NOT" in _sql(clause).upper()

    def test_assignee_is_null_false_means_has_any_assignee(self):
        clause = allowed_fields("tasks", _ctx())["assignee_ids"](
            FilterOp.is_null, False
        )
        assert "NOT" not in _sql(clause).upper()

    def test_a_non_numeric_assignee_is_refused(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as excinfo:
            allowed_fields("tasks", _ctx())["assignee_ids"](FilterOp.in_, ["nope"])
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

    def test_an_unknown_property_contributes_nothing(self):
        clause = allowed_fields("tasks", _ctx())["property_values"](
            FilterOp.eq, {"property_id": 1, "value": "x"}
        )
        assert clause is None

    def test_a_malformed_property_payload_contributes_nothing(self):
        resolve = allowed_fields("tasks", _ctx())["property_values"]
        assert resolve(FilterOp.eq, "not a dict") is None
        assert resolve(FilterOp.eq, {"property_id": "abc"}) is None


#: What ``_task_sort_fields`` offered before any of this was derived. Ordering
#: is now read off the column's type, which admits a few more; these are the
#: ones a caller already relies on and none of them may go.
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
    def test_everything_that_was_orderable_still_is(self):
        assert SORTABLE_FIELDS <= set(sort_fields("tasks", _ctx()))

    def test_a_reference_is_not_an_ordering(self):
        """Ordering by a foreign key sorts by row id, which is an ordering of
        the storage rather than of anything a reader can see."""
        sortable = set(sort_fields("tasks", _ctx()))
        assert sortable.isdisjoint({"project_id", "task_status_id", "created_by"})

    def test_long_form_text_is_not_an_ordering(self):
        """A short title orders usefully; a body of prose orders by its first
        character, which is never what anybody wanted."""
        sortable = set(sort_fields("tasks", _ctx()))
        assert "title" in sortable
        assert "description" not in sortable

    def test_a_sortable_column_orders_by_itself(self):
        assert sort_fields("tasks", _ctx())["title"] is Task.title

    def test_date_group_is_an_expression_not_a_column(self):
        """It is a CASE over two dates, so there is no column to hand back."""
        expression = sort_fields("tasks", _ctx())["date_group"]
        assert "CASE" in _sql(expression)

    def test_date_group_follows_the_readers_timezone(self):
        """The same row groups differently depending on whose day it is."""
        naive = _sql(sort_fields("tasks", _ctx())["date_group"])
        aware = _sql(sort_fields("tasks", _ctx(tz="America/New_York"))["date_group"])
        assert "AT TIME ZONE" not in naive
        assert "America/New_York" in aware

    def test_most_columns_are_filterable_without_being_sortable(self):
        """Sortability is opt-in: a field list nobody can read is not a
        feature, and most columns narrow usefully without ordering usefully."""
        filterable = set(allowed_fields("tasks", _ctx()))
        assert SORTABLE_FIELDS - {"date_group"} < filterable

    def test_date_group_is_sort_only(self):
        assert "date_group" not in allowed_fields("tasks", _ctx())


#: What the frontend's hand-kept ``TASK_FILTER_FIELDS`` offered before this
#: became derived. Everything here must survive, or a filter somebody built
#: stops being offered.
PREVIOUSLY_OFFERED = {
    "status_category": (["in_"], True),
    "task_status_id": (["in_"], True),
    "priority": (["in_"], True),
    "assignee_ids": (["in_", "is_null"], True),
    "tag_ids": (["in_"], True),
    "project_id": (["eq"], False),
    "due_date": (["gt", "gte", "is_null", "lt", "lte"], False),
    "start_date": (["gt", "gte", "is_null", "lt", "lte"], False),
    "completed_at": (["gt", "gte", "is_null", "lt", "lte"], False),
    "created_at": (["gt", "gte", "lt", "lte"], False),
    "archived_at": (["gt", "gte", "is_null", "lt", "lte"], False),
    "title": (["ilike"], False),
}

#: Added when the two lists became one — fields the engine always accepted and
#: no control ever offered.
NEWLY_OFFERED = {"description", "updated_at", "created_by"}

#: Added with the field it filters on: a task's type.
LATER_OFFERED = {"task_type_id"}


class TestDescription:
    def test_everything_the_old_frontend_list_offered_still_is(self):
        by_name = {entry["name"]: entry for entry in describe(dataset("tasks"))}
        for name, (ops, multiple) in PREVIOUSLY_OFFERED.items():
            assert name in by_name, f"{name} stopped being offered"
            assert by_name[name]["ops"] == ops, name
            assert by_name[name]["multiple"] is multiple, name

    def test_the_offered_set_is_the_old_one_plus_the_agreed_additions(self):
        offered = {entry["name"] for entry in describe(dataset("tasks"))}
        assert offered == set(PREVIOUSLY_OFFERED) | NEWLY_OFFERED | LATER_OFFERED

    def test_the_author_groups_by_member(self):
        """``created_by`` is read only where its kind is ``member``, and still
        groups by the member it names."""
        tasks = dataset("tasks")
        assert groupable(tasks, tasks.by_name["created_by"])

    def test_bookkeeping_is_hidden_everywhere_rather_than_per_dataset(self):
        """Soft-delete columns, the surrogate key, the tenant key and the
        ordering float mean nothing to somebody building a filter, and every
        table has them."""
        offered = {entry["name"] for entry in describe(dataset("tasks"))}
        assert offered.isdisjoint(
            {"id", "guild_id", "position", "deleted_at", "deleted_by", "purge_at"}
        )

    def test_a_hidden_field_is_still_filterable_by_a_stored_definition(self):
        """Hiding governs what a control offers, never what the engine accepts."""
        resolved = allowed_fields("tasks", _ctx())
        assert "initiative_ids" in resolved
        assert "property_values" in resolved

    def test_a_field_is_offered_only_where_a_control_can_supply_its_value(self):
        """``property_values`` takes an object naming a property and a value for
        it. A control that picks one does not exist yet, and a text box supplies
        a string this resolver reads as nothing — so the field stays available
        to a stored definition and out of the list a client draws."""
        offered = {entry["name"] for entry in describe(dataset("tasks"))}
        assert "property_values" not in offered

    def test_an_entry_carries_what_a_control_needs(self):
        by_name = {entry["name"]: entry for entry in describe(dataset("tasks"))}
        assert by_name["priority"]["kind"] == "select"
        assert by_name["assignee_ids"]["kind"] == "member"
        assert by_name["due_date"]["type"] == "date"

    def test_a_reference_takes_its_control_from_the_table_it_points_at(self):
        """An integer that references ``users`` is a person, not a number.
        The foreign key says so, so no dataset restates it."""
        by_name = {entry["name"]: entry for entry in describe(dataset("tasks"))}
        assert by_name["created_by"]["kind"] == "member"
        assert by_name["project_id"]["kind"] == "project"
        assert by_name["task_status_id"]["kind"] == "task_status"

    def test_a_closed_vocabulary_carries_its_own_values(self):
        """Straight off the column that stores them, so a client keeps no copy
        and a value added by a migration is offered without a release."""
        by_name = {entry["name"]: entry for entry in describe(dataset("tasks"))}
        assert by_name["priority"]["options"] == list(
            Task.__table__.columns["priority"].type.enums
        )
        assert by_name["status_category"]["options"] == [
            "backlog",
            "todo",
            "in_progress",
            "done",
        ]

    def test_a_field_with_no_closed_set_carries_no_options(self):
        by_name = {entry["name"]: entry for entry in describe(dataset("tasks"))}
        assert by_name["due_date"]["options"] == []
        assert by_name["assignee_ids"]["options"] == []

    def test_it_carries_no_resolvers(self):
        """What a field compiles to is ours; a client gets the description."""
        for entry in describe(dataset("tasks")):
            assert not any(callable(value) for value in entry.values())


class TestOperatorEnforcement:
    def test_a_field_declares_only_operators_its_resolver_handles(self):
        """The status-category and tag resolvers each build an ``IN`` over
        their value, so ``in_`` is the one operator each of them answers."""
        ops = allowed_ops("tasks")
        assert ops["status_category"] == {FilterOp.in_}
        assert ops["tag_ids"] == {FilterOp.in_}

    def test_the_one_computed_field_that_handles_emptiness_declares_it(self):
        assert FilterOp.is_null in allowed_ops("tasks")["assignee_ids"]

    def test_a_control_never_offers_an_operator_the_engine_refuses(self):
        engine = allowed_ops("tasks")
        for entry in describe(dataset("tasks")):
            offered = {FilterOp(op) for op in entry["ops"]}
            assert offered <= engine[entry["name"]], entry["name"]

    def test_is_empty_is_offered_only_where_a_value_can_be_empty(self):
        by_name = {entry["name"]: entry for entry in describe(dataset("tasks"))}
        # created_at is NOT NULL; due_date is not.
        assert "is_null" not in by_name["created_at"]["ops"]
        assert "is_null" in by_name["due_date"]["ops"]


class TestDeclaration:
    def test_a_field_is_a_column_or_a_computation_never_both(self):
        for spec in dataset("tasks").fields:
            assert not (spec.column is not None and spec.resolve is not None)

    def test_every_field_declares_some_way_to_be_used(self):
        for spec in dataset("tasks").fields:
            assert spec.filterable or spec.sortable or spec.groups is not None

    def test_a_field_cannot_claim_a_use_it_cannot_perform(self):
        for spec in dataset("tasks").fields:
            if spec.filterable:
                assert spec.column is not None or spec.resolve is not None
            if spec.sortable:
                assert spec.column is not None or spec.sort is not None

    def test_a_view_says_what_it_points_at_where_the_schema_cannot(self):
        """The member dataset reads a view, and a view records no foreign keys.
        Its ``id`` is nonetheless a person, which is what decides the picker —
        and a number box in its place is what a reader would have had to type
        an account id into."""
        from app.services.fields.spec import ControlKind, FieldType

        spec = dataset("members").by_name["id"]
        assert spec.kind is ControlKind.member
        assert spec.type is FieldType.reference

    def test_the_dataset_takes_its_name_from_the_tool_where_it_can(self):
        from app.core.tools import Tool

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

    def test_a_dataset_that_can_be_archived_starts_without_archived_rows(self):
        assert {"field": "archived_at", "op": "is_null", "value": True} in (
            default_filters("tasks")
        )

    def test_a_dataset_with_its_own_template_flag_reads_it_directly(self):
        assert {"field": "is_template", "op": "eq", "value": False} in (
            default_filters("projects")
        )

    def test_a_task_reads_the_flag_from_the_project_that_governs_it(self):
        """A task is not a template; the project holding it is. The relation is
        the one reaching the dataset under the same governing tool, so the
        route is derived rather than named here."""
        assert {"field": "project.is_template", "op": "eq", "value": False} in (
            default_filters("tasks")
        )

    def test_a_relation_to_something_governed_by_nothing_is_not_followed(self):
        """`tasks` also relates to members, which is nobody's template."""
        fields = [condition["field"] for condition in default_filters("tasks")]
        assert not any(field.startswith("assignee.") for field in fields)

    def test_a_dataset_with_neither_lifecycle_starts_clean(self):
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
