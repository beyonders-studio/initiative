import importlib.util
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, make_url, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.testing import create_task


@pytest.fixture
async def provisioner() -> AsyncIterator[AsyncEngine]:
    from conftest import TEST_DB_NAME

    engine = create_async_engine(
        make_url(settings.DATABASE_URL).set(database=TEST_DB_NAME), poolclass=NullPool
    )
    try:
        yield engine
    finally:
        await engine.dispose()


def _migration() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20261020_0528_fixed_task_recurrence_anchor.py"
    )
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _run(connection: Connection, step: Callable[[], None]) -> None:
    with Operations.context(MigrationContext.configure(connection)):
        step()


def _assert_provisioner(connection: Connection) -> None:
    assert (
        connection.scalar(text("SELECT session_user"))
        == make_url(settings.DATABASE_URL).username
    )
    role = connection.execute(
        text(
            "SELECT session_user = current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
    ).one()
    assert tuple(role) == (True, False, False)
    table = connection.execute(
        text(
            "SELECT relowner = CAST(current_user AS regrole), relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = CAST('tasks' AS regclass)"
        )
    ).one()
    assert tuple(table) == (True, True, True)
    context = connection.execute(
        text(
            "SELECT current_setting('app.current_user_id', true), current_setting('app.current_guild_id', true)"
        )
    ).one()
    assert all(value in (None, "") for value in context)
    assert (
        connection.scalar(
            text(
                "SELECT count(*) FROM pg_trigger WHERE tgrelid = CAST('tasks' AS regclass) AND NOT tgisinternal AND tgenabled = 'D'"
            )
        )
        == 0
    )


async def _prepare_migration_owner(session: AsyncSession, guild_id: int) -> None:
    # The fixture creates guild tables through its setup connection. Migrations
    # use the provisioning owner, matching the deployment's ownership shape.
    owner = make_url(settings.DATABASE_URL).username
    assert owner is not None
    quoted_owner = session.get_bind().dialect.identifier_preparer.quote(owner)
    connection = await session.connection()
    await connection.execute(
        text(f'ALTER TABLE "guild_{guild_id}".tasks OWNER TO {quoted_owner}')
    )
    await session.commit()


async def test_old_tasks_keep_their_existing_continuation_and_consumed_count(
    session, acting_user, provisioner
):
    a = await acting_user(guild_role="member", initiative=True, project=True)
    first = await create_task(
        session,
        a.project,
        due_date=datetime(2026, 10, 5, 9, tzinfo=UTC),
        recurrence_occurrence_count=2,
    )
    later = await create_task(
        session,
        a.project,
        series_id=first.id,
        due_date=datetime(2026, 10, 9, 9, tzinfo=UTC),
        recurrence_carry={"due_date": "2026-10-07T09:00:00+00:00"},
        recurrence_occurrence_count=3,
        recurrence="RRULE:FREQ=WEEKLY\nRDATE:20261007T090000Z",
    )
    without_history = await create_task(
        session,
        a.project,
        series_id=999999,
        due_date=datetime(2026, 10, 8, 9, tzinfo=UTC),
        recurrence="RRULE:FREQ=DAILY;INTERVAL=3;COUNT=4",
        recurrence_occurrence_count=3,
    )
    await _prepare_migration_owner(session, a.guild.id)
    migration = _migration()
    async with provisioner.begin() as connection:
        await connection.execute(
            text("SELECT set_config('search_path', :path, true)"),
            {"path": f"guild_{a.guild.id}, public"},
        )
        await connection.run_sync(_assert_provisioner)
        assert await connection.scalar(text("SELECT count(*) FROM tasks")) == 0
        await connection.run_sync(_run, migration._drop)
        await connection.run_sync(_run, migration._add)
        await connection.run_sync(_assert_provisioner)
        assert await connection.scalar(text("SELECT count(*) FROM tasks")) == 0
    rows = (
        await session.exec(
            text("SELECT id, recurrence_anchor, recurrence_anchor_count FROM tasks")
        )
    ).all()
    anchors = {row[0]: (row[1], row[2]) for row in rows}
    assert anchors[later.id] == (datetime(2026, 10, 7, 9, tzinfo=UTC), 3)
    assert anchors[without_history.id] == (
        datetime(2026, 10, 8, 9, tzinfo=UTC),
        3,
    )
    from app.services.tenant.task_series import next_dates

    await session.refresh(
        later, attribute_names=["recurrence_anchor", "recurrence_anchor_count"]
    )
    dates = await next_dates(
        session,
        later,
        now=datetime(2026, 10, 10, tzinfo=UTC),
        user_timezone="UTC",
    )
    assert dates is not None
    assert dates[1] == datetime(2026, 10, 14, 9, tzinfo=UTC)
    await session.refresh(
        without_history,
        attribute_names=["recurrence_anchor", "recurrence_anchor_count"],
    )
    assert (
        await next_dates(
            session,
            without_history,
            now=datetime(2026, 10, 10, tzinfo=UTC),
            user_timezone="UTC",
        )
        is None
    )


async def test_a_backfill_exception_restores_force_rls_before_returning(
    session, acting_user, provisioner, monkeypatch
):
    a = await acting_user(guild_role="member", initiative=True, project=True)
    await create_task(
        session,
        a.project,
        recurrence="RRULE:FREQ=DAILY",
        due_date=datetime(2026, 10, 5, tzinfo=UTC),
    )
    await _prepare_migration_owner(session, a.guild.id)
    migration = _migration()
    execute = migration.op.execute
    lifted = []

    async with provisioner.begin() as connection:
        await connection.execute(
            text("SELECT set_config('search_path', :path, true)"),
            {"path": f"guild_{a.guild.id}, public"},
        )
        await connection.run_sync(_assert_provisioner)
        await connection.run_sync(_run, migration._drop)

        def failing_step(sync_connection: Connection) -> None:
            def fail_backfill(statement: str) -> None:
                if statement.lstrip().startswith("UPDATE tasks"):
                    forced = sync_connection.scalar(
                        text(
                            "SELECT relforcerowsecurity FROM pg_class WHERE oid = CAST('tasks' AS regclass)"
                        )
                    )
                    assert forced is False
                    assert (
                        sync_connection.scalar(
                            text(
                                "SELECT count(*) FROM pg_trigger WHERE tgrelid = CAST('tasks' AS regclass) AND NOT tgisinternal AND tgenabled <> 'D'"
                            )
                        )
                        == 0
                    )
                    lifted.append(True)
                    raise RuntimeError("injected backfill failure")
                execute(statement)

            monkeypatch.setattr(migration.op, "execute", fail_backfill)
            with pytest.raises(RuntimeError, match="injected backfill failure"):
                _run(sync_connection, migration._add)
            _assert_provisioner(sync_connection)

        await connection.run_sync(failing_step)
    assert lifted == [True]


async def test_a_sql_backfill_error_rolls_back_columns_data_and_rls(
    session, acting_user, provisioner
):
    a = await acting_user(guild_role="member", initiative=True, project=True)
    due = datetime(2026, 10, 5, tzinfo=UTC)
    task = await create_task(
        session,
        a.project,
        recurrence="RRULE:FREQ=DAILY;COUNT=4",
        due_date=due,
        recurrence_occurrence_count=2,
    )
    # Seed corrupt historical data after a valid save, so the migration's SQL
    # error is exercised rather than the model's current date validation.
    connection = await session.connection()
    await connection.execute(
        text(
            "UPDATE tasks SET recurrence_carry = jsonb_build_object('due_date', CAST(:due AS text)) WHERE id = :id"
        ),
        {"due": "invalid date for rollback test", "id": task.id},
    )
    await _prepare_migration_owner(session, a.guild.id)
    migration = _migration()

    async with provisioner.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.execute(
                text("SELECT set_config('search_path', :path, true)"),
                {"path": f"guild_{a.guild.id}, public"},
            )
            await connection.run_sync(_assert_provisioner)
            await connection.run_sync(_run, migration._drop)
            with pytest.raises(DBAPIError, match="invalid date for rollback test"):
                await connection.run_sync(_run, migration._add)
            await connection.run_sync(_assert_provisioner)
        finally:
            await transaction.rollback()
        async with connection.begin():
            await connection.execute(
                text("SELECT set_config('search_path', :path, true)"),
                {"path": f"guild_{a.guild.id}, public"},
            )
            await connection.run_sync(_assert_provisioner)
            assert await connection.scalar(text("SELECT count(*) FROM tasks")) == 0
            columns = (
                (
                    await connection.execute(
                        text(
                            "SELECT attname FROM pg_attribute WHERE attrelid = CAST('tasks' AS regclass) AND attname IN ('recurrence_anchor', 'recurrence_anchor_count') AND NOT attisdropped"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert set(columns) == {"recurrence_anchor", "recurrence_anchor_count"}
    await session.refresh(
        task,
        attribute_names=[
            "recurrence_anchor",
            "recurrence_anchor_count",
            "recurrence_carry",
        ],
    )
    assert task.recurrence_anchor == due
    assert task.recurrence_anchor_count == 2
    assert task.recurrence_carry == {"due_date": "invalid date for rollback test"}


@pytest.mark.parametrize("state", ["archived_at", "deleted_at", "held_at"])
async def test_guarded_tasks_receive_the_backfill_and_keep_their_state(
    session, acting_user, provisioner, state
):
    a = await acting_user(guild_role="member", initiative=True, project=True)
    moment = datetime(2026, 10, 5, tzinfo=UTC)
    task = await create_task(
        session,
        a.project,
        due_date=moment,
        recurrence="RRULE:FREQ=DAILY;COUNT=4",
        recurrence_occurrence_count=2,
        **{state: moment},
    )
    await _prepare_migration_owner(session, a.guild.id)
    migration = _migration()
    async with provisioner.begin() as connection:
        await connection.execute(
            text("SELECT set_config('search_path', :path, true)"),
            {"path": f"guild_{a.guild.id}, public"},
        )
        await connection.run_sync(_assert_provisioner)
        before = dict(
            (
                await connection.execute(
                    text(
                        "SELECT tgname, tgenabled FROM pg_trigger WHERE tgrelid = CAST('tasks' AS regclass) AND NOT tgisinternal"
                    )
                )
            ).all()
        )
        assert (
            before[f"tr_tasks_{'held' if state == 'held_at' else 'frozen'}_guard"]
            == b"O"
        )
        await connection.run_sync(_run, migration._drop)
        await connection.run_sync(_run, migration._add)
        await connection.run_sync(_assert_provisioner)
        after = dict(
            (
                await connection.execute(
                    text(
                        "SELECT tgname, tgenabled FROM pg_trigger WHERE tgrelid = CAST('tasks' AS regclass) AND NOT tgisinternal"
                    )
                )
            ).all()
        )
        assert after == before
    row = (
        await session.exec(
            text(
                "SELECT recurrence_anchor, recurrence_anchor_count, archived_at, deleted_at, held_at FROM tasks WHERE id = :id"
            ),
            params={"id": task.id},
        )
    ).one()
    assert tuple(row[:2]) == (moment, 2)
    assert tuple(row[2:]) == tuple(
        moment if column == state else None
        for column in ("archived_at", "deleted_at", "held_at")
    )
