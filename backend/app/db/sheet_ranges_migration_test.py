"""Migration 20261106_0586 turns stored sheet-range bindings into statements.

Loaded by path, as the other migration tests load theirs, and asked of the
rewrite itself: what each binding becomes, and what the downgrade puts back.
"""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from app.services.query.build import Column, QuerySpec, build
from app.services.query.resolve import SheetCall

_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20261106_0586_sheet_ranges_become_queries.py"
)
_spec = importlib.util.spec_from_file_location(_PATH.stem, _PATH)
assert _spec and _spec.loader
revision = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(revision)

_FILE = SimpleNamespace(
    id=7,
    name="Budget",
    content={
        "sheets": [
            {
                "id": "s1",
                "name": "Q3 Actuals",
                "cells": {"0:0": "Region", "0:1": "Amount", "1:0": "North", "1:1": 5},
            },
            {"id": "s2", "name": "Totals", "cells": {"0:0": "=SUM(1)", "0:1": "x"}},
        ]
    },
)


def test_a_sheet_range_becomes_the_statement_the_builder_writes():
    """Each binding reads the same cells by the names the range gives them —
    the header, or letters where the first row is not one — and is written as
    the builder writes it, so the widget opens on its description. A binding
    with no file is left with no statement, and the downgrade puts every
    untouched one back, the install's half into the config."""
    definition = {
        "widgets": [
            {
                "id": "w1",
                "binding": {"source": "sheet_range", "file_id": 7, "range": "A1:B2"},
                "mapping": {"label": [0], "value": [1]},
            },
            {
                "id": "w2",
                "binding": {"source": "sheet_range", "sheet": "s2", "range": "A1:B2"},
            },
            {"id": "w3", "binding": {"source": "sheet_range", "range": "A1"}},
            {"id": "w4", "binding": {"source": "query", "sql": "SELECT 1"}},
        ]
    }
    config = {"widgets": {"w2": {"file_id": 7}}}
    before = copy.deepcopy((definition, config))

    rewritten, pruned, changed, unbound = revision._rewrite(
        definition, config, {7: _FILE}
    )

    assert (changed, unbound) == (2, ["w3"])
    first, second, third, fourth = rewritten["widgets"]
    assert first["binding"]["sql"] == build(
        QuerySpec(
            sheet=SheetCall(7, "Q3 Actuals!A1:B2"),
            columns=(Column(field="Region"), Column(field="Amount")),
        )
    )
    assert first["binding"]["spec"]["columns"] == [
        {"field": "Region"},
        {"field": "Amount"},
    ]
    assert first["mapping"] == {"label": [0], "value": [1]}
    assert (
        second["binding"]["sql"] == """SELECT "A", "B" FROM sheet(7, 'Totals!A1:B2')"""
    )
    assert "sql" not in third["binding"]
    assert fourth["binding"] == {"source": "query", "sql": "SELECT 1"}
    assert pruned == {"widgets": {}}

    assert revision._restore(rewritten, pruned) == (*before, 3)
