"""Resumable uploads: a file sent in pieces over tus 1.0, until an endpoint
takes it.

tus (tus.io/protocols/resumable-upload) is how a large file arrives: the
client creates an upload of a declared length, appends to it with ``PATCH``
requests of up to :data:`MAX_CHUNK_BYTES`, asks where it stands with ``HEAD``
after a drop, and carries on from there. Core, ``creation``, ``termination``
and ``expiration`` are spoken; the official JS client needs no more.

An upload only stages a file. Its ``purpose`` names the endpoint that will
take it (:data:`PURPOSES`), which decides at creation whether the person may
write there and how large the file may be. Once complete, the client calls
that endpoint with the upload's id in place of a multipart file, and the
endpoint checks the file as it checks any other.

The bytes are written to the guild's storage as they arrive, a part at a time
(``StorageBackend.start_parts`` and the methods beside it), so a request holds
no more than one part in memory, and no database connection while it reads
the body. The ``pending_uploads`` row is the upload's only record; a lease on
it lets one request at a time append. An upload's declared length counts
toward the community's storage from creation, and the ``resumable_uploads``
sweep throws away what was not taken within :data:`EXPIRES_AFTER`.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import math
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy import func, or_, update
from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.requests import ClientDisconnect

from app.core.file_types import is_refused
from app.core.messages import FileMessages, ResumableMessages
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.models.platform.user import User
from app.models.tenant.pending_upload import PendingUpload
from app.services.storage import get_guild_storage
from app.services.tenant import attachments

logger = logging.getLogger(__name__)

TUS_VERSION = "1.0.0"
#: The most one ``PATCH`` may carry. A reverse proxy needs to allow no more.
MAX_CHUNK_BYTES = 50 * 1024 * 1024
#: How much is held in memory before it is written as a part.
PART_BYTES = 8 * 1024 * 1024
#: How long an upload has to finish and be taken.
EXPIRES_AFTER = timedelta(hours=24)
#: How long a request appending to an upload holds it, renewed per part.
LEASE = timedelta(seconds=60)
#: Uploads one person may have unfinished at once.
MAX_LIVE_PER_PERSON = 5
MAX_METADATA_BYTES = 4096
#: Parts an upload may have: S3's limit is 10,000.
_MAX_PARTS = 9_000
#: How often a long request re-establishes the reader's standing.
_STANDING_SECONDS = 30
#: How long a request waits for the client's next bytes before renewing.
_RENEW_SECONDS = 20
#: The largest size Postgres keeps (``bigint``).
_MAX_BYTES = 2**63 - 1
_STAGING_PREFIX = "resumable-"


@dataclass(frozen=True)
class Purpose:
    """What an upload is for."""

    #: The largest file it may be, ``None`` for no limit but the storage's.
    cap: Callable[[], int | None]
    #: Refuses a person who may not write there; answers the initiative the
    #: file will be kept for.
    admit: Callable[[AsyncSession, Any, User, dict[str, str]], Awaitable[int | None]]


async def _admit_file(
    session: AsyncSession, guild_context: Any, user: User, metadata: dict[str, str]
) -> int | None:
    """A new file in ``initiative_id``, or a new version of ``file_id``."""
    from app.api import resource_access
    from app.core.tools import Tool

    try:
        if "file_id" in metadata:
            file = await resource_access.load_authorized(
                session,
                Tool.file,
                int(metadata["file_id"]),
                user,
                guild_context,
                access="write",
            )
            return file.initiative_id
        initiative = await resource_access.prepare_create(
            session, Tool.file, int(metadata["initiative_id"]), user, guild_context
        )
    except (KeyError, ValueError):
        raise _refuse(status.HTTP_400_BAD_REQUEST, ResumableMessages.INVALID_REQUEST)
    return initiative.id


PURPOSES: dict[str, Purpose] = {
    # A file's size is bounded by the community's storage alone.
    "file": Purpose(cap=lambda: None, admit=_admit_file),
}


def _refuse(code: int, detail: str) -> HTTPException:
    return HTTPException(
        status_code=code, detail=detail, headers={"Tus-Resumable": TUS_VERSION}
    )


def _headers(upload: PendingUpload) -> dict[str, str]:
    return {
        "Tus-Resumable": TUS_VERSION,
        "Upload-Offset": str(upload.offset),
        "Upload-Length": str(upload.length),
        "Upload-Expires": format_datetime(upload.expires_at, usegmt=True),
        "Cache-Control": "no-store",
    }


def _require_version(request: Request) -> None:
    if request.headers.get("tus-resumable") != TUS_VERSION:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail=ResumableMessages.VERSION_UNSUPPORTED,
            headers={"Tus-Version": TUS_VERSION},
        )


def _number(value: str | None) -> int:
    """A header's count of bytes, as large as Postgres keeps one."""
    if (
        value is None
        or not (value.isascii() and value.isdigit())
        or len(value) > 19
        or int(value) > _MAX_BYTES
    ):
        raise _refuse(status.HTTP_400_BAD_REQUEST, ResumableMessages.INVALID_REQUEST)
    return int(value)


def _metadata(header: str | None) -> dict[str, str]:
    """``Upload-Metadata``: comma-separated ``key base64value`` pairs."""
    if not header:
        return {}
    if len(header) > MAX_METADATA_BYTES:
        raise _refuse(status.HTTP_400_BAD_REQUEST, ResumableMessages.INVALID_REQUEST)
    pairs: dict[str, str] = {}
    for pair in header.split(","):
        key, _, value = pair.strip().partition(" ")
        try:
            pairs[key] = base64.b64decode(value, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            raise _refuse(
                status.HTTP_400_BAD_REQUEST, ResumableMessages.INVALID_REQUEST
            )
    return pairs


def options() -> Response:
    """What the server speaks."""
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={
            "Tus-Resumable": TUS_VERSION,
            "Tus-Version": TUS_VERSION,
            "Tus-Extension": "creation,termination,expiration",
        },
    )


async def create(
    request: Request, session: AsyncSession, guild_context: Any, user: User
) -> Response:
    """Create an upload of the declared length, for its ``purpose``. Refused
    before anything is stored for a person who may not write there, a file
    too large for it, one named as a program, too many unfinished uploads,
    and a community without room for it."""
    _require_version(request)
    length = _number(request.headers.get("upload-length"))
    metadata = _metadata(request.headers.get("upload-metadata"))
    purpose = PURPOSES.get(metadata.get("purpose", ""))
    filename = attachments.display_filename(metadata.get("filename"))
    if purpose is None or filename is None:
        raise _refuse(status.HTTP_400_BAD_REQUEST, ResumableMessages.INVALID_REQUEST)
    if is_refused(None, filename):
        raise _refuse(status.HTTP_400_BAD_REQUEST, FileMessages.TYPE_NOT_ALLOWED)
    cap = purpose.cap()
    if cap is not None and length > cap:
        raise _refuse(status.HTTP_413_CONTENT_TOO_LARGE, FileMessages.FILE_TOO_LARGE)
    initiative_id = await purpose.admit(session, guild_context, user, metadata)
    guild_id = guild_context.guild_id
    # Counted and added in turn, so two at once count each other.
    await advisory_lock(session, LockNamespace.PENDING_UPLOADS, f"{guild_id}:{user.id}")
    live = await session.scalar(
        select(func.count())
        .select_from(PendingUpload)
        .where(PendingUpload.created_by == user.id)
    )
    if (live or 0) >= MAX_LIVE_PER_PERSON:
        raise _refuse(status.HTTP_429_TOO_MANY_REQUESTS, ResumableMessages.TOO_MANY)
    await attachments.enforce_storage_quota(
        session, guild_id=guild_id, incoming_bytes=length
    )

    upload_id = secrets.token_urlsafe(16)
    key = f"{_STAGING_PREFIX}{upload_id}"
    storage = get_guild_storage(guild_id)
    part_bytes = max(PART_BYTES, math.ceil(length / _MAX_PARTS))
    state = await asyncio.to_thread(storage.start_parts, key, part_bytes=part_bytes)
    now = datetime.now(timezone.utc)
    upload = PendingUpload(
        id=upload_id,
        created_by=user.id,
        purpose=metadata["purpose"],
        initiative_id=initiative_id,
        filename=filename,
        length=length,
        staging_key=key,
        blob_state=state,
        expires_at=now + EXPIRES_AFTER,
    )
    if length == 0:
        await asyncio.to_thread(storage.finish_parts, key, state)
        upload.completed_at = now
    session.add(upload)
    try:
        await session.commit()
    except Exception:
        await asyncio.to_thread(storage.drop_parts, key, state)
        raise
    location = f"{str(request.url).split('?', 1)[0].rstrip('/')}/{upload_id}"
    return Response(
        status_code=status.HTTP_201_CREATED,
        headers={**_headers(upload), "Location": location},
    )


async def _live(session: AsyncSession, upload_id: str) -> PendingUpload:
    upload = await session.get(PendingUpload, upload_id, populate_existing=True)
    if upload is None:
        raise _refuse(status.HTTP_404_NOT_FOUND, ResumableMessages.NOT_FOUND)
    if upload.expires_at <= datetime.now(timezone.utc):
        raise _refuse(status.HTTP_410_GONE, ResumableMessages.EXPIRED)
    return upload


class _Lease:
    """One request's hold on an upload: taken and committed before anything
    else is read, with no transaction left open after it, renewed while the
    request works, and let go at the end.
    Every record of progress is made under it, so a request that has lost it
    writes nothing more."""

    def __init__(self, session: AsyncSession, upload_id: str, renew: Any) -> None:
        self.session, self.upload_id, self._renew = session, upload_id, renew
        self.token: str | None = None

    async def take(self) -> PendingUpload:
        """The upload as it stands, now that this request holds it."""
        await _live(self.session, self.upload_id)
        token = secrets.token_urlsafe(16)
        taken = await self.session.exec(
            update(PendingUpload)
            .where(
                col(PendingUpload.id) == self.upload_id,
                or_(
                    col(PendingUpload.lease_until).is_(None),
                    col(PendingUpload.lease_until) < func.now(),
                ),
            )
            .values(lease_token=token, lease_until=func.now() + LEASE)
            .returning(PendingUpload.id)
        )
        found = taken.first() is not None
        await self.session.commit()
        if not found:
            raise _refuse(status.HTTP_423_LOCKED, ResumableMessages.LOCKED)
        self.token = token
        upload = await _live(self.session, self.upload_id)
        # Ended here, so no connection is held while the request waits.
        await self.session.commit()
        return upload

    async def record(self, values: dict[str, Any], *, done: bool = False) -> None:
        """Save ``values`` under the lease, renewing it, or letting it go when
        ``done``; refused once another request holds it."""
        await self._renew()
        lease = (
            {"lease_token": None, "lease_until": None}
            if done
            else {"lease_until": func.now() + LEASE}
        )
        saved = await self.session.exec(
            update(PendingUpload)
            .where(
                col(PendingUpload.id) == self.upload_id,
                col(PendingUpload.lease_token) == self.token,
            )
            .values(**values, **lease)
            .returning(PendingUpload.id)
        )
        held = saved.first() is not None
        await self.session.commit()
        if done:
            self.token = None
        if not held:
            self.token = None
            raise _refuse(status.HTTP_423_LOCKED, ResumableMessages.LOCKED)

    async def let_go(self) -> None:
        """Let the lease go if the request still holds it; a failure to is
        left to the lease's own expiry."""
        if self.token is None:
            return
        try:
            await self.session.rollback()
            await self.session.exec(
                update(PendingUpload)
                .where(
                    col(PendingUpload.id) == self.upload_id,
                    col(PendingUpload.lease_token) == self.token,
                )
                .values(lease_token=None, lease_until=None)
            )
            await self.session.commit()
        except Exception:
            logger.warning("lease_release_failed upload=%s", self.upload_id)
        self.token = None


async def _finish(lease: _Lease, storage: Any, upload: PendingUpload) -> None:
    """Make a fully arrived upload's parts its staged object, and record it
    complete. Recorded as finishing first, so a request whose own record of
    completion does not land leaves an upload the next can finish."""
    state = {**upload.blob_state, "finishing": True}
    await lease.record({"offset": upload.length, "blob_state": state})
    await asyncio.to_thread(storage.finish_parts, upload.staging_key, state)
    await lease.record({"completed_at": func.now()}, done=True)


def _finishing(upload: PendingUpload) -> bool:
    return upload.completed_at is None and bool(upload.blob_state.get("finishing"))


async def head(session: AsyncSession, guild_id: int, upload_id: str) -> Response:
    """Where an upload stands. One a request left finishing is finished."""
    upload = await _live(session, upload_id)
    if _finishing(upload):
        lease = _Lease(session, upload_id, _nothing)
        try:
            upload = await lease.take()
            if _finishing(upload):
                await _finish(lease, get_guild_storage(guild_id), upload)
        except HTTPException as exc:
            # Another request is finishing it; say where it stands.
            if exc.status_code != status.HTTP_423_LOCKED:
                raise
        finally:
            await lease.let_go()
        upload = await _live(session, upload_id)
    return Response(headers=_headers(upload))


async def _nothing() -> None:
    return None


async def patch(
    request: Request,
    session: AsyncSession,
    guild_context: Any,
    user: User,
    upload_id: str,
) -> Response:
    """Append the request's body to an upload at the offset it names.

    The lease is taken and committed before anything else is read, so no
    database connection is held while the body streams. It is renewed before
    each part is written and while the request waits for bytes, and progress
    is recorded after each part, re-establishing the reader's standing as it
    ages; a person who lost access is refused at the next part. A client that
    drops keeps what arrived: the request's last bytes wait for the next one,
    and ``HEAD`` answers from there.
    """
    from app.api.deps import (
        GuildAccessError,
        establish_guild_access,
        raise_for_guild_access,
    )

    _require_version(request)
    if request.headers.get("content-type") != "application/offset+octet-stream":
        raise _refuse(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, ResumableMessages.INVALID_REQUEST
        )
    offset = _number(request.headers.get("upload-offset"))
    declared = request.headers.get("content-length")
    guild_id = guild_context.guild_id
    established = time.monotonic()

    async def keep_standing() -> None:
        nonlocal established
        if time.monotonic() - established > _STANDING_SECONDS:
            try:
                await establish_guild_access(session, user, guild_id)
            except GuildAccessError as exc:
                raise_for_guild_access(exc)
            established = time.monotonic()

    lease = _Lease(session, upload_id, keep_standing)
    pending: asyncio.Future | None = None
    try:
        upload = await lease.take()
        if offset != upload.offset or upload.completed_at is not None:
            raise _refuse(status.HTTP_409_CONFLICT, ResumableMessages.OFFSET_MISMATCH)
        if declared is not None and offset + _number(declared) > upload.length:
            raise _refuse(status.HTTP_400_BAD_REQUEST, ResumableMessages.PAST_LENGTH)
        storage = get_guild_storage(guild_id)
        if _finishing(upload):
            await _finish(lease, storage, upload)
            return Response(
                status_code=status.HTTP_204_NO_CONTENT,
                headers=_headers(await _live(session, upload_id)),
            )

        key, length = upload.staging_key, upload.length
        tail, state = await asyncio.to_thread(storage.take_tail, key, upload.blob_state)
        buffer = bytearray(tail)
        part = state["part_bytes"]
        stream = request.stream().__aiter__()
        while True:
            if pending is None:
                pending = asyncio.ensure_future(anext(stream))
            if not (await asyncio.wait({pending}, timeout=_RENEW_SECONDS))[0]:
                # Still waiting for the client: keep the upload held.
                await lease.record({})
                continue
            arrived, pending = pending, None
            try:
                chunk = arrived.result()
            except (StopAsyncIteration, ClientDisconnect):
                break
            if len(chunk) > length - state["stored"] - len(buffer):
                raise _refuse(
                    status.HTTP_400_BAD_REQUEST, ResumableMessages.PAST_LENGTH
                )
            buffer += chunk
            while len(buffer) >= part and state["stored"] + part < length:
                # Held before it is written, so no request writes after
                # another has taken the upload over.
                await lease.record({})
                state = await asyncio.to_thread(
                    storage.add_part, key, state, bytes(buffer[:part])
                )
                del buffer[:part]
                await lease.record({"offset": state["stored"], "blob_state": state})

        await lease.record({})
        if state["stored"] + len(buffer) == length:
            if buffer:
                state = await asyncio.to_thread(
                    storage.add_part, key, state, bytes(buffer)
                )
            upload.blob_state = state
            await _finish(lease, storage, upload)
        else:
            state = await asyncio.to_thread(
                storage.keep_tail, key, state, bytes(buffer)
            )
            await lease.record(
                {"offset": state["stored"] + state["tail"], "blob_state": state},
                done=True,
            )
    finally:
        if pending is not None:
            pending.cancel()
        await lease.let_go()
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers=_headers(await _live(session, upload_id)),
    )


async def terminate(session: AsyncSession, guild_id: int, upload_id: str) -> Response:
    """Throw an upload away, staged bytes and all."""
    lease = _Lease(session, upload_id, _nothing)
    try:
        upload = await lease.take()
        await asyncio.to_thread(
            get_guild_storage(guild_id).drop_parts,
            upload.staging_key,
            upload.blob_state,
        )
        await session.exec(
            delete(PendingUpload).where(col(PendingUpload.id) == upload_id)
        )
        await session.commit()
        lease.token = None
    finally:
        await lease.let_go()
    return Response(
        status_code=status.HTTP_204_NO_CONTENT, headers={"Tus-Resumable": TUS_VERSION}
    )


# --- the sweep ---------------------------------------------------------------


async def expire(session: AsyncSession, guild_id: int) -> None:
    """The ``resumable_uploads`` sweep's visit: throw away every upload past
    its expiry that no request is appending to."""
    storage = get_guild_storage(guild_id)
    expired = (
        await session.exec(
            select(PendingUpload).where(
                PendingUpload.expires_at <= func.now(),
                or_(
                    col(PendingUpload.lease_until).is_(None),
                    col(PendingUpload.lease_until) < func.now(),
                ),
            )
        )
    ).all()
    for upload in expired:
        try:
            await asyncio.to_thread(
                storage.drop_parts, upload.staging_key, upload.blob_state
            )
        except Exception:
            # The row goes; staged bytes left behind cost storage and nothing
            # else, and go with the community's storage when it is deleted.
            logger.exception("resumable_upload_drop_failed upload=%s", upload.id)
        await session.delete(upload)
        await session.commit()


def next_due(_now: Any) -> Any:
    """When the next upload expires."""
    return select(func.min(PendingUpload.expires_at))
