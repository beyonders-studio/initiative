"""Counter group endpoints — CRUD, value operations, permissions, WebSocket."""

from datetime import datetime, timezone
from typing import Annotated, Optional

import logging

from sqlmodel.ext.asyncio.session import AsyncSession
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    status,
)


from app.db.session import routed_guild_id
from app.api.actor_route import ActorRoute
from app.api.deps import (
    CommunityIdPath,
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    GuildContextDep,
    IncludeDeletedDep,
    RLSSessionDep,
    get_current_active_user,
    plugin_scope,
)
from app.models.tenant.counter import (
    Counter,
    CounterGroup,
)
from app.models.platform.user import User
from app.schemas.tenant.counter import (
    CounterCreate,
    CounterGroupCreate,
    CounterGroupRead,
    CounterGroupUpdate,
    CounterRead,
    CounterSetCountRequest,
    CounterStepRequest,
    CounterSortRequest,
    CounterUpdate,
    serialize_counter,
    _validate_counter_constraints,
)
from app.schemas.tenant.tool import serialize_tool
from app.services.tenant import metadata as metadata_service
from app.services.tenant import attachments as attachments_service
from app.services.tenant import counters as counters_service
from app.api import resource_access, tool_copy
from app.core.tools import Tool
from app.services.content_sockets import sockets
from app.api.content_socket import serve_tool_stream


router = APIRouter(route_class=ActorRoute)

#: A counter by its own id, mounted at the guild root. An event envelope names
#: ``(resource_type, id)`` and nothing else, so the counter has to be
#: addressable by its own id — a nested path would need a parent the envelope
#: never carries. Only adding one names its group.
counters_router = APIRouter(route_class=ActorRoute)
logger = logging.getLogger(__name__)

#: The routes an installed plug-in may call, under the counter groups scopes. A
#: group's counters and their commands answer to the group's own scopes.
CounterGroupsRead = Annotated[
    ActorContext, Depends(plugin_scope("counter_groups:read"))
]
CounterGroupsWrite = Annotated[
    ActorContext, Depends(plugin_scope("counter_groups:write"))
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def read_after_write(
    session: RLSSessionDep,
    group_id: int,
    user: Optional[User],
    guild_context: ActorContext,
) -> CounterGroupRead:
    """The counter group a write answers with: re-read after the commit,
    serialized.

    Registered in ``tool_lists.TOOL_LISTS`` so the shared sharing route
    (``tool_grants.py``) answers in this tool's own shape. ``populate_existing``
    because the session keeps what it loaded before the commit.
    """
    group = await counters_service.get_counter_group(
        session, group_id, populate_existing=True
    )
    if not group:
        raise Tool.counter_group.not_found()
    return serialize_tool(
        CounterGroupRead, group, user_id=guild_context.user_id, context=guild_context
    )


async def _group_committed(
    session: RLSSessionDep,
    group_id: int,
    user: Optional[User],
    guild_context: ActorContext,
    event: str,
) -> CounterGroupRead:
    """Commit a write to the group, tell its room ``event``, and answer with it."""
    await session.commit()
    sockets.signal(routed_guild_id(session), Tool.counter_group, group_id, event)
    return await read_after_write(session, group_id, user, guild_context)


async def _counter_committed(
    session: RLSSessionDep, counter: Counter, event: str, *, context: ActorContext
) -> CounterRead:
    """Commit a write to a counter, tell its group's room ``event``, and
    answer with the counter re-read."""
    await session.commit()
    sockets.signal(
        routed_guild_id(session), Tool.counter_group, counter.counter_group_id, event
    )
    hydrated = await resource_access.reload_child(session, Counter, counter.id)
    return await _serialized_counter(session, hydrated, context)


async def _serialized_counter(
    session: AsyncSession, counter: Counter, context: ActorContext
) -> CounterRead:
    """One counter as its own read answers it."""
    return serialize_counter(counter, context=context)


# ---------------------------------------------------------------------------
# Counter Group CRUD
# ---------------------------------------------------------------------------


@router.get("/{group_id}", response_model=CounterGroupRead)
async def read_counter_group(
    group_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CounterGroupsRead,
    include_deleted: IncludeDeletedDep = False,
) -> CounterGroupRead:
    group = await resource_access.load_authorized(
        session, Tool.counter_group, group_id, current_user, guild_context
    )
    return serialize_tool(
        CounterGroupRead,
        group,
        user_id=guild_context.user_id,
        context=guild_context,
    )


@router.post("/", response_model=CounterGroupRead, status_code=status.HTTP_201_CREATED)
async def create_counter_group(
    group_in: CounterGroupCreate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CounterGroupsWrite,
) -> CounterGroupRead:
    resource_access.refuse_plugin_sharing(guild_context, group_in, "grants")
    initiative = await resource_access.prepare_create(
        session, Tool.counter_group, group_in.initiative_id, current_user, guild_context
    )

    group = CounterGroup(
        initiative_id=initiative.id,
        created_by=guild_context.user_id,
        name=group_in.name,
        description=group_in.description,
    )
    session.add(group)
    await session.flush()
    await resource_access.grant_initial_sharing(
        session,
        guild_context,
        Tool.counter_group,
        user=current_user,
        resource_id=group.id,
        initiative_id=group.initiative_id,
        payload=group_in,
        grants=group_in.grants,
    )
    await attachments_service.claim_uploads(session, group)
    await metadata_service.write_on_create(session, group, group_in.properties)
    await session.commit()
    return await read_after_write(session, group.id, current_user, guild_context)


@router.patch("/{group_id}", response_model=CounterGroupRead)
async def update_counter_group(
    group_id: int,
    group_in: CounterGroupUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CounterGroupsWrite,
) -> CounterGroupRead:
    group = await resource_access.load_authorized(
        session,
        Tool.counter_group,
        group_id,
        current_user,
        guild_context,
        access="write",
    )
    for field, value in group_in.model_dump(exclude_unset=True).items():
        setattr(group, field, value)
    group.updated_at = datetime.now(timezone.utc)
    session.add(group)
    await attachments_service.claim_uploads(session, group)
    return await _group_committed(
        session, group_id, current_user, guild_context, "group_updated"
    )


# ---------------------------------------------------------------------------
# Counters CRUD
# ---------------------------------------------------------------------------


@router.post(
    "/{group_id}/counters",
    response_model=CounterRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_counter(
    group_id: int,
    counter_in: CounterCreate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CounterGroupsWrite,
) -> CounterRead:
    group = await resource_access.load_authorized(
        session,
        Tool.counter_group,
        group_id,
        current_user,
        guild_context,
        access="write",
    )

    clamped = counters_service.clamp(counter_in.count, counter_in.min, counter_in.max)
    clamped_initial = counters_service.clamp(
        counter_in.initial_count, counter_in.min, counter_in.max
    )

    counter = Counter(
        counter_group_id=group.id,
        name=counter_in.name,
        color=counter_in.color,
        count=clamped,
        min=counter_in.min,
        max=counter_in.max,
        step=counter_in.step,
        initial_count=clamped_initial,
        view_mode=counter_in.view_mode,
        position=counter_in.position,
    )
    session.add(counter)
    await metadata_service.write_on_create(session, counter, counter_in.properties)
    return await _counter_committed(
        session, counter, "counter_added", context=guild_context
    )


@counters_router.patch("/counters/{counter_id}", response_model=CounterRead)
async def update_counter(
    counter_id: int,
    counter_in: CounterUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CounterGroupsWrite,
) -> CounterRead:
    counter = await resource_access.load_child(
        session, Counter, counter_id, access="write"
    )

    update_data = counter_in.model_dump(exclude_unset=True)
    try:
        _validate_counter_constraints(
            view_mode=update_data.get("view_mode", counter.view_mode),
            min_value=update_data.get("min", counter.min),
            max_value=update_data.get("max", counter.max),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        )

    for field, value in update_data.items():
        setattr(counter, field, value)
    # Re-clamp count and initial_count to the new bounds
    counter.count = counters_service.clamp(counter.count, counter.min, counter.max)
    counter.initial_count = counters_service.clamp(
        counter.initial_count, counter.min, counter.max
    )
    counter.updated_at = datetime.now(timezone.utc)
    session.add(counter)
    return await _counter_committed(
        session, counter, "counter_updated", context=guild_context
    )


@counters_router.delete(
    "/counters/{counter_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_counter(
    counter_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    from app.services.tenant.soft_delete import trash

    counter = await resource_access.load_child(
        session, Counter, counter_id, access="write"
    )
    await trash(session, counter, deleted_by_user_id=guild_context.user_id)
    await session.commit()
    sockets.signal(
        routed_guild_id(session),
        Tool.counter_group,
        counter.counter_group_id,
        "counter_removed",
    )


# ---------------------------------------------------------------------------
# Counter value operations
# ---------------------------------------------------------------------------


@counters_router.get("/counters/{counter_id}", response_model=CounterRead)
async def read_counter(
    counter_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CounterGroupsRead,
    include_deleted: IncludeDeletedDep = False,
) -> CounterRead:
    """One counter by id — the read-back for a ``counters.*`` event.

    Gated by read access on the group it belongs to, like reading the group.
    The counter's own id is the whole address, so there is no parent to
    mismatch — and no hand-written deleted check to contradict the request,
    which is what a read-back after a delete depends on.
    """
    counter = await resource_access.load_child(session, Counter, counter_id)
    return await _serialized_counter(session, counter, guild_context)


@counters_router.post(
    "/counters/{counter_id}/duplicate",
    response_model=CounterRead,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_counter(
    counter_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CounterGroupsWrite,
) -> CounterRead:
    """Copy the counter to the end of its group as "<name> (Copy)", with its
    count and properties."""
    counter = await resource_access.load_child(
        session, Counter, counter_id, access="write"
    )
    copy = await tool_copy.duplicate_child(
        session,
        counter,
        position=await counters_service.next_position(
            session, counter.counter_group_id
        ),
    )
    return await _counter_committed(
        session, copy, "counter_added", context=guild_context
    )


@counters_router.post("/counters/{counter_id}/set", response_model=CounterRead)
async def set_counter_count(
    counter_id: int,
    payload: CounterSetCountRequest,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CounterGroupsWrite,
) -> CounterRead:
    """Put a counter at a number, held within its bounds."""
    counter = await resource_access.load_child(
        session, Counter, counter_id, access="write"
    )
    await counters_service.set_count(session, counter, payload.count)
    return await _counter_committed(
        session, counter, "count_changed", context=guild_context
    )


@counters_router.post("/counters/{counter_id}/step", response_model=CounterRead)
async def step_counter(
    counter_id: int,
    payload: CounterStepRequest,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CounterGroupsWrite,
) -> CounterRead:
    """Move a counter up or down, by ``amount`` or by its own step, held within
    its bounds. Two steps landing together each count."""
    counter = await resource_access.load_child(
        session, Counter, counter_id, access="write"
    )
    await counters_service.step_counter(
        session, counter.id, up=payload.direction == "up", amount=payload.amount
    )
    return await _counter_committed(
        session, counter, "count_changed", context=guild_context
    )


@counters_router.post("/counters/{counter_id}/reset", response_model=CounterRead)
async def reset_counter(
    counter_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CounterGroupsWrite,
) -> CounterRead:
    """Put a counter back to the value it starts from."""
    counter = await resource_access.load_child(
        session, Counter, counter_id, access="write"
    )
    await counters_service.reset_counter(session, counter)
    return await _counter_committed(
        session, counter, "count_changed", context=guild_context
    )


@router.post("/{group_id}/reset-all", response_model=CounterGroupRead)
async def reset_all_counters(
    group_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CounterGroupsWrite,
) -> CounterGroupRead:
    group = await resource_access.load_authorized(
        session,
        Tool.counter_group,
        group_id,
        current_user,
        guild_context,
        access="write",
    )
    await counters_service.reset_all_counters(session, group)
    return await _group_committed(
        session, group_id, current_user, guild_context, "counters_reset"
    )


@router.post("/{group_id}/sort", response_model=CounterGroupRead)
async def sort_counters(
    group_id: int,
    payload: CounterSortRequest,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CounterGroupsWrite,
) -> CounterGroupRead:
    group = await resource_access.load_authorized(
        session,
        Tool.counter_group,
        group_id,
        current_user,
        guild_context,
        access="write",
    )
    await counters_service.sort_counters(
        session, group, field=payload.field, direction=payload.direction
    )
    return await _group_committed(
        session, group_id, current_user, guild_context, "counters_reordered"
    )


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


@router.websocket("/{group_id}/ws")
async def websocket_counter_group(
    websocket: WebSocket, guild_id: CommunityIdPath, group_id: int
) -> None:
    """Change signals for one counter group: ``{type, id, timestamp}`` frames and a
    heartbeat. The client refetches on each; see ``serve_tool_stream``."""
    await serve_tool_stream(websocket, guild_id, Tool.counter_group, group_id)
