"""
Smoke tests to verify test infrastructure is working correctly.

These tests validate that the test database, fixtures, and basic
testing setup are functioning properly.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import AUTH_ACCESS_AUDIENCE, TOKEN_ISSUER
from app.models.platform.user import UserStatus
from app.services.auth.subject import user_for_subject
from app.testing.factories import (
    create_user,
    get_auth_headers,
    get_auth_token,
)


async def test_database_session(session: AsyncSession):
    """Test that database session fixture works."""
    assert session is not None
    assert isinstance(session, AsyncSession)


async def test_create_user_factory(session: AsyncSession):
    """Test that user factory creates users correctly."""
    user = await create_user(
        session,
        email="factory-test@example.com",
    )

    assert user.id is not None
    assert user.seeded_address == "factory-test@example.com"
    assert user.status == UserStatus.active
    assert user.hashed_password is not None


async def test_http_client(client: AsyncClient):
    """Test that HTTP client fixture works."""
    assert client is not None
    assert isinstance(client, AsyncClient)


async def test_version_endpoint(client: AsyncClient):
    """Test the version endpoint to verify API is working."""
    response = await client.get("/api/v1/version")
    assert response.status_code == 200
    data = response.json()
    assert "version" in data


async def test_authenticated_request(client: AsyncClient, session: AsyncSession):
    """Test that authenticated requests work with auth headers."""
    # Create a test user
    user = await create_user(session, email="auth-test@example.com")

    # Get auth headers
    headers = get_auth_headers(user)

    # Make authenticated request
    response = await client.get("/api/v1/me", headers=headers)
    assert response.status_code == 200

    data = response.json()
    assert data["email"] == "auth-test@example.com"
    assert data["id"] == user.id


async def test_acting_user_builds_guild_workspace(client: AsyncClient, acting_user):
    """The Actor seam provisions a guild + initiative + project and mints
    headers that work through the real-role request path."""
    from app.models.platform.guild import CommunityRole
    from app.models.platform.user import UserRole

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    # Guild-path actors default to the LOWEST platform tier: guild access
    # must never depend on platform privileges.
    assert a.user.role == UserRole.member
    assert a.guild is not None and a.initiative is not None and a.project is not None

    response = await client.get(a.g("/projects/"), headers=a.headers)
    assert response.status_code == 200
    assert any(p["id"] == a.project.id for p in response.json()["items"])

    # A second actor joining the same guild/initiative at member level.
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    response = await client.get(b.g("/initiatives/"), headers=b.headers)
    assert response.status_code == 200
    assert any(i["id"] == a.initiative.id for i in response.json())


async def test_tenant_rows_land_in_guild_schema(session: AsyncSession, acting_user):
    """Factory-created tenant rows live in guild_<id>, not public (which no
    longer has tenant tables since the baseline squash)."""
    from sqlalchemy import text

    a = await acting_user(guild_role="admin", initiative=True, project=True)
    count = (
        await session.exec(
            text(  # type: ignore[call-overload]
                f'SELECT count(*) FROM "guild_{a.guild.id}".projects'
            )
        )
    ).scalar()
    assert count == 1


async def test_a_pooled_guild_schema_comes_back_as_built(session: AsyncSession, engine):
    """A guild schema is parked out of sight between tests and handed back
    empty, with its ids starting over; one a test changed is not parked, and
    one whose roles went while it was parked is not handed back."""
    from sqlalchemy import text

    from app.db.guild_migrations import GUILD_SCHEMA_REGEX
    from app.db import schema_provisioning
    from app.db.schema_provisioning import drop_guild_schema, get_provisioning_bundle
    from app.testing import create_guild, create_initiative, guild_pool

    if not guild_pool.ENABLED:
        pytest.skip("PYTEST_GUILD_POOL=0")
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_initiative(session, guild, user)
    gid, schema = guild.id, f"guild_{guild.id}"
    await session.commit()

    assert await guild_pool.park(engine, gid)
    async with engine.connect() as conn:
        visible = await conn.scalar(
            text("SELECT count(*) FROM pg_namespace WHERE nspname ~ :p"),
            {"p": GUILD_SCHEMA_REGEX},
        )
    assert visible == 0

    stamp = (await get_provisioning_bundle()).stamp
    assert await guild_pool.activate(engine, gid, stamp) is True
    async with engine.connect() as conn:
        rows = await conn.scalar(text(f'SELECT count(*) FROM "{schema}".initiatives'))
        drawn = await conn.scalar(
            text(
                "SELECT count(*) FROM pg_sequences "
                "WHERE schemaname = :s AND last_value IS NOT NULL"
            ),
            {"s": schema},
        )
    assert (rows, drawn) == (0, 0)

    # Dropping a guild's roles while its schema is parked retires the schema.
    assert await guild_pool.park(engine, gid)
    async with engine.begin() as conn:
        await drop_guild_schema(conn, gid)
    assert await guild_pool.activate(engine, gid, stamp) is False
    await schema_provisioning.provision_guild(gid)

    # A grant reaches no event trigger; the permissions check catches it.
    async with engine.begin() as conn:
        await conn.execute(text(f'GRANT SELECT ON "{schema}".initiatives TO app_user'))
    assert schema not in await guild_pool.take_changed(engine)
    assert not await guild_pool.park(engine, gid)

    async with engine.begin() as conn:
        await conn.execute(
            text(f'ALTER TABLE "{schema}".initiatives ADD COLUMN probe int')
        )
    assert schema in await guild_pool.take_changed(engine)


async def test_a_parked_schema_whose_roles_went_does_not_outlive_the_session(
    session: AsyncSession, engine
):
    """A session that starts with a parked schema whose roles are gone drops
    it, rather than taking the missing roles as what the slot should hold."""
    from sqlalchemy import text

    from app.db.schema_provisioning import drop_guild_schema
    from app.testing import create_guild, guild_pool

    if not guild_pool.ENABLED:
        pytest.skip("PYTEST_GUILD_POOL=0")
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    gid = guild.id
    await session.commit()

    assert await guild_pool.park(engine, gid)
    async with engine.begin() as conn:
        await drop_guild_schema(conn, gid)

    await guild_pool.install(engine)
    async with engine.connect() as conn:
        parked = await conn.scalar(
            text("SELECT to_regnamespace(:p) IS NOT NULL"),
            {"p": guild_pool.parked_name(gid)},
        )
    assert not parked


async def test_unrouted_tenant_write_fails_closed(session: AsyncSession, acting_user):
    """A tenant write that carries no guild_id on an unrouted session must
    raise the harness's explicit error, not fall through toward public."""
    from sqlalchemy import text

    from app.models.tenant.task import TaskAssignee

    a = await acting_user(guild_role="admin")
    # Un-route the session, then write a guild_id-less junction row. The
    # router raises in before_flush, so no SQL (and no FK check) ever runs.
    await session.exec(
        text("SELECT set_config('search_path', 'public', false)")  # type: ignore[call-overload]
    )
    session.add(TaskAssignee(task_id=1, user_id=a.user.id))
    with pytest.raises(RuntimeError, match="not routed to a guild schema"):
        await session.commit()
    await session.rollback()


async def test_the_factory_mints_the_token_the_app_issues(session: AsyncSession):
    """What the suite authenticates with is the shipped session credential, not
    the pre-session scheme beside it. Every endpoint test rides on this, so it
    is pinned here rather than left to whichever test happens to notice."""
    import jwt as pyjwt

    user = await create_user(session, email="factory-token@example.com")
    claims = pyjwt.decode(
        get_auth_token(user),
        options={"verify_signature": False},
        audience=AUTH_ACCESS_AUDIENCE,
    )

    assert claims["aud"] == AUTH_ACCESS_AUDIENCE
    assert claims["iss"] == TOKEN_ISSUER
    # Named by reference, and the reference resolves back to this account —
    # asserting only the first half would pass for any opaque string.
    assert claims["sub"] != str(user.id)
    assert await user_for_subject(session, subject=claims["sub"]) == user
    assert claims["ver"] == user.token_version
    assert claims["sid"]
    # What a password sign-in carries: a factor, and no provider satisfied.
    assert claims["amr"] == ["pwd"]
    assert claims["sat"] == []


async def test_a_factory_token_can_carry_a_satisfied_provider(session: AsyncSession):
    """A guild's sign-in policy is satisfied by what the token says, so a test
    of a policy-gated guild states it here."""
    import jwt as pyjwt

    user = await create_user(session, email="factory-sat@example.com")
    claims = pyjwt.decode(
        get_auth_token(user, satisfied_providers=[4, 9], amr=["oidc:corp"]),
        options={"verify_signature": False},
        audience=AUTH_ACCESS_AUDIENCE,
    )

    assert claims["sat"] == [4, 9]
    assert claims["amr"] == ["oidc:corp"]
