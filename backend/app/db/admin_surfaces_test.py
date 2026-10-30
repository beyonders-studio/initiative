"""The admin rung's surfaces: the standing gives the admin rung every one and a
member none, and a policy that guards one part of administering the community
reads the surface, not the admin fact."""

from sqlalchemy import text

from app.models.platform.guild import AdminSurface, CommunityRole, GuildInvite
from app.testing import create_initiative, route_as

EVERY_SURFACE = {surface.value for surface in AdminSurface}


async def test_the_admin_rung_holds_every_surface_and_a_member_none(
    acting_user, role_session
):
    admin = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)

    for actor, held in ((admin, EVERY_SURFACE), (member, set())):
        s = await role_session("app_user")
        context = await route_as(s, user_id=actor.user.id, guild_id=admin.guild.id)
        assert set(context.held_surfaces) == held
        for surface in AdminSurface:
            assert context.holds_surface(surface) == (surface.value in held)


async def test_a_surface_policy_reads_the_surface_not_the_admin_fact(
    acting_user, role_session, session
):
    admin = await acting_user(guild_role=CommunityRole.admin)
    manager = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)
    await create_initiative(session, admin.guild, manager.user)
    session.add(
        GuildInvite(
            code_hash="a" * 64, guild_id=admin.guild.id, created_by=admin.user.id
        )
    )
    await session.commit()

    async def reaches(held: str) -> tuple[int, int, int]:
        s = await role_session("app_user")
        await route_as(s, user_id=admin.user.id, guild_id=admin.guild.id)
        await s.exec(
            text("SELECT set_config('app.held_surfaces', :held, true)").bindparams(
                held=held
            )
        )
        try:
            return (
                len((await s.exec(text("SELECT id FROM guild_invites"))).all()),
                (await s.exec(text("UPDATE initiatives SET name = name"))).rowcount,
                (await s.exec(text("UPDATE guilds SET name = name"))).rowcount,
            )
        finally:
            await s.rollback()

    assert await reaches(",".join(sorted(EVERY_SURFACE))) == (1, 1, 1)
    # Still the admin rung, still reaching every initiative's content: the
    # invites, the initiatives' setup and the profile are the surfaces'.
    assert await reaches("") == (0, 0, 0)
