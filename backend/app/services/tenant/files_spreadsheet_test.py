"""Unit tests for the spreadsheet-content normalizer.

The normalizer decides what a saved workbook contains: it builds its output
from an allow-list of known keys, so anything it doesn't name is discarded.
That makes it the place a schema addition is most easily forgotten, and the
failure is quiet — the live collaborative file keeps carrying the new
field, so the feature works for a whole session and is gone on reload.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.services.tenant.files_spreadsheet import normalize_spreadsheet_content

FIXTURE = (
    Path(__file__).parents[4]
    / "frontend"
    / "src"
    / "lib"
    / "spreadsheet"
    / "sheet-schema.fixture.json"
)


def _leaf_paths(value: Any, prefix: str = "") -> set[str]:
    """Every leaf in a value, as a dotted path.

    Map keys that are data rather than schema — cell keys, row and column
    indexes — collapse to ``*``, so ``columns.0.width`` and
    ``columns.7.width`` are one path rather than two.
    """
    if not isinstance(value, dict):
        return {prefix} if prefix else set()
    out: set[str] = set()
    for key, child in value.items():
        segment = "*" if re.fullmatch(r"\d+(:\d+)?", str(key)) else str(key)
        out |= _leaf_paths(child, f"{prefix}.{segment}" if prefix else segment)
    return out


@pytest.mark.always
def test_schema_fixture_survives_normalization() -> None:
    """Every field the shared fixture defines comes back out.

    The fixture is one maximal sheet, shared with the client parser, which
    asserts the same thing in ``frontend/src/lib/spreadsheet/content.test.ts``.
    Add a field to the schema and both sides fail until they carry it.
    """
    if not FIXTURE.exists():  # a backend-only checkout has no frontend tree
        pytest.skip("frontend tree not present")

    sheet = json.loads(FIXTURE.read_text())["sheet"]
    # The fixture sheet is hidden, and a workbook with nothing on show has
    # its first sheet revealed — so it needs a companion to stay hidden and
    # prove the flag survives.
    normalized = normalize_spreadsheet_content(
        {
            "schema_version": 3,
            "kind": "spreadsheet",
            "sheets": [{"id": "visible", "name": "Visible"}, sheet],
        }
    )
    kept = _leaf_paths(normalized["sheets"][1])
    assert sorted(path for path in _leaf_paths(sheet) if path not in kept) == []


def test_hidden_false_is_not_stored() -> None:
    """Only the flag being set means anything: ``true`` stays on its line,
    and ``false`` leaves nothing behind rather than filling every saved
    workbook with noise."""
    normalized = normalize_spreadsheet_content(
        {
            "schema_version": 3,
            "kind": "spreadsheet",
            "sheets": [
                {
                    "id": "s1",
                    "name": "S",
                    "cells": {},
                    "columns": {
                        "0": {"hidden": False},
                        "1": {"hidden": False, "width": 90},
                        "4": {"hidden": True},
                    },
                    "rows": {"9": {"hidden": True, "height": 30}},
                }
            ],
        }
    )
    sheet = normalized["sheets"][0]
    assert sheet["columns"] == {"1": {"width": 90}, "4": {"hidden": True}}
    assert sheet["rows"] == {"9": {"hidden": True, "height": 30}}


def test_a_workbook_keeps_one_sheet_on_show() -> None:
    """Every sheet hidden leaves nothing to render, and xlsx cannot express
    it at all — openpyxl refuses to write such a file. The first sheet is
    shown regardless of what the payload asked for."""
    normalized = normalize_spreadsheet_content(
        {
            "schema_version": 3,
            "kind": "spreadsheet",
            "sheets": [
                {"id": "s1", "name": "One", "hidden": True},
                {"id": "s2", "name": "Two", "hidden": True},
            ],
        }
    )
    states = [sheet.get("hidden") for sheet in normalized["sheets"]]
    assert states == [None, True]
