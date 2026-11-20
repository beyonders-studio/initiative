"""Tests for the guild-scoped migration helper (the forward migration pattern).

Synthetic, high guild ids so the temporary ``guild_<id>`` schemas can't collide
with real data; dropped in teardown. Runs against the test DB as the owning role
(the ``engine`` fixture), which has DDL privileges.
"""

import pytest
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text

from app.db.guild_migrations import (
    apply_to_all_guild_schemas,
    guild_schema_names,
    run_for_each_guild_schema,
)
from app.db.schema_provisioning import (
    drop_guild_schema,
    guild_schema_name,
    provision_guild_schema,
)

pytestmark = pytest.mark.always


_GID_A = 990_201
_GID_B = 990_202
_GID_C = 990_203
_GID_D = 990_204
_GID_E = 990_205
_GID_F = 990_206
_COLUMN = "_mig_helper_test"


async def _table_exists(conn, schema: str, table: str) -> bool:
    return bool(
        await conn.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = :s AND table_name = :t)"
            ),
            {"s": schema, "t": table},
        )
    )


async def _tags_has_column(conn, schema: str) -> bool:
    return bool(
        await conn.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = 'tags' AND column_name = :c)"
            ),
            {"s": schema, "c": _COLUMN},
        )
    )


async def test_apply_to_all_guild_schemas_hits_every_guild(engine):
    """A guild-scoped DDL change applied via the helper lands in every provisioned
    guild schema — the core of the forward migration pattern (a normal migration
    would only touch one schema)."""
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, _GID_A)
            await provision_guild_schema(conn, _GID_B)

        # The provisioned schemas are enumerated.
        async with engine.connect() as conn:
            names = await conn.run_sync(guild_schema_names)
        assert guild_schema_name(_GID_A) in names
        assert guild_schema_name(_GID_B) in names

        # Apply an idempotent, schema-relative ALTER to every guild schema.
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: apply_to_all_guild_schemas(
                    c,
                    f"ALTER TABLE tags ADD COLUMN IF NOT EXISTS {_COLUMN} boolean",
                )
            )

        async with engine.connect() as conn:
            assert await _tags_has_column(conn, guild_schema_name(_GID_A))
            assert await _tags_has_column(conn, guild_schema_name(_GID_B))

        # The reverse (a downgrade) removes it everywhere.
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: apply_to_all_guild_schemas(
                    c,
                    f"ALTER TABLE tags DROP COLUMN IF EXISTS {_COLUMN}",
                )
            )
        async with engine.connect() as conn:
            assert not await _tags_has_column(conn, guild_schema_name(_GID_A))
            assert not await _tags_has_column(conn, guild_schema_name(_GID_B))
    finally:
        # Best-effort: ensure no other guild schema keeps the throwaway column.
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: apply_to_all_guild_schemas(
                    c,
                    f"ALTER TABLE tags DROP COLUMN IF EXISTS {_COLUMN}",
                )
            )
            await drop_guild_schema(conn, _GID_A)
            await drop_guild_schema(conn, _GID_B)


async def test_apply_to_all_guild_schemas_targets_template(engine):
    """A guild-scoped change reaches ``guild_template`` too, not just the
    already-provisioned ``guild_<id>`` schemas. The template is the source
    provisioning reflects, so a guild created afterwards inherits the change."""
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, _GID_C)
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: apply_to_all_guild_schemas(
                    c, f"ALTER TABLE tags ADD COLUMN IF NOT EXISTS {_COLUMN} boolean"
                )
            )
        async with engine.connect() as conn:
            # The provisioned guild schema got the change...
            assert await _tags_has_column(conn, guild_schema_name(_GID_C))
            # ...and so did guild_template (the source new guilds are built from),
            # which the migration 20260702_0126 created in the test DB.
            assert await _tags_has_column(conn, "guild_template")
            # Guild schemas are the only place guild content exists.
            assert not await _table_exists(conn, "public", "tags")
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: apply_to_all_guild_schemas(
                    c, f"ALTER TABLE tags DROP COLUMN IF EXISTS {_COLUMN}"
                )  # remove from guild_template + every guild schema
            )
            await drop_guild_schema(conn, _GID_C)


async def test_a_revision_committing_each_schema_finishes_when_run_again(engine):
    """With ``commit_each``, the schemas done before a failure stay done, the
    failing one is rolled back, and running the revision again finishes."""
    first, second = guild_schema_name(_GID_E), guild_schema_name(_GID_F)

    def revision(connection, fail_in: str | None) -> None:
        context = MigrationContext.configure(
            connection, opts={"transaction_per_migration": True}
        )

        def step() -> None:
            connection.execute(
                text(f"ALTER TABLE tags ADD COLUMN IF NOT EXISTS {_COLUMN} boolean")
            )
            if connection.execute(text("SELECT current_schema()")).scalar() == fail_in:
                raise RuntimeError("stopped")

        with context.begin_transaction(_per_migration=True):
            run_for_each_guild_schema(connection, step, commit_each=context)

    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, _GID_E)
            await provision_guild_schema(conn, _GID_F)
        async with engine.connect() as conn:
            with pytest.raises(RuntimeError):
                await conn.run_sync(revision, second)
        async with engine.connect() as conn:
            assert await _tags_has_column(conn, first)
            assert not await _tags_has_column(conn, second)
        async with engine.connect() as conn:
            await conn.run_sync(revision, None)
        async with engine.connect() as conn:
            assert await _tags_has_column(conn, second)
            assert await _tags_has_column(conn, "guild_template")
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: apply_to_all_guild_schemas(
                    c, f"ALTER TABLE tags DROP COLUMN IF EXISTS {_COLUMN}"
                )
            )
            await drop_guild_schema(conn, _GID_E)
            await drop_guild_schema(conn, _GID_F)


async def test_apply_to_all_guild_schemas_failure_propagates_and_reverts(engine):
    """A failing DDL must surface its OWN error (not a masking cleanup error) and
    leave no stale search_path on the connection after rollback."""
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, _GID_D)

        async with engine.connect() as conn:
            trans = await conn.begin()
            with pytest.raises(Exception) as exc_info:
                await conn.run_sync(
                    lambda c: apply_to_all_guild_schemas(
                        c,
                        "ALTER TABLE tags ADD COLUMN _boom bogus_type_xyz",
                    )
                )
            # The original DDL error, not a 'current transaction is aborted' mask.
            assert "current transaction is aborted" not in str(exc_info.value).lower()
            await trans.rollback()
            # is_local search_path reverts on rollback — no stale guild schema.
            search_path = (await conn.exec_driver_sql("SHOW search_path")).scalar()
            assert "guild_" not in search_path
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, _GID_D)
