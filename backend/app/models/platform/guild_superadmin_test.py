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
    GUILD_STORED_ROLES,
    AdminSurface,
    Guild,
    GuildMembership,
    CommunityRole,
    assignable_roles,
)


def test_a_superadmin_carries_an_admins_authority():
    assert CommunityRole.superadmin.reaches(CommunityRole.admin)
    assert CommunityRole.superadmin in GUILD_ADMIN_ROLES


def test_a_member_still_does_not():
    assert not CommunityRole.member.reaches(CommunityRole.admin)
    assert CommunityRole.member not in GUILD_ADMIN_ROLES


def test_the_gate_asks_one_question_about_three_roles():
    """The reason a third stored role changed no policy.

    Every gate reads one fact — does this reader administer the community —
    and the standing statement computes it from the membership row with the
    two admin rungs named there, so the seat reaches what an admin reaches
    without any leg being rewritten.
    """
    assert GUILD_ADMIN_ROLES == {CommunityRole.admin, CommunityRole.superadmin}
    assert CommunityRole.superadmin in GUILD_STORED_ROLES
    assert CommunityRole.member not in GUILD_ADMIN_ROLES


def test_support_is_not_a_stored_role():
    """It is the identity a grant carries for the length of its request, so no
    membership row holds it and no routing can be asked for it."""
    assert CommunityRole.support not in GUILD_STORED_ROLES
    assert GUILD_STORED_ROLES == frozenset(CommunityRole) - {CommunityRole.support}


def test_an_ordinary_admin_cannot_hand_out_the_seat():
    """The separation: administering a community is not deciding who enters."""
    assert CommunityRole.superadmin not in assignable_roles(CommunityRole.admin)
    assert assignable_roles(CommunityRole.admin) == GUILD_ASSIGNABLE_ROLES


def test_the_seat_is_passed_on_by_whoever_holds_it():
    """A superadmin seats another, so the guild carries on without going back
    to the platform for every change."""
    allowed = assignable_roles(CommunityRole.superadmin)
    assert CommunityRole.superadmin in allowed
    assert {CommunityRole.admin, CommunityRole.member} <= allowed


def test_support_is_never_assignable_by_anybody():
    """A synthesized PAM identity, not a stored membership role."""
    for by in (CommunityRole.admin, CommunityRole.superadmin, CommunityRole.member):
        assert CommunityRole.support not in assignable_roles(by)


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


def test_the_context_answers_admin_or_above():
    assert _context(CommunityRole.admin).is_admin
    assert _context(CommunityRole.superadmin).is_admin
    assert not _context(CommunityRole.member).is_admin


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


def test_a_claim_rule_cannot_name_the_seat():
    """What an identity provider's rules may hand out.

    The mapping surface stores a role as a string, and the set it validates
    against is derived from the same one the guild's own endpoints use, so the
    seat stays off it by construction rather than by a second list agreeing.
    """
    from app.services.auth.guild_claim_rules import MAPPABLE_GUILD_ROLES

    assert CommunityRole.superadmin.value not in MAPPABLE_GUILD_ROLES
    assert CommunityRole.support.value not in MAPPABLE_GUILD_ROLES
    assert MAPPABLE_GUILD_ROLES == {r.value for r in GUILD_ASSIGNABLE_ROLES}
