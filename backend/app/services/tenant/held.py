"""What the community's own lifecycle does around held content.

A held row (``app.db.holds``) stays where it is: trashing or archiving what it
sits in leaves it as it was, and purging what it sits in waits until the
platform releases it. The database refuses anything that would delete a held
row; these let the lifecycle paths see that coming and step around it, rather
than fail part way.
"""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import CodedError
from app.core.messages import CommonMessages
from app.db.query import ids_in
from app.db.soft_delete_filter import select_including_deleted
from app.services.tenant.lifecycle_tree import Level, subtree_levels


class HeldContent(CodedError):
    """Something under this is held: it can't be destroyed until the platform
    releases it. Answered as frozen content is, naming nothing."""

    status_code = status.HTTP_409_CONFLICT

    def __init__(self) -> None:
        super().__init__(CommonMessages.CONTENT_IS_FROZEN)


async def _any_held(session: AsyncSession, rows: Level) -> bool:
    from app.models.tenant.initiative import Initiative
    from app.models.tenant.upload import Upload

    for model, ids in rows.items():
        if not ids or not hasattr(model, "held_at"):
            continue
        found = (
            await session.exec(
                select_including_deleted(model)
                .where(ids_in(model.id, ids))
                .where(model.held_at.is_not(None))
                .limit(1)
            )
        ).first()
        if found is not None:
            return True
    initiatives = rows.get(Initiative)
    if initiatives:
        # An initiative's uploads go with it, and are no part of the tree.
        found = (
            await session.exec(
                select(Upload.id)
                .where(ids_in(Upload.initiative_id, initiatives))
                .where(Upload.held_at.is_not(None))  # type: ignore[union-attr]
                .limit(1)
            )
        ).first()
        if found is not None:
            return True
    return False


async def refuse_if_held(
    session: AsyncSession, roots: Iterable[object], doomed: Level
) -> None:
    """Refuse a purge of ``roots`` — ``doomed`` is what the session found at
    and under them — when any of it is held.

    A person's session reads nothing held, so for one routed as a person the
    walk is made again as the platform, which sees it all.
    """
    from app.db import cohorts
    from app.db.request_context import SystemGuild
    from app.db.session import guild_context, set_rls_context

    if await _any_held(session, doomed):
        raise HeldContent()
    context = guild_context(session)
    if context is None:
        return
    async with cohorts.system_session(context.guild_id) as system:
        await set_rls_context(system, SystemGuild(context.guild_id, read_only=True))
        again = []
        for root in roots:
            model = type(root)
            found = (
                await system.exec(
                    select_including_deleted(model).where(model.id == root.id)  # type: ignore[attr-defined]
                )
            ).first()
            if found is not None:
                again.append(found)
        held = bool(again) and await holds_under(system, again)
        await system.rollback()
    if held:
        raise HeldContent()


async def holds_under(session: AsyncSession, roots: Iterable[object]) -> bool:
    """Whether anything at or under ``roots`` is held."""
    doomed: Level = {}
    for level in await subtree_levels(session, list(roots)):
        for model, ids in level.items():
            doomed.setdefault(model, []).extend(ids)
    return await _any_held(session, doomed)
