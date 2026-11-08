"""Phase 2 platform-role RLS ceilings (migration 0109).

These assert the *DB backstop* added in Phase 2: on the purely-platform tables
(``users``, ``access_grants``, ``app_settings``) a tier physically cannot exceed its
privilege, independent of the app-layer capability checks.

Two complementary styles:

* **Direct ``SET ROLE`` (DB-level).** The ``session`` fixture connects as the
  superuser, but ``SET ROLE platform_<tier>`` drops to a non-superuser role, so RLS
  and table GRANTs ARE enforced from that statement on — exactly like the production
  request path. This proves the policy/grant ceiling without the app layer in the
  way.
* **End-to-end (real-role ``client``).** An authenticated request assumes
  ``platform_<tier>`` on a real ``app_user`` connection, so the moved endpoints
  (operator user reads, owner config writes) run role-scoped, RLS-enforced.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.public_rls import platform_tier, role_name
from app.models.platform.user import UserRole
from app.testing import as_role, create_guild, create_user

# --- users ----------------------------------------------------------------


async def test_member_sees_only_own_user_row(session):
    """The member-tier floor: ``platform_base`` own-row only. A member can read
    their own ``users`` row but not anyone else's."""
    u1 = await create_user(session)
    u2 = await create_user(session)
    async with as_role(session, role_name(platform_tier("member")), u1.id):
        ids = {
            r[0] for r in (await session.exec(text("SELECT id FROM users"))).fetchall()
        }
    assert u1.id in ids
    assert u2.id not in ids


async def test_support_reads_all_users(session):
    """``users.read`` — support+ can SELECT every user row (``users_platform_read``)."""
    u1 = await create_user(session)
    u2 = await create_user(session)
    async with as_role(session, role_name(platform_tier("support")), u1.id):
        ids = {
            r[0] for r in (await session.exec(text("SELECT id FROM users"))).fetchall()
        }
    assert {u1.id, u2.id} <= ids


@pytest.mark.parametrize("tier", ["support", "moderator", "operator", "owner"])
async def test_no_tier_updates_another_account(session, tier):
    """An account is written by the person it names. Every tier reads every
    account (``users_platform_read``) and writes only its own
    (``users_platform_self``), so an UPDATE of someone else touches 0 rows.
    Platform user management runs on the system engine instead (0202)."""
    actor = await create_user(session)
    target = await create_user(session)

    async with as_role(session, role_name(platform_tier(tier)), actor.id):
        res = await session.exec(
            text("UPDATE users SET timezone = 'UTC' WHERE id = :id"),
            params={"id": target.id},
        )
    assert res.rowcount == 0


@pytest.mark.parametrize("tier", ["support", "moderator", "operator", "owner"])
async def test_every_tier_updates_its_own_account(session, tier):
    """The same policy is what lets a moderator edit their own profile."""
    actor = await create_user(session)

    async with as_role(session, role_name(platform_tier(tier)), actor.id):
        res = await session.exec(
            text("UPDATE users SET timezone = 'UTC' WHERE id = :id"),
            params={"id": actor.id},
        )
    assert res.rowcount == 1


async def test_no_tier_can_delete_users(session):
    """DELETE on ``public.users`` is revoked from every request-path floor
    (migration 0144); user rows are removed only on the system engine.
    An owner-tier request-path DELETE is therefore denied at the grant level
    (insufficient-privilege), not merely filtered to 0 rows."""
    actor = await create_user(session)
    target = await create_user(session)
    async with as_role(session, role_name(platform_tier("owner")), actor.id):
        with pytest.raises(DBAPIError):
            async with session.begin_nested():
                await session.exec(
                    text("DELETE FROM users WHERE id = :id"), params={"id": target.id}
                )


# --- access_grants --------------------------------------------------------


async def _insert_grant(session, user_id: int, guild_id: int) -> None:
    await session.exec(
        text(
            "INSERT INTO access_grants "
            "(user_id, guild_id, reason, requested_duration_minutes, requested_by_id) "
            "VALUES (:u, :g, 'r', 60, :u)"
        ),
        params={"u": user_id, "g": guild_id},
    )


async def test_access_grants_self_vs_approver(session):
    """A grantee sees only their own grant (``access_grants_self``); an
    ``access.approve`` holder sees the whole queue (``access_grants_admin``).
    There is no standing bypass."""
    guild = await create_guild(session)
    u1 = await create_user(session)
    u2 = await create_user(session)
    await _insert_grant(session, u1.id, guild.id)
    await _insert_grant(session, u2.id, guild.id)

    async with as_role(session, role_name(platform_tier("member")), u1.id):
        own = {
            r[0]
            for r in (
                await session.exec(text("SELECT user_id FROM access_grants"))
            ).fetchall()
        }
    assert own == {u1.id}

    async with as_role(session, role_name(platform_tier("operator")), u1.id):
        allrows = {
            r[0]
            for r in (
                await session.exec(text("SELECT user_id FROM access_grants"))
            ).fetchall()
        }
    assert {u1.id, u2.id} <= allrows


# --- app_settings (owner-only config) -------------------------------------


async def test_app_settings_write_is_owner_only(session):
    """Config writes are owner-only at the GRANT layer: a member's UPDATE raises
    insufficient-privilege (42501), the owner's lands."""
    owner = await create_user(session, role=UserRole.owner)
    member = await create_user(session, role=UserRole.member)
    await session.exec(
        text("INSERT INTO app_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
    )

    async with as_role(session, role_name(platform_tier("member")), member.id):
        with pytest.raises(DBAPIError):
            async with session.begin_nested():
                await session.exec(
                    text(
                        "UPDATE app_settings SET light_accent_color = '#000000' WHERE id = 1"
                    )
                )

    async with as_role(session, role_name(platform_tier("owner")), owner.id):
        res = await session.exec(
            text("UPDATE app_settings SET light_accent_color = '#abcdef' WHERE id = 1")
        )
    assert res.rowcount == 1


async def test_app_settings_readable_by_every_tier(session):
    """Everyone may SELECT config (``app_settings_read`` TO PUBLIC) — public reads
    like interface colors must work for any tier."""
    await session.exec(
        text("INSERT INTO app_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
    )
    member = await create_user(session, role=UserRole.member)
    async with as_role(session, role_name(platform_tier("member")), member.id):
        rows = (
            await session.exec(text("SELECT id FROM app_settings WHERE id = 1"))
        ).fetchall()
    assert len(rows) == 1


# NOTE: the env-reseed-on-read machinery was OIDC-only and is gone — OIDC env
# values now seed the platform provider registry row once at boot instead
# (platform_provider.seed_platform_provider_from_env). Reading the singleton
# creates nothing at all now: boot seeds it (app_settings.seed_app_settings)
# and get_app_settings serves env defaults transient until it has.


# --- end-to-end through the real-role request path ------------------------


async def test_support_can_list_users_role_scoped(client, acting_user):
    """The moved ``GET /operator/users`` runs as ``platform_support`` (off the
    engine) and the cross-user read is authorized by ``users_platform_read``."""
    a = await acting_user("support")
    resp = await client.get("/api/v1/operator/users", headers=a.headers)
    assert resp.status_code == 200
    assert any(u["id"] == a.user.id for u in resp.json()["items"])


async def test_member_cannot_list_users(client, acting_user):
    """The capability gate still holds above RLS: a member lacks ``users.read``."""
    a = await acting_user("member")
    resp = await client.get("/api/v1/operator/users", headers=a.headers)
    assert resp.status_code == 403


async def test_owner_can_update_interface_settings_role_scoped(client, acting_user):
    """The moved ``PUT /settings/interface`` runs as ``platform_owner`` and the
    owner-only GRANT + ``app_settings_owner`` policy let the write through."""
    a = await acting_user("owner")
    resp = await client.put(
        "/api/v1/settings/interface",
        headers=a.headers,
        json={"light_accent_color": "#123456", "dark_accent_color": "#654321"},
    )
    assert resp.status_code == 200
    assert resp.json()["light_accent_color"] == "#123456"


async def test_public_config_readable_without_write_privilege(client, acting_user):
    """A public config read works even for a non-owner when the singleton row is
    absent: the privilege-tolerant lazy-create degrades to a transient default
    instead of faulting on the owner-only write."""
    a = await acting_user("member")
    resp = await client.get("/api/v1/config", headers=a.headers)
    assert resp.status_code == 200
