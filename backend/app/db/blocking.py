"""What it means for a thing to still be standing in another thing's way.

A ``depends_on`` edge records that one thing waits on another. Whether it is
*still* waiting is a different question, and the answer is a product rule that
differs per kind: a task is done when somebody moved it to a done column, an
event is over when it has happened, a counter is finished when it reaches the
number it was counting to.

This is the one place that answers it. The entries are judgement calls rather
than a law — a kind earns one when there is an honest, cheap reading of
"finished" on the row itself. A kind with no entry reports ``None``, which is
the truthful answer for something that never finishes rather than a ``False``
standing in for one, and nothing counts it as a blocker.

Each rule is a SQL expression over the kind's own table, so the two readers —
the far end of an edge (:mod:`app.db.reference_targets`) and a task's blocker
count (``app.services.tenant.task_queries``) — work from one definition and
cannot drift.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import Table, case, exists, func, null, or_, select
from sqlalchemy.sql.elements import ColumnElement


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
    # A counter blocks until it reaches what it was counting to. One with no
    # ``max`` has no finish line, so it has no answer either — NULL, not false,
    # which SQL would otherwise fold ``max IS NOT NULL AND …`` down to.
    "counters": lambda t: case(
        (t.c["max"].is_(None), null()),
        else_=t.c["count"] < t.c["max"],
    ),
    # A project finishes when the work in it does — see the function.
    "projects": _project_has_work_left,
}


def open_expr(table_name: str, table: Table) -> ColumnElement:
    """This kind's "still outstanding" reading, or NULL where it has none."""
    rule = OPEN_WHEN.get(table_name)
    return rule(table) if rule is not None else null()


def blocking_kinds() -> list[tuple[str, Table, ColumnElement]]:
    """Every kind that can hold something up: how an edge names it, its table,
    and the reading of "still outstanding" over that table.

    Derived from :data:`OPEN_WHEN`, so a kind gains a blocker count the moment
    it gains a rule and nothing else has to be edited.
    """
    from sqlmodel import SQLModel

    from app.db.search_index import SEARCH_SOURCES

    arms: list[tuple[str, Table, ColumnElement]] = []
    for table_name, rule in OPEN_WHEN.items():
        table = SQLModel.metadata.tables[table_name]
        arms.append((SEARCH_SOURCES[table_name].entity_type.value, table, rule(table)))
    return arms
