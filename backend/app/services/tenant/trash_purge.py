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

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.tool_set import BUILTIN_TOOLS, ToolSet
from app.db.tool_rows import ToolRow
from app.services import audit as audit_service
from app.services.tenant.attachments import (
    delete_blobs,
    release_unclaimed_pasted_images,
)
from app.services.tenant.held import holds_under
from app.services.tenant.lifecycle_tree import (
    binned_tables,
    cascade_children,
    parents_first,
    trash_kinds,
)
from app.services.tenant.soft_delete import hard_purge_entities

logger = logging.getLogger(__name__)


async def _run_purge_pass(
    session,
    *,
    now: datetime,
    guild_id: int | None = None,
    tools: ToolSet = BUILTIN_TOOLS,
) -> set[str]:
    """Inner loop: walks every table with the trash in a community with
    ``tools`` once, parents before children, on the supplied session, and
    returns the stored names of the uploads that went. Caller commits, then
    deletes their blobs. Factored out so tests can drive it with their own
    session against the test DB.

    With ``guild_id``, a pass that purged anything records it once, with the
    count per entity type. The session is routed into the guild with no
    account behind it, so the record carries no actor."""
    purged: dict[str, int] = {}
    released: set[str] = set()
    tree = cascade_children(tools)
    entity_types = {table: kind for kind, table in trash_kinds(tools).items()}
    for table in parents_first(binned_tables(tools), tools):
        # A row an earlier pass took with its parent is already gone from the
        # database, so it is not found here. A row another process is purging
        # is locked, and left to it.
        stmt = (
            select(table.c.id)
            .execution_options(include_deleted=True)
            .where(table.c.purge_at.is_not(None))
            .where(table.c.purge_at < now)
            .with_for_update(skip_locked=True)
        )
        found = (await session.exec(stmt)).scalars().all()
        rows = [ToolRow(table, {"id": row_id}) for row_id in found]
        # What holds something the platform holds waits for its release, and
        # is tried again on the next pass (app.db.holds).
        rows = [row for row in rows if not await holds_under(session, [row], tree=tree)]
        if rows:
            released |= await hard_purge_entities(session, rows, tools=tools)
            purged[entity_types[table]] = len(rows)

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
    from app.db.plugin_tools import provisioned_tools

    now = datetime.now(UTC)
    released = await _run_purge_pass(
        session, now=now, guild_id=guild_id, tools=await provisioned_tools(guild_id)
    )
    released |= await release_unclaimed_pasted_images(session, now=now)
    await session.commit()
    delete_blobs(guild_id, released)
