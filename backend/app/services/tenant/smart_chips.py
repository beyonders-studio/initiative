"""Reading what a smart chip currently shows.

A chip stores nothing. The file holds a reference — ``task:12:status`` —
and this reads the row that reference names, every time, so a chip is never
older than the last request.

One entry per ``(kind, aspect)`` in :data:`SMART_CHIP_SOURCES`, and each entry reads
its whole set of ids in ONE query. A file with thirty task chips makes one
request, and that request makes one query per aspect it uses — not one per chip.

Every read goes through the session it is handed, which is the request's
RLS-scoped one, so a reference to something the caller cannot see comes back
absent rather than as an error or a row.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import ColumnElement, Table, and_, func, true
from sqlmodel import select

from app.core.smart_chips import (
    ACTIONABLE_CHIP_KINDS,
    SmartChipAspect,
    SmartChipTone,
)
from app.core.references import REF_SEPARATOR, parse_ref as parse_bare_ref
from app.core import recurrence
from app.core.search import SearchEntityType
from app.db import reference_targets
from app.core.user_display import display_name
from app.models.platform.user import User
from app.models.platform.user_profile_view import MemberProfile
from app.models.tenant.calendar_event import CalendarEvent
from app.models.tenant.counter import Counter
from app.core.file_types import FileType
from app.models.tenant.project import Project
from app.models.tenant.task import (
    Task,
    TaskAssignee,
    TaskPriority,
    TaskStatus,
    TaskStatusCategory,
)
from app.schemas.tenant.smart_chip import (
    MAX_EMBEDS,
    MAX_REFS,
    ReferenceEmbed,
    SmartChipState,
)


@dataclass(frozen=True)
class SmartChipValue:
    """What one chip reads, before it is paired back to its reference."""

    text: str
    tone: SmartChipTone = SmartChipTone.neutral
    color: Optional[str] = None
    date: Optional[datetime] = None
    number: Optional[Decimal] = None


#: A reader takes the ids wanted and answers for the ones it can see.
Reader = Callable[[AsyncSession, list[int]], Awaitable[dict[int, SmartChipValue]]]

#: Where a task sits, in the colour its own column carries. ``done`` is the one
#: category with a meaning every project shares, so it is the one that gets a
#: tone of its own; the rest are whatever the project called them.
_STATUS_TONES = {
    TaskStatusCategory.done: SmartChipTone.good,
    TaskStatusCategory.in_progress: SmartChipTone.warn,
}

_PRIORITY_TONES = {
    TaskPriority.urgent: SmartChipTone.danger,
    TaskPriority.high: SmartChipTone.warn,
    TaskPriority.low: SmartChipTone.muted,
}


async def _task_status(
    session: AsyncSession, ids: list[int]
) -> dict[int, SmartChipValue]:
    rows = (
        await session.exec(
            select(Task.id, TaskStatus.name, TaskStatus.color, TaskStatus.category)
            .join(TaskStatus, TaskStatus.id == Task.task_status_id)
            .where(Task.id.in_(ids), Task.deleted_at.is_(None))
        )
    ).all()
    return {
        task_id: SmartChipValue(
            text=name,
            tone=_STATUS_TONES.get(category, SmartChipTone.neutral),
            color=color,
        )
        for task_id, name, color, category in rows
    }


# Most tasks are held by one or two people, so two names covers the common
# case in words; past that the chip counts.
ASSIGNEES_NAMED = 2


async def _task_assignee(
    session: AsyncSession, ids: list[int]
) -> dict[int, SmartChipValue]:
    """Who holds a task. Several people can, so the chip names the first
    ``ASSIGNEES_NAMED`` and counts the rest rather than growing with the list."""
    rows = (
        await session.exec(
            select(TaskAssignee.task_id, MemberProfile)
            .join(MemberProfile, MemberProfile.id == TaskAssignee.user_id)
            .where(TaskAssignee.task_id.in_(ids))
            .order_by(TaskAssignee.task_id, MemberProfile.id)
        )
    ).all()
    holders: dict[int, list[User]] = {}
    for task_id, user in rows:
        holders.setdefault(task_id, []).append(user)

    values: dict[int, SmartChipValue] = {}
    for task_id in ids:
        people = holders.get(task_id)
        if not people:
            # Answered, not missing: an unassigned task is a fact worth showing.
            values[task_id] = SmartChipValue(text="", tone=SmartChipTone.muted)
            continue
        # ``display_name`` reads the guild's own name-visibility setting, so a
        # chip shows exactly what every other surface here shows.
        named = ", ".join(display_name(p) for p in people[:ASSIGNEES_NAMED])
        extra = len(people) - ASSIGNEES_NAMED
        values[task_id] = SmartChipValue(
            text=f"{named} +{extra}" if extra > 0 else named
        )
    return values


async def _task_due(session: AsyncSession, ids: list[int]) -> dict[int, SmartChipValue]:
    """When a task is due. Late is only late while it is unfinished — a job
    delivered a day after its date is done, not overdue."""
    rows = (
        await session.exec(
            select(Task.id, Task.due_date, TaskStatus.category)
            .join(TaskStatus, TaskStatus.id == Task.task_status_id)
            .where(Task.id.in_(ids), Task.deleted_at.is_(None))
        )
    ).all()
    now = datetime.now(timezone.utc)
    values: dict[int, SmartChipValue] = {}
    for task_id, due, category in rows:
        if due is None:
            values[task_id] = SmartChipValue(text="", tone=SmartChipTone.muted)
            continue
        moment = due if due.tzinfo else due.replace(tzinfo=timezone.utc)
        late = moment < now and category != TaskStatusCategory.done
        values[task_id] = SmartChipValue(
            text=moment.date().isoformat(),
            tone=SmartChipTone.danger if late else SmartChipTone.neutral,
            date=moment,
        )
    return values


async def _task_priority(
    session: AsyncSession, ids: list[int]
) -> dict[int, SmartChipValue]:
    rows = (
        await session.exec(
            select(Task.id, Task.priority).where(
                Task.id.in_(ids), Task.deleted_at.is_(None)
            )
        )
    ).all()
    return {
        task_id: SmartChipValue(
            text=priority.value,
            tone=_PRIORITY_TONES.get(priority, SmartChipTone.neutral),
        )
        for task_id, priority in rows
    }


async def _task_checklist(
    session: AsyncSession, ids: list[int]
) -> dict[int, SmartChipValue]:
    """Whether a task is finished — its column is a ``done`` one, the same
    reading the status chip colours green. An open task answers with nothing in
    it; a finished one says when, where that is known."""
    rows = (
        await session.exec(
            select(Task.id, Task.completed_at, TaskStatus.category)
            .join(TaskStatus, TaskStatus.id == Task.task_status_id)
            .where(Task.id.in_(ids), Task.deleted_at.is_(None))
        )
    ).all()
    return {
        task_id: (
            SmartChipValue(text="done", tone=SmartChipTone.good, date=completed)
            if category == TaskStatusCategory.done
            else SmartChipValue(text="")
        )
        for task_id, completed, category in rows
    }


async def _counter_value(
    session: AsyncSession, ids: list[int]
) -> dict[int, SmartChipValue]:
    """A counter's reading. Where it has a ceiling the chip says so, because a
    number is worth more against the number it is heading for."""
    rows = (
        await session.exec(
            select(Counter.id, Counter.count, Counter.max).where(
                Counter.id.in_(ids), Counter.deleted_at.is_(None)
            )
        )
    ).all()
    values: dict[int, SmartChipValue] = {}
    for counter_id, count, ceiling in rows:
        reached = ceiling is not None and count >= ceiling
        values[counter_id] = SmartChipValue(
            text=f"{_plain(count)} / {_plain(ceiling)}" if ceiling else _plain(count),
            tone=SmartChipTone.good if reached else SmartChipTone.neutral,
            number=count,
        )
    return values


async def _event_when(
    session: AsyncSession, ids: list[int]
) -> dict[int, SmartChipValue]:
    """When an event starts: a repeating one's next occurrence, muted once the
    series has ended, on its last."""
    rows = (
        await session.exec(
            select(
                CalendarEvent.id,
                CalendarEvent.start_at,
                CalendarEvent.recurrence,
                CalendarEvent.recurrence_shift,
            ).where(CalendarEvent.id.in_(ids), CalendarEvent.deleted_at.is_(None))
        )
    ).all()
    now = datetime.now(timezone.utc)
    values: dict[int, SmartChipValue] = {}
    for event_id, start, repeat, shift in rows:
        moment = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
        if repeat:
            try:
                moment = recurrence.upcoming(repeat, moment, shift, now)
            except ValueError:
                pass
        values[event_id] = SmartChipValue(
            text=moment.date().isoformat(),
            tone=SmartChipTone.muted if moment < now else SmartChipTone.neutral,
            date=moment,
        )
    return values


async def _project_progress(
    session: AsyncSession, ids: list[int]
) -> dict[int, SmartChipValue]:
    """How much of a project's work is done, as "2 / 5".

    Counted the same way a project decides whether it is still holding
    something up (:mod:`app.db.blocking`), so a chip reading 5 / 5 and a
    blocker that has stopped blocking are the same fact told twice rather than
    two answers that can disagree.

    Archived and trashed tasks are in neither number: nobody is waiting on
    them, and counting them would make a tidied project look unfinished
    forever. A project with no work in it yet says so plainly rather than
    claiming 0 / 0 is finished.
    """
    rows = (
        await session.exec(
            select(
                Project.id,
                func.count(Task.id),
                func.count(Task.completed_at),
            )
            .select_from(Project)
            .join(
                Task,
                and_(
                    Task.project_id == Project.id,
                    Task.archived_at.is_(None),
                    Task.deleted_at.is_(None),
                ),
                isouter=True,
            )
            .where(Project.id.in_(ids), Project.deleted_at.is_(None))
            .group_by(Project.id)
        )
    ).all()
    values: dict[int, SmartChipValue] = {}
    for project_id, total, done in rows:
        values[project_id] = SmartChipValue(
            text=f"{done} / {total}",
            # Good only once there was work and all of it is finished.
            tone=(
                SmartChipTone.good
                if total and done >= total
                else SmartChipTone.muted
                if not total
                else SmartChipTone.neutral
            ),
            number=Decimal(done),
        )
    return values


def _plain(value: Decimal) -> str:
    """A stored number as a person writes it — ``7`` rather than ``7.0000``."""
    trimmed = value.normalize()
    return format(trimmed, "f")


#: (kind, aspect) -> how to read it. Adding a chip is one entry here: the
#: endpoint, the accepted refs and the menu the editor offers all derive from
#: this, so none of them is a second list to keep in step.
SMART_CHIP_SOURCES: dict[tuple[SearchEntityType, SmartChipAspect], Reader] = {
    (SearchEntityType.task, SmartChipAspect.status): _task_status,
    (SearchEntityType.task, SmartChipAspect.assignee): _task_assignee,
    (SearchEntityType.task, SmartChipAspect.due): _task_due,
    (SearchEntityType.task, SmartChipAspect.priority): _task_priority,
    (SearchEntityType.counter, SmartChipAspect.value): _counter_value,
    (SearchEntityType.project, SmartChipAspect.progress): _project_progress,
    (SearchEntityType.calendar_event, SmartChipAspect.when): _event_when,
    (SearchEntityType.task, SmartChipAspect.checklist): _task_checklist,
}


def parse_ref(
    ref: str,
) -> Optional[tuple[SearchEntityType, int, Optional[SmartChipAspect]]]:
    """``task:12`` or ``task:12:status`` as its parts, or ``None`` for neither.

    Two shapes on purpose. A bare reference asks what the thing is called,
    which every referenceable kind answers; adding an aspect asks a fact about
    it, which only some kinds have.

    A reference that does not parse is dropped rather than refused: a file
    can outlive a build that stopped offering one of these, and a chip that
    cannot be read falls back to the words stored beside it.
    """
    parts = ref.split(REF_SEPARATOR)
    if len(parts) not in (2, 3):
        return None
    # The name half is the bare reference every trigger writes, read by the
    # one parser that owns that shape.
    named = parse_bare_ref(REF_SEPARATOR.join(parts[:2]))
    if named is None:
        return None
    entity_type, entity_id = named
    if len(parts) == 2:
        return entity_type, entity_id, None
    try:
        aspect = SmartChipAspect(parts[2])
    except ValueError:
        return None
    if (entity_type, aspect) not in SMART_CHIP_SOURCES:
        return None
    return entity_type, entity_id, aspect


async def _titles(
    session: AsyncSession, entity_type: SearchEntityType, ids: list[int]
) -> dict[int, str]:
    """What these things are called right now.

    The column is whichever one the kind calls its name — derived, so a queue
    item answers with its label and a task with its title without either being
    written down here.
    """
    table = reference_targets.id_column(entity_type).table
    title = reference_targets.title_column(entity_type)
    rows = (
        await session.exec(select(table.c["id"], title).where(table.c["id"].in_(ids)))
    ).all()
    return {entity_id: name or "" for entity_id, name in rows}


async def _visible(
    session: AsyncSession,
    *,
    user_id: int,
    wanted: dict[SearchEntityType, set[int]],
    need_write: bool = False,
) -> dict[SearchEntityType, set[int]]:
    """Which of the things asked about this request may actually open.

    Being routed into the guild and being in the initiative is not the whole
    answer — a tool is shared per resource, and that is the gate this applies.
    The gate itself is derived: see :mod:`app.db.reference_targets`.

    Done here rather than inside each reader on purpose: a reader is never
    handed an id that did not come back from this, so a chip added later
    cannot forget it.
    """
    seen: dict[SearchEntityType, set[int]] = {}
    for entity_type, ids in wanted.items():
        statement = reference_targets.visible_ids(
            entity_type, user_id, need_write=need_write
        ).where(reference_targets.id_column(entity_type).in_(ids))
        # A Core-column select yields rows, not scalars.
        rows = (await session.exec(statement)).all()
        seen[entity_type] = {row[0] for row in rows}
    return seen


async def read_smart_chips(
    session: AsyncSession, *, user_id: int, refs: list[str]
) -> list[SmartChipState]:
    """Current state for every reference that resolves, in the order asked.

    Grouped by ``(kind, aspect)`` so each reader runs once over its whole set of
    ids. A reference naming something that is gone, or that this caller cannot
    see, is left out of the answer.
    """
    wanted: dict[tuple[SearchEntityType, Optional[SmartChipAspect]], list[int]] = {}
    parsed: list[
        tuple[str, tuple[SearchEntityType, Optional[SmartChipAspect]], int]
    ] = []
    for ref in dict.fromkeys(refs[:MAX_REFS]):
        resolved = parse_ref(ref)
        if resolved is None:
            continue
        entity_type, entity_id, aspect = resolved
        wanted.setdefault((entity_type, aspect), []).append(entity_id)
        parsed.append((ref, (entity_type, aspect), entity_id))

    by_type: dict[SearchEntityType, set[int]] = {}
    for (entity_type, _aspect), ids in wanted.items():
        by_type.setdefault(entity_type, set()).update(ids)
    visible = await _visible(session, user_id=user_id, wanted=by_type)
    # Whether each chip that can be acted on may be, asked at edit level of the
    # same gate — so the page offers the box only where ticking it would land.
    actionable: dict[SearchEntityType, set[int]] = {}
    for (entity_type, aspect), ids in wanted.items():
        if (entity_type, aspect) in ACTIONABLE_CHIP_KINDS:
            actionable.setdefault(entity_type, set()).update(
                i for i in ids if i in visible.get(entity_type, ())
            )
    writable = (
        await _visible(session, user_id=user_id, wanted=actionable, need_write=True)
        if actionable
        else {}
    )

    # What each thing is called, read once per kind and sent with every answer
    # about it. A chip carries the name of its own thing rather than the caller
    # asking for it separately, so showing a fact costs one reference and not
    # two — which is what keeps a long file inside :data:`MAX_REFS`.
    names: dict[SearchEntityType, dict[int, str]] = {}
    for entity_type, ids in by_type.items():
        allowed = [i for i in ids if i in visible.get(entity_type, ())]
        names[entity_type] = (
            await _titles(session, entity_type, allowed) if allowed else {}
        )

    read: dict[
        tuple[SearchEntityType, Optional[SmartChipAspect]], dict[int, SmartChipValue]
    ] = {}
    for pair, ids in wanted.items():
        entity_type, aspect = pair
        allowed = {i for i in ids if i in visible.get(entity_type, ())}
        if not allowed:
            read[pair] = {}
        elif aspect is None:
            # A bare reference asks only what the thing is called, so the name
            # already read IS the answer.
            read[pair] = {
                entity_id: SmartChipValue(text=name)
                for entity_id, name in names[entity_type].items()
                if entity_id in allowed
            }
        else:
            read[pair] = await SMART_CHIP_SOURCES[(entity_type, aspect)](
                session, sorted(allowed)
            )

    states: list[SmartChipState] = []
    for ref, pair, entity_id in parsed:
        value = read.get(pair, {}).get(entity_id)
        if value is None:
            continue
        states.append(
            SmartChipState(
                ref=ref,
                entity_type=pair[0],
                aspect=pair[1],
                text=value.text,
                title=names.get(pair[0], {}).get(entity_id),
                tone=value.tone,
                color=value.color,
                date=value.date,
                number=value.number,
                writable=(pair in ACTIONABLE_CHIP_KINDS)
                and entity_id in writable.get(pair[0], ()),
            )
        )
    return states


async def _descriptions(
    session: AsyncSession, entity_type: SearchEntityType, ids: list[int]
) -> dict[int, str]:
    """What these things say about themselves — read from the kind's own
    ``description`` column, so a kind has one here exactly when its table does."""
    table = reference_targets.id_column(entity_type).table
    if "description" not in table.c:
        return {}
    rows = (
        await session.exec(
            select(table.c["id"], table.c["description"]).where(table.c["id"].in_(ids))
        )
    ).all()
    return {entity_id: text for entity_id, text in rows if text}


#: The kinds whose body is prose, and which of their rows are: an embed of one
#: shows what it says, not only what it is called. A file is prose only as
#: a text document; a spreadsheet or a whiteboard embeds as its name.
_PROSE: dict[SearchEntityType, Callable[[Table], ColumnElement[bool]]] = {
    SearchEntityType.file: lambda t: t.c["file_type"] == FileType.lexical,
    SearchEntityType.wiki_page: lambda t: true(),
}


async def _bodies(
    session: AsyncSession, entity_type: SearchEntityType, ids: list[int]
) -> dict[int, dict]:
    """What these things say, in full — for the kinds in :data:`_PROSE`.

    An empty body is left out, the way an empty description is: there is
    nothing to show under the name. A wiki page still being drafted is left
    out for anyone who cannot edit it by the table's own read policy, which
    this request's session is under, as every other read of a page is.
    """
    prose = _PROSE.get(entity_type)
    if prose is None:
        return {}
    table = reference_targets.id_column(entity_type).table
    rows = (
        await session.exec(
            select(table.c["id"], table.c["content"]).where(
                table.c["id"].in_(ids), prose(table)
            )
        )
    ).all()
    return {entity_id: body for entity_id, body in rows if body}


async def read_embeds(
    session: AsyncSession, *, user_id: int, refs: list[str]
) -> list[ReferenceEmbed]:
    """Every embedded reference that resolves, in the order asked.

    Gated exactly as a chip is — through :func:`_visible` — so an embed of
    something gone or out of reach is left out of the answer.
    """
    wanted: dict[SearchEntityType, set[int]] = {}
    parsed: list[tuple[str, SearchEntityType, int]] = []
    for ref in dict.fromkeys(refs[:MAX_EMBEDS]):
        named = parse_bare_ref(ref)
        if named is None:
            continue
        entity_type, entity_id = named
        wanted.setdefault(entity_type, set()).add(entity_id)
        parsed.append((ref, entity_type, entity_id))

    visible = await _visible(session, user_id=user_id, wanted=wanted)
    names: dict[SearchEntityType, dict[int, str]] = {}
    described: dict[SearchEntityType, dict[int, str]] = {}
    bodies: dict[SearchEntityType, dict[int, dict]] = {}
    for entity_type, ids in visible.items():
        if not ids:
            continue
        allowed = sorted(ids)
        names[entity_type] = await _titles(session, entity_type, allowed)
        described[entity_type] = await _descriptions(session, entity_type, allowed)
        bodies[entity_type] = await _bodies(session, entity_type, allowed)

    return [
        ReferenceEmbed(
            ref=ref,
            entity_type=entity_type,
            title=names[entity_type][entity_id],
            description=described[entity_type].get(entity_id),
            body=bodies[entity_type].get(entity_id),
        )
        for ref, entity_type, entity_id in parsed
        if entity_id in names.get(entity_type, {})
    ]
