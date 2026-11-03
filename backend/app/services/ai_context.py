"""What an AI feature tells the model: about a task, or about what changed in
a community while a member was away.

Everything is read on the member's own session, so what they cannot read never
reaches a prompt. The reads are the app's own read shapes, trimmed as the MCP
server trims its results (:mod:`app.services.compact`), and sent as compact
JSON.

The task, its project and the open tasks linked to it always go in. Its
comments fill what is left of the budget, newest first; when they do not all
fit, the result says how many were read. A catch-up is the activity feed's
entries since a moment, in the feed's own order, as many as the budget holds.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from sqlalchemy import func, tuple_
from sqlalchemy.orm import selectinload
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.identity_boundary import STORED_MENTION
from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.core.user_display import display_name
from app.models.platform.user_profile_view import MemberProfile
from app.models.tenant.comment import Comment, in_thread
from app.models.tenant.metadata import MetadataType
from app.models.tenant.task import Task, TaskStatus, TaskStatusCategory
from app.schemas.tenant.property import PropertySummary
from app.schemas.tenant.task import TaskRead
from app.services import compact
from app.services.tenant import activity_feed
from app.services.tenant import relationships as relationships_service
from app.services.tenant import task_queries

#: Roughly how many characters a token holds, to keep a prompt near its budget.
_CHARS_PER_TOKEN = 4
_COMMENT_PAGE = 100

#: What a model is told of a task: the fields that describe the work.
_TASK_FIELDS: dict[str, Any] = {
    "title": True,
    "description": True,
    "priority": True,
    "start_date": True,
    "due_date": True,
    "task_status": {"name", "category"},
    "task_type": {"name"},
    "checklist": {"__all__": {"text", "done"}},
    "tags": {"__all__": {"name"}},
}
#: A field's value is the member's own, passed through as it is.
_FREE_FORM = frozenset({"value"})


@dataclass(frozen=True)
class TaskContext:
    """The task as the prompt carries it."""

    #: Compact JSON: the task, its project, its open linked tasks and the
    #: comments that fit.
    data: str
    comments_read: int
    comments_total: int


async def task_context(
    session: AsyncSession, task: Task, *, budget: int
) -> TaskContext:
    """``task`` as the reader ``session`` is routed for reads it, within about
    ``budget`` tokens."""
    loaded = await task_queries.load_task(session, task.id)  # type: ignore[arg-type]
    read = TaskRead.model_validate(loaded)
    told = read.model_dump(mode="json", include=_TASK_FIELDS)
    told["assignees"] = [display_name(person) for person in read.assignees]
    told["properties"] = [
        {"name": field.name, "value": _shown(field)} for field in read.properties
    ]
    parts: dict[str, Any] = {
        "task": told,
        "project": {"name": task.project.name, "description": task.project.description},
        "linked_tasks": await _open_linked_tasks(session, task.id),  # type: ignore[arg-type]
    }
    room = budget * _CHARS_PER_TOKEN - len(_dumps(compact.trim(parts, _FREE_FORM)))
    comments, total = await _recent_comments(session, task.id, room=room)  # type: ignore[arg-type]
    parts["comments"] = comments
    data = await _named(session, _dumps(compact.trim(parts, _FREE_FORM)))
    return TaskContext(data=data, comments_read=len(comments), comments_total=total)


@dataclass(frozen=True)
class ActivityContext:
    """What changed, as the prompt carries it."""

    #: One compact JSON line per item, as many as fit.
    data: str
    #: Where the changes read start: the moment asked for, or where the change
    #: log's window begins when that is later.
    since: datetime
    entries_read: int
    entries_total: int


async def activity_context(
    session: AsyncSession,
    *,
    reader_id: int,
    since: datetime | None,
    tool: Tool | None,
    tool_id: int | None,
    budget: int,
) -> ActivityContext:
    """The items people changed since ``since`` that the reader can see, in
    the whole community or in one tool, within about ``budget`` tokens."""
    window = datetime.now(timezone.utc) - activity_feed.WINDOW
    start = max(since, window) if since else window
    entries, _ = await activity_feed.feed(
        session,
        reader_id=reader_id,
        tool=tool,
        tool_id=tool_id,
        since=start,
        page_size=activity_feed.CANDIDATE_CHANGES,
    )
    room = budget * _CHARS_PER_TOKEN
    lines: list[str] = []
    for entry in entries:
        line = _dumps(
            compact.trim(
                {
                    "item": entry.title,
                    "kind": entry.entity_type,
                    "in": entry.tool_title,
                    "initiative": entry.initiative_name,
                    "did": entry.verbs,
                    "by": [display_name(person) for person in entry.actors],
                    "others": entry.actor_count - len(entry.actors),
                    "at": entry.latest.isoformat(timespec="minutes"),
                }
            )
        )
        room -= len(line) + 1
        if room < 0:
            break
        lines.append(line)
    return ActivityContext(
        data=await _named(session, "\n".join(lines)),
        since=start,
        entries_read=len(lines),
        entries_total=len(entries),
    )


def _shown(field: PropertySummary) -> Any:
    """A field's value as the task's page shows it: an option by its label,
    a person by their name."""
    value = field.model_dump(mode="json", include={"value"}).get("value")
    if field.options and value is not None:
        labels = {option.value: option.label for option in field.options}
        if isinstance(value, list):
            return [labels.get(item, item) for item in value]
        return labels.get(value, value)
    if field.type is MetadataType.user_reference and isinstance(value, dict):
        return display_name(SimpleNamespace(**value))
    return value


def _dumps(value: Any) -> str:
    """Compact JSON that cannot close the tag it is sent in."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace(
        "<", "\\u003c"
    )


async def _open_linked_tasks(session: AsyncSession, task_id: int) -> list[str]:
    """The unfinished tasks linked to this one, each as how it is linked."""
    anchor = relationships_service.Endpoint(SearchEntityType.task, task_id)
    edges = await relationships_service.list_for_entity(
        session, anchor, other_kind=SearchEntityType.task
    )
    links: dict[int, list[str]] = {}
    for edge in edges:
        outbound = edge.source_node == anchor.node
        other = edge.target_id if outbound else edge.source_id
        links.setdefault(other, []).append(
            f"this task {edge.relationship_type} it"
            if outbound
            else f"it {edge.relationship_type} this task"
        )
    if not links:
        return []
    rows = await session.exec(
        select(Task.id, Task.title)
        .join(TaskStatus, col(TaskStatus.id) == Task.task_status_id)
        .where(
            col(Task.id).in_(links),
            TaskStatus.category != TaskStatusCategory.done,
            col(Task.archived_at).is_(None),
            col(Task.deleted_at).is_(None),
        )
        .order_by(col(Task.id))
    )
    return [
        f"{title} ({'; '.join(links[other])})"
        for other, title in rows.all()  # type: ignore[misc]
    ]


async def _recent_comments(
    session: AsyncSession, task_id: int, *, room: int
) -> tuple[list[dict[str, Any]], int]:
    """The newest of the task's comments that fit in ``room`` characters,
    oldest first, and how many there are in all.

    Read newest first across the whole thread, replies included, so a reply
    written today under an old conversation goes in before older comments.
    """
    live = (
        col(Comment.task_id) == task_id,
        in_thread(),
        col(Comment.deleted_at).is_(None),
        col(Comment.removed_at).is_(None),
    )
    taken: list[dict[str, Any]] = []
    after: tuple[datetime, int | None] | None = None
    while True:
        statement = (
            select(Comment)
            .where(*live)
            .order_by(col(Comment.created_at).desc(), col(Comment.id).desc())
            .limit(_COMMENT_PAGE)
            .options(selectinload(Comment.author))  # type: ignore[arg-type]
        )
        if after is not None:
            statement = statement.where(tuple_(Comment.created_at, Comment.id) < after)
        page = (await session.exec(statement)).all()
        for comment in page:
            row = compact.trim(
                {
                    "by": comment.imported_author_name or display_name(comment.author),
                    "at": comment.created_at.isoformat(timespec="minutes"),
                    "text": comment.content,
                }
            )
            room -= len(_dumps(row)) + 1
            if room < 0:
                total = (await session.exec(select(func.count()).where(*live))).one()
                return taken[::-1], total
            taken.append(row)
        if len(page) < _COMMENT_PAGE:
            return taken[::-1], len(taken)
        after = (page[-1].created_at, page[-1].id)


async def _named(session: AsyncSession, data: str) -> str:
    """``data`` with each mention as the name the person goes by here."""
    ids = {int(user_id) for _, user_id in STORED_MENTION.findall(data)}
    if not ids:
        return data
    profiles = await session.exec(
        select(MemberProfile).where(col(MemberProfile.id).in_(ids))
    )
    names = {profile.id: display_name(profile) for profile in profiles.all()}

    def name(match: Any) -> str:
        shown = names.get(int(match.group(2))) or match.group(1) or "someone"
        return "@" + _dumps(shown)[1:-1]

    return STORED_MENTION.sub(name, data)
