"""What a notification line is about, read at the moment the line is read.

A notification names the thing it is about — a task, a file, the post
somebody published — and the bell needs that thing's title to say anything
useful. The row itself carries only the identifiers, so the titles are read
here, from the community's own schema, through the same seam a
``/c/{community_id}`` request goes through.

Reading them rather than storing them is what keeps a line honest: a task
renamed after the mention shows its new name, and a line whose subject the
reader can no longer reach resolves to nothing, which is what the bell renders
as its plain form.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tool_set import ToolSet
from app.core.tools import CONTENT_KINDS, plural_of
from app.db.session import routed_tools
from app.db.tool_rows import locate
from app.models.platform.notification import Notification
from app.models.tenant._mixins import tool_models
from app.models.tenant.calendar_event import CalendarEvent
from app.models.tenant.initiative import Initiative
from app.models.tenant.post import Post
from app.models.tenant.project import Project
from app.models.tenant.task import Task
from app.services.cross_guild import gather_across_guilds

__all__ = ["SUBJECTS", "Subject", "resolve_subjects"]


@dataclass(frozen=True)
class Subject:
    """One value a line needs, and where to read it.

    ``key`` is what the payload is filled with, ``id_key`` the identifier the
    row already carries, and ``model``/``column`` where the title lives inside
    the community's schema.
    """

    key: str
    id_key: str
    model: type[Any]
    column: str


#: The titles a line can name, by the identifier it carries. Adding a notifier
#: that names something new is one entry here.
SUBJECTS: tuple[Subject, ...] = (
    Subject("task_title", "task_id", Task, "title"),
    Subject("mentioned_task_title", "mentioned_task_id", Task, "title"),
    Subject("project_name", "project_id", Project, "name"),
    Subject("initiative_name", "initiative_id", Initiative, "name"),
    Subject("post_name", "post_id", Post, "name"),
    Subject("event_title", "event_id", CalendarEvent, "title"),
)

_ENTITY_KEYS: tuple[tuple[str, str, str], ...] = (
    # (key to fill, id key, type key). Three spellings of the same pair, from
    # the three notifiers that grew them; the first that resolves wins.
    ("entity_name", "entity_id", "entity_type"),
    ("context_title", "entity_id", "entity_type"),
    ("context_title", "context_entity_id", "context_entity_type"),
    ("context_title", "target_id", "target_type"),
)


def _as_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except TypeError, ValueError:
        return None


#: One line's needs, flattened: the key to fill, where its title lives (a
#: model and its column, or a kind the community's tool set names, with no
#: column) and the row that fills it. Read off the notification BEFORE any
#: routing happens, because routing detaches the rows this was read from.
_Need = tuple[str, type[Any] | str, str | None, int]


def _needs(line: Notification) -> list[_Need]:
    data: Mapping[str, Any] = line.data or {}
    out: list[_Need] = []
    for subject in SUBJECTS:
        row_id = _as_int(data.get(subject.id_key))
        if row_id is not None:
            out.append((subject.key, subject.model, subject.column, row_id))
    for key, id_key, type_key in _ENTITY_KEYS:
        entity_type = data.get(type_key)
        row_id = _as_int(data.get(id_key))
        if isinstance(entity_type, str) and row_id is not None:
            out.append((key, entity_type, None, row_id))
    return out


def _titles(
    tools: ToolSet, source: type[Any] | str, column: str | None, ids: set[int]
) -> Any | None:
    """The ids and titles of these rows: a fixed subject's, by its model and
    column; or a polymorphic one's — a comment names whatever it is on, and a
    subscription notice whatever changed, any tool or anything inside one, a
    tool plug-in's among them, in ``entity_type`` — by the table the
    community's tool set keeps that kind in, labelled by a model's own display
    column or a tool plug-in's ``name``. None for a kind the community does
    not have."""
    if isinstance(source, str):
        located = locate(tools, source)
        if located is not None:
            table = located.table
            return select(table.c.id, table.c.name).where(
                table.c.id.in_(ids), table.c.deleted_at.is_(None)
            )
        if source not in CONTENT_KINDS:
            return None
        source = tool_models()[plural_of(source)]
        column = source.display_field()
    return select(source.id, getattr(source, cast(str, column))).where(
        source.id.in_(ids)
    )


async def resolve_subjects(
    session: AsyncSession,
    user_id: int,
    notifications: Sequence[Notification],
) -> dict[int, dict[str, str]]:
    """Titles for each line, keyed by notification id.

    Visits each community the page names, once. A community this reader cannot
    reach, and a row inside one they cannot see, contribute nothing — so what
    comes back is what the reader may be told now, rather than what was true
    when the line was written.
    """
    # Snapshot first: gathering routes the session into each schema in turn and
    # detaches what was read on the way in.
    plan: list[tuple[int, int, list[_Need]]] = []
    wanted: dict[int, dict[tuple[type[Any] | str, str | None], set[int]]] = {}
    for line in notifications:
        if line.id is None or line.guild_id is None:
            continue
        needs = _needs(line)
        if not needs:
            continue
        plan.append((line.id, line.guild_id, needs))
        per_guild = wanted.setdefault(line.guild_id, {})
        for _key, source, column, row_id in needs:
            per_guild.setdefault((source, column), set()).add(row_id)
    if not wanted:
        return {}

    async def _fetch(
        guild_session: AsyncSession, guild_id: int
    ) -> list[tuple[tuple[int, type[Any] | str, str | None, int], str]]:
        found: list[tuple[tuple[int, type[Any] | str, str | None, int], str]] = []
        tools = routed_tools(guild_session)
        for (source, column), ids in wanted.get(guild_id, {}).items():
            statement = _titles(tools, source, column, ids)
            if statement is None:
                continue
            for row_id, value in await guild_session.exec(statement):
                if isinstance(value, str) and value:
                    found.append(((guild_id, source, column, row_id), value))
        return found

    titles = dict(
        await gather_across_guilds(session, {user_id: sorted(wanted)}, _fetch)
    )

    resolved: dict[int, dict[str, str]] = {}
    for notification_id, guild_id, needs in plan:
        found = {
            key: titles[(guild_id, source, column, row_id)]
            for key, source, column, row_id in needs
            if (guild_id, source, column, row_id) in titles
        }
        if found:
            resolved[notification_id] = found
    return resolved
