"""The tasks of one repeating series, and changing one of them alone.

A repeating task makes the next task of its series when it is completed
(``advance_recurrence_if_needed``), copied from itself. Every task
the series has made carries ``series_id``, the id of its first task, from the
moment the series first moves on. The repeat moves to the new task, and the
finished one stops repeating.

The next task's date is counted by the task's ``recurrence_strategy``
(:func:`next_dates`): "On schedule" (``fixed``) from the due date, "After
completion" (``rolling``) from when the task was finished. Skipping a task
(:func:`skip`) moves it to the date the next task would have had.

An edit asks which tasks it is for:

- **this** — the task keeps the values it changed from in
  ``recurrence_carry``, and the next task is made with those, so the change
  stays on this task;
- **following** — the next task is copied from this one, so the change carries
  forward (what an edit always did);
- **all** — also every other task of the series, completed ones included, for
  the fields the tasks share (:data:`SHARED`).

Nothing here commits.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from types import EllipsisType
from typing import Any

from sqlalchemy.orm import joinedload, selectinload
from sqlmodel import or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import recurrence
from app.core.user_input_validators import resolve_zone
from app.models.tenant.project import Project
from app.models.tenant.tag import Tag
from app.models.tenant.task import (
    RecurrenceStrategy,
    Task,
    TaskPriority,
    TaskStatusCategory,
    TaskType,
)
from app.schemas.recurrence import OccurrenceScope
from app.services.tenant import properties as properties_service
from app.services.tenant import tags as tags_service
from app.services.tenant import task_checklist as checklist_service
from app.services.tenant import descriptions as descriptions_service
from app.services.tenant import task_statuses as task_statuses_service
from app.services.tenant.task_completion import sync_completed_at
from app.services.tenant.task_creation import next_position, set_task_assignees

#: What an edit of just one task keeps from the rest of its series.
CARRIED = (
    "title",
    "description",
    "priority",
    "start_date",
    "due_date",
    "assignee_ids",
    "tag_ids",
    "task_type_id",
)
#: What an edit of every task reaches. Dates, status, checklist and the repeat
#: are each task's own.
SHARED = frozenset(
    {"title", "description", "priority", "assignee_ids", "tag_ids", "task_type_id"}
)
_DATES = frozenset({"start_date", "due_date"})
_TAGS = tags_service.TAG_LINKS["task"]


def _stored(field: str, value: Any) -> Any:
    if field in _DATES:
        return value.isoformat() if value is not None else None
    if field == "priority":
        return TaskPriority(value).value
    if field in {"assignee_ids", "tag_ids"}:
        return sorted(set(value))
    return value


def _loaded(field: str, value: Any) -> Any:
    if field in _DATES:
        return datetime.fromisoformat(value) if value is not None else None
    if field == "priority":
        return TaskPriority(value)
    return value


async def values_of(session: AsyncSession, task: Task) -> dict[str, Any]:
    """The task's :data:`CARRIED` fields as ``recurrence_carry`` holds them."""
    tag_ids = await tags_service.active_tag_ids(session, _TAGS, task.id)
    return {
        "title": task.title,
        "description": task.description,
        "priority": _stored("priority", task.priority),
        "start_date": _stored("start_date", task.start_date),
        "due_date": _stored("due_date", task.due_date),
        "assignee_ids": _stored("assignee_ids", [a.id for a in task.assignees]),
        "tag_ids": _stored("tag_ids", tag_ids),
        "task_type_id": task.task_type_id,
    }


def edited(
    task: Task,
    before: dict[str, Any],
    *,
    scope: OccurrenceScope | None,
    assignee_ids: list[int] | None,
    tag_ids: list[int] | None,
) -> tuple[dict[str, Any], set[str]]:
    """The task's :data:`CARRIED` fields once an edit has set its columns and
    sent these lists (``None`` = unchanged), and which of them it changed.

    An edit of just this task remembers what each field changed from, so the
    next task is made with that; a field set back to the series' value no
    longer needs remembering. Any other edit carries its changes forward."""
    after = {
        field: _stored(field, getattr(task, field))
        for field in (
            "title",
            "description",
            "priority",
            "start_date",
            "due_date",
            "task_type_id",
        )
    }
    after["assignee_ids"] = (
        before["assignee_ids"]
        if assignee_ids is None
        else _stored("assignee_ids", assignee_ids)
    )
    after["tag_ids"] = (
        before["tag_ids"] if tag_ids is None else _stored("tag_ids", tag_ids)
    )
    moved = {field for field in CARRIED if before[field] != after[field]}
    if scope == "this" and task.recurrence:
        carry = dict(task.recurrence_carry or {})
        for field in moved:
            carry.setdefault(field, before[field])
            if carry[field] == after[field]:
                del carry[field]
        task.recurrence_carry = carry or None
    else:
        _release(task, moved)
    return after, moved


def _release(task: Task, fields: set[str]) -> None:
    """These fields carry forward again, as this task now has them."""
    carry = {
        field: value
        for field, value in (task.recurrence_carry or {}).items()
        if field not in fields
    }
    task.recurrence_carry = carry or None


def carried(task: Task) -> dict[str, Any]:
    """What the next task of the series is made with in place of this task's
    own values."""
    return {
        field: _loaded(field, value)
        for field, value in (task.recurrence_carry or {}).items()
    }


def anchor_from_dates(task: Task) -> tuple[datetime | None, int]:
    """A fresh anchor and consumed count from the series' effective dates.

    Used when writing a new baseline, or as a read-only fallback for a task
    without a saved anchor. A this-only edit keeps the series' dates in carry.
    """
    values = carried(task)
    start = values.get("due_date", task.due_date) or values.get(
        "start_date", task.start_date
    )
    return (start if task.recurrence else None), task.recurrence_occurrence_count


def repeat_edited(
    task: Task,
    sent: str | None | EllipsisType,
    *,
    previous_start: datetime | None,
    tz: str | None,
    scope: OccurrenceScope | None,
) -> None:
    """The task's repeat once an edit has set its dates
    (:func:`recurrence.edited`). An edit of just this task leaves the series'
    repeat where it was; a task that stops repeating counts afresh if it
    repeats again."""
    if sent is None:
        task.recurrence_occurrence_count = 0
        task.recurrence_strategy = RecurrenceStrategy.fixed
        task.recurrence_limit = None
    start = task.due_date or task.start_date
    task.recurrence, task.recurrence_shift = recurrence.edited(
        task.recurrence,
        task.recurrence_shift,
        sent,
        moved=start != previous_start and scope != "this",
        old_start=previous_start,
        new_start=start,
        tz=tz,
        kind="task",
    )


async def next_dates(
    session: AsyncSession,
    task: Task,
    *,
    now: datetime,
    user_timezone: str | None,
    skipping: bool = False,
    completing: bool = True,
) -> tuple[datetime | None, datetime] | None:
    """The next task's start and due dates, or ``None`` when the series has no
    more. Raises ``ValueError`` for a rule that does not parse."""
    rule = recurrence.parse(task.recurrence).rule
    values = carried(task)
    due = values.get("due_date", task.due_date)
    start = values.get("start_date", task.start_date)
    rolling = task.recurrence_strategy == RecurrenceStrategy.rolling
    done = task.recurrence_occurrence_count
    hourly = rule.get("FREQ") == ["HOURLY"]
    if hourly:
        if not rolling:
            raise ValueError("Hourly task recurrence requires rolling")
        # Sub-minute completion precision does not move an hourly schedule.
        base = max(now, due) if skipping else now
        base = base.replace(second=0, microsecond=0)
    elif rolling:
        # Rolling counts from the completer's local day, at the task's own
        # local time of day: a 5pm LA task is midnight UTC the next day, so a
        # UTC day would land a day early. The zone is the request's, read here
        # and never stored.
        zone = resolve_zone(user_timezone)
        due_local = due.astimezone(zone)
        base = (
            now.astimezone(zone)
            .replace(
                hour=due_local.hour,
                minute=due_local.minute,
                second=due_local.second,
                microsecond=due_local.microsecond,
            )
            .astimezone(zone)
        )
    else:
        if task.recurrence_anchor is None:
            base, done = anchor_from_dates(task)
        else:
            base, done = task.recurrence_anchor, task.recurrence_anchor_count
    # Rolling tasks restart from completion, so their counter ends a COUNT.
    # Fixed tasks keep their anchor: dateutil counts only the rule's starts,
    # before EXDATE/RDATE, as RFC 5545 requires.
    count = rule.get("COUNT", [None])[0]
    consumed = task.recurrence_occurrence_count + (1 if completing or skipping else 0)
    if rolling and count is not None and consumed >= count:
        return None
    next_due = recurrence.next_start(
        task.recurrence,
        base,
        task.recurrence_shift,
        count=not rolling,
        after=None if rolling else due,
        done=done,
    )
    if next_due is None:
        return None
    if hourly and task.recurrence_limit is not None:
        next_due = await _limited_hourly_due(
            session,
            task,
            now=now,
            due=due,
            next_due=next_due,
            user_timezone=user_timezone,
            skipping=skipping,
            completing=completing,
        )
        if next_due is None:
            return None
        if "UNTIL" in rule:
            until = recurrence.last_start(task.recurrence, due, task.recurrence_shift)
            if until is not None and next_due > until:
                return None
    length: timedelta | None = due - start if start and due else None
    return (next_due - length if length is not None else None), next_due


async def _limited_hourly_due(
    session: AsyncSession,
    task: Task,
    *,
    now: datetime,
    due: datetime,
    next_due: datetime,
    user_timezone: str | None,
    skipping: bool,
    completing: bool,
) -> datetime | None:
    """A cap and daily reset derived only from this series' completion rows.

    Read through the caller's guild/RLS session. Trashed completions still
    happened, and count until those rows are permanently removed. A skipped
    task has no completion timestamp and never consumes the daily allowance.
    """
    zone = resolve_zone(user_timezone)
    limit = task.recurrence_limit
    if limit is None:
        return next_due
    local_day = (max(now, due) if skipping else now).astimezone(zone).date()
    lower = datetime.combine(local_day, time.min, zone).astimezone(timezone.utc)
    upper = datetime.combine(local_day + timedelta(days=1), time.min, zone).astimezone(
        timezone.utc
    )
    series = task.series_id or task.id
    history = (
        await session.exec(
            select(Task.completed_at, Task.due_date)
            .where(
                or_(Task.series_id == series, Task.id == series),
                Task.id != task.id,
                Task.completed_at >= lower,
                Task.completed_at < upper,
            )
            .order_by(Task.completed_at, Task.id)
            .execution_options(include_deleted=True)
        )
    ).all()
    count = len(history) + (1 if completing and not skipping else 0)
    first_due = next(
        (historic_due for _, historic_due in history if historic_due is not None), due
    )
    if count < limit and next_due.astimezone(zone).date() == local_day:
        return next_due
    reset = datetime.combine(
        local_day + timedelta(days=1), first_due.astimezone(zone).time(), zone
    ).astimezone(timezone.utc)
    # Date filters may have moved next_due several days beyond the elapsed
    # interval. A daily reset starts a new hourly grid on its chosen day.
    base = max(now, due) if skipping else now
    parsed = recurrence.parse(task.recurrence)
    interval = parsed.rule.get("INTERVAL", [1])[0]
    earliest = base.astimezone(timezone.utc).replace(
        second=0, microsecond=0
    ) + timedelta(hours=interval)
    reset = max(reset, earliest)
    # Find the next allowed day independently of the elapsed hourly interval;
    # a long interval's grid must not skip otherwise eligible reset days.
    days = recurrence.Recurrence(
        {**parsed.rule, "INTERVAL": [1]}, parsed.exdates, parsed.rdates
    ).to_lines()
    starts = recurrence.first(days, reset, task.recurrence_shift, 1)
    if not starts:
        return None
    candidate = starts[0]
    anchor = datetime.combine(
        candidate.astimezone(zone).date(), first_due.astimezone(zone).time(), zone
    ).astimezone(timezone.utc)
    starts = recurrence.first(
        task.recurrence, max(anchor, earliest), task.recurrence_shift, 1
    )
    return starts[0] if starts else None


async def reschedule_hourly(
    session: AsyncSession,
    task: Task,
    *,
    user_timezone: str | None,
    due_sent: bool,
    rule_changed: bool,
) -> None:
    """Settings edits recalculate the pending task from its last real completion."""
    if task.recurrence_strategy != RecurrenceStrategy.rolling or not task.recurrence:
        return
    if recurrence.parse(task.recurrence).rule.get("FREQ") != ["HOURLY"]:
        return
    series = task.series_id or task.id
    last = (
        await session.exec(
            select(Task.completed_at)
            .where(
                or_(Task.series_id == series, Task.id == series),
                Task.id != task.id,
                Task.completed_at.isnot(None),
            )
            .order_by(Task.completed_at.desc(), Task.id.desc())
            .limit(1)
            .execution_options(include_deleted=True)
        )
    ).first()
    if last is None:
        return
    dates = await next_dates(
        session, task, now=last, user_timezone=user_timezone, completing=False
    )
    if dates is None:
        raise ValueError("INVALID_RECURRENCE_LIMIT")
    _, minimum = dates
    if due_sent:
        if task.due_date is None or task.due_date < minimum:
            raise ValueError("INVALID_RECURRENCE_LIMIT")
    elif rule_changed:
        zone = resolve_zone(user_timezone)
        if task.due_date is not None:
            # A future day's pending occurrence may have been explicitly skipped.
            day = task.due_date.astimezone(zone).date()
            if minimum.astimezone(zone).date() < day:
                minimum = max(
                    minimum,
                    datetime.combine(
                        day, minimum.astimezone(zone).time(), zone
                    ).astimezone(timezone.utc),
                )
                starts = recurrence.first(
                    task.recurrence, minimum, task.recurrence_shift, 1
                )
                if not starts:
                    raise ValueError("INVALID_RECURRENCE_LIMIT")
                minimum = starts[0]
        length = (
            task.due_date - task.start_date
            if task.due_date and task.start_date
            else None
        )
        task.due_date = minimum
        task.start_date = minimum - length if length is not None else None


async def retag(session: AsyncSession, task_id: int, tag_ids: list[int]) -> None:
    """Give the task these tags, leaving out any trashed since."""
    live = (await session.exec(select(Tag.id).where(Tag.id.in_(tag_ids)))).all()
    await tags_service.replace_entity_tags(session, _TAGS, task_id, sorted(live))


async def advance_recurrence_if_needed(
    session: AsyncSession,
    task: Task,
    *,
    previous_status_category: TaskStatusCategory | None,
    now: datetime,
    user_timezone: str | None,
) -> bool:
    """Make the next task of the series when this change completed ``task``.
    The repeat moves to the new task, and ``task`` stops repeating. False when
    the task was not just completed, does not repeat, or its series has no
    more."""
    category = task.task_status.category if task.task_status else None
    if (
        previous_status_category == TaskStatusCategory.done
        or category != TaskStatusCategory.done
        or not task.recurrence
        or task.due_date is None
    ):
        return False
    try:
        dates = await next_dates(session, task, now=now, user_timezone=user_timezone)
    except ValueError:
        return False
    if dates is None:
        task.recurrence = None
        task.recurrence_limit = None
        return False
    new_task = await _next_task(session, task, dates, now=now, in_place=False)
    await session.flush()
    # Reload through a select rather than ``session.refresh``: refresh takes no
    # loader options, so the assignees would come back unloaded and the
    # serializer would have to emit IO from sync context. ``populate_existing``
    # applies the freshly loaded rows to the identity-mapped instance.
    await session.exec(
        select(Task)
        .where(Task.id == new_task.id)
        .options(selectinload(Task.assignees))
        .execution_options(populate_existing=True)
    )
    await tags_service.annotate_tags(session, [new_task])
    await properties_service.annotate_properties(session, [new_task])

    task.recurrence = None
    task.recurrence_strategy = RecurrenceStrategy.fixed
    task.recurrence_limit = None
    task.recurrence_carry = None
    task.updated_at = now
    session.add(task)
    return True


async def skip(
    session: AsyncSession, task: Task, *, now: datetime, user_timezone: str | None
) -> bool:
    """Move the task on to the next occurrence without completing it, as the
    next task would have been made. False when the series has no more."""
    if task.due_date is None:
        return False
    try:
        dates = await next_dates(
            session, task, now=now, user_timezone=user_timezone, skipping=True
        )
    except ValueError:
        return False
    if dates is None:
        return False
    await _next_task(session, task, dates, now=now, in_place=True)
    return True


async def _next_task(
    session: AsyncSession,
    task: Task,
    dates: tuple[datetime | None, datetime],
    *,
    now: datetime,
    in_place: bool,
) -> Task:
    """The next task of the series, on ``dates``: ``task`` itself moved on
    (``in_place``, a skip), or a new task copied from it (a completion). Both
    take what an edit of just ``task`` changed from (:func:`carried`)."""
    if (
        task.recurrence_strategy == RecurrenceStrategy.fixed
        and task.recurrence_anchor is None
    ):
        # Save the effective baseline before advancing dates or releasing carry.
        task.recurrence_anchor, task.recurrence_anchor_count = anchor_from_dates(task)
    values = carried(task)
    task.series_id = task.series_id or task.id
    default_status = await task_statuses_service.get_default_status(
        session, task.project_id
    )
    if in_place:
        following = task
        following.task_status_id = default_status.id  # ty: ignore[invalid-assignment] — persisted row, id is set
    else:
        following = Task(
            project_id=task.project_id,
            task_status_id=default_status.id,
            task_type_id=task.task_type_id,
            title=task.title,
            description=task.description,
            priority=task.priority,
            recurrence=task.recurrence,
            recurrence_shift=task.recurrence_shift,
            recurrence_anchor=task.recurrence_anchor,
            recurrence_anchor_count=task.recurrence_anchor_count,
            recurrence_strategy=task.recurrence_strategy,
            recurrence_limit=task.recurrence_limit,
            position=await next_position(session, task.project_id),
            series_id=task.series_id,
            created_by=task.created_by,
        )
    following.task_status = default_status
    for field in ("title", "description", "priority"):
        if field in values:
            setattr(following, field, values[field])
    if "task_type_id" in values and await _still_a_type_of(
        session, values["task_type_id"], task.project_id
    ):
        following.task_type_id = values["task_type_id"]
    sync_completed_at(following, default_status.category, now=now)
    following.start_date, following.due_date = dates
    following.recurrence_occurrence_count = task.recurrence_occurrence_count + 1
    following.checklist = checklist_service.cloned(task.checklist)
    following.recurrence_carry = None
    following.updated_at = now
    if not in_place:
        session.add(following)
        await session.flush()

    # A new task takes the people and tags of the one it is copied from; a
    # skipped task keeps its own unless an edit of just it changed them.
    if "assignee_ids" in values or not in_place:
        project = await session.get(Project, task.project_id)
        if project is None:  # the task was just read inside it
            raise RuntimeError("a repeating task's project is gone")
        await set_task_assignees(
            session,
            following,
            values.get("assignee_ids", [assignee.id for assignee in task.assignees]),
            project=project,
            carried=True,
        )
    if "tag_ids" in values:
        await retag(session, following.id, values["tag_ids"])
    elif not in_place:
        await tags_service.copy_entity_tags(session, _TAGS, {task.id: following.id})
    if "description" in values or (not in_place and following.description):
        await descriptions_service.record_references(
            session, following, author_id=task.created_by
        )
    return following


async def _still_a_type_of(
    session: AsyncSession, type_id: Any, project_id: int
) -> bool:
    """Whether a type a task kept back is still one of its project's: it may
    have been deleted since, or the task moved to another project."""
    if not isinstance(type_id, int):
        return False
    kept = await session.get(TaskType, type_id)
    return kept is not None and kept.project_id == project_id


async def others(session: AsyncSession, task: Task) -> list[Task]:
    """Every other live task of the task's series, with its project."""
    if task.series_id is None:
        return []
    statement = (
        select(Task)
        .where(Task.series_id == task.series_id, Task.id != task.id)
        .options(
            joinedload(Task.project).joinedload(Project.initiative),
            selectinload(Task.assignees),
        )
    )
    return list((await session.exec(statement)).all())


async def apply_to_others(
    session: AsyncSession,
    members: list[Task],
    after: dict[str, Any],
    fields: set[str],
    *,
    now: datetime,
    author_id: int | None,
) -> None:
    """Give every other task of the series the task's new :data:`SHARED`
    values. The caller has checked it may change each one."""
    fields = fields & SHARED
    if not fields:
        return
    # A type is its project's: a task of the series that was moved to another
    # project keeps its own.
    shared_type = (
        await session.get(TaskType, after["task_type_id"])
        if "task_type_id" in fields
        else None
    )
    type_project = shared_type.project_id if shared_type is not None else None
    for member in members:
        for field in fields - {"assignee_ids", "tag_ids"}:
            if field == "task_type_id" and member.project_id != type_project:
                continue
            setattr(member, field, _loaded(field, after[field]))
        if "assignee_ids" in fields:
            await set_task_assignees(
                session,
                member,
                after["assignee_ids"],
                project=member.project,
                carried=True,
            )
        if "tag_ids" in fields:
            await tags_service.replace_entity_tags(
                session, _TAGS, member.id, after["tag_ids"]
            )
        if "description" in fields:
            await descriptions_service.record_references(
                session, member, author_id=author_id
            )
        _release(member, fields)
        member.updated_at = now
