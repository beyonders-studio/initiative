"""DB-level RLS isolation tests for PAM grants.

A grant is a row, and the establishment seam is the only thing that reads one:
it resolves the live rows, routes the session into the community at the level
they name, and recomputes their effect in the request's standing. So these
tests write the row and then enter through the seam, on the real request login
— the superuser the setup runs on cannot see a policy hide anything.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.guild_standing import GuildContext
from app.db.request_context import ContentGrantee, Platform
from app.db.schema_provisioning import guild_schema_name
from app.db.session import set_rls_context
from app.models.platform.user import UserRole
from app.models.tenant._mixins import ActorKind
from app.models.tenant.counter import CounterGroup
from app.models.tenant.file import File
from app.services.platform import app_settings as app_settings_service
from app.testing import (
    create_access_grant,
    create_guild,
    create_initiative,
    create_project,
    create_user,
)
from app.testing.schema_harness import route_session_to_guild


async def _set_app_user(session: AsyncSession) -> None:
    await session.exec(text("SET ROLE app_user"))


async def _reset_role(session: AsyncSession) -> None:
    await session.exec(text("RESET ROLE"))


async def test_pam_read_grant_sees_only_granted_guild(
    session: AsyncSession, reading_as
):
    owner = await create_user(session, email="owner@example.com", role=UserRole.owner)
    support = await create_user(
        session, email="support@example.com", role=UserRole.support
    )

    guild_a = await create_guild(session, creator=owner)
    init_a = await create_initiative(session, guild_a, owner)
    proj_a = await create_project(session, init_a, owner, name="Alpha")
    doc_a = File(
        initiative_id=init_a.id,
        name="Alpha Doc",
        content={},
        created_by=owner.id,
        created_by_kind=ActorKind.member,
    )
    session.add(doc_a)
    await session.commit()
    await session.refresh(doc_a)

    guild_b = await create_guild(session, creator=owner)
    init_b = await create_initiative(session, guild_b, owner)
    await create_project(session, init_b, owner, name="Bravo")

    # Live READ grant scoped to guild A, entered through the seam.
    await create_access_grant(session, user=support, guild=guild_a)
    reader = await reading_as(support.id, guild_a.id)

    # The rest of this test reads as the grantee.
    session = reader
    if True:
        # The guild row itself must be readable — get_guild_membership fetches
        # it to build the request context, so without this every guild-scoped
        # endpoint 500s for a grantee.
        visible_guild = (
            await session.exec(
                text("SELECT id FROM guilds WHERE id = :g"), params={"g": guild_a.id}
            )
        ).all()
        assert len(visible_guild) == 1, (
            "grantee must be able to read the granted guild row"
        )

        # Initiatives of the granted guild are visible (the sidebar list) — this
        # is the exact RLS path the empty-guild bug would break.
        visible_inits = (
            await session.exec(
                text("SELECT id FROM initiatives WHERE id = :i"),
                params={"i": init_a.id},
            )
        ).all()
        assert len(visible_inits) == 1, (
            "read grant should see the granted guild's initiatives"
        )

        visible_a = (
            await session.exec(
                text("SELECT id FROM projects WHERE id = :p"), params={"p": proj_a.id}
            )
        ).all()
        assert len(visible_a) == 1, "read grant should see the granted guild's project"

        # Files must be visible too — the collaboration WebSocket loads the
        # file under this exact pam_read context before authorizing.
        visible_doc = (
            await session.exec(
                text("SELECT id FROM files WHERE id = :d"), params={"d": doc_a.id}
            )
        ).all()
        assert len(visible_doc) == 1, "read grant should see the granted guild's files"

        # Cross-guild isolation: guild B's project lives in another schema, so it
        # is invisible here. (Query by name — its per-schema id collides with A's.)
        visible_b = (
            await session.exec(text("SELECT id FROM projects WHERE name = 'Bravo'"))
        ).all()
        assert len(visible_b) == 0, "read grant must NOT see other guilds"

        # Read grant is read-only: the read-only role has no write on the schema,
        # so a write is denied at the role level (raises permission denied).
        with pytest.raises(DBAPIError):
            await session.exec(
                text("UPDATE projects SET name = 'hacked' WHERE name = 'Alpha'")
            )
        await session.rollback()


async def test_grantee_guild_settings_lazy_create_does_not_fault(
    session: AsyncSession, reading_as
):
    """``get_or_create_guild_settings`` must not try to INSERT for a grantee.

    guild_settings is a config table off-limits to grants, so the lazy create
    would violate RLS and 500 the read-only ``/settings/ai/resolved`` (and any
    other settings read). A grantee gets a transient default instead.
    """
    owner = await create_user(
        session, email="owner-gs@example.com", role=UserRole.owner
    )
    support = await create_user(
        session, email="support-gs@example.com", role=UserRole.support
    )
    guild = await create_guild(session, creator=owner)
    # Start without the row the factory seeds, so the read takes the lazy create.
    await route_session_to_guild(session, guild.id)
    await session.exec(text("DELETE FROM guild_settings"))
    await session.commit()

    # Live READ grant scoped to the guild, entered through the seam.
    await create_access_grant(session, user=support, guild=guild)
    reader = await reading_as(support.id, guild.id)

    # Pre-fix this raised InsufficientPrivilegeError on the INSERT.
    row = await app_settings_service.get_or_create_guild_settings(reader, guild.id)
    assert row.id is None, "grantee settings must be transient, not persisted"
    await reader.rollback()

    # Nothing was written.
    await route_session_to_guild(session, guild.id)
    persisted = (
        await session.exec(
            text("SELECT count(*) FROM guild_settings"),
        )
    ).scalar_one()
    assert persisted == 0, "grantee read must not create a guild_settings row"


async def test_pam_read_grant_does_not_fault_legacy_isolation_tables(
    session: AsyncSession, reading_as
):
    """Tables with the legacy guild_isolation policy must not 500 for a grantee.

    A grantee leaves ``current_guild_id`` unset, so a policy that casts it to
    int without a NULLIF guard raises ``invalid input syntax for type integer``
    and faults the whole query (counters, …). This guards migration
    ``20260530_0095``.
    """
    owner = await create_user(session, email="owner4@example.com", role=UserRole.owner)
    support = await create_user(
        session, email="support4@example.com", role=UserRole.support
    )
    guild = await create_guild(session, creator=owner)
    init = await create_initiative(session, guild, owner)
    cg = CounterGroup(
        initiative_id=init.id,
        name="Stats",
        created_by=owner.id,
        created_by_kind=ActorKind.member,
    )
    session.add(cg)
    await session.commit()
    await session.refresh(cg)

    await create_access_grant(session, user=support, guild=guild)
    reader = await reading_as(support.id, guild.id)

    # This would raise InvalidTextRepresentationError pre-0095.
    visible_cg = (
        await reader.exec(
            text("SELECT id FROM counter_groups WHERE id = :c"), params={"c": cg.id}
        )
    ).all()
    assert len(visible_cg) == 1, (
        "read grant should see the granted guild's counter groups"
    )


async def test_no_pam_flag_sees_nothing(session: AsyncSession):
    """An INACTIVE grant (pam_guild_id set, but neither flag) must yield no access.

    The guild's ``projects`` live only in ``guild_<id>``.
    ``set_rls_context`` deliberately does NOT route an inactive
    grant into the guild schema (see the "don't route inactive grants" fix), so
    the fail-closed guarantee is at the schema/role boundary: the session stays on
    the public path with no guild role assumed, leaving the guild's schema entirely
    out of reach. We assert both halves — the context did not route in, and the
    guild's content is unreachable — so "sees nothing" is proven, not weakened."""
    owner = await create_user(session, email="owner2@example.com", role=UserRole.owner)
    support = await create_user(
        session, email="support2@example.com", role=UserRole.support
    )
    guild = await create_guild(session, creator=owner)
    init = await create_initiative(session, guild, owner)
    await create_project(session, init, owner, name="Gamma")

    try:
        await _set_app_user(session)
        # Same guild id, but the standing found no live grant — it is inactive.
        inactive = GuildContext(
            guild=None, user_id=support.id, guild_id=guild.id
        ).with_standing({"standing_guild_id": str(guild.id)})
        await set_rls_context(
            session,
            ContentGrantee(guild_id=guild.id, user_id=support.id, standing=inactive),
        )
        # An inactive grant is not routed: no guild role is assumed (set_rls_context
        # resets to the login role) and the guild schema is not on the search_path.
        current_role = (await session.exec(text("SELECT current_user"))).scalar_one()
        search_path = (await session.exec(text("SHOW search_path"))).scalar_one()
        assert guild_schema_name(guild.id) not in current_role
        assert guild_schema_name(guild.id) not in search_path
        # Under the real (non-privileged) app_user login role — which holds no
        # standing access to any guild schema (WITH INHERIT FALSE) — the guild's
        # content is denied at the catalog/role boundary, so the grantee sees
        # nothing.
        await _set_app_user(session)
        with pytest.raises(DBAPIError):
            await session.exec(
                text(f'SELECT id FROM "{guild_schema_name(guild.id)}".projects')
            )
        await session.rollback()
    finally:
        await _reset_role(session)


async def test_pam_write_grant_can_update(session: AsyncSession, reading_as):
    owner = await create_user(session, email="owner3@example.com", role=UserRole.owner)
    support = await create_user(
        session, email="support3@example.com", role=UserRole.support
    )
    guild = await create_guild(session, creator=owner)
    init = await create_initiative(session, guild, owner)
    proj = await create_project(session, init, owner, name="Delta")

    await create_access_grant(
        session, user=support, guild=guild, access_level="read_write"
    )
    reader = await reading_as(support.id, guild.id)

    result = await reader.exec(
        text("UPDATE projects SET name = 'edited' WHERE id = :p"),
        params={"p": proj.id},
    )
    assert result.rowcount == 1, "read_write grant should be able to update content"
    await reader.rollback()


async def test_request_role_cannot_self_insert_an_access_grant(session: AsyncSession):
    """Grant creation is system-engine-only (migration 0146): a routed
    request-path session is refused when it writes ``access_grants``, so the
    PAM/support path cannot be self-granted. Routed as the actor on the
    platform path; the write is denied at the role level."""
    attacker = await create_user(session, email="attacker@example.com")
    target = await create_guild(session)  # a guild the actor is not a member of

    try:
        await set_rls_context(session, Platform(user_id=attacker.id, tier="member"))
        with pytest.raises(Exception) as exc:
            await session.exec(
                text(
                    "INSERT INTO public.access_grants "
                    "(user_id, guild_id, access_level, status, reason, "
                    "requested_duration_minutes, requested_by_id, requested_at, "
                    "created_at, updated_at, expires_at) VALUES "
                    "(:uid, :gid, 'read_write', 'approved', 'ticket', 60, :uid, "
                    "now(), now(), now(), now() + interval '1 hour')"
                ),
                params={"uid": attacker.id, "gid": target.id},
            )
        assert "permission denied" in str(exc.value).lower(), (
            f"expected a grant-level denial on access_grants, got: {exc.value!r}"
        )
        await session.rollback()
    finally:
        await _reset_role(session)
