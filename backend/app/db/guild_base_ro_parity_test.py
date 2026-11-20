"""``app_guild_base_ro`` holds the read half of ``app_guild_base``.

The two are kept as one set: every table the writable floor can read, and no
other. ``app_guild_base_ro`` takes no schema-wide default privileges, so a
shared table added later reaches the writable floor and not this one, and shows
up here as a difference until the migration that adds it says which it is.
"""

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.always


WRITABLE_FLOOR = "app_guild_base"
READ_FLOOR = "app_guild_base_ro"


@pytest.fixture(autouse=True)
async def _materialize_lazy_shared_tables():
    """``storage_backfill_state`` is created lazily at runtime, not by a
    migration, so whether it is in the catalog here depends on whether a
    storage test happened to run first in this worker. Created up front, the
    way ``security_invariants_test`` does it, so the floors are compared over
    the same set of tables every run."""
    from app.services.storage_backfill import _ensure_table

    await _ensure_table()


_TABLES = """
SELECT c.oid::regclass::text AS name,
       has_table_privilege(:writable, c.oid, 'SELECT') AS writable_reads,
       has_table_privilege(:read_only, c.oid, 'SELECT') AS read_only_reads
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
"""


async def _rows(engine):
    async with engine.connect() as conn:
        return (
            await conn.execute(
                text(_TABLES), {"writable": WRITABLE_FLOOR, "read_only": READ_FLOOR}
            )
        ).all()


async def test_the_read_floor_reads_exactly_what_the_writable_one_does(engine):
    """A guild read the full role can serve works here too, and nothing the
    writable floor cannot read is readable here.

    A new shared table lands here first: grant it to ``app_guild_base_ro`` in
    the migration that adds it, or leave it out on purpose.
    """
    rows = await _rows(engine)
    wider = [r.name for r in rows if r.read_only_reads and not r.writable_reads]
    narrower = [r.name for r in rows if r.writable_reads and not r.read_only_reads]
    assert wider == [], f"{READ_FLOOR} reads tables {WRITABLE_FLOOR} cannot: {wider}"
    assert narrower == [], f"{READ_FLOOR} cannot read: {narrower}"


async def test_the_read_floor_holds_no_sequences(engine):
    """A read names no sequence."""
    async with engine.connect() as conn:
        held = await conn.scalar(
            text(
                "WITH s AS MATERIALIZED ("
                "  SELECT c.oid FROM pg_class c"
                "  JOIN pg_namespace n ON n.oid = c.relnamespace"
                "  WHERE n.nspname = 'public' AND c.relkind = 'S') "
                "SELECT count(*) FROM s "
                "WHERE has_sequence_privilege(:r, s.oid, 'SELECT') "
                "   OR has_sequence_privilege(:r, s.oid, 'USAGE')"
            ),
            {"r": READ_FLOOR},
        )
        assert held == 0


async def test_the_read_floor_takes_no_default_privileges(engine):
    """Nothing grants it a table it was not granted on purpose."""
    async with engine.connect() as conn:
        entries = await conn.scalar(
            text(
                "SELECT count(*) FROM pg_default_acl a "
                "JOIN pg_namespace n ON n.oid = a.defaclnamespace "
                "WHERE n.nspname = 'public' "
                "AND strpos(array_to_string(a.defaclacl, ','), :r) > 0"
            ),
            {"r": READ_FLOOR},
        )
        assert entries == 0


@pytest.mark.parametrize("verb", ["INSERT", "UPDATE", "DELETE"])
async def test_the_read_floor_writes_nothing(engine, verb):
    async with engine.connect() as conn:
        writable = (
            await conn.execute(
                text(
                    "SELECT c.oid::regclass::text AS name FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') "
                    "AND has_table_privilege(:r, c.oid, :v)"
                ),
                {"r": READ_FLOOR, "v": verb},
            )
        ).all()
    assert [row.name for row in writable] == []
