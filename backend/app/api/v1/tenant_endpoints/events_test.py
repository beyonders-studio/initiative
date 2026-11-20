"""Which rooms an events-bus socket is seated in.

``_rooms_for`` is asked at connect and on every re-check, and it reads the one
``initiative_access`` function RLS uses: a member is seated in the initiatives
they are in, a guild admin and a grant holder in every one, and every socket in
its guild's own room.
"""

from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.tenant_endpoints.events import _rooms_for
from app.models.platform.guild import CommunityRole
from app.models.platform.user import UserRole
from app.services.content_sockets import guild_room, initiative_room
from app.testing import (
    create_access_grant,
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_user,
)


async def test_rooms_follow_initiative_access(
    session: AsyncSession, reading_as
) -> None:
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(
        session, user=owner, guild=guild, role=CommunityRole.admin
    )
    member = await create_user(session)
    await create_guild_membership(
        session, user=member, guild=guild, role=CommunityRole.member
    )
    joined = await create_initiative(session, guild, owner)
    await create_initiative_member(session, joined, member)
    other = await create_initiative(session, guild, owner)  # member NOT added
    grantee = await create_user(session, role=UserRole.support)  # not a member
    await create_access_grant(session, user=grantee, guild=guild)

    async def rooms(user) -> frozenset | None:
        # On the request login: which rooms exist for somebody is a policy
        # answer, and the setup session's own login is one the database treats
        # as trusted.
        reader = await reading_as(user.id, guild.id)
        seated = await _rooms_for(guild.id)(reader, user)
        await reader.rollback()
        return seated

    home = guild_room(guild.id)
    joined_room = initiative_room(guild.id, joined.id)
    every = {home, joined_room, initiative_room(guild.id, other.id)}
    # An initiative they're not in is never a room.
    assert await rooms(member) == {home, joined_room}
    # The guild-admin and PAM legs of initiative_access reach every initiative.
    assert await rooms(owner) == every
    assert await rooms(grantee) == every
