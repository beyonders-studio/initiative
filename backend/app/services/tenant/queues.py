"""Queue service layer — queue and queue-item fetching with eager-loaded
relationships, and turn management (advance, previous, start, stop, reset, set
active item)."""

from datetime import datetime, timezone
from typing import Sequence

from fastapi import HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import selectinload, undefer
from sqlmodel import select

from app.core.tools import KINDS
from app.core.messages import QueueMessages
from app.db.query import ids_in
from app.models.tenant.queue import (
    Queue,
    QueueItem,
)
from app.schemas.tenant.queue import QueueTurnPreview
from app.services.permissions import with_tool
from app.services.tenant import metadata as metadata_service
from app.services.tenant import tags as tags_service


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def list_loader_options() -> list:
    """Eager-load what a queue *list* row needs: its sharing and the level the
    request holds on it. Lighter than :func:`get_queue`, which also loads the
    items the turn commands walk."""
    return [
        selectinload(Queue.grants),
        selectinload(Queue.initiative),
        undefer(Queue.actions),
    ]


async def get_queue(
    session: AsyncSession,
    queue_id: int,
    *,
    populate_existing: bool = False,
) -> Queue | None:
    """Fetch a queue with what authorizing it, the grant flow and the turn
    commands read: its sharing, its level and its items."""
    stmt = (
        select(Queue)
        .where(Queue.id == queue_id)
        .options(*list_loader_options(), selectinload(Queue.items))
        .execution_options(populate_existing=populate_existing)
    )
    return (await session.exec(stmt)).one_or_none()


async def get_queue_hydrated(
    session: AsyncSession,
    queue_id: int,
    *,
    populate_existing: bool = False,
) -> Queue | None:
    """Fetch a queue with everything a serialized ``QueueRead`` reads: what
    :func:`get_queue` loads, each item's person, and the tags and properties
    of the queue and its items."""
    stmt = (
        select(Queue)
        .where(Queue.id == queue_id)
        .options(
            *list_loader_options(),
            selectinload(Queue.items).selectinload(QueueItem.user),
        )
        .execution_options(populate_existing=populate_existing)
    )
    queue = (await session.exec(stmt)).one_or_none()
    if queue is not None:
        await tags_service.annotate_tags(session, [queue])
        await metadata_service.annotate_properties(session, [queue])
        await tags_service.annotate_tags(session, queue.items)
        await metadata_service.annotate_properties(session, queue.items)
    return queue


async def get_queue_item(
    session: AsyncSession,
    item_id: int,
    *,
    populate_existing: bool = False,
) -> QueueItem | None:
    """Fetch a queue item with its person, tags and properties, and its queue
    as authorizing it reads it."""
    stmt = (
        select(QueueItem)
        .where(QueueItem.id == item_id)
        .options(
            selectinload(QueueItem.user),
            with_tool(QueueItem.queue),
        )
    )
    if populate_existing:
        stmt = stmt.execution_options(populate_existing=True)
    result = await session.exec(stmt)
    item = result.one_or_none()
    if item is not None:
        await tags_service.annotate_tags(session, [item])
        await metadata_service.annotate_properties(session, [item])
    return item


#: Turns a list's card shows for each queue: whoever is up and who follows.
PREVIEW_TURNS = 3


async def list_previews(
    session: AsyncSession, queues: Sequence[Queue]
) -> dict[int, list[QueueTurnPreview]]:
    """Whose turn it is and who follows, for every queue on a list's page, read
    in one statement for the whole page.

    The turns after the current one are walked the way :func:`advance_turn`
    walks them: a held item is passed over until its round comes due, and is
    then the turn it would be. A queue not running shows its order from the
    top, without the held. Hidden items are out of the rotation either way."""
    by_id = {queue.id: queue for queue in queues if queue.id is not None}
    if not by_id:
        return {}
    rows = await session.exec(
        select(
            QueueItem.id,
            QueueItem.queue_id,
            QueueItem.label,
            QueueItem.color,
            QueueItem.held_at_round,
        )
        .where(
            ids_in(QueueItem.queue_id, list(by_id)),
            QueueItem.deleted_at.is_(None),
            QueueItem.is_visible.is_(True),
        )
        .order_by(QueueItem.queue_id, QueueItem.position.desc(), QueueItem.id)
    )
    visible: dict[int, list] = {queue_id: [] for queue_id in by_id}
    for row in rows.all():
        visible[row.queue_id].append(row)

    def turn(row, current: bool = False) -> QueueTurnPreview:
        return QueueTurnPreview(
            id=row.id, label=row.label, color=row.color, current=current
        )

    previews: dict[int, list[QueueTurnPreview]] = {}
    for queue_id, order in visible.items():
        queue = by_id[queue_id]
        at = next(
            (
                index
                for index, row in enumerate(order)
                if queue.is_active and row.id == queue.current_item_id
            ),
            None,
        )
        if at is None:
            previews[queue_id] = [
                turn(row) for row in order if row.held_at_round is None
            ][:PREVIEW_TURNS]
            continue
        turns = [turn(order[at], current=True)]
        round_ = queue.current_round
        for step in range(1, len(order)):
            index = (at + step) % len(order)
            if index == 0:
                round_ += 1
            row = order[index]
            if row.held_at_round is None or row.held_at_round < round_:
                turns.append(turn(row))
            if len(turns) == PREVIEW_TURNS:
                break
        previews[queue_id] = turns
    return previews


# ---------------------------------------------------------------------------
# Turn management
# ---------------------------------------------------------------------------


def _visible_items_desc(queue: Queue) -> list[QueueItem]:
    """Return visible items sorted by position descending (highest first).

    Includes held items — the rotation logic in ``advance_turn`` walks the
    visible list directly so it can auto-release held items whose due slot
    has come up. Functions that want the *active* (non-held) rotation use
    :func:`_active_rotation_desc` instead.
    """
    items = getattr(queue, "items", None) or []
    return sorted(
        [item for item in items if item.is_visible],
        key=lambda item: item.position,
        reverse=True,
    )


def _active_rotation_desc(queue: Queue) -> list[QueueItem]:
    """Return rotation-eligible items (visible AND not held), position desc.

    Used by ``previous_turn``, ``start_queue``, ``reset_queue`` to land on
    items that are currently in the rotation. ``advance_turn`` and the
    hold/release helpers iterate over :func:`_visible_items_desc` instead
    because they have to consider held items for auto-release.
    """
    return [item for item in _visible_items_desc(queue) if item.held_at_round is None]


async def advance_turn(session: AsyncSession, queue: Queue) -> Queue:
    """Advance to the next rotation slot, auto-releasing any held item due.

    Walks visible items in position-desc order (with round wrap). A candidate
    that's held with ``held_at_round < new_current_round`` is auto-released
    (``held_at_round`` cleared) and becomes the current turn — so a held
    participant whose natural slot has come back around isn't silently
    skipped forever. Held items whose due round hasn't arrived are skipped.
    Mirrors the algorithm in ``advanceQueueState`` (frontend).
    """
    visible = _visible_items_desc(queue)
    if not visible:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueueMessages.NO_ITEMS,
        )

    # Locate the current item within the visible list (held or not).
    current_idx: int | None = None
    if queue.current_item_id is not None:
        for idx, item in enumerate(visible):
            if item.id == queue.current_item_id:
                current_idx = idx
                break

    idx = current_idx if current_idx is not None else -1
    round_ = queue.current_round
    # Cap iterations defensively; the only natural terminator is "found a
    # rotation-eligible candidate" or "every held item has a future due
    # round" (which would be a pathological state).
    for _ in range(len(visible) * 2 + 1):
        next_idx = (idx + 1) % len(visible)
        wrapped = next_idx == 0 and current_idx is not None
        if wrapped:
            round_ += 1
        candidate = visible[next_idx]
        if candidate.held_at_round is None:
            queue.current_item_id = candidate.id
            queue.current_round = round_
            queue.updated_at = datetime.now(timezone.utc)
            session.add(queue)
            return queue
        if candidate.held_at_round < round_:
            # Due: auto-release and act now.
            candidate.held_at_round = None
            session.add(candidate)
            queue.current_item_id = candidate.id
            queue.current_round = round_
            queue.updated_at = datetime.now(timezone.utc)
            session.add(queue)
            return queue
        # Held and not yet due — skip past it.
        idx = next_idx
        current_idx = next_idx  # subsequent wraps should bump round

    # Every item in the rotation is held and not yet due. Clear current and
    # leave the round where we landed; user can release manually.
    queue.current_item_id = None
    queue.current_round = round_
    queue.updated_at = datetime.now(timezone.utc)
    session.add(queue)
    return queue


async def previous_turn(session: AsyncSession, queue: Queue) -> Queue:
    """Move to the previous rotation-eligible item by position (descending).

    Held items are skipped without auto-release — auto-release is a forward-
    time effect of :func:`advance_turn` only. Wraps to the last and
    decrements ``current_round`` (minimum 1).
    """
    rotation = _active_rotation_desc(queue)
    if not rotation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueueMessages.NO_ITEMS,
        )

    current_idx: int | None = None
    if queue.current_item_id is not None:
        for idx, item in enumerate(rotation):
            if item.id == queue.current_item_id:
                current_idx = idx
                break

    if current_idx is None or current_idx <= 0:
        queue.current_item_id = rotation[-1].id
        queue.current_round = max(1, queue.current_round - 1)
    else:
        queue.current_item_id = rotation[current_idx - 1].id

    queue.updated_at = datetime.now(timezone.utc)
    session.add(queue)
    return queue


async def start_queue(session: AsyncSession, queue: Queue) -> Queue:
    """Start the queue: set is_active=True, reset to first rotation item, round 1."""
    rotation = _active_rotation_desc(queue)
    if not rotation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueueMessages.NO_ITEMS,
        )

    queue.is_active = True
    queue.current_item_id = rotation[0].id
    queue.current_round = 1
    queue.updated_at = datetime.now(timezone.utc)
    session.add(queue)
    return queue


async def stop_queue(session: AsyncSession, queue: Queue) -> Queue:
    """Stop the queue: set is_active=False but keep current position."""
    queue.is_active = False
    queue.updated_at = datetime.now(timezone.utc)
    session.add(queue)
    return queue


async def reset_queue(session: AsyncSession, queue: Queue) -> Queue:
    """Reset the queue: round=1, current = first rotation item. Held state preserved."""
    rotation = _active_rotation_desc(queue)
    if not rotation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueueMessages.NO_ITEMS,
        )

    queue.current_round = 1
    queue.current_item_id = rotation[0].id
    queue.updated_at = datetime.now(timezone.utc)
    session.add(queue)
    return queue


async def set_active_item(
    session: AsyncSession,
    queue: Queue,
    item_id: int,
) -> Queue:
    """Set the active item on a queue. Validates item belongs to the queue.

    If the target is currently held, ``held_at_round`` is cleared as part of
    the same operation — the invariant ``current ∉ held set`` should survive
    any direct-set path so the rotation doesn't enter a state where its
    current pointer references a held item.
    """
    items = getattr(queue, "items", None) or []
    target: QueueItem | None = next(
        (item for item in items if item.id == item_id), None
    )
    if target is None:
        raise KINDS["queue_item"].not_found()

    if target.held_at_round is not None:
        target.held_at_round = None
        session.add(target)
    queue.current_item_id = item_id
    queue.updated_at = datetime.now(timezone.utc)
    session.add(queue)
    return queue


async def hold_current(session: AsyncSession, queue: Queue) -> Queue:
    """Hold the current turn — record the round and advance to the next item.

    The held item leaves the rotation immediately. ``current_item_id``
    advances to the next rotation slot, skipping any other held items whose
    due round hasn't arrived. If holding empties the rotation,
    ``current_item_id`` is cleared and the round is unchanged.
    """
    if queue.current_item_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueueMessages.NO_CURRENT_ITEM,
        )
    items = getattr(queue, "items", None) or []
    current = next((item for item in items if item.id == queue.current_item_id), None)
    if current is None:
        # current_item_id pointing at a deleted/missing row; treat as "no current"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueueMessages.NO_CURRENT_ITEM,
        )

    # Record the hold *before* advancing so the rotation skips this item.
    current.held_at_round = queue.current_round
    session.add(current)

    # Find the next rotation-eligible slot in position-desc order, with wrap.
    visible = _visible_items_desc(queue)
    rotation = [item for item in visible if item.held_at_round is None]
    if not rotation:
        queue.current_item_id = None
        queue.updated_at = datetime.now(timezone.utc)
        session.add(queue)
        return queue

    # Locate where we *were* in the full visible list; advance from there to
    # the next non-held slot, wrapping and bumping round if needed.
    current_idx = next(
        (idx for idx, item in enumerate(visible) if item.id == current.id),
        -1,
    )
    round_ = queue.current_round
    for step in range(1, len(visible) + 1):
        next_idx = (current_idx + step) % len(visible)
        if next_idx <= current_idx:
            round_ = queue.current_round + 1
        candidate = visible[next_idx]
        if candidate.held_at_round is None:
            queue.current_item_id = candidate.id
            queue.current_round = round_
            break

    queue.updated_at = datetime.now(timezone.utc)
    session.add(queue)
    return queue


async def release_held(
    session: AsyncSession,
    queue: Queue,
    item_id: int,
    *,
    reposition: bool = False,
) -> Queue:
    """Manually release a held item back into the rotation.

    Clears ``held_at_round`` on the target so it rejoins the active rotation.
    ``current_item_id``, ``current_round``, and ``is_active`` are deliberately
    untouched — releasing a hold shouldn't rewind the rotation pointer onto
    items that already took their turn this round.

    When ``reposition`` is True (PF2e Delay semantics), the target acts now
    — it becomes the current turn, and its ``position`` is rewritten to land
    just above the previous current item in the position-desc rotation
    (midpoint between the previous current and the next-higher active item,
    or ``current.position + 1`` if current was the top of the rotation). The
    new initiative slot persists for the rest of the encounter, exactly like
    a PF2e Delay re-entry. Default ``False`` keeps the released item at its
    original position so it acts at its natural slot the next time the
    rotation reaches it, without disrupting the current pointer.
    """
    items = getattr(queue, "items", None) or []
    target = next((item for item in items if item.id == item_id), None)
    if target is None:
        raise KINDS["queue_item"].not_found()
    if target.held_at_round is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueueMessages.ITEM_NOT_HELD,
        )

    target.held_at_round = None

    if (
        reposition
        and queue.current_item_id is not None
        and queue.current_item_id != target.id
    ):
        current = next((x for x in items if x.id == queue.current_item_id), None)
        if current is not None:
            # Next active item whose position is strictly above current's
            # (held items and the target itself excluded).
            actives_above = sorted(
                (
                    x
                    for x in items
                    if x.is_visible
                    and x.held_at_round is None
                    and x.id != target.id
                    and x.id != current.id
                    and x.position > current.position
                ),
                key=lambda x: x.position,
            )
            if actives_above:
                target.position = (current.position + actives_above[0].position) / 2
            else:
                # Current was already the top — drop the released item just
                # above it. +1.0 is arbitrary but safely over any other
                # active position relative to current.
                target.position = current.position + 1.0
            # They're acting *now*, before the previous current's turn — take
            # over the current pointer so the rotation reflects that.
            queue.current_item_id = target.id

    session.add(target)
    queue.updated_at = datetime.now(timezone.utc)
    session.add(queue)
    return queue
