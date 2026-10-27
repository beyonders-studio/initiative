"""Static guard: uploads are stored through one function.

Every file a person or an import brings into a guild is written by
``attachments.store_upload``, which writes the bytes and adds the ``uploads``
row the serve route requires and the storage quota sums. Two shapes are
confined to it and to a short list of named exceptions:

* ``Upload(...)`` — a row for a stored file.
* A function that takes a guild's storage (``get_guild_storage(...)``) and
  writes to it (``.write`` / ``.write_file``, called or handed to a thread).

The exceptions store something that is not an upload — an export artifact, a
staged import payload — or record a copy of bytes already stored. A new
upload path that writes around ``store_upload`` fails here instead of relying
on a reviewer to notice.

The walk is syntactic, like ``app/api/context_seam_guard_test.py``: it reads
each function as written and does not follow a storage handle passed in from
somewhere else.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.always


_APP_DIR = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _APP_DIR.parent

_SEAM = "app/services/tenant/attachments.py::store_upload"

#: Where an ``uploads`` row may be built other than the seam, and why.
_ROW_EXCEPTIONS = {
    # A copy of a file the guild already stores; its row carries the source's
    # size, type and hash, and no new bytes arrive.
    "app/services/tenant/attachments.py::copy_uploads",
    # A file that arrived in parts (``app.services.resumable``), recorded where
    # it was staged once its type is checked; ``store_upload`` records through
    # it too.
    "app/services/tenant/attachments.py::record_upload",
    # Test data.
    "app/testing/factories.py",
}

#: Functions that write a guild's storage other than the seam, and why.
_WRITE_EXCEPTIONS = {
    # Export artifacts: rendered by the server from files already stored.
    "app/services/export/engine.py::render_to_storage",
    "app/services/export/engine.py::_stream_zip_to_storage",
    # Staged import payloads: never served; their members are stored through
    # the seam when the import runs.
    "app/services/import_engine/engine.py::stage_payload",
    "app/services/import_engine/engine.py::stage_payload_file",
    # Evidence: sealed under a key of its own and reached only through its
    # own row, never through the upload route.
    "app/services/platform/evidence.py::store",
}


def _runtime_files() -> list[Path]:
    return sorted(p for p in _APP_DIR.rglob("*.py") if not p.name.endswith("_test.py"))


def _callee(node: ast.Call) -> str | None:
    fn = node.func
    if isinstance(fn, ast.Attribute):
        return fn.attr
    if isinstance(fn, ast.Name):
        return fn.id
    return None


def _functions(path: Path):
    rel = path.relative_to(_BACKEND_DIR).as_posix()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield rel, node


def _builds_upload_row(fn: ast.AST) -> bool:
    return any(isinstance(n, ast.Call) and _callee(n) == "Upload" for n in ast.walk(fn))


def _is_storage_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and _callee(node) == "get_guild_storage"


def _writes_guild_storage(fn: ast.AST) -> bool:
    """Whether ``fn`` writes through a guild storage handle: the resolver's
    result directly, or a name assigned from it."""
    nodes = list(ast.walk(fn))
    handles = {
        target.id
        for n in nodes
        if isinstance(n, ast.Assign) and _is_storage_call(n.value)
        for target in n.targets
        if isinstance(target, ast.Name)
    }
    return any(
        isinstance(n, ast.Attribute)
        and n.attr in {"write", "write_file"}
        and (
            _is_storage_call(n.value)
            or (isinstance(n.value, ast.Name) and n.value.id in handles)
        )
        for n in nodes
    )


def test_only_the_seam_builds_an_upload_row():
    offenders = sorted(
        f"{rel}::{fn.name}:{fn.lineno}"
        for path in _runtime_files()
        for rel, fn in _functions(path)
        if _builds_upload_row(fn)
        and f"{rel}::{fn.name}" != _SEAM
        and not {rel, f"{rel}::{fn.name}"} & _ROW_EXCEPTIONS
    )
    assert offenders == [], (
        "store an upload with attachments.store_upload, which writes the bytes "
        f"and records the row together: {offenders}"
    )


def test_only_the_seam_writes_an_upload_to_guild_storage():
    offenders = sorted(
        f"{rel}::{fn.name}:{fn.lineno}"
        for path in _runtime_files()
        for rel, fn in _functions(path)
        if _writes_guild_storage(fn)
        and f"{rel}::{fn.name}" not in _WRITE_EXCEPTIONS | {_SEAM}
    )
    assert offenders == [], (
        "store an upload with attachments.store_upload; a write that is not an "
        f"upload belongs in this test's exceptions, with its reason: {offenders}"
    )


def test_the_exceptions_still_exist():
    """An exception whose function is gone would quietly admit a new one of
    the same name."""
    found = {
        f"{rel}::{fn.name}"
        for path in _runtime_files()
        for rel, fn in _functions(path)
        if _writes_guild_storage(fn)
    }
    assert _WRITE_EXCEPTIONS | {_SEAM} <= found
