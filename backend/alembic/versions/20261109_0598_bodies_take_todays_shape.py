"""Bodies take today's shape

Rewrites the bodies older releases wrote in shapes the current app no longer
reads, in ``guild_template`` and every ``guild_<id>``:

* **Hashtags** — a ``hashtag`` node, which no editor has written since
  2026-09-01, becomes the ``text`` node it has read as since, its other fields
  kept: in the JSON of a ``lexical`` file, a wiki page and a post, and in the
  Yjs state of a file and a wiki page (the ``__type`` of the text node's map).
* **Mentions** — in the Yjs state of a ``lexical`` file and a wiki page, a
  mention of somebody by id has its name (``__mention``) cleared, as their
  JSON already has. In the JSON, a mention written before mentions were
  decorator nodes carries no ``mentionName``; it gains one, empty (with its
  ``text``) for somebody by id, its ``text`` for a mention with no id.
* **Spreadsheets** — a ``sheet`` file's content in the single-sheet shapes
  (versions 1 and 2: the sheet's ``dimensions``, ``cells``, formatting maps
  and ``frozen`` at the top level) becomes a version 3 workbook whose one
  sheet, ``s1`` named ``Sheet1``, holds them, any of the formatting maps or
  ``frozen`` it lacked empty. Its Yjs state, when its sheet maps (``meta``,
  ``cells``, ``columns``, ``rows``, ``cellStyles``) are at the top of the
  document and its ``sheets`` map is empty, has each one's entries copied into
  the same map of sheet ``s1`` in ``sheets``, as the editor copied them on
  opening such a file; the sheet is named as the content's first sheet and
  ordered first unless its ``meta`` already says. Where ``sheets`` holds a
  sheet already, the top-level maps are only emptied.

The readers of the old shapes go with this revision: a spreadsheet payload in
version 1 or 2 is refused, and a Yjs state is read by its ``sheets`` alone.

Only rows that hold an old shape are written. A Yjs state that cannot be read
is left as it is: collaboration never loads one, and starts from the content.
The writes run with each table's row security unforced and its user triggers
held, both restored in the same transaction once they are done.

Revision ID: 20261109_0598
Revises: 20261109_0597
Create Date: 2026-11-09
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from alembic import op
from pycrdt import Doc, Map, Text, XmlElement, XmlText
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261109_0598"
down_revision = "20261109_0597"
branch_labels = None
depends_on = None

#: Lexical bodies with a Yjs state beside their JSON, and which rows hold one.
_LIVE_BODIES = (("files", "file_type = 'lexical'"), ("wiki_pages", "true"))
#: Lexical bodies with no Yjs state.
_STATE_BODIES = (("posts", "body"),)
_TABLES = ("files", "wiki_pages", "posts")

#: A JSON body holding a node of an old shape.
_OLD_IN_JSON = (
    'lax $.** ? (@.type == "hashtag" '
    '|| (@.type == "mention" && !(exists(@.mentionName))))'
)
#: A Yjs state that may: a node typed ``hashtag`` (a string value, its length
#: before it), or a mention of somebody by id.
_OLD_IN_YJS = (b"\x77\x07hashtag", b"__mentionUserId")

#: The maps of one sheet, which a file from before workbooks kept at the top of
#: its Yjs document (``workbookDoc.ts``), in the order the editor creates them.
_SHEET_PARTS = ("meta", "cells", "columns", "rows", "cellStyles")
_FIRST_SHEET = "s1"
_FIRST_SHEET_NAME = "Sheet1"

_SHEET_CONTENT = f"""
UPDATE files SET content = jsonb_build_object(
    'schema_version', 3,
    'kind', 'spreadsheet',
    'sheets', jsonb_build_array(
        '{{"dimensions": {{"rows": 100, "cols": 26}}, "cells": {{}},
          "columns": {{}}, "rows": {{}}, "cellStyles": {{}},
          "frozen": {{"rows": 0, "cols": 0}}}}'::jsonb
        || (content - 'schema_version' - 'kind')
        || '{{"id": "{_FIRST_SHEET}", "name": "{_FIRST_SHEET_NAME}"}}'::jsonb
    )
)
WHERE file_type = 'sheet'
  AND jsonb_typeof(content) = 'object'
  AND content <> '{{}}'::jsonb
  AND NOT content ? 'sheets'
"""


@contextmanager
def _held(bind: Connection, tables: tuple[str, ...]) -> Iterator[None]:
    """Unforce each table's row security and hold its user triggers, restoring
    both afterwards. A failure rolls the whole revision back, these changes
    with it, so nothing is restored on that path."""
    forced: list[str] = []
    held: list[str] = []
    for table in tables:
        state = bind.execute(
            text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
        if state is None:
            continue
        if state:
            bind.exec_driver_sql(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            forced.append(table)
        bind.exec_driver_sql(f"ALTER TABLE {table} DISABLE TRIGGER USER")
        held.append(table)
    yield
    for table in held:
        bind.exec_driver_sql(f"ALTER TABLE {table} ENABLE TRIGGER USER")
    for table in forced:
        bind.exec_driver_sql(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _as_json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _json_body(value: Any) -> Any:
    """A Lexical body's JSON with each node of an old shape in today's."""
    if isinstance(value, list):
        return [_json_body(item) for item in value]
    if not isinstance(value, dict):
        return value
    node = {key: _json_body(item) for key, item in value.items()}
    if node.get("type") == "hashtag":
        node["type"] = "text"
    elif node.get("type") == "mention" and "mentionName" not in node:
        if node.get("mentionUserId") is None:
            node["mentionName"] = node.get("text", "")
        else:
            node["mentionName"] = node["text"] = ""
    return node


def _lexical_state(state: bytes) -> bytes | None:
    """A Lexical body's Yjs state with each node of an old shape in today's,
    or ``None`` when it holds none or cannot be read.

    The editor's binding keeps a document under the root ``root``: an element
    as an ``XmlText`` embedded in its parent, a text node as a ``Map`` of its
    properties embedded before its text, and a decorator, a mention among them,
    as an ``XmlElement`` whose attributes are its properties. Each change is an
    edit on top of the state, so nothing else in it moves.
    """
    doc = Doc()
    changed = False

    def walk(parent: Text | XmlText) -> None:
        nonlocal changed
        for node, _attrs in parent.diff():
            if isinstance(node, XmlText):
                walk(node)
            elif isinstance(node, Map) and node.get("__type") == "hashtag":
                node["__type"] = "text"
                changed = True
            elif (
                isinstance(node, XmlElement)
                and node.attributes.get("__type") == "mention"
                and node.attributes.get("__mentionUserId") is not None
                and node.attributes.get("__mention")
            ):
                node.attributes["__mention"] = ""
                changed = True

    try:
        doc.apply_update(state)
        walk(doc.get("root", type=Text))
    except Exception:
        return None
    return bytes(doc.get_update()) if changed else None


def _plain(value: Any) -> Any:
    return value.to_py() if isinstance(value, Map) else value


def _sheet_state(state: bytes, name: str) -> bytes | None:
    """A spreadsheet's Yjs state with its top-level sheet maps moved into its
    first sheet (``workbookDoc.ts``, ``ensureWorkbook``), or ``None`` when no
    top-level map holds anything or the state cannot be read."""
    doc = Doc()
    try:
        doc.apply_update(state)
        legacy = {key: doc.get(key, type=Map) for key in _SHEET_PARTS}
        if not any(len(part) for part in legacy.values()):
            return None
        with doc.transaction():
            sheets = doc.get("sheets", type=Map)
            if not len(sheets):
                container = sheets[_FIRST_SHEET] = Map()
                for key in _SHEET_PARTS:
                    container[key] = Map()
                for key, part in legacy.items():
                    target = container[key]
                    for entry, value in part.items():
                        target[entry] = _plain(value)
                meta = container["meta"]
                if not isinstance(meta.get("name"), str):
                    meta["name"] = name
                if not isinstance(meta.get("order"), (int, float)):
                    meta["order"] = 0
            for part in legacy.values():
                for entry in list(part.keys()):
                    del part[entry]
    except Exception:
        return None
    return bytes(doc.get_update())


def _ids(bind: Connection, sql: str, params: dict[str, Any] | None = None) -> list:
    return list(bind.execute(text(sql), params or {}).scalars())


def _write_state(bind: Connection, table: str, row_id: int, state: bytes) -> None:
    bind.execute(
        text(f"UPDATE {table} SET yjs_state = :s WHERE id = :id"),
        {"s": state, "id": row_id},
    )


def _lexical(bind: Connection) -> None:
    """Each Lexical body's JSON and Yjs state, read a row at a time."""
    bodies = (
        *((table, "content", lexical) for table, lexical in _LIVE_BODIES),
        *((table, column, "true") for table, column in _STATE_BODIES),
    )
    for table, column, lexical in bodies:
        for row_id in _ids(
            bind,
            f"SELECT id FROM {table} WHERE {lexical} "
            f"AND jsonb_path_exists({column}, CAST(:old AS jsonpath))",
            {"old": _OLD_IN_JSON},
        ):
            body = bind.execute(
                text(f"SELECT {column} FROM {table} WHERE id = :id"), {"id": row_id}
            ).scalar()
            bind.execute(
                text(f"UPDATE {table} SET {column} = CAST(:b AS jsonb) WHERE id = :id"),
                {"b": json.dumps(_json_body(_as_json(body))), "id": row_id},
            )
    needles = {f"n{i}": needle for i, needle in enumerate(_OLD_IN_YJS)}
    in_yjs = " OR ".join(
        f"position(CAST(:{key} AS bytea) IN yjs_state) > 0" for key in needles
    )
    for table, lexical in _LIVE_BODIES:
        for row_id in _ids(
            bind,
            f"SELECT id FROM {table} WHERE {lexical} "
            f"AND yjs_state IS NOT NULL AND ({in_yjs})",
            needles,
        ):
            state = bind.execute(
                text(f"SELECT yjs_state FROM {table} WHERE id = :id"), {"id": row_id}
            ).scalar()
            rewritten = _lexical_state(bytes(state))
            if rewritten is not None:
                _write_state(bind, table, row_id, rewritten)


def _spreadsheets(bind: Connection) -> None:
    """Each spreadsheet's content, then its Yjs state, read a row at a time."""
    bind.exec_driver_sql(_SHEET_CONTENT)
    for row_id in _ids(
        bind,
        "SELECT id FROM files WHERE file_type = 'sheet' AND yjs_state IS NOT NULL",
    ):
        state, name = bind.execute(
            text(
                "SELECT yjs_state, content #>> '{sheets,0,name}' FROM files "
                "WHERE id = :id"
            ),
            {"id": row_id},
        ).one()
        rewritten = _sheet_state(bytes(state), name or _FIRST_SHEET_NAME)
        if rewritten is not None:
            _write_state(bind, "files", row_id, rewritten)


def _upgrade_schema(bind: Connection) -> None:
    """One guild schema, the one the search_path names."""
    with _held(bind, _TABLES):
        _lexical(bind)
        _spreadsheets(bind)


def upgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, lambda: _upgrade_schema(bind))


def downgrade() -> None:
    """The old shapes are not restored: the release before this one reads
    today's shapes too."""
