"""The hourly sweep reaching the audit log.

The sweep destroys rows whose retention has run out, and nobody asked it to:
one record per guild pass, carrying what it took and no actor, because the
session it runs on has no account behind it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.db.soft_delete_filter import select_including_deleted
from app.models.tenant.initiative import Initiative
from app.services.guild_sweeps import Scope, each_guild
from app.services.tenant.soft_delete import soft_delete_entity
from app.services.tenant.trash_purge import purge_guild
from app.testing import emitted
from app.testing.factories import (
    create_guild,
    create_initiative,
    create_project,
    create_user,
)


async def _expired_initiative(session: AsyncSession, guild, user, **overrides):
    """An initiative (with a project under it) whose retention has run out."""
    initiative = await create_initiative(session, guild, user, **overrides)
    await create_project(session, initiative, user)
    await soft_delete_entity(
        session, initiative, deleted_by_user_id=user.id, retention_days=1
    )
    await session.commit()

    refreshed = (
        await session.exec(
            select_including_deleted(Initiative).where(Initiative.id == initiative.id)
        )
    ).one()
    refreshed.purge_at = datetime.now(UTC) - timedelta(days=2)
    session.add(refreshed)
    await session.commit()
    return initiative


async def test_a_sweep_records_one_pass_per_guild_with_its_counts(
    session: AsyncSession, capfd
):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    guild_id = guild.id
    await _expired_initiative(session, guild, user, name="Swept")

    capfd.readouterr()
    await each_guild([(Scope.ACTIVE, purge_guild)], name="trash-purge")

    rows = [
        row
        for row in emitted(capfd, AuditEventType.TRASH_PURGED)
        if row["guild_id"] == guild_id
    ]
    assert len(rows) == 1
    (row,) = rows
    # Nobody signed in caused this, so there is no actor to name.
    assert row["actor_user_id"] is None
    assert row["target"] is None
    assert row["detail"]["via"] == "sweep"
    # The project under it went with the initiative, so the initiative is what
    # the pass walked.
    assert row["detail"]["counts"] == {"initiative": 1}


async def test_a_guild_with_nothing_due_records_nothing(session: AsyncSession, capfd):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    guild_id = guild.id
    await create_initiative(session, guild, user, name="Still here")

    capfd.readouterr()
    await each_guild([(Scope.ACTIVE, purge_guild)], name="trash-purge")

    assert [
        row
        for row in emitted(capfd, AuditEventType.TRASH_PURGED)
        if row["guild_id"] == guild_id
    ] == []
