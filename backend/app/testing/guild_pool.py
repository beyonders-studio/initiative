"""Test-only: a per-worker pool of built guild schemas, reused between tests.

Building a guild schema is most of what a guild test spends before its own
work starts, and guild ids restart at 1 every test, so without this the same
``guild_1`` is built and dropped again for every test. Instead, a schema whose
test is over is emptied and kept, *parked* as ``test_pool_<id>`` — a name
nothing in ``app/`` enumerates — and renamed back the next time a test
provisions that guild id. Its roles keep their names; nothing uses them while
the schema is parked.

A parked schema has to be exactly what provisioning would build. Two checks
decide whether one still is when its test ends:

* an event trigger records every DDL statement that touches a guild schema or
  ``guild_template`` in ``test_harness.ddl_log``; a schema named there is
  dropped rather than parked;
* a fingerprint of the permissions around the schema — grants on it and on its
  objects, its default privileges, its roles' memberships and attributes, none
  of which reach an event trigger — must equal the one taken when it was built.

The permissions are checked again when a parked schema is handed back out: a
test can drop a guild's roles while that guild's schema is parked.

``PYTEST_GUILD_POOL=0`` turns the pool off, so every guild is built and
dropped; ``@pytest.mark.fresh_guild_schema`` does the same for one test.
"""

from __future__ import annotations

import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db.schema_provisioning import (
    GuildRoleKind,
    drop_guild_schema,
    guild_role_name,
    guild_schema_name,
)

#: Guild ids 1..POOL_SIZE are pooled: a test's first communities.
POOL_SIZE = 3
ENABLED = os.environ.get("PYTEST_GUILD_POOL", "1") != "0"
TEMPLATE = "guild_template"

# The schema an object belongs to, from its identity ("guild_1.tasks",
# "p on guild_1.tasks", "guild_1").
_SCHEMA_IN_IDENTITY = r'(?:^|[ "])(guild_(?:[0-9]+|template))(?:[."]|$)'

_INSTALL = f"""
CREATE SCHEMA IF NOT EXISTS test_harness;
CREATE UNLOGGED TABLE IF NOT EXISTS test_harness.ddl_log (schema_name text NOT NULL);
CREATE TABLE IF NOT EXISTS test_harness.slots (
    guild_id int PRIMARY KEY,
    permissions text NOT NULL
);
CREATE OR REPLACE FUNCTION test_harness.log_ddl() RETURNS event_trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $fn$
BEGIN
    IF current_setting('test_harness.quiet', true) = 'on' THEN
        RETURN;
    END IF;
    IF TG_EVENT = 'sql_drop' THEN
        INSERT INTO test_harness.ddl_log
        SELECT DISTINCT substring(object_identity FROM '{_SCHEMA_IN_IDENTITY}')
          FROM pg_event_trigger_dropped_objects()
         WHERE object_identity ~ '{_SCHEMA_IN_IDENTITY}';
    ELSE
        INSERT INTO test_harness.ddl_log
        SELECT DISTINCT substring(object_identity FROM '{_SCHEMA_IN_IDENTITY}')
          FROM pg_event_trigger_ddl_commands()
         WHERE object_identity ~ '{_SCHEMA_IN_IDENTITY}';
    END IF;
END
$fn$;
DROP EVENT TRIGGER IF EXISTS test_harness_ddl_end;
DROP EVENT TRIGGER IF EXISTS test_harness_sql_drop;
CREATE EVENT TRIGGER test_harness_ddl_end ON ddl_command_end
    EXECUTE FUNCTION test_harness.log_ddl();
CREATE EVENT TRIGGER test_harness_sql_drop ON sql_drop
    EXECUTE FUNCTION test_harness.log_ddl();
"""


def parked_name(guild_id: int) -> str:
    return f"test_pool_{int(guild_id)}"


async def quiet(conn: AsyncConnection) -> None:
    """Keep this transaction's DDL out of the log: the harness's own."""
    await conn.execute(text("SELECT set_config('test_harness.quiet', 'on', true)"))


def _permissions_sql(schema: str, guild_id: int) -> str:
    roles = ", ".join(f"'{guild_role_name(guild_id, kind)}'" for kind in GuildRoleKind)
    # Names are built from int ids and the run's role prefix, never from input.
    return f"""
SELECT md5(concat_ws('|',
  (SELECT nspacl::text FROM pg_namespace WHERE nspname = '{schema}'),
  (SELECT string_agg(relname || ':' || coalesce(relacl::text, ''), ',' ORDER BY relname)
     FROM pg_class WHERE relnamespace = '{schema}'::regnamespace),
  (SELECT string_agg(c.relname || '.' || a.attname || ':' || a.attacl::text, ','
                     ORDER BY c.relname, a.attname)
     FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
    WHERE c.relnamespace = '{schema}'::regnamespace AND a.attacl IS NOT NULL),
  (SELECT string_agg(proname || ':' || coalesce(proacl::text, ''), ',' ORDER BY proname)
     FROM pg_proc WHERE pronamespace = '{schema}'::regnamespace),
  (SELECT string_agg(concat_ws(':', defaclrole::regrole, defaclobjtype, defaclacl::text),
                     ',' ORDER BY 1)
     FROM pg_default_acl WHERE defaclnamespace = '{schema}'::regnamespace),
  (SELECT string_agg(concat_ws(':', roleid::regrole, member::regrole, admin_option,
                               inherit_option, set_option), ',' ORDER BY 1)
     FROM pg_auth_members
    WHERE roleid::regrole::text IN ({roles}) OR member::regrole::text IN ({roles})),
  (SELECT string_agg(concat_ws(':', rolname, rolsuper, rolinherit, rolcreaterole,
                               rolcreatedb, rolcanlogin, rolbypassrls, rolconnlimit),
                     ',' ORDER BY rolname)
     FROM pg_roles WHERE rolname IN ({roles}))
))
"""


async def _record_permissions(
    conn: AsyncConnection, schema: str, guild_id: int
) -> None:
    permissions = await conn.scalar(text(_permissions_sql(schema, guild_id)))
    await conn.execute(
        text(
            "INSERT INTO test_harness.slots (guild_id, permissions) VALUES (:g, :p) "
            "ON CONFLICT (guild_id) DO UPDATE SET permissions = EXCLUDED.permissions"
        ),
        {"g": guild_id, "p": permissions},
    )


async def _permissions_intact(
    conn: AsyncConnection, schema: str, guild_id: int
) -> bool:
    recorded = await conn.scalar(
        text("SELECT permissions FROM test_harness.slots WHERE guild_id = :g"),
        {"g": guild_id},
    )
    return recorded is not None and recorded == await conn.scalar(
        text(_permissions_sql(schema, guild_id))
    )


async def install(engine: AsyncEngine) -> None:
    """Set up the log and bring the pool to a known state, once per session.

    A guild schema left under its own name is a run that stopped mid-test, so
    it goes. A parked one is kept, and its permissions are recorded again: the
    bootstrap every session starts with re-grants the guild roles to the
    provisioning login. One whose roles are gone goes too: recording it would
    take the missing roles as the slot's permissions, and every later session
    would hand it out without them.
    """
    async with engine.begin() as conn:
        raw = await conn.get_raw_connection()
        await raw.driver_connection.execute(_INSTALL)
        await quiet(conn)
        leftovers = (
            (
                await conn.execute(
                    text(
                        "SELECT nspname FROM pg_namespace WHERE nspname ~ '^guild_[0-9]+$'"
                    )
                )
            )
            .scalars()
            .all()
        )
        for schema in leftovers:
            await drop_guild_schema(conn, int(schema.removeprefix("guild_")))
        parked = (
            (
                await conn.execute(
                    text(
                        "SELECT nspname FROM pg_namespace WHERE nspname ~ '^test_pool_[0-9]+$'"
                    )
                )
            )
            .scalars()
            .all()
        )
        for schema in parked:
            guild_id = int(schema.removeprefix("test_pool_"))
            roles = [guild_role_name(guild_id, kind) for kind in GuildRoleKind]
            present = await conn.scalar(
                text("SELECT count(*) FROM pg_roles WHERE rolname = ANY(:r)"),
                {"r": roles},
            )
            if present != len(roles):
                await conn.exec_driver_sql(
                    f'DROP SCHEMA "{parked_name(guild_id)}" CASCADE'
                )
                await drop_guild_schema(conn, guild_id)
                continue
            await _record_permissions(conn, schema, guild_id)
        await conn.execute(text("DELETE FROM test_harness.ddl_log"))


async def activate(engine: AsyncEngine, guild_id: int, stamp: str) -> bool | None:
    """Rename the parked schema for ``guild_id`` back into service.

    True when it was. None when ``guild_<id>`` already exists, so whatever
    provisions it next builds over a schema the pool did not hand out. False
    otherwise: the caller provisions, and the result can join the pool. A
    parked schema built from another render than ``stamp`` is dropped, and so
    is one whose permissions moved while it was parked: a test that drops a
    guild's roles leaves that guild's parked schema without them.
    """
    if not 1 <= guild_id <= POOL_SIZE:
        return False
    parked = parked_name(guild_id)
    async with engine.begin() as conn:
        await quiet(conn)
        found, parked_stamp, in_use = (
            await conn.execute(
                text(
                    "SELECT to_regnamespace(:p) IS NOT NULL, "
                    "obj_description(to_regnamespace(:p), 'pg_namespace'), "
                    "to_regnamespace(:g) IS NOT NULL"
                ),
                {"p": parked, "g": guild_schema_name(guild_id)},
            )
        ).one()
        if in_use:
            return None
        if not found:
            return False
        if parked_stamp != stamp or not await _permissions_intact(
            conn, parked, guild_id
        ):
            await conn.exec_driver_sql(f'DROP SCHEMA "{parked}" CASCADE')
            return False
        await conn.exec_driver_sql(
            f'ALTER SCHEMA "{parked}" RENAME TO "{guild_schema_name(guild_id)}"'
        )
        return True


async def adopt(engine: AsyncEngine, guild_id: int) -> None:
    """Take a schema provisioning just built for ``guild_id`` into the pool:
    its build is not a change, and its permissions are what the slot's must
    stay."""
    if not 1 <= guild_id <= POOL_SIZE:
        return
    schema = guild_schema_name(guild_id)
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM test_harness.ddl_log WHERE schema_name = :s"),
            {"s": schema},
        )
        await _record_permissions(conn, schema, guild_id)


async def drop(engine: AsyncEngine, guild_id: int) -> None:
    """Drop ``guild_<id>`` and its roles, and the parked schema for the same
    id with them: it was built on those roles."""
    async with engine.begin() as conn:
        await quiet(conn)
        await conn.exec_driver_sql(
            f'DROP SCHEMA IF EXISTS "{parked_name(guild_id)}" CASCADE'
        )
        await drop_guild_schema(conn, guild_id)


async def take_changed(engine: AsyncEngine) -> set[str]:
    """The schemas DDL touched since the last call, clearing the log."""
    async with engine.begin() as conn:
        return set(
            (
                await conn.execute(
                    text("DELETE FROM test_harness.ddl_log RETURNING schema_name")
                )
            ).scalars()
        )


async def park(engine: AsyncEngine, guild_id: int) -> bool:
    """Empty ``guild_<id>`` and park it; False when it must be dropped instead.

    Only the tables holding a row and the sequences that were drawn from are
    reset, with triggers off (``replica``): emptying the rest costs more than
    the build this replaces.
    """
    if not 1 <= guild_id <= POOL_SIZE:
        return False
    schema = guild_schema_name(guild_id)
    async with engine.begin() as conn:
        await quiet(conn)
        if not await _permissions_intact(conn, schema, guild_id):
            return False
        tables = (
            (
                await conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = :s"),
                    {"s": schema},
                )
            )
            .scalars()
            .all()
        )
        written = (
            (
                await conn.execute(
                    text(
                        " UNION ALL ".join(
                            f'SELECT \'{t}\' WHERE EXISTS (SELECT 1 FROM "{schema}"."{t}")'
                            for t in tables
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        drawn = (
            (
                await conn.execute(
                    text(
                        "SELECT sequencename FROM pg_sequences "
                        "WHERE schemaname = :s AND last_value IS NOT NULL"
                    ),
                    {"s": schema},
                )
            )
            .scalars()
            .all()
        )
        raw = await conn.get_raw_connection()
        await raw.driver_connection.execute(
            ";\n".join(
                [
                    "SET LOCAL session_replication_role = 'replica'",
                    *(f'DELETE FROM "{schema}"."{t}"' for t in written),
                    *(f'SELECT setval(\'"{schema}"."{s}"\', 1, false)' for s in drawn),
                    "SET LOCAL session_replication_role = 'origin'",
                    f'ALTER SCHEMA "{schema}" RENAME TO "{parked_name(guild_id)}"',
                ]
            )
        )
    return True
