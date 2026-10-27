"""Every permission key must be reachable by a backfill migration.

A tool that ships adds two ``PermissionKey`` members, and every role created
before that release keeps storing the ones it already had. Nothing is
mis-authorized — an absent row reads as its default — but the stored role no
longer matches the role the code describes.

The guard is the union of the ``_ROLE_PERMISSION_DEFAULTS`` maps across every
migration that declares one: if a new tool's keys are in none of them, the tool
shipped without a backfill and this fails with the missing names.

Each such migration states its own SQL rather than sharing a helper (a helper
holding table names and column names would let a later edit change what a past
revision does), so this loads the migration by path and runs the statement it
actually carries.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import ModuleType

from sqlalchemy import text

from app.models.tenant.initiative import PermissionKey
from app.testing import create_guild, create_initiative, create_user

VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
DEFAULTS_NAME = "_ROLE_PERMISSION_DEFAULTS"


def _backfill_migrations() -> dict[Path, set[str]]:
    """Each migration declaring a defaults map, and the keys it names."""
    found: dict[Path, set[str]] = {}
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        source = path.read_text()
        if DEFAULTS_NAME not in source:
            continue
        module = ast.parse(source)
        keys: set[str] = set()
        for node in ast.walk(module):
            if not isinstance(node, ast.AnnAssign | ast.Assign):
                continue
            targets = (
                [node.target] if isinstance(node, ast.AnnAssign) else list(node.targets)
            )
            named = any(
                isinstance(t, ast.Name) and t.id == DEFAULTS_NAME for t in targets
            )
            if named and isinstance(node.value, ast.Dict):
                keys.update(
                    k.value
                    for k in node.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                )
        if keys:
            found[path] = keys
    return found


def _load(path: Path) -> ModuleType:
    """Import a migration by path — they are not on the import path."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_permission_key_has_a_backfill_migration() -> None:
    backfilled: set[str] = set()
    for keys in _backfill_migrations().values():
        backfilled |= keys

    missing = {key.value for key in PermissionKey} - backfilled
    assert not missing, (
        "These permission keys were added without backfilling the roles that "
        f"predate them: {sorted(missing)}. Add a guild-scoped migration that "
        f"declares a {DEFAULTS_NAME} map naming them and runs its own INSERT — "
        "see 20260907_0233, which is meant to be copied rather than imported."
    )


async def test_backfill_writes_only_the_missing_rows(session) -> None:
    """A role stripped of a key gets it back at the documented default, and a
    row that already exists is left alone — including one an operator turned
    off. Runs the statement the migration itself carries."""
    migrations = _backfill_migrations()
    assert migrations, "no backfill migration found to exercise"
    path = max(migrations)
    migration = _load(path)
    # A key a later tool's removal retired is not one this build stores.
    known = {key.value for key in PermissionKey}
    defaults = {
        key: value
        for key, value in getattr(migration, DEFAULTS_NAME).items()
        if key in known
    }

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)

    schema = f"guild_{guild.id}"
    await session.exec(text(f'SET LOCAL search_path TO "{schema}", public'))

    roles = (
        await session.exec(
            text(
                "SELECT id, name, is_builtin FROM initiative_roles "
                "WHERE initiative_id = :iid"
            ).bindparams(iid=initiative.id)
        )
    ).all()
    pm = next(r for r in roles if r.name == "project_manager")
    member = next(r for r in roles if r.name == "member")

    # Simulate a tool that shipped after these roles were created: drop the
    # posts rows from both. Then turn a surviving row off, to prove the
    # backfill does not rewrite it.
    await session.exec(
        text(
            "DELETE FROM initiative_role_permissions "
            "WHERE initiative_role_id IN (:pm, :member) "
            "AND permission_key IN ('posts_enabled', 'create_posts')"
        ).bindparams(pm=pm.id, member=member.id)
    )
    await session.exec(
        text(
            "UPDATE initiative_role_permissions SET enabled = false "
            "WHERE initiative_role_id = :pm AND permission_key = 'projects_enabled'"
        ).bindparams(pm=pm.id)
    )

    await session.exec(text(migration.backfill_sql(defaults)))

    stored = {
        (row.initiative_role_id, row.permission_key): row.enabled
        for row in (
            await session.exec(
                text(
                    "SELECT initiative_role_id, permission_key, enabled "
                    "FROM initiative_role_permissions "
                    "WHERE initiative_role_id IN (:pm, :member)"
                ).bindparams(pm=pm.id, member=member.id)
            )
        ).all()
    }

    # Restored: the PM gets everything, an ordinary role gets the default.
    assert stored[(pm.id, "posts_enabled")] is True
    assert stored[(pm.id, "create_posts")] is True
    assert stored[(member.id, "posts_enabled")] is False
    assert stored[(member.id, "create_posts")] is False
    # Untouched: the row an operator turned off is still off.
    assert stored[(pm.id, "projects_enabled")] is False
    # Every key now has a row on every role.
    for role_id in (pm.id, member.id):
        assert {k for (r, k) in stored if r == role_id} == set(defaults)
