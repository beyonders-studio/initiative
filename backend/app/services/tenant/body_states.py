"""A collaborative body's two views, and how the server moves between them.

A body is stored twice: its JSON ``content``, which everything outside a live
session reads, and its Yjs state, which a session edits. The server makes the
state from the content when a row has none, renders the content from the state
when a room saves, and writes a change to the content into the state, rewriting
only what changed. How depends on the editor whose state it is:

- a file or wiki page is the Lexical editor's, which only the editor itself
  maps (:mod:`app.services.editor_engine`);
- a whiteboard is one Excalidraw scene, held as a JSON string under
  ``excalidraw.scene`` (``WhiteboardDocumentEditor.tsx``);
- a spreadsheet is a ``sheets`` map of sheet containers
  (``spreadsheet/workbookDoc.ts``).

The last two are plain Yjs maps, which ``pycrdt`` reads and writes as the
browser's Yjs does, so they need no editor.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional, Protocol

from pycrdt import Doc, Map

from app.core.file_types import FileType
from app.core.identity_boundary import MentionForm, without_mention_names
from app.services import editor_engine

logger = logging.getLogger(__name__)


class BodyState(Protocol):
    async def bootstrap(self, content: Any) -> bytes:
        """The Yjs state of a body reading as ``content``, as stored."""
        ...

    def holds_body(self, state: bytes) -> bool:
        """Whether ``state`` holds a body at all. One a browser saved before
        writing anything into it does not, and the content is the body."""
        ...

    async def render(self, state: bytes) -> Optional[dict]:
        """The content ``state`` reads as, or ``None`` when it holds no body
        to read."""
        ...

    async def apply(self, state: bytes, content: dict) -> bytes:
        """The Yjs update that makes ``state`` read as ``content``."""
        ...


def _js(value: Any) -> Any:
    """``value`` as JSON reads it in the browser. Yjs keeps every number as a
    float, so a whole one comes back here as ``3.0`` where the editor wrote,
    and ``JSON.stringify`` writes, ``3``."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _js(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_js(v) for v in value]
    return value


def _same(a: Any, b: Any) -> bool:
    # Compared as JSON: ``True == 1`` in Python, and a cell holding one is not
    # a cell holding the other.
    return json.dumps(_js(a), sort_keys=True) == json.dumps(_js(b), sort_keys=True)


def _written(state: Optional[bytes], write: Callable[[Doc], None]) -> bytes:
    """What ``write`` changes in ``state``, as an update from a Yjs client of
    its own; the whole state when there is none to start from."""
    doc = Doc()
    if state:
        doc.apply_update(state)
    before = doc.get_state()
    with doc.transaction():
        write(doc)
    return bytes(doc.get_update(before))


def _read(state: bytes) -> Doc:
    doc = Doc()
    doc.apply_update(state)
    return doc


def _editor_state(content: Any) -> Optional[dict]:
    """``content`` as the editor can start from it, or ``None`` for an empty
    file. A body nobody has written is stored as ``{}``, or as a root with
    no children, and the editor refuses both as a starting state."""
    root = content.get("root") if isinstance(content, dict) else None
    children = root.get("children") if isinstance(root, dict) else None
    return content if isinstance(children, list) and children else None


class _Lexical:
    async def bootstrap(self, content: Any) -> bytes:
        return await editor_engine.bootstrap(_editor_state(content))

    def holds_body(self, state: bytes) -> bool:
        # The editor reads any state as a document, an empty one included.
        return True

    async def render(self, state: bytes) -> Optional[dict]:
        return without_mention_names(
            await editor_engine.render(state), MentionForm.lexical
        )

    async def apply(self, state: bytes, content: dict) -> bytes:
        return await editor_engine.apply(state, content)


_SCENE_MAP = "excalidraw"
_SCENE_KEY = "scene"


def _scene(value: Any) -> Optional[dict]:
    """The scene a whiteboard's live value holds, or ``None`` for none."""
    if not isinstance(value, str):
        return None
    try:
        scene = json.loads(value)
    except json.JSONDecodeError:
        logger.warning("A whiteboard's live scene is not JSON")
        return None
    return scene if isinstance(scene, dict) else None


class _Whiteboard:
    """The scene is one value, written whole: the editor resolves concurrent
    drawing the same way, last write wins."""

    @staticmethod
    def _normalized(content: Any) -> dict:
        from app.services.tenant.files import normalize_file_content

        return normalize_file_content(content, file_type=FileType.excalidraw)

    async def bootstrap(self, content: Any) -> bytes:
        return await self.apply(b"", self._normalized(content))

    def holds_body(self, state: bytes) -> bool:
        return _read(state).get(_SCENE_MAP, type=Map).get(_SCENE_KEY) is not None

    async def render(self, state: bytes) -> Optional[dict]:
        scene = _scene(_read(state).get(_SCENE_MAP, type=Map).get(_SCENE_KEY))
        return None if scene is None else self._normalized(scene)

    async def apply(self, state: bytes, content: dict) -> bytes:
        def write(doc: Doc) -> None:
            scene = doc.get(_SCENE_MAP, type=Map)
            if _same(_scene(scene.get(_SCENE_KEY)), content):
                return
            scene[_SCENE_KEY] = json.dumps(
                content, separators=(",", ":"), ensure_ascii=False
            )

        return _written(state, write)


_SHEETS = "sheets"
_META = "meta"
#: A sheet's maps of entries, named as the v3 content names them.
_PARTS = ("cells", "columns", "rows", "cellStyles")
#: What a sheet's ``meta`` map holds, and where in the content each one is.
_META_FIELDS = (
    ("name", ("name",)),
    ("rows", ("dimensions", "rows")),
    ("cols", ("dimensions", "cols")),
    ("frozenRows", ("frozen", "rows")),
    ("frozenCols", ("frozen", "cols")),
)


def _number(value: Any, fallback: int) -> Any:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _js(value)
    return fallback


class _Spreadsheet:
    """Each sheet is a container of five maps, one entry per cell or format, so
    a write changes the entries that differ and leaves the rest — and anybody
    editing them — alone."""

    @staticmethod
    def _normalized(content: Any) -> dict:
        from app.services.tenant.files_spreadsheet import (
            normalize_spreadsheet_content,
        )

        return normalize_spreadsheet_content(content)

    async def bootstrap(self, content: Any) -> bytes:
        from app.services.tenant.files import FileContentError

        try:
            workbook = self._normalized(content)
        except FileContentError:
            logger.warning("A spreadsheet's stored content is not a workbook")
            workbook = self._normalized(None)
        return await self.apply(b"", workbook)

    def holds_body(self, state: bytes) -> bool:
        doc = _read(state)
        return any(len(doc.get(key, type=Map)) for key in (_SHEETS, _META, *_PARTS))

    async def render(self, state: bytes) -> Optional[dict]:
        from app.services.tenant.files import FileContentError

        doc = _read(state)
        sheets: list[tuple[Any, str, dict]] = []
        for sheet_id, container in doc.get(_SHEETS, type=Map).items():
            if isinstance(container, Map):
                sheets.append(self._sheet(sheet_id, container))
        if not sheets:
            # Written before a workbook held several sheets: its maps sit at
            # the top of the file, and are the one sheet.
            legacy = {key: doc.get(key, type=Map) for key in (_META, *_PARTS)}
            if not any(len(part) for part in legacy.values()):
                return None
            sheets.append(self._sheet(None, legacy))
        # Tab order, ties broken by id, as the editor lists them.
        sheets.sort(key=lambda sheet: (sheet[0], sheet[1]))
        try:
            return self._normalized(
                {
                    "schema_version": 3,
                    "kind": "spreadsheet",
                    "sheets": [sheet for _, _, sheet in sheets],
                }
            )
        except FileContentError:
            logger.warning("A spreadsheet's live state is not a workbook")
            return None

    @staticmethod
    def _sheet(sheet_id: Optional[str], container: Any) -> tuple[Any, str, dict]:
        def part(key: str) -> dict:
            value = container.get(key)
            return dict(value.items()) if isinstance(value, Map) else {}

        meta = part(_META)
        order = meta.get("order")
        sheet: dict[str, Any] = {
            "name": meta.get("name"),
            "dimensions": {
                "rows": _number(meta.get("rows"), 100),
                "cols": _number(meta.get("cols"), 26),
            },
            "frozen": {
                "rows": _number(meta.get("frozenRows"), 0),
                "cols": _number(meta.get("frozenCols"), 0),
            },
            "cells": {
                key: _js(value)
                for key, value in part("cells").items()
                if value is None or isinstance(value, (str, int, float, bool))
            },
        }
        for key in ("columns", "rows", "cellStyles"):
            sheet[key] = {
                index: _js(value)
                for index, value in part(key).items()
                if isinstance(value, dict)
            }
        if sheet_id is not None:
            sheet["id"] = sheet_id
        if meta.get("hidden") is True:
            sheet["hidden"] = True
        position = order if isinstance(order, (int, float)) else float("inf")
        return position, sheet_id or "", sheet

    async def apply(self, state: bytes, content: dict) -> bytes:
        def write(doc: Doc) -> None:
            root = doc.get(_SHEETS, type=Map)
            wanted = [sheet["id"] for sheet in content["sheets"]]
            for sheet_id in [key for key in root.keys() if key not in wanted]:
                del root[sheet_id]
            for order, sheet in enumerate(content["sheets"]):
                container = root.get(sheet["id"])
                if not isinstance(container, Map):
                    container = root[sheet["id"]] = Map()
                for key in (_META, *_PARTS):
                    if not isinstance(container.get(key), Map):
                        container[key] = Map()
                meta = {key: _dig(sheet, path) for key, path in _META_FIELDS}
                meta["order"] = order
                # Absent rather than false for a shown sheet, as the editor
                # writes it.
                if sheet.get("hidden") is True:
                    meta["hidden"] = True
                _sync(container[_META], meta)
                for key in _PARTS:
                    _sync(container[key], sheet[key])
            # A file from before several sheets keeps its maps at the
            # top; the workbook now holds them.
            for key in (_META, *_PARTS):
                legacy = doc.get(key, type=Map)
                for entry in list(legacy.keys()):
                    del legacy[entry]

        return _written(state, write)


def _dig(content: dict, path: tuple[str, ...]) -> Any:
    for key in path:
        content = content[key]
    return content


def _sync(target: Map, wanted: dict) -> None:
    """Make ``target`` hold ``wanted``, writing only the entries that differ."""
    for key in [key for key in target.keys() if key not in wanted]:
        del target[key]
    for key, value in wanted.items():
        if key not in target or not _same(target[key], value):
            target[key] = value


LEXICAL: BodyState = _Lexical()
WHITEBOARD: BodyState = _Whiteboard()
SPREADSHEET: BodyState = _Spreadsheet()

_BY_KIND: dict[str, BodyState] = {
    FileType.lexical.value: LEXICAL,
    FileType.excalidraw.value: WHITEBOARD,
    FileType.sheet.value: SPREADSHEET,
}


def for_row(row: Any) -> Optional[BodyState]:
    """How a stored row's body moves between its views: a file's by its
    type, a wiki page's as prose."""
    from app.models.tenant.file import File

    return for_kind(row.file_type) if isinstance(row, File) else LEXICAL


def for_kind(kind: Any) -> Optional[BodyState]:
    """How a body of ``kind`` — a file type, ``lexical`` for any Lexical
    body — moves between its views; ``None`` for one with no live editor."""
    return _BY_KIND.get(getattr(kind, "value", kind))
