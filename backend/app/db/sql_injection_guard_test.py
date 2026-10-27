"""Static guard against new string-built SQL sites (Tier 1 regression net).

Interpolating a value into raw SQL (f-string, ``%`` format, or ``str.format``)
inside a ``text()`` / ``execute()`` / ``exec_driver_sql()`` call is the shape
that turns a value into SQL text. This test inventories every
such site under ``app/`` and asserts the set matches a **reviewed allowlist**:
each entry was audited and is safe only because what it interpolates is an
integer-derived identifier (``guild_<id>``), a module constant, operator
config, or a catalog identifier that is quoted server-side — never
request-derived data.

When this test fails it means a new dynamic-SQL site appeared (or a known one
moved/left). A NEW site must be reviewed and, only if it interpolates nothing
request-derived, added to ``ALLOWED_DYNAMIC_SQL`` with a one-line reason.
This forces a human to look before any new string-built SQL lands.

Known limitation (by design, this is a tripwire not a proof): it flags the
common *direct* pattern ``text(f"...")``. It does not follow a value through
a local variable (``sql = f"..."; execute(text(sql))``) — the paired
identifier-builder unit tests and the request-path audit cover the rest.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.always


# app/ package dir and the backend root the keys are expressed relative to.
_APP_DIR = Path(__file__).resolve().parents[1]
_BACKEND_DIR = _APP_DIR.parent

# Callables whose SQL-string argument we care about.
_SQL_CALLEES = {"text", "exec_driver_sql", "execute", "executescript"}

# Reviewed, safe dynamic-SQL sites. Key: "<relpath>::<enclosing.qualname>".
# Value: why the interpolation carries no request data. Provisioning / DDL /
# admin-job layer only — the request path (endpoints, services) must stay empty.
ALLOWED_DYNAMIC_SQL: dict[str, str] = {
    "app/db/guild_ddl.py::<module>": (
        "module-level DDL templates interpolate only the _SRC_SCHEMA constant "
        "('guild_template'); table lists are bound params"
    ),
    "app/db/guild_ddl.py::render_guild_schema_ddl": (
        "reflected catalog identifiers from the Alembic-owned guild_template, "
        "quoted; no request data"
    ),
    "app/db/schema_provisioning.py::_apply_parts": (
        "int-derived guild_<id> schema name + hex-digest stamp"
    ),
    "app/db/schema_provisioning.py::apply_guild_schema": (
        "int-derived schema name + reflected guild_template DDL"
    ),
    "app/db/schema_provisioning.py::_write_stamp": (
        "int-derived guild_<id> schema name + hex-digest stamp"
    ),
    "app/db/schema_provisioning.py::apply_guild_checks": (
        "int-derived schema name + CHECKs rendered from model declarations (constants)"
    ),
    "app/db/schema_provisioning.py::apply_guild_rls": (
        "int-derived schema name + registry-rendered RLS DDL (constants)"
    ),
    "app/db/schema_provisioning.py::apply_guild_capture": (
        "int-derived schema name + registry-rendered trigger DDL (constants)"
    ),
    "app/db/schema_provisioning.py::apply_guild_search": (
        "int-derived schema name + registry-rendered trigger DDL (constants)"
    ),
    "app/db/schema_provisioning.py::apply_guild_timers": (
        "int-derived schema name + registry-rendered trigger DDL (constants)"
    ),
    "app/db/schema_provisioning.py::reindex_guild_search": (
        "int-derived guild_<id> schema name, registry-rendered "
        "reindex statements (constants), and a hex-digest generation marker"
    ),
    "app/db/schema_provisioning.py::drop_guild_schema": (
        "int-derived guild_<id> schema/role names"
    ),
    "app/testing/guild_pool.py::activate": (
        "test harness: int-derived guild_<id> / test_pool_<id> schema names"
    ),
    "app/testing/guild_pool.py::install": (
        "test harness: int-derived test_pool_<id> schema name"
    ),
    "app/testing/guild_pool.py::drop": (
        "test harness: int-derived test_pool_<id> schema name"
    ),
    "app/models/tenant/property.py::PropertyValue": (
        "model DDL: the CHECK lists the PROPERTY_TARGETS constant, the partial "
        "indexes name the model's own value columns"
    ),
    "app/db/schema_provisioning.py::strip_template_registry_objects": (
        "the TEMPLATE_SCHEMA constant; policy, trigger and table names read "
        "from the catalog and quoted; function names and argument lists from "
        "the authorization registry constants"
    ),
    "app/db/authorization.py::drop_public_copies": (
        "boot step; function names and argument lists are the "
        "GUILD_FUNCTION_SIGNATURES registry constants under the public schema"
    ),
    "app/db/public_rls.py::apply_public_rls_if_changed": (
        "boot step; the schema comment is the STAMP_PREFIX constant plus a hex "
        "digest of the registry render"
    ),
    "app/db/backfill_uploads_to_s3.py::_guild_upload_meta": (
        "admin backfill job; schema name is int-derived guild_<id>"
    ),
    "app/db/backfill_uploads_to_s3.py::_guild_import_payloads": (
        "admin backfill job; schema name is int-derived guild_<id>"
    ),
    "app/db/bootstrap.py::_revoke_former_set_config_holders": (
        "startup on the owner connection: role names read from pg_roles, "
        "quoted; the function signature is a module constant"
    ),
    "app/services/storage_backfill.py::_persist": (
        "SET clause joined from literal 'col = :bind' fragments; all values bound"
    ),
}


def _is_dynamic_sql_arg(node: ast.AST) -> bool:
    """True if this argument builds SQL by interpolation rather than a literal
    or a bound-parameter placeholder string."""
    if isinstance(node, ast.JoinedStr):  # f"..."
        return any(isinstance(v, ast.FormattedValue) for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):  # "..." % x
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr == "format":  # "...".format(...)
            return True
    return False


def _callee_name(func: ast.AST) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _scan_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    rel = path.relative_to(_BACKEND_DIR).as_posix()
    stack: list[str] = []
    found: list[str] = []

    class _V(ast.NodeVisitor):
        def _enter(self, name: str, node: ast.AST) -> None:
            stack.append(name)
            self.generic_visit(node)
            stack.pop()

        def visit_FunctionDef(self, node):  # noqa: N802
            self._enter(node.name, node)

        def visit_AsyncFunctionDef(self, node):  # noqa: N802
            self._enter(node.name, node)

        def visit_ClassDef(self, node):  # noqa: N802
            self._enter(node.name, node)

        def visit_Call(self, node):  # noqa: N802
            if _callee_name(node.func) in _SQL_CALLEES:
                if any(_is_dynamic_sql_arg(a) for a in node.args):
                    qual = ".".join(stack) or "<module>"
                    found.append(f"{rel}::{qual}")
            self.generic_visit(node)

    _V().visit(tree)
    return found


def _inventory() -> set[str]:
    sites: set[str] = set()
    for path in _APP_DIR.rglob("*.py"):
        if path.name.endswith("_test.py"):
            continue
        sites.update(_scan_file(path))
    return sites


def test_no_unreviewed_dynamic_sql_sites():
    """The set of dynamic-SQL sites must exactly match the reviewed allowlist."""
    current = _inventory()
    allowed = set(ALLOWED_DYNAMIC_SQL)

    unreviewed = sorted(current - allowed)
    stale = sorted(allowed - current)

    assert not unreviewed, (
        "New dynamic-SQL site(s) found under app/. Review each: it is safe ONLY "
        "if it interpolates an int-derived identifier, a constant, operator "
        "config, or a quoted catalog identifier — never request data. If safe, "
        "add it to ALLOWED_DYNAMIC_SQL with a one-line reason:\n  "
        + "\n  ".join(unreviewed)
    )
    assert not stale, (
        "Allowlisted dynamic-SQL site(s) no longer present — remove the stale "
        "entries from ALLOWED_DYNAMIC_SQL:\n  " + "\n  ".join(stale)
    )


def test_request_path_has_no_dynamic_sql():
    """Endpoints and non-DB services must contain zero dynamic-SQL sites — the
    request path stays fully parameterized. All allowlisted sites live in the
    db/ provisioning layer or admin jobs."""
    request_path_sites = sorted(
        site
        for site in _inventory()
        if site.startswith("app/api/")
        or (
            site.startswith("app/services/")
            # storage_backfill is an admin maintenance job, not a request path.
            and not site.startswith("app/services/storage_backfill.py")
        )
    )
    assert request_path_sites == [], (
        "Dynamic SQL appeared on the request path (endpoint/service). Request "
        "handlers must use ORM column objects and bound parameters only:\n  "
        + "\n  ".join(request_path_sites)
    )
