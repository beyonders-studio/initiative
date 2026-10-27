"""Library items have a description and a date

In ``guild_template`` and every ``guild_<id>``:

* **Columns** — ``library_items.caption`` is ``description``, and the new
  ``occurred_on`` is the day an item is about. Every existing item is dated
  the day it was added (in UTC), which is where it already sat in its
  library. ``ix_library_items_library_order`` orders a library by it.
* **Row security** — the policies on ``library_items`` are dropped and row
  security disabled before the DDL, then enabled and forced again; with no
  policies the table admits only the system engine until the next start
  renders them from the registries, before any request is served. The
  downgrade does the same.
* **Stored values** — an item layout that places ``caption`` places
  ``description``; a library item's change, and a webhook subscription's
  fields, list ``description`` where they listed ``caption``; a dashboard's
  statements that read ``library_items`` read ``description``.

In ``public``: a library listing's items, and a dashboard listing's statements
that read ``library_items``, say ``description`` where they said ``caption``.

The downgrade reverses each rewrite and drops the dates.

Revision ID: 20261026_0542
Revises: 20261026_0541
Create Date: 2026-10-26
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261026_0542"
down_revision = "20261026_0541"
branch_labels = None
depends_on = None

_OLD, _NEW = "caption", "description"
_ORDER_INDEX = "ix_library_items_library_order"
#: Listing kinds that are not a tool's: their definitions are not envelopes.
_NOT_TOOL_LISTINGS = ("plugin", "auto", "profile_pack")


def _names(forward: bool) -> tuple[str, str]:
    return (_OLD, _NEW) if forward else (_NEW, _OLD)


def _table_exists(bind: Connection, table: str) -> bool:
    return bool(bind.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar())


def _writable(bind: Connection, table: str, fn: Callable[[], None]) -> None:
    """Run ``fn`` with ``table``'s row security unforced and its user triggers
    held, then restore both. A failure rolls the whole revision back, so
    nothing is restored on that path."""
    if not _table_exists(bind, table):
        return
    forced = bool(
        bind.execute(
            text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
    )
    if forced:
        bind.exec_driver_sql(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    bind.exec_driver_sql(f"ALTER TABLE {table} DISABLE TRIGGER USER")
    fn()
    bind.exec_driver_sql(f"ALTER TABLE {table} ENABLE TRIGGER USER")
    if forced:
        bind.exec_driver_sql(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


# --- statements --------------------------------------------------------------

#: What a statement is read as: a string value (single- or dollar-quoted),
#: left as written; a double-quoted name; or a bare word.
_TOKEN = re.compile(
    r"'(?:[^']|'')*'|\$(\w*)\$.*?\$\1\$|\"((?:[^\"]|\"\")*)\"|\b(\w+)\b", re.S
)
_STRINGS = re.compile(r"'(?:[^']|'')*'|\$(\w*)\$.*?\$\1\$", re.S)
_AFTER_AS = re.compile(r"\bAS\s*$", re.I)
_QUALIFIED = re.compile(r"\.\s*$")
_ORDER_BY = re.compile(r"\bORDER\s+BY\b", re.I)
_READS_ITEMS = re.compile(r"\blibrary_items\b", re.I)


def _statement(sql: str, old: str, new: str) -> str:
    """``sql`` reading ``new`` for the column ``old``, when it reads
    ``library_items`` at all.

    A name the statement gives an output column is its author's: it is kept
    where it is declared (after ``AS``), and where its ``ORDER BY`` names it
    unqualified, which reads an output column before an input one."""
    if not _READS_ITEMS.search(sql):
        return sql
    blank = _STRINGS.sub(lambda m: " " * len(m.group(0)), sql)
    declared = re.search(rf'\bAS\s+"?{re.escape(old)}"?(?![\w"])', blank, re.I)
    sorts = [m.start() for m in _ORDER_BY.finditer(blank)]
    sorted_from = sorts[-1] if declared and sorts else len(sql)

    def respell(token: re.Match[str]) -> str:
        quoted, bare = token.group(2), token.group(3)
        named = quoted if quoted is not None else bare
        if named is None or (named if quoted is not None else named.lower()) != old:
            return token.group(0)
        before = sql[: token.start()]
        if _AFTER_AS.search(before):
            return token.group(0)
        if token.start() > sorted_from and not _QUALIFIED.search(before):
            return token.group(0)
        return f'"{new}"' if quoted is not None else new

    return _TOKEN.sub(respell, sql)


def _sql_respeller(forward: bool) -> Callable[[Any], Any]:
    old, new = _names(forward)

    def respell(value: Any) -> Any:
        if isinstance(value, list):
            return [respell(item) for item in value]
        if not isinstance(value, dict):
            return value
        return {
            key: (
                _statement(item, old, new)
                if key == "sql" and isinstance(item, str)
                else respell(item)
            )
            for key, item in value.items()
        }

    return respell


def _respell_json(
    bind: Connection,
    table: str,
    columns: tuple[str, ...],
    respell: Callable[[Any], Any],
    *,
    select_from: str | None = None,
) -> None:
    """Rewrite JSON ``columns`` of ``table`` row by row, where ``respell``
    changes them."""
    source = select_from or f"SELECT id, {', '.join(columns)} FROM {table}"
    for row in bind.execute(text(source)).all():
        row_id, values = row[0], row[1 : 1 + len(columns)]
        for column, value in zip(columns, values):
            if value is None:
                continue
            if isinstance(value, str):
                value = json.loads(value)
            respelled = respell(value)
            if respelled != value:
                bind.execute(
                    text(
                        f"UPDATE {table} SET {column} = CAST(:v AS jsonb) WHERE id = :id"
                    ),
                    {"v": json.dumps(respelled), "id": row_id},
                )


# --- guild schemas -----------------------------------------------------------


def _lift_row_security(bind: Connection) -> tuple[bool, bool] | None:
    """Drop every policy on ``library_items`` and disable its row security,
    returning its (enabled, forced) to restore."""
    state = bind.execute(
        text(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE oid = to_regclass('library_items')"
        )
    ).first()
    if state is None:
        return None
    names = bind.execute(
        text(
            "SELECT polname FROM pg_policy WHERE polrelid = to_regclass('library_items')"
        )
    ).scalars()
    for name in list(names):
        bind.exec_driver_sql(f'DROP POLICY IF EXISTS "{name}" ON library_items')
    bind.exec_driver_sql("ALTER TABLE library_items DISABLE ROW LEVEL SECURITY")
    return bool(state[0]), bool(state[1])


def _restore_row_security(bind: Connection, held: tuple[bool, bool]) -> None:
    """Enable and force row security again. The table has no policies until
    the next start renders them, which admits nobody but the system engine
    meanwhile."""
    enabled, forced = held
    if enabled:
        bind.exec_driver_sql("ALTER TABLE library_items ENABLE ROW LEVEL SECURITY")
    if forced:
        bind.exec_driver_sql("ALTER TABLE library_items FORCE ROW LEVEL SECURITY")


def _structure(bind: Connection, forward: bool) -> None:
    held = _lift_row_security(bind)
    if held is None:
        return
    old, new = _names(forward)
    bind.exec_driver_sql(f"ALTER TABLE library_items RENAME COLUMN {old} TO {new}")
    if forward:
        bind.exec_driver_sql("ALTER TABLE library_items ADD COLUMN occurred_on date")
        _writable(
            bind,
            "library_items",
            lambda: bind.exec_driver_sql(
                "UPDATE library_items "
                "SET occurred_on = (created_at AT TIME ZONE 'UTC')::date"
            ),
        )
        bind.exec_driver_sql(
            "ALTER TABLE library_items ALTER COLUMN occurred_on SET NOT NULL"
        )
        bind.exec_driver_sql(
            f"CREATE INDEX {_ORDER_INDEX} ON library_items "
            "(library_id, occurred_on, created_at, id)"
        )
    else:
        bind.exec_driver_sql(f"DROP INDEX IF EXISTS {_ORDER_INDEX}")
        bind.exec_driver_sql("ALTER TABLE library_items DROP COLUMN occurred_on")
    _restore_row_security(bind, held)


def _stored_values(bind: Connection, forward: bool) -> None:
    old, new = _names(forward)
    names = {"old": old, "new": new}
    placed = {"old": f'"field": "{old}"', "new": f'"field": "{new}"'}

    _writable(
        bind,
        "tool_layouts",
        lambda: bind.execute(
            text(
                "UPDATE tool_layouts SET definition = "
                "CAST(replace(CAST(definition AS text), :old, :new) AS jsonb) "
                "WHERE tool = 'library' AND kind = 'library_item' "
                "AND strpos(CAST(definition AS text), :old) > 0"
            ),
            placed,
        ),
    )
    _writable(
        bind,
        "event_outbox",
        lambda: bind.execute(
            text(
                "UPDATE event_outbox SET changed = array_replace(changed, CAST(:old AS text), CAST(:new AS text)) "
                "WHERE resource_type = 'library_items' AND :old = ANY(changed)"
            ),
            names,
        ),
    )
    _writable(
        bind,
        "webhook_subscriptions",
        lambda: bind.execute(
            text(
                "UPDATE webhook_subscriptions SET fields = "
                "array_replace(fields, CAST(:old AS text), CAST(:new AS text)) "
                "WHERE :old = ANY(fields)"
            ),
            names,
        ),
    )
    _writable(
        bind,
        "dashboards",
        lambda: _respell_json(
            bind, "dashboards", ("definition",), _sql_respeller(forward)
        ),
    )


def _guild(forward: bool) -> None:
    bind = op.get_bind()
    _structure(bind, forward)
    _stored_values(bind, forward)


# --- public ------------------------------------------------------------------


def _listings(bind: Connection, forward: bool) -> None:
    old, new = _names(forward)
    statements = _sql_respeller(forward)

    def items(value: Any) -> Any:
        if not isinstance(value, dict) or value.get("type") != "initiative-library":
            return value
        rows = value.get("items")
        if not isinstance(rows, list):
            return value
        return {
            **value,
            "items": [
                {(new if key == old else key): item for key, item in row.items()}
                if isinstance(row, dict)
                else row
                for row in rows
            ],
        }

    def respell(value: Any) -> Any:
        return statements(items(value))

    _respell_json(
        bind,
        "public.marketplace_listing_versions",
        ("definition", "example"),
        respell,
        select_from=(
            "SELECT v.id, v.definition, v.example "
            "FROM public.marketplace_listing_versions v "
            "JOIN public.marketplace_listings l ON l.id = v.listing_id "
            f"WHERE l.kind NOT IN {_NOT_TOOL_LISTINGS!r}"
        ),
    )


def _public(forward: bool) -> None:
    bind = op.get_bind()
    # Both unforced for the whole rewrite: the versions are found by joining
    # their listing, which a forced listings table would hide.
    _writable(
        bind,
        "public.marketplace_listings",
        lambda: _writable(
            bind,
            "public.marketplace_listing_versions",
            lambda: _listings(bind, forward),
        ),
    )


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), lambda: _guild(True))
    _public(True)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), lambda: _guild(False))
    _public(False)
