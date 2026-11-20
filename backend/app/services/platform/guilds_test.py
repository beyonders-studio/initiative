"""
Unit tests for guild service functions.

Tests the business logic in app.services.guilds including:
- Guild creation and management
- Membership management
- Invite generation and redemption
- Guild resolution and permissions
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import text
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import post_commit
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.models.platform.guild import CommunityRole
from app.models.tenant.initiative import InitiativeMember, InitiativeRoleModel
from app.services.platform import guilds as guild_service
from app.testing import community_plan
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_user,
)
from app.testing.routing import platform_session
from app.testing.schema_harness import route_session_to_guild


async def test_get_primary_guild_creates_if_missing(session: AsyncSession):
    """Test that primary guild is created if none exists."""
    # Clear any migration-seeded guilds so we test the creation path
    await session.exec(text("TRUNCATE TABLE guilds RESTART IDENTITY CASCADE"))
    guild = await guild_service.get_primary_guild(session)

    assert guild.id is not None
    assert guild.name == "Primary Community"
    assert guild.description == "Default community"
    # The bootstrap seed is a guild-creation path like any other, so it owes the
    # same companion row: without it the operator dashboard has no caps to show
    # and get_administration raises for the one guild a fresh install has.
    administration = await guild_service.get_administration(session, guild_id=guild.id)
    assert administration.tier_name is None
    plan = await community_plan(session, guild.id)
    assert (plan["max_storage_bytes"], plan["max_users"]) == (None, None)
    assert not (plan["community_sign_in"] or plan["security_standards"])


async def test_get_primary_guild_seed_warns_when_users_exist(
    session: AsyncSession, caplog
):
    """Zero guilds beside existing users is either a deliberate all-guilds-
    deleted state or a session that cannot see the real rows (wrong database
    target, blinded system engine) — the seed must say so in the log instead
    of silently creating a fresh default guild."""
    await session.exec(text("TRUNCATE TABLE guilds RESTART IDENTITY CASCADE"))
    await create_user(session)

    with caplog.at_level("WARNING", logger="app.services.platform.guilds"):
        guild = await guild_service.get_primary_guild(session)

    assert guild.name == "Primary Community"
    assert any(
        "creating a default primary guild" in record.getMessage()
        for record in caplog.records
    )


async def test_get_primary_guild_seed_warns_when_guild_schemas_survive(
    session: AsyncSession, caplog
):
    """A blinded session reads zero rows in users as well as guilds, so row
    counts alone can't flag it — but guild_<id> schemas live in the catalog,
    which row-level security never filters. Seeding beside surviving guild
    schemas must warn."""
    from app.db import session as db_session
    from app.db.schema_provisioning import drop_guild_schema, provision_guild

    gid = 990_301  # synthetic high id, mirrors the provisioning tests
    await session.exec(text("TRUNCATE TABLE users, guilds RESTART IDENTITY CASCADE"))
    await session.commit()
    await provision_guild(gid)
    try:
        with caplog.at_level("WARNING", logger="app.services.platform.guilds"):
            guild = await guild_service.get_primary_guild(session)

        assert guild.name == "Primary Community"
        assert any(
            "the database is not fresh" in record.getMessage()
            for record in caplog.records
        )
    finally:
        async with db_session.provisioning_engine.begin() as conn:
            await drop_guild_schema(conn, gid)


async def test_get_primary_guild_returns_existing(session: AsyncSession):
    """Test that existing guild is returned as primary."""
    # Create a guild first
    first_guild = await create_guild(session, name="First Guild")

    # Get primary guild should return this one
    primary = await guild_service.get_primary_guild(session)

    assert primary.id == first_guild.id
    assert primary.name == "First Guild"


async def test_concurrent_joins_cannot_exceed_user_cap(session: AsyncSession, engine):
    """Concurrent joins racing for the last seat can't overshoot the cap.

    Six users try to join a guild with ``max_users=1`` at the same instant, each
    on its OWN connection/transaction (real concurrency, not one shared session).
    The per-guild advisory lock in ``_assert_member_capacity`` serializes the
    count-then-insert, so exactly one joiner wins the seat and the other five get
    ``GuildCapacityError`` — the guild never exceeds its cap. Without the lock,
    several would each read the pre-insert count of 0 and all commit (the TOCTOU
    race this guards against).
    """
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    # Room for exactly one member, and none yet.
    guild = await create_guild(session, max_users=1)
    joiners = [
        await create_user(session, email=f"race-joiner-{i}@example.com")
        for i in range(6)
    ]
    # Commit so the independent worker connections below can see the guild + users.
    await session.commit()

    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def try_join(user_id: int) -> bool:
        """Attempt one join on a fresh connection; True if it claimed the seat."""
        async with maker() as worker:
            try:
                await guild_service.ensure_membership(
                    worker,
                    guild_id=guild.id,
                    user_id=user_id,
                    role=CommunityRole.member,
                )
                await worker.commit()
                return True
            except guild_service.GuildCapacityError:
                await worker.rollback()
                return False

    results = await asyncio.gather(*(try_join(u.id) for u in joiners))

    # Exactly one winner, and the guild sits at — never above — its cap.
    assert sum(results) == 1
    assert await guild_service.count_members(session, guild_id=guild.id) == 1


async def test_ensure_membership_force_role_updates(session: AsyncSession):
    """Test that force_role updates an existing membership's role."""
    user = await create_user(session)
    guild = await create_guild(session)

    # Create as member
    await create_guild_membership(
        session,
        user=user,
        guild=guild,
        role=CommunityRole.member,
    )

    # Force upgrade to admin
    membership = await guild_service.ensure_membership(
        session,
        guild_id=guild.id,
        user_id=user.id,
        role=CommunityRole.admin,
        force_role=True,
    )

    assert membership.role == CommunityRole.admin


async def test_get_guild_retention_days_distinguishes_never_from_missing(
    session: AsyncSession,
):
    """retention_days = NULL is the user's explicit "never auto-purge"
    choice. The helper must surface None in that case (not silently
    fall back to the 90-day default), and only fall back to 90 when no
    guild_settings row exists at all.

    Regression: a previous version selected GuildSetting.retention_days
    directly and conflated "row present with NULL" and "no row" — both
    came back as None from one_or_none(), so the fallback re-enabled
    auto-purge for guilds that opted out.
    """
    from app.models.tenant.guild_setting import GuildSetting
    from app.testing import route_session_to_guild

    # 1. No guild_settings row at all -> default 90.
    guild = await create_guild(session)
    # guild_settings is guild-scoped: its rows live only in guild_<id> post-squash,
    # so route the session there before reading it (production callers route too).
    await route_session_to_guild(session, guild.id)
    setting = (await session.exec(select(GuildSetting))).one()
    await session.delete(setting)
    await session.commit()
    await route_session_to_guild(session, guild.id)
    assert (await guild_service.get_guild_retention_days(session)) == 90

    # 2. Row exists with retention_days = 30 -> 30.
    setting = GuildSetting(retention_days=30)
    session.add(setting)
    await session.commit()
    await route_session_to_guild(session, guild.id)
    assert (await guild_service.get_guild_retention_days(session)) == 30

    # 3. Row exists with retention_days = NULL -> None ("never").
    setting.retention_days = None
    session.add(setting)
    await session.commit()
    await route_session_to_guild(session, guild.id)
    assert (await guild_service.get_guild_retention_days(session)) is None


async def test_list_memberships_reads_retention_per_guild(session: AsyncSession):
    """retention_days lives in each guild's own schema. The guild list must read
    it per guild with the user's context — a single cross-guild join hits the
    empty public guild_settings and reports NULL for everyone."""
    from app.models.tenant.guild_setting import GuildSetting

    user = await create_user(session)

    guild_30 = await create_guild(session, creator=user)
    await create_guild_membership(
        session, user=user, guild=guild_30, role=CommunityRole.admin
    )
    await route_session_to_guild(session, guild_30.id)
    setting = (await session.exec(select(GuildSetting))).one()
    setting.retention_days = 30
    session.add(setting)
    await session.commit()

    # A guild with the seeded settings row keeps the 90-day default.
    guild_default = await create_guild(session, creator=user)
    await create_guild_membership(
        session, user=user, guild=guild_default, role=CommunityRole.admin
    )
    await session.commit()

    async with platform_session(user) as caller:
        memberships = await guild_service.list_memberships(caller, user_id=user.id)
    by_guild = {
        guild.id: retention
        for guild, _membership, retention, _count, _admin, _api in memberships
    }

    assert by_guild[guild_30.id] == 30  # read from the guild's own schema
    assert by_guild[guild_default.id] == 90  # the seeded default


# ============================================================================
# Auto-join enrolment (discovery §5): the hook on the genuine-join chokepoint
# ============================================================================


async def _initiative_role_names(
    session: AsyncSession, *, guild_id: int, user_id: int
) -> dict[int, str]:
    """The initiatives ``user_id`` belongs to in ``guild_id``, by role name."""
    await route_session_to_guild(session, guild_id)
    rows = (
        await session.exec(
            select(InitiativeMember, InitiativeRoleModel)
            .join(
                InitiativeRoleModel,
                InitiativeRoleModel.id == InitiativeMember.role_id,
            )
            .where(InitiativeMember.user_id == user_id)
        )
    ).all()
    return {member.initiative_id: role.name for member, role in rows}


async def test_archived_and_deleted_auto_join_initiatives_are_skipped(
    session: AsyncSession,
):
    """An initiative nobody can open is not somewhere to land."""
    from datetime import datetime as _datetime

    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    live = await create_initiative(
        session, guild, admin, name="Live", join_policy="open", auto_join=True
    )
    archived = await create_initiative(
        session,
        guild,
        admin,
        name="Archived",
        join_policy="open",
        auto_join=True,
        archived_at=datetime.now(UTC),
    )
    deleted = await create_initiative(
        session,
        guild,
        admin,
        name="Deleted",
        join_policy="open",
        auto_join=True,
        deleted_at=_datetime.now(UTC),
    )

    joiner = await create_user(session, email="joiner@example.com")
    await guild_service.ensure_membership(session, guild_id=guild.id, user_id=joiner.id)
    await session.commit()
    await post_commit.settle(session)

    roles = await _initiative_role_names(session, guild_id=guild.id, user_id=joiner.id)
    assert set(roles) == {live.id}
    assert archived.id not in roles
    assert deleted.id not in roles


async def test_returning_member_is_not_re_enrolled(session: AsyncSession):
    """Enrolment is onboarding, not a sweep: someone already in the guild is
    returned early and picks up nothing, even if auto-join was switched on
    after they arrived."""
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    member = await create_user(session, email="member@example.com")
    await create_guild_membership(session, user=member, guild=guild)
    later = await create_initiative(
        session, guild, admin, name="Added later", join_policy="open", auto_join=True
    )

    await guild_service.ensure_membership(session, guild_id=guild.id, user_id=member.id)
    await session.commit()
    await post_commit.settle(session)

    roles = await _initiative_role_names(session, guild_id=guild.id, user_id=member.id)
    assert later.id not in roles


async def test_guild_admin_is_not_enrolled_as_a_member(session: AsyncSession):
    """A guild admin already reaches every initiative in their guild, and the
    built-in member role is one they must never hold."""
    founder = await create_user(session)
    guild = await create_guild(session, creator=founder)
    welcome = await create_initiative(
        session, guild, founder, name="Welcome", join_policy="open", auto_join=True
    )

    second_admin = await create_user(session, email="admin2@example.com")
    await guild_service.ensure_membership(
        session, guild_id=guild.id, user_id=second_admin.id, role=CommunityRole.admin
    )
    await session.commit()
    await post_commit.settle(session)

    roles = await _initiative_role_names(
        session, guild_id=guild.id, user_id=second_admin.id
    )
    assert welcome.id not in roles


async def test_enrolment_failure_does_not_fail_the_join(session: AsyncSession, caplog):
    """An initiative that cannot take a member is logged and skipped; the guild
    join stands and the other initiatives still enrol."""
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    broken = await create_initiative(
        session, guild, admin, name="Broken", join_policy="open", auto_join=True
    )
    healthy = await create_initiative(
        session, guild, admin, name="Healthy", join_policy="open", auto_join=True
    )
    # An initiative whose built-in member role is gone can take no joiner.
    await route_session_to_guild(session, guild.id)
    await session.exec(
        delete(InitiativeRoleModel).where(
            InitiativeRoleModel.initiative_id == broken.id,
            InitiativeRoleModel.name == "member",
        )
    )
    await session.commit()

    joiner = await create_user(session, email="joiner@example.com")
    with caplog.at_level(logging.ERROR):
        membership = await guild_service.ensure_membership(
            session, guild_id=guild.id, user_id=joiner.id
        )
        await session.commit()
        await post_commit.settle(session)

    assert membership.role == CommunityRole.member
    roles = await _initiative_role_names(session, guild_id=guild.id, user_id=joiner.id)
    assert set(roles) == {healthy.id}
    assert any("auto-join" in record.message for record in caplog.records)


# --- The lock that orders seat and sign-in-requirement changes ---------------


async def _try_lock(probe, guild_id: int) -> bool:
    """Whether a second connection can still take one guild's seat lock."""
    return await advisory_lock(probe, LockNamespace.GUILD_SEATS, guild_id, wait=False)


async def test_the_seat_lock_excludes_another_connection(session, role_session):
    """The paths that could leave a sign-in requirement unliftable do not all
    write on the connection that asks the question, so what orders them has to
    reach across connections. This is that, demonstrated.
    """
    from app.testing.factories import create_guild

    guild = await create_guild(session)
    elsewhere = await create_guild(session)
    guild_id, elsewhere_id = guild.id, elsewhere.id

    await guild_service.lock_guild_seats(session, guild_id)

    probe = await role_session("app_admin")
    assert await _try_lock(probe, guild_id) is False, (
        "a second connection must wait for this guild's seat lock"
    )
    # And it is per guild, not a global gate: every other community carries on.
    assert await _try_lock(probe, elsewhere_id) is True
    await probe.rollback()

    # Transaction-scoped, so ending this one hands it on. That is also what
    # makes it safe behind a transaction-mode pooler, which CI runs.
    await session.rollback()
    probe_again = await role_session("app_admin")
    assert await _try_lock(probe_again, guild_id) is True
    await probe_again.rollback()
