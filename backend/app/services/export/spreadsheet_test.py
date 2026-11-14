"""Unit tests for the spreadsheet-file renderers.

Focus: the workbook shape. A snapshot has to reach xlsx as one worksheet
per sheet, and CSV — which cannot express a workbook — has to make its
single-sheet choice explicit and predictable.
"""

import io
from typing import Any

from openpyxl import load_workbook

from app.services.export.spreadsheet import render_csv, render_xlsx, sheets_of


def _sheet(name: str, cells: dict, **extra: Any) -> dict:
    return {
        "id": name.lower(),
        "name": name,
        "dimensions": {"rows": 3, "cols": 2},
        "cells": cells,
        "columns": {},
        "rows": {},
        "cellStyles": {},
        "frozen": {"rows": 0, "cols": 0},
        **extra,
    }


def _workbook(*sheets: dict) -> dict:
    return {"schema_version": 3, "kind": "spreadsheet", "sheets": list(sheets)}


def test_sheets_of_reads_a_v3_workbook():
    content = _workbook(_sheet("One", {}), _sheet("Two", {}))
    assert [s["name"] for s in sheets_of(content)] == ["One", "Two"]


def test_xlsx_renders_one_worksheet_per_sheet():
    content = _workbook(
        _sheet("Summary", {"0:0": "total", "0:1": "=SUM(Data!A1:A2)"}),
        _sheet("Data", {"0:0": 1, "1:0": 2}),
    )
    book = load_workbook(io.BytesIO(render_xlsx(content, title="Doc")))
    assert book.sheetnames == ["Summary", "Data"]
    # The cross-sheet formula travels verbatim; Excel re-evaluates it.
    assert book["Summary"]["B1"].value == "=SUM(Data!A1:A2)"
    assert book["Data"]["A1"].value == 1
    assert book["Data"]["A2"].value == 2


def test_xlsx_titles_a_nameless_sheet_from_the_file_name():
    nameless = _workbook(_sheet("", {"0:0": "x"}))
    book = load_workbook(io.BytesIO(render_xlsx(nameless, title="Q2: Numbers/Plan")))
    # Forbidden characters stripped, capped at Excel's 31.
    assert book.sheetnames == ["Q2 NumbersPlan"]


def test_xlsx_breaks_colliding_worksheet_titles():
    """openpyxl raises on a duplicate title, and a hand-edited payload can
    still carry one even though names are de-duplicated on write."""
    content = _workbook(_sheet("Data", {}), {**_sheet("Data", {}), "id": "other"})
    book = load_workbook(io.BytesIO(render_xlsx(content, title="Doc")))
    assert book.sheetnames == ["Data", "Data 2"]


def test_xlsx_keeps_per_sheet_frozen_panes():
    content = _workbook(
        _sheet("A", {}, frozen={"rows": 1, "cols": 0}),
        _sheet("B", {}, frozen={"rows": 0, "cols": 2}),
    )
    book = load_workbook(io.BytesIO(render_xlsx(content, title="Doc")))
    assert book["A"].freeze_panes == "A2"
    assert book["B"].freeze_panes == "C1"


def test_csv_renders_the_first_sheet_only():
    content = _workbook(
        _sheet("First", {"0:0": "a", "0:1": "b"}),
        _sheet("Second", {"0:0": "should not appear"}),
    )
    text = render_csv(content).decode("utf-8")
    assert "a,b" in text
    assert "should not appear" not in text


def test_all_hidden_workbook_still_renders() -> None:
    """xlsx cannot express a workbook with nothing on show — openpyxl
    refuses to write one — so the renderer shows the first sheet rather
    than failing the export of a snapshot stored before the normalizer
    enforced it."""
    content = {
        "schema_version": 3,
        "kind": "spreadsheet",
        "sheets": [
            _sheet("One", {"0:0": 1}, hidden=True),
            _sheet("Two", {"0:0": 2}, hidden=True),
        ],
    }
    book = load_workbook(io.BytesIO(render_xlsx(content, title="doc")))
    assert [ws.sheet_state for ws in book.worksheets] == ["visible", "hidden"]


def test_a_hidden_sheet_exports_hidden() -> None:
    content = {
        "schema_version": 3,
        "kind": "spreadsheet",
        "sheets": [
            _sheet("Shown", {"0:0": 1}),
            _sheet("Working", {"0:0": 2}, hidden=True),
        ],
    }
    book = load_workbook(io.BytesIO(render_xlsx(content, title="doc")))
    assert [ws.sheet_state for ws in book.worksheets] == ["visible", "hidden"]


def test_hidden_rows_and_columns_export_hidden() -> None:
    content = {
        "schema_version": 3,
        "kind": "spreadsheet",
        "sheets": [
            _sheet(
                "S",
                {"0:0": 1},
                columns={"2": {"hidden": True}},
                rows={"4": {"hidden": True}},
            )
        ],
    }
    book = load_workbook(io.BytesIO(render_xlsx(content, title="doc")))
    sheet = book.worksheets[0]
    assert sheet.column_dimensions["C"].hidden is True
    assert sheet.row_dimensions[5].hidden is True


# ── per-cell formatting, in both shapes a file has had ───────────────────


def _rendered(content: dict):
    return load_workbook(io.BytesIO(render_xlsx(content, title="B"))).active


def test_a_cells_own_look_reaches_the_workbook() -> None:
    """A cell entry keeps its look under ``style``, beside its ``format`` —
    the same wrapper the column and row layers use. Reading the entry as
    though it were the look finds neither."""
    sheet = _rendered(
        {
            "schema_version": 3,
            "kind": "spreadsheet",
            "sheets": [
                _sheet(
                    "S",
                    {"0:0": 1},
                    cellStyles={
                        "0:0": {
                            "style": {"bold": True, "fill": "#ff0000"},
                            "format": {"type": "percent", "decimals": 1},
                        }
                    },
                )
            ],
        }
    )

    cell = sheet.cell(row=1, column=1)
    assert cell.font.bold is True
    assert cell.fill.start_color.rgb == "FFFF0000"
    assert cell.number_format == "0.0%"


def test_a_column_look_still_reaches_the_workbook() -> None:
    """Column and row layers have always used the wrapper; a cell layer that
    does must not cost them theirs."""
    sheet = _rendered(
        {
            "schema_version": 3,
            "kind": "spreadsheet",
            "sheets": [
                _sheet("S", {"0:0": 1}, columns={"0": {"style": {"italic": True}}})
            ],
        }
    )

    assert sheet.cell(row=1, column=1).font.italic is True
