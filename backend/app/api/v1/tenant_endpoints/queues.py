"""Queue endpoints — CRUD, turn management, item management, and DAC permissions.

Initiative-scoped queues for turn/priority tracking (e.g., TTRPG initiative order).
"""

from datetime import datetime, timezone
from typing import Annotated, Optional, cast

import logging

from fastapi import (
    APIRouter,
    Depends,
    WebSocket,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import routed_guild_id
from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.services.tenant import metadata as metadata_service
from app.services.tenant import attachments as attachments_service
from app.services.tenant import overwrites
from app.services.tenant import relationships
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
from app.models.tenant.queue import (
    Queue,
    QueueItem,
)
from app.models.platform.user import User
from app.schemas.tenant.queue import (
    QueueCreate,
    QueueUpdate,
    QueueRead,
    QueueItemCreate,
    QueueItemUpdate,
    QueueItemRead,
    QueueReleaseRequest,
    active_items,
    serialize_queue,
    serialize_queue_item,
)
from app.api import resource_access, tool_copy
from app.core.tools import Tool
from app.db.session import require_actor_context
from app.services.tenant import queues as queues_service
from app.services.tenant import named_people
from app.services.tenant import tags as tags_service
from app.services.content_sockets import sockets
from app.api.content_socket import serve_tool_stream


async def _serialized_queue(
    session: AsyncSession, queue: Queue, *, user_id: int | None
) -> QueueRead:
    """A queue and its items, each with how many things are pinned to it,
    counted for the whole page in one query."""
    counts = await relationships.counts_for_many(
        session,
        SearchEntityType.queue_item,
        [item.id for item in active_items(queue)],
        relationship_type=RelationshipType.attached,
    )
    return serialize_queue(
        queue,
        context=require_actor_context(session),
        user_id=user_id,
        attachment_counts=counts,
    )


async def _serialized_queue_item(
    session: AsyncSession, item: QueueItem
) -> QueueItemRead:
    counts = await relationships.counts_for_many(
        session,
        SearchEntityType.queue_item,
        [item.id],
        relationship_type=RelationshipType.attached,
    )
    return serialize_queue_item(item, attachment_count=counts.get(item.id, 0))


router = APIRouter(route_class=ActorRoute)

#: An item by its own id, mounted at the guild root. An event envelope names
#: ``(resource_type, id)`` and nothing else, so the resource has to be
#: addressable by its own id — a nested path would need a parent the envelope
#: never carries. Only adding one names its queue.
items_router = APIRouter(route_class=ActorRoute)


logger = logging.getLogger(__name__)

#: The routes an installed plug-in may call, under the queues scopes. A queue's
#: items and its turn commands answer to the queue's own scopes.
QueuesRead = Annotated[ActorContext, Depends(plugin_scope("queues:read"))]
QueuesWrite = Annotated[ActorContext, Depends(plugin_scope("queues:write"))]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


async def read_after_write(
    session: RLSSessionDep,
    queue_id: int,
    user: Optional[User],
    guild_context: ActorContext,
) -> QueueRead:
    """The queue a write answers with: re-read after the commit, serialized.

    Registered in ``tool_lists.TOOL_LISTS`` so the shared sharing route
    (``tool_grants.py``) answers in this tool's own shape. ``populate_existing``
    because the session keeps what it loaded before the commit.
    """
    queue = await queues_service.get_queue_hydrated(
        session, queue_id, populate_existing=True
    )
    if not queue:
        raise Tool.queue.not_found()
    return await _serialized_queue(session, queue, user_id=guild_context.user_id)


async def _queue_committed(
    session: RLSSessionDep,
    queue_id: int,
    user: Optional[User],
    guild_context: ActorContext,
    event: str,
) -> QueueRead:
    """Commit a write to the queue, tell its room ``event``, and answer with it."""
    await session.commit()
    sockets.signal(routed_guild_id(session), Tool.queue, queue_id, event)
    return await read_after_write(session, queue_id, user, guild_context)


async def _item_committed(
    session: RLSSessionDep, item: QueueItem, event: str
) -> QueueItemRead:
    """Commit a write to an item, tell its queue's room ``event``, and answer
    with the item re-read."""
    await session.commit()
    sockets.signal(routed_guild_id(session), Tool.queue, item.queue_id, event)
    hydrated = await resource_access.reload_child(session, QueueItem, item.id)
    return await _serialized_queue_item(session, hydrated)


# ---------------------------------------------------------------------------
# Queue CRUD
# ---------------------------------------------------------------------------


@items_router.get("/queue-items/{item_id}", response_model=QueueItemRead)
async def read_queue_item(
    item_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesRead,
    include_deleted: IncludeDeletedDep = False,
) -> QueueItemRead:
    """One queue item by id — the read-back for a ``queue_items.*`` event.

    Gated by read access on the queue it belongs to, like listing it. The item's
    own id is the whole address, so there is no parent to mismatch.
    """
    item = await resource_access.load_child(session, QueueItem, item_id)
    return await _serialized_queue_item(session, item)


@items_router.post(
    "/queue-items/{item_id}/duplicate",
    response_model=QueueItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_queue_item(
    item_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesWrite,
) -> QueueItemRead:
    """Copy the item beside itself, at the same place in the turn order, as
    "<label> (Copy)", with its person, tags, links and properties."""
    item = await resource_access.load_child(session, QueueItem, item_id, access="write")
    queue = item.queue
    named = {item.user_id} if item.user_id is not None else set()
    keep = await named_people.readers(
        session, named_people.Governing.of(Tool.queue, queue), named
    )
    copy = await tool_copy.duplicate_child(
        session, item, user_id=item.user_id if item.user_id in keep else None
    )
    return await _item_committed(session, copy, "item_added")


@router.get("/{queue_id}", response_model=QueueRead)
async def read_queue(
    queue_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesRead,
    include_deleted: IncludeDeletedDep = False,
) -> QueueRead:
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, hydrated=True
    )
    return await _serialized_queue(session, queue, user_id=guild_context.user_id)


@router.post("/", response_model=QueueRead, status_code=status.HTTP_201_CREATED)
async def create_queue(
    queue_in: QueueCreate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesWrite,
) -> QueueRead:
    """Create a new queue in an initiative.

    Requires create_queues permission on the initiative (or guild admin).
    The creator automatically gets owner-level permission.
    """
    resource_access.refuse_plugin_sharing(guild_context, queue_in, "grants")
    initiative = await resource_access.prepare_create(
        session, Tool.queue, queue_in.initiative_id, current_user, guild_context
    )

    queue = Queue(
        initiative_id=initiative.id,
        created_by=guild_context.user_id,
        name=queue_in.name,
        description=queue_in.description,
    )
    session.add(queue)
    await session.flush()

    await resource_access.grant_initial_sharing(
        session,
        guild_context,
        Tool.queue,
        user=current_user,
        resource_id=queue.id,
        initiative_id=queue.initiative_id,
        payload=queue_in,
        grants=queue_in.grants,
    )
    await attachments_service.claim_uploads(session, queue)
    await metadata_service.write_on_create(session, queue, queue_in.properties)
    await session.commit()
    return await read_after_write(session, queue.id, current_user, guild_context)


@router.patch("/{queue_id}", response_model=QueueRead)
async def update_queue(
    queue_id: int,
    queue_in: QueueUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesWrite,
) -> QueueRead:
    """Update queue name/description. Requires write access."""
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    for field, value in queue_in.model_dump(exclude_unset=True).items():
        setattr(queue, field, value)
    queue.updated_at = datetime.now(timezone.utc)
    session.add(queue)
    await attachments_service.claim_uploads(session, queue)
    return await _queue_committed(
        session, queue_id, current_user, guild_context, "queue_updated"
    )


# ---------------------------------------------------------------------------
# Queue Items
# ---------------------------------------------------------------------------


@router.post(
    "/{queue_id}/items",
    response_model=QueueItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_queue_item(
    queue_id: int,
    item_in: QueueItemCreate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesWrite,
) -> QueueItemRead:
    """Add an item to a queue. Requires write access."""
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    if item_in.user_id is not None:
        await named_people.require_readers(
            session, named_people.Governing.of(Tool.queue, queue), [item_in.user_id]
        )

    item = QueueItem(
        queue_id=queue.id,
        label=item_in.label,
        position=item_in.position,
        user_id=item_in.user_id,
        color=item_in.color,
        notes=item_in.notes,
        is_visible=item_in.is_visible,
    )
    session.add(item)
    await session.flush()

    # Set tags if provided
    if item_in.tag_ids:
        await tags_service.set_entity_tags(
            session,
            tags_service.TAG_LINKS["queue_item"],
            guild_id=routed_guild_id(session),
            entity_id=item.id,
            tag_ids=item_in.tag_ids,
        )

    if item_in.task_ids:
        await relationships.set_related(
            session,
            relationships.Endpoint(SearchEntityType.queue_item, item.id),
            relationship_type=RelationshipType.attached,
            other_kind=SearchEntityType.task,
            ids=item_in.task_ids,
            user_id=guild_context.user_id,
        )

    await attachments_service.claim_uploads(session, item)
    await metadata_service.write_on_create(session, item, item_in.properties)
    return await _item_committed(session, item, "item_added")


@items_router.patch("/queue-items/{item_id}", response_model=QueueItemRead)
async def update_queue_item(
    item_id: int,
    item_in: QueueItemUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesWrite,
) -> QueueItemRead:
    """Update a queue item. Requires write access on the queue."""
    item = await resource_access.load_child(session, QueueItem, item_id, access="write")
    if "notes_base" in item_in.model_fields_set:
        await overwrites.refuse_written_over(session, item, "notes", item_in.notes_base)
    update_data = item_in.model_dump(
        exclude_unset=True, exclude={"tag_ids", "properties", "notes_base"}
    )
    if update_data.get("user_id") is not None:
        await named_people.require_readers(
            session,
            named_people.Governing.of(Tool.queue, item.queue),
            [update_data["user_id"]],
        )
    for field, value in update_data.items():
        setattr(item, field, value)
    if item_in.tag_ids is not None:
        await tags_service.set_entity_tags(
            session,
            tags_service.TAG_LINKS["queue_item"],
            guild_id=routed_guild_id(session),
            entity_id=item.id,
            tag_ids=item_in.tag_ids,
        )
    if item_in.properties is not None:
        await metadata_service.write_on_update(session, item, item_in.properties)
    session.add(item)
    await attachments_service.claim_uploads(session, item)
    return await _item_committed(session, item, "item_updated")


@items_router.delete("/queue-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_queue_item(
    item_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Soft-delete a queue item. Requires write access on the parent queue."""
    from app.services.tenant.soft_delete import trash

    item = await resource_access.load_child(session, QueueItem, item_id, access="write")
    queue = cast(Queue, item.queue)

    if queue.current_item_id == item.id:
        queue.current_item_id = None
        session.add(queue)

    await trash(session, item, deleted_by_user_id=guild_context.user_id)
    await session.commit()
    sockets.signal(routed_guild_id(session), Tool.queue, queue.id, "item_removed")


# ---------------------------------------------------------------------------
# Turn Management
# ---------------------------------------------------------------------------


@router.post("/{queue_id}/start", response_model=QueueRead)
async def start_queue(
    queue_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesWrite,
) -> QueueRead:
    """Start the queue: set active, reset to first item, round 1."""
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    await queues_service.start_queue(session, queue)
    return await _queue_committed(
        session, queue_id, current_user, guild_context, "queue_started"
    )


@router.post("/{queue_id}/stop", response_model=QueueRead)
async def stop_queue(
    queue_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesWrite,
) -> QueueRead:
    """Stop the queue: set inactive but keep current position."""
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    await queues_service.stop_queue(session, queue)
    return await _queue_committed(
        session, queue_id, current_user, guild_context, "queue_stopped"
    )


@router.post("/{queue_id}/next", response_model=QueueRead)
async def advance_turn(
    queue_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesWrite,
) -> QueueRead:
    """Advance to the next visible item. Wraps around and increments round."""
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    await queues_service.advance_turn(session, queue)
    return await _queue_committed(
        session, queue_id, current_user, guild_context, "turn_advance"
    )


@router.post("/{queue_id}/previous", response_model=QueueRead)
async def previous_turn(
    queue_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesWrite,
) -> QueueRead:
    """Move to the previous visible item. Wraps around and decrements round."""
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    await queues_service.previous_turn(session, queue)
    return await _queue_committed(
        session, queue_id, current_user, guild_context, "turn_previous"
    )


@router.post("/{queue_id}/set-active/{item_id}", response_model=QueueRead)
async def set_active_item(
    queue_id: int,
    item_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesWrite,
) -> QueueRead:
    """Jump to a specific item in the queue."""
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    await queues_service.set_active_item(session, queue, item_id)
    return await _queue_committed(
        session, queue_id, current_user, guild_context, "turn_set_active"
    )


@router.post("/{queue_id}/reset", response_model=QueueRead)
async def reset_queue(
    queue_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesWrite,
) -> QueueRead:
    """Reset the queue to round 1, first visible item."""
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    await queues_service.reset_queue(session, queue)
    return await _queue_committed(
        session, queue_id, current_user, guild_context, "queue_reset"
    )


@router.post("/{queue_id}/hold", response_model=QueueRead)
async def hold_current_turn(
    queue_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesWrite,
) -> QueueRead:
    """Hold the current turn — the item leaves the rotation until it acts.

    The held item is recorded with the current round; the rotation
    auto-releases it when its natural position-desc slot comes back around in
    a later round. Users can also call ``/release/{item_id}`` to act sooner.
    """
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    await queues_service.hold_current(session, queue)
    return await _queue_committed(
        session, queue_id, current_user, guild_context, "turn_held"
    )


@router.post("/{queue_id}/release/{item_id}", response_model=QueueRead)
async def release_held_item(
    queue_id: int,
    item_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesWrite,
    options: QueueReleaseRequest = QueueReleaseRequest(),  # noqa: B008
) -> QueueRead:
    """Release a held item back into the rotation.

    Clears ``held_at_round`` on the target so it rejoins the active rotation.
    The rotation pointer is unchanged, so this doesn't pull current back onto
    items that already took their turn this round.

    When ``options.reposition`` is True (PF2e Delay semantics), the released
    item's ``position`` is rewritten to land just after the current item in
    turn order — the new initiative slot persists for the rest of the
    encounter. Default ``False`` keeps the released item at its original
    position so it acts at its natural slot next time the rotation reaches
    it.
    """
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    await queues_service.release_held(
        session, queue, item_id, reposition=options.reposition
    )
    return await _queue_committed(
        session, queue_id, current_user, guild_context, "turn_released"
    )


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


@router.websocket("/{queue_id}/ws")
async def websocket_queue(
    websocket: WebSocket, guild_id: CommunityIdPath, queue_id: int
) -> None:
    """Change signals for one queue: ``{type, id, timestamp}`` frames and a
    heartbeat. The client refetches on each; see ``serve_tool_stream``."""
    await serve_tool_stream(websocket, guild_id, Tool.queue, queue_id)
