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
from app.services.platform import app_settings as app_settings_service
from app.testing import (
    create_access_grant,
    create_file,
    create_guild,
    create_initiative,
    create_project,
    create_user,
    create_wiki,
)
from app.testing.schema_harness import route_session_to_guild


async def _set_app_user(session: AsyncSession) -> None:
    await session.exec(text("SET ROLE app_user"))


async def _reset_role(session: AsyncSession) -> None:
    await session.exec(text("RESET ROLE"))


async def test_pam_read_grant_sees_only_granted_guild(
    session: AsyncSession, reading_as
):
    """A live read grant reads the granted guild's row and content, files and
    wikis included, and nothing of another guild; it writes nothing. Wikis
    carry a policy that reads ``current_guild_id``, which a grantee leaves
    unset, so the read also proves that read is NULLIF-guarded."""
    owner = await create_user(session, email="owner@example.com", role=UserRole.owner)
    support = await create_user(
        session, email="support@example.com", role=UserRole.support
    )

    guild_a = await create_guild(session, creator=owner)
    init_a = await create_initiative(session, guild_a, owner)
    proj_a = await create_project(session, init_a, owner, name="Alpha")
    doc_a = await create_file(session, init_a, owner, name="Alpha Doc")
    wiki_a = await create_wiki(session, init_a, owner)

    guild_b = await create_guild(session, creator=owner)
    init_b = await create_initiative(session, guild_b, owner)
    await create_project(session, init_b, owner, name="Bravo")

    await create_access_grant(session, user=support, guild=guild_a)
    reader = await reading_as(support.id, guild_a.id)

    async def visible(statement: str, **params) -> int:
        return len((await reader.exec(text(statement), params=params)).all())

    # The guild row itself: the seam fetches it to build the request context.
    assert await visible("SELECT id FROM guilds WHERE id = :g", g=guild_a.id) == 1
    for table, row in (
        ("initiatives", init_a),
        ("projects", proj_a),
        ("files", doc_a),
        ("wikis", wiki_a),
    ):
        assert await visible(f"SELECT id FROM {table} WHERE id = :i", i=row.id) == 1, (
            f"read grant should see the granted guild's {table}"
        )
    # Guild B's project lives in another schema. (Queried by name — its
    # per-schema id collides with A's.)
    assert await visible("SELECT id FROM projects WHERE name = 'Bravo'") == 0

    # The read-only role has no write on the schema.
    with pytest.raises(DBAPIError):
        await reader.exec(
            text("UPDATE projects SET name = 'edited' WHERE name = 'Alpha'")
        )
    await reader.rollback()


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
