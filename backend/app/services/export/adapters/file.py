"""File source adapter: one source, per-type format rules.

A file's exportable formats depend on its type, so the static registry
declares the union and this adapter enforces the per-type subset at count
time (before a job is created, so a mismatch is an immediate 400):

* ``native`` (Lexical)  -> ``json`` (the generic file envelope with the
  raw editor state as ``content`` — the editor toolbar's import unwraps it,
  so an engine export still round-trips), plus ``md`` (zipped with an
  ``assets/`` folder when images are referenced), ``pdf`` and ``docx`` (both
  embedding referenced same-guild images) via the ``lexical`` converter
  module.
* ``whiteboard``        -> ``json``  — the generic file envelope with
  the scene (as the standard Excalidraw file shape) under ``content``, so a
  backup keeps tags/properties and unwrapping still yields a file any
  Excalidraw opens. Pixel exports (PNG/SVG) are deliberately client-side:
  only Excalidraw's own JS renders scenes faithfully, and the design forbids
  a JS runtime here.
* ``spreadsheet``       -> ``csv`` / ``xlsx`` — the sparse grid, with the
  formatting model mapped for xlsx — and ``json``, the canonical snapshot in
  an importable envelope (the snapshot is already the versioned format the
  write-path normalizer validates, so a future import consumes it directly).
* ``file``              -> ``file`` — the stored upload, unconverted, under
  its original name.
* ``smart_link``        -> ``md``  — the title and URL — and ``json``, the
  generic file envelope (importable backup, like spreadsheets).

Every ``initiative-file`` envelope carries the file's ``tags`` (by
name) and custom ``properties`` (flat, by name — the shared encoding in
``export/property_values.py``), so backups don't shed metadata.

Access: READ suffices (exporting is a formatted read), enforced by the
``ToolExportAdapter.fetch`` seam at both count and build time under the
caller's RLS session.
"""

from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ExportMessages
from app.core.tools import Tool, tool_envelope_type
from app.models.platform.user import User
from app.core.file_types import FileType, export_formats, is_stored
from app.models.tenant.file import File
from app.services.export.adapters._common import (
    BuildContext,
    ToolExportAdapter,
    export_stem,
    storage_key_of,
)
from app.services.export.contract import RenderItem
from app.services.export.engine import ExportError


# The size proxy divisor for file passthroughs: one "row" per MiB, so the
# inline threshold (rows) doubles as an inline size cap in MiB.
_FILE_SIZE_ROW_BYTES = 1_048_576


class FileAdapter(ToolExportAdapter):
    tool = Tool.file
    template_id = "document"  # the Lexical PDF template
    # Ordered, so the union the route publishes reads in one stable order.
    formats = tuple(
        dict.fromkeys(
            fmt for file_type in FileType for fmt in export_formats(file_type)
        )
    )

    async def load(
        self,
        session: AsyncSession,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> list[File]:
        """The selection, as every tool loads it (fetched, authorized and
        narrowed by the filters), held to the per-type format rule: a selection
        is only exportable in a format every file in it supports."""
        files = await super().load(session, user, guild_id, params, format)
        for file in files:
            if format not in export_formats(file_type_of(file)):
                raise ExportError(ExportMessages.EXPORT_INVALID_FORMAT)
        return files

    def rows(self, file: File, /) -> int:
        return _file_count(file)

    def item(self, file: File, ctx: BuildContext, /) -> RenderItem:
        from app.services.export.i18n import export_locale

        return build_file_item(
            file,
            ctx.format,
            guild_id=ctx.guild_id,
            date=ctx.date,
            loc=export_locale(ctx.user),
        )


def _file_count(file: File) -> int:
    file_type = file_type_of(file)
    if file_type == FileType.sheet.value:
        from app.services.export.spreadsheet import sheets_of

        return sum(
            len(sheet.get("cells") or {}) for sheet in sheets_of(file.content or {})
        )
    if is_stored(file_type):
        return int(file.current_version.file_size or 0) // _FILE_SIZE_ROW_BYTES
    return 1


def build_file_item(
    file: File, format: str, *, guild_id: int, date: str, loc: str
) -> RenderItem:
    """One file's render item — a selection export is just a batch of
    these (the engine zips a batch of N into a single download)."""
    from app.services.export.i18n import et

    file_type = file_type_of(file)
    stem = export_stem(file.name, date)

    if file_type == FileType.lexical.value and format != "json":
        from app.services.export.lexical import blocks_from_editor_state

        blocks, assets = blocks_from_editor_state(file.content or {}, guild_id=guild_id)
        data = {
            # Title/footer are the file's own name (user data).
            "title": file.name,
            "footer": file.name,
            "page_of": et("pageOf", loc),
            "stem": stem,
            "blocks": blocks,
            "assets": assets,
        }
        return RenderItem(key=stem, data=data)
    if file_type == FileType.excalidraw.value:
        # Importable backup: the scene wrapped as the standard Excalidraw
        # file shape INSIDE the generic envelope — a future import
        # discriminates by type like every other file type, and
        # unwrapping `content` still yields a file any Excalidraw opens.
        content = file.content or {}
        data = _envelope(
            file,
            content={
                "type": "excalidraw",
                "version": 2,
                "source": "initiative",
                "elements": content.get("elements") or [],
                "appState": content.get("appState") or {},
                "files": content.get("files") or {},
            },
        )
    elif file_type == FileType.lexical.value:
        # Importable backup: the raw editor state inside the generic
        # file envelope. The editor toolbar's import unwraps the
        # envelope, so round-trip through the editor survives.
        data = _envelope(file, content=file.content or {})
    elif file_type == FileType.sheet.value:
        if format == "json":
            # Importable backup: the canonical (already-versioned) snapshot
            # in the generic file envelope, so a future import can
            # discriminate file types uniformly.
            data = _envelope(file, content=file.content or {})
        else:
            data = {"title": file.name, "grid": file.content or {}}
    elif is_stored(file_type):
        version = file.current_version
        storage_key = storage_key_of(version.file_url)
        data = {
            "storage_key": storage_key,
            "filename": version.original_filename or storage_key,
            "content_type": version.file_content_type,
        }
    else:  # url
        if format == "json":
            data = _envelope(
                file,
                content={"url": (file.content or {}).get("url", "")},
            )
        else:
            data = {
                "layout": "link",
                "title": file.name,
                "url": (file.content or {}).get("url", ""),
            }

    return RenderItem(key=stem, data=data)


def _envelope(file: File, *, content: dict) -> dict:
    """The generic ``initiative-file`` envelope: type + schema_version
    discriminate the file for a future import; tags (by name) and custom
    properties (flat, by name) ride along so a backup keeps the file's
    metadata."""
    from app.services.export.property_values import exported_properties

    return {
        "type": tool_envelope_type(Tool.file),
        "schema_version": 1,
        "file_type": file_type_of(file),
        "name": file.name,
        "content": content,
        "tags": sorted(tag.name for tag in file.tags or []),
        "properties": exported_properties(file),
    }


def file_type_of(file: File) -> str:
    """The file's type as its string value."""
    file_type = file.file_type
    return file_type.value if hasattr(file_type, "value") else str(file_type)
