"""Role-security test for the settings singleton's stored credentials.

``app_setting_secrets`` holds the SMTP password and the S3 secret access key,
split off ``app_settings`` (migration 0362), which every request role reads.
The new table is read and written on the system engine alone: no request floor
holds a verb on it, no platform tier holds one directly, and it carries no
policy. ``app_settings`` keeps no credential column.

Style mirrors ``token_tables_rls_test``: ``SET ROLE`` drops the superuser setup
session to the role under test, so table grants and policies are enforced as
they are on a real request.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.capabilities import Capability, roles_with_capability
from app.db.public_rls import (
    FORCED_NO_POLICY,
    INSERT,
    SELECT,
    SHARED_TABLE_REGISTRY,
    UPDATE,
    Grants,
    SharedTable,
    platform_tier,
    role_name,
)
from app.db.tenancy import SHARED_TABLES
from app.models.platform.app_setting import AppSetting
from app.services.platform.app_settings import GLOBAL_SETTINGS_ID
from app.testing import as_role, create_user

TABLE = "app_setting_secrets"
MOVED_COLUMNS = ("smtp_password_encrypted", "s3_secret_access_key_encrypted")
PLATFORM_FLOOR = role_name("platform_base")
REQUEST_FLOORS = ("app_user", "app_guild_base", "app_guild_base_ro", PLATFORM_FLOOR)
VERBS = ("SELECT", "INSERT", "UPDATE", "DELETE")


async def _make_rows(session) -> None:
    await session.exec(
        text("INSERT INTO app_settings (id) VALUES (:id) ON CONFLICT DO NOTHING"),
        params={"id": GLOBAL_SETTINGS_ID},
    )
    await session.exec(
        text(
            f"INSERT INTO {TABLE} (id, smtp_password_encrypted, "
            "s3_secret_access_key_encrypted) VALUES (:id, 'smtp-ct', 's3-ct') "
            "ON CONFLICT (id) DO NOTHING"
        ),
        params={"id": GLOBAL_SETTINGS_ID},
    )


def _config_manage_tiers() -> list[str]:
    return sorted(
        role_name(platform_tier(role))
        for role in roles_with_capability(Capability.CONFIG_MANAGE)
    )


def test_registry_records_the_system_engine_alone():
    """No request-path role holds the table, no tier holds a verb of its own,
    no policy admits a row, and the system engine holds what boot, the
    settings routes and the key rotation use."""
    assert TABLE in SHARED_TABLES
    assert SHARED_TABLE_REGISTRY[TABLE] == SharedTable(
        rls=FORCED_NO_POLICY,
        grants=Grants(app_admin=frozenset({SELECT, INSERT, UPDATE})),
    )


def test_app_settings_model_carries_no_credential():
    columns = set(AppSetting.__table__.columns.keys())
    assert not columns & set(MOVED_COLUMNS)


async def test_app_settings_table_carries_no_credential(session):
    present = (
        await session.exec(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'app_settings' "
                "AND column_name = ANY(:names)"
            ),
            params={"names": list(MOVED_COLUMNS)},
        )
    ).all()
    assert present == []


async def test_table_forces_row_security_with_no_policy(session):
    row = (
        await session.exec(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relnamespace = 'public'::regnamespace AND relname = :name"
            ),
            params={"name": TABLE},
        )
    ).one()
    assert (row[0], row[1]) == (True, True)
    policies = (
        await session.exec(
            text(
                "SELECT count(*) FROM pg_policies "
                "WHERE schemaname = 'public' AND tablename = :name"
            ),
            params={"name": TABLE},
        )
    ).scalar_one()
    assert policies == 0


async def test_no_request_role_holds_a_verb(session):
    """The request floors, the seat floor, the install floor and every tier
    holding ``config.manage`` hold nothing on the table."""
    roles = [
        *REQUEST_FLOORS,
        "app_superadmin",
        "plugin_install_base",
        *_config_manage_tiers(),
    ]
    for role in roles:
        for verb in VERBS:
            held = (
                await session.exec(
                    text(f"SELECT has_table_privilege(:r, 'public.{TABLE}', :v)"),
                    params={"r": role, "v": verb},
                )
            ).scalar_one()
            assert not held, f"{role} holds {verb} on {TABLE}"


async def test_every_request_role_is_refused_select(session):
    """Each request floor, and a tier that manages the deployment's
    configuration, is refused a read of the stored credentials."""
    user = await create_user(session)
    await _make_rows(session)
    seen = (await session.exec(text(f"SELECT count(*) FROM {TABLE}"))).scalar_one()
    assert seen == 1

    for role in [*REQUEST_FLOORS, *_config_manage_tiers()]:
        async with as_role(session, role, user.id):
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    await session.exec(
                        text(f"SELECT smtp_password_encrypted FROM {TABLE}")
                    )


async def test_the_system_engine_reads_and_writes_it(session):
    """``app_admin`` reads the row and updates it: its grants are what boot, the
    settings routes and the key rotation run on."""
    user = await create_user(session)
    await _make_rows(session)

    async with as_role(session, "app_admin", user.id), session.begin_nested():
        value = (
            await session.exec(
                text(f"SELECT smtp_password_encrypted FROM {TABLE} WHERE id = 1")
            )
        ).scalar_one()
        assert value == "smtp-ct"
        await session.exec(
            text(
                f"UPDATE {TABLE} SET s3_secret_access_key_encrypted = 'rotated' "
                "WHERE id = 1"
            )
        )
    stored = (
        await session.exec(
            text(f"SELECT s3_secret_access_key_encrypted FROM {TABLE} WHERE id = 1")
        )
    ).scalar_one()
    assert stored == "rotated"
