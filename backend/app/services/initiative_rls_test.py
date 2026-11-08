"""DB-level initiative RLS isolation tests.

These bypass the app layer entirely: they set the guild RLS context and run a raw
``SELECT`` as the assumed guild role, so a missing/incorrect policy fails the
assertion (the app-layer ``membership.py`` clause can't paper over it). Proves the
``initiative_access`` policies on the guild content tables actually enforce
initiative-membership for non-admin guild roles.
"""

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import CommunityRole
from app.models.tenant.project import Project
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_project,
    create_resource_grant,
    create_user,
)


async def test_non_admin_member_sees_only_their_initiatives_content(
    session: AsyncSession, reading_as
):
    """Under the guild role, a non-admin member sees content rows only for the
    initiatives they belong to — a co-guild-member's other initiative is hidden by
    RLS, not just by app code. A guild admin sees everything in the guild."""
    owner = await create_user(session, email="irls-owner@example.com")
    member = await create_user(session, email="irls-member@example.com")
    guild = await create_guild(session, creator=owner)
    admin = owner
    await create_guild_membership(
        session, user=member, guild=guild, role=CommunityRole.member
    )
    init_a = await create_initiative(session, guild, owner, name="Alpha")
    init_b = await create_initiative(session, guild, owner, name="Bravo")
    await create_initiative_member(session, init_a, member)  # member of Alpha only
    proj_a = await create_project(session, init_a, owner, name="A-Proj")
    await create_project(session, init_b, owner, name="B-Proj")
    # Shared with Alpha, so the sharing gate admits it and what this measures is
    # the initiative one: Bravo's project stays hidden either way.
    await create_resource_grant(session, proj_a, all_initiative_members=True)

    # On the request login, where the policies bind.
    reader = await reading_as(member.id, guild.id)
    member_view = set((await reader.exec(select(Project.name))).all())
    await reader.rollback()
    assert "A-Proj" in member_view, "member must see their own initiative's project"
    assert "B-Proj" not in member_view, (
        "RLS must hide a project in an initiative the member doesn't belong to"
    )

    # A community's administrator sees every initiative's content.
    admin_reader = await reading_as(admin.id, guild.id)
    admin_view = set((await admin_reader.exec(select(Project.name))).all())
    await admin_reader.rollback()
    assert {"A-Proj", "B-Proj"} <= admin_view
