"""The task dataset — what a table cannot say about a task.

The columns are not here. They are read off ``Task`` itself, because a foreign
key already names the picker that fills it and a SQL type already says whether
it orders. What is left is the part no table carries: the fields that are a
subquery rather than a column, the parent a list groups by, and the columns that
exist for a feature's own bookkeeping.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import case, func, literal, text
from sqlmodel import select

from app.core.messages import TaskMessages
from app.core.tools import Tool
from app.models.tenant.project import Project
from app.models.tenant.task import Task, TaskAssignee, TaskStatus
from app.schemas.query import FilterOp
from app.services.fields.derive import derive_fields, options_for
from app.services.fields.spec import (
    Hop,
    Relation,
    EQUALITY,
    MEMBERSHIP,
    ORDERED,
    TEXTUAL,
    ControlKind,
    Dataset,
    FieldContext,
    FieldSpec,
    SortContext,
    computed,
)
from app.services.tenant import metadata as metadata_service

#: Columns that are the recurrence feature's own state — the rule, its end, the
#: strategy that applies it, the counter that tracks it and the series a task
#: is in. Real columns, filterable by a stored definition, and not something
#: anybody narrows a board by.
_INTERNAL = frozenset(
    {
        "recurrence",
        "recurrence_until",
        "recurrence_shift",
        "recurrence_anchor",
        "recurrence_anchor_count",
        "recurrence_strategy",
        "recurrence_occurrence_count",
        "recurrence_limit",
        "series_id",
    }
)


def _status_category(op: FilterOp, value: Any, ctx: FieldContext) -> Any:
    if not value:
        return None
    subq = select(TaskStatus.id).where(TaskStatus.category.in_(tuple(value)))
    return Task.task_status_id.in_(subq)


def _assignee_ids(op: FilterOp, value: Any, ctx: FieldContext) -> Any:
    # "Unassigned": no row in task_assignees at all. Answered before the
    # emptiness guard below, which is there to skip an empty id list.
    # ``negate`` inverts it, so "has any assignee" comes free.
    if op == FilterOp.is_null:
        has_assignee = Task.id.in_(select(TaskAssignee.task_id))
        return ~has_assignee if value else has_assignee
    if not value:
        return None
    user_ids: list[int] = []
    for aid in value:
        if aid == "me":
            # "Me" names the person asking; a request that is nobody's has
            # no one to name.
            if ctx.user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=TaskMessages.INVALID_ASSIGNEE_ID,
                )
            user_ids.append(ctx.user_id)
        else:
            try:
                user_ids.append(int(aid))
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=TaskMessages.INVALID_ASSIGNEE_ID,
                )
    if not user_ids:
        return None
    subq = select(TaskAssignee.task_id).where(TaskAssignee.user_id.in_(tuple(user_ids)))
    return Task.id.in_(subq)


def _initiative_ids(op: FilterOp, value: Any, ctx: FieldContext) -> Any:
    if not value:
        return None
    subq = select(Project.id).where(Project.initiative_id.in_(tuple(value)))
    return Task.project_id.in_(subq)


def _property_values(op: FilterOp, value: Any, ctx: FieldContext) -> Any:
    """Filter tasks by a custom property value.

    ``value`` is a dict of ``{"property_id": int, "value": <any>}``. Compilation
    is delegated to ``build_single_property_clause`` so the typed-column and
    is_empty semantics stay in sync with files and events.
    """
    if not isinstance(value, dict):
        return None
    try:
        pid = int(value.get("property_id"))
    except (TypeError, ValueError):
        return None
    defn = ctx.property_definitions.get(pid)
    if defn is None:
        # Unknown or cross-guild property — silently skip (defense in depth,
        # consistent with the rest of apply_filters).
        return None
    return metadata_service.build_single_property_clause(
        "task", pid, op, value.get("value"), defn
    )


def _plugin_values(op: FilterOp, value: Any, ctx: FieldContext) -> Any:
    """Filter tasks by a plug-in field's value.

    ``value`` is a dict of ``{"field": "plugin:<install>:<key>", "value": <any>}``,
    with ``"facet"`` naming one of the facets of the field's states to compare
    by the key a value names for it. A field the person is not drawn, or a
    facet it does not declare, contributes nothing, as an unknown property
    does."""
    if not isinstance(value, dict):
        return None
    field = ctx.plugin_fields.get(str(value.get("field")))
    if field is None:
        return None
    return metadata_service.filter_clause(
        field, op, value.get("value"), value.get("facet")
    )


def _date_group(ctx: SortContext) -> Any:
    """SQL CASE mirroring the frontend's ``getTaskDateStatus()``.

    Returns a numeric group: 0 overdue, 1 today, 2 this week, 3 this month,
    4 later.

    When the context carries an IANA timezone the expression converts both
    ``now()`` and the task columns into it, so "today" is the *reader's* local
    day rather than the database server's UTC one. That is why this is an
    expression resolved per request rather than a column: the same row belongs
    to a different group depending on who is looking.
    """
    tz = ctx.tz
    if tz:
        tz_sql = literal(tz)
        now = func.now().op("AT TIME ZONE")(tz_sql)
        start = Task.start_date.op("AT TIME ZONE")(tz_sql)
        due = Task.due_date.op("AT TIME ZONE")(tz_sql)
    else:
        now = func.now()
        start = Task.start_date
        due = Task.due_date

    today = func.date_trunc("day", now)
    week_later = now + text("interval '7 days'")
    month_later = now + text("interval '30 days'")

    return case(
        # 0: overdue — due_date is in the past
        (due < now, 0),
        # 1: today — start_date before today, or start/due is today
        (start < today, 1),
        (func.date_trunc("day", start) == today, 1),
        (func.date_trunc("day", due) == today, 1),
        # 2: this week — start or due within 7 days
        (start <= week_later, 2),
        (due <= week_later, 2),
        # 3: this month — start or due within 30 days
        (start <= month_later, 3),
        (due <= month_later, 3),
        # 4: later — everything else
        else_=4,
    )


#: What each resolver actually handles. Narrower than the type would suggest,
#: and deliberately so: ``_status_category`` builds an ``IN`` over its value, so
#: ``in_`` is the one operator it answers.
_IN_ONLY = frozenset({FilterOp.in_})

#: A custom property answers whichever operators its own type supports; the
#: dispatch inside ``build_single_property_clause`` decides, so this one really
#: is as wide as it looks.
_ANY_OP = EQUALITY | MEMBERSHIP | ORDERED | TEXTUAL


def _status_position(ctx: SortContext) -> Any:
    """The task's column on its project's board."""
    return (
        select(TaskStatus.position)
        .where(TaskStatus.id == Task.task_status_id)
        .scalar_subquery()
    )


def _tag_name(ctx: SortContext) -> Any:
    from app.services.tenant.tags import TAG_LINKS, first_tag_name

    return first_tag_name(TAG_LINKS["task"], Task.id)


async def _parent_groups(session: Any, ids: list[int]) -> Any:
    from app.services.tenant import task_hierarchy

    return await task_hierarchy.groups(session, ids)


def _computed() -> tuple[FieldSpec, ...]:
    return (
        FieldSpec(
            name="date_group",
            kind=ControlKind.number,
            ops=frozenset(),
            sort=_date_group,
            filterable=False,
            sortable=True,
            buckets=True,
        ),
        # Orderings with nothing to filter: a status is picked by its id or
        # category, and a tag by its id.
        FieldSpec(
            name="status_position",
            kind=ControlKind.number,
            ops=frozenset(),
            sort=_status_position,
            filterable=False,
            sortable=True,
        ),
        # The task a task is part of. A grouping only: the tree is stored as
        # ``part_of`` edges, which no column or declared relation reaches.
        FieldSpec(
            name="parent_task_id",
            kind=ControlKind.task,
            ops=frozenset(),
            filterable=False,
            groups=_parent_groups,
        ),
        FieldSpec(
            name="tag_name",
            kind=ControlKind.text,
            ops=frozenset(),
            sort=_tag_name,
            filterable=False,
            sortable=True,
        ),
        computed(
            "status_category",
            _status_category,
            kind=ControlKind.select,
            ops=_IN_ONLY,
            # The categories a status can be in, read off the column that
            # stores them rather than restated here or on the client.
            options=options_for(TaskStatus.__table__.columns["category"]),
        ),
        computed(
            "assignee_ids",
            _assignee_ids,
            kind=ControlKind.member,
            # The one computed field where "is empty" means something: a task
            # with no row in task_assignees at all.
            ops=frozenset({FilterOp.in_, FilterOp.is_null}),
            nullable=True,
        ),
        computed(
            "initiative_ids",
            _initiative_ids,
            kind=ControlKind.initiative,
            ops=_IN_ONLY,
            # For the cross-guild "my tasks" views, which pass it themselves. A
            # dashboard already knows its initiative and cannot say otherwise.
            offer=False,
        ),
        computed(
            "property_values",
            _property_values,
            kind=ControlKind.property_value,
            ops=_ANY_OP,
            nullable=True,
            # A property filter names one property and a value for it, so a
            # control has to choose the property before it can offer values.
            # Until there is such a control, this is filterable by a stored
            # definition only — which is how the tasks page uses it.
            offer=False,
        ),
        computed(
            "plugin_values",
            _plugin_values,
            kind=ControlKind.property_value,
            ops=_ANY_OP,
            nullable=True,
            # As a property filter: one field and a value for it, by a stored
            # definition.
            offer=False,
        ),
    )


#: What a task can be read alongside.
#:
#: ``assignee`` is the one worth reading. Who is doing something is a table of
#: its own, so naming a person beside a task is two joins — and asking for a
#: board per person, or a count per person, is the question that made this
#: whole declaration worth having. The table between them is a hop rather than
#: a destination: nobody wants to see a row of two ids.
_RELATIONS: tuple[Relation, ...] = (
    Relation(
        name="assignee",
        hops=(
            Hop(dataset="task_assignees", left="id", right="task_id"),
            Hop(dataset="members", left="user_id", right="id"),
        ),
    ),
    Relation(
        name="status",
        hops=(Hop(dataset="task_statuses", left="task_status_id", right="id"),),
    ),
    Relation(
        name="type",
        hops=(Hop(dataset="task_types", left="task_type_id", right="id"),),
    ),
    Relation(
        name="project",
        hops=(Hop(dataset="projects", left="project_id", right="id"),),
    ),
)


def build() -> Dataset:
    """The dataset, with its columns read off the model.

    Built on call rather than at import so the columns are read once the mappers
    are configured, and so a test can rebuild it.
    """
    return Dataset(
        model=Task,
        tool=Tool.project,
        name_override="tasks",
        fields=derive_fields(
            Task, internal=_INTERNAL, descending=frozenset({"priority"})
        )
        + _computed(),
        relations=_RELATIONS,
    )
