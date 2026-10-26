"""Duplicating a tool: one set of steps for every tool.

A copy is a create whose values come from another row. Every tool's copy takes
the same steps in the same order here: who may copy, where the copy may go,
what it is called, which columns come along, who it is shared with, and the
tags, properties and files it carries. What differs from tool to tool is what
lives inside it, and that is all ``TOOL_COPIERS`` holds.

``tool_lifecycle.py`` mounts ``POST /{tool}/{id}/duplicate`` for every tool
here, and a project made from a template is a copy as well
(``create_project``).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import resource_access
from app.core.messages import FileMessages
from app.core.tools import Tool
from app.db.guild_standing import ActorContext, InstallContext
from app.db.session import require_actor_context
from app.models.platform.user import User
from app.models.tenant._mixins import (
    ArchiveMixin,
    CreatedByMixin,
    ListingProvenanceMixin,
    SoftDeleteMixin,
)
from app.models.tenant.calendar import Calendar
from app.models.tenant.calendar_event import CalendarEvent, CalendarEventAttendee
from app.models.tenant.counter import Counter
from app.models.tenant.catalog import Catalog, CatalogItem
from app.models.tenant.post import Post
from app.models.tenant.post_poll import PostPoll, PostPollOption
from app.models.tenant.project import Project
from app.models.tenant.queue import QueueItem
from app.models.tenant.task import Task
from app.models.tenant.wiki import Wiki, WikiPage
from app.schemas.base import RESERVED_SIGIL_CODE, RESERVED_SIGILS
from app.schemas.tenant.resource_grant import ResourceGrantSchema
from app.services import notifications as notifications_service
from app.services.tenant import attachments as attachments_service
from app.services.tenant import calendar_occurrences as occurrences_service
from app.services.tenant import files as files_service
from app.services.tenant import file_versions
from app.services.tenant import named_people, project_grants
from app.services.tenant import properties as properties_service
from app.services.tenant import content_references, relationships
from app.services.tenant.relationships import Endpoint
from app.services.tenant import tags as tags_service
from app.services.tenant import task_creation
from app.services.tenant import task_types as task_types_service
from app.services.tenant import task_statuses as task_statuses_service
from app.services.tenant import tool_layouts as tool_layouts_service
from app.services.tenant import wikis as wikis_service
from app.services.tenant.names import copy_name, ensure_name_free

#: async (session, source, copy, actor) -> the rows made inside ``copy``
Contents = Callable[[AsyncSession, Any, Any, ActorContext], Awaitable[Sequence[Any]]]


@dataclass(frozen=True)
class ToolCopier:
    """What a copy of one tool does beyond the shared steps."""

    #: The tables inside the tool that ``contents`` fills. Every other table
    #: filed under it (``lifecycle_tree.CASCADE_CHILDREN``) stays with the
    #: source; ``tool_copy_test`` holds the two to each other.
    copies: frozenset[type] = frozenset()
    contents: Optional[Contents] = None
    #: Columns a copy starts afresh rather than carries.
    reset: Mapping[str, Any] = field(default_factory=dict)
    #: The refusal when the target initiative already has one of this name;
    #: ``None`` where names may repeat.
    name_taken: Optional[str] = None
    #: Whether a name may carry the reserved sigils, as a file's may: it
    #: starts life as a filename.
    name_takes_sigils: bool = False
    #: async (session, copy_id, user): tell people about the copy, once it is
    #: committed.
    announce: Optional[Callable[[AsyncSession, int, User], Awaitable[None]]] = None


#: What a row says about its own lifecycle and origin rather than its content.
_NOT_CARRIED = frozenset(
    {
        *SoftDeleteMixin.model_fields,
        *ArchiveMixin.model_fields,
        *CreatedByMixin.model_fields,
        *ListingProvenanceMixin.model_fields,
        "created_at",
        "updated_at",
    }
)


def _carried(model: Any, skip: Collection[str] = ()) -> list[str]:
    """The columns a copy takes from its source: everything the row says about
    itself, but not its identity, its lifecycle, the rows it points at, which
    are the copy's own, or ``skip``."""
    return [
        column.name
        for column in model.__table__.columns
        if not column.primary_key
        and not column.foreign_keys
        and column.name not in _NOT_CARRIED
        and column.name not in skip
    ]


def _clone(source: Any, reset: Mapping[str, Any] | None = None, **values: Any) -> Any:
    """A new row of ``source``'s model carrying its columns (:func:`_carried`),
    with ``reset`` and ``values`` set on top. ``source`` is loaded."""
    reset = reset or {}
    model = type(source)
    carried = {c: deepcopy(getattr(source, c)) for c in _carried(model, reset)}
    return model(**{**carried, **reset, **values})


async def _record_references(session: AsyncSession, rows: Sequence[Any]) -> None:
    """Record what the copies' own text points at, for a model whose body
    makes links (``content_references.BODY_COLUMNS``)."""
    found = next(
        (
            (kind, column)
            for kind, (model, column) in content_references.BODY_COLUMNS.items()
            if rows and type(rows[0]) is model
        ),
        None,
    )
    if found is None:
        return
    kind, column = found
    author_id = require_actor_context(session).user_id
    for row in rows:
        if getattr(row, column):
            await content_references.sync_for_entity(
                session,
                Endpoint(kind, row.id),
                body=getattr(row, column),
                author_id=author_id,
            )


async def _copy_extras(
    session: AsyncSession, pairs: Sequence[tuple[Any, Any]], *, beside: bool
) -> None:
    """The tags, links and text references of rows copied inside a tool, one
    model at a time, and their property values when the copy stays in its
    initiative."""
    if not pairs:
        return
    model = type(pairs[0][0])
    copies = {source.id: copy.id for source, copy in pairs}
    spec = next((s for s in tags_service.TAG_LINKS.values() if s.entity is model), None)
    if spec is not None:
        await tags_service.copy_entity_tags(session, spec, copies)
        await relationships.copy_links(session, spec.kind, copies)
    await _record_references(session, [copy for _, copy in pairs])
    if beside and model in properties_service.PROPERTY_LINKS_BY_MODEL:
        await properties_service.copy_values(session, model, copies)


async def _copy_children(
    session: AsyncSession,
    sources: Sequence[Any],
    *,
    beside: bool,
    values: Callable[[Any], Mapping[str, Any]],
    reset: Mapping[str, Any] | None = None,
) -> list[tuple[Any, Any]]:
    """Clone ``sources``, rows inside a tool, with ``values(source)`` set on
    each, then copy their tags and properties; returns the pairs."""
    if sources and type(sources[0]) in resource_access.SUB_TOOLS:
        resets = resource_access.SUB_TOOLS[type(sources[0])].copy_resets
        reset = {**resets, **(reset or {})}
    pairs = [(source, _clone(source, reset, **values(source))) for source in sources]
    session.add_all(clone for _, clone in pairs)
    await session.flush()
    await _copy_extras(session, pairs, beside=beside)
    return pairs


async def load_source(
    session: AsyncSession,
    tool: Tool,
    source_id: int,
    user: Optional[User],
    actor: ActorContext,
) -> Any:
    """The row to copy, once the caller may copy it. Read is enough for a
    template, which is made to be copied; anything else asks for write, so a
    copy is never a quiet fork of somebody else's work."""
    source = await resource_access.load_authorized(
        session, tool, source_id, user, actor
    )
    if not getattr(source, "is_template", False):
        resource_access.authorize(tool, source, user, access="write", context=actor)
    return source


async def duplicate(
    session: AsyncSession,
    tool: Tool,
    source: Any,
    *,
    initiative_id: Optional[int],
    name: Optional[str],
    user: Optional[User],
    actor: ActorContext,
    payload: Any,
    values: Mapping[str, Any] | None = None,
    grants: Optional[list[ResourceGrantSchema]] = None,
) -> Any:
    """Copy ``source`` into ``initiative_id`` (its own when ``None``), held to
    what a create there is held to. Beside its source the copy is called
    "<name> (Copy)" unless ``name`` is given; elsewhere it keeps the name,
    unless the source's initiative keeps its content in, which refuses it.

    ``values`` overrides carried columns (a project made from a template takes
    its own dates), and ``grants`` replaces the source's sharing. Raises
    ``StorageQuotaExceededError`` when its files do not fit. The caller
    commits.
    """
    copier = TOOL_COPIERS[tool]
    model = type(source)
    initiative_id = initiative_id or source.initiative_id
    beside = initiative_id == source.initiative_id
    await resource_access.require_stays_in(session, source.initiative_id, initiative_id)
    await resource_access.prepare_create(session, tool, initiative_id, user, actor)
    name = (name or "").strip() or (
        copy_name(source.name, _length(model, "name")) if beside else source.name
    )
    if not copier.name_takes_sigils and RESERVED_SIGILS.intersection(name):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=RESERVED_SIGIL_CODE,
        )
    if copier.name_taken is not None:
        await ensure_name_free(
            session,
            model.name,
            name,
            model.initiative_id == initiative_id,
            detail=copier.name_taken,
        )

    columns = _carried(model, copier.reset)
    # Deferred columns (a file's body) are read too.
    await session.refresh(source, columns)
    copy = model(
        **{
            **{column: deepcopy(getattr(source, column)) for column in columns},
            **copier.reset,
            **(values or {}),
            "name": name,
            "initiative_id": initiative_id,
        }
    )
    session.add(copy)
    await session.flush()
    await resource_access.grant_initial_sharing(
        session,
        actor,
        tool,
        user=user,
        resource_id=copy.id,
        initiative_id=initiative_id,
        payload=payload,
        grants=(
            resource_access.duplicate_sharing(source, initiative_id=initiative_id)
            if grants is None
            else grants
        ),
    )
    # Everything inside is reached through the copy, so its sharing lands first.
    await session.flush()

    rows = (
        list(await copier.contents(session, source, copy, actor))
        if copier.contents
        else []
    )
    spec = tags_service.TOOL_TAG_LINKS[tool]
    await tags_service.copy_entity_tags(session, spec, {source.id: copy.id})
    await relationships.copy_links(session, spec.kind, {source.id: copy.id})
    await _record_references(session, [copy])
    # Definitions belong to an initiative, so values only go where they apply.
    if beside and model in properties_service.PROPERTY_LINKS_BY_MODEL:
        await properties_service.copy_values(session, model, {source.id: copy.id})
    # Files kept for another initiative are copied for the copy's.
    await attachments_service.claim_uploads(session, copy, *rows)
    return copy


async def _project_contents(
    session: AsyncSession, source: Project, copy: Project, actor: ActorContext
) -> list[Task]:
    status_mapping = await task_statuses_service.clone_statuses(
        session, source_project_id=source.id, target_project_id=copy.id
    )
    type_mapping = await task_types_service.clone_types(
        session, source_project_id=source.id, target_project_id=copy.id
    )
    # A copy has what its source has; these only repair a source found with
    # none, where no one's language is in question.
    locale = task_statuses_service.REPAIR_LOCALE
    statuses = await task_statuses_service.ensure_default_statuses(
        session, copy.id, locale=locale
    )
    types = await task_types_service.ensure_default_types(
        session, copy.id, locale=locale
    )
    # A plug-in's copy has the shipped layouts: they are the initiative's own
    # drawing of its tools, which plug-ins do not read.
    if not isinstance(actor, InstallContext):
        await tool_layouts_service.copy_layouts(
            session,
            tool_layouts_service.Target(Tool.project, source.id, source.initiative_id),
            tool_layouts_service.Target(Tool.project, copy.id, copy.initiative_id),
            status_mapping=status_mapping,
            type_mapping=type_mapping,
        )
    return await task_creation.copy_project_tasks(
        session,
        source,
        copy,
        status_mapping=status_mapping,
        fallback_status_ids={status.category: status.id for status in statuses},
        type_mapping=type_mapping,
        fallback_type_id=next(t.id for t in types if t.is_default),
    )


async def _announce_project(session: AsyncSession, project_id: int, user: User) -> None:
    project = await project_grants.get_project_hydrated(session, project_id)
    await notifications_service.notify_project_added(session, project, user)


def _beside(source: Any, copy: Any) -> bool:
    return source.initiative_id == copy.initiative_id


def _rows_inside(model: type, *carried: str) -> Contents:
    """The contents of a tool that is a list of ``model`` rows: each copied
    into the copy, keeping ``carried`` of the references a copy otherwise
    drops."""
    parent = resource_access.parent_column(model)

    async def contents(
        session: AsyncSession, source: Any, copy: Any, actor: ActorContext
    ) -> list[Any]:
        rows = (
            await session.exec(select(model).where(getattr(model, parent) == source.id))
        ).all()
        pairs = await _copy_children(
            session,
            rows,
            beside=_beside(source, copy),
            values=lambda row: {
                parent: copy.id,
                **{column: getattr(row, column) for column in carried},
            },
        )
        return [clone for _, clone in pairs]

    return contents


async def _catalog_contents(
    session: AsyncSession, source: Catalog, copy: Catalog, actor: ActorContext
) -> list[Any]:
    images = (
        await session.exec(
            select(CatalogItem).where(CatalogItem.catalog_id == source.id)
        )
    ).all()
    # Each picture starts again at version 1, authored by whoever copied it; a
    # plug-in is never an author, so its copy keeps the picture's uploader.
    pairs = await _copy_children(
        session,
        images,
        beside=_beside(source, copy),
        values=lambda image: {
            "catalog_id": copy.id,
            "created_by": actor.user_id or image.created_by,
        },
    )
    versions = [
        file_versions.copy_version(
            session, image.current_version, clone, created_by=clone.created_by
        )
        for image, clone in pairs
        if image.current_version is not None
    ]
    copy.cover_item_id = {s.id: c.id for s, c in pairs}.get(source.cover_item_id)
    # The versions name the files, so they are what is claimed for the copy.
    return [*(clone for _, clone in pairs), *versions]


async def _post_contents(
    session: AsyncSession, source: Post, copy: Post, actor: ActorContext
) -> list[Any]:
    """The post's poll, with its options and none of the votes. Its deadline
    is copied as written; publishing the draft opens a poll whose deadline
    has passed by then."""
    for poll in (
        await session.exec(select(PostPoll).where(PostPoll.post_id == source.id))
    ).all():
        ((_, clone),) = await _copy_children(
            session, [poll], beside=False, values=lambda _: {"post_id": copy.id}
        )
        options = (
            await session.exec(
                select(PostPollOption).where(PostPollOption.poll_id == poll.id)
            )
        ).all()
        await _copy_children(
            session, options, beside=False, values=lambda _: {"poll_id": clone.id}
        )
    return []


async def _copy_events(
    session: AsyncSession,
    events: Sequence[CalendarEvent],
    *,
    beside: bool,
    values: Callable[[Any], Mapping[str, Any]],
    people: Optional[Collection[int]] = None,
) -> list[tuple[Any, Any]]:
    """Copy ``events``, each series among them with the occurrences changed on
    their own, and their invitees (those in ``people`` when it is given),
    whose answers start over."""
    pairs = await _copy_children(session, events, beside=beside, values=values)
    series = {source.id: clone for source, clone in pairs if clone.recurrence}
    changed = (
        await session.exec(
            select(CalendarEvent).where(CalendarEvent.series_id.in_(series))
        )
    ).all()
    pairs += await _copy_children(
        session,
        changed,
        beside=beside,
        values=lambda event: {
            "calendar_id": series[event.series_id].calendar_id,
            "series_id": series[event.series_id].id,
        },
    )
    clones = {source.id: clone.id for source, clone in pairs}
    attendees = (
        await session.exec(
            select(CalendarEventAttendee).where(
                CalendarEventAttendee.calendar_event_id.in_(clones)
            )
        )
    ).all()
    session.add_all(
        CalendarEventAttendee(
            calendar_event_id=clones[attendee.calendar_event_id],
            user_id=attendee.user_id,
        )
        for attendee in attendees
        if people is None or attendee.user_id in people
    )
    return pairs


async def _calendar_contents(
    session: AsyncSession, source: Calendar, copy: Calendar, actor: ActorContext
) -> list[CalendarEvent]:
    events = (
        await session.exec(
            select(CalendarEvent).where(
                CalendarEvent.calendar_id == source.id,
                CalendarEvent.series_id.is_(None),
            )
        )
    ).all()
    pairs = await _copy_events(
        session,
        events,
        beside=_beside(source, copy),
        values=lambda _: {"calendar_id": copy.id},
    )
    return [clone for _, clone in pairs]


async def _wiki_contents(
    session: AsyncSession, source: Wiki, copy: Wiki, actor: ActorContext
) -> list[WikiPage]:
    """Its published pages, each under its nearest published ancestor, with
    the borrowed files filed the same way, and the home and template pages
    pointed at their copies. Drafts stay behind."""
    pages = (
        await session.exec(select(WikiPage).where(WikiPage.wiki_id == source.id))
    ).all()
    parent_of = {page.id: page.parent_page_id for page in pages}
    published = [page for page in pages if not page.is_draft]
    pairs = await _copy_children(
        session,
        published,
        beside=_beside(source, copy),
        values=lambda _: {"wiki_id": copy.id},
    )
    clones = {page.id: clone.id for page, clone in pairs}

    def placed_under(page_id: int | None) -> int | None:
        while page_id is not None and page_id not in clones:
            page_id = parent_of.get(page_id)
        return clones.get(page_id) if page_id is not None else None

    for page, clone in pairs:
        clone.parent_page_id = placed_under(page.parent_page_id)
    copy.file_positions = {}
    for file_id in source.file_positions or {}:
        wikis_service.place_file(
            copy,
            int(file_id),
            parent_page_id=placed_under(
                wikis_service.file_parent(source, int(file_id))
            ),
            position=wikis_service.file_position(source, int(file_id)),
        )
    copy.home_page_id = clones.get(source.home_page_id)
    copy.template_page_id = clones.get(source.template_page_id)
    return [clone for _, clone in pairs]


def _length(model: Any, column: str) -> int | None:
    return getattr(model.__table__.c[column].type, "length", None)


def copied_name(source: Any) -> str:
    """What a copy of ``source``, a row inside a tool, is called beside it."""
    column = resource_access.SUB_TOOLS[type(source)].name
    return copy_name(getattr(source, column), _length(type(source), column))


async def duplicate_child(session: AsyncSession, source: Any, **values: Any) -> Any:
    """Copy ``source``, a row inside a tool, beside itself as "<name> (Copy)",
    with its tags, links, text references, property values and files.
    ``values`` sets what its sub-tool decides: where the copy sits, and whom
    it names. The caller commits."""
    parent = resource_access.parent_column(type(source))
    ((_, copy),) = await _copy_children(
        session,
        [source],
        beside=True,
        values=lambda _: {
            parent: getattr(source, parent),
            resource_access.SUB_TOOLS[type(source)].name: copied_name(source),
            **values,
        },
    )
    await attachments_service.claim_uploads(session, copy)
    return copy


async def duplicate_event(
    session: AsyncSession,
    event: CalendarEvent,
    calendar: Calendar,
    at: Optional[datetime] = None,
) -> CalendarEvent:
    """Copy ``event``, in ``calendar``, beside itself as "<title> (Copy)",
    with its invitees who can open the calendar. A series takes the
    occurrences changed on their own, which keep following its title where
    they did; one changed occurrence, or the series' occurrence at ``at``,
    becomes an event of its own. The caller commits."""
    alone: dict[str, Any] = (
        {"original_start": None, "overridden_fields": []}
        if event.series_id is not None
        else {}
    )
    if at is not None:
        at = occurrences_service.require_occurrence(event, at)
        changed = (
            await session.exec(
                select(CalendarEvent).where(
                    CalendarEvent.series_id == event.id,
                    CalendarEvent.original_start == at,
                )
            )
        ).one_or_none()
        if changed is not None:
            return await duplicate_event(session, changed, calendar)
        alone = {
            "start_at": at,
            "end_at": at + (event.end_at - event.start_at),
            "recurrence": None,
            "recurrence_shift": 0,
            "recurrence_until": None,
        }
    invited = (
        await session.exec(
            select(CalendarEventAttendee.user_id)
            .join(CalendarEvent)
            .where(
                or_(CalendarEvent.id == event.id, CalendarEvent.series_id == event.id)
            )
        )
    ).all()
    people = await named_people.readers(
        session, named_people.Governing.of(Tool.calendar, calendar), invited
    )
    ((_, copy), *_rest) = await _copy_events(
        session,
        [event],
        beside=True,
        values=lambda _: {
            "calendar_id": event.calendar_id,
            "title": copied_name(event),
            **alone,
        },
        people=people,
    )
    if copy.recurrence:
        await occurrences_service.follow(session, copy, {"title"})
    await attachments_service.claim_uploads(session, copy)
    return copy


TOOL_COPIERS: dict[Tool, ToolCopier] = {
    Tool.project: ToolCopier(
        copies=frozenset({Task}),
        contents=_project_contents,
        reset={"is_template": False, "pinned_at": None},
        announce=_announce_project,
    ),
    Tool.file: ToolCopier(
        contents=files_service.copy_contents,
        reset={"is_template": False, "yjs_state": None, "yjs_updated_at": None},
        name_taken=FileMessages.NAME_ALREADY_EXISTS,
        name_takes_sigils=True,
    ),
    Tool.counter_group: ToolCopier(
        copies=frozenset({Counter}), contents=_rows_inside(Counter)
    ),
    Tool.queue: ToolCopier(
        copies=frozenset({QueueItem}),
        contents=_rows_inside(QueueItem, "user_id"),
        # A copy starts its rotation from the top.
        reset={"is_active": False, "current_round": 1},
    ),
    Tool.catalog: ToolCopier(
        copies=frozenset({CatalogItem}), contents=_catalog_contents
    ),
    Tool.dashboard: ToolCopier(),
    Tool.calendar: ToolCopier(
        copies=frozenset({CalendarEvent}), contents=_calendar_contents
    ),
    Tool.wiki: ToolCopier(copies=frozenset({WikiPage}), contents=_wiki_contents),
    # A copy of a notice is a draft: not published, scheduled or pinned.
    Tool.post: ToolCopier(
        contents=_post_contents,
        reset={
            "published_at": None,
            "scheduled_for": None,
            "pinned_at": None,
            "pinned_by": None,
            "pin_expires_at": None,
        },
    ),
}
