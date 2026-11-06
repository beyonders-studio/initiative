"""The own-row guild tables and a settings grant.

A row there belongs to one member. The community's settings rung reads every
row, and writes one only beside a ``read_write`` content grant — the same
answer the seat and structure tables give. Each test acts on the real request
login, routed through the seam as the seat's routes route it.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import select

from app.models.platform.guild import CommunityRole
from app.models.platform.user import UserRole
from app.models.tenant.data_job import DataJob, DataJobDirection
from app.testing import (
    create_access_grant,
    create_export_job,
    create_user,
    route_as,
    route_session_to_guild,
)


_FAIL = text("UPDATE data_jobs SET status = 'failed'")


async def _seat_session(role_session, *, user_id: int, guild_id: int):
    """A request-login session routed as a seat route routes it."""
    s = await role_session("app_user")
    await route_as(s, user_id=user_id, guild_id=guild_id, seat=True)
    return s


async def _statuses(session, guild_id: int) -> list[str]:
    session.expire_all()
    await route_session_to_guild(session, guild_id)
    return list((await session.exec(select(DataJob.status))).all())


async def test_a_settings_grant_reads_a_members_row_and_writes_only_beside_read_write(
    session, acting_user, role_session
):
    member = await acting_user(guild_role=CommunityRole.member)
    guild_id = member.guild.id
    await create_export_job(session, member.guild, member.user)
    other = await create_user(session)
    support = await create_user(session, role=UserRole.support)
    await create_access_grant(
        session,
        user=support,
        guild=member.guild,
        access_level="superadmin",
        purpose="settings",
    )

    s = await _seat_session(role_session, user_id=support.id, guild_id=guild_id)
    assert list(await s.exec(select(DataJob.created_by))) == [member.user.id]
    # The row is read and not written: the update matches nothing.
    result = await s.exec(_FAIL)
    assert result.rowcount == 0
    await s.commit()
    s.add(
        DataJob(
            direction=DataJobDirection.export,
            created_by=other.id,
            source="tasks",
            template_id="task-table",
        )
    )
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.commit()
    await s.rollback()
    assert await _statuses(session, guild_id) == ["queued"]

    await session.refresh(support)
    await session.refresh(member.guild)
    await create_access_grant(
        session, user=support, guild=member.guild, access_level="read_write"
    )
    s = await _seat_session(role_session, user_id=support.id, guild_id=guild_id)
    result = await s.exec(_FAIL)
    assert result.rowcount == 1
    await s.commit()
    assert await _statuses(session, guild_id) == ["failed"]


async def test_the_seat_holder_writes_a_members_row(session, acting_user, role_session):
    seat = await acting_user(guild_role=CommunityRole.superadmin)
    member = await acting_user(guild_role=CommunityRole.member, guild=seat.guild)
    await create_export_job(session, seat.guild, member.user)

    s = await _seat_session(role_session, user_id=seat.user.id, guild_id=seat.guild.id)
    result = await s.exec(_FAIL)
    assert result.rowcount == 1
    await s.commit()
    assert await _statuses(session, seat.guild.id) == ["failed"]
