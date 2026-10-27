"""A file kept as numbered versions: an uploaded file's, a library picture's.

The parent row names the version it shows (``current_version_id``) and the
version rows are its history. Both tools take the same steps through here:
number a new version and make it current, copy one for a duplicate, delete
one and point back at the newest left, and take back the stored files a
failed or finished write leaves behind. Every version a row is given has a
type its tool accepts, since that type decides how the file is shown.

A parent's versions are read off its ``versions`` relationship, so the steps
work for any model that keeps one.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, TypeVar

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import Column, func
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import DataError, IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.file_types import is_refused, spec_of, type_of_media
from app.core.messages import CommonMessages
from app.schemas.tenant.tool import from_row
from app.services.tenant import attachments as attachments_service

logger = logging.getLogger(__name__)

ReadT = TypeVar("ReadT", bound=BaseModel)

#: Which commit failures prove nothing was written.
#:
#: A constraint the server rejected is definitive: the transaction is gone,
#: and the blobs written for it are bytes nothing will ever reference. A lost
#: connection is not — Postgres may have committed and failed to say so — and
#: the two must not be treated alike, because they fail in opposite
#: directions. A blob left behind is waste somebody can sweep up; a blob
#: deleted out from under a committed row is a file that is broken forever.
_DEFINITIVELY_NOT_COMMITTED = (IntegrityError, DataError)


def _history(parent: Any) -> tuple[type, Column]:
    """The version model ``parent`` keeps, and its column naming the parent."""
    relationship = sa_inspect(type(parent)).relationships["versions"]
    (column,) = relationship.remote_side
    return relationship.mapper.class_, column


def _stored(version: Any) -> list[str | None]:
    """The stored files a version names: its file, and a picture's thumbnail."""
    return [version.file_url, getattr(version, "thumbnail_url", None)]


def _may_hold(model: type, content_type: str | None) -> bool:
    """Whether a ``model`` row's file may be of ``content_type``: what an
    upload of one accepts. A library item holds a picture; a file holds
    anything but a program."""
    from app.models.tenant.library import LibraryItem
    from app.services.tenant.libraries import PICTURE_EXTENSIONS

    if model is LibraryItem:
        return content_type in PICTURE_EXTENSIONS
    return content_type is not None and not is_refused(content_type, None)


def file_type(model: type, data: bytes, *, filename: str | None) -> str | None:
    """The type ``data`` takes as a ``model`` row's file, read from its bytes
    by the rule an upload of one follows (``filename`` narrows it), or
    ``None`` where it is not a file the row may hold."""
    from app.models.tenant.library import LibraryItem
    from app.services.tenant import libraries

    try:
        if model is LibraryItem:
            return libraries.validate_image(data)[0].content_type
        return attachments_service.validate_file(data, filename)[0]
    except ValueError:
        return None


async def stored_file_type(
    model: type,
    guild_id: int,
    key: str,
    *,
    filename: str | None = None,
) -> str | None:
    """:func:`file_type` for a file already stored in the community under
    ``key``, or ``None`` where nothing is stored there."""
    from app.services.import_engine.engine import read_payload

    data = await asyncio.to_thread(read_payload, guild_id, key)
    if data is None:
        return None
    return file_type(model, data, filename=filename)


def _make_current(parent: Any, version: Any) -> None:
    """Make ``version`` the one ``parent`` shows. An uploaded file's type is
    its current version's."""
    from app.models.tenant.file import File

    parent.current_version = version
    parent.updated_at = datetime.now(timezone.utc)
    if isinstance(parent, File):
        parent.file_type = type_of_media(version.file_content_type)


def _new_version(session: AsyncSession, parent: Any, fields: dict[str, Any]) -> Any:
    """Add a version of ``parent``'s file and make it current. Its type is one
    ``parent`` may show; anything else raises ``ValueError``. A picture's
    version waits for the ``thumbnails`` sweep to draw it smaller."""
    from app.models.tenant.file import File

    content_type = fields.get("file_content_type")
    if not _may_hold(type(parent), content_type):
        raise ValueError(f"Unsupported file type: {content_type}")
    if (
        isinstance(parent, File)
        and fields.get("thumbnail_url") is None
        and spec_of(type_of_media(content_type)).picture_format
    ):
        fields["thumbnail_state"] = "pending"
    model, _ = _history(parent)
    if "original_filename" in fields:
        fields["original_filename"] = attachments_service.display_filename(
            fields["original_filename"]
        )
    version = model(**fields)
    session.add(version)
    _make_current(parent, version)
    return version


async def versions_newest_first(session: AsyncSession, parent: Any) -> list[Any]:
    model, column = _history(parent)
    result = await session.exec(
        select(model).where(column == parent.id).order_by(model.version_number.desc())
    )
    return list(result.all())


async def add_version(session: AsyncSession, parent: Any, **fields: Any) -> Any:
    """A new version of ``parent``'s file, numbered after its last and made
    current. ``fields`` are the version's columns: its file, its type and who
    made it."""
    model, column = _history(parent)
    last = await session.scalar(
        select(func.max(model.version_number)).where(column == parent.id)
    )
    number = (last or 0) + 1
    return _new_version(
        session, parent, {**fields, column.key: parent.id, "version_number": number}
    )


def copy_version(session: AsyncSession, version: Any, copy: Any, **values: Any) -> Any:
    """Version 1 of ``copy``, carrying ``version``'s file, made current.
    ``values`` set what differs from it: the copy's author, a copied file. A
    file version's thumbnail is its own, so the copy's is drawn again."""
    from app.models.tenant.file import FileVersion

    model, column = _history(copy)
    left = {"version_number", "created_at"}
    if model is FileVersion:
        left |= {"thumbnail_url", "thumbnail_state"}
    carried = {
        c.name: getattr(version, c.name)
        for c in model.__table__.columns
        if not (c.primary_key or c.foreign_keys) and c.name not in left
    }
    return _new_version(
        session,
        copy,
        {**carried, **values, column.key: copy.id, "version_number": 1},
    )


def discard_orphans(
    guild_id: int, urls: list[str | None], failure: BaseException
) -> None:
    """Take back blobs a failed commit left behind — but only where the
    failure proves they are orphans. Anything ambiguous keeps its bytes and
    says so, so the waste is findable rather than the file missing."""
    kept = [url for url in urls if url]
    if not kept:
        return
    if isinstance(failure, _DEFINITIVELY_NOT_COMMITTED):
        attachments_service.delete_blobs(
            guild_id, attachments_service.upload_names(kept)
        )
        return
    logger.warning(
        "Left %d uploaded blob(s) in place after an inconclusive commit "
        "failure (%s); they are orphaned only if the transaction did not "
        "land: %s",
        len(kept),
        type(failure).__name__,
        ", ".join(kept),
    )


async def commit_version(
    session: AsyncSession, guild_id: int, version: Any, *, conflict: bool = False
) -> None:
    """Commit the write that added ``version``, whose files are already
    stored. When the commit fails its files are taken back (see
    :func:`discard_orphans`); with ``conflict``, a version number another
    upload took first is answered 409."""
    urls = _stored(version)
    try:
        await session.commit()
    except Exception as failed:
        await session.rollback()
        discard_orphans(guild_id, urls, failed)
        if conflict and isinstance(failed, IntegrityError):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=CommonMessages.VERSION_CONFLICT,
            ) from failed
        raise


async def delete_version(session: AsyncSession, parent: Any, version_id: int) -> Any:
    """Delete one of ``parent``'s versions and return it; the caller commits,
    then calls :func:`release_files`. Deleting the current version makes the
    newest one left current. The last version is kept."""
    model = type(parent)
    # One deletion at a time per parent, read fresh once it holds the lock, so
    # two deletions cannot each take one of its last two versions.
    await session.exec(
        select(model)
        .where(model.id == parent.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    versions = await versions_newest_first(session, parent)
    if len(versions) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=CommonMessages.CANNOT_DELETE_LAST_VERSION,
        )
    target = next((v for v in versions if v.id == version_id), None)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CommonMessages.VERSION_NOT_FOUND,
        )
    if parent.current_version_id == target.id:
        _make_current(parent, next(v for v in versions if v is not target))
        # The parent points elsewhere before the version it showed goes.
        await session.flush()
    await session.delete(target)
    return target


async def release_files(guild_id: int, version: Any) -> None:
    """Delete a deleted version's stored files, once that has committed and
    where nothing else shows them."""
    released = await attachments_service.release_unshown(guild_id, _stored(version))
    attachments_service.delete_blobs(guild_id, released)


def read(schema: type[ReadT], version: Any, parent: Any) -> ReadT:
    """``version`` in ``schema``, saying whether ``parent`` shows it."""
    current = version.id == parent.current_version_id
    return from_row(schema, version, is_current=current)
