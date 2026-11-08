"""Phase 1 platform-role ladder: roles exist, are least-privilege, and the
public/platform path assumes the right one.

NOTE on what these can and can't prove: the default ``session`` fixture connects
as the SUPERUSER, which can ``SET ROLE`` into any role and (without an assumed
role) bypasses RLS/GRANTs. So these assert the *catalog* shape (roles exist,
NOLOGIN, no BYPASSRLS) and that ``set_rls_context`` assumes the correct role name
— not that a tier hits a GRANT ceiling (that's Phase 2, and must be tested via the
real ``app_user`` login role, not the superuser session).
"""

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.db.public_rls import platform_tier, role_name
from app.db.request_context import Platform
from app.db.session import set_rls_context
from app.models.platform.user import UserRole

_TIERS = [role.value for role in UserRole]


async def _reset_role(session) -> None:
    await session.exec(text("SELECT set_config('role', 'none', false)"))


async def test_platform_roles_exist_and_are_least_privilege(session):
    """All five tiers + the base floor exist, are NOLOGIN, and crucially carry
    NO BYPASSRLS — the platform ladder never holds a standing all-guild bypass."""
    expected = {role_name("platform_base")} | {
        role_name(platform_tier(tier)) for tier in _TIERS
    }
    rows = (
        await session.exec(
            text(
                "SELECT rolname, rolcanlogin, rolbypassrls FROM pg_roles "
                "WHERE rolname ~ :pat"
            ),
            params={"pat": f"^{settings.PLATFORM_ROLE_PREFIX}platform_"},
        )
    ).all()
    found = {name: (canlogin, bypassrls) for name, canlogin, bypassrls in rows}

    for name in expected:
        assert name in found, f"platform role {name!r} was not created by the migration"
        canlogin, bypassrls = found[name]
        assert canlogin is False, f"{name} must be NOLOGIN"
        assert bypassrls is False, f"{name} must NOT carry BYPASSRLS (least privilege)"


async def test_each_tier_inherits_the_base_floor(session):
    """Each platform_<tier> is a member of platform_base, so assuming a tier
    yields the floor's privileges."""
    base = role_name("platform_base")
    members = (
        (
            await session.exec(
                text(
                    "SELECT m.rolname FROM pg_auth_members am "
                    "JOIN pg_roles base ON base.oid = am.roleid "
                    "JOIN pg_roles m ON m.oid = am.member "
                    "WHERE base.rolname = :base"
                ),
                params={"base": base},
            )
        )
        .scalars()
        .all()
    )
    for tier in _TIERS:
        assert role_name(platform_tier(tier)) in members


@pytest.mark.parametrize("tier", _TIERS)
async def test_public_path_assumes_platform_role(session, tier):
    """A no-guild request with a platform tier assumes platform_<tier>, not the
    bare login role."""
    await set_rls_context(session, Platform(user_id=1, tier=tier))
    current = (await session.exec(text("SELECT current_user"))).scalar_one()
    assert current == role_name(platform_tier(tier))
    await _reset_role(session)


async def test_no_tier_stays_on_login_role(session):
    """Without a platform tier the public path stays on the login role ('none'),
    preserving today's behavior for unauthenticated / service-layer callers."""
    await set_rls_context(session, Platform(user_id=1))
    # current_user is the connection's login role (superuser in tests); the point
    # is that no platform_* role was assumed.
    current = (await session.exec(text("SELECT current_user"))).scalar_one()
    assert not current.startswith(f"{settings.PLATFORM_ROLE_PREFIX}platform_")
    await _reset_role(session)


async def test_commit_preserves_platform_role(session):
    """The after_begin replay re-asserts the platform role on the transaction
    after a commit, so post-commit queries stay role-scoped with no manual
    reapply."""
    await set_rls_context(session, Platform(user_id=1, tier="support"))
    await session.commit()
    current = (await session.exec(text("SELECT current_user"))).scalar_one()
    assert current == role_name(platform_tier("support"))
    await _reset_role(session)


async def test_invalid_platform_role_rejected(session):
    """An off-ladder tier is rejected before reaching the SET ROLE name sink."""
    with pytest.raises(ValueError):
        await set_rls_context(session, Platform(user_id=1, tier="superuser"))


# --- acting_user harness (emulate a platform role through the request path) ---


async def test_acting_user_defaults_to_owner(client, acting_user):
    """The harness mints an owner by default (no guild_role) and the request path
    serves it."""
    a = await acting_user()
    assert a.user.role.value == "owner"
    # A personal-mode (UserSessionDep) endpoint runs AS platform_owner end to end.
    resp = await client.get("/api/v1/communities/", headers=a.headers)
    assert resp.status_code == 200


@pytest.mark.parametrize(
    "tier", ["member", "support", "moderator", "operator", "owner"]
)
async def test_acting_user_emulates_each_tier(client, acting_user, tier):
    """Any tier can be emulated; the public path serves all of them (Phase 1 keeps
    RLS unchanged, so every tier runs a personal-mode request like today)."""
    a = await acting_user(tier)
    assert a.user.role.value == tier
    resp = await client.get("/api/v1/communities/", headers=a.headers)
    assert resp.status_code == 200


@pytest.mark.parametrize("g_role", ["member", "admin"])
async def test_acting_user_optional_guild_role(client, acting_user, g_role):
    """The optional guild dimension: the harness provisions a guild + membership,
    and the guild-path request routes through guild_<id>, authorized by it. The
    platform tier (member) and the guild role are orthogonal — pass the tier
    explicitly since a guild_role actor defaults to platform member."""
    a = await acting_user("member", guild_role=g_role)
    assert a.user.role.value == "member"
    resp = await client.get(f"/api/v1/c/{a.guild.id}/initiatives/", headers=a.headers)
    assert resp.status_code == 200


async def test_platform_and_guild_roles_coexist(client, acting_user):
    """A user can hold BOTH a platform tier and a guild role at once, and the SAME
    identity uses the right role on each path:

      * public/platform path  -> assumes platform_<tier>  (here platform_member)
      * guild path (/c/{id}/…) -> assumes guild_<id> with current_guild_role=admin

    SET ROLE is single-valued per statement, so the two never conflict and neither
    costs the other. Uses a non-bypass platform tier (member) so the guild request
    is governed purely by the guild role, not data.bypass or any bypass flag.
    """
    a = await acting_user("member", guild_role="admin")

    public_resp = await client.get("/api/v1/communities/", headers=a.headers)
    assert public_resp.status_code == 200  # ran as platform_member

    guild_resp = await client.get(
        f"/api/v1/c/{a.guild.id}/initiatives/", headers=a.headers
    )
    assert guild_resp.status_code == 200  # ran as guild_<id> (admin), same identity
