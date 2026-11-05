"""Reading a zip an import was handed: opened within its bounds, and each
member read no further than its cap.

Every zip the import engine reads — a backup, an exported tool's zip, a
Confluence HTML export, a bundle a fetch wrote — is opened by
:func:`open_zip` and its members read by :func:`read_member`,
:func:`read_json_member` or :func:`copy_member`. Opening checks the central
directory: how many members there are, what they declare they add up to, and
that every name is a relative path. Reading decompresses a member a chunk at a
time and stops once it passes its cap, whatever size the member declared.

A backup, a Confluence HTML export, and a bundle the app wrote itself from a
fetch, are held to the bundle bounds rather than another zip's, as
:mod:`limits` explains.
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, BinaryIO

from app.core.messages import ImportEngineMessages
from app.services.import_engine import limits as import_limits
from app.services.import_engine.contract import ImportEngineError

#: How much of a member is decompressed at a time.
_CHUNK_BYTES = 1024 * 1024


def open_zip(
    payload: bytes | Path | BinaryIO, *, bundle: bool = False
) -> zipfile.ZipFile:
    """Open a zip held in memory, read from a file or from an open seekable
    one, and check its central directory, within the ``bundle`` bounds when
    it is one of the zips held to them.
    Raises ``IMPORT_ZIP_INVALID`` or ``IMPORT_TOO_LARGE`` before any member
    is read."""
    max_members = (
        import_limits.IMPORT_MAX_BUNDLE_MEMBERS
        if bundle
        else import_limits.IMPORT_MAX_ZIP_MEMBERS
    )
    max_bytes = (
        import_limits.IMPORT_MAX_BUNDLE_BYTES
        if bundle
        else import_limits.IMPORT_MAX_ZIP_UNCOMPRESSED_BYTES
    )
    try:
        archive = zipfile.ZipFile(
            io.BytesIO(payload) if isinstance(payload, bytes) else payload
        )
    except Exception as exc:
        raise ImportEngineError(ImportEngineMessages.IMPORT_ZIP_INVALID) from exc
    try:
        infos = archive.infolist()
        if len(infos) > max_members:
            raise ImportEngineError(ImportEngineMessages.IMPORT_TOO_LARGE)
        declared = 0
        for info in infos:
            name = info.filename
            # A bare "/" is a directory entry some zip writers add for the
            # root; it names nothing and holds nothing.
            if name == "/" and info.is_dir():
                continue
            if name.startswith("/") or ".." in name.split("/"):
                raise ImportEngineError(ImportEngineMessages.IMPORT_ZIP_INVALID)
            declared += info.file_size
            if declared > max_bytes:
                raise ImportEngineError(ImportEngineMessages.IMPORT_TOO_LARGE)
    except BaseException:
        archive.close()
        raise
    return archive


def json_cap(*, fetched: bool = False) -> int:
    """The most one JSON member — an envelope or a manifest — may hold, more
    in a bundle the app ``fetched`` and wrote itself."""
    return (
        import_limits.IMPORT_FETCH_MAX_ENVELOPE_BYTES
        if fetched
        else import_limits.IMPORT_MAX_ENVELOPE_BYTES
    )


def read_member(
    archive: zipfile.ZipFile,
    member: str | zipfile.ZipInfo,
    *,
    max_bytes: int,
    code: str = ImportEngineMessages.IMPORT_TOO_LARGE,
) -> bytes:
    """One member's bytes, read up to ``max_bytes``.

    A member that declares more than its cap is refused before it is opened,
    and one that decompresses to more is refused as soon as it passes the
    cap: at most ``max_bytes`` plus one chunk is ever held. Raises
    :class:`ImportEngineError` with ``code`` either way, and ``KeyError`` for
    a name the zip does not hold. Blocking; run it in a thread from async
    code.
    """
    return b"".join(_chunks(archive, member, max_bytes=max_bytes, code=code))


def copy_member(
    archive: zipfile.ZipFile,
    member: str | zipfile.ZipInfo,
    target: BinaryIO,
    *,
    max_bytes: int,
    code: str = ImportEngineMessages.IMPORT_TOO_LARGE,
) -> int:
    """Write one member to ``target`` a chunk at a time, read up to
    ``max_bytes`` as :func:`read_member` reads one, and answer how many bytes
    it wrote. Blocking; run it in a thread from async code."""
    written = 0
    for chunk in _chunks(archive, member, max_bytes=max_bytes, code=code):
        target.write(chunk)
        written += len(chunk)
    return written


def _chunks(
    archive: zipfile.ZipFile,
    member: str | zipfile.ZipInfo,
    *,
    max_bytes: int,
    code: str,
) -> Iterator[bytes]:
    info = member if isinstance(member, zipfile.ZipInfo) else archive.getinfo(member)
    if info.file_size > max_bytes:
        raise ImportEngineError(code)
    total = 0
    with archive.open(info) as handle:
        while chunk := handle.read(min(_CHUNK_BYTES, max_bytes + 1 - total)):
            total += len(chunk)
            if total > max_bytes:
                raise ImportEngineError(code)
            yield chunk


def read_json_member(
    archive: zipfile.ZipFile,
    member: str | zipfile.ZipInfo,
    *,
    max_bytes: int,
    invalid: str = ImportEngineMessages.IMPORT_INVALID_ENVELOPE,
) -> Any:
    """One member parsed as JSON, read up to ``max_bytes``.

    Raises ``IMPORT_TOO_LARGE`` for a member past its cap, ``invalid`` for
    one that is not JSON, and ``KeyError`` for a name the zip does not hold.
    Blocking; run it in a thread from async code.
    """
    data = read_member(archive, member, max_bytes=max_bytes)
    try:
        return json.loads(data)
    except (ValueError, RecursionError) as exc:
        raise ImportEngineError(invalid) from exc
