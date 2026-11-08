"""Who exported a file, and when — kept in the file, not printed on it.

Added at the render choke points (inline export + worker replay) beside the
brand, as ``exported`` on every item a renderer turns into a document:
``{"by": <name>, "date": {year, month, day, hour, minute, second}}`` in UTC.
The parts spread straight into Typst's ``datetime(..)``. Each renderer writes it
where its format keeps metadata: PDF document info, DOCX/XLSX core properties,
and a Markdown comment. JSON envelopes carry their own ``exported_at``; CSV,
iCalendar and passthrough files have nowhere to put it.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from app.services.export.contract import RenderRequest

_STAMPED_FORMATS = frozenset({"pdf", "md", "docx", "xlsx"})


def stamp_export(request: RenderRequest, by: str) -> RenderRequest:
    """Return ``request`` with ``exported`` on every item rendered as a document,
    naming ``by`` — the exporter as the community names them
    (``user_display.name_here``)."""
    now = datetime.now(UTC)
    exported: dict[str, Any] = {
        "date": {
            "year": now.year,
            "month": now.month,
            "day": now.day,
            "hour": now.hour,
            "minute": now.minute,
            "second": now.second,
        }
    }
    exported["by"] = by
    batch = tuple(
        replace(item, data={**item.data, "exported": exported})
        if (item.format or request.format) in _STAMPED_FORMATS
        else item
        for item in request.batch
    )
    return replace(request, batch=batch)


def exported_by(data: dict) -> str | None:
    return (data.get("exported") or {}).get("by")


def exported_at(data: dict) -> datetime | None:
    parts = (data.get("exported") or {}).get("date")
    return datetime(**parts, tzinfo=UTC) if parts else None


def markdown_stamp(data: dict) -> list[str]:
    """An HTML comment heading a Markdown file — kept, but not rendered."""
    at = exported_at(data)
    if at is None:
        return []
    note = f"exported: {at.isoformat().replace('+00:00', 'Z')}"
    if by := exported_by(data):
        # A comment may not contain "--", so a name cannot end it early.
        while "--" in by:
            by = by.replace("--", "- -")
        note += f"; by: {by}"
    return [f"<!-- {note} -->", ""]


def stamp_workbook(workbook: Any, data: dict) -> None:
    """Write the stamp into an openpyxl workbook's core properties."""
    if (at := exported_at(data)) is not None:
        workbook.properties.created = workbook.properties.modified = at.replace(
            tzinfo=None
        )
    if by := exported_by(data):
        workbook.properties.creator = workbook.properties.lastModifiedBy = by


def stamp_docx(document: Any, data: dict) -> None:
    """Write the stamp into a python-docx document's core properties."""
    props = document.core_properties
    if (at := exported_at(data)) is not None:
        props.created = props.modified = at.replace(tzinfo=None)
    if by := exported_by(data):
        props.author = props.last_modified_by = by
