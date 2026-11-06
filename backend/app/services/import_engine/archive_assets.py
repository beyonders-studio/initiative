"""The files a zip carries under ``assets/``, put into a community's storage.

A backup and an exported tool's zip both carry files named by the storage key
they had where they were exported, and both restore them here, under that key,
so the references in their envelopes resolve without rewriting.

Every file is what the zip claims only once it has been read. Each is held to
the rule for what it is meant to be — a file a file may hold, or any upload —
and stored as the type its bytes turned out to be. One that is not is left out, and the import says so. A key already stored
here is never written over. The community's storage quota is checked against
the zip's own sizes before anything is written, and those sizes bound what is
read, too. A file is copied out of the zip to disk a chunk at a time and
stored from there, so none is held in memory whole, however large.
"""

from __future__ import annotations

import asyncio
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, BinaryIO, Callable, Literal, Sequence

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ImportEngineMessages
from app.models.platform.user import User
from app.services.data_jobs import while_beating
from app.services.import_engine.atlassian import HEARTBEAT_SECONDS
from app.services.import_engine.contract import ImportEngineError
from app.services.import_engine.zip_bounds import copy_member

if TYPE_CHECKING:
    from app.services.storage import StorageBackend

#: What a file is meant to be: a file a file may hold, or any upload — a
#: document image, or else a file.
AssetKind = Literal["file", "upload"]

#: How many keys one lookup of the ``uploads`` table names.
_LOOKUP_BATCH = 1000


@dataclass(frozen=True)
class ArchiveAsset:
    """One file to restore: the storage key it goes under, where it sits in
    the zip, what it is meant to be, and what the zip says about it — the
    name and type the file rule reads as hints."""

    key: str
    member: str
    kind: AssetKind
    original_filename: str | None = None
    content_type: str | None = None


@dataclass
class RestoredAssets:
    """What a restore did."""

    #: Keys written, in order — for the caller to remove if what follows fails.
    written: list[str] = field(default_factory=list)
    #: The type each written key was stored as.
    content_types: dict[str, str] = field(default_factory=dict)
    #: Bytes written.
    restored_bytes: int = 0
    #: Keys already stored here, and so not written.
    deduped: int = 0
    #: Keys named but not in the zip, or not readable from it.
    missing: list[str] = field(default_factory=list)
    #: ``unsupported_file:<key>`` for each file left out because of what it
    #: turned out to be.
    warnings: list[str] = field(default_factory=list)


def _detect(
    asset: ArchiveAsset, source: BinaryIO, size: int
) -> tuple[str | None, str | None]:
    """The type the ``size`` bytes ``source`` reads are stored as, or the
    warning that leaves them out."""
    from app.services.tenant.attachments import (
        MAX_IMAGE_BYTES,
        detect_document_image_type,
        validate_source,
    )

    unsupported = f"unsupported_file:{asset.key}"
    if not size:
        return None, unsupported
    if asset.kind == "upload" and size <= MAX_IMAGE_BYTES:
        # An upload is a document image or an uploaded file, whichever its
        # bytes say; an image takes the same rule it was uploaded under.
        image_type = detect_document_image_type(source.read())
        if image_type is not None:
            return image_type, None
        source.seek(0)
    try:
        return validate_source(source, asset.original_filename), None
    except ValueError:
        return None, unsupported


async def _already_stored(
    guild_id: int, storage: StorageBackend, keys: list[str]
) -> set[str]:
    """The keys this community already holds: an ``uploads`` row, whoever can
    read it, or a stored file."""
    from app.models.tenant.upload import Upload
    from app.services.tenant.attachments import guild_wide

    found: set[str] = set()
    async with guild_wide(guild_id) as session:
        for start in range(0, len(keys), _LOOKUP_BATCH):
            batch = keys[start : start + _LOOKUP_BATCH]
            found.update(
                await session.exec(
                    select(Upload.filename).where(Upload.filename.in_(batch))
                )
            )
    rest = [key for key in keys if key not in found]
    if rest:
        found.update(
            await asyncio.to_thread(
                lambda: {key for key in rest if storage.exists(key)}
            )
        )
    return found


async def restore_assets(
    session: AsyncSession,
    archive: zipfile.ZipFile,
    assets: Sequence[ArchiveAsset],
    *,
    guild_id: int,
    user: User,
    initiative_id: int | None = None,
    heartbeat: Callable[[], Awaitable[None]] | None = None,
) -> RestoredAssets:
    """Put each file into the community's storage under its key and record it
    in ``uploads``, kept for ``initiative_id`` when the files all go there and
    otherwise waiting to be claimed. One entry per key; the caller merges
    duplicates.

    Raises ``IMPORT_QUOTA_EXCEEDED`` when the files would take the community
    past its storage quota, or when they read to more than the zip declared.
    On any failure the files already written are removed. ``heartbeat`` is
    called after each file stored, and while a large one is copied or stored.
    """
    from app.services.storage import get_guild_storage
    from app.services.tenant.attachments import (
        StorageQuotaExceededError,
        enforce_storage_quota,
        store_upload,
    )

    storage = get_guild_storage(guild_id)
    outcome = RestoredAssets()
    stored = await _already_stored(guild_id, storage, [asset.key for asset in assets])

    pending: list[tuple[ArchiveAsset, zipfile.ZipInfo]] = []
    incoming = 0
    for asset in assets:
        if asset.key in stored:
            # A re-import of the same zip reuses the file it already brought.
            outcome.deduped += 1
            continue
        try:
            info = archive.getinfo(asset.member)
        except KeyError:
            outcome.missing.append(asset.key)
            continue
        # The quota is checked against the zip's own sizes, not what its
        # manifest or envelope says a file weighs.
        incoming += info.file_size
        pending.append((asset, info))

    try:
        await enforce_storage_quota(session, guild_id=guild_id, incoming_bytes=incoming)
    except StorageQuotaExceededError as exc:
        raise ImportEngineError(
            ImportEngineMessages.IMPORT_QUOTA_EXCEEDED, status_code=400
        ) from exc

    read_total = 0
    # Each file is copied here before it is checked and stored.
    spool = tempfile.NamedTemporaryFile(prefix="import-asset-")
    try:
        for asset, info in pending:
            spool.seek(0)
            spool.truncate()
            # What the quota was checked against also bounds what is read: a
            # member is read no further than what is left of it.
            size = await while_beating(
                asyncio.to_thread(
                    _copy_out, archive, info, spool, incoming - read_total
                ),
                heartbeat,
                every=HEARTBEAT_SECONDS,
                finish=True,
            )
            if size is None:
                outcome.missing.append(asset.key)
                continue
            read_total += size
            spool.flush()
            spool.seek(0)
            content_type, warning = await asyncio.to_thread(_detect, asset, spool, size)
            if content_type is None:
                if warning is not None:
                    outcome.warnings.append(warning)
                continue
            await while_beating(
                store_upload(
                    session,
                    guild_id=guild_id,
                    filename=asset.key,
                    data=Path(spool.name),
                    content_type=content_type,
                    created_by=user.id,
                    initiative_id=initiative_id,
                ),
                heartbeat,
                every=HEARTBEAT_SECONDS,
                finish=True,
            )
            outcome.written.append(asset.key)
            outcome.content_types[asset.key] = content_type
            outcome.restored_bytes += size
            if heartbeat is not None:
                await heartbeat()
    except BaseException:
        remove_written(guild_id, outcome.written)
        raise
    finally:
        spool.close()
    return outcome


def _copy_out(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, target: BinaryIO, max_bytes: int
) -> int | None:
    """Copy one member to ``target`` and answer its size, or ``None`` when it
    cannot be read. One that reads past ``max_bytes`` raises
    ``IMPORT_QUOTA_EXCEEDED``. Blocking; run it in a thread."""
    try:
        return copy_member(
            archive,
            info,
            target,
            max_bytes=max_bytes,
            code=ImportEngineMessages.IMPORT_QUOTA_EXCEEDED,
        )
    except ImportEngineError:
        raise
    except Exception:
        return None


def remove_written(guild_id: int, keys: list[str]) -> None:
    """Best-effort removal of files an import wrote before it failed."""
    from app.services.storage import get_guild_storage

    storage = get_guild_storage(guild_id)
    for key in keys:
        try:
            storage.delete(key)
        except Exception:  # pragma: no cover - backend-specific failures
            pass
