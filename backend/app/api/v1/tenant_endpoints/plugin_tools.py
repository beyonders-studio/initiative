"""Every tool plug-in's tool and items: one set of routes, by kind.

A tool plug-in declares a tool, and its community serves it as it serves its
own (``history/tool-plugins-design.md``). Its rows are the tool's and its
items', each table a kind (``<key>.<uid>``), and these routes take the kind as
a path parameter, so no tool plug-in adds a route:

* ``GET /{kind}``: the tool as its plug-in declares it, its fields, items and
  actions, where it is on in an initiative the reader reaches;
* ``GET /{kind}/``: a page of the tool's rows in an initiative
  (``initiative_id``), or an item's under the row it sits in (``parent_id``);
* ``POST /{kind}/``: a new one there;
* ``GET`` and ``PATCH /{kind}/{row_id}``: one row, of the tool or an item;
* ``POST /{kind}/{row_id}/duplicate``: a copy of a row with the items under
  it, as a built-in tool's duplicate makes one;
* ``POST /{kind}/{row_id}/step``: move one of a row's counter fields;
* ``POST /{kind}/{row_id}/actions/{action_id}``: run one of its actions;
* ``/{kind}/{row_id}/ws``: the tool's row's change signal.

Trash, archive, comments, tags, links and sharing are the universal routes'.
Every write tells the tool's room that it changed, and nothing else.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, status

from app.api import resource_access
from app.api.actor_route import ActorRoute
from app.api.content_socket import serve_tool_stream
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    CommunityIdPath,
    plugin_tool_scope,
)
from app.core.plugin_scopes import PluginScopeAccess
from app.db.query import build_paginated_response
from app.db.session import routed_guild_id, routed_tools
from app.db.tool_rows import Located, ToolRow, load_row
from app.schemas.base import RESERVED_SIGIL_CODE, RESERVED_SIGILS
from app.schemas.tenant.plugin_tool import (
    PluginToolActionRun,
    PluginToolRead,
    PluginToolRowCreate,
    PluginToolRowList,
    PluginToolRowRead,
    PluginToolRowUpdate,
    PluginToolStep,
)
from app.schemas.tenant.tool import ToolDuplicateRequest
from app.services.content_sockets import sockets
from app.services.tenant import plugin_tool_rows as rows_service
from app.services.tenant.names import copy_name

router = APIRouter(route_class=ActorRoute)

ToolRead = Annotated[ActorContext, Depends(plugin_tool_scope(PluginScopeAccess.read))]
ToolWrite = Annotated[ActorContext, Depends(plugin_tool_scope(PluginScopeAccess.write))]

#: The longest name a row holds.
_NAME_LENGTH = 255


async def _read(
    session: ActorSessionDep, context: ActorContext, located: Located, row_id: int
) -> PluginToolRowRead:
    """One row as a read returns it, read afresh after a write."""
    row = await load_row(session, located, routed_tools(session), row_id)
    if row is None:
        raise located.tool.not_found()
    (read,) = await rows_service.serialize(session, context, located, [row])
    return read


async def _committed(
    session: ActorSessionDep,
    context: ActorContext,
    located: Located,
    row_id: int,
    tool_id: int,
    event: str,
) -> PluginToolRowRead:
    """Commit a write, tell the tool's room ``event``, and answer with the
    row."""
    await session.commit()
    sockets.signal(routed_guild_id(session), located.tool, tool_id, event)
    return await _read(session, context, located, row_id)


def _tool_id(row: ToolRow) -> int:
    return int(row.tool["id"])


@router.get("/{kind}", response_model=PluginToolRead, name="read_plugin_tool")
async def read_plugin_tool(
    kind: str, session: ActorSessionDep, context: ToolRead
) -> PluginToolRead:
    """A tool plug-in's tool as it declares it, by its kind or one of its
    items': its names, the fields of its rows and of each item with their
    kinds and options, which item sits under which, and its actions with the
    fields they ask for. Not found where it is on in no initiative the
    caller reaches."""
    located = rows_service.located_kind(routed_tools(session), kind)
    if not rows_service.placed_anywhere(context, located):
        raise located.tool.not_found()
    return rows_service.declaration(located)


@router.get("/{kind}/", response_model=PluginToolRowList, name="list_plugin_tool_rows")
async def list_plugin_tool_rows(
    kind: str,
    session: ActorSessionDep,
    context: ToolRead,
    initiative_id: int | None = Query(
        default=None, description="The initiative whose tool rows to list"
    ),
    parent_id: int | None = Query(
        default=None, description="The row whose items to list, for an item's kind"
    ),
    archived: bool = Query(default=False, description="List archived rows instead"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=0, le=100),
) -> PluginToolRowList:
    """A page of a tool plug-in's rows: its tool's in an initiative, or an
    item's under the row it sits in, in their order."""
    tools = routed_tools(session)
    located = rows_service.located_kind(tools, kind)
    if rows_service.parent_column(located) is None:
        if initiative_id is None or parent_id is not None:
            raise rows_service.refuse_placement()
        await rows_service.require_on(session, context, located, initiative_id)
        under = initiative_id
    else:
        if parent_id is None or initiative_id is not None:
            raise rows_service.refuse_placement()
        await rows_service.load_authorized(
            session, context, rows_service.parent_of(located, tools), tools, parent_id
        )
        under = parent_id
    rows = await rows_service.rows_under(
        session,
        located,
        tools,
        under,
        archived=archived,
        page_number=page,
        page_size=page_size,
    )
    total = await rows_service.count_under(session, located, under, archived=archived)
    return PluginToolRowList(
        **build_paginated_response(
            await rows_service.serialize(session, context, located, rows),
            total,
            page,
            page_size,
        )
    )


@router.post(
    "/{kind}/",
    response_model=PluginToolRowRead,
    status_code=status.HTTP_201_CREATED,
    name="create_plugin_tool_row",
)
async def create_plugin_tool_row(
    kind: str,
    body: PluginToolRowCreate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    context: ToolWrite,
) -> PluginToolRowRead:
    """Add a row: of the tool, in an initiative where its switch is on and the
    caller's role may create it, shared as ``grants`` says; or of an item,
    under a row of the tool the caller may change. Fields left out start at
    their defaults."""
    tools = routed_tools(session)
    located = rows_service.located_kind(tools, kind)
    parent = rows_service.parent_column(located)
    if parent is None:
        if body.initiative_id is None or body.parent_id is not None:
            raise rows_service.refuse_placement()
        resource_access.refuse_plugin_sharing(context, body, "grants")
        initiative = await resource_access.prepare_create(
            session, located.tool, body.initiative_id, current_user, context
        )
        placed = {"initiative_id": initiative.id}
    else:
        if body.parent_id is None or body.initiative_id is not None:
            raise rows_service.refuse_placement()
        above = await rows_service.load_authorized(
            session,
            context,
            rows_service.parent_of(located, tools),
            tools,
            body.parent_id,
            action=rows_service.writing(located),
        )
        placed = {parent: above.id}
    values = rows_service.given_values(located, body)
    await rows_service.require_members(session, context, located, values)
    columns = {
        **rows_service.column_values(located, values, current=None),
        **placed,
        "name": body.name,
        **({} if body.position is None else {"position": body.position}),
    }
    row_id = await rows_service.insert(session, located, columns)
    if parent is None:
        await resource_access.grant_initial_sharing(
            session,
            context,
            located.tool,
            user=current_user,
            resource_id=row_id,
            initiative_id=placed["initiative_id"],
            payload=body,
            grants=body.grants,
        )
        await session.flush()
    await rows_service.tell_mentioned(
        session,
        located,
        row_id,
        name=body.name,
        before=None,
        after=columns,
        author=current_user,
    )
    if parent is None:
        await session.commit()
        return await _read(session, context, located, row_id)
    return await _committed(
        session, context, located, row_id, _tool_id(above), "item_added"
    )


@router.get(
    "/{kind}/{row_id}",
    response_model=PluginToolRowRead,
    name="read_plugin_tool_row",
)
async def read_plugin_tool_row(
    kind: str, row_id: int, session: ActorSessionDep, context: ToolRead
) -> PluginToolRowRead:
    """One row of a tool plug-in's tool or of one of its items."""
    tools = routed_tools(session)
    located = rows_service.located_kind(tools, kind)
    row = await rows_service.load_authorized(session, context, located, tools, row_id)
    (read,) = await rows_service.serialize(session, context, located, [row])
    return read


@router.patch(
    "/{kind}/{row_id}",
    response_model=PluginToolRowRead,
    name="update_plugin_tool_row",
)
async def update_plugin_tool_row(
    kind: str,
    row_id: int,
    body: PluginToolRowUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    context: ToolWrite,
) -> PluginToolRowRead:
    """Change a row: its name, its place and the fields sent. A counter is
    held to its bounds."""
    tools = routed_tools(session)
    located = rows_service.located_kind(tools, kind)
    row = await rows_service.load_authorized(
        session, context, located, tools, row_id, action=rows_service.writing(located)
    )
    values = rows_service.given_values(located, body)
    await rows_service.require_members(session, context, located, values)
    await rows_service.write(
        session,
        located,
        row,
        values,
        author=current_user,
        name=body.name,
        position=body.position,
    )
    return await _committed(session, context, located, row_id, _tool_id(row), "updated")


@router.post(
    "/{kind}/{row_id}/duplicate",
    response_model=PluginToolRowRead,
    status_code=status.HTTP_201_CREATED,
    name="duplicate_plugin_tool_row",
)
async def duplicate_plugin_tool_row(
    kind: str,
    row_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    context: ToolWrite,
    body: ToolDuplicateRequest | None = None,
) -> PluginToolRowRead:
    """Copy a row with every item under it, as a built-in tool's duplicate
    does: a tool's row into an initiative, its own unless the body names
    another, shared as its source is while it stays there; an item beside
    itself. Beside its source the copy is called "<name> (Copy)" unless the
    body names it."""
    body = body or ToolDuplicateRequest()
    tools = routed_tools(session)
    located = rows_service.located_kind(tools, kind)
    parent = rows_service.parent_column(located)
    source = await rows_service.load_authorized(
        session, context, located, tools, row_id, action=rows_service.writing(located)
    )
    initiative_id = body.target_initiative_id or int(source.tool["initiative_id"])
    beside = initiative_id == source.tool["initiative_id"]
    if parent is not None and not beside:
        raise rows_service.refuse_placement()
    name = (body.name or "").strip() or (
        copy_name(source.name, _NAME_LENGTH) if beside else source.name
    )
    if RESERVED_SIGILS.intersection(name):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=RESERVED_SIGIL_CODE,
        )
    columns = {"name": name, **rows_service.copy_columns(located, source)}
    if parent is not None:
        copy_id = await rows_service.insert(
            session, located, {**columns, parent: source.values[parent]}
        )
    else:
        await resource_access.require_stays_in(
            session, source.initiative_id, initiative_id
        )
        await resource_access.prepare_create(
            session, located.tool, initiative_id, current_user, context
        )
        copy_id = await rows_service.insert(
            session, located, {**columns, "initiative_id": initiative_id}
        )
        held = await rows_service.grants_of(session, located.kind, [source.id])
        await resource_access.grant_initial_sharing(
            session,
            context,
            located.tool,
            user=current_user,
            resource_id=copy_id,
            initiative_id=initiative_id,
            payload=body,
            grants=resource_access.duplicate_sharing(
                SimpleNamespace(
                    grants=held.get(source.id, []),
                    initiative_id=source.initiative_id,
                ),
                initiative_id=initiative_id,
            ),
        )
        await session.flush()
    await rows_service.carried(session, located, tools, source, copy_id)
    if parent is None:
        await session.commit()
        return await _read(session, context, located, copy_id)
    return await _committed(
        session, context, located, copy_id, _tool_id(source), "item_added"
    )


@router.post(
    "/{kind}/{row_id}/step",
    response_model=PluginToolRowRead,
    name="step_plugin_tool_row",
)
async def step_plugin_tool_row(
    kind: str,
    row_id: int,
    body: PluginToolStep,
    session: ActorSessionDep,
    context: ToolWrite,
) -> PluginToolRowRead:
    """Move one counter field of a row, named by its key: by ``by``, signed,
    or by the field's own step, up or ``down``, held within its bounds. Two
    steps landing together each count. Answers the row as it now stands."""
    tools = routed_tools(session)
    located = rows_service.located_kind(tools, kind)
    row = await rows_service.load_authorized(
        session, context, located, tools, row_id, action=rows_service.writing(located)
    )
    await rows_service.step(
        session, located, row.id, body.field, by=body.by, down=body.down
    )
    return await _committed(session, context, located, row_id, _tool_id(row), "updated")


@router.post(
    "/{kind}/{row_id}/actions/{action_id}",
    response_model=PluginToolRowRead,
    name="run_plugin_tool_action",
)
async def run_plugin_tool_action(
    kind: str,
    row_id: int,
    action_id: str,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    context: ToolWrite,
    body: PluginToolActionRun | None = None,
) -> PluginToolRowRead:
    """Run one of the tool's actions on a row, with the answers to its
    ``params``. Its change is made as the caller would make it by hand, all of
    it or none, and the row is answered as it now stands."""
    tools = routed_tools(session)
    located = rows_service.located_kind(tools, kind)
    row = await rows_service.load_authorized(
        session, context, located, tools, row_id, action=rows_service.writing(located)
    )
    await rows_service.run_action(
        session,
        context,
        located,
        tools,
        row,
        action_id,
        body or PluginToolActionRun(),
        author=current_user,
    )
    return await _committed(session, context, located, row_id, _tool_id(row), "updated")


@router.websocket("/{kind}/{row_id}/ws")
async def plugin_tool_stream(
    websocket: WebSocket, guild_id: CommunityIdPath, kind: str, row_id: int
) -> None:
    """Change signals for one row of a tool plug-in's tool: ``{type, id,
    timestamp}`` frames and a heartbeat. The client refetches on each; see
    ``serve_tool_stream``."""
    await serve_tool_stream(websocket, guild_id, kind, row_id)
