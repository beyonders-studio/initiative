"""Reading a workbook calamine reads, in a worker process, for :mod:`worker_host`.

The host loads this module by path and calls :func:`start` with ``<cells>
<rows> <cols> <scan> <address space bytes>``; this imports the standard library and
python-calamine and nothing of Initiative.

A request is ``{"path"}``: an ``.xls`` or ``.ods`` workbook on disk. The answer
is ``{"sheets": [...]}``, each ``{"name", "hidden", "rows", "cols", "cells"}``
with ``cells`` keyed ``"row:col"`` from zero; ``{"too_large": true}`` for a
workbook past the bounds (more filled cells, rows or columns than
``<cells>``, ``<rows>`` and ``<cols>``, or a filled area of more than
``<scan>`` cells across its sheets); or ``{"error"}`` for one calamine cannot read. A cell
holds the value it shows: calamine reads no formulas, so a formula's cell
holds its last result, and a date its ISO text. The process's address space is
bounded where the platform allows it; a read that runs out of memory is
answered as too large, with ``"replace": true``, and the worker exits.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Callable

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


def answer(
    request: dict[str, Any], cells: int, rows: int, cols: int, scan: int
) -> dict[str, Any]:
    """The sheets a workbook holds, or why it can't be read."""
    try:
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
                        if value is None:
                            continue
                        budget -= 1
                        if budget < 0:
                            raise _TooLarge
                        found[f"{r}:{c}"] = value
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
