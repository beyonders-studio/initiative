"""What the per-guild query role can and cannot do.

These assertions *attempt* each operation and require an error, rather than
reading a grant — a grant can be read correctly and still not be the whole
answer, because ownership, defaults and PUBLIC all grant on their own.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.db.schema_provisioning import (
    GuildRoleKind,
    guild_role_name,
    drop_guild_schema,
    guild_schema_name,
    provision_guild_schema,
)


_GID = 990_140
_GID_OTHER = 990_141


@pytest.fixture
async def provisioned(engine):
    """Two provisioned guilds, so "another guild's schema" is a real place."""
    async with engine.begin() as conn:
        await provision_guild_schema(conn, _GID)
        await provision_guild_schema(conn, _GID_OTHER)
    try:
        yield guild_schema_name(_GID), guild_schema_name(_GID_OTHER)
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, _GID)
            await drop_guild_schema(conn, _GID_OTHER)


async def _as_query_role(conn, statement: str):
    """Run one statement as the query role, routed as a request would be.

    The search path is the guild's schema alone, as a query's is: the
    initiative-RLS policies defer to ``initiative_access``, whose body names
    ``initiative_members`` without a schema, so it resolves against the
    caller's path — the guild's own membership table.
    """
    schema = guild_schema_name(_GID)
    await conn.exec_driver_sql(
        f'SET ROLE "{guild_role_name(_GID, GuildRoleKind.query)}"'
    )
    await conn.exec_driver_sql(f'SET search_path = "{schema}"')
    try:
        return await conn.execute(text(statement))
    finally:
        await conn.rollback()
        await conn.exec_driver_sql("RESET ROLE")
        await conn.exec_driver_sql("RESET search_path")


async def test_it_can_read_its_own_schema(engine, provisioned):
    schema, _ = provisioned
    async with engine.connect() as conn:
        result = await _as_query_role(conn, f"SELECT count(*) FROM {schema}.tasks")
        assert result.scalar() == 0


async def test_initiative_rls_still_applies_to_it(engine, provisioned):
    """The policies read the request's identity, not its role, so a query runs
    under the same initiative scoping as any other read.

    ``projects`` is initiative-scoped; ``initiatives`` itself deliberately is
    not, being guild-scoped by the schema boundary. With no identity set the
    row-level answer is none — and the owning role seeing the row is what
    shows the difference is the policy rather than an empty table.
    """
    schema, _ = provisioned
    async with engine.begin() as conn:
        initiative_id = await conn.scalar(
            text(
                f"INSERT INTO {schema}.initiatives (name, created_at, updated_at) "
                "VALUES ('i', now(), now()) RETURNING id"
            ),
        )
        await conn.execute(
            text(
                f"INSERT INTO {schema}.projects (name, initiative_id, "
                "archived_at, is_template, comments_enabled, "
                "created_at, updated_at) "
                "VALUES ('p', :i, NULL, false, true, now(), now())"
            ),
            {"i": initiative_id},
        )

    async with engine.connect() as conn:
        owner_sees = await conn.scalar(text(f"SELECT count(*) FROM {schema}.projects"))
        result = await _as_query_role(conn, f"SELECT count(*) FROM {schema}.projects")
        assert owner_sees == 1
        assert result.scalar() == 0


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO {schema}.tasks (title) VALUES ('x')",
        "UPDATE {schema}.tasks SET title = 'x'",
        "DELETE FROM {schema}.tasks",
        "TRUNCATE {schema}.tasks",
    ],
)
async def test_it_cannot_write(engine, provisioned, statement):
    """Refused by the role, before any policy is consulted."""
    schema, _ = provisioned
    async with engine.connect() as conn:
        with pytest.raises((ProgrammingError, DBAPIError)):
            await _as_query_role(conn, statement.format(schema=schema))


async def test_it_cannot_create_anything(engine, provisioned):
    schema, _ = provisioned
    async with engine.connect() as conn:
        with pytest.raises((ProgrammingError, DBAPIError)):
            await _as_query_role(conn, f"CREATE TABLE {schema}.evil (id int)")


async def test_it_cannot_read_another_guilds_schema(engine, provisioned):
    """The tenancy boundary, from the role's side: one guild's query role has
    no reach into another guild's schema at all."""
    _, other = provisioned
    async with engine.connect() as conn:
        with pytest.raises((ProgrammingError, DBAPIError)):
            await _as_query_role(conn, f"SELECT count(*) FROM {other}.tasks")


async def test_the_login_role_holds_no_standing_access(engine, provisioned):
    """Membership is granted WITH INHERIT FALSE, so reaching the schema takes
    an explicit SET ROLE rather than merely being the app.

    The two halves are asserted separately because one implies the other:
    ``USAGE`` (privileges arrive by inheritance) is the half that must be
    false, and ``MEMBER`` (may SET ROLE) the half that must be true. A single
    expression combining them cannot tell the two settings apart.
    """
    role = guild_role_name(_GID, GuildRoleKind.query)
    async with engine.connect() as conn:
        standing = await conn.scalar(
            text("SELECT pg_has_role(:login, :role, 'USAGE')"),
            {"login": "app_user", "role": role},
        )
        may_assume = await conn.scalar(
            text("SELECT pg_has_role(:login, :role, 'MEMBER')"),
            {"login": "app_user", "role": role},
        )
        assert standing is False, "privileges should not arrive by inheritance"
        assert may_assume is True, "the login role should still be able to SET ROLE"


@pytest.mark.parametrize(
    "table", ["public.user_view_preferences", "public.user_tokens", "public.guilds"]
)
@pytest.mark.parametrize("verb", ["INSERT", "UPDATE", "DELETE"])
async def test_it_cannot_write_shared_tables(engine, provisioned, table, verb):
    """It inherits no shared floor to write through."""
    role = guild_role_name(_GID, GuildRoleKind.query)
    async with engine.connect() as conn:
        granted = await conn.scalar(
            text("SELECT has_table_privilege(:r, :t, :p)"),
            {"r": role, "t": table, "p": verb},
        )
        assert granted is False, f"{verb} on {table}"


@pytest.mark.parametrize(
    "table",
    [
        "public.community_rules",
        "public.access_grants",
        "public.app_settings",
        "public.guild_memberships",
        "public.guilds",
        "public.users",
    ],
)
async def test_it_cannot_read_shared_tables(engine, provisioned, table):
    """A query reads its own community, so no shared table is reachable."""
    async with engine.connect() as conn:
        with pytest.raises(ProgrammingError, match="permission denied"):
            await _as_query_role(conn, f"SELECT count(*) FROM {table}")


async def test_it_can_read_its_communitys_members(engine, provisioned):
    """The one thing in ``public`` it reads, which answers for the routed
    community alone."""
    async with engine.connect() as conn:
        await conn.exec_driver_sql(
            f"SELECT set_config('app.current_guild_id', '{_GID}', false)"
        )
        try:
            result = await _as_query_role(
                conn, "SELECT count(*) FROM public.current_guild_members"
            )
            assert result.scalar() == 0
        finally:
            await conn.exec_driver_sql("RESET app.current_guild_id")


async def test_the_catalogs_are_readable_like_any_role(engine, provisioned):
    """PostgreSQL grants the system catalogs to PUBLIC, so this role reads
    names from them as every role does. Recorded because the opposite is easy
    to assume."""
    async with engine.connect() as conn:
        result = await _as_query_role(conn, "SELECT count(*) FROM pg_catalog.pg_class")
        assert result.scalar() > 0


@pytest.mark.parametrize(
    ("what", "statement"),
    [
        ("password hashes", "SELECT count(*) FROM pg_catalog.pg_authid"),
        ("raw column statistics", "SELECT count(*) FROM pg_catalog.pg_statistic"),
        ("the filesystem", "SELECT pg_read_file('/etc/hostname')"),
    ],
)
async def test_the_privileged_catalogs_stay_privileged(
    engine, provisioned, what, statement
):
    """The parts PostgreSQL keeps for a superuser. This role is not one."""
    async with engine.connect() as conn:
        with pytest.raises((ProgrammingError, DBAPIError)):
            await _as_query_role(conn, statement)


async def test_another_guilds_statistics_are_not_readable(engine, provisioned):
    """``pg_stats`` reports only columns the reader may select, so the value
    distributions of a schema this role cannot read are absent from it."""
    _, other = provisioned
    async with engine.connect() as conn:
        result = await _as_query_role(
            conn,
            "SELECT count(*) FROM pg_stats WHERE schemaname = :s".replace(
                ":s", f"'{other}'"
            ),
        )
        assert result.scalar() == 0
