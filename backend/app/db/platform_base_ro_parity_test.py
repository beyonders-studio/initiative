"""``platform_base_ro`` holds the read half of ``platform_base``, and
``platform_suspended`` holds that and nothing more.

A suspended account's request assumes ``platform_suspended``: its own rows,
read, and nothing written. The read floor is kept as one set with the writable
floor — every table ``platform_base`` can read, and no other — and takes no
schema-wide default privileges, so a shared table added later reaches the
writable floor and not this one, and shows up here as a difference until the
migration that adds it says which it is.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.public_rls import PLATFORM_SUSPENDED, platform_tier, role_name
from app.models.platform.notification import NotificationType
from app.testing import as_role, create_user

pytestmark = pytest.mark.always


def _writable() -> str:
    return role_name("platform_base")


def _read_floor() -> str:
    return role_name("platform_base_ro")


@pytest.fixture(autouse=True)
async def _materialize_lazy_shared_tables():
    """``storage_backfill_state`` is created lazily at runtime; created up front
    so the floors are compared over the same set of tables every run."""
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
                text(_TABLES), {"writable": _writable(), "read_only": _read_floor()}
            )
        ).all()


async def test_the_read_floor_reads_exactly_what_the_writable_one_does(engine):
    """A new shared table lands here first: grant it to ``platform_base_ro`` in
    the migration that adds it, or leave it out on purpose."""
    rows = await _rows(engine)
    wider = [r.name for r in rows if r.read_only_reads and not r.writable_reads]
    narrower = [r.name for r in rows if r.writable_reads and not r.read_only_reads]
    assert wider == [], f"{_read_floor()} reads tables {_writable()} cannot: {wider}"
    assert narrower == [], f"{_read_floor()} cannot read: {narrower}"


@pytest.mark.parametrize("verb", ["INSERT", "UPDATE", "DELETE", "TRUNCATE"])
async def test_the_suspended_role_writes_nothing(engine, verb):
    suspended = role_name(platform_tier(PLATFORM_SUSPENDED))
    async with engine.connect() as conn:
        writable = (
            await conn.execute(
                text(
                    "SELECT c.oid::regclass::text AS name FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') "
                    "AND has_table_privilege(:r, c.oid, :v)"
                ),
                {"r": suspended, "v": verb},
            )
        ).all()
    assert [row.name for row in writable] == []


async def test_the_read_floor_takes_no_default_privileges(engine):
    async with engine.connect() as conn:
        entries = await conn.scalar(
            text(
                "SELECT count(*) FROM pg_default_acl a "
                "JOIN pg_namespace n ON n.oid = a.defaclnamespace "
                "WHERE n.nspname = 'public' "
                "AND strpos(array_to_string(a.defaclacl, ','), :r) > 0"
            ),
            {"r": _read_floor()},
        )
        assert entries == 0


async def test_a_suspended_account_reads_its_own_rows(session):
    me = await create_user(session)
    other = await create_user(session)
    async with as_role(session, role_name(platform_tier(PLATFORM_SUSPENDED)), me.id):
        ids = {r[0] for r in (await session.exec(text("SELECT id FROM users"))).all()}
    assert me.id in ids
    assert other.id not in ids


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE users SET timezone = 'UTC' WHERE id = :uid",
        (
            "INSERT INTO notifications (user_id, type, data) "
            f"VALUES (:uid, '{NotificationType.account_suspended.value}', '{{}}')"
        ),
        "DELETE FROM notifications WHERE user_id = :uid",
    ],
)
async def test_a_suspended_account_writes_nothing(session, statement):
    me = await create_user(session)
    async with as_role(session, role_name(platform_tier(PLATFORM_SUSPENDED)), me.id):
        with pytest.raises(DBAPIError) as refused:
            await session.exec(text(statement), params={"uid": me.id})
        await session.rollback()
    assert "permission denied" in str(refused.value)
