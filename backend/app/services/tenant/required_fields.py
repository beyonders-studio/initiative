"""What a person must fill in on an item, as its page's layout requires, and
the check that holds them to it.

A detail layout marks fields required (``tool_layouts.required_keys``): a
project's task page per task type, the calendar's event page and the posts page
of an initiative, and a collection's file page for the collection's own
metadata. A person adding an item fills each in, and cannot empty one once it
is filled. An item that lacks one already, made before it was required or by a
path that is not held to it, keeps it until a person fills it.

Who is held to it is who a board's column limits hold
(:func:`app.db.guild_standing.by_a_person`): a person, through the app or the
API, and a plug-in acting for a member. A plug-in acting as itself, an
automation, an import and the project's own machinery (a repeating task's next
one, a copy) are not, and the item shows the field as missing.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable, Optional

from sqlalchemy import exists, func, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import CodedError
from app.core.messages import ToolLayoutMessages
from app.core.tools import Tool
from app.db.guild_standing import ActorContext, by_a_person
from app.models.tenant.calendar import Calendar
from app.models.tenant.calendar_event import CalendarEvent, CalendarEventAttendee
from app.models.tenant.file import File
from app.models.tenant.metadata import (
    VALUE_COLUMNS,
    MetadataDefinition,
    MetadataType,
    MetadataValue,
)
from app.models.tenant.post import Post
from app.models.tenant.task import Task, TaskAssignee
from app.models.tenant.tool_layout import ToolLayout
from app.schemas.tenant.tool_layout import PROPERTY_FIELD_PREFIX
from app.services.tenant import metadata as metadata_service
from app.services.tenant import tags as tags_service
from app.services.tenant.tool_layouts import required_keys


@dataclass(frozen=True)
class Required:
    """What one item's layout requires of it, and what of that it held when
    it was read."""

    row: Any
    #: The collection whose file page it is, for a file.
    collection_id: Optional[int]
    #: Each by its key: a built-in field's id, a part's type, or
    #: ``property:<id>``; in the order the layout places them.
    keys: tuple[str, ...]
    #: Each property's name, by its key.
    names: dict[str, str]
    filled: frozenset[str]


def _layout_of(row: Any, collection_id: Optional[int]) -> Optional[Any]:
    """The query for the stored page layout that governs ``row``: its type's
    task page, its initiative's event or posts page, or the collection's file
    page. None for an item no layout requires anything of."""
    definition = select(ToolLayout.definition, ToolLayout.initiative_id)
    if isinstance(row, Task):
        return definition.where(
            ToolLayout.tool == Tool.project.value,
            ToolLayout.tool_id == row.project_id,
            ToolLayout.kind == "task",
            ToolLayout.task_type_id == row.task_type_id,
        )
    if isinstance(row, CalendarEvent):
        return definition.join(
            Calendar, col(Calendar.initiative_id) == col(ToolLayout.initiative_id)
        ).where(
            Calendar.id == row.calendar_id,
            ToolLayout.tool == Tool.calendar.value,
            col(ToolLayout.tool_id).is_(None),
            ToolLayout.kind == "calendar_event",
        )
    if isinstance(row, Post):
        return definition.where(
            ToolLayout.initiative_id == row.initiative_id,
            ToolLayout.tool == Tool.post.value,
            col(ToolLayout.tool_id).is_(None),
            ToolLayout.kind == "post",
        )
    if isinstance(row, File) and collection_id is not None:
        return definition.where(
            ToolLayout.tool == "collection",
            ToolLayout.tool_id == collection_id,
            ToolLayout.kind == "file",
        )
    return None


def _text(value: Optional[str]) -> bool:
    return bool((value or "").strip())


async def _tagged(session: AsyncSession, row: Any) -> bool:
    return bool(
        await tags_service.active_tag_ids(session, tags_service.spec_for(row), row.id)
    )


async def _any(session: AsyncSession, column: Any, row_id: int) -> bool:
    return bool((await session.exec(select(exists().where(column == row_id)))).one())


#: How each built-in field a layout can require reads as filled, by the model
#: of the item holding it (``tool_layouts.REQUIREABLE``).
_BUILT_IN: dict[type, dict[str, Callable[[AsyncSession, Any], Any]]] = {
    Task: {
        "description": lambda _, row: _text(row.description),
        "checklist": lambda _, row: bool(row.checklist),
        "recurrence": lambda _, row: row.recurrence is not None,
        "dates": lambda _, row: row.start_date is not None or row.due_date is not None,
        "assignees": lambda session, row: _any(
            session, col(TaskAssignee.task_id), row.id
        ),
        "tags": _tagged,
    },
    CalendarEvent: {
        "description": lambda _, row: _text(row.description),
        "location": lambda _, row: _text(row.location),
        "recurrence": lambda _, row: row.recurrence is not None,
        "attendees": lambda session, row: _any(
            session, col(CalendarEventAttendee.calendar_event_id), row.id
        ),
        "tags": _tagged,
    },
    Post: {"tags": _tagged},
}


def _property_id(key: str) -> Optional[int]:
    if not key.startswith(PROPERTY_FIELD_PREFIX):
        return None
    return int(key.removeprefix(PROPERTY_FIELD_PREFIX))


async def _filled(
    session: AsyncSession, row: Any, keys: tuple[str, ...]
) -> frozenset[str]:
    """Which of ``keys`` the item holds a value for, as the session has it."""
    await session.flush()
    held: set[str] = set()
    ids = [found for key in keys if (found := _property_id(key)) is not None]
    if ids:
        json_value = col(MetadataValue.value_json)
        valued = (
            await session.exec(
                select(MetadataValue.property_id).where(
                    MetadataValue.entity_type == metadata_service.link_for(row).target,
                    MetadataValue.entity_id == row.id,
                    col(MetadataValue.property_id).in_(ids),
                    or_(
                        *(
                            getattr(MetadataValue, column).is_not(None)
                            for column in VALUE_COLUMNS
                            if column != "value_json"
                        ),
                        json_value.is_not(None)
                        & (
                            (func.jsonb_typeof(json_value) != "array")
                            | (func.jsonb_array_length(json_value) > 0)
                        ),
                    ),
                )
            )
        ).all()
        held.update(f"{PROPERTY_FIELD_PREFIX}{property_id}" for property_id in valued)
    readers = _BUILT_IN.get(type(row), {})
    for key in keys:
        reader = readers.get(key)
        if reader is None:
            continue
        answer = reader(session, row)
        if await answer if inspect.isawaitable(answer) else answer:
            held.add(key)
    return frozenset(held)


async def required_of(
    session: AsyncSession,
    context: ActorContext,
    row: Any,
    *,
    collection_id: Optional[int] = None,
) -> Optional[Required]:
    """What ``row``'s page layout requires of this request, and what of it the
    row holds now. None when the request is not a person's, or the layout
    requires nothing. A required property that has since been deleted, or
    that the row cannot carry, requires nothing."""
    if not by_a_person(context):
        return None
    query = _layout_of(row, collection_id)
    if query is None:
        return None
    found_layout = (await session.exec(query)).first()
    definition, initiative_id = found_layout or ({}, None)
    keys = required_keys(definition or {})
    if not keys:
        return None
    ids = [found for key in keys if (found := _property_id(key)) is not None]
    names: dict[str, str] = {}
    if ids:
        found = await session.exec(
            select(MetadataDefinition.id, MetadataDefinition.name).where(
                col(MetadataDefinition.id).in_(ids),
                MetadataDefinition.initiative_id == initiative_id,
                col(MetadataDefinition.collection_id).is_not_distinct_from(
                    collection_id
                ),
                MetadataDefinition.type != MetadataType.checkbox,
            )
        )
        names = {
            f"{PROPERTY_FIELD_PREFIX}{definition_id}": name
            for definition_id, name in found.all()
        }
    readers = _BUILT_IN.get(type(row), {})
    held = tuple(key for key in keys if key in names or key in readers)
    if not held:
        return None
    return Required(
        row=row,
        collection_id=collection_id,
        keys=held,
        names=names,
        filled=await _filled(session, row, held),
    )


def _refuse(required: Required, missing: frozenset[str]) -> None:
    keys = [key for key in required.keys if key in missing]
    if keys:
        raise CodedError(
            ToolLayoutMessages.REQUIRED_FIELDS_MISSING,
            params={
                "fields": "\n".join(required.names.get(key, key) for key in keys),
                "keys": "\n".join(keys),
            },
        )


async def refuse_missing(
    session: AsyncSession,
    context: ActorContext,
    *rows: Any,
    collection_id: Optional[int] = None,
) -> None:
    """Refuse a person adding ``rows`` (items of one page: a new task, or the
    files put in a collection) without each field their page requires. Called
    once they hold everything the request gave them, before it commits."""
    if not rows:
        return
    required = await required_of(session, context, rows[0], collection_id=collection_id)
    if required is None:
        return
    _refuse(required, frozenset(required.keys) - required.filled)
    for row in rows[1:]:
        _refuse(
            required,
            frozenset(required.keys) - await _filled(session, row, required.keys),
        )


async def refuse_emptied(session: AsyncSession, before: Optional[Required]) -> None:
    """Refuse a person's write that empties a field the item's page requires
    and the item held before it (``before``, read by :func:`required_of`).
    A field it lacked already may stay empty."""
    if before is None:
        return
    now = await _filled(session, before.row, before.keys)
    _refuse(before, before.filled - now)
