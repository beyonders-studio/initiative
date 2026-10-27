"""Convert to edit: an uploaded file becomes one the editor keeps.

An uploaded file of a type that converts (``FileTypeSpec.converts_to``) opens
to read, with **Edit** beside it; editing it converts it, as a word processor
converts a file in an older format before it edits one. The file itself
changes type, so its id, name, initiative, tags, sharing, comments and links
stay as they are and nothing pointing at it changes. Its uploaded versions go,
and their stored files are released once that has committed; export gets a
file back out.

A spreadsheet is read by the importer a workbook's own import uses
(:mod:`app.services.tenant.spreadsheet_import`), and Markdown and plain text by
the server's copy of the editor (:func:`app.services.editor_engine.from_markdown`),
so a converted file is the same kind of object as one made in the app.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.body_limit import DOCUMENT_MAX_REQUEST_BYTES
from app.core.file_types import FileType, spec_of
from app.core.messages import FileMessages
from app.models.tenant.file import File, FileVersion
from app.services import editor_engine
from app.services.import_engine.engine import read_payload
from app.services.tenant import attachments, file_versions, spreadsheet_import
from app.services.tenant.files import normalize_file_content

#: The largest uploaded file converted: the largest a single upload of one is.
MAX_CONVERT_BYTES = attachments.MAX_FILE_SIZE


def _refuse(code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=code, detail=detail)


async def convert(
    session: AsyncSession, guild_id: int, file: File
) -> list[FileVersion]:
    """Make ``file`` the type it converts to, from its current version, and
    delete its versions. The caller commits, then releases the returned
    versions' files (:func:`file_versions.release_files`)."""
    # One conversion at a time, read fresh once it holds the lock, so two
    # cannot both read the version the first one deletes.
    await session.exec(
        select(File)
        .where(File.id == file.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    spec = spec_of(file.file_type)
    version = file.current_version
    if spec.converts_to is None or version is None:
        raise _refuse(status.HTTP_400_BAD_REQUEST, FileMessages.NOT_CONVERTIBLE)
    if (version.file_size or 0) > MAX_CONVERT_BYTES:
        raise _refuse(
            status.HTTP_413_CONTENT_TOO_LARGE, FileMessages.TOO_LARGE_TO_CONVERT
        )
    (key,) = attachments.upload_names([version.file_url])
    data = await asyncio.to_thread(read_payload, guild_id, key)
    if data is None:
        raise _refuse(status.HTTP_400_BAD_REQUEST, FileMessages.INVALID_FILE)

    stem = Path(version.original_filename or file.name).stem or file.name
    content = await _content(spec.converts_to, file.file_type, data, stem)
    if len(json.dumps(content)) > DOCUMENT_MAX_REQUEST_BYTES:
        raise _refuse(
            status.HTTP_413_CONTENT_TOO_LARGE, FileMessages.TOO_LARGE_TO_CONVERT
        )

    versions = await file_versions.versions_newest_first(session, file)
    # The file stops pointing at a version before its versions go.
    file.current_version = None
    await session.flush()
    for gone in versions:
        await session.delete(gone)
    file.file_type = spec.converts_to
    file.content = content
    file.yjs_state = None
    file.updated_at = datetime.now(timezone.utc)
    session.add(file)
    return versions


async def _content(
    target: FileType, source: FileType, data: bytes, stem: str
) -> dict[str, Any]:
    """The content a file of ``source`` type holding ``data`` converts to."""
    if target is FileType.sheet:
        # Named with the type's own extension, which is what the importer
        # reads a format from; a text table's one sheet takes the file's name.
        sheets = await asyncio.to_thread(
            spreadsheet_import.parse_spreadsheet_file,
            f"{stem}{spec_of(source).extensions[0]}",
            data,
            strict=True,
        )
        return normalize_file_content(
            {"schema_version": 3, "kind": "spreadsheet", "sheets": sheets},
            file_type=FileType.sheet,
        )
    # Read whole or not at all: the original goes once this converts.
    text = spreadsheet_import.decode_text(data)
    if text is None:
        raise _refuse(status.HTTP_400_BAD_REQUEST, FileMessages.UNREADABLE_TEXT)
    try:
        content = await editor_engine.from_markdown(text, plain=source == FileType.txt)
    except editor_engine.EditorError as exc:
        raise _refuse(status.HTTP_400_BAD_REQUEST, FileMessages.INVALID_FILE) from exc
    return normalize_file_content(content, file_type=FileType.lexical)
