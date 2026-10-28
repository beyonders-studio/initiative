"""Evidence: taking a person's files in, storing them sealed, and serving them.

Every path that handles an attached file goes through here:

- :func:`prepare` holds files to their stream's policy — how many, how large,
  and what their bytes say they are — and takes a picture's location out of it
  before anything is hashed or stored.
- :class:`Sealing` seals each file under a key of its own and writes its row,
  on the caller's session, in the caller's transaction, and removes what it
  wrote if that transaction does not commit.
- :func:`serve` streams one back, opened and checked against its hash, with
  the headers that keep a browser from treating it as anything but a download
  or a picture. Whether the reader may have the row is decided before this is
  called, by whichever session read it.
- :func:`transfer` carries a report's files into the operations case it was
  escalated to: the stored bytes are copied as they are and only the key is
  wrapped again.
- :func:`purge_due` and :func:`rewrap_guild` are the retention sweep's and the
  key rotation's halves.

Files are never written to ``uploads``: a community's uploads are readable
community-wide, and evidence is readable only through its own row.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import struct
import unicodedata
import uuid
import warnings
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional, Sequence

from fastapi.responses import StreamingResponse
from sqlalchemy import and_, delete, or_, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import blob_crypto
from app.core.intake import EvidencePolicy, IntakeStream, meta
from app.core.messages import EvidenceMessages
from app.db import cohorts
from app.db.request_context import SystemGuild
from app.db.session import set_rls_context
from app.db.soft_delete_filter import select_including_deleted
from app.models.tenant.evidence import DISPLAY_NAME_LENGTH, Evidence, EvidenceKind
from app.services import storage as storage_service

logger = logging.getLogger(__name__)

#: How evidence objects are named in their community's namespace.
_KEY_PREFIX = storage_service.EVIDENCE_KEY_PREFIX
_KEY_SUFFIX = ".iev"

#: Pictures a browser may draw inline. Anything else downloads.
_INLINE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})

#: Pictures whose location is taken out before they are stored.
_EXIF_TYPES = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}

#: The EXIF tag that holds where a picture was taken.
_GPS_TAG = 0x8825

_READ_CHUNK = 64 * 1024


class EvidenceRefused(Exception):
    """A file the stream does not take. ``code`` is the message to answer with."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class IncomingFile:
    """One file as a request carried it."""

    filename: Optional[str]
    data: bytes


@dataclass(frozen=True)
class PreparedEvidence:
    """A file ready to store: its bytes as they will be kept, what they are,
    and what to call them."""

    data: bytes
    content_type: str
    display_name: str
    sha256: str


# -- Taking files in ----------------------------------------------------------


def _sniff(data: bytes) -> str:
    from app.services.tenant.attachments import detect_mime_type

    detected = detect_mime_type(data) or "application/octet-stream"
    # Text of any flavour is kept as text: what it is called beyond that is a
    # guess, and nothing here renders it.
    if detected.startswith("text/"):
        return "text/plain"
    return detected


#: Bytes per value of each TIFF field type, for finding a value stored apart
#: from its entry.
_TIFF_TYPE_SIZES = {
    1: 1,
    2: 1,
    3: 2,
    4: 4,
    5: 8,
    6: 1,
    7: 1,
    8: 2,
    9: 4,
    10: 8,
    11: 4,
    12: 8,
    13: 4,
}

_EXIF_PREFIX = b"Exif\x00\x00"


def _clear(buf: bytearray, start: int, length: int, end: int) -> None:
    if start < 0 or length < 0 or start + length > end:
        raise ValueError("an EXIF value lies outside its block")
    buf[start : start + length] = bytes(length)


def _drop_gps(buf: bytearray, base: int, end: int) -> bool:
    """Take the location out of the EXIF block at ``buf[base:end]``, in place.

    The location's own directory and every value it points at are zeroed and
    its entry is removed from the first directory, so the block keeps its
    length and every other offset in it still holds. Returns whether there was
    a location to take out.
    """
    if buf[base : base + 6] == _EXIF_PREFIX:
        base += 6
    order = bytes(buf[base : base + 2])
    if order == b"II":
        e = "<"
    elif order == b"MM":
        e = ">"
    else:
        raise ValueError("not a TIFF header")
    ifd0 = base + struct.unpack_from(e + "I", buf, base + 4)[0]
    count = struct.unpack_from(e + "H", buf, ifd0)[0]
    directory_end = ifd0 + 2 + 12 * count
    if directory_end + 4 > end:
        raise ValueError("the first directory runs past its block")
    for i in range(count):
        entry = ifd0 + 2 + 12 * i
        if struct.unpack_from(e + "H", buf, entry)[0] != _GPS_TAG:
            continue
        gps = base + struct.unpack_from(e + "I", buf, entry + 8)[0]
        gps_count = struct.unpack_from(e + "H", buf, gps)[0]
        if gps + 2 + 12 * gps_count + 4 > end:
            raise ValueError("the location directory runs past its block")
        for j in range(gps_count):
            field = gps + 2 + 12 * j
            kind, n = struct.unpack_from(e + "HI", buf, field + 2)
            size = _TIFF_TYPE_SIZES.get(kind, 1) * n
            if size > 4:
                offset = base + struct.unpack_from(e + "I", buf, field + 8)[0]
                _clear(buf, offset, size, end)
        _clear(buf, gps, 2 + 12 * gps_count + 4, end)
        # The entry goes from the first directory: the ones after it, and the
        # next-directory offset, move up one place.
        buf[entry : directory_end + 4] = buf[entry + 12 : directory_end + 4] + bytes(12)
        struct.pack_into(e + "H", buf, ifd0, count - 1)
        return True
    return False


def _jpeg_exif(buf: bytearray) -> bool:
    found = False
    i = 2
    while i + 4 <= len(buf):
        if buf[i] != 0xFF:
            raise ValueError("not a JPEG marker")
        marker = buf[i + 1]
        if marker == 0xFF:
            i += 1
            continue
        if marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if marker in (0xD9, 0xDA):
            # The picture itself starts here; nothing after it is metadata.
            break
        length = struct.unpack_from(">H", buf, i + 2)[0]
        end = i + 2 + length
        if marker == 0xE1 and buf[i + 4 : i + 10] == _EXIF_PREFIX:
            found |= _drop_gps(buf, i + 4, end)
        i = end
    return found


def _png_exif(buf: bytearray) -> bool:
    found = False
    i = 8
    while i + 8 <= len(buf):
        length = struct.unpack_from(">I", buf, i)[0]
        kind = bytes(buf[i + 4 : i + 8])
        start, end = i + 8, i + 8 + length
        if kind == b"eXIf" and _drop_gps(buf, start, end):
            found = True
            struct.pack_into(">I", buf, end, zlib.crc32(buf[i + 4 : end]) & 0xFFFFFFFF)
        if kind == b"IEND":
            break
        i = end + 4
    return found


def _webp_exif(buf: bytearray) -> bool:
    if buf[0:4] != b"RIFF" or buf[8:12] != b"WEBP":
        raise ValueError("not a WebP container")
    found = False
    i = 12
    while i + 8 <= len(buf):
        kind = bytes(buf[i : i + 4])
        length = struct.unpack_from("<I", buf, i + 4)[0]
        start, end = i + 8, i + 8 + length
        if kind == b"EXIF":
            found |= _drop_gps(buf, start, end)
        i = end + (length & 1)
    return found


_LOCATION_REMOVERS = {"JPEG": _jpeg_exif, "PNG": _png_exif, "WEBP": _webp_exif}


def _without_location(data: bytes, content_type: str) -> bytes:
    """``data`` with where the picture was taken removed, or as it was where
    it carries no location. Pictures of other kinds carry no EXIF to remove.

    Only the location is changed, in place: the picture is not re-encoded, so
    its pixels, its frames and its size are what was sent.
    """
    fmt = _EXIF_TYPES.get(content_type)
    if fmt is None:
        return data
    from PIL import Image, UnidentifiedImageError

    from app.core.image_headers import MAX_IMAGE_PIXELS

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
            with Image.open(io.BytesIO(data)) as image:
                if _GPS_TAG not in image.getexif():
                    return data
        buf = bytearray(data)
        _LOCATION_REMOVERS[fmt](buf)
        return bytes(buf)
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        ValueError,
        struct.error,
    ) as exc:
        raise EvidenceRefused(EvidenceMessages.UNREADABLE) from exc


_UNSAFE_NAME = re.compile(r"[\x00-\x1f\x7f/\\]+")


def clean_name(filename: Optional[str]) -> str:
    """A name to show for a file: its last path part, with control characters
    and separators taken out, and no longer than the column."""
    name = unicodedata.normalize("NFC", Path(filename or "").name)
    name = _UNSAFE_NAME.sub(" ", name).strip().strip(".")
    if not name:
        return "attachment"
    if len(name) <= DISPLAY_NAME_LENGTH:
        return name
    stem, dot, ext = name.rpartition(".")
    if dot and len(ext) <= 10:
        return f"{stem[: DISPLAY_NAME_LENGTH - len(ext) - 1]}.{ext}"
    return name[:DISPLAY_NAME_LENGTH]


def prepare(
    files: Sequence[IncomingFile], policy: EvidencePolicy
) -> list[PreparedEvidence]:
    """Hold ``files`` to ``policy`` and ready each for storing.

    Raises :class:`EvidenceRefused` for the first thing wrong; nothing is kept
    of a set that is refused.
    """
    if not files:
        return []
    if policy.max_files == 0:
        raise EvidenceRefused(EvidenceMessages.NOT_TAKEN)
    if len(files) > policy.max_files:
        raise EvidenceRefused(EvidenceMessages.TOO_MANY)
    prepared: list[PreparedEvidence] = []
    for incoming in files:
        if not incoming.data:
            raise EvidenceRefused(EvidenceMessages.EMPTY)
        if len(incoming.data) > policy.max_bytes:
            raise EvidenceRefused(EvidenceMessages.TOO_LARGE)
        content_type = _sniff(incoming.data)
        if content_type not in policy.types:
            raise EvidenceRefused(EvidenceMessages.TYPE_NOT_ALLOWED)
        data = _without_location(incoming.data, content_type)
        prepared.append(
            PreparedEvidence(
                data=data,
                content_type=content_type,
                display_name=clean_name(incoming.filename),
                sha256=hashlib.sha256(data).hexdigest(),
            )
        )
    return prepared


# -- Storing ------------------------------------------------------------------


def _key(origin_id: uuid.UUID) -> str:
    return f"{_KEY_PREFIX}{origin_id.hex}{_KEY_SUFFIX}"


def store(
    session: AsyncSession,
    *,
    guild_id: int,
    prepared: Iterable[PreparedEvidence],
    created_by: Optional[int],
    written: list[str],
    case_id: Optional[int] = None,
    report_id: Optional[int] = None,
    comment_id: Optional[int] = None,
) -> list[Evidence]:
    """Seal and store each file in ``guild_id``'s namespace, and add its row to
    ``session``, which must be routed into that community. Each object's key
    is added to ``written`` before it is written. Nothing commits here: use
    :class:`Sealing`, which removes the objects if the rows never land.
    """
    storage = storage_service.get_guild_storage(guild_id)
    version = blob_crypto.current_kek_version()
    rows: list[Evidence] = []
    for item in prepared:
        origin_id = uuid.uuid4()
        dek = blob_crypto.new_dek()
        key = _key(origin_id)
        written.append(key)
        storage.write(
            key,
            blob_crypto.encrypt(
                item.data, dek, origin_guild_id=guild_id, origin_id=origin_id
            ),
            content_type="application/octet-stream",
        )
        row = Evidence(
            report_id=report_id,
            case_id=case_id,
            comment_id=comment_id,
            kind=EvidenceKind.attachment,
            origin_guild_id=guild_id,
            origin_id=origin_id,
            storage_key=key,
            size_bytes=len(item.data),
            content_type=item.content_type,
            display_name=item.display_name,
            sha256=item.sha256,
            wrapped_dek=blob_crypto.wrap(
                dek, holding_guild_id=guild_id, origin_id=origin_id, version=version
            ),
            kek_version=version,
            created_by=created_by,
        )
        session.add(row)
        rows.append(row)
    return rows


def discard(guild_id: int, keys: Iterable[str]) -> None:
    """Remove these stored objects, whose rows were never committed."""
    storage = storage_service.get_guild_storage(guild_id)
    for key in keys:
        try:
            storage.delete(key)
        except Exception:  # pragma: no cover - best effort, logged
            logger.exception("evidence: could not remove %s", key)


class Sealing:
    """The objects one transaction writes into ``guild_id``'s namespace.

    Everything written inside the ``with`` block is removed again when the
    block ends without :meth:`keep` having been called — whatever failed, and
    wherever. Call :meth:`keep` straight after the commit that holds the rows::

        with Sealing(guild_id) as sealing:
            sealing.store(session, prepared=files, created_by=user_id, case_id=1)
            ...
            await session.commit()
            sealing.keep()
    """

    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        self.written: list[str] = []
        self._kept = False

    def __enter__(self) -> "Sealing":
        return self

    def __exit__(self, *exc: object) -> None:
        if not self._kept and self.written:
            discard(self.guild_id, self.written)

    def store(
        self,
        session: AsyncSession,
        *,
        prepared: Iterable[PreparedEvidence],
        created_by: Optional[int],
        case_id: Optional[int] = None,
        report_id: Optional[int] = None,
        comment_id: Optional[int] = None,
    ) -> list[Evidence]:
        return store(
            session,
            guild_id=self.guild_id,
            prepared=prepared,
            created_by=created_by,
            written=self.written,
            case_id=case_id,
            report_id=report_id,
            comment_id=comment_id,
        )

    def keep(self) -> None:
        """The rows committed: the objects stay."""
        self._kept = True


# -- Listing ------------------------------------------------------------------


async def listed(
    session: AsyncSession,
    *,
    report_ids: Sequence[int] = (),
    case_ids: Sequence[int] = (),
) -> dict[tuple[str, int], list[Evidence]]:
    """The files attached to these reports and cases, read on ``session`` and
    keyed ``("report", id)`` or ``("case", id)``, oldest first. One statement,
    whatever the page holds."""
    if not report_ids and not case_ids:
        return {}
    conditions = []
    if report_ids:
        conditions.append(Evidence.report_id.in_(tuple(report_ids)))  # type: ignore[union-attr]
    if case_ids:
        conditions.append(Evidence.case_id.in_(tuple(case_ids)))  # type: ignore[union-attr]
    rows = (
        await session.exec(
            select(Evidence)
            .where(or_(*conditions))
            .order_by(Evidence.created_at, Evidence.id)
        )
    ).all()
    found: dict[tuple[str, int], list[Evidence]] = {}
    for row in rows:
        key = ("report", row.report_id) if row.report_id else ("case", row.case_id)
        found.setdefault(key, []).append(row)  # type: ignore[arg-type]
    return found


# -- Serving ------------------------------------------------------------------


@dataclass(frozen=True)
class SealedObject:
    """What opening one stored object takes, read from its row."""

    storage_key: str
    origin_guild_id: int
    origin_id: uuid.UUID
    wrapped_dek: bytes
    kek_version: int
    sha256: str
    content_type: str
    display_name: str
    size_bytes: int


async def sealed(session: AsyncSession, evidence_id: int) -> Optional[SealedObject]:
    """The stored half of row ``evidence_id``, read on ``session`` — a system
    session routed into the community holding it, once the reader's own
    session has shown the row is theirs to read."""
    row = (
        await session.exec(
            select(
                Evidence.storage_key,
                Evidence.origin_guild_id,
                Evidence.origin_id,
                Evidence.wrapped_dek,
                Evidence.kek_version,
                Evidence.sha256,
                Evidence.content_type,
                Evidence.display_name,
                Evidence.size_bytes,
            ).where(Evidence.id == evidence_id)
        )
    ).first()
    return SealedObject(*row) if row is not None else None


def _stored_bytes(guild_id: int, key: str) -> Iterator[bytes]:
    blob = storage_service.get_guild_storage(guild_id).open_readable(key)
    if blob is None:
        raise EvidenceRefused(EvidenceMessages.NOT_FOUND)
    if blob.path is not None:
        with blob.path.open("rb") as handle:
            while piece := handle.read(_READ_CHUNK):
                yield piece
        return
    yield from blob.stream or ()


def plaintext(guild_id: int, obj: SealedObject) -> Iterator[bytes]:
    """The object's bytes as they were stored, a chunk at a time, checked
    against the row's hash once the last one is out."""
    dek = blob_crypto.unwrap(
        obj.wrapped_dek,
        holding_guild_id=guild_id,
        origin_id=obj.origin_id,
        version=obj.kek_version,
    )
    digest = hashlib.sha256()
    for chunk in blob_crypto.decrypt_stream(
        _stored_bytes(guild_id, obj.storage_key),
        dek,
        origin_guild_id=obj.origin_guild_id,
        origin_id=obj.origin_id,
    ):
        digest.update(chunk)
        yield chunk
    if digest.hexdigest() != obj.sha256:
        raise blob_crypto.BlobCryptoError("the object is not the one its row names")


def serve(guild_id: int, obj: SealedObject) -> StreamingResponse:
    """A response streaming one object, opened. Pictures are shown; anything
    else is downloaded. Never cached, never sniffed, never run."""
    from app.services.storage import content_disposition_attachment

    inline = obj.content_type in _INLINE_TYPES
    headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox; default-src 'none'",
        "Content-Length": str(obj.size_bytes),
        "Content-Disposition": (
            "inline" if inline else content_disposition_attachment(obj.display_name)
        ),
    }
    return StreamingResponse(
        plaintext(guild_id, obj),
        media_type=obj.content_type if inline else "application/octet-stream",
        headers=headers,
    )


# -- Crossing communities -----------------------------------------------------


async def transfer(
    *,
    source_guild_id: int,
    rows: Sequence[Evidence],
    destination: AsyncSession,
    destination_guild_id: int,
    case_id: int,
    written: list[str],
) -> list[Evidence]:
    """Carry ``rows`` — read in ``source_guild_id`` — into the operations case
    ``case_id``, on ``destination``, a system session routed into
    ``destination_guild_id``.

    Each object is copied as it is stored; it is never opened. Its key is
    unwrapped with the source community's key and wrapped with the
    destination's, and the new row keeps the object's origin and hash, which is
    what its bytes are bound to. Each object copied is added to ``written``.
    Nothing commits here.
    """
    already = set(
        (
            await destination.exec(
                select(Evidence.origin_id).where(Evidence.case_id == case_id)
            )
        ).all()
    )
    same_community = int(source_guild_id) == int(destination_guild_id)
    version = blob_crypto.current_kek_version()
    carried: list[Evidence] = []
    for row in rows:
        if row.origin_id in already:
            # Carried by an earlier escalation of the same report.
            continue
        if not same_community:
            # Named before the copy, so one that fails part way is removed too.
            written.append(row.storage_key)
            if not storage_service.copy_between_guilds(
                source_guild_id, destination_guild_id, row.storage_key
            ):
                written.pop()
                logger.warning(
                    "evidence: %s is gone from community %s; not carried",
                    row.storage_key,
                    source_guild_id,
                )
                continue
        dek = blob_crypto.unwrap(
            row.wrapped_dek,
            holding_guild_id=source_guild_id,
            origin_id=row.origin_id,
            version=row.kek_version,
        )
        copy = Evidence(
            case_id=case_id,
            kind=row.kind,
            origin_guild_id=row.origin_guild_id,
            origin_id=row.origin_id,
            storage_key=row.storage_key,
            size_bytes=row.size_bytes,
            content_type=row.content_type,
            display_name=row.display_name,
            sha256=row.sha256,
            wrapped_dek=blob_crypto.wrap(
                dek,
                holding_guild_id=destination_guild_id,
                origin_id=row.origin_id,
                version=version,
            ),
            kek_version=version,
            created_by=row.created_by,
        )
        destination.add(copy)
        carried.append(copy)
    return carried


async def carry_report(
    session: AsyncSession,
    *,
    source_guild_id: int,
    report_id: int,
    case_id: int,
) -> int:
    """Carry what was attached to community report ``report_id`` — read on
    ``session``, routed into ``source_guild_id`` — into operations case
    ``case_id``. Returns how many files were carried.

    Its own transaction in the operations community, committed before the
    report closes: a report closed as escalated has handed its files over.
    """
    from app.services.platform.intake import configured_operations_guild_id

    rows = (
        await session.exec(select(Evidence).where(Evidence.report_id == report_id))
    ).all()
    if not rows:
        return 0
    operations = await configured_operations_guild_id()
    if operations is None:
        return 0
    async with cohorts.system_session(operations) as destination:
        await set_rls_context(destination, SystemGuild(operations))
        with Sealing(operations) as sealing:
            carried = await transfer(
                source_guild_id=source_guild_id,
                rows=rows,
                destination=destination,
                destination_guild_id=operations,
                case_id=case_id,
                written=sealing.written,
            )
            await destination.commit()
            sealing.keep()
    return len(carried)


# -- Retention ----------------------------------------------------------------


async def purge_due(session: AsyncSession, guild_id: int) -> int:
    """One community's retention: delete the evidence of what closed long
    enough ago — the rows, then the objects. Returns how many went.

    A case closes when its task is done or in the trash, and its evidence is
    kept for its stream's ``retention_days`` from then. A report closes when it
    is settled, and its evidence is kept for the moderation stream's. Each is
    read from the parent as it stands when the rows are deleted, so a reopened
    case keeps its files, and one closed again counts from the new close. The
    tasks are locked while that is decided, so a reopen at the same moment
    either lands first and keeps the files, or waits for them to go. A case
    a hold still names keeps its files until the hold is released.
    """
    from app.models.tenant.intake import IntakeCase
    from app.models.tenant.moderation import ModerationReport
    from app.models.tenant.task import Task, TaskStatus, TaskStatusCategory

    now = datetime.now(timezone.utc)
    gone: list[str] = []
    for stream in IntakeStream:
        cutoff = now - timedelta(days=meta(stream).retention_days)
        due = (
            await session.exec(
                # A case in the trash is closed too.
                select_including_deleted(IntakeCase.id, IntakeCase.task_id)
                .join(Task, Task.id == IntakeCase.task_id)
                .join(TaskStatus, TaskStatus.id == Task.task_status_id)
                .where(IntakeCase.stream == stream.value)
                .where(IntakeCase.id.in_(select(Evidence.case_id)))  # type: ignore[union-attr]
                .where(
                    or_(
                        Task.deleted_at < cutoff,  # type: ignore[operator]
                        and_(
                            TaskStatus.category == TaskStatusCategory.done,
                            Task.completed_at < cutoff,  # type: ignore[operator]
                        ),
                    )
                )
                .with_for_update(of=Task)
            )
        ).all()
        if not due:
            continue
        # A case a hold still names keeps its files for as long as the hold
        # stands, however long ago it closed.
        held = await held_cases(session, [int(task_id) for _id, task_id in due])
        kept = [int(case_id) for case_id, task_id in due if task_id not in held]
        if not kept:
            continue
        gone += (
            (
                await session.exec(
                    delete(Evidence)
                    .where(Evidence.case_id.in_(kept))  # type: ignore[union-attr]
                    .returning(Evidence.storage_key)
                )
            )
            .scalars()
            .all()
        )
    report_cutoff = now - timedelta(days=meta(IntakeStream.moderation).retention_days)
    gone += (
        (
            await session.exec(
                delete(Evidence)
                .where(
                    Evidence.report_id.in_(  # type: ignore[union-attr]
                        select(ModerationReport.id).where(
                            ModerationReport.decided_at < report_cutoff  # type: ignore[operator]
                        )
                    )
                )
                .returning(Evidence.storage_key)
            )
        )
        .scalars()
        .all()
    )
    await session.commit()
    if gone:
        await _remove_unnamed(session, guild_id, gone)
        logger.info("evidence: purged %s from community %s", len(gone), guild_id)
    return len(gone)


async def held_cases(session: AsyncSession, task_ids: Sequence[int]) -> set[int]:
    """The cases among ``task_ids`` that a hold in force still names.

    ``session`` is routed into the operations community. A case's holds sit
    in the community it is about — placing a hold for a case settles that —
    so each community is asked about its own cases, once. One that can't be
    asked keeps its cases' files until it can.
    """
    from app.core.intake import CaseField
    from app.db.session import SystemSessionLocal
    from app.models.platform.guild import Guild
    from app.models.tenant.content_hold import ContentHold
    from app.services.tenant.metadata import summaries_by_id

    by_subject: dict[int, list[int]] = {}
    for task_id, summaries in (
        await summaries_by_id(session, "task", task_ids)
    ).items():
        for summary in summaries:
            if summary.name != CaseField.subject_guild.value:
                continue
            try:
                subject = int(summary.value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            by_subject.setdefault(subject, []).append(task_id)
    if not by_subject:
        return set()
    async with SystemSessionLocal() as shared:
        standing = set(
            (
                await shared.exec(
                    select(Guild.id).where(Guild.id.in_(list(by_subject)))  # type: ignore[union-attr]
                )
            ).all()
        )
    held: set[int] = set()
    for subject, ids in by_subject.items():
        if subject not in standing:
            # A community deleted for good held nothing: it couldn't be
            # deleted while a hold stood.
            continue
        try:
            async with cohorts.system_session(subject) as other:
                await set_rls_context(other, SystemGuild(subject, read_only=True))
                held.update(
                    (
                        await other.exec(
                            select(ContentHold.case_task_id)
                            .where(ContentHold.case_task_id.in_(ids))  # type: ignore[union-attr]
                            .where(ContentHold.released_at.is_(None))  # type: ignore[union-attr]
                        )
                    ).all()
                )
                await other.rollback()
        except Exception:  # noqa: BLE001 — kept rather than lost; asked again next sweep
            logger.exception("evidence: could not ask community %s for holds", subject)
            held.update(ids)
    return {int(task_id) for task_id in held if task_id is not None}


async def _remove_unnamed(
    session: AsyncSession, guild_id: int, keys: Iterable[str]
) -> None:
    """Remove the objects no row in ``guild_id`` names any more. A report's
    file carried into a case in the same community is one object under two
    rows, and stays while either does."""
    keys = set(keys)
    if not keys:
        return
    still = set(
        (
            await session.exec(
                select(Evidence.storage_key).where(
                    Evidence.storage_key.in_(tuple(keys))  # type: ignore[union-attr]
                )
            )
        ).all()
    )
    discard(guild_id, keys - still)


async def released_by_purge(
    session: AsyncSession,
    *,
    task_ids: Sequence[int] = (),
    initiative_ids: Sequence[int] = (),
) -> set[str]:
    """The stored objects that go when these tasks and initiatives are purged
    for good: their cases' and reports' files, which their rows' cascade takes
    with them. An object another surviving row still names is left out.

    Read before the parents are deleted, on the purging session; the caller
    removes what this returns once its commit has landed.
    """
    from app.models.tenant.intake import IntakeCase
    from app.models.tenant.moderation import ModerationReport

    conditions = []
    if task_ids:
        conditions.append(
            Evidence.case_id.in_(  # type: ignore[union-attr]
                select(IntakeCase.id).where(
                    IntakeCase.task_id.in_(tuple(task_ids))  # type: ignore[union-attr]
                )
            )
        )
    if initiative_ids:
        conditions.append(
            Evidence.report_id.in_(  # type: ignore[union-attr]
                select(ModerationReport.id).where(
                    ModerationReport.initiative_id.in_(tuple(initiative_ids))  # type: ignore[union-attr]
                )
            )
        )
    if not conditions:
        return set()
    doomed = (
        await session.exec(
            select(Evidence.id, Evidence.storage_key).where(or_(*conditions))
        )
    ).all()
    if not doomed:
        return set()
    keys = {key for _, key in doomed}
    still = set(
        (
            await session.exec(
                select(Evidence.storage_key)
                .where(Evidence.storage_key.in_(tuple(keys)))  # type: ignore[union-attr]
                .where(Evidence.id.not_in(tuple(i for i, _ in doomed)))  # type: ignore[union-attr]
            )
        ).all()
    )
    return keys - still


# -- Key rotation -------------------------------------------------------------


async def rewrap_guild(
    session: AsyncSession,
    guild_id: int,
    *,
    old_secret_key: str,
    new_secret_key: str,
    dry_run: bool = False,
) -> tuple[int, int, int]:
    """Wrap every evidence key in ``guild_id`` that ``SECRET_KEY`` wraps
    (version 1) under ``new_secret_key``. Objects are not touched, nor are
    keys under the community's storage key (version 2), which a rotation of
    ``SECRET_KEY`` does not reach. Returns ``(rotated, skipped, failed)``: a
    key that already unwraps under the new secret is skipped, one that
    unwraps under neither is counted and left."""
    rows = (
        await session.exec(
            select(Evidence.id, Evidence.origin_id, Evidence.wrapped_dek).where(
                Evidence.kek_version == blob_crypto.KEK_VERSION
            )
        )
    ).all()
    rotated = skipped = failed = 0
    for evidence_id, origin_id, wrapped in rows:
        try:
            blob_crypto.unwrap(
                wrapped,
                holding_guild_id=guild_id,
                origin_id=origin_id,
                secret_key=new_secret_key,
            )
            skipped += 1
            continue
        except blob_crypto.BlobCryptoError:
            pass
        try:
            new = blob_crypto.rewrap(
                wrapped,
                holding_guild_id=guild_id,
                origin_id=origin_id,
                old_secret_key=old_secret_key,
                new_secret_key=new_secret_key,
            )
        except blob_crypto.BlobCryptoError:
            failed += 1
            continue
        rotated += 1
        if not dry_run:
            await session.exec(
                update(Evidence)
                .where(Evidence.id == evidence_id)
                .values(wrapped_dek=new, kek_version=blob_crypto.KEK_VERSION)
            )
    return rotated, skipped, failed


async def adopt_community_key(session: AsyncSession, guild_id: int) -> int:
    """Re-wrap every evidence key in ``guild_id`` that ``SECRET_KEY`` wraps
    under the community's storage key instead, so the evidence goes with that
    key when the community does. Objects are not touched. ``session`` is
    routed into the community; the caller commits. Returns how many it
    re-wrapped."""
    rows = (
        await session.exec(
            select(Evidence.id, Evidence.origin_id, Evidence.wrapped_dek).where(
                Evidence.kek_version == blob_crypto.KEK_VERSION
            )
        )
    ).all()
    for evidence_id, origin_id, wrapped in rows:
        dek = blob_crypto.unwrap(
            wrapped, holding_guild_id=guild_id, origin_id=origin_id
        )
        await session.exec(
            update(Evidence)
            .where(Evidence.id == evidence_id)
            .values(
                wrapped_dek=blob_crypto.wrap(
                    dek,
                    holding_guild_id=guild_id,
                    origin_id=origin_id,
                    version=blob_crypto.COMMUNITY_KEK_VERSION,
                ),
                kek_version=blob_crypto.COMMUNITY_KEK_VERSION,
            )
        )
    return len(rows)
