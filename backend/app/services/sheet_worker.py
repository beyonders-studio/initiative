"""Reading a workbook calamine reads, in a worker process, for :mod:`worker_host`.

The host loads this module by path and calls :func:`start` with ``<cells>
<rows> <cols> <scan> <address space bytes>``; this imports the standard library,
python-calamine and defusedxml and nothing of Initiative.

A request is ``{"path"}``: an ``.xls`` or ``.ods`` workbook on disk. The answer
is ``{"sheets": [...]}``, each ``{"name", "hidden", "rows", "cols", "cells"}``
with ``cells`` keyed ``"row:col"`` from zero; ``{"too_large": true}`` for a
workbook past the bounds (more filled cells, rows or columns than
``<cells>``, ``<rows>`` and ``<cols>``, or a filled area of more than
``<scan>`` cells across its sheets); or ``{"error"}`` for one calamine cannot
read. A cell holds the value it shows, a date its ISO text. Calamine reads no
formulas, so an ``.ods`` file's are read from its ``content.xml`` and written
as the grid writes one (:func:`grid_formula`); a cell whose formula can't be
written so, and every ``.xls`` formula, holds its last result. The process's
address space is bounded where the platform allows it; a read that runs out of
memory is answered as too large, with ``"replace": true``, and the worker
exits.
"""

from __future__ import annotations

import re
import zipfile
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Iterator

from defusedxml.ElementTree import iterparse
from python_calamine import CalamineWorkbook, SheetTypeEnum, SheetVisibleEnum


class _TooLarge(Exception):
    pass


def _value(value: Any) -> Any:
    """A cell's value as the grid holds one, or ``None`` for an empty cell."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, (int, float, str)):
        return value
    if isinstance(value, datetime):
        return (
            value.date().isoformat()
            if value.time() == time(0, 0)
            else value.isoformat(sep=" ")
        )
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    return str(value)


# ── OpenFormula ──────────────────────────────────────────────────────────────
# An OpenDocument formula (ISO/IEC 26300-2) names cells in brackets —
# ``[.A1]``, ``[.A1:.B2]``, ``[Sheet2.A1]``, ``['Q1 Actuals'.A1]`` — and
# separates arguments with ``;``. The grid writes ``A1``, ``Sheet2!A1`` and
# ``'Q1 Actuals'!A1``, and separates them with ``,``.

#: One end of a bracketed reference: a sheet (``$`` marks it absolute), a dot,
#: then a cell, a column or a row, each part ``$`` when it stays put.
_END = re.compile(
    r"^\$?(?P<sheet>'(?:[^']|'')*'|[^.']*)\."
    r"(?P<fixed_col>\$?)(?P<col>[A-Za-z]*)(?P<fixed_row>\$?)(?P<row>[0-9]*)$"
)
#: A sheet name the grid writes without quotes; anything else is quoted.
_BARE = re.compile(r"^[A-Za-z_\u007F-￿][A-Za-z0-9_.\u007F-￿]*$")
_LOOKS_LIKE_REFERENCE = re.compile(
    r"^(?:\$?[A-Za-z]{1,3}\$?[1-9][0-9]*|[Rr][0-9]*[Cc][0-9]*|TRUE|FALSE)$",
    re.IGNORECASE,
)
#: Prefixes OpenDocument puts on functions it borrowed from other suites.
_FUNCTION_PREFIXES = re.compile(
    r"\b(?:COM\.MICROSOFT|ORG\.OPENOFFICE|ORG\.LIBREOFFICE)\."
)


def _sheet_prefix(spelled: str) -> str:
    """``Sheet2!`` or ``'Q1 Actuals'!``, from a sheet as OpenFormula spells it."""
    name = (
        spelled[1:-1].replace("''", "'")
        if spelled.startswith("'") and spelled.endswith("'")
        else spelled
    )
    if _BARE.match(name) and not _LOOKS_LIKE_REFERENCE.match(name):
        return f"{name}!"
    return "'{}'!".format(name.replace("'", "''"))


def _ends(inner: str) -> Iterator[str]:
    """The ends of a reference, split at ``:`` outside quoted sheet names."""
    start, quoted = 0, False
    for index, char in enumerate(inner):
        if char == "'":
            quoted = not quoted
        elif char == ":" and not quoted:
            yield inner[start:index]
            start = index + 1
    yield inner[start:]


def _column_number(letters: str) -> int:
    number = 0
    for letter in letters.upper():
        number = number * 26 + ord(letter) - ord("A") + 1
    return number


def _column_letters(number: int) -> str:
    letters = ""
    while number:
        number, rest = divmod(number - 1, 26)
        letters = chr(ord("A") + rest) + letters
    return letters


def _end(match: re.Match[str], down: int, right: int) -> str | None:
    """One end of a reference, moved ``down`` rows and ``right`` columns
    unless it is fixed; ``None`` for one moved off the sheet or naming
    neither a column nor a row."""
    col, row = match["col"], match["row"]
    if not col and not row:
        return None
    if col and not match["fixed_col"]:
        moved = _column_number(col) + right
        if moved < 1:
            return None
        col = _column_letters(moved)
    if row and not match["fixed_row"]:
        moved = int(row) + down
        if moved < 1:
            return None
        row = str(moved)
    return f"{match['fixed_col']}{col.upper()}{match['fixed_row']}{row}"


def _reference(inner: str, down: int, right: int) -> str | None:
    """A bracketed reference as the grid writes it, moved for a repeated
    cell; ``None`` for one it has no way to write: another file's, an error,
    a range across sheets."""
    sheets, cells = [], []
    for end in _ends(inner):
        match = _END.match(end)
        cell = _end(match, down, right) if match is not None else None
        if match is None or cell is None:
            return None
        sheets.append(match["sheet"])
        cells.append(cell)
    if len(cells) > 2 or any(sheet and sheet != sheets[0] for sheet in sheets[1:]):
        return None
    prefix = _sheet_prefix(sheets[0]) if sheets[0] else ""
    return prefix + ":".join(cells)


def grid_formula(formula: str, down: int = 0, right: int = 0) -> str | None:
    """An OpenDocument cell's ``table:formula`` as the grid writes one, or
    ``None`` for one it can't. A cell repeated ``down`` rows and ``right``
    columns from the one that spells it moves its references as a filled cell
    does: all but the parts marked ``$``."""
    namespace, _, body = formula.partition(":")
    if namespace == "msoxl" and body.startswith("="):
        return body
    if namespace not in ("of", "oooc") or not body.startswith("="):
        return None
    out: list[str] = []
    # What lies outside strings and references, where function names are.
    plain: list[str] = []

    def flush() -> None:
        out.append(_FUNCTION_PREFIXES.sub("", "".join(plain)))
        plain.clear()

    index = 0
    while index < len(body):
        char = body[index]
        if char == '"':
            flush()
            # A string, copied as it is, ``""`` and all.
            end = index + 1
            while end < len(body) and not (
                body[end] == '"' and body[end + 1 : end + 2] != '"'
            ):
                end += 2 if body[end] == '"' else 1
            out.append(body[index : end + 1])
            index = end + 1
        elif char == "[":
            flush()
            end = body.find("]", index)
            reference = (
                _reference(body[index + 1 : end], down, right) if end > 0 else None
            )
            if reference is None:
                return None
            out.append(reference)
            index = end + 1
        else:
            plain.append("," if char == ";" else char)
            index += 1
    flush()
    return "".join(out)


_TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
_ROW = f"{_TABLE}table-row"
_CELLS = (f"{_TABLE}table-cell", f"{_TABLE}covered-table-cell")


def _ods_formulas(
    path: str, cells: int, rows: int, cols: int
) -> dict[str, dict[str, str]]:
    """Each sheet's formulas by ``"row:col"``, as the grid writes them, read
    from the workbook's ``content.xml``; within ``rows`` and ``cols``, and no
    more than ``cells`` of them. A repeated row or cell spells its formula
    once, for the first; each repeat has it moved to where it sits."""
    found: dict[str, dict[str, str]] = {}
    sheet: dict[str, str] | None = None
    row = col = 0
    # The current row's formulas: where each starts, how often it repeats.
    spelled: list[tuple[int, int, str]] = []
    with zipfile.ZipFile(path) as package, package.open("content.xml") as content:
        for event, element in iterparse(content, events=("start", "end")):
            tag = element.tag
            if event == "start":
                if tag == f"{_TABLE}table":
                    sheet = found.setdefault(element.get(f"{_TABLE}name", ""), {})
                    row = 0
                elif tag == _ROW:
                    col, spelled = 0, []
                continue
            if tag in _CELLS:
                repeat = int(element.get(f"{_TABLE}number-columns-repeated", "1"))
                formula = element.get(f"{_TABLE}formula")
                if formula and col < cols:
                    spelled.append((col, repeat, formula))
                col += repeat
                element.clear()
            elif tag == _ROW:
                repeat = int(element.get(f"{_TABLE}number-rows-repeated", "1"))
                for down in range(min(repeat, max(rows - row, 0))):
                    for start, across, formula in spelled:
                        for right in range(min(across, cols - start)):
                            written = grid_formula(formula, down, right)
                            if written is None or sheet is None:
                                continue
                            sheet[f"{row + down}:{start + right}"] = written
                            cells -= 1
                            if cells < 0:
                                raise _TooLarge
                row += repeat
                element.clear()
    return found


# ── the workbook ─────────────────────────────────────────────────────────────


def answer(
    request: dict[str, Any], cells: int, rows: int, cols: int, scan: int
) -> dict[str, Any]:
    """The sheets a workbook holds, or why it can't be read."""
    try:
        formulas = (
            _ods_formulas(request["path"], cells, rows, cols)
            if request["path"].lower().endswith(".ods")
            else {}
        )
        workbook = CalamineWorkbook.from_path(request["path"])
        try:
            budget = cells
            sheets = []
            for meta in workbook.sheets_metadata:
                # Charts, dialogs and macros hold no grid.
                if meta.typ != SheetTypeEnum.WorkSheet:
                    continue
                sheet = workbook.get_sheet_by_name(meta.name)
                # The last filled cell, so the grid reaches it.
                bottom, right = sheet.end or (-1, -1)
                if bottom + 1 > rows or right + 1 > cols:
                    raise _TooLarge
                scan -= sheet.height * sheet.width
                if scan < 0:
                    raise _TooLarge
                # The filled area, from its first filled cell.
                top, left = sheet.start or (0, 0)
                found: dict[str, Any] = {}
                for r, row in enumerate(sheet.to_python(), start=top):
                    for c, raw in enumerate(row, start=left):
                        value = _value(raw)
                        if value is not None:
                            found[f"{r}:{c}"] = value
                # A formula takes the place of the value it showed, and one
                # with no value saved still widens the grid to reach it.
                for key, formula in formulas.get(meta.name, {}).items():
                    found[key] = formula
                    r, c = (int(part) for part in key.split(":"))
                    bottom, right = max(bottom, r), max(right, c)
                budget -= len(found)
                if budget < 0:
                    raise _TooLarge
                sheets.append(
                    {
                        "name": meta.name,
                        "hidden": meta.visible != SheetVisibleEnum.Visible,
                        "rows": bottom + 1,
                        "cols": right + 1,
                        "cells": found,
                    }
                )
        finally:
            workbook.close()
    except _TooLarge:
        return {"too_large": True}
    except MemoryError:
        return {"too_large": True, "replace": True}
    except Exception as error:  # noqa: BLE001 - every read failure is one answer
        return {"error": str(error) or type(error).__name__}
    return {"sheets": sheets}


def start(arguments: list[str]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Set the process's bounds, and answer requests within them."""
    cells, rows, cols, scan, address_space = (int(value) for value in arguments)
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (address_space, address_space))
    except (ImportError, ValueError, OSError):
        pass
    return lambda request: answer(request, cells, rows, cols, scan)
