"""The seat above admin, and the one thing it must not cost.

``superadmin`` is a third stored role. What keeps that from touching the
tenancy model is that no policy asks which of the three it is: the standing
carries one fact, ``app.guild_admin``, computed from the row by the database.
These pin both halves — the authority the seat has, and the gate it does not
widen.
"""

import pytest
from fastapi import HTTPException

from app.api import deps
from app.db.guild_standing import GuildContext
from app.models.platform.guild import (
    GUILD_ADMIN_ROLES,
    GUILD_ASSIGNABLE_ROLES,
    AdminSurface,
    CommunityRole,
    Guild,
    GuildMembership,
    assignable_roles,
)


def test_a_superadmin_carries_an_admins_authority_and_a_member_does_not():
    assert CommunityRole.superadmin.reaches(CommunityRole.admin)
    assert not CommunityRole.member.reaches(CommunityRole.admin)


@pytest.mark.parametrize(
    ("by", "assignable"),
    [
        # Administering a community is not deciding who enters.
        (CommunityRole.admin, GUILD_ASSIGNABLE_ROLES),
        (CommunityRole.member, GUILD_ASSIGNABLE_ROLES),
        # The seat is passed on by whoever holds it.
        (CommunityRole.superadmin, GUILD_ASSIGNABLE_ROLES | {CommunityRole.superadmin}),
    ],
)
def test_only_the_seat_hands_out_the_seat(by, assignable):
    allowed = assignable_roles(by)
    assert allowed == assignable
    assert {CommunityRole.admin, CommunityRole.member} <= allowed
    # Support is a synthesized PAM identity, never a stored membership role.
    assert CommunityRole.support not in allowed


def _context(role: CommunityRole) -> GuildContext:
    """A context shaped as the seam would have built it for this row.

    The admin fact is what the standing statement computed from the membership
    row, so a fixture states it the same way rather than re-deriving it.
    """
    return GuildContext(
        guild=Guild(id=1, name="g"),
        user_id=2,
        guild_id=1,
        membership=GuildMembership(guild_id=1, user_id=2, role=role),
        guild_role=role.value,
        standing_guild_id=1,
        guild_admin=role in GUILD_ADMIN_ROLES,
        held_surfaces=(
            tuple(s.value for s in AdminSurface) if role in GUILD_ADMIN_ROLES else ()
        ),
        guild_seat=role is CommunityRole.superadmin,
    )


async def test_a_surface_guard_admits_the_admin_rung_and_the_seat_above_it():
    """The dependency every admin endpoint is written against: each names the
    surface it guards, and the admin rung holds every one."""
    for surface in AdminSurface:
        guard = deps.require_surface(surface)
        for role in (CommunityRole.admin, CommunityRole.superadmin):
            assert (await guard(_context(role))).role == role


async def test_that_guard_still_turns_a_member_away():
    guard = deps.require_surface(AdminSurface.invites)
    with pytest.raises(HTTPException) as caught:
        await guard(_context(CommunityRole.member))
    assert caught.value.status_code == 403


def test_no_guard_asks_for_the_admin_rung_alone():
    """An admin route names its surface, so the rung guard refuses ``admin``."""
    with pytest.raises(ValueError):
        deps.require_guild_roles(CommunityRole.admin)


async def test_a_guard_naming_a_rung_admits_the_rungs_above_it():
    """The ladder answers every guard the same way: a rung asked for is that
    rung or above, and granted access — no membership row — reaches no rung
    of the community's own."""
    guard = deps.require_guild_roles(CommunityRole.member)
    await guard(_context(CommunityRole.superadmin))
    with pytest.raises(HTTPException):
        await guard(_context(CommunityRole.support))
