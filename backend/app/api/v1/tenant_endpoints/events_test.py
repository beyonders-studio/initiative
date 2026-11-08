"""Which rooms an events-bus socket is seated in.

``_rooms_for`` is asked at connect and on every re-check, and it reads the one
``initiative_access`` function RLS uses: a member is seated in the initiatives
they are in, a guild admin and a grant holder in every one, and every socket in
its guild's own room.
"""

from datetime import datetime, timedelta, timezone

from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import establish_guild_access
from app.api.v1.tenant_endpoints.events import _rooms_for
from app.models.platform.access_grant import AccessGrant, AccessGrantStatus, AccessLevel
from app.models.platform.guild import CommunityRole
from app.models.platform.user import UserRole
from app.services.content_sockets import guild_room, initiative_room
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_user,
)


async def test_rooms_member_sees_only_their_own(
    session: AsyncSession, reading_as
) -> None:
    owner = await create_user(session, email="owner@example.com")
    guild = await create_guild(session, creator=owner)
    member = await create_user(session, email="member@example.com")
    await create_guild_membership(
        session, user=member, guild=guild, role=CommunityRole.member
    )
    joined = await create_initiative(session, guild, owner)
    await create_initiative_member(session, joined, member)
    other = await create_initiative(session, guild, owner)  # member NOT added

    # On the request login: which rooms exist for somebody is a policy answer,
    # and the setup session's own login is one the database treats as trusted.
    reader = await reading_as(member.id, guild.id)
    rooms = await _rooms_for(guild.id)(reader, member)
    await reader.rollback()

    assert guild_room(guild.id) in rooms
    assert initiative_room(guild.id, joined.id) in rooms
    assert (
        initiative_room(guild.id, other.id) not in rooms
    )  # an initiative they're not in is never a room


async def test_rooms_guild_admin_sees_all(
    session: AsyncSession,
) -> None:
    owner = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(
        session, user=owner, guild=guild, role=CommunityRole.admin
    )
    one = await create_initiative(session, guild, owner)
    two = await create_initiative(session, guild, owner)

    await establish_guild_access(session, owner, guild.id)
    rooms = await _rooms_for(guild.id)(session, owner)

    # The guild-admin leg of initiative_access reaches every initiative.
    assert initiative_room(guild.id, one.id) in rooms
    assert initiative_room(guild.id, two.id) in rooms


async def test_rooms_pam_grantee_sees_all(
    session: AsyncSession,
) -> None:
    """A live PAM read grantee has guild-wide read, so they may be notified about
    every initiative — they join all rooms, via the PAM leg of initiative_access."""
    owner = await create_user(session, email="grant-owner@example.com")
    guild = await create_guild(session, creator=owner)
    one = await create_initiative(session, guild, owner)
    two = await create_initiative(session, guild, owner)

    grantee = await create_user(  # not a member
        session, email="grantee@example.com", role=UserRole.support
    )
    now = datetime.now(timezone.utc)
    session.add(
        AccessGrant(
            user_id=grantee.id,
            guild_id=guild.id,
            access_level=AccessLevel.read.value,
            status=AccessGrantStatus.approved.value,
            reason="support",
            requested_duration_minutes=60,
            requested_by_id=grantee.id,
            approved_by_id=owner.id,
            requested_at=now,
            decided_at=now,
            expires_at=now + timedelta(hours=1),
        )
    )
    await session.commit()

    await establish_guild_access(session, grantee, guild.id)
    rooms = await _rooms_for(guild.id)(session, grantee)

    assert initiative_room(guild.id, one.id) in rooms
    assert initiative_room(guild.id, two.id) in rooms
