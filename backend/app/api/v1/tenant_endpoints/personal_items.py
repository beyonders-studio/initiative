"""What a member keeps about items: opens, bookmarks, subscriptions and
reminders.

A subscription is also worked out: making something or being named on it
subscribes the reader, so unsubscribing is kept as a mark of its own.

Setting and clearing one is community-addressed
(``/c/{community_id}/personal-items/{mark}/{kind}/{id}``): per-schema ids are
only unique within a community. Opening and subscribing take read on the item,
the same its own page takes; bookmarking takes it on a tool. Clearing asks
nothing of the item, so a mark on something the reader has lost still comes
off. A community's bookmarks serve its sidebar and the bookmarks on its pages;
``/me/personal-items`` gathers every community's tabs or bookmarks, names and
icons only, each community's read inside that community's routed session.

A reminder is on a task, and is the reader's alone: it is told to them when it
comes due (``notifications.task_reminder_scan``), and a repeating task's next
task takes it on.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, status
from sqlmodel import select

from app.api import resource_access
from app.api.deps import CurrentUser, GuildContextDep, RLSSessionDep, UserSessionDep
from app.core.tools import Tool
from app.db.session import require_guild_context
from app.models.platform.guild import GuildMembership
from app.models.tenant.personal_item import ViewSource
from app.schemas.tenant.personal_item import (
    ContentKind,
    ListedMark,
    PersonalItemRead,
    PersonalItemState,
    ReminderSet,
)
from app.services.cross_guild import gather_across_guilds
from app.services.tenant import personal_items as service
from app.services.tenant.personal_items import Mark
from app.services.tenant.tool_items import load_tool_items

#: ``/c/{community_id}/personal-items``: one community's.
guild_router = APIRouter()
#: ``/me/personal-items``: every community's.
me_router = APIRouter()


async def _community_items(
    session, user_id: int, mark: ListedMark, limit: int | None = None
) -> List[PersonalItemRead]:
    """This community's tools the reader marked this way and may still read,
    newest first. Must run in the community's routed session."""
    context = require_guild_context(session)
    rows = await service.list_marked(
        session, user_id=user_id, mark=Mark(mark.value), limit=limit
    )
    if not rows:
        return []
    loaded = await load_tool_items(
        session, ((row.entity_type, row.entity_id) for row in rows)
    )
    items: List[PersonalItemRead] = []
    for row in rows:
        item = loaded.get((row.entity_type, row.entity_id))
        if item is None:
            continue
        items.append(
            # Trusted columns, already sanitized on the way in: constructed so
            # they are not escaped a second time on the way out.
            PersonalItemRead.model_construct(
                entity_type=item.tool,
                entity_id=item.entity_id,
                community_id=context.guild_id,
                initiative_id=item.initiative_id,
                name=item.name,
                viewed_at=row.viewed_at,
                bookmarked_at=row.bookmarked_at,
                **item.extra,
            )
        )
    return items


async def _state(
    session, user_id: int, kind: str, entity_id: int, *, subscription: bool = True
) -> PersonalItemState:
    row = await service.item_state(
        session, user_id=user_id, kind=kind, entity_id=entity_id
    )
    subscribed = (
        await service.is_subscribed(
            session, user_id=user_id, kind=kind, entity_id=entity_id
        )
        if subscription
        else None
    )
    return PersonalItemState(
        entity_type=ContentKind(kind),
        entity_id=entity_id,
        viewed_at=row.viewed_at if row else None,
        view_source=ViewSource(row.view_source) if row and row.view_source else None,
        bookmarked_at=row.bookmarked_at if row else None,
        subscribed_at=row.subscribed_at if row else None,
        subscribed=subscribed,
        remind_at=row.remind_at if row else None,
        reminded_at=row.reminded_at if row else None,
    )


async def _set(
    mark: Mark,
    kind: str,
    entity_id: int,
    session,
    current_user,
    guild_context,
) -> PersonalItemState:
    """Bookmark or subscribe, after loading the item as its page does. A platform
    grantee is not a member, so nothing is kept for them."""
    row = await resource_access.load_kind(
        session, kind, entity_id, current_user, guild_context
    )
    if not guild_context.is_pam:
        await service.set_mark(
            session, user_id=current_user.id, mark=mark, kind=kind, entity_id=row.id
        )
    return await _state(session, current_user.id, kind, row.id)


@guild_router.get("", response_model=List[PersonalItemRead])
async def list_personal_items(
    mark: ListedMark,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> List[PersonalItemRead]:
    """The tools the reader opened or bookmarked in this community, newest first."""
    del guild_context  # validation + routing happen in the dependency
    return await _community_items(session, current_user.id, mark)


@guild_router.get("/{kind}/{entity_id}", response_model=PersonalItemState)
async def read_personal_item(
    kind: ContentKind,
    entity_id: int,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> PersonalItemState:
    """What the reader keeps about one item: empty where they keep nothing."""
    del guild_context
    return await _state(session, current_user.id, kind.value, entity_id)


@guild_router.put("/view/{kind}/{entity_id}", response_model=PersonalItemState)
async def record_view(
    kind: ContentKind,
    entity_id: int,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    source: ViewSource = ViewSource.direct,
) -> PersonalItemState:
    """Record that the reader opened this: a tool, which becomes a tab, or
    something inside one, which does not. A platform grantee's browsing is
    transient and is not kept."""
    row = await resource_access.load_kind(
        session, kind.value, entity_id, current_user, guild_context
    )
    viewed_at = await service.record_view(
        session,
        user_id=current_user.id,
        entity_type=kind.value,
        entity_id=row.id,
        source=source,
        persist=not guild_context.is_pam,
    )
    state = await _state(
        session, current_user.id, kind.value, row.id, subscription=False
    )
    return state.model_copy(update={"viewed_at": viewed_at, "view_source": source})


@guild_router.put("/bookmark/{tool}/{entity_id}", response_model=PersonalItemState)
async def bookmark_item(
    tool: Tool,
    entity_id: int,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> PersonalItemState:
    """Bookmark a tool. Bookmarking one already bookmarked keeps the first time."""
    return await _set(
        Mark.bookmark, tool.value, entity_id, session, current_user, guild_context
    )


@guild_router.put("/subscribe/{kind}/{entity_id}", response_model=PersonalItemState)
async def subscribe_item(
    kind: ContentKind,
    entity_id: int,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> PersonalItemState:
    """Subscribe to a tool or anything inside one: its changes, and those of what is
    inside it, rise in the reader's feed and notify them."""
    return await _set(
        Mark.subscribe, kind.value, entity_id, session, current_user, guild_context
    )


@guild_router.put("/reminder/task/{task_id}", response_model=PersonalItemState)
async def set_task_reminder(
    task_id: int,
    reminder: ReminderSet,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> PersonalItemState:
    """Remind the reader of a task at a time of their choosing. Setting it again
    moves it, and arms one already sent. A platform grantee is not a member, so
    nothing is kept for them."""
    row = await resource_access.load_kind(
        session, "task", task_id, current_user, guild_context
    )
    if not guild_context.is_pam:
        await service.set_reminder(
            session,
            user_id=current_user.id,
            task_id=row.id,
            remind_at=reminder.remind_at,
        )
    return await _state(session, current_user.id, "task", row.id)


@guild_router.delete("/reminder/task/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def clear_task_reminder(
    task_id: int,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> None:
    """Take the reader's reminder of a task off. Idempotent."""
    del guild_context
    await service.clear_reminder(session, user_id=current_user.id, task_id=task_id)


async def _clear(mark: Mark, kind: str, entity_id: int, session, user_id: int) -> None:
    await service.clear_mark(
        session, user_id=user_id, mark=mark, kind=kind, entity_id=entity_id
    )


@guild_router.delete("/view/{kind}/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def clear_view(
    kind: ContentKind,
    entity_id: int,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> None:
    """Close a tab. Idempotent."""
    del guild_context
    await _clear(Mark.view, kind.value, entity_id, session, current_user.id)


@guild_router.delete(
    "/bookmark/{tool}/{entity_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def unbookmark_item(
    tool: Tool,
    entity_id: int,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> None:
    """Remove a bookmark. Idempotent."""
    del guild_context
    await _clear(Mark.bookmark, tool.value, entity_id, session, current_user.id)


@guild_router.delete(
    "/subscribe/{kind}/{entity_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def unsubscribe_item(
    kind: ContentKind,
    entity_id: int,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> None:
    """Unsubscribe: nothing about it reaches the reader any more, whatever ties
    them to it, until they subscribe again. Idempotent, and a subscription
    comes off something the reader has lost too; where they keep nothing about
    it yet, the item is loaded as its page does. A platform grantee is not a
    member, so nothing is kept."""
    if guild_context.is_pam:
        return
    if await service.unsubscribe(
        session, user_id=current_user.id, kind=kind.value, entity_id=entity_id
    ):
        return
    row = await resource_access.load_kind(
        session, kind.value, entity_id, current_user, guild_context
    )
    await service.unsubscribe(
        session, user_id=current_user.id, kind=kind.value, entity_id=row.id, new=True
    )


@me_router.get("/personal-items", response_model=List[PersonalItemRead])
async def list_my_personal_items(
    mark: ListedMark,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> List[PersonalItemRead]:
    """The tools the reader opened or bookmarked in every community they are in,
    newest first. Opens are the tabs: as many as the reader keeps."""
    member_guilds = list(
        (
            await session.exec(
                select(GuildMembership.guild_id).where(
                    GuildMembership.user_id == current_user.id
                )
            )
        ).all()
    )
    limit = (
        service.clamp_recent_limit(current_user.recent_tabs_limit)
        if mark is ListedMark.view
        else None
    )

    async def _fetch(guild_session, guild_id: int) -> List[PersonalItemRead]:  # type: ignore[no-untyped-def]
        del guild_id
        return await _community_items(guild_session, current_user.id, mark, limit)

    items = await gather_across_guilds(
        session, {current_user.id: member_guilds}, _fetch
    )
    field = "viewed_at" if mark is ListedMark.view else "bookmarked_at"
    items.sort(key=lambda item: getattr(item, field), reverse=True)
    return items[:limit] if limit is not None else items
