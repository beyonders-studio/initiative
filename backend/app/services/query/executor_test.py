"""Running a query, and the limits it runs inside.

These go to a real database: the interesting behaviour is Postgres's, not
ours — a transaction that refuses a write, a role that holds only SELECT, a
planner estimate, a statement timeout.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from asyncpg.exceptions import DatabaseDroppedError, SerializationError

from app.core.messages import QueryMessages
from app.db.guild_standing import GuildContext
from app.db.request_context import ContentGrantee, Member, Platform
from app.models.platform.guild import Guild
from app.db.schema_provisioning import drop_guild_schema, provision_guild_schema
from app.services.fields.spec import FieldType
from app.services.query import executor
from app.services.query import (
    QueryColumn,
    QueryError,
    describe,
    execute,
    resolve,
    run,
)


_GID = 990_200


def _context(guild_id: int) -> Member:
    """What the request's own session would have established.

    The reader's standing rides along as the ``GuildContext`` the seam built,
    because that is what the policies on the tables a statement reads will
    answer to. These tests are about the statement rather than about who may
    read what, so the community here has nothing in it and the standing is an
    administrator's.
    """
    standing = GuildContext(
        guild=Guild(id=guild_id, name="Query probe"),
        user_id=1,
        guild_id=guild_id,
        standing_guild_id=guild_id,
        guild_admin=True,
        guild_auth_ok=True,
    )
    return Member(guild_id=guild_id, user_id=1, standing=standing)


@pytest.fixture
async def guild(engine):
    async with engine.begin() as conn:
        await provision_guild_schema(conn, _GID)
    try:
        yield _GID
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, _GID)


async def test_it_returns_columns_and_rows(guild):
    result = await run("SELECT title FROM tasks", context=_context(guild))
    assert result.columns == (QueryColumn(name="title", type=FieldType.text),)
    assert result.rows == ()


async def test_an_aggregate_answers_without_shipping_the_rows(guild):
    """The shape a stat tile asks for: one number, computed by the database."""
    result = await run(
        "SELECT count(*) AS n FROM tasks",
        context=_context(guild),
    )
    assert result.columns == (QueryColumn(name="n", type=FieldType.number),)
    assert result.rows == ((0,),)


async def test_every_shipped_dashboard_asks_something_postgres_plans(guild):
    """The validator reads a statement; only Postgres can say it groups what
    it shows and that its types meet. A shipped tile it refuses is an error in
    every community that installed the dashboard."""
    from app.services.marketplace.builtin import load_builtin_manifests

    for manifest in load_builtin_manifests():
        if manifest.get("kind") != "dashboard":
            continue
        for widget in manifest["definition"]["widgets"]:
            await describe(widget["binding"]["sql"], context=_context(guild))


async def test_it_reports_what_the_planner_expected(guild):
    result = await run("SELECT title FROM tasks", context=_context(guild))
    assert result.cost > 0


async def test_a_statement_the_planner_prices_too_high_never_runs(guild, monkeypatch):
    monkeypatch.setattr(executor, "QUERY_MAX_COST", 0.0)
    with pytest.raises(QueryError) as refused:
        await run("SELECT title FROM tasks", context=_context(guild))
    assert refused.value.code == QueryMessages.TOO_EXPENSIVE


async def test_a_slow_statement_is_stopped(guild, monkeypatch):
    """The time bound, exercised through the one function that can spend it."""
    monkeypatch.setattr(executor, "QUERY_STATEMENT_TIMEOUT_MS", 100)
    statement = resolve("SELECT title FROM tasks")
    slow = type(statement)(
        sql="SELECT pg_sleep(3) AS slept", parameters=(), relations=("tasks",)
    )
    with pytest.raises(QueryError) as stopped:
        await execute(slow, context=_context(guild))
    assert stopped.value.code == QueryMessages.TIMED_OUT


@pytest.mark.parametrize("stopped_by", [SerializationError, DatabaseDroppedError])
async def test_a_read_the_database_stopped_on_its_own_can_be_asked_again(
    stopped_by,
):
    """What a read replica says when it cancels a statement to keep replaying."""
    with pytest.raises(QueryError) as stopped:
        async with executor._translated_failures():
            raise stopped_by("canceling statement due to conflict with recovery")
    assert stopped.value.code == QueryMessages.INTERRUPTED


@pytest.mark.parametrize(
    ("sql", "answer"),
    [
        # The role holds no write on any table.
        (f"INSERT INTO guild_{_GID}.tasks (title) VALUES ('x')", "permission"),
        # A write the role may make is refused by the transaction, which is
        # read-only before the reader's first statement.
        ("SELECT lo_create(0)", "read-only"),
        # The role cannot change its session's settings: not the transaction's
        # mode, and not what the policies read.
        ("SELECT set_config('transaction_read_only', 'off', true)", "permission"),
        ("SELECT set_config('app.guild_admin', 'true', true)", "permission"),
    ],
)
async def test_the_transaction_refuses_a_write(guild, sql, answer):
    """Reached past the validator on purpose: the transaction and the role
    answer for themselves, so a statement that never went through resolve is
    still refused."""
    statement = resolve("SELECT title FROM tasks")
    write = type(statement)(sql=sql, parameters=(), relations=("tasks",))
    with pytest.raises(Exception) as refused:
        await execute(write, context=_context(guild))
    assert answer in str(refused.value).lower()


async def test_more_rows_than_one_query_returns_are_cut_off(guild, monkeypatch):
    monkeypatch.setattr(executor, "QUERY_MAX_ROWS", 2)
    statement = resolve("SELECT title FROM tasks")
    many = type(statement)(
        sql="SELECT g AS n FROM generate_series(1, 50) AS g",
        parameters=(),
        relations=("tasks",),
    )
    result = await execute(many, context=_context(guild))
    assert len(result.rows) == 2
    assert result.truncated is True


async def test_a_grantee_routes_by_the_grant(guild):
    """A context with no membership but a live grant reads that guild: the
    executor takes whichever the request's own session recorded."""
    result = await run(
        "SELECT title FROM tasks",
        context=ContentGrantee(guild_id=guild, user_id=1),
    )
    assert result.columns == (QueryColumn(name="title", type=FieldType.text),)


async def test_a_context_that_routes_nowhere_is_refused(guild):
    with pytest.raises(QueryError) as refused:
        await run("SELECT title FROM tasks", context=Platform(user_id=1))
    assert refused.value.code == QueryMessages.MISSING_RELATION


async def test_a_query_keeping_both_names_keeps_both_values(guild):
    """``SELECT t.id, p.id`` names both columns ``id``. Rows are positional
    for exactly this: a mapping would keep one of the two."""
    statement = resolve("SELECT title FROM tasks")
    doubled = type(statement)(
        sql="SELECT 1 AS id, 2 AS id",
        parameters=(),
        relations=("tasks",),
    )
    result = await execute(doubled, context=_context(guild))
    assert result.columns == (
        QueryColumn(name="id", type=FieldType.number),
        QueryColumn(name="id", type=FieldType.number),
    )
    assert result.rows == ((1, 2),)


async def test_a_guild_runs_only_so_many_at_once(guild, monkeypatch):
    """The cap is per guild and lives in the database, so it is the cap for
    the deployment rather than for each process serving it."""
    import asyncio

    monkeypatch.setattr(executor, "QUERY_MAX_CONCURRENT_PER_GUILD", 1)
    statement = resolve("SELECT title FROM tasks")
    slow = type(statement)(
        sql="SELECT pg_sleep(2) AS slept", parameters=(), relations=("tasks",)
    )
    held = asyncio.create_task(execute(slow, context=_context(guild)))
    await asyncio.sleep(0.3)
    try:
        with pytest.raises(QueryError) as busy:
            await run("SELECT title FROM tasks", context=_context(guild))
        assert busy.value.code == QueryMessages.BUSY
    finally:
        held.cancel()
        with pytest.raises(BaseException):
            await held


async def test_a_description_that_cannot_be_planned_is_stopped(
    guild, engine, monkeypatch
):
    """Preparing plans, and planning waits its turn for the relation. That wait
    spends the same time bound a running statement does, and ends the same way."""
    monkeypatch.setattr(executor, "QUERY_STATEMENT_TIMEOUT_MS", 250)
    async with engine.connect() as holder:
        await holder.execute(
            sa.text(f"LOCK TABLE guild_{_GID}.tasks IN ACCESS EXCLUSIVE MODE")
        )
        try:
            with pytest.raises(QueryError) as stopped:
                await describe("SELECT title FROM tasks", context=_context(guild))
        finally:
            await holder.rollback()
    assert stopped.value.code == QueryMessages.TIMED_OUT


async def test_a_field_selected_on_its_own_is_typed_by_the_registry(guild):
    """``project_id`` is stored as an integer and means a project. The shape a
    query reports and the fields a dataset offers answer that the same way,
    because one declaration answers both."""
    columns, _ = await describe(
        "SELECT project_id, title FROM tasks", context=_context(guild)
    )
    assert columns == (
        QueryColumn(name="project_id", type=FieldType.reference),
        QueryColumn(name="title", type=FieldType.text),
    )


async def test_an_output_built_from_fields_is_typed_by_the_database(guild):
    """Nothing declares what an expression is, so the database describes it."""
    columns, _ = await describe(
        "SELECT lower(title) AS t, length(title) AS n FROM tasks",
        context=_context(guild),
    )
    assert columns == (
        QueryColumn(name="t", type=FieldType.text),
        QueryColumn(name="n", type=FieldType.number),
    )


async def test_a_moment_comes_back_as_a_moment(guild):
    """Timestamps are epoch milliseconds UTC — the one spelling the widgets
    read — and an exact number is a number rather than its decimal spelling."""
    statement = resolve("SELECT title FROM tasks")
    values = type(statement)(
        sql=(
            "SELECT timestamptz '2026-01-02T03:04:05Z' AS at,"
            " date '2026-01-02' AS on_day,"
            " numeric '12.5' AS exact"
        ),
        parameters=(),
        relations=("tasks",),
    )
    result = await execute(values, context=_context(guild))
    assert result.rows == ((1767323045000, 1767312000000, 12.5),)


async def test_a_length_of_time_is_not_a_moment(guild):
    """An interval is a length, not a point, so nothing offers to place it on a
    timeline."""
    columns, _ = await describe(
        "SELECT interval '3 days' AS gap FROM tasks", context=_context(guild)
    )
    assert columns == (QueryColumn(name="gap", type=FieldType.text),)
