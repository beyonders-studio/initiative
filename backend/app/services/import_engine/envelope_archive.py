"""An export that travels as a zip: its envelope, and the files it names.

A catalog is its pictures, so a catalog exported on its own downloads as a zip
holding its envelope at the top level and each picture under ``assets/``, named
by the storage key the envelope gives it — the layout a backup uses. Importing
that zip puts the pictures in the community's storage under those keys and then
imports the envelope exactly as a lone JSON file is imported, so every rule the
envelope path has (authorization, the people step, inline or queued) holds.

A wiki's zip carries the uploads filed in it the same way. A zip holding any
other tool's envelope imports too: it simply carries nothing beside it.

Every file is what the zip claims only once it has been read: a picture must
be one a catalog can show, and an upload a file an uploaded file may hold. One that
is not is left out and the import says so. A key already stored here is never
written over — a re-import of the same zip reuses the file it already brought
— and the community's storage quota is checked against the zip's own sizes
before anything is written.
"""

from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ImportEngineMessages
from app.models.platform.user import User
from app.services.import_engine import engine as import_engine
from app.services.import_engine.archive_assets import (
    ArchiveAsset,
    AssetKind,
    remove_written,
    restore_assets,
)
from app.services.import_engine.contract import ImportEngineError, InlineImport
from app.services.import_engine.zip_bounds import json_cap, open_zip, read_json_member

#: Where the files an envelope names sit in its zip.
ASSET_DIR = "assets/"


def read_envelope_archive(
    payload: bytes | Path,
) -> tuple[zipfile.ZipFile, dict[str, Any]]:
    """The zip, bound-checked, and the one envelope at its top level. The
    caller closes the zip. Blocking; run it in a thread from async code."""
    archive = open_zip(payload)
    try:
        candidates = [
            info
            for info in archive.infolist()
            if not info.is_dir() and "/" not in info.filename
        ]
        envelopes = [info for info in candidates if info.filename.endswith(".json")]
        if len(envelopes) != 1:
            raise ImportEngineError(ImportEngineMessages.IMPORT_ARCHIVE_NO_ENVELOPE)
        [info] = envelopes
        try:
            envelope = read_json_member(archive, info, max_bytes=json_cap())
        except ImportEngineError:
            raise
        except Exception as exc:
            raise ImportEngineError(
                ImportEngineMessages.IMPORT_INVALID_ENVELOPE
            ) from exc
        if not isinstance(envelope, dict) or not isinstance(envelope.get("type"), str):
            raise ImportEngineError(ImportEngineMessages.IMPORT_INVALID_ENVELOPE)
    except BaseException:
        archive.close()
        raise
    return archive, envelope


def _flat_key(key: Any) -> str | None:
    """A storage key the way every stored file is named: one flat filename."""
    if not isinstance(key, str):
        return None
    key = key.strip()
    if not key or "/" in key or "\\" in key or key in (".", ".."):
        return None
    return key


async def restore_archive_assets(
    session: AsyncSession,
    archive: zipfile.ZipFile,
    assets: list[tuple[dict[str, Any], str]],
    *,
    guild_id: int,
    user: User,
    initiative_id: int,
) -> tuple[list[str], list[str]]:
    """Put each named file the zip carries into the community's storage, kept
    for the initiative the envelope is imported into.

    ``assets`` are the envelope's own records of its files, each with what it
    should be — ``"picture"`` or ``"file"``; each record's ``content_type`` is
    set to what the file turned out to be, since that is what the importer
    stores. Returns the keys written — for the caller to remove if the import
    then fails — and the warnings to report. A file the envelope lists but the
    zip does not carry is left to the importer, which counts it as missing
    unless it is already stored here.
    """
    by_key: dict[str, list[dict[str, Any]]] = {}
    kinds: dict[str, AssetKind] = {}
    for record, kind in assets:
        key = _flat_key(record.get("storage_key"))
        if key is None:
            continue
        by_key.setdefault(key, []).append(record)
        # A key named as a picture anywhere is held to the picture rule.
        if kinds.get(key) != "picture":
            kinds[key] = "picture" if kind == "picture" else "file"

    restored = await restore_assets(
        session,
        archive,
        [
            ArchiveAsset(
                key=key,
                member=f"{ASSET_DIR}{key}",
                kind=kinds[key],
                original_filename=records[0].get("original_filename"),
                content_type=records[0].get("content_type"),
            )
            for key, records in by_key.items()
        ],
        guild_id=guild_id,
        user=user,
        initiative_id=initiative_id,
    )
    for key, content_type in restored.content_types.items():
        for record in by_key[key]:
            record["content_type"] = content_type
    return restored.written, restored.warnings


async def start_envelope_archive_import(
    session: AsyncSession,
    *,
    user: User,
    guild_id: int,
    initiative_id: int,
    payload: bytes | Path,
    expected_type: str | None = None,
):
    """Import an exported zip into an initiative: authorize, put its files in
    storage, then import its envelope the way a lone file is imported.

    ``expected_type`` is the envelope type of the tool the import was started
    from; a zip holding another tool's export is refused rather than landing
    somewhere nobody looked for it.
    """
    archive, envelope = await asyncio.to_thread(read_envelope_archive, payload)
    with archive:
        return await _import_archive(
            session,
            archive,
            envelope,
            user=user,
            guild_id=guild_id,
            initiative_id=initiative_id,
            expected_type=expected_type,
        )


async def _import_archive(
    session: AsyncSession,
    archive: zipfile.ZipFile,
    envelope: dict[str, Any],
    *,
    user: User,
    guild_id: int,
    initiative_id: int,
    expected_type: str | None,
):
    if expected_type is not None and envelope["type"] != expected_type:
        raise ImportEngineError(ImportEngineMessages.IMPORT_WRONG_TOOL)
    importer = import_engine.get_importer(envelope["type"])
    importer.validate(envelope)
    # Authorized before anything is written: the same gate the import itself
    # runs again below.
    await import_engine.load_target_initiative(
        session,
        guild_id=guild_id,
        initiative_id=initiative_id,
        importer=importer,
        user=user,
    )
    assets_of = getattr(importer, "archive_assets", None)
    written: list[str] = []
    warnings: list[str] = []
    if assets_of is not None:
        written, warnings = await restore_archive_assets(
            session,
            archive,
            assets_of(envelope),
            guild_id=guild_id,
            user=user,
            initiative_id=initiative_id,
        )
    try:
        outcome = await import_engine.start_envelope_import(
            session,
            user=user,
            guild_id=guild_id,
            initiative_id=initiative_id,
            envelope=envelope,
        )
    except BaseException:
        remove_written(guild_id, written)
        raise
    if isinstance(outcome, InlineImport):
        outcome.result.warnings.extend(warnings)
    return outcome
