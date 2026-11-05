"""Tabular renderers (CSV/XLSX) for the export engine.

Same source adapters, different renderer: a tabular format consumes the
``columns``/``rows`` of the same data payload the PDF template reads, so a
source that declares the format gets it with no adapter changes.

Both formats reuse the platform CSV exporter's formula neutralization rather
than duplicating it (``csv_export.neutralize_cell``) — XLSX included, because
openpyxl infers a *string* cell starting with ``=`` as a formula. XLSX
neutralizes string cells only, keeping numeric cells typed (see
``_xlsx_cell``).
"""

from __future__ import annotations

import io
from typing import Any

from openpyxl import Workbook

from app.services.export.contract import RenderItem
from app.services.export.stamp import markdown_stamp, stamp_workbook
from app.services.platform.csv_export import build_csv, neutralize_cell

# Sheet titles have a 31-char limit and a forbidden character set in the XLSX
# spec (openpyxl raises InvalidSheetTitle). The payload title can carry user
# text (a guild or project name), so sanitize rather than trust it.
_SHEET_TITLE_MAX = 31
_SHEET_TITLE_FORBIDDEN = str.maketrans("", "", "[]:*?/\\")


def _sheet_title(item: RenderItem) -> str:
    raw = str(item.data.get("title", item.key)).translate(_SHEET_TITLE_FORBIDDEN)
    fallback = item.key.translate(_SHEET_TITLE_FORBIDDEN)[:_SHEET_TITLE_MAX]
    return raw.strip()[:_SHEET_TITLE_MAX] or fallback or "Export"


def _table(item: RenderItem) -> tuple[list[str], list[list[Any]]]:
    """Project the payload's ``columns``/``rows`` into header + cell lists."""
    columns = item.data.get("columns") or []
    keys = [c["key"] for c in columns]
    headers = [c.get("label", c["key"]) for c in columns]
    rows = [[row.get(key, "") for key in keys] for row in item.data.get("rows") or []]
    return headers, rows


def render_csv(item: RenderItem) -> bytes:
    headers, rows = _table(item)
    return build_csv(headers, rows)


def _md_cell(value: Any) -> str:
    """A cell must not break the GFM table structure: escape pipes and
    collapse newlines, keeping the table layout intact."""
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\r\n", " ").replace("\n", " ")


def render_md(item: RenderItem) -> bytes:
    lines = _md_header(item)
    layout = item.data.get("layout")
    if layout == "link":
        # Smart-link files: the file IS a URL. The autolink form
        # (<url>) needs no bracket/paren escaping and renders clickable
        # everywhere.
        lines.append(f"<{item.data.get('url', '')}>")
    elif layout == "checklist":
        lines.extend(_md_checklist(item))
    else:
        lines.extend(_md_table(item))
    lines.append("")
    return "\n".join(lines).encode("utf-8")


def _md_header(item: RenderItem) -> list[str]:
    lines = markdown_stamp(item.data)
    title = str(item.data.get("title", "")).strip()
    subtitle = str(item.data.get("subtitle", "")).strip()
    if title:
        lines.append(f"# {_md_cell(title)}")
        lines.append("")
    if subtitle:
        lines.append(_md_cell(subtitle))
        lines.append("")
    return lines


def _md_table(item: RenderItem) -> list[str]:
    headers, rows = _table(item)
    lines = ["| " + " | ".join(_md_cell(h) for h in headers) + " |"]
    lines.append("|" + "|".join(" --- " for _ in headers) + "|")
    for row in rows:
        lines.append("| " + " | ".join(_md_cell(value) for value in row) + " |")
    return lines


def _md_details(row: dict, detail_keys: list[str]) -> str:
    """The parenthesized detail trail after a checklist row's title. ``None``
    must be skipped BEFORE stringifying — ``str(None)`` is truthy, and
    ``_md_cell(None)`` returns ``""``, so a None value would otherwise add
    an empty segment (and its spurious ``·`` separator) to the join."""
    values = (row.get(key) for key in detail_keys)
    return " · ".join(
        _md_cell(value) for value in values if value is not None and str(value).strip()
    )


def _untitled(item: RenderItem) -> str:
    """The empty-title fallback, localized by the adapter via the payload
    (``fallback.untitled``); the ASCII default is a last resort."""
    return item.data.get("untitled") or "(untitled)"


def _md_checklist(item: RenderItem) -> list[str]:
    """GitHub-style task list: one checkbox item per row, checked when the
    row's ``done`` flag is set, with the non-title columns as a detail trail."""
    columns = item.data.get("columns") or []
    detail_keys = [c["key"] for c in columns if c["key"] != "title"]
    untitled = _untitled(item)
    lines: list[str] = []
    for row in item.data.get("rows") or []:
        box = "x" if row.get("done") else " "
        title = _md_cell(row.get("title", "")) or untitled
        details = _md_details(row, detail_keys)
        lines.append(f"- [{box}] {title}" + (f" ({details})" if details else ""))
    return lines


def _xlsx_cell(value: Any) -> Any:
    """Neutralize only STRING cells for XLSX. Unlike CSV (where every value
    becomes text anyway), XLSX cells are typed: a number must stay a number
    (coercing ``-5`` to ``"'-5"`` would break sorting/arithmetic in the
    sheet), and openpyxl cannot infer a formula from an int/float/date, so
    only strings can carry a formula trigger."""
    if isinstance(value, str):
        return neutralize_cell(value)
    return value


def render_xlsx(item: RenderItem) -> bytes:
    headers, rows = _table(item)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = _sheet_title(item)
    sheet.append([_xlsx_cell(value) for value in headers])
    for row in rows:
        sheet.append([_xlsx_cell(value) for value in row])
    sheet.freeze_panes = "A2"
    stamp_workbook(workbook, item.data)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
