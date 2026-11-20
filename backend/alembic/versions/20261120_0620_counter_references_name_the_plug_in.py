"""counter references name the plug-in

20261119_0619 made Counters the Counters tool plug-in, whose kinds are
``counter_group.tsjvtcm0s7gv2x`` and ``counter.tsjvtcm0s7gv2x``, under the
same ids, and gave every column naming a kind the plug-in's. This gives what
content says the same spelling, in ``guild_template`` and every
``guild_<id>``:

* **Running text**, in every text and JSON column of the schema (a comment, a
  description, a checklist): ``#counter-group[Scores](4)`` is
  ``#counter-group.tsjvtcm0s7gv2x[Scores](4)`` and ``#counter[Laps](5)`` is
  ``#counter.tsjvtcm0s7gv2x[Laps](5)``. A word written in the kind's own
  spelling (``#counter_group``) keeps it.
* **A Lexical body**, in every JSON column, and in a file's or a wiki page's
  Yjs state, read and written through the editor: an ``entity-mention`` or a
  ``reference-embed`` whose ``entityType`` is ``counter_group`` or ``counter``
  names the plug-in's kind. A ``smart-chip`` of one (``counter:value``, a fact
  the plug-in does not offer) is an ``entity-mention`` of it, with the words
  it stored. A reference an import is still waiting to place
  (``importSourceRef``) is spelled the same way.

The downgrade spells them the built-in way again. A chip made a link stays a
link.

The writes run with each table's row security unforced and its user triggers
held, both restored in the same transaction once they are done.

Revision ID: 20261120_0620
Revises: 20261119_0619
Create Date: 2026-11-20
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from alembic import op
from pycrdt import Doc
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.util import await_only

import app.services.editor_engine as editor_engine
from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261120_0620"
down_revision = "20261119_0619"
branch_labels = None
depends_on = None

_UID = "tsjvtcm0s7gv2x"
#: Each built-in kind and the plug-in's kind it became.
_KINDS = {"counter_group": f"counter_group.{_UID}", "counter": f"counter.{_UID}"}
_BACK = {new: old for old, new in _KINDS.items()}

#: A ``#`` reference in running text, by the word the composer wrote.
_WORDS = "counter-group|counter_group|counter"
_LINK = r"(\[[^]]*\]\([0-9]+\))"
_TEXT_FORWARD = (f"#({_WORDS}){_LINK}", rf"#\1.{_UID}\2")
_TEXT_BACK = (rf"#({_WORDS})\.{_UID}{_LINK}", r"#\1\2")

#: A reference node of a counter kind in a body's JSON.
_KEYS = "entityType|chipKind|importSourceRef"
_NODE_FORWARD = f'"({_KEYS})": ?"counter(_group)?[":]'
_NODE_BACK = rf'"({_KEYS})": ?"counter(_group)?\.{_UID}[":]'

#: A counter kind in a Yjs state: a kind is stored as a whole string value,
#: its length before it, and a chip's as ``kind:aspect``.
_YJS_FORWARD = (b"\x77\x07counter", b"\x77\x0dcounter_group", b"counter:")
_YJS_BACK = (f".{_UID}".encode(),)

#: Bodies an editor session edits, each with a Yjs state beside its JSON, and
#: which of their rows hold a Lexical body.
_LIVE_BODIES = (("files", "file_type = 'lexical'"), ("wiki_pages", "true"))

_REFERENCE_NODES = ("entity-mention", "reference-embed", "smart-chip")
_SOURCE_REF = "importSourceRef"


def _ref(ref: str, kinds: dict[str, str]) -> str:
    """``kind:id`` spelled with ``kinds``."""
    kind, separator, rest = ref.partition(":")
    return f"{kinds.get(kind, kind)}{separator}{rest}"


def _node(node: dict[str, Any], forward: bool) -> dict[str, Any]:
    """One reference node spelled the other way."""
    kinds = _KINDS if forward else _BACK
    out = dict(node)
    if isinstance(out.get(_SOURCE_REF), str):
        out[_SOURCE_REF] = _ref(out[_SOURCE_REF], kinds)
    chip = out.get("chipKind")
    if out.get("type") == "smart-chip" and isinstance(chip, str):
        kind = chip.partition(":")[0]
        if forward and kind in kinds:
            mention = {
                "type": "entity-mention",
                "version": 1,
                "entityType": kinds[kind],
                "entityId": out.get("entityId"),
                "text": out.get("text") or "",
            }
            if _SOURCE_REF in out:
                mention[_SOURCE_REF] = out[_SOURCE_REF]
            return mention
        return out
    kind = out.get("entityType")
    if isinstance(kind, str) and kind in kinds:
        out["entityType"] = kinds[kind]
    return out


def _rewrite(value: Any, forward: bool) -> Any:
    """Every reference node anywhere in a JSON value spelled the other way.
    Returns new values and never edits ``value``."""
    if isinstance(value, list):
        return [_rewrite(item, forward) for item in value]
    if not isinstance(value, dict):
        return value
    if value.get("type") in _REFERENCE_NODES:
        value = _node(value, forward)
    return {key: _rewrite(item, forward) for key, item in value.items()}


def _as_json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


@contextmanager
def _held(bind: Connection, table: str) -> Iterator[None]:
    """Unforce the table's row security and hold its user triggers, restoring
    both afterwards. A failure rolls the whole revision back, these changes
    with it, so nothing is restored on that path."""
    forced = bind.execute(
        text("SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"),
        {"t": table},
    ).scalar()
    if forced:
        bind.exec_driver_sql(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
    bind.exec_driver_sql(f'ALTER TABLE "{table}" DISABLE TRIGGER USER')
    yield
    bind.exec_driver_sql(f'ALTER TABLE "{table}" ENABLE TRIGGER USER')
    if forced:
        bind.exec_driver_sql(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')


def _columns(bind: Connection) -> list[tuple[str, str, str]]:
    """Every text and JSON column of the schema's tables, and its type. A
    ``character varying`` with a length holds a name, never a body."""
    return [
        (table, column, kind)
        for table, column, kind in bind.execute(
            text(
                "SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod)"
                " FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid"
                " WHERE c.relnamespace = current_schema()::regnamespace"
                " AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped"
                " AND format_type(a.atttypid, a.atttypmod)"
                " IN ('text', 'character varying', 'json', 'jsonb')"
                " ORDER BY c.relname, a.attnum"
            )
        ).all()
    ]


def _matches(bind: Connection, table: str, column: str, pattern: str) -> bool:
    return bool(
        bind.execute(
            text(
                f'SELECT EXISTS (SELECT 1 FROM "{table}"'
                f' WHERE CAST("{column}" AS text) ~ :p)'
            ),
            {"p": pattern},
        ).scalar()
    )


def _live_bodies(bind: Connection, forward: bool) -> None:
    """Rewrite each body whose Yjs state names a kind to rewrite, through the
    editor, its JSON with it."""
    needles = _YJS_FORWARD if forward else _YJS_BACK
    found = " OR ".join(
        f"position(CAST(:n{i} AS bytea) IN yjs_state) > 0" for i in range(len(needles))
    )
    params = {f"n{i}": needle for i, needle in enumerate(needles)}
    started = False
    for table, lexical in _LIVE_BODIES:
        if not bind.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar():
            continue
        rows = bind.execute(
            text(
                f"SELECT id, content, yjs_state FROM {table}"
                f" WHERE {lexical} AND yjs_state IS NOT NULL AND ({found})"
            ),
            params,
        ).all()
        if not rows:
            continue
        with _held(bind, table):
            for row_id, content, state in rows:
                if not started:
                    # An editor that cannot start fails the revision here.
                    await_only(editor_engine.bootstrap(None))
                    started = True
                try:
                    reading = await_only(editor_engine.render(bytes(state)))
                except editor_engine.EditorError:
                    # A state the editor refuses opens nowhere: the body is
                    # its JSON, which the pass over JSON columns rewrites.
                    continue
                rewritten = _rewrite(reading, forward)
                if rewritten == reading:
                    continue
                doc = Doc()
                doc.apply_update(bytes(state))
                doc.apply_update(
                    await_only(editor_engine.apply(bytes(state), rewritten))
                )
                body = _rewrite(_as_json(content), forward)
                bind.execute(
                    text(
                        f"UPDATE {table} SET content = CAST(:c AS jsonb),"
                        " yjs_state = :s, yjs_updated_at = now() WHERE id = :id"
                    ),
                    {"c": json.dumps(body), "s": bytes(doc.get_update()), "id": row_id},
                )


def _bodies(bind: Connection, forward: bool) -> None:
    """Rewrite the reference nodes in every JSON column, row by row."""
    pattern = _NODE_FORWARD if forward else _NODE_BACK
    for table, column, kind in _columns(bind):
        if kind not in ("json", "jsonb") or not _matches(bind, table, column, pattern):
            continue
        with _held(bind, table):
            rows = bind.execute(
                text(
                    f'SELECT CAST(ctid AS text), "{column}" FROM "{table}"'
                    f' WHERE CAST("{column}" AS text) ~ :p'
                ),
                {"p": pattern},
            ).all()
            for ctid, value in rows:
                value = _as_json(value)
                rewritten = _rewrite(value, forward)
                if rewritten == value:
                    continue
                bind.execute(
                    text(
                        f'UPDATE "{table}" SET "{column}" = CAST(:v AS {kind})'
                        " WHERE ctid = CAST(:ctid AS tid)"
                    ),
                    {"v": json.dumps(rewritten), "ctid": ctid},
                )


def _running_text(bind: Connection, forward: bool) -> None:
    """Rewrite the ``#`` references in every text and JSON column."""
    pattern, replacement = _TEXT_FORWARD if forward else _TEXT_BACK
    for table, column, kind in _columns(bind):
        if not _matches(bind, table, column, pattern):
            continue
        with _held(bind, table):
            bind.execute(
                text(
                    f'UPDATE "{table}" SET "{column}" = CAST(regexp_replace('
                    f"CAST(\"{column}\" AS text), :p, :r, 'g') AS {kind})"
                    f' WHERE CAST("{column}" AS text) ~ :p'
                ),
                {"p": pattern, "r": replacement},
            )


def _apply(forward: bool) -> None:
    bind = op.get_bind()
    _live_bodies(bind, forward)
    _bodies(bind, forward)
    _running_text(bind, forward)


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), lambda: _apply(True))


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), lambda: _apply(False))
