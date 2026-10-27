"""Tool lists and their sidebar counts — a list per tool, and one count for all.

``GET /`` was nine copies of the same hundred lines: scope the guild, honour
the tool's switch, apply sharing, narrow by the search box and the tag filter,
count, order, page, annotate, serialize. None of that depends on which tool it
is beyond the model, what to eager-load and how a row becomes a summary — so
the list is mounted per ``Tool`` out of :data:`TOOL_LISTS` rather than written
nine times over, and ``GET /tools/counts/by-initiative`` answers every tool's
sidebar badge from the same registry in one statement. The query itself is
:mod:`app.services.tenant.tool_listing`; the per-tool differences that survive
are the registry's fields, and each is commented where it sits.

**The list and the count use different scope clauses, deliberately.** A list
runs ``permissions.listing_scope_clause``: asked for one initiative by name it
adds nothing, because the content table's own policy has already settled who
may read the row, and a guild admin's authority reaches every initiative in
their community. A count runs ``permissions.granted_scope_clause``: a count is
guild-wide, so there is no single initiative to ask about, and what it answers
is what has been *granted* to the reader — the same rule their sidebar and the
community front page list initiatives by. A badge that counted an admin's whole
guild would not be a badge about them.

Each list keeps the path, method, tag, name, summary and parameters its tool
already had.

:data:`TOOL_LISTS` also carries each tool's **single-row** answer — its Read
model and its own re-read-and-serialize — because that is the same per-tool
fact in a different shape, and a second table of it would be one more thing to
keep in step. :mod:`app.api.v1.tenant_endpoints.tool_grants` reads it.
"""

# NOT ``from __future__ import annotations``: the list handlers are built per
# tool from a signature assembled at import time, and the parameter annotations
# have to be real objects for FastAPI to read them.

import inspect
from functools import lru_cache
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Awaitable, Callable, List, Literal, Mapping, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, ValidationError, create_model
from sqlalchemy import and_, func, literal, select, union_all
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    RLSSessionDep,
    plugin_scope,
    get_current_active_user,
    GuildContextDep,
)
from app.core.plugin_scopes import PluginScopeAccess, scope_name, tool_resource
from app.api import resource_access
from app.api.v1.tenant_endpoints import calendars as calendars_endpoints
from app.api.v1.tenant_endpoints import counters as counters_endpoints
from app.api.v1.tenant_endpoints import dashboards as dashboards_endpoints
from app.api.v1.tenant_endpoints import files as files_endpoints
from app.api.v1.tenant_endpoints import posts as posts_endpoints
from app.api.v1.tenant_endpoints import projects as projects_endpoints
from app.api.v1.tenant_endpoints import queues as queues_endpoints
from app.api.v1.tenant_endpoints import wikis as wikis_endpoints
from app.core.messages import QueryMessages
from app.core.tools import Tool
from app.db.query import build_paginated_response
from app.models.platform.user import User
from app.models.tenant.calendar import Calendar
from app.models.tenant.collection import Collection, CollectionFile
from app.models.tenant.counter import CounterGroup
from app.models.tenant.dashboard import Dashboard
from app.core.file_types import FileKind, FileType
from app.models.tenant.file import File
from app.models.tenant.post import Post
from app.models.tenant.project import Project
from app.models.tenant.personal_item import PersonalItem
from app.models.tenant.queue import Queue
from app.models.tenant.wiki import Wiki
from app.schemas.tenant.collection import (
    CollectionFileListResponse,
    CollectionFileSummary,
)
from app.schemas.tenant.calendar import (
    CalendarListResponse,
    CalendarRead,
    CalendarSummary,
)
from app.schemas.tenant.counter import (
    CounterGroupListResponse,
    CounterGroupRead,
    CounterGroupSummary,
)
from app.schemas.tenant.dashboard import (
    DashboardListResponse,
    DashboardRead,
    DashboardPreview,
    DashboardSummary,
)
from app.schemas.tenant.file import (
    FileListResponse,
    FileRead,
)
from app.schemas.tenant.initiative import (
    ToolCountsByInitiativeResponse,
    ToolCountsResponse,
)
from app.schemas.tenant.post import PostListResponse, PostRead
from app.schemas.tenant.timeline import TimelineResponse
from app.schemas.tenant.project import ProjectListResponse, ProjectRead
from app.schemas.tenant.queue import (
    QueueListResponse,
    QueueRead,
    QueueSummary,
)
from app.schemas.tenant.wiki import (
    WikiListResponse,
    WikiRead,
    WikiSummary,
)
from app.schemas.tenant.tool import ToolSummaryBase, serialize_tool
from app.services.permissions import Action
from app.services.tenant import archive as archive_service
from app.services.tenant import comments as comments_service
from app.services.tenant import calendars as calendars_service
from app.services.tenant import collections as collections_service
from app.services.tenant import counters as counters_service
from app.services.tenant import dashboards as dashboards_service
from app.services.tenant import files as files_service
from app.services.tenant import posts as posts_service
from app.services.tenant import properties as properties_service
from app.services.tenant import queues as queues_service
from app.services.tenant import tags as tags_service
from app.services.tenant import timeline as timeline_service
from app.services.tenant import tool_listing
from app.services.tenant import wikis as wikis_service

router = APIRouter(route_class=ActorRoute)

CurrentUserDep = Annotated[User, Depends(get_current_active_user)]


# ---------------------------------------------------------------------------
# What a handler is handed
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ListRequest:
    """One list request: who is asking, where, and with which parameters.

    ``values`` holds every query parameter the tool declared, by name, so a
    per-tool hook reads the ones it asked for without the generic handler
    knowing they exist.
    """

    session: AsyncSession
    #: The person asking; ``None`` when an installed plug-in is.
    user: Optional[User]
    guild_context: ActorContext
    values: dict[str, Any]

    @property
    def guild_id(self) -> int:
        return self.guild_context.guild_id

    @property
    def user_id(self) -> Optional[int]:
        """The person asking, by id; ``None`` for an installed plug-in."""
        return self.guild_context.user_id


# ---------------------------------------------------------------------------
# Query parameters
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ListParam:
    """One query parameter of a tool's list, in the order it is published."""

    name: str
    annotation: Any
    default: Any


_SORT_DIR_DESCRIPTION = "asc (default) or desc."
_ROW_SEARCH_DESCRIPTION = (
    "Full-text match over the row — its name and its description. "
    "Reads the same index the search page does, so a list's filter "
    "box and a search agree about what matches."
)
_TOOL_SORT_DESCRIPTION = (
    "Order by one of: name, initiative, updated_at. Omit for this "
    "tool's own default order."
)


def _initiative_id(description: Optional[str] = None) -> ListParam:
    return ListParam(
        "initiative_id", Optional[int], Query(default=None, description=description)
    )


def search_param(description: Optional[str] = _ROW_SEARCH_DESCRIPTION) -> ListParam:
    return ListParam(
        "search", Optional[str], Query(default=None, description=description)
    )


def sort_by_param(description: Optional[str] = _TOOL_SORT_DESCRIPTION) -> ListParam:
    return ListParam(
        "sort_by", Optional[str], Query(default=None, description=description)
    )


def sort_dir_param(description: Optional[str] = _SORT_DIR_DESCRIPTION) -> ListParam:
    return ListParam(
        "sort_dir", Optional[str], Query(default=None, description=description)
    )


def _tag_ids(tool: Tool, description: Optional[str] = None) -> ListParam:
    """Every tool is taggable, so every list narrows by tag — ANY-of, the way a
    shelf is narrowed by what somebody remembers about a row rather than by
    everything that is true of it."""
    if description is None:
        plural = tool.plural.replace("_", " ")
        description = f"Only {plural} carrying any of these tags."
    return ListParam(
        "tag_ids", Optional[List[int]], Query(default=None, description=description)
    )


def _property_filters() -> ListParam:
    """Every tool carries properties, so every list narrows by them — ALL-of,
    each a typed comparison against one property's value."""
    return ListParam(
        "property_filters",
        Optional[str],
        Query(
            default=None,
            description=(
                "JSON-encoded list of property-value filters, e.g. "
                '`[{"property_id": 12, "op": "eq", "value": "live"}]`. '
                f"Maximum {properties_service.MAX_PROPERTY_FILTERS} "
                "conditions per request."
            ),
        ),
    )


def _archived(described: bool = True) -> ListParam:
    return ListParam(
        "archived",
        Optional[bool],
        Query(
            default=None,
            description=archive_service.ARCHIVED_QUERY_DESCRIPTION
            if described
            else None,
        ),
    )


def _is_template(tool: Tool) -> ListParam:
    """The template filter of a tool that has templates."""
    plural = tool.plural.replace("_", " ")
    return ListParam(
        "is_template",
        Optional[bool],
        Query(
            default=None,
            description=(
                f"Only templates (true) or only {plural} that are not templates "
                "(false). Omit for both."
            ),
        ),
    )


def page_param() -> ListParam:
    return ListParam("page", int, Query(default=1, ge=1))


def page_size_param(
    default: int, *, ge: int, le: int, description: Optional[str] = None
) -> ListParam:
    """A tool's page defaults, declared where they can be compared.

    They differ on purpose — a board of posts carries whole bodies and pages in
    fives, a dashboard list is a sidebar and fetches a hundred — and the
    clients depend on them, so they are stated per tool rather than averaged.
    """
    return ListParam(
        "page_size", int, Query(default=default, ge=ge, le=le, description=description)
    )


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


#: List params that say where, in what order and in what shape a page is
#: served, or which rows the reader may change: the caller's, not filters.
_NOT_FILTERS = frozenset(
    {
        "initiative_id",
        "scope",
        "slim",
        "writable",
        "page",
        "page_size",
        "sort_by",
        "sort_dir",
    }
)


@lru_cache(maxsize=None)
def list_filter_model(tool: Tool) -> type[BaseModel]:
    """What one tool's list can be narrowed by: its params, less the ones that
    place and order a page. Derived, so a filter the list gains is one every
    caller narrowing that list (its counts, its export) takes."""
    return create_model(
        f"{tool.value}_list_filters",
        __config__=ConfigDict(extra="forbid"),
        **{
            param.name: (param.annotation, param.default.default)
            for param in TOOL_LISTS[tool].params
            if param.name not in _NOT_FILTERS
        },
    )


def _list_filters(tool: Tool, raw: Optional[str]) -> dict[str, Any]:
    """The list filters a request sent as JSON, checked against the tool's
    list; the ones it left out are not narrowing."""
    if not raw:
        return {}
    try:
        return (
            list_filter_model(tool)
            .model_validate_json(raw)
            .model_dump(exclude_unset=True)
        )
    except ValidationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueryMessages.INVALID_CONDITIONS,
        )


#: Live rows and the archive: the views every tool has.
DEFAULT_VIEWS: Mapping[str, Mapping[str, Any]] = {
    "active": {},
    "archived": {"archived": True},
}

#: The views of a tool with templates: its live rows without them, the
#: templates on their own, and an archive holding both.
TEMPLATE_VIEWS: Mapping[str, Mapping[str, Any]] = {
    "active": {"is_template": False},
    "templates": {"is_template": True},
    "archived": {"archived": True},
}


@dataclass(frozen=True)
class ToolListSpec:
    """Everything about one tool's API surface that the shared routes do not know.

    For the list: the model and its initiative switch, what a page eager-loads,
    how a row becomes a summary, the order a request that names none falls back
    to, the parameters the route publishes, and the page defaults (in
    ``params``). For the single row a write answers with: the Read model and
    the tool's own re-read-and-serialize (``read_model`` / ``read_row``), which
    the shared sharing route reads.
    """

    tool: Tool
    model: Any
    response_model: Any
    #: (req) -> eager loads for the page query
    loader_options: Callable[["ListRequest"], list]
    #: (req) -> ORDER BY when the request asks for no sort
    default_order: Callable[["ListRequest"], list]
    #: async (spec, req, rows) -> the response's ``items``
    serialize: Callable[..., Awaitable[list]]
    params: tuple[ListParam, ...]
    #: The tool's detail Read model — the single row a write answers with.
    read_model: Any
    #: async (session, row_id, user, guild_context) -> ``read_model``. The
    #: tool's own re-read-and-serialize, which the shared sharing route
    #: (``tool_grants.py``) answers with.
    read_row: Callable[..., Awaitable[Any]]
    #: What the sharing route's published description adds for this tool.
    grants_note: Optional[str] = None
    #: async (spec, req) -> the whole WHERE. Defaults to the shared set.
    conditions: Optional[Callable[..., Awaitable[list]]] = None
    #: Rows belonging to the guild rather than to an initiative (guild calendars).
    guild_level_rows: bool = False
    #: Send a reader whose page has fallen off the end back to the first one.
    clamp_page: bool = False
    #: Sort fields this tool offers beyond the shared three.
    extra_sort_fields: Optional[dict[str, Any]] = None
    #: (req) -> statement transform applied before ORDER BY reads it.
    refine: Optional[Callable[["ListRequest"], Callable[[Any], Any]]] = None
    #: The views the tool's page shows one at a time, each as the list
    #: parameters that select it. Every count is a count of one of these lists.
    views: Mapping[str, Mapping[str, Any]] = field(
        default_factory=lambda: dict(DEFAULT_VIEWS)
    )
    list_doc: Optional[str] = None
    #: The OpenAPI tag, where it is not the tool's own plural.
    tag: Optional[str] = None
    #: Whether an installed plug-in may list this tool, under its read scope.
    serves_plugins: bool = True


# ---------------------------------------------------------------------------
# Shared hook bodies
# ---------------------------------------------------------------------------


async def _default_conditions(spec: ToolListSpec, req: ListRequest) -> list:
    """The WHERE every tool list shares, plus the archive answer."""
    values = req.values
    return [
        *tool_listing.base_conditions(
            spec.tool,
            spec.model,
            req.user_id,
            context=req.guild_context,
            initiative_id=values.get("initiative_id"),
            search=values.get("search"),
            tag_ids=values.get("tag_ids"),
            guild_level_rows=spec.guild_level_rows,
        ),
        archive_service.archive_filter_clause(spec.model, values.get("archived")),
    ]


async def list_conditions(spec: ToolListSpec, req: ListRequest) -> list:
    """The WHERE one tool's list answers ``req`` with — what an export of the
    tool narrows by, too. Every tool carries properties, so every list
    narrows by them the same way."""
    return [
        *await (spec.conditions or _default_conditions)(spec, req),
        *await properties_service.property_filter_clauses(
            req.session,
            spec.tool.value,
            req.values.get("property_filters"),
            names_people=req.user is not None,
        ),
    ]


#: (session, guild_id, rows) -> each row's card preview, keyed by row id.
PreviewLoader = Callable[[AsyncSession, int, list], Awaitable[Mapping[int, Any]]]


def _summaries(
    schema: type[ToolSummaryBase], preview: Optional[PreviewLoader] = None
) -> Callable[..., Awaitable[list]]:
    """The ordinary page: tag the rows, count their comments where the summary
    reports them, then turn each into its summary. A tool whose card previews
    what is inside it reads every row's preview for the page at once, and only
    when the list was asked for them."""

    async def serialize(spec: ToolListSpec, req: ListRequest, rows: list) -> list:
        await tags_service.annotate_tags(req.session, rows)
        await properties_service.annotate_properties(req.session, rows)
        if "comment_count" in schema.model_fields:
            await comments_service.annotate_comment_counts(
                req.session, rows, column=f"{spec.tool.value}_id"
            )
        items = [
            serialize_tool(schema, row, context=req.guild_context, user_id=req.user_id)
            for row in rows
        ]
        if preview is not None and req.values.get("include_preview"):
            previews = await preview(req.session, req.guild_id, rows)
            for item in items:
                item.preview = previews.get(item.id)
        return items

    return serialize


def _include_preview() -> ListParam:
    return ListParam(
        "include_preview",
        bool,
        Query(
            default=False,
            description=(
                "Also send what each row's card shows of what is inside it, read "
                "for the whole page at once."
            ),
        ),
    )


async def _dashboard_previews(
    session: AsyncSession, guild_id: int, rows: list
) -> dict[int, DashboardPreview]:
    """Each dashboard's canvas. The card draws its widgets from sample data, so
    nothing here runs a query."""
    return {
        dashboard.id: DashboardPreview(
            definition=dashboard.definition, config=dashboard.config
        )
        for dashboard in rows
    }


def _loads(loader: Callable[[], list]) -> Callable[[ListRequest], list]:
    """A tool whose eager loads do not depend on the request."""
    return lambda _req: loader()


def _order(*columns: Any) -> Callable[[ListRequest], list]:
    """A tool whose fallback order is fixed."""
    return lambda _req: list(columns)


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


async def _project_conditions(spec: ToolListSpec, req: ListRequest) -> list:
    values = req.values
    conditions = projects_endpoints.visible_project_conditions(
        req.user_id,
        context=req.guild_context,
        archived=values.get("archived"),
        is_template=values.get("is_template"),
        search=values.get("search"),
        tag_ids=values.get("tag_ids"),
        initiative_id=values.get("initiative_id"),
    )
    if values.get("writable"):
        conditions.append(Project.actions.any(Action.edit.value))
    return conditions


def _project_refine(req: ListRequest) -> Callable[[Any], Any]:
    """Join each reader's own manual positions, which the default order reads.

    An installed plug-in keeps no positions of its own, so its list is left as it
    is and ordered by id (:func:`_project_order`)."""
    if req.user_id is None:
        return lambda statement: statement
    return lambda statement: statement.outerjoin(
        PersonalItem,
        and_(
            col(PersonalItem.entity_type) == Tool.project.value,
            col(PersonalItem.entity_id) == Project.id,
            col(PersonalItem.user_id) == req.user_id,
        ),
    )


def _project_order(req: ListRequest) -> list:
    """The reader's own manual order, then id; by id alone for a plug-in."""
    if req.user_id is None:
        return [Project.id.asc()]
    return [col(PersonalItem.sort_order).asc().nulls_last(), Project.id.asc()]


async def _serialize_projects(spec: ToolListSpec, req: ListRequest, rows: list) -> list:
    return await projects_endpoints.serialize_project_page(
        req.session, req.user_id, rows, slim=bool(req.values.get("slim"))
    )


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


async def _file_conditions(spec: ToolListSpec, req: ListRequest) -> list:
    values = req.values
    conditions = files_endpoints.visible_file_conditions(
        req.guild_context,
        req.user_id,
        initiative_id=values.get("initiative_id"),
        search=values.get("search"),
        tag_ids=values.get("tag_ids"),
        untagged=values.get("untagged"),
        is_template=values.get("is_template"),
        file_type=values.get("file_type"),
        kind=values.get("kind"),
        collection_id=values.get("collection_id"),
    )
    conditions.append(
        archive_service.archive_filter_clause(File, values.get("archived"))
    )
    return conditions


async def _serialize_files(spec: ToolListSpec, req: ListRequest, rows: list) -> list:
    return await files_endpoints.serialize_file_page(req.session, req.user_id, rows)


_COLLECTION_FILTER = ListParam(
    "collection_id",
    Optional[int],
    Query(default=None, description="Filter to the files in one collection"),
)


# ---------------------------------------------------------------------------
# Calendars
# ---------------------------------------------------------------------------


async def _calendar_conditions(spec: ToolListSpec, req: ListRequest) -> list:
    conditions = await _default_conditions(spec, req)
    if req.values.get("scope") == "community":
        # The opposite of the unfiltered list, which is everything in scope, so
        # it is asked for by name rather than inferred from an absent
        # ``initiative_id``.
        conditions.append(Calendar.initiative_id.is_(None))
    return conditions


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------


async def _queue_conditions(spec: ToolListSpec, req: ListRequest) -> list:
    """The shared set, and whether the queue is running."""
    conditions = await _default_conditions(spec, req)
    if req.values.get("is_active") is not None:
        conditions.append(Queue.is_active.is_(req.values["is_active"]))
    return conditions


async def _post_conditions(spec: ToolListSpec, req: ListRequest) -> list:
    values = req.values
    conditions = posts_endpoints.board_conditions(
        req.user_id,
        context=req.guild_context,
        initiative_id=values.get("initiative_id"),
        search=values.get("search"),
        tag_ids=values.get("tag_ids"),
        unread=bool(values.get("unread")),
        archived=values.get("archived"),
    )
    if values.get("until") is not None:
        conditions.append(posts_service.anchored_clause(values["until"]))
    return conditions


def _post_order(req: ListRequest) -> list:
    return posts_service.board_order(anchored=req.values.get("until") is not None)


async def _serialize_posts(spec: ToolListSpec, req: ListRequest, rows: list) -> list:
    # One grouped query each for the page, so a board of twenty asks a handful
    # of times rather than forty.
    # An installed plug-in's page carries no reactions, read state or ballots.
    await posts_endpoints.annotate_post_rows(req.session, rows, user_id=req.user_id)
    return [
        serialize_tool(PostRead, post, context=req.guild_context, user_id=req.user_id)
        for post in rows
    ]


# ---------------------------------------------------------------------------
# One row per tool
# ---------------------------------------------------------------------------


TOOL_LISTS: dict[Tool, ToolListSpec] = {
    Tool.project: ToolListSpec(
        tool=Tool.project,
        read_model=ProjectRead,
        read_row=projects_endpoints.read_after_write,
        model=Project,
        response_model=ProjectListResponse,
        loader_options=lambda req: projects_endpoints.project_load_options(
            slim=bool(req.values.get("slim"))
        ),
        # No sort asked for keeps the per-user manual order the projects page
        # drags into place; a sort replaces it for this request only.
        default_order=_project_order,
        serialize=_serialize_projects,
        conditions=_project_conditions,
        refine=_project_refine,
        clamp_page=True,
        views=TEMPLATE_VIEWS,
        params=(
            _archived(),
            _is_template(Tool.project),
            search_param(),
            _initiative_id(
                "Only projects in this initiative. Omit for every initiative "
                "the caller can see."
            ),
            ListParam(
                "slim",
                bool,
                Query(
                    default=False,
                    description=(
                        "Return a lightweight projection (id, name, icon, "
                        "initiative_id, can) without files, "
                        "grants, tags, or the nested initiative. For project "
                        "pickers and other list-only callers."
                    ),
                ),
            ),
            ListParam(
                "writable",
                bool,
                Query(
                    default=False,
                    description=(
                        "Only projects the caller may edit — the pickers that "
                        "move work into a project."
                    ),
                ),
            ),
            sort_by_param(
                "Order by one of: name, initiative, updated_at. Omit to keep "
                "the reader's own manual order."
            ),
            sort_dir_param(),
            _tag_ids(Tool.project),
            _property_filters(),
            page_param(),
            page_size_param(0, ge=0, le=100),
        ),
    ),
    Tool.file: ToolListSpec(
        tool=Tool.file,
        read_model=FileRead,
        read_row=files_endpoints.read_after_write,
        model=File,
        response_model=FileListResponse,
        loader_options=_loads(files_service.list_loader_options),
        default_order=_order(File.updated_at.desc(), File.id.desc()),
        serialize=_serialize_files,
        conditions=_file_conditions,
        views=TEMPLATE_VIEWS,
        # The one tool that also sorts by when a row was written — a file
        # list is a filing cabinet, and "newest first" is how you read one.
        extra_sort_fields={"created_at": File.created_at},
        params=(
            _initiative_id(),
            search_param(description=None),
            _tag_ids(Tool.file, description="Filter by tag IDs"),
            _property_filters(),
            ListParam(
                "untagged",
                Optional[bool],
                Query(default=None, description="Filter to files with no tags"),
            ),
            _is_template(Tool.file),
            ListParam(
                "file_type",
                Optional[FileType],
                Query(default=None, description="Filter by file type"),
            ),
            ListParam(
                "kind",
                Optional[FileKind],
                Query(default=None, description="Filter by kind of file"),
            ),
            _COLLECTION_FILTER,
            page_param(),
            page_size_param(20, ge=0, le=100),
            sort_by_param("Order by one of: name, initiative, updated_at, created_at."),
            sort_dir_param(),
            _archived(),
        ),
        list_doc=(
            "List files in the active guild visible to the current user.\n"
            "\n"
            "DAC: Files shared with the reader directly or through "
            "their initiative role.\n"
            "\n"
            "Pagination: page_size=0 serves the full set in server-bounded "
            "windows —\n"
            "walk page=1,2,... until has_next is false.\n"
            "\n"
            'Cross-guild "my files" lives under /me/files (see '
            "list_my_files)."
        ),
    ),
    Tool.queue: ToolListSpec(
        tool=Tool.queue,
        read_model=QueueRead,
        read_row=queues_endpoints.read_after_write,
        model=Queue,
        response_model=QueueListResponse,
        loader_options=_loads(queues_service.list_loader_options),
        default_order=_order(Queue.updated_at.desc(), Queue.id.desc()),
        serialize=_summaries(
            QueueSummary,
            preview=lambda session, _guild_id, rows: queues_service.list_previews(
                session, rows
            ),
        ),
        conditions=_queue_conditions,
        params=(
            _initiative_id(),
            search_param(),
            sort_by_param(),
            sort_dir_param(),
            _tag_ids(Tool.queue),
            _property_filters(),
            _archived(),
            ListParam(
                "is_active",
                Optional[bool],
                Query(
                    default=None,
                    description="Only running queues, or only stopped ones.",
                ),
            ),
            _include_preview(),
            page_param(),
            page_size_param(20, ge=1, le=100),
        ),
        list_doc="List queues visible to the current user (guild admins see all).",
    ),
    Tool.counter_group: ToolListSpec(
        tool=Tool.counter_group,
        read_model=CounterGroupRead,
        read_row=counters_endpoints.read_after_write,
        model=CounterGroup,
        response_model=CounterGroupListResponse,
        loader_options=_loads(counters_service.list_loader_options),
        default_order=_order(CounterGroup.updated_at.desc(), CounterGroup.id.desc()),
        serialize=_summaries(
            CounterGroupSummary,
            preview=lambda session, _guild_id, rows: counters_service.list_previews(
                session, rows
            ),
        ),
        # The counters router carries the wider "counters" tag, which the
        # individual counters underneath these groups share.
        tag="counters",
        params=(
            _initiative_id(),
            search_param(),
            sort_by_param(),
            sort_dir_param(),
            _tag_ids(Tool.counter_group),
            _property_filters(),
            _archived(),
            _include_preview(),
            page_param(),
            page_size_param(20, ge=1, le=100),
        ),
    ),
    Tool.calendar: ToolListSpec(
        tool=Tool.calendar,
        read_model=CalendarRead,
        read_row=calendars_endpoints.read_after_write,
        model=Calendar,
        response_model=CalendarListResponse,
        loader_options=_loads(calendars_service.calendar_loader_options),
        default_order=_order(Calendar.name.asc(), Calendar.id.asc()),
        serialize=_summaries(CalendarSummary),
        conditions=_calendar_conditions,
        # A calendar may belong to the guild rather than to an initiative: the
        # plug-in holds it, and no initiative's switch has anything to say about it.
        guild_level_rows=True,
        params=(
            _initiative_id(),
            ListParam("scope", Optional[Literal["community"]], Query(default=None)),
            search_param(),
            sort_by_param(),
            sort_dir_param(),
            _tag_ids(Tool.calendar),
            _property_filters(),
            _archived(),
            page_param(),
            page_size_param(100, ge=1, le=200),
        ),
        list_doc=(
            "List calendars visible to the current user (guild admins see "
            "all).\n"
            "\n"
            "``scope=community`` narrows to the guild's own calendars — the ones the "
            "calendar\n"
            "plug-in holds, belonging to no initiative. That is the opposite of the\n"
            "unfiltered list, which is everything in scope, so it is asked for by "
            "name\n"
            "rather than inferred from an absent ``initiative_id``."
        ),
    ),
    Tool.dashboard: ToolListSpec(
        tool=Tool.dashboard,
        # Not among what an installed plug-in reads today.
        serves_plugins=False,
        read_model=DashboardRead,
        read_row=dashboards_endpoints.read_after_write,
        grants_note=(
            "This shares the canvas, not its data: each widget still resolves against\n"
            "the viewer's own access to the sources it binds."
        ),
        model=Dashboard,
        response_model=DashboardListResponse,
        loader_options=_loads(dashboards_service.dashboard_loader_options),
        default_order=_order(Dashboard.name.asc(), Dashboard.id.asc()),
        serialize=_summaries(DashboardSummary, preview=_dashboard_previews),
        params=(
            _initiative_id(),
            search_param(),
            sort_by_param(),
            sort_dir_param(),
            _tag_ids(Tool.dashboard),
            _property_filters(),
            _archived(),
            _include_preview(),
            page_param(),
            page_size_param(100, ge=1, le=200),
        ),
        list_doc="List dashboards visible to the current user (guild admins see all).",
    ),
    Tool.post: ToolListSpec(
        tool=Tool.post,
        read_model=PostRead,
        read_row=posts_endpoints.read_after_write,
        model=Post,
        response_model=PostListResponse,
        loader_options=_loads(posts_service.list_loader_options),
        default_order=_post_order,
        serialize=_serialize_posts,
        conditions=_post_conditions,
        params=(
            _initiative_id(),
            search_param(
                "Full-text match over the notice — its headline and its body. "
                "Reads the same index the search page does, so the board's "
                "filter and a search agree about what matches."
            ),
            sort_by_param(
                "Order by one of: name, initiative, updated_at. Omit for the "
                "board order — live pins first, then newest first."
            ),
            sort_dir_param(),
            _tag_ids(Tool.post),
            _property_filters(),
            _archived(),
            ListParam(
                "unread",
                bool,
                Query(
                    default=False,
                    description="Only notices this reader has not read yet.",
                ),
            ),
            ListParam(
                "until",
                Optional[datetime],
                Query(
                    default=None,
                    description=(
                        "Start the board at this instant and go back — "
                        "inclusive, and measured by the same date the feed is "
                        "ordered by. This is how a timeline jumps to a month "
                        "without paging through everything since. An anchored "
                        "board is strictly chronological: the pinned band steps "
                        "aside, because a pin says what matters now rather than "
                        "what mattered then."
                    ),
                ),
            ),
            page_param(),
            page_size_param(
                posts_endpoints.BOARD_PAGE_SIZE,
                ge=1,
                le=posts_endpoints.MAX_BOARD_PAGE_SIZE,
                description=(
                    "Posts per page. Small by default: a board renders each "
                    "post's body, so a page is that many editors to mount."
                ),
            ),
        ),
        list_doc=(
            "List posts visible to the current user (guild admins see all).\n"
            "\n"
            "Returns whole posts — a board shows notices, not headlines — which "
            "is why\n"
            "it pages in fives. A scheduled notice is here only for the people "
            "who\n"
            "could edit it; for everyone else the board starts when it goes up."
        ),
    ),
    Tool.wiki: ToolListSpec(
        tool=Tool.wiki,
        read_model=WikiRead,
        read_row=wikis_endpoints.read_after_write,
        model=Wiki,
        response_model=WikiListResponse,
        loader_options=_loads(wikis_service.list_loader_options),
        default_order=_order(Wiki.updated_at.desc(), Wiki.id.desc()),
        serialize=_summaries(WikiSummary),
        params=(
            _initiative_id(),
            search_param(
                "Full-text match over the wiki's name and description, through "
                "the same index the search page reads."
            ),
            sort_by_param(
                "Order by one of: name, initiative, updated_at. Omit for newest first."
            ),
            sort_dir_param(),
            _tag_ids(Tool.wiki),
            _property_filters(),
            _archived(),
            page_param(),
            page_size_param(100, ge=0, le=500),
        ),
        list_doc="List wikis visible to the current user (guild admins see all).",
    ),
}


# ---------------------------------------------------------------------------
# Mounting
# ---------------------------------------------------------------------------


def _tags(spec: ToolListSpec) -> list[str | Enum]:
    return [spec.tag or spec.tool.plural]


_CONTEXT_PARAMS: tuple[tuple[str, Any], ...] = (
    ("session", RLSSessionDep),
    ("current_user", CurrentUserDep),
    ("guild_context", GuildContextDep),
)


def _actor_params(tool: Tool) -> tuple[tuple[str, Any], ...]:
    """The same three, for a list an installed plug-in may call under the tool's
    read scope: a person arrives exactly as above, and an install through its
    token."""
    scope = scope_name(tool_resource(tool), PluginScopeAccess.read)
    return (
        ("session", ActorSessionDep),
        ("current_user", ActorUserDep),
        ("guild_context", Annotated[ActorContext, Depends(plugin_scope(scope))]),
    )


def _signature(
    params: tuple[ListParam, ...],
    context_params: tuple[tuple[str, Any], ...] = _CONTEXT_PARAMS,
) -> inspect.Signature:
    """The signature FastAPI reads off a tool's list handler.

    Keyword-only throughout, so the registry's declared order is what the
    published parameter list follows: the dependencies contribute the path and
    cookie params, which OpenAPI groups separately, and the tool's own query
    parameters keep the order its route has always published them in.
    """
    declared = [
        inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=annotation)
        for name, annotation in context_params
    ]
    declared += [
        inspect.Parameter(
            param.name,
            inspect.Parameter.KEYWORD_ONLY,
            annotation=param.annotation,
            default=param.default,
        )
        for param in params
    ]
    return inspect.Signature(declared)


async def _list(spec: ToolListSpec, request: ListRequest) -> Any:
    """One page of a tool's list, as its ``GET /`` answers it."""
    values = request.values
    conditions = await list_conditions(spec, request)
    rows, total_count, page = await tool_listing.list_tool_rows(
        request.session,
        spec.model,
        conditions=conditions,
        loader_options=spec.loader_options(request),
        sort_by=values.get("sort_by"),
        sort_dir=values.get("sort_dir"),
        default_order=spec.default_order(request),
        page=values["page"],
        page_size=values["page_size"],
        extra_sort_fields=spec.extra_sort_fields,
        refine=spec.refine(request) if spec.refine else None,
        clamp=spec.clamp_page,
    )
    items = await spec.serialize(spec, request, rows)
    page_size = values["page_size"]
    return spec.response_model(
        **build_paginated_response(items, total_count, page, page_size)
    )


def _mount_list(spec: ToolListSpec) -> None:
    """Mount ``GET /`` for one tool."""

    async def list_rows(session, current_user, guild_context, **values):
        return await _list(
            spec, ListRequest(session, current_user, guild_context, values)
        )

    list_rows.__signature__ = _signature(
        spec.params,
        _actor_params(spec.tool) if spec.serves_plugins else _CONTEXT_PARAMS,
    )
    router.add_api_route(
        f"/{spec.tool.route_segment}/",
        list_rows,
        methods=["GET"],
        response_model=spec.response_model,
        name=f"list_{spec.tool.plural}",
        description=spec.list_doc,
        tags=_tags(spec),
    )


async def view_conditions(
    spec: ToolListSpec,
    session: AsyncSession,
    current_user: User,
    guild_context: ActorContext,
    **values: Any,
) -> list:
    """The WHERE the tool's own list answers ``values`` with."""
    return await list_conditions(
        spec, ListRequest(session, current_user, guild_context, values)
    )


@router.get(
    "/tools/counts/by-initiative",
    response_model=ToolCountsByInitiativeResponse,
    tags=["tools"],
)
async def get_tool_counts_by_initiative(
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> ToolCountsByInitiativeResponse:
    """Every tool's live rows, grouped by initiative.

    What the sidebar and the initiative directory badge: each tool's ``active``
    view, counted by the same conditions as its list, in one statement for
    every tool rather than a request per tool. Rows belonging to the guild
    rather than an initiative fall outside every group.
    """
    selects = [
        select(literal(spec.tool.value), spec.model.initiative_id, func.count())
        .where(
            *await view_conditions(
                spec, session, current_user, guild_context, **spec.views["active"]
            )
        )
        .group_by(spec.model.initiative_id)
        for spec in TOOL_LISTS.values()
    ]
    counts: dict[Tool, dict[int, int]] = {tool: {} for tool in TOOL_LISTS}
    for tool, initiative_id, count in (await session.exec(union_all(*selects))).all():
        if initiative_id is not None:
            counts[Tool(tool)][initiative_id] = count
    return ToolCountsByInitiativeResponse(counts=counts)


@router.get("/tools/{tool}/counts", response_model=ToolCountsResponse, tags=["tools"])
async def get_tool_counts(
    tool: Tool,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
    initiative_id: Optional[int] = Query(default=None),
    view: str = Query(
        default="active",
        description="The view the tag counts are for: active, archived, or "
        "templates for a tool that has them",
    ),
    filters: Optional[str] = Query(
        default=None,
        description="JSON object of the tool's own list filters, as its list "
        'route takes them (``{"search": "notes", "kind": "document"}``), '
        "that the tag counts are for",
    ),
    include_tags: bool = Query(
        default=False, description="Also count the tag tree beside ``view``"
    ),
) -> ToolCountsResponse:
    """How many rows sit in each of one tool's views, and, when asked, the tag
    tree beside the one being shown.

    Every figure is a count of the tool's own list. ``views`` counts each view
    in the initiative (or the guild) whatever the page's filters, so a toggle
    says how much sits behind each view before it is opened. The tag counts
    are for ``view`` after ``search`` and the tool's own filters, so the tree
    and the list beside it agree; tags are not a filter here, because the tree
    shows every one. A page with no tree leaves ``include_tags`` off and its
    request runs the view counts alone.
    """
    spec = TOOL_LISTS[tool]
    if view not in spec.views:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=QueryMessages.UNKNOWN_VIEW,
        )
    scope = {"initiative_id": initiative_id}
    # Checked whether or not the tag counts are asked for. The tree shows
    # every tag, so tags are what it counts, not what it narrows by; and what
    # the views select by (the archive, templates) is the view's to say.
    set_aside = {
        "tag_ids",
        "untagged",
        *(key for v in spec.views.values() for key in v),
    }
    narrowing = {
        name: value
        for name, value in _list_filters(tool, filters).items()
        if name not in set_aside
    }

    view_counts = (
        await session.exec(
            union_all(
                *[
                    select(literal(name), func.count()).where(
                        *await view_conditions(
                            spec,
                            session,
                            current_user,
                            guild_context,
                            **scope,
                            **params,
                        )
                    )
                    for name, params in spec.views.items()
                ]
            )
        )
    ).all()
    if not include_tags:
        return ToolCountsResponse(views=dict(view_counts))

    shown = select(spec.model.id).where(
        *await view_conditions(
            spec,
            session,
            current_user,
            guild_context,
            **scope,
            **narrowing,
            **spec.views[view],
        )
    )
    link = tags_service.TOOL_TAG_LINKS[tool]
    tag_rows = (await session.exec(tags_service.tag_counts_for(link, shown))).all()
    shown_subq = shown.subquery()
    untagged_count = await session.scalar(
        select(func.count())
        .select_from(shown_subq)
        .where(tags_service.untagged_clause(link, shown_subq.c.id))
    )

    return ToolCountsResponse(
        views=dict(view_counts),
        tag_counts=dict(tag_rows),
        untagged_count=untagged_count,
    )


for _spec in TOOL_LISTS.values():
    _mount_list(_spec)


# ---------------------------------------------------------------------------
# A collection's files
# ---------------------------------------------------------------------------


async def _collection_file_conditions(spec: ToolListSpec, req: ListRequest) -> list:
    """The Files list's, and where an anchored page starts."""
    conditions = await _file_conditions(spec, req)
    values = req.values
    if values.get("until") is not None:
        conditions.append(
            collections_service.added_from(
                values["collection_id"],
                values["until"],
                oldest_first=values.get("sort_by") == "added_at"
                and values.get("sort_dir") == "asc",
            )
        )
    return conditions


async def _serialize_collection_files(
    spec: ToolListSpec, req: ListRequest, rows: list
) -> list:
    collection_id = req.values["collection_id"]
    ids = [row.id for row in rows]
    added = await collections_service.added_at_of(req.session, collection_id, ids)
    fields = await properties_service.summaries_by_id(
        req.session, Tool.file.value, ids, collection_id=collection_id
    )
    for row in rows:
        object.__setattr__(row, "added_at", added[row.id])
        object.__setattr__(row, "fields", fields.get(row.id, []))
    return await files_endpoints.serialize_file_page(
        req.session, req.user_id, rows, CollectionFileSummary
    )


def _collection_files(collection_id: int) -> ToolListSpec:
    """The Files list narrowed to one collection, which also orders by when
    each file was added to it, and by that unless told otherwise."""
    added_at = col(CollectionFile.added_at)
    return replace(
        TOOL_LISTS[Tool.file],
        response_model=CollectionFileListResponse,
        conditions=_collection_file_conditions,
        serialize=_serialize_collection_files,
        refine=lambda _req: (
            lambda statement: statement.join(
                CollectionFile,
                and_(
                    col(CollectionFile.file_id) == File.id,
                    col(CollectionFile.collection_id) == collection_id,
                ),
            )
        ),
        default_order=_order(added_at.desc(), File.id.desc()),
        extra_sort_fields={"created_at": File.created_at, "added_at": added_at},
    )


_UNTIL_ADDED = ListParam(
    "until",
    Optional[datetime],
    Query(
        default=None,
        description=(
            "Start the list at this instant, measured by when each file was "
            "added to the collection. Newest first it is a ceiling and the page "
            "walks back from it; oldest first (sort_by=added_at, sort_dir=asc) "
            "a floor and the page walks forward. This is how a timeline jumps "
            "to a month: pair it with the matching end of the month's bucket."
        ),
    ),
)
#: The Files list's parameters, less the collection filter the path states,
#: with its own order and the timeline's anchor.
_COLLECTION_FILES_PARAMS = (
    *(
        sort_by_param(
            "Order by one of: name, initiative, updated_at, created_at, "
            "added_at (when each was added to the collection). Omit for "
            "added_at, newest first."
        )
        if p.name == "sort_by"
        else p
        for p in TOOL_LISTS[Tool.file].params
        if p is not _COLLECTION_FILTER
    ),
    _UNTIL_ADDED,
)


async def list_collection_files(
    session, current_user, guild_context, collection_id, **values
):
    """The files in one collection the reader can open: the Files list, with
    its parameters, narrowed to the collection, each with when it was added
    to it. A collection out of reach is a 404."""
    await resource_access.load_child(session, Collection, collection_id)
    request = ListRequest(
        session, current_user, guild_context, {**values, "collection_id": collection_id}
    )
    return await _list(_collection_files(collection_id), request)


list_collection_files.__signature__ = _signature(
    _COLLECTION_FILES_PARAMS,
    (*_actor_params(Tool.file), ("collection_id", int)),
)
router.add_api_route(
    "/collections/{collection_id}/files",
    list_collection_files,
    methods=["GET"],
    response_model=CollectionFileListResponse,
    name="list_collection_files",
    tags=_tags(TOOL_LISTS[Tool.file]),
)


async def get_collection_files_timeline(
    session, current_user, guild_context, collection_id, tz, **values
):
    """The months files were added to this collection in, newest first, each
    with how many of them the reader can open and the instants to jump to:
    what the timeline rail is drawn from. Takes the same filters the list
    does, so the rail is a picture of the list as it stands."""
    await resource_access.load_child(session, Collection, collection_id)
    request = ListRequest(
        session, current_user, guild_context, {**values, "collection_id": collection_id}
    )
    conditions = await list_conditions(TOOL_LISTS[Tool.file], request)
    return TimelineResponse(
        buckets=await timeline_service.month_buckets(
            session,
            date_expr=col(CollectionFile.added_at),
            conditions=[
                *conditions,
                col(CollectionFile.file_id) == File.id,
                col(CollectionFile.collection_id) == collection_id,
            ],
            tz=tz,
        )
    )


get_collection_files_timeline.__signature__ = _signature(
    (
        *(
            p
            for p in _COLLECTION_FILES_PARAMS
            if p.name not in _NOT_FILTERS and p.name != "until"
        ),
        ListParam(
            "tz",
            Optional[str],
            Query(
                default=None,
                description=(
                    "IANA zone the month boundaries are cut in, e.g. "
                    "Pacific/Auckland. Defaults to UTC."
                ),
            ),
        ),
    ),
    (*_actor_params(Tool.file), ("collection_id", int)),
)
router.add_api_route(
    "/collections/{collection_id}/files/timeline",
    get_collection_files_timeline,
    methods=["GET"],
    response_model=TimelineResponse,
    name="get_collection_files_timeline",
    tags=_tags(TOOL_LISTS[Tool.file]),
)
