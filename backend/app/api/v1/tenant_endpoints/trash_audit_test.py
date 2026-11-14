"""Purging from the trash reaching the audit log.

A purge is the one action nothing recovers from, so the record is what is left
of the row afterwards: which kind of thing it was, which id, and who did it.
"""

from __future__ import annotations

from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.models.platform.guild import CommunityRole
from app.testing import create_project, emitted


async def test_purging_an_entity_records_what_was_destroyed(
    client: AsyncClient, session: AsyncSession, acting_user, capfd
):
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    project = await create_project(session, admin.initiative, admin.user)

    trashed = await client.delete(
        admin.g(f"/projects/{project.id}"), headers=admin.headers
    )
    assert trashed.status_code in (200, 204), trashed.text
    capfd.readouterr()

    purged = await client.delete(
        admin.g(f"/trash/project/{project.id}/purge"), headers=admin.headers
    )
    assert purged.status_code == 204, purged.text

    (row,) = emitted(capfd, AuditEventType.TRASH_PURGED)
    assert row["actor_user_id"] == admin.user.id
    assert row["target_user_id"] is None
    assert row["guild_id"] == admin.guild.id
    assert row["target"] == {"type": "project", "id": project.id}
    assert row["detail"] == {"via": "admin"}


async def test_a_refused_purge_records_nothing(
    client: AsyncClient, session: AsyncSession, acting_user, capfd
):
    """A purge is a guild admin's, and a request that never got past that
    destroyed nothing to write down."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    project = await create_project(session, admin.initiative, admin.user)
    trashed = await client.delete(
        admin.g(f"/projects/{project.id}"), headers=admin.headers
    )
    assert trashed.status_code in (200, 204), trashed.text
    capfd.readouterr()

    refused = await client.delete(
        member.g(f"/trash/project/{project.id}/purge"), headers=member.headers
    )
    assert refused.status_code == 403

    assert emitted(capfd, AuditEventType.TRASH_PURGED) == []
