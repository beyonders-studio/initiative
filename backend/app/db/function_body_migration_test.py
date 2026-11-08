"""Migrations that restate a guild schema's functions run against real schemas.

A restatement only runs where the function already exists, which a database
built from empty never has while it migrates: provisioning renders the
functions afterwards. So these run the restatement against a provisioned
guild schema directly, inside a transaction that is rolled back, leaving the
schema's current bodies in place.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from app.testing import create_guild, create_user

_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _migration(name: str) -> ModuleType:
    path = _VERSIONS / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("which", ["AFTER", "BEFORE"])
async def test_0381_restates_the_access_functions_in_a_provisioned_schema(
    session, which: str
):
    migration = _migration("20260924_0381_an_install_answers_to_its_scopes.py")
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    await session.commit()

    bodies = tuple(
        getattr(migration, f"{name}_{which}")
        for name in ("RESOURCE_LEVEL", "RESOURCE_ACCESS", "ENTITY_ACCESS")
    )
    connection = await session.connection()
    try:
        schemas = await connection.run_sync(
            lambda bind: migration._schemas_holding(bind, migration.RESOURCE_ACCESS_SIG)
        )
        assert f"guild_{guild.id}" in schemas
        await connection.run_sync(lambda bind: migration._restate(bind, bodies))
    finally:
        await session.rollback()
