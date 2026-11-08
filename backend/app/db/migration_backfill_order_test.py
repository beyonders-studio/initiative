"""A migration must fill a new table before it locks that table down.

``FORCE ROW LEVEL SECURITY`` binds the table's *owner* — which is the
provisioning role every migration runs as. So the moment a revision turns FORCE
on for a table it just created, its own backfill is subject to that table's
policies: the INSERT needs a matching one, and those policies are written for
the request path, keyed on GUCs (``app.current_user_id``,
``app.current_guild_id``) a migration has no value for. There is nothing to
match, and the insert is rejected — as ``guild_images`` and ``user_avatars``
were, on any database that actually had legacy rows to carry over. A fresh
install has none, so the backfill never runs and CI stays green while every
real upgrade fails.

The order is therefore the fix and the invariant: create the table, move the
rows in, *then* enable RLS and grant. Migration 0179 is the reference.

Scoped to tables the same ``upgrade()`` creates. A pre-existing table is
handled the other way round — lift FORCE for the length of the write and
restore it in the same transaction — and that restore is not a lockdown.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.always


_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"

# "ALTER TABLE public.x FORCE ROW LEVEL SECURITY". The optional "public." and
# the required whitespace before FORCE keep this from matching the "NO FORCE"
# half of a lift-and-restore.
_FORCE = re.compile(
    r"ALTER\s+TABLE\s+(?:public\.)?(\w+)\s+FORCE\s+ROW\s+LEVEL", re.IGNORECASE
)
_WRITE = re.compile(r"(?:INSERT\s+INTO|UPDATE)\s+(?:public\.)?(\w+)", re.IGNORECASE)


def _module_functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def _reachable_strings(
    node: ast.AST, functions: dict[str, ast.FunctionDef], seen: set[str]
) -> list[str]:
    """Every string literal this statement can execute, helpers included.

    A revision keeps its backfill in a helper, so reading only the call site
    would see no SQL at all.
    """
    found: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            found.append(child.value)
        elif isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
            name = child.func.id
            if name in functions and name not in seen:
                seen.add(name)
                found.extend(_reachable_strings(functions[name], functions, seen))
    return found


def _created_tables(upgrade: ast.FunctionDef) -> set[str]:
    created = set()
    for node in ast.walk(upgrade):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "create_table"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            created.add(node.args[0].value)
    return created


def _revisions() -> list[Path]:
    return sorted(p for p in _VERSIONS.glob("*.py") if not p.name.startswith("__"))


@pytest.mark.parametrize("path", _revisions(), ids=lambda p: p.stem)
def test_new_table_is_filled_before_it_is_locked_down(path: Path):
    tree = ast.parse(path.read_text())
    functions = _module_functions(tree)
    upgrade = functions.get("upgrade")
    if upgrade is None:
        pytest.skip("no upgrade()")

    created = _created_tables(upgrade)
    if not created:
        pytest.skip("creates no table")

    forced: dict[str, int] = {}
    written: dict[str, int] = {}
    for statement in upgrade.body:
        for sql in _reachable_strings(statement, functions, set()):
            for table in _FORCE.findall(sql):
                if table in created:
                    forced.setdefault(table, statement.lineno)
            for table in _WRITE.findall(sql):
                if table in created:
                    written.setdefault(table, statement.lineno)

    for table, force_line in forced.items():
        write_line = written.get(table)
        if write_line is None:
            continue
        assert write_line < force_line, (
            f"{path.name}: rows are written to public.{table} at line "
            f"{write_line}, after FORCE ROW LEVEL SECURITY is enabled on it at "
            f"line {force_line}. The migration runs as the table's owner, which "
            "FORCE makes policy-bound, and no policy matches a migration's "
            "empty request context — so the write is rejected on every database "
            "that has rows to move. Fill the table first, then lock it down."
        )
