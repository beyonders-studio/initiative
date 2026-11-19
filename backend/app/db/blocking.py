"""What it means for a thing to still be standing in another thing's way.

A ``depends_on`` edge records that one thing waits on another. Whether it is
*still* waiting is a different question, and the answer is a product rule that
differs per kind: a task is done when somebody moved it to a done column, an
event is over when it has happened, a counter is finished when it reaches the
number it was counting to.

This is the one place that answers it. The entries are judgement calls rather
than a law — a kind earns one when there is an honest, cheap reading of
"finished" on the row itself. A tool plug-in's item says its own, as the
``open_while`` it declares: one condition on one of its fields, read here into
the same kind of expression. A kind with neither reports ``None``, which is the
truthful answer for something that never finishes rather than a ``False``
standing in for one, and nothing counts it as a blocker.

Each rule is a SQL expression over the kind's own table, so the two readers —
the far end of an edge (:mod:`app.db.reference_targets`) and a task's blocker
count (``app.services.tenant.task_queries``) — work from one definition and
cannot drift.
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sqlalchemy import Table, case, exists, func, null, or_, select, true
from sqlalchemy.sql.elements import ColumnElement

if TYPE_CHECKING:
    from app.core.tool_set import ToolSet


def _project_has_work_left(projects: Table) -> ColumnElement:
    """A project is finished when its tasks are, and not before.

    Two readings, because "all of them are done" is vacuously true of a project
    with no tasks at all — and a project nobody has filled in yet is the one
    thing it certainly is not: finished. So an empty project is outstanding,
    and a project stops blocking only once it has had work in it and all of
    that work is done.

    Archived and trashed tasks are not work anybody is waiting on, so they
    neither keep a project open nor count as the work that closes it.
    """
    from sqlmodel import SQLModel

    tasks = SQLModel.metadata.tables["tasks"]
    live = (
        tasks.c["project_id"] == projects.c["id"],
        tasks.c["archived_at"].is_(None),
        tasks.c["deleted_at"].is_(None),
    )
    return or_(
        ~exists(select(1).select_from(tasks).where(*live)),
        exists(
            select(1).select_from(tasks).where(*live, tasks.c["completed_at"].is_(None))
        ),
    )


#: Table name -> "this row is still outstanding". Keyed by table rather than by
#: :class:`SearchEntityType` to match how ``reference_targets`` and
#: ``INITIATIVE_PATHS`` address a kind.
OPEN_WHEN: dict[str, Callable[[Table], ColumnElement]] = {
    # Set when the task entered a done-category status and cleared when it
    # leaves one, by ``app.services.tenant.task_completion``.
    "tasks": lambda t: t.c["completed_at"].is_(None),
    # An event blocks until it has passed. A RECURRING one never passes, so it
    # answers NULL rather than "finished": it has no last occurrence for an end
    # date to be the end of, and calling it finished would strike it through on
    # every surface that dims a blocker somebody has dealt with.
    "calendar_events": lambda t: case(
        (t.c["recurrence"].isnot(None), null()),
        else_=t.c["end_at"] > func.now(),
    ),
    # A project finishes when the work in it does — see the function.
    "projects": _project_has_work_left,
}


#: How a declared ``open_while`` compares a number or counter field
#: (``app.services.marketplace.tool_plugins``).
_COMPARISONS: dict[str, Callable[[Any, Any], ColumnElement]] = {
    "below": operator.lt,
    "at_most": operator.le,
    "above": operator.gt,
    "at_least": operator.ge,
    "equals": operator.eq,
    "not_equals": operator.ne,
}


def _declared(table: Table) -> ColumnElement | None:
    """The "still outstanding" a tool plug-in's item declares
    (``open_while``), over its table, or None where it declares none.

    The declaration is one condition on one field, checked when the plug-in
    was registered: a number or counter field compared with another such
    field or with a value, a checkbox ticked or not (an unticked one is never
    NULL here), a select among some of its options, a date or datetime not yet
    passed. A value is a bound parameter. A field left empty compares as NULL,
    which, as a counter with no ``max`` does, has no answer.
    """
    from app.db.plugin_tools import DECLARED

    condition = (table.info.get(DECLARED) or {}).get("open_while")
    if condition is None:
        return None
    column = table.c[condition["field"]]
    ((term, value),) = ((k, v) for k, v in condition.items() if k != "field")
    if term in _COMPARISONS:
        operand = table.c[value["field"]] if isinstance(value, dict) else value
        return _COMPARISONS[term](column, operand)
    if term == "is":
        return column.is_(true()) if value else column.is_not(true())
    if term == "in":
        return column.in_(value)
    # ``not_passed``: a date is still to come through its own day.
    if column.info["field"] == "date":
        return column >= func.current_date()
    return column > func.now()


def open_expr(table: Table) -> ColumnElement:
    """This kind's "still outstanding" reading, or NULL where it has none."""
    rule = OPEN_WHEN.get(table.name)
    if rule is not None:
        return rule(table)
    declared = _declared(table)
    return null() if declared is None else declared


def blocking_kinds(tools: ToolSet) -> list[tuple[str, Table, ColumnElement]]:
    """Every kind that can hold something up in a community with ``tools``:
    how an edge names it, its table, and the reading of "still outstanding"
    over that table.

    Derived from :data:`OPEN_WHEN` and the installed tools' declarations, so
    a kind gains a blocker count the moment it gains a rule and nothing else
    has to be edited.
    """
    from sqlmodel import SQLModel

    from app.db.search_index import search_sources

    sources = search_sources(tools)
    tables = [SQLModel.metadata.tables[name] for name in OPEN_WHEN] + [
        table for table in tools.installed_tables if _declared(table) is not None
    ]
    return [
        (sources[table.name].entity_type, table, open_expr(table)) for table in tables
    ]
