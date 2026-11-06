"""rewrite every stored sheet-range binding as a statement

A widget could read a spreadsheet through its own source, ``sheet_range``: a
file id, a sheet and a range. A statement now reads a spreadsheet itself, with
``sheet(file, range)`` in ``FROM``, so each such binding becomes the statement
that reads the same cells: every column of the range, by the name the range
gives it. Column order is kept, so a widget's mapping, which holds column
positions, still fills the same slots.

A column is named by the range's header row, or by its sheet letter when the
range has none. The header is the first row when the range has more than one
row and every cell in it is text. This reads the stored cells and evaluates no
formula, so a header cell that holds one names its columns by letter; the
statement then names columns the range does not have, and is refused until
they are picked again.

The binding and its builder description are both written, so the widget opens
on what it reads. A binding that names no file, or a file, sheet or range that
is not there, leaves its widget with no statement, which draws the panel asking
for one, and is named in the log.

What each widget was rides along under ``legacy`` (as in ``20260909_0241``),
which is what lets the downgrade put it back. Dashboards and files force
row-level security on their owner, which this runs as, so the force is lifted
while the rows are read and written and restored whatever happens; the
dashboards' own triggers are held too, so an archived or trashed dashboard is
rewritten like any other.

A description holds at most 20 columns, so a range wider than that keeps its
statement and opens on SQL.

Revision ID: 20261106_0586
Revises: 20261106_0585
Create Date: 2026-11-06
"""

import hashlib
import json
import logging
import re

from alembic import op
import sqlalchemy as sa
from pglast import parse_sql
from pglast.stream import RawStream

revision = "20261106_0586"
down_revision = "20261106_0585"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

#: The most columns a builder description holds.
_DESCRIBED_COLUMNS = 20

#: The range a ``sheet_range`` binding took: one cell, or two corners.
_RANGE = re.compile(r"^\s*\$?([A-Za-z]+)\$?(\d+)(?:\s*:\s*\$?([A-Za-z]+)\$?(\d+))?\s*$")


def _fingerprint(statement: str | None) -> str:
    """A short stand-in for the statement this revision wrote, so the downgrade
    can tell a widget nobody has touched from one somebody rebuilt."""
    return hashlib.sha256((statement or "").encode()).hexdigest()[:16]


def _column(letters: str) -> int:
    number = 0
    for letter in letters.upper():
        number = number * 26 + ord(letter) - ord("A") + 1
    return number - 1


def _letters(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(ord("A") + rest) + letters
    return letters


def _quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _reading(binding: dict, file) -> tuple[str, dict | None] | None:
    """The statement and builder description that read what *binding* read
    from *file* (its ``name`` and ``content``), or ``None``."""
    content = file.content if isinstance(file.content, dict) else {}
    sheets = content.get("sheets")
    if not isinstance(sheets, list):
        sheets = [{"name": "Sheet1", "id": "s1", "cells": content.get("cells")}]
    wanted = binding.get("sheet")
    sheet = next(
        (
            entry
            for entry in sheets
            if isinstance(entry, dict)
            and (not wanted or wanted in (entry.get("name"), entry.get("id")))
        ),
        None,
    )
    corners = _RANGE.match(str(binding.get("range") or ""))
    if sheet is None or corners is None:
        return None
    cells = sheet.get("cells") if isinstance(sheet.get("cells"), dict) else {}
    c1, c2 = sorted((_column(corners[1]), _column(corners[3] or corners[1])))
    r1, r2 = sorted((int(corners[2]) - 1, int(corners[4] or corners[2]) - 1))
    first = [cells.get(f"{r1}:{col}") for col in range(c1, c2 + 1)]
    header = r2 > r1 and all(
        isinstance(value, str) and value.strip() and not value.startswith("=")
        for value in first
    )
    names = [
        value.strip() if header else _letters(col)
        for col, value in zip(range(c1, c2 + 1), first)
    ]
    range_ = f"{sheet.get('name') or 'Sheet1'}!{binding['range'].strip()}"
    literal = "'" + range_.replace("'", "''") + "'"
    statement = RawStream()(
        parse_sql(
            f"SELECT {', '.join(_quoted(name) for name in names)} "
            f"FROM sheet({int(binding['file_id'])}, {literal})"
        )[0].stmt
    )
    spec = {
        "sheet": {"file": int(binding["file_id"]), "range": range_},
        "columns": [{"field": name} for name in names],
        "where": [],
        "group_by": [],
    }
    return statement, spec if len(names) <= _DESCRIBED_COLUMNS else None


def _rewrite(
    definition: dict, config: dict, files: dict
) -> tuple[dict, dict, int, list[str]]:
    """The definition with every sheet-range binding turned into a statement,
    and the config without the entries those bindings spent."""
    changed = 0
    unbound: list[str] = []
    widgets = config.get("widgets")
    per_widget = dict(widgets) if isinstance(widgets, dict) else {}

    for widget in definition.get("widgets") or []:
        binding = widget.get("binding")
        if not isinstance(binding, dict):
            continue
        widget_id = widget.get("id")
        overrides = per_widget.get(widget_id)
        effective = (
            {**binding, **overrides} if isinstance(overrides, dict) else dict(binding)
        )
        if effective.get("source") != "sheet_range":
            continue
        legacy: dict = {"binding": binding}
        if isinstance(overrides, dict) and overrides:
            legacy["config"] = overrides
        rewritten: dict = {"source": "query", "legacy": legacy}
        file_id = effective.get("file_id")
        file = files.get(file_id) if isinstance(file_id, int) else None
        reading = _reading(effective, file) if file is not None else None
        if reading is None:
            unbound.append(str(widget_id))
        else:
            rewritten["sql"], spec = reading
            if spec is not None:
                rewritten["spec"] = spec
            legacy["sql"] = _fingerprint(rewritten["sql"])
            changed += 1
        widget["binding"] = rewritten
        per_widget.pop(widget_id, None)

    return definition, {**config, "widgets": per_widget}, changed, unbound


def _schemas(connection) -> list[str]:
    return [
        row[0]
        for row in connection.execute(
            sa.text(
                "SELECT nspname FROM pg_namespace WHERE nspname LIKE 'guild\\_%' "
                "AND nspname !~ '_(template|ro|q)$' ORDER BY nspname"
            )
        )
    ]


def upgrade() -> None:
    connection = op.get_bind()
    schemas = _schemas(connection)
    widgets = 0
    left = 0
    for schema in schemas:
        connection.execute(sa.text(f'SET LOCAL search_path = "{schema}", public'))
        for table in ("dashboards", "files"):
            connection.execute(
                sa.text(f'ALTER TABLE "{schema}".{table} NO FORCE ROW LEVEL SECURITY')
            )
        connection.execute(
            sa.text(f'ALTER TABLE "{schema}".dashboards DISABLE TRIGGER USER')
        )
        try:
            stored = connection.execute(
                sa.text(f'SELECT id, definition, config FROM "{schema}".dashboards')  # noqa: S608
            ).fetchall()
            wanted = {
                widget["binding"].get("file_id")
                for _, definition, config in stored
                if isinstance(definition, dict)
                for widget in definition.get("widgets") or []
                if isinstance(widget, dict) and isinstance(widget.get("binding"), dict)
            } | {
                entry.get("file_id")
                for _, _, config in stored
                if isinstance(config, dict) and isinstance(config.get("widgets"), dict)
                for entry in config["widgets"].values()
                if isinstance(entry, dict)
            }
            ids = [value for value in wanted if isinstance(value, int)]
            files = (
                {
                    row.id: row
                    for row in connection.execute(
                        sa.text(
                            f'SELECT id, name, content FROM "{schema}".files '  # noqa: S608
                            "WHERE id = ANY(:ids) AND file_type = 'sheet'"
                        ),
                        {"ids": ids},
                    )
                }
                if ids
                else {}
            )
            for dashboard_id, definition, config in stored:
                if not isinstance(definition, dict):
                    continue
                rewritten, pruned, changed, unbound = _rewrite(
                    definition, config if isinstance(config, dict) else {}, files
                )
                for widget_id in unbound:
                    left += 1
                    logger.warning(
                        "dashboard widget left unconfigured: %s.dashboards id=%s "
                        "widget=%s — its spreadsheet, sheet or range is not there",
                        schema,
                        dashboard_id,
                        widget_id,
                    )
                if not changed and not unbound:
                    continue
                connection.execute(
                    sa.text(
                        f'UPDATE "{schema}".dashboards '  # noqa: S608
                        "SET definition = CAST(:body AS jsonb), "
                        "config = CAST(:config AS jsonb) WHERE id = :id"
                    ),
                    {
                        "body": json.dumps(rewritten),
                        "config": json.dumps(pruned),
                        "id": dashboard_id,
                    },
                )
                widgets += changed
        finally:
            connection.execute(
                sa.text(f'ALTER TABLE "{schema}".dashboards ENABLE TRIGGER USER')
            )
            for table in ("dashboards", "files"):
                connection.execute(
                    sa.text(f'ALTER TABLE "{schema}".{table} FORCE ROW LEVEL SECURITY')
                )
    connection.execute(sa.text("SET LOCAL search_path = public"))
    logger.info(
        "sheet-range bindings rewritten: %s widget(s) in %s schema(s); "
        "%s left unconfigured",
        widgets,
        len(schemas),
        left,
    )


def _restore(definition: dict, config: dict) -> tuple[dict, dict, int]:
    """Every widget this revision rewrote and nobody has touched since, put
    back as it was."""
    restored = 0
    widgets = config.get("widgets")
    per_widget = dict(widgets) if isinstance(widgets, dict) else {}
    for widget in definition.get("widgets") or []:
        binding = widget.get("binding")
        if not isinstance(binding, dict):
            continue
        legacy = binding.get("legacy")
        if (
            not isinstance(legacy, dict)
            or not isinstance(legacy.get("binding"), dict)
            or legacy["binding"].get("source") != "sheet_range"
            or legacy.get("sql", _fingerprint(None)) != _fingerprint(binding.get("sql"))
        ):
            continue
        widget["binding"] = legacy["binding"]
        if isinstance(legacy.get("config"), dict):
            per_widget[str(widget.get("id"))] = legacy["config"]
        restored += 1
    return definition, {**config, "widgets": per_widget}, restored


def downgrade() -> None:
    """Put back each sheet-range binding this revision rewrote, unless somebody
    has rebuilt the widget since."""
    connection = op.get_bind()
    for schema in _schemas(connection):
        connection.execute(sa.text(f'SET LOCAL search_path = "{schema}", public'))
        connection.execute(
            sa.text(f'ALTER TABLE "{schema}".dashboards NO FORCE ROW LEVEL SECURITY')
        )
        connection.execute(
            sa.text(f'ALTER TABLE "{schema}".dashboards DISABLE TRIGGER USER')
        )
        try:
            stored = connection.execute(
                sa.text(f'SELECT id, definition, config FROM "{schema}".dashboards')  # noqa: S608
            ).fetchall()
            for dashboard_id, definition, config in stored:
                if not isinstance(definition, dict):
                    continue
                restored, put_back, count = _restore(
                    definition, config if isinstance(config, dict) else {}
                )
                if not count:
                    continue
                connection.execute(
                    sa.text(
                        f'UPDATE "{schema}".dashboards '  # noqa: S608
                        "SET definition = CAST(:body AS jsonb), "
                        "config = CAST(:config AS jsonb) WHERE id = :id"
                    ),
                    {
                        "body": json.dumps(restored),
                        "config": json.dumps(put_back),
                        "id": dashboard_id,
                    },
                )
        finally:
            connection.execute(
                sa.text(f'ALTER TABLE "{schema}".dashboards ENABLE TRIGGER USER')
            )
            connection.execute(
                sa.text(f'ALTER TABLE "{schema}".dashboards FORCE ROW LEVEL SECURITY')
            )
    connection.execute(sa.text("SET LOCAL search_path = public"))
