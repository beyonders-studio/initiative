"""a mention keeps no name

A mention of somebody with an account is stored by id alone, and the app takes
the name out on every write. This takes it out of what was written before:
``@[Ada](42)`` becomes ``@[](42)`` in markdown, and a Lexical mention node
keeps its ``mentionUserId`` with ``mentionName`` and ``text`` empty. A mention
of somebody with no account keeps its name, which is all it has. Text inside an
editor state is what somebody typed, not markdown, and is left alone.

The columns are stated here rather than read from any registry, so this
revision reads the same whatever the modules say later. Archived, template and
trashed rows are rewritten too. A document's or wiki page's collaboration
state, which an editor from before can have written a name into, has its
mentions made nameless the same way, as an edit on top of it. The tables' row
security and request triggers (the freeze, change capture, search) are held
while rows change, and a guild with rows changed has its search marker
cleared, so the next start reindexes it. Rows are read in batches.

The downgrade leaves content as it is: the names are kept nowhere.

Revision ID: 20261002_0444
Revises: 20261002_0443
Create Date: 2026-10-02
"""

import json
import re
from typing import Any, Optional

import sqlalchemy as sa
from alembic import op
from pycrdt import Doc, Text, XmlElement, XmlText
from pycrdt._base import base_types
from sqlalchemy.engine import Connection

from app.db.guild_migrations import guild_schema_names

revision = "20261002_0444"
down_revision = "20261002_0443"
branch_labels = None
depends_on = None

#: A markdown mention that still carries a name, as Python and Postgres read it.
_NAMED = r"@\[[^\]]+\]\(([0-9]+)\)"
#: An editor-state mention node naming an account, in the column's text.
_NAMED_NODE = r'"mentionUserId":\s*[0-9]'
#: Rows read at a time from a ``jsonb`` column.
_BATCH = 500

#: Markdown columns that can hold a mention.
TEXT_COLUMNS: dict[str, tuple[str, ...]] = {
    "calendar_events": ("description", "location"),
    "calendars": ("description",),
    "comments": ("content",),
    "counter_groups": ("description",),
    "dashboards": ("description",),
    "galleries": ("description",),
    "gallery_images": ("caption",),
    "initiatives": ("description",),
    "projects": ("description",),
    "queue_items": ("notes",),
    "queues": ("description",),
    "tasks": ("description",),
    "wikis": ("description",),
}
#: Editor states, whose mentions are nodes.
EDITOR_STATES: dict[str, str] = {
    "documents": "content",
    "posts": "body",
    "wiki_pages": "content",
}
#: ``jsonb`` columns holding markdown: a checklist's lines, a repeat's
#: description.
MARKDOWN_IN_JSON: dict[str, tuple[str, ...]] = {
    "tasks": ("checklist", "recurrence_carry"),
}
#: Tables whose rows keep a collaboration state beside their editor state.
_COLLABORATIVE = ("documents", "wiki_pages")


def _nameless(value: Any, *, markdown: bool) -> tuple[Any, bool]:
    """``value`` with no mention by id carrying a name — every node, and with
    ``markdown`` every string's markdown mentions — and whether anything
    changed."""
    pattern = re.compile(_NAMED)
    changed = False

    def walk(node: Any) -> Any:
        nonlocal changed
        if isinstance(node, str):
            if not markdown:
                return node
            stripped = pattern.sub(r"@[](\1)", node)
            changed = changed or stripped != node
            return stripped
        if isinstance(node, list):
            return [walk(item) for item in node]
        if not isinstance(node, dict):
            return node
        node = {key: walk(child) for key, child in node.items()}
        user_id = node.get("mentionUserId")
        if (
            isinstance(user_id, int)
            and not isinstance(user_id, bool)
            and (node.get("mentionName") or node.get("text"))
        ):
            node |= {"mentionName": "", "text": ""}
            changed = True
        return node

    return walk(value), changed


def _nameless_state(state: bytes) -> Optional[bytes]:
    """A collaboration state with no mention by id holding a name, or ``None``
    where none held one.

    The editor's binding keeps a document under the root ``root``: an element
    as an ``XmlText`` embedded in its parent, and a decorator, a mention among
    them, as an ``XmlElement`` whose attributes are its properties, the name in
    ``__mention`` and the id in ``__mentionUserId``. A state that cannot be
    read is left as it is: collaboration never loads one, and starts from the
    content instead.
    """
    doc = Doc()
    changed = False

    def walk(text: Text) -> None:
        nonlocal changed
        for value, _ in text.diff():
            kind = base_types.get(type(value))
            node = kind(_doc=doc, _integrated=value) if kind else None
            if isinstance(node, XmlText):
                walk(node)
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


def _batches(bind: Connection, statement: str, params: dict) -> Any:
    """The rows ``statement`` selects, ``_BATCH`` at a time by id. It selects
    ``id`` first and reads ``:after`` and ``:batch``."""
    after = 0
    while True:
        rows = bind.execute(
            sa.text(statement), {**params, "after": after, "batch": _BATCH}
        ).all()
        if not rows:
            return
        yield from rows
        after = rows[-1].id


def strip_schema(bind: Connection, schema: str) -> None:
    """Take the names out of one guild schema's mentions, with the tables'
    row security and request triggers held while rows change."""
    tables = sorted({*TEXT_COLUMNS, *EDITOR_STATES, *MARKDOWN_IN_JSON})
    for table in tables:
        bind.execute(
            sa.text(f'ALTER TABLE "{schema}".{table} NO FORCE ROW LEVEL SECURITY')
        )
        bind.execute(sa.text(f'ALTER TABLE "{schema}".{table} DISABLE TRIGGER USER'))
    try:
        changed = _strip(bind, schema)
    finally:
        for table in tables:
            bind.execute(sa.text(f'ALTER TABLE "{schema}".{table} ENABLE TRIGGER USER'))
            bind.execute(
                sa.text(f'ALTER TABLE "{schema}".{table} FORCE ROW LEVEL SECURITY')
            )
    if changed:
        bind.execute(sa.text(f'COMMENT ON TABLE "{schema}".search_entries IS NULL'))


def _strip(bind: Connection, schema: str) -> int:
    """The names taken out of one schema's mentions; the rows changed."""
    changed = 0
    for table, columns in TEXT_COLUMNS.items():
        for column in columns:
            changed += bind.execute(
                sa.text(
                    f'UPDATE "{schema}".{table}'  # noqa: S608 — stated names
                    f" SET {column} = regexp_replace({column}, :named, :id, 'g')"
                    f" WHERE {column} ~ :named"
                ),
                {"named": _NAMED, "id": r"@[](\1)"},
            ).rowcount
    columns = [(table, column, False) for table, column in EDITOR_STATES.items()]
    columns += [
        (table, column, True)
        for table, held in MARKDOWN_IN_JSON.items()
        for column in held
    ]
    for table, column, markdown in columns:
        pattern = f"{_NAMED_NODE}|{_NAMED}" if markdown else _NAMED_NODE
        for row in _batches(
            bind,
            f'SELECT id, {column} AS value FROM "{schema}".{table}'  # noqa: S608
            f" WHERE id > :after AND {column}::text ~ :pattern"
            " ORDER BY id LIMIT :batch",
            {"pattern": pattern},
        ):
            value, did = _nameless(row.value, markdown=markdown)
            if not did:
                continue
            bind.execute(
                sa.text(
                    f'UPDATE "{schema}".{table}'  # noqa: S608
                    f" SET {column} = CAST(:value AS jsonb) WHERE id = :id"
                ),
                {"value": json.dumps(value), "id": row.id},
            )
            changed += 1
    for table in _COLLABORATIVE:
        for row in _batches(
            bind,
            f'SELECT id, yjs_state AS state FROM "{schema}".{table}'  # noqa: S608
            " WHERE id > :after AND yjs_state IS NOT NULL"
            " AND content::text ~ :pattern ORDER BY id LIMIT :batch",
            {"pattern": _NAMED_NODE},
        ):
            state = _nameless_state(row.state)
            if state is not None:
                bind.execute(
                    sa.text(
                        f'UPDATE "{schema}".{table}'  # noqa: S608
                        " SET yjs_state = :state WHERE id = :id"
                    ),
                    {"state": state, "id": row.id},
                )
    return changed


def upgrade() -> None:
    bind = op.get_bind()
    for schema in guild_schema_names(bind):
        if schema.removeprefix("guild_").isdigit():
            strip_schema(bind, schema)


def downgrade() -> None:
    # The names are kept nowhere to put back.
    pass
