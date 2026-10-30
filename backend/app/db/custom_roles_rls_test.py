"""Custom roles in the standing and the policies: a role on its holder's rung
decides what they hold, and nobody writes a role past what they hold."""

from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.models.platform.guild import CommunityRole
from app.models.tenant.custom_role import CustomRole, CustomRoleMember
from app.testing import route_as
from app.testing.schema_harness import route_session_to_guild


async def _give(session, guild_id: int, user_id: int, **role) -> CustomRole:
    await route_session_to_guild(session, guild_id)
    made = CustomRole(**role)
    session.add(made)
    await session.flush()
    session.add(CustomRoleMember(user_id=user_id, role_id=made.id))
    await session.commit()
    return made


async def _held(role_session, actor) -> set[str]:
    s = await role_session("app_user")
    context = await route_as(s, user_id=actor.user.id, guild_id=actor.guild.id)
    return set(context.held_surfaces)


async def test_a_role_on_its_holders_rung_decides_what_they_hold(
    acting_user, role_session, session
):
    admin = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)
    other = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)
    gid = admin.guild.id
    await _give(
        session,
        gid,
        member.user.id,
        name="Doors",
        base_rung="member",
        surfaces=["invites"],
    )
    await _give(
        session,
        gid,
        admin.user.id,
        name="Calendars",
        base_rung="admin",
        surfaces=["community_calendars"],
    )
    # On the wrong rung, a role gives nothing.
    await _give(
        session,
        gid,
        other.user.id,
        name="Admins'",
        base_rung="admin",
        surfaces=["roles"],
    )

    assert await _held(role_session, member) == {"invites"}
    assert await _held(role_session, admin) == {"community_calendars"}
    assert await _held(role_session, other) == set()

    # A role given before the membership began is an old membership's.
    member.membership.joined_at = member.membership.joined_at + timedelta(days=1)
    session.add(member.membership)
    await session.commit()
    assert await _held(role_session, member) == set()


async def test_nobody_writes_a_role_past_what_they_hold(
    acting_user, role_session, session
):
    admin = await acting_user(guild_role=CommunityRole.admin)
    narrowed = await acting_user(guild_role=CommunityRole.admin, guild=admin.guild)
    gid = admin.guild.id
    kept = await _give(
        session,
        gid,
        narrowed.user.id,
        name="Roster",
        base_rung="admin",
        surfaces=["members", "roles"],
    )

    async def writes(actor, sql: str) -> bool:
        s = await role_session("app_user")
        await route_as(s, user_id=actor.user.id, guild_id=gid)
        try:
            changed = (await s.exec(text(sql))).rowcount
            await s.commit()
        except DBAPIError:
            return False
        finally:
            await s.rollback()
        return changed > 0

    make = (
        "INSERT INTO custom_roles (name, base_rung, surfaces, created_at)"
        " VALUES ('{name}', 'member', ARRAY[{surfaces}]::text[], now())"
    )
    assert not await writes(narrowed, make.format(name="Doors", surfaces="'invites'"))
    assert await writes(narrowed, make.format(name="Roll", surfaces="'members'"))
    # Taking an admin's role off widens them to every surface.
    unassign = f"DELETE FROM custom_role_members WHERE user_id = {narrowed.user.id}"
    assert not await writes(narrowed, unassign)
    assert not await writes(narrowed, f"DELETE FROM custom_roles WHERE id = {kept.id}")
    # Nor does a role move to another rung.
    assert not await writes(
        admin, f"UPDATE custom_roles SET base_rung = 'member' WHERE id = {kept.id}"
    )
    assert await writes(admin, unassign)
