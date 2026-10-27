from __future__ import annotations

import asyncio
import functools
import hashlib
import io
import json
import logging
import re
import unicodedata
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import (
    Any,
    AsyncIterator,
    BinaryIO,
    Dict,
    Iterable,
    Mapping,
    Set,
    Tuple,
)
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import UploadFile

from app.core.errors import CodedError
from app.core.file_types import is_refused, spec_of, type_of_media, type_of_name
from app.core.identity_boundary import UPLOAD_PATH_SHAPE
from app.core.messages import AttachmentMessages
from app.core.image_headers import read_image_header
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db.query import ids_in
from app.services.platform import billing_changes
from app.services.storage import get_guild_storage, open_seekable

logger = logging.getLogger(__name__)

UPLOADS_URL_PREFIX = "/uploads/"

#: What the stored name of a picture pasted into markdown — a task's
#: description, a comment — starts with. The server chooses every stored name,
#: so this is how an upload says it was pasted, and only an upload that says so
#: is ever deleted because the text stopped showing it. An image copied in from
#: a file keeps its own name and is never touched.
PASTED_IMAGE_PREFIX = "pasted-"

#: What the stored name of a thumbnail the app made starts with. A thumbnail
#: is made again whenever it is wanted, so it counts toward no storage limit
#: and no backup carries it.
THUMBNAIL_PREFIX = "thumbnail-"

#: An upload's address inside markdown: ``/uploads/{community_id}/{filename}``,
#: optionally behind an origin.
_MARKDOWN_UPLOAD_URL = re.compile(rf"(?:https?://[^\s()<>]+?)?{UPLOAD_PATH_SHAPE}")

# Maximum file size for file uploads: 50 MB
MAX_FILE_SIZE = 50 * 1024 * 1024


class FileTooLargeError(Exception):
    """Raised when an uploaded file exceeds the allowed byte limit.

    Carries the limit so callers can build an accurate error response without
    re-deriving it.
    """

    def __init__(self, max_size: int) -> None:
        self.max_size = max_size
        super().__init__(f"File exceeds maximum size of {max_size} bytes")


class StorageQuotaExceededError(CodedError):
    """Raised when a write would push a guild over its ``max_storage_bytes``.

    Answered by the API wherever it is raised, because saving content can copy
    the files it shows (``claim_uploads``), and every save goes through that.
    """

    status_code = 507

    def __init__(self) -> None:
        super().__init__(AttachmentMessages.STORAGE_QUOTA_EXCEEDED)


async def read_upload_bounded(file: UploadFile, max_size: int) -> bytes:
    """Read an upload without buffering more than ``max_size`` bytes.

    Reads ``max_size + 1`` bytes so an over-limit body is detected from the
    single extra byte instead of materializing the whole payload in memory
    (which would let a large upload exhaust process memory). Returns the file
    bytes when within the limit; raises :class:`FileTooLargeError` otherwise.
    """
    contents = await file.read(max_size + 1)
    if len(contents) > max_size:
        raise FileTooLargeError(max_size)
    return contents


def compute_content_hash(data: bytes) -> str:
    """SHA-256 hex of blob bytes — recorded on the ``uploads`` row for integrity
    verification (object-store migration) and future content dedup."""
    return hashlib.sha256(data).hexdigest()


def normalize_upload_url(url: str | None) -> str | None:
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    path = url
    if url.startswith("http://") or url.startswith("https://"):
        parsed = urlparse(url)
        path = parsed.path or ""
    if not path.startswith(UPLOADS_URL_PREFIX):
        return None
    # Keep the full ``/uploads/{community_id}/{filename}`` path (only origin/query are
    # dropped): the guild segment is part of the canonical URL, so content
    # rewrites and dedup compare like-for-like. Disk ops take ``Path(url).name``,
    # which is the filename regardless of the guild segment.
    if not Path(path).name:
        return None
    return path


def delete_blobs(guild_id: int, filenames: Iterable[str]) -> None:
    """Remove these stored files from the guild's storage.

    Call it with the names a release or purge returned, after the commit that
    removed their ``uploads`` rows, so a rolled-back write leaves the file.
    """
    storage = get_guild_storage(guild_id)
    for name in set(filenames):
        storage.delete(name)


def upload_names(urls: Iterable[str | None]) -> Set[str]:
    """The stored names these URLs address."""
    return {Path(n).name for n in (normalize_upload_url(u) for u in urls) if n}


async def purge_file_uploads(session, files: Iterable[Any]) -> Set[str]:
    """Delete the uploads of files about to be hard-purged.

    A version's thumbnail backs that version alone, so it goes with it. The
    version's own file may also be shown by a page a picture was picked into,
    and it goes, like what a file shows — pictures in its body, its featured
    image — only when nothing that stays shows it too; a trashed file still
    counts, since it may be restored.

    Caller must use a session that can DELETE from ``uploads``; caller commits,
    then deletes the blobs of the stored names returned.
    """
    from sqlmodel import select

    from app.models.tenant.file import File, FileVersion

    doomed = list(files)
    if not doomed:
        return set()
    doomed_ids = {d.id for d in doomed}

    versions = (
        await session.exec(
            select(
                FileVersion.id, FileVersion.file_url, FileVersion.thumbnail_url
            ).where(FileVersion.file_id.in_(doomed_ids))
        )
    ).all()
    shown = {row.file_url for row in versions if row.file_url}
    # A small picture is its own thumbnail, so that name is the version's file.
    removed = await _drop_upload_rows(
        session,
        upload_names(row.thumbnail_url for row in versions) - upload_names(shown),
    )

    for d in doomed:
        shown |= extract_upload_urls(d.content)
        if d.featured_image_url:
            shown.add(d.featured_image_url)
    return removed | await release_uploads(
        session,
        shown,
        leaving={File: doomed_ids, FileVersion: {row.id for row in versions}},
    )


def upload_urls_in_markdown(text: str | None) -> Set[str]:
    """Every upload a markdown body shows, normalized."""
    urls: Set[str] = set()
    for match in _MARKDOWN_UPLOAD_URL.findall(text or ""):
        normalized = normalize_upload_url(match)
        if normalized:
            urls.add(normalized)
    return urls


def _is_pasted(url: str) -> bool:
    return Path(url).name.startswith(PASTED_IMAGE_PREFIX)


#: How long a pasted picture waits to be saved before the sweep takes it. The
#: page that pasted it discards it as soon as it is left without saving; this
#: is for the tab that was closed instead, and is long enough that a draft left
#: open overnight still saves with its pictures.
UNCLAIMED_PASTED_IMAGE_GRACE = timedelta(hours=24)


def _upload_columns() -> tuple[tuple[type, str], ...]:
    """Every column a stored upload can be shown from: every column somebody
    writes in, a file's featured image, and the files and thumbnails of every
    version of an uploaded file."""
    from app.db.search_index import written_columns
    from app.models.tenant.file import File, FileVersion

    return (
        *(
            (model, column)
            for model, columns in written_columns().items()
            for column in columns
        ),
        (File, "featured_image_url"),
        (FileVersion, "file_url"),
        (FileVersion, "thumbnail_url"),
    )


def _like(filename: str) -> str:
    """A LIKE pattern matching text that contains this stored name.

    Its wildcards are escaped with the default escape character: a filename
    carries ``_``. The name alone is matched — every stored name is unique — so
    an address written with or without an origin is found either way.
    """
    safe = filename.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{safe}%"


@asynccontextmanager
async def guild_wide(guild_id: int) -> AsyncIterator[Any]:
    """A system session from the guild's cohort, routed into it: every upload
    it stores, whoever can read which."""
    from app.db import cohorts
    from app.db.request_context import SystemGuild
    from app.db.session import set_rls_context

    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id))
        yield session


#: The rows a caller is taking the pictures OUT of — they no longer count as
#: showing anything. Keyed by model.
Leaving = Mapping[type, Iterable[int]]


async def _still_shown(
    session, filename: str, *, leaving: Leaving, tables: Set[str] | None = None
) -> bool:
    """Whether anything stored — archived or in the trash included — other than
    the rows ``leaving`` shows this stored file, looking only in ``tables`` when
    they are named."""
    from sqlalchemy import Text, cast

    from app.db.soft_delete_filter import select_including_deleted

    for model, column in _upload_columns():
        if tables is not None and model.__tablename__ not in tables:
            continue
        stmt = select_including_deleted(model.id).where(  # type: ignore[attr-defined]
            cast(getattr(model, column), Text).like(_like(filename))
        )
        ids = set(leaving.get(model, ()))
        if ids:
            stmt = stmt.where(~model.id.in_(ids))  # type: ignore[attr-defined]
        if (await session.exec(stmt.limit(1))).first() is not None:
            return True
    return False


async def _drop_upload_rows(session, filenames: Set[str]) -> Set[str]:
    """Delete these ``uploads`` rows of the routed guild; returns the names
    that had one."""
    from sqlalchemy import delete as sa_delete

    from app.models.tenant.upload import Upload

    if not filenames:
        return set()
    result = await session.exec(
        sa_delete(Upload)
        .where(ids_in(Upload.filename, filenames))
        # A held upload stays, whatever stops showing it (app.db.holds).
        .where(Upload.held_at.is_(None))  # type: ignore[union-attr]
        .returning(Upload.filename)
    )
    dropped = set(result.scalars().all())
    if dropped:
        billing_changes.storage_moved(session)
    return dropped


async def release_uploads(
    session, urls: Iterable[str | None], *, leaving: Leaving = {}
) -> Set[str]:
    """Delete the ``uploads`` rows of the files these URLs name that nothing
    stored shows any more.

    ``urls`` are what an edit took out, or what rows about to be purged (the
    ones in ``leaving``) show. A file goes only when no other row, archived or
    in the trash included, still shows it: a duplicated task shares its
    original's pictures, and a picture can be pasted from one body into another.

    Returns the stored names released, whose blobs the caller deletes with
    :func:`delete_blobs` once the rows are gone — after its commit, so a
    rolled-back write leaves the file.
    """
    names = {
        name
        for name in upload_names(urls)
        if not await _still_shown(session, name, leaving=leaving)
    }
    return await _drop_upload_rows(session, names)


async def release_unshown(
    guild_id: int, urls: Iterable[str | None], *, pasted_only: bool = False
) -> Set[str]:
    """Delete the ``uploads`` rows of the files these URLs name that nothing in
    the community shows, once the change that let go of them has committed.

    Asked across the whole community — archived and trashed rows included — on
    a system session from its cohort routed into it, and committed there, so
    whether a file is still shown does not depend on what the editor can see.
    ``pasted_only`` keeps to the pictures a markdown body owns (see
    :data:`PASTED_IMAGE_PREFIX`). Returns the stored names released; the caller
    deletes their blobs with :func:`delete_blobs`.
    """
    names = upload_names(u for u in urls if u and (not pasted_only or _is_pasted(u)))
    if not names:
        return set()
    try:
        async with guild_wide(guild_id) as session:
            unshown = {
                n for n in names if not await _still_shown(session, n, leaving={})
            }
            released = await _drop_upload_rows(session, unshown)
            await session.commit()
    except Exception:
        # The edit has landed; a file that could not be released stays, which
        # costs storage and nothing else.
        logger.exception("Could not release uploads in guild %s", guild_id)
        return set()
    return released


async def release_pasted_images(
    session, urls: Iterable[str], *, leaving: Leaving
) -> Set[str]:
    """:func:`release_uploads`, for the pictures pasted into a task description
    or a comment (see :data:`PASTED_IMAGE_PREFIX`) — the only uploads a markdown
    body owns."""
    return await release_uploads(
        session, [u for u in urls if _is_pasted(u)], leaving=leaving
    )


async def discard_pasted_image(session, filename: str, *, user_id: int) -> str | None:
    """Delete a picture its uploader pasted and then did not save.

    Only a pasted picture (see :data:`PASTED_IMAGE_PREFIX`), only one the
    asking person uploaded, and only while nothing saved shows it — so a page
    discarding what it pasted cannot take a picture that did get saved, or
    anybody else's. Returns the stored name when it was deleted, for the caller
    to remove the blob after its commit; ``None`` when it stays.
    """
    from sqlmodel import select

    from app.models.tenant.upload import Upload

    name = Path(filename).name
    if name != filename or not name.startswith(PASTED_IMAGE_PREFIX):
        return None
    upload = (
        await session.exec(
            select(Upload).where(Upload.filename == name, Upload.created_by == user_id)
        )
    ).first()
    if upload is None or await _still_shown(session, name, leaving={}):
        return None
    await _drop_upload_rows(session, {name})
    return name


async def release_unclaimed_pasted_images(session, *, now: datetime) -> Set[str]:
    """Delete pictures pasted longer ago than the grace period that nothing
    shows — the ones a closed tab never got to discard.

    Each pasted picture is looked at once: one that something shows is claimed
    for it (:func:`claim_shown`) and left to the edits and purges that take it
    out (:func:`release_unshown`, :func:`purge_pasted_images`).

    Runs in one routed guild with authority to delete uploads (the trash
    sweep). Returns the stored names released; the caller commits and then
    removes the blobs.
    """
    from sqlmodel import select

    from app.models.tenant.upload import Upload

    stale = await session.exec(
        select(Upload.filename)
        .where(Upload.filename.startswith(PASTED_IMAGE_PREFIX))  # type: ignore[attr-defined]
        .where(Upload.claimed_at.is_(None))
        .where(Upload.created_at < now - UNCLAIMED_PASTED_IMAGE_GRACE)
    )
    names = set(stale.all())
    if not names:
        return set()
    await claim_shown(session, names)
    unshown = await session.exec(
        select(Upload.filename).where(
            ids_in(Upload.filename, names), Upload.claimed_at.is_(None)
        )
    )
    return await _drop_upload_rows(session, set(unshown.all()))


async def purge_pasted_images(session, doomed: Iterable[Any]) -> Set[str]:
    """Delete the pictures pasted into tasks and comments about to be
    hard-purged, unless something that stays still shows them.

    Caller must use a session that can DELETE from ``uploads``; caller commits,
    then deletes the blobs of the stored names returned.
    """
    from app.models.tenant.comment import Comment
    from app.models.tenant.task import Task

    urls: Set[str] = set()
    leaving: dict[type, set[int]] = {Task: set(), Comment: set()}
    for row in doomed:
        if isinstance(row, Task):
            urls |= upload_urls_in_markdown(row.description)
            leaving[Task].add(row.id)
        elif isinstance(row, Comment):
            urls |= upload_urls_in_markdown(row.content)
            leaving[Comment].add(row.id)
    return await release_pasted_images(session, urls, leaving=leaving)


def extract_upload_urls(payload: Any) -> Set[str]:
    urls: Set[str] = set()

    def _walk(value: Any) -> None:
        if isinstance(value, str):
            normalized = normalize_upload_url(value)
            if normalized:
                urls.add(normalized)
        elif isinstance(value, dict):
            for item in value.values():
                _walk(item)
        elif isinstance(value, list):
            for item in value:
                _walk(item)

    _walk(payload)
    return urls


async def copy_uploads(
    session,
    urls: Iterable[str | None],
    *,
    guild_id: int,
    created_by: int | None,
    initiative_id: int | None,
) -> Dict[str, str]:
    """Copy the guild's stored files these URLs name into new files, kept for
    ``initiative_id`` (``None``: the whole guild), and return each source URL's
    copy. ``created_by`` None keeps each file's own uploader on its copy.

    Only files this session reads are copied — anything else stays as it was
    written. The copies count against the storage quota, checked for all of
    them before a byte is written. Caller commits.
    """
    from sqlmodel import select

    from app.models.tenant.upload import Upload

    by_name = {Path(u).name: u for u in (normalize_upload_url(u) for u in urls) if u}
    if not by_name:
        return {}
    sources = (
        await session.exec(select(Upload).where(Upload.filename.in_(by_name)))  # type: ignore[attr-defined]
    ).all()
    if not sources:
        return {}
    await enforce_storage_quota(
        session,
        guild_id=guild_id,
        incoming_bytes=sum(source.size_bytes or 0 for source in sources),
    )
    storage = get_guild_storage(guild_id)
    copies: Dict[str, str] = {}
    for source in sources:
        name = new_upload_filename(
            Path(source.filename).suffix,
            prefix=PASTED_IMAGE_PREFIX if _is_pasted(source.filename) else "",
        )
        if not await asyncio.to_thread(storage.copy, source.filename, name):
            logger.error("Failed to copy upload %s -> %s", source.filename, name)
            continue
        session.add(
            Upload(
                filename=name,
                created_by=created_by if created_by is not None else source.created_by,
                size_bytes=source.size_bytes,
                content_type=source.content_type,
                content_hash=source.content_hash,
                initiative_id=initiative_id,
                claimed_at=datetime.now(timezone.utc),
            )
        )
        copies[by_name[source.filename]] = f"{UPLOADS_URL_PREFIX}{guild_id}/{name}"
    if copies:
        billing_changes.storage_moved(session, guild_id)
    return copies


def replace_upload_urls(payload: Any, replacements: Mapping[str, str]) -> Any:
    """``payload`` with each upload address ``replacements`` names swapped for
    its replacement, wherever it is written — a value of its own or inside
    text."""
    if not replacements:
        return payload

    def _swap(match: re.Match[str]) -> str:
        return replacements.get(normalize_upload_url(match[0]) or "", match[0])

    def _walk(value: Any) -> Any:
        if isinstance(value, str):
            return _MARKDOWN_UPLOAD_URL.sub(_swap, value)
        if isinstance(value, dict):
            return {key: _walk(child) for key, child in value.items()}
        if isinstance(value, list):
            return [_walk(item) for item in value]
        return value

    return _walk(payload)


def shows_files(model: type, fields: Iterable[str]) -> bool:
    """Whether any of ``fields`` is a column ``model``'s rows can show a stored
    file from."""
    named = set(fields)
    return any(m is model and column in named for m, column in _upload_columns())


async def claim_uploads(
    session, *rows: Any, uploaded_by: Set[int] | None = None, carried: bool = False
) -> None:
    """Keep the uploads these saved rows show for the initiative each row
    belongs to — none for content of the whole guild.

    A file not yet saved into anything takes the row's initiative and is
    claimed. One already kept there is left as it is. One kept for another
    initiative, or for the whole guild where the row is in an initiative (or
    the reverse), is copied for the row's and the row rewritten to show the
    copy — on a person's session when they can read the file, or by the
    sweep, which keeps the file's uploader on the copy. The rows given
    together share one copy of a file per initiative, and an initiative's
    copies are held to the storage quota together. Only files this session
    reads are touched; anything else is left as written.

    ``uploaded_by`` keeps the claims to files those people uploaded, for a save
    made on nobody's session (a live-editing room); such a save copies nothing.

    ``carried`` says the rows bring content they already showed, as a move
    does, rather than content this save wrote.

    Flushes first; the caller commits.
    """
    from sqlalchemy import inspect, text
    from sqlalchemy import select as sa_select
    from sqlalchemy.orm.attributes import flag_modified
    from sqlmodel import select

    from app.db.plugin_rls import PLUGIN_TABLE_ACCESS
    from app.db.initiative_rls import INITIATIVE_PATHS
    from app.db.session import guild_context, install_context
    from app.models.tenant.upload import Upload
    from app.services.tenant import body_states
    from app.services.tenant.collaboration import written_into
    from app.services.tenant.collaborative_resources import YJS_STATE_COLUMN

    await session.flush()
    schema = (await session.exec(text("SELECT current_schema()"))).scalar()
    guild_id = int(schema.removeprefix("guild_"))
    own = f"{UPLOADS_URL_PREFIX}{guild_id}/"
    # Each row showing one of the guild's files: its upload columns, its
    # initiative, and the files it shows by stored name.
    showing: list[tuple[Any, list[str], int | None, Dict[str, str]]] = []
    for row in rows:
        columns = [c for model, c in _upload_columns() if type(row) is model]
        unloaded = [c for c in columns if c in inspect(row).unloaded]
        if unloaded:
            await session.refresh(row, unloaded)
        shown = {
            Path(url).name: url
            for column in columns
            for value in (getattr(row, column),)
            for url in upload_urls_in_markdown(
                value if value is None or isinstance(value, str) else json.dumps(value)
            )
            if url.startswith(own)
        }
        if not shown:
            continue
        relation = type(row).__table__
        initiative_id = (
            await session.exec(
                sa_select(
                    text(INITIATIVE_PATHS[relation.name].initiative_expr(relation.name))
                )
                .select_from(relation)
                .where(relation.c["id"] == row.id)
            )
        ).scalar()
        showing.append((row, columns, initiative_id, shown))
    if not showing:
        return

    uploads = {
        upload.filename: upload
        for upload in await session.exec(
            select(Upload)
            .where(ids_in(Upload.filename, {n for *_, s in showing for n in s}))
            .execution_options(populate_existing=True)
        )
    }
    now = datetime.now(timezone.utc)
    wanted: Dict[int | None, Set[str]] = {}
    for _row, _columns, initiative_id, shown in showing:
        for name, url in shown.items():
            upload = uploads.get(name)
            if upload is None:
                continue
            if upload.claimed_at is None:
                if uploaded_by is None or upload.created_by in uploaded_by:
                    upload.initiative_id = initiative_id
                    upload.claimed_at = now
            elif upload.initiative_id != initiative_id:
                wanted.setdefault(initiative_id, set()).add(url)
    await session.flush()

    person = guild_context(session)
    if not wanted or (person is None and uploaded_by is not None):
        return
    if install_context(session) is not None:
        # An installed plug-in reaches a file through the content showing it, so
        # it copies one only when content it reads shows it: other content,
        # or rows it carried here.
        saving: Dict[type, list[int]] = {}
        for row, *_ in showing:
            saving.setdefault(type(row), []).append(row.id)
        for initiative_id, urls in wanted.items():
            wanted[initiative_id] = {
                url
                for url in urls
                if await _still_shown(
                    session,
                    Path(url).name,
                    leaving={} if carried else saving,
                    tables=set(PLUGIN_TABLE_ACCESS),
                )
            }
    copies = {
        initiative_id: await copy_uploads(
            session,
            urls,
            guild_id=guild_id,
            created_by=person.user_id if person is not None else None,
            initiative_id=initiative_id,
        )
        for initiative_id, urls in wanted.items()
    }
    for row, columns, initiative_id, _shown in showing:
        for column in columns:
            value = replace_upload_urls(
                getattr(row, column), copies.get(initiative_id, {})
            )
            if value != getattr(row, column):
                setattr(row, column, value)
                flag_modified(row, column)
                if column == "content" and YJS_STATE_COLUMN in type(row).__table__.c:
                    # The editor loads its stored state before the column, so
                    # the rewrite is written into it: a live session merges it
                    # in, and the next one opens on it.
                    await session.refresh(row, [YJS_STATE_COLUMN])
                    body = body_states.for_row(row)
                    setattr(
                        row,
                        YJS_STATE_COLUMN,
                        await written_into(body, getattr(row, YJS_STATE_COLUMN), value)
                        if body is not None
                        else None,
                    )
    await session.flush()


async def claim_shown(session, filenames: Set[str]) -> None:
    """:func:`claim_uploads` for every stored row that shows these files —
    archived or in the trash included — oldest first."""
    from sqlalchemy import ARRAY, Text, any_, bindparam, cast

    from app.db.soft_delete_filter import select_including_deleted

    if not filenames:
        return
    patterns = bindparam(None, [_like(n) for n in filenames], type_=ARRAY(Text()))
    found: dict[tuple[type, int], Any] = {}
    for model, column in _upload_columns():
        rows = await session.exec(
            select_including_deleted(model).where(
                cast(getattr(model, column), Text).like(any_(patterns))
            )
        )
        for row in rows.all():
            found[(model, row.id)] = row
    await claim_uploads(
        session, *sorted(found.values(), key=lambda row: row.created_at)
    )


async def purge_initiative_uploads(session, initiative_ids: Iterable[int]) -> Set[str]:
    """Delete the ``uploads`` rows kept for initiatives about to be hard-purged;
    returns their stored names, whose blobs the caller deletes after its
    commit."""
    from sqlalchemy import delete as sa_delete

    from app.models.tenant.upload import Upload

    result = await session.exec(
        sa_delete(Upload)
        .where(ids_in(Upload.initiative_id, initiative_ids))
        .where(Upload.held_at.is_(None))  # type: ignore[union-attr]
        .returning(Upload.filename)
    )
    dropped = set(result.scalars().all())
    if dropped:
        billing_changes.storage_moved(session)
    return dropped


#: What the bytes of a text file say whatever kind of text it is; its name says
#: which (Markdown, HTML, plain).
_PLAIN_TEXT = frozenset({"text/plain", "text/x-markdown"})
#: Office formats whose bytes are a zip package; the name says which.
_OFFICE_PACKAGES = frozenset(
    {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
)
#: Older Office formats, whose bytes are a compound-document container.
_OFFICE_CONTAINERS = frozenset(
    {"application/msword", "application/vnd.ms-excel", "application/vnd.ms-powerpoint"}
)
_CONTAINER_TYPES = frozenset({"application/CDFV2", "application/x-ole-storage"})


class RefusedFileTypeError(ValueError):
    """A program, which no upload may be (``file_types.is_refused``)."""


def detect_mime_type(content: bytes) -> str | None:
    """The type ``content``'s bytes say it is, or ``None`` where they can't be
    read."""
    try:
        import magic

        return magic.from_buffer(content, mime=True) or None
    except Exception:
        logger.exception("upload_type_detection_failed")
        return None


def _zip_names(source: BinaryIO) -> list[str]:
    try:
        with zipfile.ZipFile(source) as package:
            return package.namelist()
    except zipfile.BadZipFile:
        return []


def _is_app_package(source: BinaryIO) -> bool:
    """Whether a zip is a Java, Android or iOS app."""
    return any(
        name in ("META-INF/MANIFEST.MF", "AndroidManifest.xml")
        or (name.startswith("Payload/") and ".app/" in name)
        for name in _zip_names(source)
    )


def _name_settles(detected: str, named: str, source: BinaryIO) -> bool:
    """Whether a file's name may make it ``named`` where its bytes said
    ``detected``: only where the bytes say no more than the family."""
    if detected in _PLAIN_TEXT:
        return named.startswith("text/") or named == "application/json"
    if named in _OFFICE_PACKAGES:
        return "[Content_Types].xml" in _zip_names(source)
    return named in _OFFICE_CONTAINERS and detected in _CONTAINER_TYPES


def validate_file(content: bytes, filename: str | None) -> Tuple[str, str]:
    """The type and stored extension of an uploaded file, read from its bytes.

    Any format is taken but a program. The name only narrows what the bytes
    allow (:func:`_name_settles`); the type the client sent is never asked.
    Bytes nothing can read are ``application/octet-stream``. Raises
    :class:`RefusedFileTypeError` for a program, and ``ValueError`` for a file
    that is empty or too large.
    """
    if len(content) > MAX_FILE_SIZE:
        raise ValueError(
            f"File exceeds maximum size of {MAX_FILE_SIZE // (1024 * 1024)} MB"
        )
    if not content:
        raise ValueError("Uploaded file is empty")
    return _type_of(detect_mime_type(content), io.BytesIO(content), filename)


@functools.cache
def _head_bytes() -> int:
    """How much of a file the type library reads to name its type."""
    import magic

    return magic.Magic(mime=True).getparam(magic.MAGIC_PARAM_BYTES_MAX)


def validate_stored(guild_id: int, key: str, size: int, filename: str | None) -> str:
    """The type of a file already in the guild's storage under ``key``, a
    finished resumable upload, read as :func:`validate_file` reads one: from
    its first bytes, and from a zip's own list of what it holds, without
    fetching the rest. Raises as :func:`validate_file` does."""
    if not size:
        raise ValueError("Uploaded file is empty")
    source = open_seekable(get_guild_storage(guild_id), key, size)
    if source is None:
        raise ValueError("Uploaded file is missing")
    with source:
        detected = detect_mime_type(source.read(_head_bytes()))
        return _type_of(detected, source, filename)[0]


def _type_of(
    detected: str | None, source: BinaryIO, filename: str | None
) -> Tuple[str, str]:
    """The type and stored extension of a file whose bytes said ``detected``,
    with ``source`` to read a zip's list from."""
    # Read as the name the file is kept and downloaded under.
    filename = display_filename(filename)
    detected = detected or "application/octet-stream"
    if is_refused(detected, filename) or (
        detected == "application/zip" and _is_app_package(source)
    ):
        raise RefusedFileTypeError(f"Refused file type: {detected}")
    named_type = type_of_name(filename)
    mime = detected
    if named_type is not None and named_type is not type_of_media(detected):
        named = spec_of(named_type).media_types[0]
        if _name_settles(detected, named, source):
            mime = named
    extensions = spec_of(type_of_media(mime)).extensions
    suffix = Path(filename).suffix.lower() if filename else ""
    return mime, suffix if suffix in extensions else next(iter(extensions), "")


#: The longest name a file keeps; most filesystems stop at 255.
MAX_DISPLAY_NAME = 255


def display_filename(name: str | None) -> str | None:
    """``name`` as a file shows it and downloads under it: without control or
    formatting characters, which never belong in a name, trimmed of the
    spaces and dots a desktop drops, and cut to 255 characters, keeping its
    extension."""
    if name is None:
        return None
    kept = "".join(c for c in name if unicodedata.category(c) not in ("Cc", "Cf"))
    kept = kept.strip().rstrip(". ")
    if len(kept) > MAX_DISPLAY_NAME:
        suffix = Path(kept).suffix[:16]
        kept = kept[: MAX_DISPLAY_NAME - len(suffix)] + suffix
    return kept or None


def new_upload_filename(extension: str, *, prefix: str = "") -> str:
    """A fresh stored name: ``prefix``, a random hex id, then ``extension``
    (with or without its dot; empty for none)."""
    if extension and not extension.startswith("."):
        extension = f".{extension}"
    return f"{prefix}{uuid4().hex}{extension}"


async def store_upload(
    session,
    *,
    guild_id: int,
    filename: str,
    data: bytes,
    content_type: str | None,
    created_by: int | None,
    initiative_id: int | None = None,
) -> str:
    """Write ``data`` to the guild's storage as ``filename`` and record it in
    ``uploads``. Returns the served URL, ``/uploads/{community_id}/{filename}``.

    Every upload a person or an import brings into a guild is stored here.
    The ``uploads`` row is what the serve route requires and what the storage
    quota is summed from; the caller owns naming, validation, the quota check
    and the commit. ``initiative_id`` is the initiative a file written together
    with what shows it is kept for; without it the file waits to be claimed
    (:func:`claim_uploads`).
    """
    await asyncio.to_thread(
        get_guild_storage(guild_id).write,
        filename,
        data,
        content_type=content_type or "application/octet-stream",
    )
    return record_upload(
        session,
        guild_id=guild_id,
        filename=filename,
        size=len(data),
        content_type=content_type,
        content_hash=compute_content_hash(data),
        created_by=created_by,
        initiative_id=initiative_id,
    )


def record_upload(
    session,
    *,
    guild_id: int,
    filename: str,
    size: int,
    content_type: str | None,
    content_hash: str | None,
    created_by: int | None,
    initiative_id: int | None,
) -> str:
    """Record what is already in the guild's storage as ``filename`` in
    ``uploads``, as :func:`store_upload` records what it writes, and return
    its served URL. A finished resumable upload is recorded where it was
    staged, without its hash, which would mean reading it all again."""
    from app.models.tenant.upload import Upload

    session.add(
        Upload(
            filename=filename,
            created_by=created_by,
            size_bytes=size,
            content_type=content_type,
            content_hash=content_hash,
            initiative_id=initiative_id,
            claimed_at=None if initiative_id is None else datetime.now(timezone.utc),
        )
    )
    # What billing is told the community stores, once this commits.
    billing_changes.storage_moved(session, guild_id)
    return f"{UPLOADS_URL_PREFIX}{guild_id}/{filename}"


async def get_guild_storage_usage(guild_id: int) -> int:
    """Total stored blob bytes for the guild — ``SUM(uploads.size_bytes)`` over
    every upload it stores but the thumbnails the app made
    (:data:`THUMBNAIL_PREFIX`), plus the declared length of every file still
    arriving to be kept (``pending_uploads`` of a stored purpose), read on
    :func:`guild_wide`."""
    from sqlalchemy import func
    from sqlmodel import col, select

    from app.models.tenant.pending_upload import PendingUpload
    from app.models.tenant.upload import Upload
    from app.services.resumable import STORED_PURPOSES

    stored = (
        select(func.coalesce(func.sum(Upload.size_bytes), 0))
        .where(~col(Upload.filename).startswith(THUMBNAIL_PREFIX))
        .scalar_subquery()
    )
    arriving = (
        select(func.coalesce(func.sum(PendingUpload.length), 0))
        .where(col(PendingUpload.purpose).in_(STORED_PURPOSES))
        .scalar_subquery()
    )
    async with guild_wide(guild_id) as session:
        return int((await session.exec(select(stored + arriving))).one())


async def _storage_limit(guild_id: int) -> int | None:
    """The guild's ``max_storage_bytes``, ``None`` for no limit. A setting of
    the community rather than of whoever is writing, so it is read on
    :func:`guild_wide`, as the usage it is compared with is."""
    from sqlmodel import select

    from app.models.platform.guild_administration import GuildAdministration

    async with guild_wide(guild_id) as session:
        return (
            await session.exec(
                select(GuildAdministration.max_storage_bytes).where(
                    GuildAdministration.guild_id == guild_id
                )
            )
        ).one_or_none()


async def storage_left(guild_id: int) -> int | None:
    """What the guild's ``max_storage_bytes`` still allows, or ``None`` when it
    has no limit. A reading for planning, not a reservation: the write that
    follows still goes through :func:`enforce_storage_quota`."""
    limit = await _storage_limit(guild_id)
    if limit is None:
        return None
    return max(0, limit - await get_guild_storage_usage(guild_id))


async def enforce_storage_quota(session, *, guild_id: int, incoming_bytes: int) -> None:
    """Reject an upload that would exceed the guild's ``max_storage_bytes``.

    NULL / absent limit means unlimited (the default), so this is a no-op until a
    quota is set on the guild. The limit is :func:`_storage_limit` and the
    usage :func:`get_guild_storage_usage`, every upload the guild stores, both
    read for the community whoever is writing.

    Must be called within the SAME transaction that then inserts the ``uploads``
    row and commits. When a limit is set, it takes a transaction-scoped advisory
    lock keyed on the guild before reading usage, so the check and the insert that
    follows cannot interleave with a concurrent upload — without it, two uploads
    to a near-full guild could each read the pre-upload usage and collectively
    exceed the limit (a TOCTOU race). The lock releases on commit/rollback;
    uploads to other guilds are unaffected.
    """
    limit = await _storage_limit(guild_id)
    if limit is None:
        return
    # Serialize concurrent uploads for this guild for the remainder of the
    # transaction so the usage check + the row insert that follows are atomic
    # w.r.t. other uploads to the same guild.
    await advisory_lock(session, LockNamespace.STORAGE_QUOTA, guild_id)
    usage = await get_guild_storage_usage(guild_id)
    if usage + incoming_bytes > limit:
        raise StorageQuotaExceededError()


#: How far into a file the SVG root element may sit — past a byte-order mark, an
#: XML declaration, comments and a doctype. Generous for an editor's preamble,
#: bounded so the check stays a slice of the head rather than a scan of 10 MB.
_SVG_HEAD_BYTES = 1024

#: What may follow the root element's name: whitespace before an attribute, or
#: the end of an empty or opening tag. Anything else is a different element
#: whose name happens to start with the same three letters.
_ROOT_NAME_ENDS = (b" ", b"\t", b"\r", b"\n", b">", b"/")


def _past_the_prolog(head: bytes) -> bytes:
    """Drop what an XML file may carry before its root element — a
    byte-order mark, whitespace, the declaration, comments and a doctype —
    and return what is left of ``head``."""
    head = head.lstrip(b"\xef\xbb\xbf").lstrip()
    while True:
        if head.startswith(b"<?"):
            end, skip = head.find(b"?>"), 2
        elif head.startswith(b"<!--"):
            end, skip = head.find(b"-->"), 3
        elif head.startswith(b"<!"):
            end, skip = head.find(b">"), 1
        else:
            return head
        if end < 0:
            # The construct runs past the slice being read; nothing to return.
            return b""
        head = head[end + skip :].lstrip()


def _opens_an_svg(contents: bytes) -> bool:
    """Whether the file's root element is ``<svg>``.

    Raster signatures are checked before this, so the question here is only
    whether markup is an SVG rather than something else — and the answer is
    read from a bounded slice of the head, not from a parse of the body.
    """
    head = _past_the_prolog(contents[:_SVG_HEAD_BYTES])
    if head[:1] != b"<":
        return False
    name = head[1:5].lower()
    return name[:3] == b"svg" and name[3:4] in _ROOT_NAME_ENDS


#: The largest document image.
MAX_IMAGE_BYTES = 10 * 1024 * 1024

#: What a document image may be, and the suffix its stored copy takes. The four
#: raster formats ``read_image_header`` identifies, plus the three
#: :func:`detect_document_image_type` allows on top of them: TIFF and ICO, which
#: it does not read, and SVG, which is markup rather than a raster and so is
#: served as a download.
IMAGE_SUFFIXES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/tiff": ".tiff",
    "image/x-icon": ".ico",
    "image/svg+xml": ".svg",
}


def detect_document_image_type(contents: bytes) -> str | None:
    """Identify a document image from its bytes, or ``None`` if it is not one.

    The client's ``Content-Type`` and filename are not consulted — the rule the
    avatar, guild-image and announcement paths already follow, and a
    mislabelled PNG is still a PNG. What comes back is what the stored row, the
    stored name and the served response all describe the file as.
    """
    header = read_image_header(contents)
    if header is not None:
        return header.content_type
    if contents[:4] in (b"II\x2a\x00", b"MM\x00\x2a"):
        return "image/tiff"
    if contents[:4] == b"\x00\x00\x01\x00":
        return "image/x-icon"
    if _opens_an_svg(contents):
        return "image/svg+xml"
    return None
