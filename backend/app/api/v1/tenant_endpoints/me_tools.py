"""Cross-guild tool lists — the My Tools page.

The page is the guild home's table with the guild boundary taken off: pick a
tool, see everything of that kind that reaches you, across every community you
belong to. Inside each community a My Tools list IS that tool's own list —
its live view, through :func:`tool_lists.list_conditions`, loaded and
serialized by the same registry entry — so what reaches you here is what its
page in that community shows. The made-by-me toggle is the one thing added.

``GET /me/{tool}`` is one route, mounted once for every tool out of
:data:`MY_TOOL_LISTS`. Projects, files and calendars each had a cross-guild
list of their own before this page existed — for the task wizard, for My
Calendar — and each was its own copy of the same merge. They answer here now,
so the nine lists cannot drift. What survives per tool is what a merge across
communities needs of its own: the order a request that names none falls back
to (one key the rows carry, which every community orders by alike), the page
window and the published description. Everything else is read from
:data:`TOOL_LISTS` — a tool answers in one shape whether it is asked inside a
guild or across them.

Every route keeps the path, method, name and parameters its tool already had,
so the published surface — its operation id included — is unchanged.

All nine run on ``UserSessionDep``: the caller is resolved against the shared
tables as their own platform role, and each guild is then entered with the
membership role they hold there (``cross_guild.gather_across_guilds``), which
is the same ``SET ROLE guild_<id>`` a ``/c/{community_id}`` request makes.
"""

# NOT ``from __future__ import annotations``: the list handlers are built per
# tool from a signature assembled at import time, and the parameter annotations
# have to be real objects for FastAPI to read them.

import inspect
from dataclasses import dataclass
from typing import Annotated, Any, Callable, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import ColumnElement, func, literal, union_all
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import UserSessionDep, get_current_active_user
from app.api.v1.tenant_endpoints.tool_lists import (
    TOOL_LISTS,
    ListParam,
    ListRequest,
    list_conditions,
    page_param,
    page_size_param,
    search_param,
    sort_by_param,
    sort_dir_param,
)
from app.core.tools import Tool
from app.db.session import require_guild_context
from app.db.query import build_paginated_response
from app.models.platform.user import User
from app.schemas.tenant.my_tools import MyToolCountsResponse
from app.services.cross_guild import (
    gather_across_guilds,
    member_guild_ids,
    page_across_guilds,
)
from app.services.tenant import my_tools as my_tools_service

me_router = APIRouter()

CurrentUserDep = Annotated[User, Depends(get_current_active_user)]


# ---------------------------------------------------------------------------
# Query parameters
# ---------------------------------------------------------------------------


_SORT_BY_DESCRIPTION = (
    "Order by one of: name, updated_at, created_at. Omit for this tool's own "
    "default order. There is no `initiative` here — a merged cross-guild list "
    "is ordered by what the tool's own rows carry, and an initiative name is "
    "not one of them."
)


def _params(tool: Tool, page_size: ListParam) -> tuple[ListParam, ...]:
    """The parameters a My Tools list publishes, in the order it publishes them.

    Only the page window differs between tools, so it is the argument.
    """
    plural = tool.plural.replace("_", " ")
    return (
        ListParam(
            "guild_ids", Optional[List[int]], Query(default=None, alias="community_ids")
        ),
        search_param(None),
        ListParam(
            "created_by_me",
            bool,
            Query(default=False, description=f"Narrow to {plural} the caller created."),
        ),
        sort_by_param(_SORT_BY_DESCRIPTION),
        sort_dir_param(),
        page_param(),
        page_size,
    )


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MyToolList:
    """What a cross-guild list needs beyond the tool's own list.

    The order it falls back to when the request asks for none, its page window
    and its published description. Which rows, how they load and how they
    serialize are the tool's :data:`TOOL_LISTS` entry.
    """

    #: (model) -> the SQL sort key used when the request names no order. One
    #: key the rows carry, so every guild orders alike and their pages merge;
    #: a tool's own default order may not be one (projects keep each reader's
    #: manual order, which is a join).
    default_key: Callable[[Any], ColumnElement[Any]]
    #: The page window; the other parameters are every tool's.
    page_size: ListParam
    list_doc: str
    default_desc: bool = True


MY_TOOL_LISTS: dict[Tool, MyToolList] = {
    Tool.project: MyToolList(
        default_key=lambda model: model.updated_at,
        page_size=page_size_param(20, ge=1, le=100),
        list_doc=(
            "List projects across all guilds the current user belongs to.\n"
            "\n"
            "Returns a paginated list filtered by DAC permissions, excluding\n"
            "archived and template projects. Supports optional guild, "
            "name-search and\n"
            "made-by-me filters."
        ),
    ),
    Tool.file: MyToolList(
        default_key=lambda model: model.updated_at,
        page_size=page_size_param(20, ge=0, le=100),
        list_doc=(
            "Files that reach the current user across every guild they "
            "belong to.\n"
            "\n"
            "An optional ``guild_ids`` filter narrows to a subset of guilds, "
            "and\n"
            "``created_by_me`` to the ones the caller wrote."
        ),
    ),
    Tool.queue: MyToolList(
        default_key=lambda model: model.updated_at,
        page_size=page_size_param(20, ge=0, le=100),
        list_doc="Queues that reach the caller across every guild they belong to.",
    ),
    Tool.counter_group: MyToolList(
        default_key=lambda model: model.updated_at,
        page_size=page_size_param(20, ge=0, le=100),
        list_doc=(
            "Counter groups that reach the caller across every guild they belong to."
        ),
    ),
    Tool.calendar: MyToolList(
        # By name, like the calendar list inside a guild: this one backs a
        # grouping panel, which is read down rather than scanned for what moved.
        default_key=my_tools_service.name_key,
        default_desc=False,
        page_size=page_size_param(200, ge=1, le=200),
        list_doc=(
            "List the calendars visible to the user across all their guilds — "
            "the\n"
            "backing data for the My Calendar grouping panel and the My Tools "
            "table.\n"
            "\n"
            "Visits each member guild schema under the user's own RLS context "
            "(guild\n"
            "isolation + DAC hold); each orders and limits its own rows in SQL, "
            "and the\n"
            "page is cut from their merge. Inside each guild this is the "
            "calendar list's\n"
            "own live view, so a guild calendar belongs in it like any other."
        ),
    ),
    Tool.dashboard: MyToolList(
        default_key=my_tools_service.name_key,
        default_desc=False,
        page_size=page_size_param(20, ge=0, le=100),
        list_doc="Dashboards that reach the caller across every guild they belong to.",
    ),
    Tool.post: MyToolList(
        # The board's own date: when it went up, or when it is due to. A
        # scheduled draft — which only its writers see here — sorts by the day
        # it will land, not by the day somebody started it.
        default_key=lambda model: func.coalesce(
            model.published_at, model.scheduled_for, model.created_at
        ),
        page_size=page_size_param(20, ge=0, le=50),
        list_doc=(
            "Posts that reach the caller across every guild they belong to.\n"
            "\n"
            "Paged small like the board itself: these carry their bodies, and "
            "a body is\n"
            "an editor the client mounts."
        ),
    ),
    Tool.wiki: MyToolList(
        default_key=lambda model: model.updated_at,
        page_size=page_size_param(20, ge=0, le=100),
        list_doc=("Wikis that reach the caller across every guild they belong to."),
    ),
}


# ---------------------------------------------------------------------------
# The merge
# ---------------------------------------------------------------------------


def _live_view(
    guild_session: AsyncSession, current_user: User, tool: Tool, **values: Any
) -> ListRequest:
    """The tool's own list in this guild, asked for its live view.

    Built inside :func:`gather_across_guilds`, which has routed the session
    into the guild and computed the reader's standing there.
    """
    spec = TOOL_LISTS[tool]
    return ListRequest(
        guild_session,
        current_user,
        require_guild_context(guild_session),
        {**spec.views["active"], **values},
    )


async def _conditions(
    request: ListRequest, tool: Tool, *, created_by_me: bool, user_id: int
) -> list:
    """What the tool's list answers ``request`` with, and, for the page's other
    view, only what the reader wrote. Authorship, not ownership: handing a
    file to someone else does not take it out of the things you wrote."""
    spec = TOOL_LISTS[tool]
    conditions = await list_conditions(spec, request)
    if created_by_me:
        conditions.append(spec.model.created_by == user_id)
    return conditions


async def list_across_guilds(
    session: AsyncSession,
    current_user: User,
    tool: Tool,
    *,
    guild_ids: Optional[List[int]],
    search: Optional[str],
    created_by_me: bool,
    sort_by: Optional[str],
    sort_dir: Optional[str],
    page: int,
    page_size: int,
) -> tuple[list, int]:
    """One page of ``tool`` across every guild the caller belongs to.

    Two passes, since per-schema ids collide and no statement spans guilds:

    1. **Order.** Each guild answers with the sort key and id of its first
       ``page * page_size`` rows, ordered and limited in SQL, and its count;
       the page is cut from their merge.
    2. **Load.** Only the rows on that page are loaded and serialized, from
       the guilds that contribute to it. By id alone, so a concurrent edit
       cannot take a row the first pass counted off the page.
    """
    spec = MY_TOOL_LISTS[tool]
    tool_list = TOOL_LISTS[tool]
    model = tool_list.model
    key, descending = my_tools_service.sort_key(
        model,
        sort_by,
        sort_dir,
        default=spec.default_key,
        default_desc=spec.default_desc,
    )
    target_guilds = await member_guild_ids(
        session, current_user.id, restrict_to=guild_ids
    )

    async def _keys(
        guild_session: AsyncSession, _guild_id: int, limit: int
    ) -> tuple[list, int]:
        conditions = await _conditions(
            _live_view(guild_session, current_user, tool, search=search),
            tool,
            created_by_me=created_by_me,
            user_id=current_user.id,
        )
        rows = await guild_session.exec(
            select(key, model.id)
            .where(*conditions)
            .order_by(key.desc() if descending else key.asc(), model.id.desc())
            .limit(limit)
        )
        count = await guild_session.exec(
            select(func.count(model.id)).where(*conditions)
        )
        return list(rows.all()), count.one()

    window, total_count = await page_across_guilds(
        session,
        current_user.id,
        target_guilds,
        _keys,
        order=lambda row: (row[0], row[1]),
        descending=descending,
        page=page,
        page_size=page_size,
    )

    # (guild, id) -> where it sits on the page, so the loaded rows come back in
    # the merged order rather than in guild order.
    placement: dict[tuple[int, int], int] = {}
    wanted: dict[int, list[int]] = {}
    for index, (guild_id, row) in enumerate(window):
        placement[(guild_id, row[1])] = index
        wanted.setdefault(guild_id, []).append(row[1])

    async def _load(guild_session: AsyncSession, guild_id: int) -> list:
        request = _live_view(guild_session, current_user, tool)
        statement = (
            select(model)
            .where(model.id.in_(wanted[guild_id]))
            .options(*tool_list.loader_options(request))
        )
        rows = list((await guild_session.exec(statement)).unique().all())
        # Serialized by the tool's own list, inside the routed session:
        # relationships and the per-guild annotations (a dashboard's preview,
        # a wiki's page count) resolve in this guild's schema, and the next guild
        # expunges these rows.
        items = await tool_list.serialize(tool_list, request, rows)
        return [(placement[(guild_id, item.id)], item) for item in items]

    loaded = await gather_across_guilds(
        session, {current_user.id: sorted(wanted)}, _load
    )
    loaded.sort(key=lambda pair: pair[0])
    return [item for _, item in loaded], total_count


# ---------------------------------------------------------------------------
# Mounting
# ---------------------------------------------------------------------------


_CONTEXT_PARAMS: tuple[tuple[str, Any], ...] = (
    ("session", UserSessionDep),
    ("current_user", CurrentUserDep),
)


def _signature(params: tuple[ListParam, ...]) -> inspect.Signature:
    """The signature FastAPI reads off a tool's list handler.

    Keyword-only throughout, so the registry's declared order is what the
    published parameter list follows.
    """
    declared = [
        inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=annotation)
        for name, annotation in _CONTEXT_PARAMS
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


def _mount(tool: Tool, spec: MyToolList) -> None:
    """Mount ``GET /{tool}`` for one tool."""
    response_model = TOOL_LISTS[tool].response_model

    async def list_rows(session, current_user, **values):
        page, page_size = values["page"], values["page_size"]
        items, total_count = await list_across_guilds(
            session,
            current_user,
            tool,
            guild_ids=values["guild_ids"],
            search=values["search"],
            created_by_me=values["created_by_me"],
            sort_by=values["sort_by"],
            sort_dir=values["sort_dir"],
            page=page,
            page_size=page_size,
        )
        return response_model(
            **build_paginated_response(items, total_count, page, page_size)
        )

    list_rows.__signature__ = _signature(_params(tool, spec.page_size))
    me_router.add_api_route(
        f"/{tool.route_segment}",
        list_rows,
        methods=["GET"],
        response_model=response_model,
        name=f"list_my_{tool.plural}",
        description=spec.list_doc,
    )


@me_router.get("/tools/counts", response_model=MyToolCountsResponse)
async def get_my_tool_counts(
    session: UserSessionDep,
    current_user: CurrentUserDep,
    guild_ids: Optional[List[int]] = Query(default=None, alias="community_ids"),
    created_by_me: bool = Query(
        default=False,
        description="Count only what the caller wrote, matching the list views.",
    ),
) -> MyToolCountsResponse:
    """How much of each tool reaches the caller, across their communities.

    The My Tools page's tabs: a tool with nothing behind it gets none, so the
    page never offers a table of nothing. Each tool's figure is its list's
    total, summed over the caller's communities, and each community answers
    for every tool in one statement.
    """
    totals: dict[Tool, int] = {tool: 0 for tool in Tool}

    async def _count(guild_session: AsyncSession, _guild_id: int) -> list:
        selects = []
        for tool in Tool:
            conditions = await _conditions(
                _live_view(guild_session, current_user, tool),
                tool,
                created_by_me=created_by_me,
                user_id=current_user.id,
            )
            selects.append(select(literal(tool.value), func.count()).where(*conditions))
        for tool, count in (await guild_session.exec(union_all(*selects))).all():
            totals[Tool(tool)] += count
        # The tallies accumulate above; the merge itself carries nothing.
        return []

    target_guilds = await member_guild_ids(
        session, current_user.id, restrict_to=guild_ids
    )
    await gather_across_guilds(session, {current_user.id: target_guilds}, _count)
    return MyToolCountsResponse(counts={tool.value: n for tool, n in totals.items()})


for _tool, _spec in MY_TOOL_LISTS.items():
    _mount(_tool, _spec)
