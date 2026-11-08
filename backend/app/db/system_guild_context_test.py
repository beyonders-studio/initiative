"""The narrow, fail-closed guild route used by account erasure."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import text

from app.db.request_context import SystemMaintenance
from app.db.session import set_rls_context
from app.testing.factories import (
    create_comment,
    create_guild,
    create_initiative,
    create_project,
    create_task,
    create_user,
)

OUTBOX_SCAN_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260921_0346_the_poller_scans_the_log_as_the_system.py"
)


_EXPECTED_OUTBOX_SCAN_COLUMN_GRANTS = {
    ("event_outbox", "id", "SELECT"),
    ("event_outbox", "txn_id", "SELECT"),
    ("webhook_deliveries", "subscription_id", "SELECT"),
    ("webhook_deliveries", "txn_id", "SELECT"),
    ("webhook_deliveries", "delivered_at", "SELECT"),
    ("webhook_deliveries", "dead_lettered_at", "SELECT"),
    ("webhook_deliveries", "next_attempt_at", "SELECT"),
}


def _load_migration(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_system_guild_route_keeps_app_admin_bypass_and_denies_app_user(
    session, role_session
) -> None:
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    initiative = await create_initiative(session, guild, owner)
    project = await create_project(session, initiative, owner)
    task = await create_task(session, project)
    await create_comment(session, owner, task=task, content="private")

    admin = await role_session("app_admin")
    await set_rls_context(admin, SystemMaintenance(guild.id))
    identity = (
        await admin.exec(
            text(
                "SELECT current_user, session_user, rolbypassrls, current_schema() "
                "FROM pg_roles WHERE rolname = current_user"
            )
        )
    ).one()
    assert identity == ("app_admin", "app_admin", True, f"guild_{guild.id}")
    assert (await admin.exec(text("SELECT count(*) FROM comments"))).one()[0] == 1

    request_session = await role_session("app_user")
    with pytest.raises(
        PermissionError,
        match="system guild routing requires the configured system login",
    ):
        await set_rls_context(request_session, SystemMaintenance(guild.id))


async def test_outbox_scan_migration_grants_only_its_columns(session, engine) -> None:
    """The poller's candidate scan keeps BYPASSRLS on exactly the columns it
    reads. The migration adds those, and reversing it removes those and nothing
    else — the erasure route's grants from 0278 are left standing."""
    migration = _load_migration(OUTBOX_SCAN_MIGRATION)
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    schema = f"guild_{guild.id}"

    async def direct_column_grants() -> set[tuple[str, str, str]]:
        rows = (
            await session.exec(
                text(
                    "SELECT table_name, column_name, privilege_type "
                    "FROM information_schema.role_column_grants "
                    "WHERE grantee = 'app_admin' AND table_schema = :schema"
                ),
                params={"schema": schema},
            )
        ).all()
        return {(str(row[0]), str(row[1]), str(row[2])) for row in rows}

    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync: migration._revoke_from_schema(sync, schema)
        )
    assert _EXPECTED_OUTBOX_SCAN_COLUMN_GRANTS.isdisjoint(await direct_column_grants())

    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: migration._grant_to_schema(sync, schema))
    after_upgrade = await direct_column_grants()
    assert _EXPECTED_OUTBOX_SCAN_COLUMN_GRANTS <= after_upgrade
    # The erasure route's INSERT grants on the same table are untouched.
    assert ("event_outbox", "txn_id", "INSERT") in after_upgrade

    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync: migration._revoke_from_schema(sync, schema)
        )
    after_downgrade = await direct_column_grants()
    assert _EXPECTED_OUTBOX_SCAN_COLUMN_GRANTS.isdisjoint(after_downgrade)
    assert ("event_outbox", "txn_id", "INSERT") in after_downgrade
