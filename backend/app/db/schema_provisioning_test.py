"""Tests for per-guild schema provisioning.

Use a synthetic, high guild id so the temporary ``guild_<id>`` schema can't
collide with real data, and drop it in teardown. Runs against the test DB as
the owning role (the ``engine`` fixture), which has DDL privileges.
"""

import asyncio
import re

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

import app.db.schema_provisioning as schema_provisioning
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db.guild_ddl import rendered_constraint_names, rendered_trigger_names
from app.db.registry_checks import registry_checks
from app.db.schema_provisioning import (
    GuildRoleKind,
    PLUGIN_ROLE_MACHINERY_READS,
    SUPPORT_WRITE_PROTECTED_TABLES,
    apply_guild_rls,
    strip_template_registry_objects,
    backfill_guild_schemas,
    drop_guild_schema,
    guild_role_name,
    guild_schema_name,
    provision_guild_schema,
    SYSTEM_LOGIN_ROLE,
)
from app.db.tenancy import GUILD_SCOPED_TABLES


# Synthetic ids well above any real guild; each test uses its own.
_GID_COMPLETE = 990_101
_GID_ISOLATION = 990_102
_GID_IDEMPOTENT = 990_103
_GID_ROLE_A = 990_104
_GID_ROLE_B = 990_105
_GID_ROLE_DROP = 990_106
_GID_ROLE_WRITE = 990_107
_GID_BACKFILL = 990_108
_GID_REPROVISION = 990_109
_GID_DROP_ABSENT = 990_110
_GID_SUPPORT = 990_120
_GID_READ_FLOOR = 990_121
_GID_SEAT = 990_122
_GID_RETIRED_A = 990_123
_GID_RETIRED_B = 990_124
_GID_PLUGIN = 990_125
_GID_PLUGIN_DENIED = 990_126
# Back-fill sweep (each pair: one provisioned, one only a public row).
_GID_BACKFILL_DONE = 990_111
_GID_BACKFILL_MISSING = 990_112
_GID_BACKFILL_DRIFT = 990_113
_GID_BACKFILL_OK_A = 990_114
_GID_BACKFILL_OK_B = 990_115
_GID_BACKFILL_FAIL = 990_116
_GID_BACKFILL_PARTIAL = 990_117
_GID_BACKFILL_HELD = 990_118


async def _insert_public_guild(conn, gid: int, name: str) -> None:
    """Insert a public.guilds row so guild-scoped FKs (-> public.guilds) hold."""
    await conn.execute(
        text(
            "INSERT INTO public.guilds (id, name, created_at, updated_at) "
            "VALUES (:id, :n, now(), now())"
        ),
        {"id": gid, "n": name},
    )


async def test_provision_creates_every_guild_scoped_table(engine):
    schema = guild_schema_name(_GID_COMPLETE)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, _GID_COMPLETE)
        async with engine.connect() as conn:
            res = await conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :s AND table_type = 'BASE TABLE'"
                ),
                {"s": schema},
            )
            created = {row[0] for row in res}
        assert created == set(GUILD_SCOPED_TABLES)
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, _GID_COMPLETE)


async def test_writes_route_to_guild_schema_not_public(engine):
    """A routed tenant write lands in the guild schema; an UNROUTED one fails.

    Isolation is the schema boundary itself: a tenant table exists only in
    ``guild_<id>``, so a write with the search_path still on ``public`` fails
    closed (relation does not exist)."""
    gid = _GID_ISOLATION
    schema = guild_schema_name(gid)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)
            await _insert_public_guild(conn, gid, "provision-iso-test")
            # Same unqualified INSERT, but routed via the guild search_path.
            await conn.exec_driver_sql(f'SET search_path TO "{schema}", public')
            # 9-char alpha color also exercises the widened tags.color column.
            await conn.execute(
                text(
                    "INSERT INTO tags (name, color, created_at, updated_at) "
                    "VALUES (:n, '#abcdef80', now(), now())"
                ),
                {"n": "iso-tag"},
            )
            await conn.exec_driver_sql("SET search_path TO public")

            in_guild = await conn.scalar(text(f'SELECT count(*) FROM "{schema}".tags'))
        assert in_guild == 1, "row should be in the guild schema"

        # A tenant table exists only in guild schemas, so an unrouted (public
        # search_path) tenant write fails closed.
        async with engine.connect() as conn:
            public_tags = await conn.scalar(text("SELECT to_regclass('public.tags')"))
        assert public_tags is None, "there must be NO public.tags copy post-squash"

        with pytest.raises(ProgrammingError):
            async with engine.begin() as conn:
                await conn.exec_driver_sql("SET search_path TO public")
                await conn.execute(
                    text(
                        "INSERT INTO tags (name, color, created_at, "
                        "updated_at) VALUES (:n, '#abcdef80', now(), now())"
                    ),
                    {"n": "unrouted-tag"},
                )
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)
            await conn.execute(
                text("DELETE FROM public.guilds WHERE id = :id"), {"id": gid}
            )


async def test_provision_is_idempotent(engine):
    """Calling provision twice is a no-op, not an error."""
    gid = _GID_IDEMPOTENT
    schema = guild_schema_name(gid)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)
            await provision_guild_schema(conn, gid)  # must not raise
        async with engine.connect() as conn:
            count = await conn.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = :s AND table_type = 'BASE TABLE'"
                ),
                {"s": schema},
            )
        assert count == len(GUILD_SCOPED_TABLES)
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)


async def test_guild_role_is_scoped_to_its_own_schema(engine):
    """The per-guild role can reach its own schema but is denied another's.

    This is the fail-closed boundary: Postgres denies a role access to any
    schema it lacks USAGE on, *before* any RLS evaluates.
    """
    a, b = _GID_ROLE_A, _GID_ROLE_B
    role_a = guild_role_name(a)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, a)
            await provision_guild_schema(conn, b)

        # Assuming guild A's role, its own schema is readable.
        async with engine.connect() as conn:
            await conn.exec_driver_sql(f'SET ROLE "{role_a}"')
            own = await conn.scalar(
                text(f'SELECT count(*) FROM "{guild_schema_name(a)}".tags')
            )
            await conn.exec_driver_sql("RESET ROLE")
        assert own == 0

        # ...but guild B's schema is denied at the catalog layer.
        async with engine.connect() as conn:
            await conn.exec_driver_sql(f'SET ROLE "{role_a}"')
            with pytest.raises(ProgrammingError) as exc:
                await conn.scalar(
                    text(f'SELECT count(*) FROM "{guild_schema_name(b)}".tags')
                )
            assert "permission denied" in str(exc.value).lower()
            await conn.rollback()  # clear the aborted txn before resetting role
            await conn.exec_driver_sql("RESET ROLE")
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, a)
            await drop_guild_schema(conn, b)


async def test_drop_guild_schema_removes_role(engine):
    """Tearing down a guild drops ALL its roles too, not just the schema."""
    gid = _GID_ROLE_DROP
    roles = tuple(guild_role_name(gid, kind) for kind in GuildRoleKind)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)
        async with engine.connect() as conn:
            before = [
                await conn.scalar(
                    text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": r}
                )
                for r in roles
            ]
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)
        async with engine.connect() as conn:
            after = [
                await conn.scalar(
                    text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": r}
                )
                for r in roles
            ]
        assert all(before), "every role should exist after provisioning"
        assert not any(after), "every role should be gone after drop"
    finally:
        # Defensive: ensure no leftover role/schema if an assertion failed early.
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)


async def test_the_seat_role_is_the_guild_role_plus_the_communitys_own_settings(
    engine,
):
    """``guild_<id>_superadmin`` is what the four configuration routes assume.

    Everything the community's own role reaches, and beside it the one shared
    floor carrying its sign-in configuration — which the guild role itself no
    longer writes.
    """
    gid = _GID_SEAT
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)
        schema = guild_schema_name(gid)
        seat = guild_role_name(gid, GuildRoleKind.seat)
        role = guild_role_name(gid)
        async with engine.connect() as conn:
            for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                assert (
                    await conn.scalar(
                        text("SELECT has_table_privilege(:r, :t, :p)"),
                        {"r": seat, "t": "public.guild_auth_policies", "p": verb},
                    )
                    is True
                ), f"the seat role must hold {verb} on guild_auth_policies"
                # The community's own role reaches its content as before, and
                # the seat role inherits that reach.
                assert (
                    await conn.scalar(
                        text("SELECT has_table_privilege(:r, :t, :p)"),
                        {"r": seat, "t": f"{schema}.projects", "p": verb},
                    )
                    is True
                ), f"the seat role must hold {verb} on the community's content"
            # And the writes it adds are the ones the guild role gave up.
            for verb in ("INSERT", "UPDATE", "DELETE"):
                assert (
                    await conn.scalar(
                        text("SELECT has_table_privilege(:r, :t, :p)"),
                        {"r": role, "t": "public.guild_auth_policies", "p": verb},
                    )
                    is False
                ), f"the guild role must not hold {verb} on guild_auth_policies"
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)


async def test_the_plugin_role_holds_only_what_a_plugin_reaches(engine):
    """``guild_<id>_plugin`` writes content, reads the initiative structure, and
    holds nothing on the community's configuration or its plug-in setup beyond
    the columns its own standing reads."""
    gid = _GID_PLUGIN
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)
        schema = guild_schema_name(gid)
        plugin_role = guild_role_name(gid, GuildRoleKind.plugin)

        async def held(conn, table: str, verb: str) -> bool:
            return await conn.scalar(
                text("SELECT has_table_privilege(:r, :t, :p)"),
                {"r": plugin_role, "t": f"{schema}.{table}", "p": verb},
            )

        async with engine.connect() as conn:
            assert await conn.scalar(
                text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": plugin_role}
            )
            for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                assert await held(conn, "tasks", verb) is True, f"tasks {verb}"
            assert await held(conn, "initiatives", "SELECT") is True
            for verb in ("INSERT", "UPDATE", "DELETE"):
                assert await held(conn, "initiatives", verb) is False, (
                    f"initiatives {verb}"
                )
            for table in (
                "guild_settings",
                "guild_plugins",
                "guild_plugin_secrets",
                "plugin_placements",
                "initiative_role_permissions",
            ):
                for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    assert await held(conn, table, verb) is False, f"{table} {verb}"
            # The install standing statement reads these columns and no others.
            for table, columns in PLUGIN_ROLE_MACHINERY_READS.items():
                if not columns:
                    continue
                readable = {
                    row[0]
                    for row in (
                        await conn.execute(
                            text(
                                "SELECT column_name, has_column_privilege("
                                ":r, CAST(:t AS text), column_name, 'SELECT') "
                                "FROM information_schema.columns "
                                "WHERE table_schema = :s AND table_name = :n"
                            ),
                            {
                                "r": plugin_role,
                                "t": f"{schema}.{table}",
                                "s": schema,
                                "n": table,
                            },
                        )
                    ).all()
                    if row[1]
                }
                assert readable == set(columns), table
            assert await held(conn, "resource_grants", "SELECT") is True
            # The owner grant on what it creates, and the shares it rewrites
            # with sharing:write; the row policies decide which rows.
            assert await held(conn, "resource_grants", "INSERT") is True
            assert await held(conn, "resource_grants", "DELETE") is True
            assert await held(conn, "resource_grants", "UPDATE") is False
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)


async def test_the_plugin_role_is_refused_the_communitys_settings(engine):
    """A session assuming ``guild_<id>_plugin`` cannot read ``guild_settings``."""
    gid = _GID_PLUGIN_DENIED
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)
        async with engine.connect() as conn:
            await conn.exec_driver_sql(
                f'SET ROLE "{guild_role_name(gid, GuildRoleKind.plugin)}"'
            )
            with pytest.raises(ProgrammingError) as exc:
                await conn.scalar(
                    text(
                        f'SELECT count(*) FROM "{guild_schema_name(gid)}".guild_settings'
                    )
                )
            assert "permission denied" in str(exc.value).lower()
            await conn.rollback()
            await conn.exec_driver_sql("RESET ROLE")
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)


async def test_the_read_roles_cannot_write_shared_tables(engine):
    """The two per-guild roles that only read write nothing in ``public``.

    ``guild_<id>_ro`` serves PAM read grants and read-only members, over the
    read-only shared floor; ``guild_<id>_q`` serves the query surface and holds
    no floor at all. The writable floor the other roles carry would arrive by
    inheritance, which cannot be revoked back off.
    """
    gid = _GID_READ_FLOOR
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)
        async with engine.connect() as conn:
            for role in (
                guild_role_name(gid, GuildRoleKind.read_only),
                guild_role_name(gid, GuildRoleKind.query),
            ):
                for table in (
                    "public.user_view_preferences",
                    "public.user_tokens",
                    "public.guilds",
                ):
                    for verb in ("INSERT", "UPDATE", "DELETE"):
                        assert (
                            await conn.scalar(
                                text("SELECT has_table_privilege(:r, :t, :p)"),
                                {"r": role, "t": table, "p": verb},
                            )
                            is False
                        ), f"{role} {verb} {table}"
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)


async def test_support_role_write_capped_on_protected_tables(engine):
    """The restricted ``support`` role reads everything and writes content;
    the permission tables are SELECT-only, checked via has_table_privilege.
    The initiative's own structure is writable at the privilege level — the
    ``managed_*`` policies decide those writes from the standing, and a settings
    rung beside a read_write grant is among what they admit."""
    gid = _GID_SUPPORT
    schema = guild_schema_name(gid)
    support = guild_role_name(gid, GuildRoleKind.support)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)
        async with engine.connect() as conn:

            async def priv(table: str, verb: str) -> bool:
                return await conn.scalar(
                    text("SELECT has_table_privilege(:r, :t, :p)"),
                    {"r": support, "t": f"{schema}.{table}", "p": verb},
                )

            # Protected tables: readable, but no writes.
            for table in SUPPORT_WRITE_PROTECTED_TABLES:
                assert await priv(table, "SELECT") is True, f"{table} SELECT"
                for verb in ("INSERT", "UPDATE", "DELETE"):
                    assert await priv(table, verb) is False, f"{table} {verb}"

            # Every table that decides who may reach what is on the list. Stated
            # as a set rather than left to the loop above, because that list is
            # opt-in: a new access-management table silently gets full support
            # DML until somebody remembers it, which has happened twice.
            for table in (
                "resource_grants",
                "guild_plugin_user_connections",
                "plugin_member_consents",
            ):
                assert table in SUPPORT_WRITE_PROTECTED_TABLES, table

            # Content, guild settings and the initiative's structure: full DML
            # at the privilege level; the policies decide the structure's writes.
            for table in (
                "tasks",
                "guild_settings",
                "initiative_members",
                "initiative_roles",
                "initiative_role_permissions",
            ):
                for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    assert await priv(table, verb) is True, f"{table} {verb}"
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)


async def test_guild_role_can_write_in_its_own_schema(engine):
    """The role's DML grant actually works — it can INSERT, not just SELECT."""
    gid = _GID_ROLE_WRITE
    schema = guild_schema_name(gid)
    role = guild_role_name(gid)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)
            await _insert_public_guild(conn, gid, "role-write")
        async with engine.begin() as conn:
            await conn.exec_driver_sql(f'SET ROLE "{role}"')
            await conn.exec_driver_sql(f'SET search_path TO "{schema}", public')
            await conn.execute(
                text(
                    "INSERT INTO tags (name, color, created_at, updated_at) "
                    "VALUES (:n, '#112233', now(), now())"
                ),
                {"n": "written-by-role"},
            )
            written = await conn.scalar(text("SELECT count(*) FROM tags"))
            await conn.exec_driver_sql("SET search_path TO public")
            await conn.exec_driver_sql("RESET ROLE")
        assert written == 1
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)
            await conn.execute(
                text("DELETE FROM public.guilds WHERE id = :id"), {"id": gid}
            )


async def test_reprovision_backfills_missing_tables_with_grants(engine):
    """Re-provisioning recreates a table missing from the schema and grants it.

    Stands in for "a new guild-scoped table was added to the manifest": the
    table is absent from an existing schema, and a re-provision must create it
    *and* extend the role's access to it. The system login's grants are brought
    to the registry too: one an earlier release gave and the registry no longer
    names — table-wide ``UPDATE`` on ``comments``, which is column-scoped now —
    is gone afterwards, and the column grant is not.
    """
    gid = _GID_BACKFILL
    schema = guild_schema_name(gid)
    role = guild_role_name(gid)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)
            # Simulate a table that didn't exist when the schema was first made.
            await conn.exec_driver_sql(f'DROP TABLE "{schema}".task_assignees CASCADE')
            await conn.exec_driver_sql(
                f'GRANT UPDATE ON "{schema}".comments TO "{SYSTEM_LOGIN_ROLE}"'
            )

        async with engine.connect() as conn:
            gone = await conn.scalar(
                text(f"SELECT to_regclass('{schema}.task_assignees')")
            )
        assert gone is None, "precondition: task_assignees dropped"

        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)  # back-fill

        async with engine.connect() as conn:
            recreated = await conn.scalar(
                text(f"SELECT to_regclass('{schema}.task_assignees')")
            )
            # and the role's grant reaches the back-filled table. Route the
            # search_path into the guild schema first: the table's
            # initiative-member RLS policy references
            # tasks/projects/initiative_members unqualified, and those live only
            # in the guild schema.
            await conn.exec_driver_sql(f'SET search_path TO "{schema}", public')
            await conn.exec_driver_sql(f'SET ROLE "{role}"')
            readable = await conn.scalar(text("SELECT count(*) FROM task_assignees"))
            await conn.exec_driver_sql("RESET ROLE")
            await conn.exec_driver_sql("SET search_path TO public")
            table_wide, on_content = (
                await conn.execute(
                    text(
                        "SELECT has_table_privilege(:r, :t, 'UPDATE'), "
                        "has_column_privilege(:r, :t, 'content', 'UPDATE')"
                    ).bindparams(r=SYSTEM_LOGIN_ROLE, t=f"{schema}.comments")
                )
            ).one()
        assert recreated is not None, "task_assignees should be back-filled"
        assert readable == 0, "role should be able to read the back-filled table"
        assert not table_wide, "a grant the registry no longer names survived"
        assert on_content, "the registry's column grant was not restored"
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)


async def test_reprovision_preserves_existing_rows(engine):
    """Idempotency must not wipe data: a second provision keeps existing rows."""
    gid = _GID_REPROVISION
    schema = guild_schema_name(gid)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)
            await _insert_public_guild(conn, gid, "reprovision")
            await conn.exec_driver_sql(f'SET search_path TO "{schema}", public')
            await conn.execute(
                text(
                    "INSERT INTO tags (name, color, created_at, updated_at) "
                    "VALUES (:n, '#445566', now(), now())"
                ),
                {"n": "survivor"},
            )
            await conn.exec_driver_sql("SET search_path TO public")
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)  # second time
        async with engine.connect() as conn:
            count = await conn.scalar(text(f'SELECT count(*) FROM "{schema}".tags'))
        assert count == 1, "existing row must survive a re-provision"
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)
            await conn.execute(
                text("DELETE FROM public.guilds WHERE id = :id"), {"id": gid}
            )


async def test_drop_guild_schema_is_safe_when_absent(engine):
    """Dropping a guild that was never provisioned is a no-op, not an error."""
    async with engine.begin() as conn:
        await drop_guild_schema(conn, _GID_DROP_ABSENT)  # must not raise


# --- drift guard: the provisioned guild schema must equal guild_template --------

_GID_DRIFT = 990_120
_GID_NO_GUILD_COLUMN = 990_122
_GID_NO_CROSS_SCHEMA_FK = 990_123

# The Alembic-maintained canonical guild schema (created by migration
# 20260701_0126 by running guild_schema.sql + guild_rls.sql). Post-squash there
# are no tenant tables in ``public``, so the drift reference is the template.
_TEMPLATE_SCHEMA = "guild_template"


def _norm_default(d):
    # Per-schema sequences are correct; collapse nextval(...) so the seq name
    # (and a legacy rename like teams_id_seq) doesn't read as drift.
    return re.sub(r"nextval\('[^']+'::regclass\)", "nextval(SEQ)", d) if d else d


def _norm_constraint(s):
    # PG re-renders array casts on round-trip; strip cast/paren/space noise so a
    # semantically identical CHECK doesn't read as drift.
    s = re.sub(
        r"::(?:text|character varying|varchar|bpchar|integer|bigint)(?:\[\])?", "", s
    )
    return re.sub(r"[\s()\[\]]", "", s)


async def test_guild_schema_matches_guild_template(engine):
    """A provisioned guild schema must be a structurally faithful CLONE of the
    ``guild_template`` schema it was rendered from (``app.db.guild_ddl`` reflects
    the live template) — same columns/types/nullability/defaults, CHECK/PK/UNIQUE,
    indexes (incl. opclasses), and FK ON DELETE rules. This catches any fidelity
    gap in the live-reflection renderer.

    Every key counts, not only the ones that stay inside the schema: since
    20260922_0349 the template holds none that leave either, so the comparison
    can be whole, and one that came back would read here as the drift it is."""
    schema = guild_schema_name(_GID_DRIFT)
    rendered = rendered_trigger_names()
    rendered_cons = rendered_constraint_names()
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, _GID_DRIFT)

        async with engine.connect() as conn:

            async def cols(ns, t):
                r = await conn.execute(
                    text(
                        "SELECT a.attname a, format_type(a.atttypid,a.atttypmod) ty, a.attnotnull n, "
                        "pg_get_expr(ad.adbin,ad.adrelid) d FROM pg_attribute a "
                        "LEFT JOIN pg_attrdef ad ON ad.adrelid=a.attrelid AND ad.adnum=a.attnum "
                        "WHERE a.attrelid=(:ns||'.'||:t)::regclass AND a.attnum>0 AND NOT a.attisdropped"
                    ),
                    {"ns": ns, "t": t},
                )
                return {x.a: (x.ty, x.n, _norm_default(x.d)) for x in r}

            async def cons(ns, t):  # CHECK/PK/UNIQUE
                r = await conn.execute(
                    text(
                        "SELECT conname n, pg_get_constraintdef(oid) d FROM pg_constraint "
                        "WHERE conrelid=(:ns||'.'||:t)::regclass AND contype IN ('c','p','u')"
                    ),
                    {"ns": ns, "t": t},
                )
                # A constraint the registries render (the search index's
                # entity-type CHECK) is not structure, for the same reason as
                # the triggers below.
                return sorted(
                    _norm_constraint(x.d) for x in r if x.n not in rendered_cons
                )

            async def fks(ns, t):  # (target, ON DELETE) for every key on the table
                r = await conn.execute(
                    text(
                        "SELECT tgt.relname g, con.confdeltype::text d FROM pg_constraint con "
                        "JOIN pg_class tgt ON tgt.oid=con.confrelid "
                        "WHERE con.conrelid=(:ns||'.'||:t)::regclass AND con.contype='f'"
                    ),
                    {"ns": ns, "t": t},
                )
                return {(x.g, x.d) for x in r}

            async def idx(ns, t):  # the USING ... part is schema-independent
                r = await conn.execute(
                    text(
                        "SELECT indexdef i FROM pg_indexes WHERE schemaname=:ns AND tablename=:t"
                    ),
                    {"ns": ns, "t": t},
                )
                return sorted(x.i.split(" USING ", 1)[1] for x in r if " USING " in x.i)

            async def trig(ns, t):  # guild_id denorm triggers (functions stay shared)
                r = await conn.execute(
                    text(
                        "SELECT tg.tgname n, pg_get_triggerdef(tg.oid) d "
                        "FROM pg_trigger tg "
                        "JOIN pg_class cl ON cl.oid=tg.tgrelid "
                        "WHERE cl.oid=(:ns||'.'||:t)::regclass AND NOT tg.tgisinternal"
                    ),
                    {"ns": ns, "t": t},
                )
                return sorted(
                    re.sub(r"\bON \w+\.", "ON ", x.d)  # strip table schema
                    for x in r
                    # Triggers the registries render (freeze, capture, search)
                    # are not structure: a provisioned schema has them and the
                    # template does not, and neither side is wrong about it.
                    if x.n not in rendered
                )

            drift = []
            for t in sorted(GUILD_SCOPED_TABLES):
                if await cols(_TEMPLATE_SCHEMA, t) != await cols(schema, t):
                    drift.append(f"columns: {t}")
                if await cons(_TEMPLATE_SCHEMA, t) != await cons(schema, t):
                    drift.append(f"constraints: {t}")
                if await fks(_TEMPLATE_SCHEMA, t) != await fks(schema, t):
                    drift.append(f"foreign keys: {t}")
                if await idx(_TEMPLATE_SCHEMA, t) != await idx(schema, t):
                    drift.append(f"indexes: {t}")
                if await trig(_TEMPLATE_SCHEMA, t) != await trig(schema, t):
                    drift.append(f"triggers: {t}")
            assert drift == [], f"guild schema drifted from guild_template: {drift}"

            # The CHECKs that follow a registry are there, validated, and admit
            # what the model says.
            def values(definition: str) -> set[str]:
                return set(re.findall(r"'([^']*)'", definition))

            for table, check in registry_checks():
                row = (
                    await conn.execute(
                        text(
                            "SELECT convalidated v, pg_get_constraintdef(oid) d "
                            "FROM pg_constraint WHERE conname=:n "
                            "AND conrelid=(:ns||'.'||:t)::regclass"
                        ),
                        {"n": check.name, "ns": schema, "t": table.name},
                    )
                ).one()
                assert row.v, check.name
                assert values(row.d) == values(str(check.sqltext)), check.name
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, _GID_DRIFT)


_CROSS_SCHEMA_FKS = text(
    "SELECT cl.relname tbl, con.conname name, "
    "       tgt.relnamespace::regnamespace::text || '.' || tgt.relname tgt "
    "FROM pg_constraint con "
    "JOIN pg_class cl ON cl.oid = con.conrelid "
    "JOIN pg_class tgt ON tgt.oid = con.confrelid "
    "WHERE con.contype = 'f' "
    "  AND cl.relnamespace = CAST(:s AS regnamespace) "
    "  AND tgt.relnamespace <> cl.relnamespace "
    "ORDER BY 1, 2"
)


async def test_no_key_reaches_out_of_a_guild_schema(engine):
    """A guild schema holds no foreign key to a table outside it.

    Provisioning renders intra-schema keys only, so one written into a
    migration reaches ``guild_template`` and no guild — a rule the database
    states in the one place it is never enforced. 20260922_0349 removed the
    twenty-three that had collected that way, and
    ``migration_filters.strip_cross_schema_foreign_keys`` keeps autogenerate
    from writing the next one; this is the catalog saying so.
    """
    schema = guild_schema_name(_GID_NO_CROSS_SCHEMA_FK)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, _GID_NO_CROSS_SCHEMA_FK)

        async with engine.connect() as conn:
            for ns in (_TEMPLATE_SCHEMA, schema):
                found = [
                    f"{ns}.{r.tbl}.{r.name} -> {r.tgt}"
                    for r in await conn.execute(_CROSS_SCHEMA_FKS, {"s": ns})
                ]
                assert found == [], (
                    "foreign keys point out of the guild schema, where no guild "
                    f"would ever enforce them: {found}"
                )
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, _GID_NO_CROSS_SCHEMA_FK)


async def test_the_template_strip_removes_only_what_a_render_put_there(engine):
    """``guild_template`` carries structure. Boots before it became
    structure-only rendered the registries into it; the boot back-fill now
    strips those, and must leave the migrations' own triggers where they are."""
    from app.db import presence
    from app.db.authorization import GUILD_FUNCTION_SIGNATURES

    async def counts(conn):
        policies = await conn.scalar(
            text("SELECT count(*) FROM pg_policies WHERE schemaname = :s"),
            {"s": _TEMPLATE_SCHEMA},
        )
        names = [
            r[0]
            for r in await conn.execute(
                text(
                    "SELECT t.tgname FROM pg_trigger t JOIN pg_class c "
                    "ON c.oid = t.tgrelid WHERE NOT t.tgisinternal "
                    "AND c.relnamespace = CAST(:s AS regnamespace)"
                ),
                {"s": _TEMPLATE_SCHEMA},
            )
        ]
        rendered = rendered_trigger_names()
        functions = await conn.scalar(
            text(
                "SELECT count(*) FROM pg_proc WHERE proname = ANY(:n) "
                "AND pronamespace = CAST(:s AS regnamespace)"
            ),
            {"n": list(GUILD_FUNCTION_SIGNATURES), "s": _TEMPLATE_SCHEMA},
        )
        return (
            int(policies),
            sum(n in rendered for n in names),
            sum(n not in rendered for n in names),
            int(functions),
        )

    # What an earlier boot did: render the registry into the template. Its
    # policies name the presence view, which provisioning makes beside them.
    view = f'"{_TEMPLATE_SCHEMA}".{presence.VIEW}'
    body = "\nUNION ALL\n".join(arm.select(_TEMPLATE_SCHEMA) for arm in presence.arms())
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE VIEW {view} AS\n{body}"))
        await apply_guild_rls(conn, _TEMPLATE_SCHEMA)
    async with engine.connect() as conn:
        policies, rendered, own, functions = await counts(conn)
    assert policies > 0 and rendered > 0 and functions == len(GUILD_FUNCTION_SIGNATURES)

    async with engine.begin() as conn:
        removed = await strip_template_registry_objects(conn)
    async with engine.connect() as conn:
        after = await counts(conn)
    assert after == (0, 0, own, 0), after
    assert removed == policies + rendered + functions

    # And once clean, there is nothing to do.
    async with engine.begin() as conn:
        assert await strip_template_registry_objects(conn) == 0
        await conn.execute(text(f"DROP VIEW {view}"))


async def test_public_schema_has_no_tenant_tables(engine):
    """Squash check: on a fresh database the ``public`` schema must contain
    NO copy of any guild-scoped (tenant) table. Post-v0.53.5-baseline, tenant
    content lives ONLY in ``guild_<id>`` (and ``guild_template``), so this fails
    if a public copy reappears."""
    async with engine.connect() as conn:
        leaked = {
            row[0]
            for row in (
                await conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' AND table_name = ANY(:t)"
                    ),
                    {"t": list(GUILD_SCOPED_TABLES)},
                )
            )
        }
    assert leaked == set(), (
        f"public must hold NO tenant tables post-squash; found: {sorted(leaked)}"
    )


# --- back-fill sweep: heal half-states and drift for existing guilds -----------


async def test_backfill_provisions_a_guild_missing_its_schema(engine):
    """A guild row whose schema was never created (e.g. a crash mid-provision)
    gets its schema + tables on the next back-fill sweep."""
    done, missing = _GID_BACKFILL_DONE, _GID_BACKFILL_MISSING
    missing_schema = guild_schema_name(missing)
    try:
        async with engine.begin() as conn:
            await _insert_public_guild(conn, done, "backfill-done")
            await _insert_public_guild(conn, missing, "backfill-missing")
            await provision_guild_schema(conn, done)  # only `done` is provisioned

        async with engine.connect() as conn:
            before = await conn.scalar(
                text(
                    "SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"
                ),
                {"s": missing_schema},
            )
        assert before is None, "precondition: missing guild has no schema yet"

        summary = await backfill_guild_schemas()
        # Assert about OUR guilds only — the sweep covers every guild row in the
        # shared test DB, and an unrelated broken guild must not fail this test.
        assert done not in summary.failed_guild_ids
        assert missing not in summary.failed_guild_ids
        # `missing` had no schema, so it must have been provisioned; `done` was
        # provisioned with the current artifacts, so the stamp skips it.
        assert summary.provisioned >= 1
        assert summary.skipped >= 1

        async with engine.connect() as conn:
            tables = await conn.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = :s AND table_type = 'BASE TABLE'"
                ),
                {"s": missing_schema},
            )
        assert tables == len(GUILD_SCOPED_TABLES), "schema should be fully back-filled"
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, done)
            await drop_guild_schema(conn, missing)
            await conn.execute(
                text("DELETE FROM public.guilds WHERE id = ANY(:ids)"),
                {"ids": [done, missing]},
            )


async def test_backfill_repairs_a_dropped_table(engine):
    """A table missing from an already-provisioned schema (drift: a table added to
    guild_schema.sql after the guild was made) is recreated by the back-fill.

    In that scenario the guild's schema-comment stamp predates the current
    artifacts, so the sweep re-provisions it (a schema stamped with the CURRENT
    artifacts is skipped — out-of-band corruption needs FORCE_GUILD_BACKFILL)."""
    gid = _GID_BACKFILL_DRIFT
    schema = guild_schema_name(gid)
    try:
        async with engine.begin() as conn:
            await _insert_public_guild(conn, gid, "backfill-drift")
            await provision_guild_schema(conn, gid)
            # Simulate a table that didn't exist when the schema was provisioned:
            # the table is absent AND the stamp names the older artifact version.
            await conn.exec_driver_sql(f'DROP TABLE "{schema}".task_assignees CASCADE')
            await conn.exec_driver_sql(
                f"COMMENT ON SCHEMA \"{schema}\" IS 'provisioned:pre-task_assignees'"
            )

        async with engine.connect() as conn:
            gone = await conn.scalar(
                text(f"SELECT to_regclass('{schema}.task_assignees')")
            )
        assert gone is None, "precondition: task_assignees dropped"

        summary = await backfill_guild_schemas()
        # Scoped to our guild — unrelated broken guilds in the shared test DB
        # must not fail this test.
        assert gid not in summary.failed_guild_ids
        assert summary.provisioned >= 1

        async with engine.connect() as conn:
            recreated = await conn.scalar(
                text(f"SELECT to_regclass('{schema}.task_assignees')")
            )
        assert recreated is not None, "back-fill should recreate the dropped table"
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)
            await conn.execute(
                text("DELETE FROM public.guilds WHERE id = :id"), {"id": gid}
            )


async def test_backfill_continues_past_a_failing_guild(engine, monkeypatch):
    """One guild that fails to provision is logged and skipped — the others in the
    same sweep are still processed."""
    ok_a, ok_b, bad = _GID_BACKFILL_OK_A, _GID_BACKFILL_OK_B, _GID_BACKFILL_FAIL
    try:
        async with engine.begin() as conn:
            for gid, name in (
                (ok_a, "backfill-ok-a"),
                (ok_b, "backfill-ok-b"),
                (bad, "backfill-bad"),
            ):
                await _insert_public_guild(conn, gid, name)

        # Force exactly one guild's provisioning to blow up; the real function
        # handles every other id. The sweep calls _apply_parts as a
        # module-level name, so patching it here is enough.
        real_apply_parts = schema_provisioning._apply_parts

        async def _flaky_apply_parts(conn, guild_id: int, parts, **kw) -> None:
            if guild_id == bad:
                raise RuntimeError("forced provisioning failure")
            await real_apply_parts(conn, guild_id, parts, **kw)

        monkeypatch.setattr(schema_provisioning, "_apply_parts", _flaky_apply_parts)

        summary = await backfill_guild_schemas()

        # The bad guild is counted as failed but doesn't abort the sweep; both
        # healthy guilds (plus any other real guild rows) still get provisioned.
        assert bad in summary.failed_guild_ids
        assert ok_a not in summary.failed_guild_ids
        assert ok_b not in summary.failed_guild_ids
        assert summary.provisioned >= 2

        async with engine.connect() as conn:
            for gid in (ok_a, ok_b):
                tables = await conn.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema = :s AND table_type = 'BASE TABLE'"
                    ),
                    {"s": guild_schema_name(gid)},
                )
                assert tables == len(GUILD_SCOPED_TABLES), (
                    f"healthy guild {gid} should be provisioned despite a sibling failure"
                )
            bad_exists = await conn.scalar(
                text(
                    "SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"
                ),
                {"s": guild_schema_name(bad)},
            )
        assert bad_exists is None, "the forced-failure guild's schema must not exist"
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, ok_a)
            await drop_guild_schema(conn, ok_b)
            await drop_guild_schema(conn, bad)
            await conn.execute(
                text("DELETE FROM public.guilds WHERE id = ANY(:ids)"),
                {"ids": [ok_a, ok_b, bad]},
            )


async def test_backfill_applies_only_stale_parts_and_waits_for_a_held_guild(
    engine, monkeypatch
):
    """A guild behind on some parts gets those parts alone; its registry
    CHECKs are validated after they are replaced, and only then is it stamped
    current. A guild another process holds the provisioning lock on is waited
    for, and found current once it lets go, rather than applied a second time."""
    partial, held = _GID_BACKFILL_PARTIAL, _GID_BACKFILL_HELD
    bundle = await schema_provisioning.get_provisioning_bundle()
    stale_rls = bundle.stamp.replace(f"rls={bundle.digests['rls']}", "rls=old").replace(
        f"checks={bundle.digests['checks']}", "checks=old"
    )
    try:
        async with engine.begin() as conn:
            for gid, name in ((partial, "backfill-partial"), (held, "backfill-held")):
                await _insert_public_guild(conn, gid, name)
                await provision_guild_schema(conn, gid)
                await conn.exec_driver_sql(
                    f"COMMENT ON SCHEMA \"{guild_schema_name(gid)}\" IS '{stale_rls}'"
                )

        applied: dict[int, tuple[str, ...]] = {}
        real_apply_parts = schema_provisioning._apply_parts

        async def _recording_apply_parts(conn, guild_id: int, parts, **kw) -> None:
            applied[guild_id] = parts
            await real_apply_parts(conn, guild_id, parts, **kw)

        monkeypatch.setattr(schema_provisioning, "_apply_parts", _recording_apply_parts)

        # The other process: holds `held`'s lock with the guild brought current
        # but not yet committed, until the sweep is waiting on it.
        async with engine.connect() as other:
            await other.begin()
            await advisory_lock(other, LockNamespace.GUILD_PROVISION, held)
            await other.exec_driver_sql(
                f"COMMENT ON SCHEMA \"{guild_schema_name(held)}\" IS '{bundle.stamp}'"
            )
            sweep = asyncio.create_task(backfill_guild_schemas())
            async with engine.connect() as probe:
                while not await probe.scalar(
                    text(
                        "SELECT 1 FROM pg_locks WHERE locktype = 'advisory' "
                        "AND NOT granted AND classid::bigint = :ns "
                        "AND objid::bigint = :gid"
                    ),
                    {"ns": LockNamespace.GUILD_PROVISION, "gid": held},
                ):
                    assert not sweep.done(), "the sweep did not wait for the lock"
                    await asyncio.sleep(0.05)
            await other.commit()
        summary = await sweep

        assert partial not in summary.failed_guild_ids
        assert held not in summary.failed_guild_ids
        assert applied.get(partial) == ("checks", "rls")
        assert held not in applied
        async with engine.connect() as conn:
            schema = guild_schema_name(partial)
            assert (
                await conn.scalar(
                    text("SELECT obj_description(to_regnamespace(:s), 'pg_namespace')"),
                    {"s": schema},
                )
                == bundle.stamp
            )
            unvalidated = await conn.scalar(
                text(
                    "SELECT count(*) FROM pg_constraint "
                    "WHERE connamespace = to_regnamespace(:s) AND NOT convalidated"
                ),
                {"s": schema},
            )
            assert unvalidated == 0
    finally:
        async with engine.begin() as conn:
            for gid in (partial, held):
                await drop_guild_schema(conn, gid)
            await conn.execute(
                text("DELETE FROM public.guilds WHERE id = ANY(:ids)"),
                {"ids": [partial, held]},
            )


async def test_rendering_the_bundle_twice_gives_the_same_stamp(engine):
    """Reflection reads the template afresh each time, and the catalog does not
    promise to return a table's constraints in the same order twice. The stamp
    decides whether a guild's schema is stale, so an order that wobbles would
    re-provision every guild on every boot — and, across replicas, have them
    undo one another. Several renders, one stamp."""
    from app.db import schema_provisioning as sp

    stamps = []
    for _ in range(3):
        sp.reset_provisioning_bundle()
        stamps.append((await sp.get_provisioning_bundle()).stamp)
    sp.reset_provisioning_bundle()

    assert len(set(stamps)) == 1, f"the rendered bundle is not stable: {stamps}"


async def test_provisioning_stamp_tracks_grant_behavior_not_cosmetics(engine):
    """The back-fill stamp is derived from the RENDERED provisioning bundle
    (live schema DDL + registry RLS + rendered grant statements) — no manual
    version bump: a behavioral grants change moves the grants digest and no
    other; a cosmetic rewrite of ``_grant_statements`` moves nothing."""
    from unittest import mock

    from app.db import schema_provisioning as sp

    sp.reset_provisioning_bundle()
    base = await sp.get_provisioning_bundle()
    baseline = base.stamp

    _original = sp._grant_statements

    def _different_grants(*_args: str) -> list[str]:
        return ["GRANT USAGE ON SCHEMA x TO y"]

    def _cosmetic_rewrite(*args: str) -> list[str]:
        # Different source text, byte-identical output.
        return list(_original(*args))

    try:
        with mock.patch.object(sp, "_grant_statements", _different_grants):
            sp.reset_provisioning_bundle()
            changed = await sp.get_provisioning_bundle()
        with mock.patch.object(sp, "_grant_statements", _cosmetic_rewrite):
            sp.reset_provisioning_bundle()
            cosmetic = (await sp.get_provisioning_bundle()).stamp
    finally:
        sp.reset_provisioning_bundle()

    assert base.stale_parts(changed.stamp) == ("grants",), (
        "a behavioral grants change must move the grants digest alone"
    )
    assert cosmetic == baseline, "a cosmetic rewrite must NOT move the stamp"
    assert (await sp.get_provisioning_bundle()).stamp == baseline


# --- ensure_system_engine_bypassrls (issue #835) -----------------------------
#
# A system-engine login without BYPASSRLS reads shared tables as empty and
# boot seeding dies on the guilds RLS policy. The boot check must pass a
# healthy posture untouched and stop boot with instructions otherwise.


async def _login_can_alter_bypassrls(engine) -> bool:
    async with engine.connect() as conn:
        return bool(
            (
                await conn.execute(
                    text(
                        "SELECT rolsuper OR rolbypassrls FROM pg_roles "
                        "WHERE rolname = current_user"
                    )
                )
            ).scalar()
        )


async def _create_policy_bound_login(engine, role: str, password: str):
    """Create a LOGIN role WITHOUT BYPASSRLS and return an engine for it."""
    from sqlalchemy.ext.asyncio import create_async_engine

    async with engine.begin() as conn:
        await conn.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
        await conn.execute(
            text(f"CREATE ROLE \"{role}\" WITH LOGIN NOBYPASSRLS PASSWORD '{password}'")
        )
    return create_async_engine(
        engine.url.set(username=role, password=password), echo=False
    )


async def _drop_login(engine, role: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP ROLE IF EXISTS "{role}"'))


async def test_system_engine_check_passes_on_healthy_posture():
    # The harness routes the system engine to the real app_admin (BYPASSRLS)
    # against the test DB — the check must be a silent no-op.
    await schema_provisioning.ensure_system_engine_bypassrls()


async def test_system_engine_check_stops_boot_without_bypassrls(engine, monkeypatch):
    import app.db.session as db_session

    if not await _login_can_alter_bypassrls(engine):
        pytest.skip("test login may not alter BYPASSRLS roles")

    role = f"{engine.url.database}_unheal_role"
    bound_engine = await _create_policy_bound_login(engine, role, "unheal-pw")
    monkeypatch.setattr(db_session, "system_engine", bound_engine)
    try:
        with pytest.raises(SystemExit) as excinfo:
            await schema_provisioning.ensure_system_engine_bypassrls()
        assert "ALTER ROLE" in str(excinfo.value)
        assert role in str(excinfo.value)
        async with engine.connect() as conn:
            still_bound = (
                await conn.execute(
                    text("SELECT rolbypassrls FROM pg_roles WHERE rolname = :r"),
                    {"r": role},
                )
            ).scalar()
        assert not still_bound, "the check must not change the role"
    finally:
        await bound_engine.dispose()
        await _drop_login(engine, role)


# --- ensure_shared_table_grants (issue #835 follow-up) -----------------------
#
# BYPASSRLS skips RLS *policies*, not table GRANTs. A restored/recreated role
# can bypass RLS yet be missing the per-table grants, failing one gate deeper
# with "permission denied for table ...". The boot heal leaves a healthy
# posture untouched and otherwise re-asserts the audited grants (table + owned
# sequence) for the logins the URLs connect as. These tests point the registry
# at a throwaway public table so they never change the real app_admin/app_user
# grants (cluster-global roles shared across xdist workers); the per-worker
# test DB keeps the throwaway isolated.

_PROBE_TABLE = "grant_heal_probe"


async def _make_probe_table(engine, *, admin_grants, user_grants):
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS public.{_PROBE_TABLE}"))
        await conn.execute(
            text(f"CREATE TABLE public.{_PROBE_TABLE} (id serial PRIMARY KEY)")
        )
        # Fresh table created by the (superuser) test engine gives app_admin /
        # app_user nothing (default privileges were revoked for them); the
        # explicit REVOKE is belt-and-suspenders for the "restored role" state.
        await conn.execute(
            text(f"REVOKE ALL ON public.{_PROBE_TABLE} FROM app_admin, app_user")
        )
        if admin_grants:
            await conn.execute(
                text(f"GRANT {admin_grants} ON public.{_PROBE_TABLE} TO app_admin")
            )
        if user_grants:
            await conn.execute(
                text(f"GRANT {user_grants} ON public.{_PROBE_TABLE} TO app_user")
            )


async def _drop_probe_table(engine):
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS public.{_PROBE_TABLE}"))


def _point_registry_at_probe(monkeypatch, *, sys_verbs, user_verbs):
    from app.db import system_grants

    for role, verbs in (("app_admin", sys_verbs), ("app_user", user_verbs)):
        monkeypatch.setitem(
            system_grants.ROLE_GRANTS,
            role,
            {_PROBE_TABLE: frozenset(verbs) if verbs else None},
        )


async def test_shared_grants_heal_restores_missing_table_and_sequence(
    engine, monkeypatch
):
    # A restored role: the table exists but app_admin/app_user hold no grants —
    # exactly issue #835's second report ("permission denied for table guilds").
    await _make_probe_table(engine, admin_grants=None, user_grants=None)
    _point_registry_at_probe(
        monkeypatch, sys_verbs={"SELECT", "INSERT"}, user_verbs={"SELECT"}
    )
    try:
        await schema_provisioning.ensure_shared_table_grants()
        async with engine.connect() as conn:
            admin_insert, user_select, admin_seq, user_seq = (
                await conn.execute(
                    text(
                        "SELECT has_table_privilege('app_admin', :t, 'INSERT'), "
                        "has_table_privilege('app_user', :t, 'SELECT'), "
                        "has_sequence_privilege('app_admin', :s, 'USAGE'), "
                        "has_sequence_privilege('app_user', :s, 'USAGE')"
                    ),
                    {
                        "t": f"public.{_PROBE_TABLE}",
                        "s": f"public.{_PROBE_TABLE}_id_seq",
                    },
                )
            ).one()
        assert admin_insert, "system engine INSERT grant must be restored"
        assert user_select, "bare login SELECT grant must be restored"
        assert admin_seq, "INSERT needs the row-id sequence — must be restored too"
        # app_user is SELECT-only on this table, so it needs NO sequence grant:
        # the heal grants a sequence only where the role actually holds INSERT
        # (least privilege), matching each role's real per-table need.
        assert not user_seq, "a SELECT-only role must not receive a sequence grant"
    finally:
        await _drop_probe_table(engine)


async def test_shared_grants_heal_is_noop_when_intact(engine, monkeypatch):
    # Already fully granted (table + sequence) — the heal must not re-assert.
    await _make_probe_table(engine, admin_grants="SELECT, INSERT", user_grants="SELECT")
    async with engine.begin() as conn:
        await conn.execute(
            text(f"GRANT ALL ON SEQUENCE public.{_PROBE_TABLE}_id_seq TO app_admin")
        )
        await conn.execute(
            text(
                f"GRANT SELECT, USAGE ON SEQUENCE public.{_PROBE_TABLE}_id_seq "
                "TO app_user"
            )
        )
    _point_registry_at_probe(
        monkeypatch, sys_verbs={"SELECT", "INSERT"}, user_verbs={"SELECT"}
    )
    reasserted = False

    async def _spy(*args, **kwargs):
        nonlocal reasserted
        reasserted = True
        return 0

    monkeypatch.setattr(schema_provisioning, "_reassert_shared_grants", _spy)
    try:
        await schema_provisioning.ensure_shared_table_grants()
        assert not reasserted, "a healthy grant posture must be a single-probe no-op"
    finally:
        await _drop_probe_table(engine)


async def test_shared_grants_probe_detects_partial_grant(engine, monkeypatch):
    import app.db.session as db_session
    from app.db import system_grants

    # SELECT present but INSERT missing: the probe reports the INSERT, so a
    # partially-restored role still triggers the heal.
    await _make_probe_table(engine, admin_grants="SELECT", user_grants="SELECT")
    _point_registry_at_probe(
        monkeypatch, sys_verbs={"SELECT", "INSERT"}, user_verbs={"SELECT"}
    )
    try:
        async with db_session.provisioning_engine.connect() as conn:
            assert await system_grants.missing_grants(conn, "app_admin") == [
                (_PROBE_TABLE, "INSERT")
            ]
            assert await system_grants.missing_grants(conn, "app_user") == []
    finally:
        await _drop_probe_table(engine)


async def test_shared_grants_tolerate_lazily_created_table(engine, monkeypatch):
    import app.db.session as db_session
    from app.db import system_grants

    # A registry entry may name a table that is created lazily at runtime
    # (NON_MODEL_SHARED_TABLES — storage_backfill_state). Before the table
    # first materializes, the boot heal treats it as nothing to check.
    await _drop_probe_table(engine)
    _point_registry_at_probe(
        monkeypatch, sys_verbs={"SELECT", "INSERT"}, user_verbs={"SELECT"}
    )

    await schema_provisioning.ensure_shared_table_grants()  # must not raise

    async with db_session.provisioning_engine.connect() as conn:
        assert await system_grants.missing_grants(conn, "app_admin") == []


async def test_shared_grants_reach_the_configured_login_or_stop_boot(
    engine, monkeypatch
):
    """The heal grants the login DATABASE_URL_ADMIN connects as, whatever it is
    named; when the grants still do not hold, boot stops with the GRANTs that
    repair it, naming that login."""
    from app.core.config import settings

    role = f"{engine.url.database}_nogrant_role"
    bound_engine = await _create_policy_bound_login(engine, role, "nogrant-pw")
    monkeypatch.setattr(
        settings,
        "DATABASE_URL_ADMIN",
        bound_engine.url.render_as_string(hide_password=False),
    )
    await _make_probe_table(engine, admin_grants=None, user_grants="SELECT")
    _point_registry_at_probe(
        monkeypatch, sys_verbs={"SELECT", "INSERT"}, user_verbs={"SELECT"}
    )
    probe = f"public.{_PROBE_TABLE}"
    try:
        await schema_provisioning.ensure_shared_table_grants()
        async with engine.connect() as conn:
            login_insert, login_seq, canonical_insert = (
                await conn.execute(
                    text(
                        "SELECT has_table_privilege(:r, :t, 'INSERT'), "
                        "has_sequence_privilege(:r, :s, 'USAGE'), "
                        "has_table_privilege('app_admin', :t, 'INSERT')"
                    ),
                    {"r": role, "t": probe, "s": f"{probe}_id_seq"},
                )
            ).one()
        assert login_insert and login_seq
        assert not canonical_insert

        async with engine.begin() as conn:
            await conn.execute(text(f'REVOKE ALL ON {probe} FROM "{role}"'))

        async def _granted_nothing(*_args) -> int:
            return 0

        monkeypatch.setattr(
            schema_provisioning, "_reassert_shared_grants", _granted_nothing
        )
        with pytest.raises(SystemExit) as excinfo:
            await schema_provisioning.ensure_shared_table_grants()
        message = str(excinfo.value)
        assert "DATABASE_URL_ADMIN" in message
        assert (
            f'GRANT SELECT, INSERT ON TABLE public."{_PROBE_TABLE}" TO "{role}";'
            in message
        )
    finally:
        await _drop_probe_table(engine)
        await bound_engine.dispose()
        await _drop_login(engine, role)


# --- verify_engine_identities ------------------------------------------------
#
# This boot check pins the wiring itself: which login each URL connects as.


async def test_engine_identities_warn_on_shared_app_and_admin_login(
    monkeypatch, caplog
):
    import app.db.session as db_session

    # Point the app engine at the (harness) system engine: same login, same DB.
    # Working-but-not-recommended wiring warns loudly and boots; it never
    # stops. Contrast reject_privileged_database_url, which does stop --- the
    # difference is a weakened backstop versus no boundary at all.
    monkeypatch.setattr(db_session, "engine", db_session.system_engine)
    with caplog.at_level("WARNING", logger="app.db.schema_provisioning"):
        await schema_provisioning.verify_engine_identities()
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "DATABASE_URL_APP and DATABASE_URL_ADMIN" in joined
    assert "NOT RECOMMENDED" in joined


async def test_engine_identities_warn_on_privileged_app_login(
    engine, monkeypatch, caplog
):
    import app.db.session as db_session
    from sqlalchemy.ext.asyncio import create_async_engine

    # App engine as app_admin (BYPASSRLS) — a swapped-URLs deployment. A
    # DISTINCT engine from a distinct login must be the admin side so the
    # same-login warning doesn't fire instead.
    swapped_app = create_async_engine(db_session.system_engine.url, echo=False)
    monkeypatch.setattr(db_session, "engine", swapped_app)
    monkeypatch.setattr(db_session, "system_engine", engine)
    try:
        with caplog.at_level("WARNING", logger="app.db.schema_provisioning"):
            await schema_provisioning.verify_engine_identities()
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "SUPERUSER or" in joined
        assert "BYPASSRLS" in joined
        assert "DATABASE_URL_APP" in joined
    finally:
        await swapped_app.dispose()


async def test_engine_identities_flag_an_unused_temporary_grant(caplog):
    """The request login needs no TEMPORARY on the database. Only the database
    owner can revoke it, so the app reports the drift and names the command
    rather than trying to change it.

    Asserted against what the login actually holds. A database that has been
    handed over (the bootstrap revokes the grant) must draw no notice, and
    one that has not must draw one — reading the state first is
    what makes this a test of the report rather than of whichever database the
    developer happens to be pointed at.
    """
    import app.db.session as db_session

    async with db_session.engine.connect() as conn:
        holds_temp = (
            await conn.execute(
                text(
                    "SELECT has_database_privilege("
                    "  session_user, current_database(), 'TEMP')"
                )
            )
        ).scalar_one()

    with caplog.at_level("WARNING", logger="app.db.schema_provisioning"):
        await schema_provisioning.verify_engine_identities()
    joined = "\n".join(r.getMessage() for r in caplog.records)

    if holds_temp:
        assert "PRIVILEGE DRIFT" in joined
        assert "REVOKE TEMPORARY ON DATABASE" in joined
        assert "DATABASE_URL_BOOTSTRAP" in joined
    else:
        assert "REVOKE TEMPORARY ON DATABASE" not in joined


# --- reject_privileged_database_url (T67) ------------------------------------
#
# The role attributes are faked rather than created. Whether the harness login
# happens to be a superuser is a property of the CI database, not of this
# behaviour, and a test that only runs where the DB is set up a particular way
# is a test that quietly stops running.


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def one(self):
        return self._row


class _FakeConnection:
    def __init__(self, row):
        self._row = row

    async def execute(self, *_args, **_kwargs):
        return _FakeResult(self._row)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


class _FakeEngine:
    """Stands in for provisioning_engine, reporting fixed role attributes."""

    def __init__(self, *, rolsuper: bool, rolbypassrls: bool):
        self._row = (rolsuper, rolbypassrls)

    def connect(self):
        return _FakeConnection(self._row)


def _fake_provisioning_engine(monkeypatch, *, rolsuper=False, rolbypassrls=False):
    import app.db.session as db_session

    monkeypatch.setattr(
        db_session,
        "provisioning_engine",
        _FakeEngine(rolsuper=rolsuper, rolbypassrls=rolbypassrls),
    )


async def test_unprivileged_database_url_starts(monkeypatch):
    _fake_provisioning_engine(monkeypatch)
    await schema_provisioning.reject_privileged_database_url()


@pytest.mark.parametrize(
    ("attributes", "named"),
    [
        ({"rolsuper": True}, "SUPERUSER"),
        ({"rolbypassrls": True}, "BYPASSRLS"),
    ],
)
async def test_privileged_database_url_refuses_to_start(monkeypatch, attributes, named):
    """Either attribute means the connection is more than the app needs, so
    both stop the boot. The message names which was found, because the operator
    has to know which to remove."""
    _fake_provisioning_engine(monkeypatch, **attributes)

    with pytest.raises(SystemExit) as exit_info:
        await schema_provisioning.reject_privileged_database_url()

    message = str(exit_info.value)
    assert named in message
    # The refusal carries the way out; without it, it is an outage with no
    # stated remedy.
    assert "remove DATABASE_URL_APP" in message
    assert "app_provisioner" in message
    # Both ways to make the roles, so neither the operator who wants the app to
    # do it nor the one who wants the SQL has to go looking for the other.
    assert "python -m app.db.bootstrap --print-sql" in message


async def test_privileged_derived_provisioner_names_the_role_to_fix(monkeypatch):
    """With DATABASE_URL as the owner the app made app_provisioner itself, so
    the remedy is the role, not the connection settings."""
    from app.core.config import settings

    _fake_provisioning_engine(monkeypatch, rolsuper=True)
    monkeypatch.setattr(settings, "_database_logins_derived", True)

    with pytest.raises(SystemExit) as exit_info:
        await schema_provisioning.reject_privileged_database_url()

    message = str(exit_info.value)
    assert "ALTER ROLE app_provisioner NOSUPERUSER NOBYPASSRLS" in message
    assert "DATABASE_URL_APP" not in message


async def test_a_provisioned_schema_names_no_community(engine):
    """A guild schema is what says which community it is, so no table in one
    carries a ``guild_id`` column.

    Read from the catalog rather than compared against a list, so it cannot
    become a test of the exemptions that produced it: a table added later with
    the column fails here without anyone remembering to add it anywhere.
    """
    schema = guild_schema_name(_GID_NO_GUILD_COLUMN)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, _GID_NO_GUILD_COLUMN)
        async with engine.connect() as conn:
            named = (
                await conn.execute(
                    text(
                        "SELECT c.relname, a.attname FROM pg_attribute a "
                        "JOIN pg_class c ON c.oid = a.attrelid "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname = :ns AND c.relkind = 'r' "
                        "AND a.attnum > 0 AND NOT a.attisdropped "
                        "AND a.attname = 'guild_id' ORDER BY c.relname"
                    ),
                    {"ns": schema},
                )
            ).all()
        assert named == [], (
            "these tables still name their community in a column: "
            f"{[row[0] for row in named]}"
        )
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, _GID_NO_GUILD_COLUMN)


async def test_retiring_a_function_leaves_the_shared_copy_to_the_boot_step(engine):
    """A render retires only its own schema's copy of a retired function.

    0.71 kept ``relationship_endpoint_access`` in ``public``, and every guild's
    policies were bound to that one copy. The render drops retired functions
    with the search path on ``<guild>, public``, so an unqualified drop in a
    guild with no local copy reached the shared one and was refused — the
    other guilds still depended on it — and the back-fill failed for every
    guild in turn. Here guild B stands in for "every other guild".
    """
    from app.db.authorization import RETIRED_GUILD_FUNCTION_SIGNATURES
    from app.db.guild_ddl import render_retired_functions_ddl

    name, args = RETIRED_GUILD_FUNCTION_SIGNATURES[0]
    schema_a = guild_schema_name(_GID_RETIRED_A)
    schema_b = guild_schema_name(_GID_RETIRED_B)
    shared = f"public.{name}{args}"
    created_shared = False
    try:
        async with engine.begin() as conn:
            if (
                await conn.scalar(
                    text("SELECT to_regprocedure(CAST(:s AS text))"), {"s": shared}
                )
                is None
            ):
                created_shared = True
                await conn.exec_driver_sql(
                    f"CREATE FUNCTION {shared} RETURNS boolean "
                    "LANGUAGE sql STABLE AS 'SELECT true'"
                )
            for schema in (schema_a, schema_b):
                await conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
                await conn.exec_driver_sql(
                    f'CREATE TABLE "{schema}".t (kind text, id integer)'
                )
            # Guild B's policy is bound to the shared copy, as every guild's
            # was before this release re-rendered it.
            await conn.exec_driver_sql(
                f'ALTER TABLE "{schema_b}".t ENABLE ROW LEVEL SECURITY'
            )
            await conn.exec_driver_sql(
                f'CREATE POLICY p ON "{schema_b}".t USING '
                f"(public.{name}(kind, id, false))"
            )
            # Guild A has a copy of its own, which is the one to retire.
            await conn.exec_driver_sql(
                f'CREATE FUNCTION "{schema_a}".{name}{args} RETURNS boolean '
                "LANGUAGE sql STABLE AS 'SELECT true'"
            )

        async with engine.begin() as conn:
            await conn.exec_driver_sql(f'SET search_path TO "{schema_a}", public')
            await conn.exec_driver_sql(render_retired_functions_ddl())
            await conn.exec_driver_sql("SET search_path TO public")

        async with engine.connect() as conn:
            local = await conn.scalar(
                text("SELECT to_regprocedure(CAST(:s AS text))"),
                {"s": f'"{schema_a}".{name}{args}'},
            )
            still_shared = await conn.scalar(
                text("SELECT to_regprocedure(CAST(:s AS text))"), {"s": shared}
            )
        assert local is None, "the guild's own copy is retired"
        assert still_shared is not None, "the shared copy is left for the boot step"

        # And a render in a schema with no copy of its own is a no-op, rather
        # than a drop that reaches the shared one.
        async with engine.begin() as conn:
            await conn.exec_driver_sql(f'SET search_path TO "{schema_a}", public')
            await conn.exec_driver_sql(render_retired_functions_ddl())
            await conn.exec_driver_sql("SET search_path TO public")
    finally:
        async with engine.begin() as conn:
            for schema in (schema_a, schema_b):
                await conn.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            if created_shared:
                await conn.exec_driver_sql(f"DROP FUNCTION IF EXISTS {shared}")
