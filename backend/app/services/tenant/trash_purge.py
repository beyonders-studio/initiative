"""Auto-purge background worker for trashed entities past their retention.

Visited in an active guild when its ``trash`` timer comes due (armed as a row
is trashed, for its ``purge_at``), on a system session routed into the guild's
schema; the policies' system leg names that login. See :func:`purge_guild`.

Each table's due rows are purged together, parents first, through the same
``hard_purge_entities`` the trash can's purge button uses: files and
pictures take their stored files with them, and descendants go before the rows
they hang off.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.db.soft_delete_filter import SOFT_DELETE_MODELS, select_including_deleted
from app.services import audit as audit_service
from app.services.tenant.attachments import (
    delete_blobs,
    release_unclaimed_pasted_images,
)
from app.services.tenant.held import holds_under
from app.services.tenant.lifecycle_tree import parents_first
from app.services.tenant.soft_delete import hard_purge_entities

logger = logging.getLogger(__name__)


#: Every soft-deletable model, parents before children, so a row whose
#: retention has elapsed takes its descendants with it and the later passes find
#: them gone.
_PURGE_TOP_DOWN = parents_first(SOFT_DELETE_MODELS)


def _entity_type(model: type) -> str:
    """The trash-can name for a model — ``CounterGroup`` → ``counter_group``."""
    name = model.__name__
    parts: list[str] = []
    for index, char in enumerate(name):
        if char.isupper() and index:
            parts.append("_")
        parts.append(char.lower())
    return "".join(parts)


async def _run_purge_pass(
    session, *, now: datetime, guild_id: int | None = None
) -> set[str]:
    """Inner loop: walks _PURGE_TOP_DOWN once on the supplied session, and
    returns the stored names of the uploads that went. Caller commits, then
    deletes their blobs. Factored out so tests can drive it with their own
    session against the test DB.

    With ``guild_id``, a pass that purged anything records it once, with the
    count per entity type. The session is routed into the guild with no
    account behind it, so the record carries no actor."""
    purged: dict[str, int] = {}
    released: set[str] = set()
    for model in _PURGE_TOP_DOWN:
        # A row an earlier pass took with its parent is already gone from the
        # database, so it is not found here. A row another process is purging
        # is locked, and left to it.
        stmt = (
            select_including_deleted(model)
            .where(model.purge_at.is_not(None))
            .where(model.purge_at < now)
            .with_for_update(skip_locked=True)
        )
        rows = list((await session.exec(stmt)).all())
        # What holds something the platform holds waits for its release, and
        # is tried again on the next pass (app.db.holds).
        rows = [row for row in rows if not await holds_under(session, [row])]
        if rows:
            released |= await hard_purge_entities(session, rows)
            purged[_entity_type(model)] = len(rows)

    if guild_id is not None and purged:
        await audit_service.record(
            session,
            event_type=AuditEventType.TRASH_PURGED,
            actor_user_id=None,
            guild_id=guild_id,
            detail={"via": "sweep", "counts": purged},
        )
    return released


async def purge_guild(session: AsyncSession, guild_id: int) -> None:
    """Purge the guild's trash past its retention, and the pictures pasted
    and never saved past their grace period.

    Goes through ``hard_purge_entities`` rather than a bare
    ``DELETE … WHERE purge_at < now()``, so that:
    1. ``File`` upload cleanup (blobs + Upload rows) runs before each
       File is deleted.
    2. Descendants go first — most keys between these tables do not cascade
       in the database, so a bare delete of a parent would fail on them.

    Only active guilds are visited. A read-only or suspended guild is frozen:
    retention resumes, with the original ``purge_at`` stamps, when it returns
    to active.
    """
    now = datetime.now(UTC)
    released = await _run_purge_pass(session, now=now, guild_id=guild_id)
    released |= await release_unclaimed_pasted_images(session, now=now)
    await session.commit()
    delete_blobs(guild_id, released)
