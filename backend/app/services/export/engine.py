"""ExportEngine — the single shared dispatcher every export endpoint feeds.

One engine, many sources, many formats: a thin per-resource adapter queries
the data under the caller's RLS session and shapes it into a backend-agnostic
``RenderRequest``; the engine picks inline-vs-job delivery, invokes the
configured ``RenderBackend``, and confines all storage access. The engine
never makes an authorization decision — RLS already gated the rows when the
adapter queried, and the download endpoint re-gates on the DataJob row.
"""

from __future__ import annotations

import asyncio
import tempfile
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.errors import CodedError
from app.core.user_display import name_here
from app.core.user_input_validators import resolve_zone
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.models.platform.user import User
from app.models.tenant.data_job import DataJob, DataJobDirection, DataJobStatus
from app.services.data_jobs import while_beating
from app.services.export import limits as export_limits
from app.services.export.contract import (
    RenderBackend,
    RenderedArtifact,
    RenderItem,
    RenderRequest,
)
from app.services.export.local_backend import LocalRenderBackend
from app.services.import_engine.atlassian import HEARTBEAT_SECONDS
from app.services.storage import (
    ReadableBlob,
    StorageBackend,
    blob_pieces,
    get_guild_storage,
)

#: Called once per rendered artifact, so a job can show it is still going.
Heartbeat = Callable[[], Awaitable[None]]


async def _no_heartbeat() -> None:
    return None


class SourceAdapter(Protocol):
    """A per-resource export source. ``count`` is the cheap pre-render signal
    for inline-vs-job selection and the EXPORT_MAX_ROWS bound; ``build`` runs
    the real query (under the caller's RLS session — that query IS the
    authorization) and shapes the data payload."""

    source: str
    template_id: str

    @property
    def formats(self) -> tuple[str, ...]: ...

    async def count(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> int: ...

    async def build(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> RenderRequest: ...


class ExportError(CodedError):
    """Engine-level failure with a machine-readable code (``messages.py``
    constant). The API answers it with its status; the worker records the
    code on the failed job row."""


@dataclass(frozen=True)
class InlineExport:
    """A small export rendered in-request. Deliberately persists no job row:
    an inline export is a formatted read, same surface as the list endpoint."""

    filename: str
    content_type: str
    #: The bytes, or a stored file or an archive on disk for the response to
    #: stream.
    content: bytes | ReadableBlob
    #: An archive written for this response, removed once it is sent.
    temporary: Path | None = None


def get_backend() -> RenderBackend:
    return LocalRenderBackend()


def get_adapter(source: str, format: str) -> SourceAdapter:
    """Resolve a source×format combo against the registry, so unsupported
    combinations are rejected centrally."""
    from app.core.messages import ExportMessages
    from app.services.export.adapters import ADAPTERS

    adapter = ADAPTERS.get(source)
    if adapter is None:
        raise ExportError(ExportMessages.EXPORT_UNKNOWN_SOURCE, status_code=404)
    if format not in adapter.formats:
        raise ExportError(ExportMessages.EXPORT_INVALID_FORMAT)
    return adapter


async def count_within_bound(
    session: AsyncSession,
    adapter: SourceAdapter,
    *,
    user: User,
    guild_id: int,
    params: dict[str, Any],
    format: str,
) -> int:
    """How many rows ``params`` selects, refused past the source's bound.

    Aggregate sources (whole-initiative/guild) declare their own ceiling — a
    guild dump legitimately exceeds the per-report bound."""
    from app.core.messages import ExportMessages

    row_count = await adapter.count(
        session, user=user, guild_id=guild_id, params=params, format=format
    )
    max_rows = getattr(adapter, "max_rows", None) or export_limits.EXPORT_MAX_ROWS
    if row_count > max_rows:
        raise ExportError(ExportMessages.EXPORT_TOO_LARGE)
    return row_count


async def start_export(
    session: AsyncSession,
    *,
    user: User,
    guild_id: int,
    source: str,
    format: str,
    params: dict[str, Any],
    allow_job: bool,
) -> InlineExport | DataJob:
    """The shared create path: count under RLS, bound, then auto-select
    delivery — render inline at/under EXPORT_INLINE_MAX_ROWS, else persist a
    queued DataJob (the filter selector only, never content) for the worker,
    which re-runs the query under the creator's RLS session at render time.

    ``allow_job`` is the caller's write-ability: a read-only actor (guild in
    read_only lifecycle, or a non-break-glass PAM grantee, who must not author
    rows) still gets inline export but cannot enqueue a job.
    """
    from app.core.messages import ExportMessages

    adapter = get_adapter(source, format)
    row_count = await count_within_bound(
        session, adapter, user=user, guild_id=guild_id, params=params, format=format
    )

    # Aggregate sources always run as a job: their build spans many entities
    # (and possibly upload blobs), and the worker's fresh creator-routed
    # session is where the mid-build access refresh is safe.
    always_job = getattr(adapter, "always_job", False)
    if not always_job and row_count <= export_limits.EXPORT_INLINE_MAX_ROWS:
        from app.services.export.branding import apply_brand
        from app.services.export.stamp import stamp_export

        request = await adapter.build(
            session, user=user, guild_id=guild_id, params=params, format=format
        )
        request = await apply_brand(request, session)
        request = stamp_export(request, await name_here(session, user))
        stem = _bundle_stem(source, params.get("tz"))
        force_zip = getattr(adapter, "force_zip", False)
        if any(_is_stored(item, request) for item in request.batch):
            return await _inline_with_stored(request, stem=stem, force_zip=force_zip)
        artifacts = await get_backend().render(request)
        artifact = await asyncio.to_thread(
            _bundle, artifacts, format=format, stem=stem, force_zip=force_zip
        )
        return InlineExport(
            filename=artifact.filename or f"{artifact.key}.{format}",
            content_type=artifact.content_type,
            content=artifact.content,
        )

    if not allow_job:
        raise ExportError(ExportMessages.EXPORT_WRITE_REQUIRED, status_code=403)

    # Serialize count+insert per user so concurrent requests can't race past
    # the cap. Transaction-scoped advisory lock: released at the commit below.
    await advisory_lock(session, LockNamespace.EXPORT_CAP, user.id)
    active = (
        await session.exec(
            select(func.count())
            .select_from(DataJob)
            .where(
                DataJob.direction == DataJobDirection.export,
                DataJob.created_by == user.id,
                col(DataJob.status).in_((DataJobStatus.queued, DataJobStatus.running)),
            )
        )
    ).one()
    if active >= export_limits.EXPORT_MAX_ACTIVE_JOBS_PER_USER:
        raise ExportError(ExportMessages.EXPORT_JOB_LIMIT_REACHED, status_code=429)

    job = DataJob(
        direction=DataJobDirection.export,
        created_by=user.id,
        source=source,
        template_id=adapter.template_id,
        format=format,
        params=params,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def _inline_with_stored(
    request: RenderRequest, *, stem: str, force_zip: bool
) -> InlineExport:
    """An inline export that carries stored files, for the response to
    stream: one file on its own as itself, read from storage, anything else
    as an archive written to disk (:func:`_write_archive`)."""
    if len(request.batch) == 1 and not force_zip:
        (item,) = request.batch
        blob = await asyncio.to_thread(
            get_guild_storage(request.guild_id).open_readable,
            str(item.data["storage_key"]),
        )
        if blob is None:
            raise FileNotFoundError(item.data["storage_key"])
        return InlineExport(
            filename=_stored_name(item, request),
            content_type=str(item.data.get("content_type") or "")
            or blob.content_type
            or "application/octet-stream",
            content=blob,
        )
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as handle:
        path = Path(handle.name)
    try:
        await _write_archive(request, path, _no_heartbeat)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return InlineExport(
        filename=f"{stem}.zip",
        content_type="application/zip",
        content=ReadableBlob(path=path),
        temporary=path,
    )


@dataclass(frozen=True)
class ArtifactLocation:
    """Where a finished job's bytes ended up. Exactly one field is set.

    ``artifact_ref`` means the app holds it and will serve it.
    ``destination_ref`` means it was written to the operator's destination and
    the app neither holds nor serves it — see ``export.delivery``.
    """

    artifact_ref: str | None = None
    destination_ref: str | None = None


async def render_to_storage(
    request: RenderRequest,
    *,
    job_id: int,
    source: str,
    tz: str | None = None,
    heartbeat: Heartbeat | None = None,
) -> ArtifactLocation:
    """Render a job's request and put the artifact where it belongs: behind
    the guild's storage backend for the app to serve, or — for an archive past
    the download bound — in the operator's destination.

    ``heartbeat`` is awaited after each artifact is rendered. Compressing,
    writing and delivering run in threads, off the event loop.

    Idempotent by job id: a re-render overwrites the same key or the same
    destination filename."""
    from app.services.export.adapters import ADAPTERS

    beat = heartbeat or _no_heartbeat
    stem = _bundle_stem(source, tz)
    if getattr(ADAPTERS.get(source), "force_zip", False) or len(request.batch) > 1:
        # An archive assembles on disk: a whole community's, or a selection
        # of files, is not something to hold in memory twice (once as
        # rendered artifacts, once as the zip) just to hand it to storage.
        return await _stream_zip_to_storage(
            request,
            job_id=job_id,
            stem=stem,
            guild_id=request.guild_id,
            heartbeat=beat,
        )

    if request.batch and _is_stored(request.batch[0], request):
        # One stored file going out unconverted is stored again under the
        # job's key, named as below.
        item = request.batch[0]
        key = f"exports/{job_id}-{_stored_name(item, request)}"
        await while_beating(
            asyncio.to_thread(
                _store_again,
                get_guild_storage(request.guild_id),
                str(item.data["storage_key"]),
                key,
                str(item.data.get("content_type") or "") or None,
            ),
            beat,
            every=HEARTBEAT_SECONDS,
            finish=True,
        )
        await beat()
        return ArtifactLocation(artifact_ref=key)

    artifacts: list[RenderedArtifact] = []
    async for rendered in render_artifacts(request):
        artifacts.append(rendered)
        await beat()
    artifact = await asyncio.to_thread(
        _bundle,
        artifacts,
        format=request.format,
        stem=stem,
        force_zip=False,
    )
    # The job id must live in the storage BASENAME, not a directory: both
    # backends flatten a key to Path(key).name (a path-traversal guard), so a
    # nested `exports/{job}/name` would drop the job id and two same-named
    # passthroughs (two members' "report.pdf") would collide. Prefix the id
    # into the name instead; the download endpoint strips `{job_id}-` back off
    # to recover the original filename for Content-Disposition.
    if artifact.filename:
        key = f"exports/{job_id}-{artifact.filename}"
    else:
        key = f"exports/{job_id}.{request.format}"
    storage = get_guild_storage(request.guild_id)
    await asyncio.to_thread(
        storage.write, key, artifact.content, content_type=artifact.content_type
    )
    return ArtifactLocation(artifact_ref=key)


async def render_artifacts(request: RenderRequest):
    """Every artifact in the request, one at a time.

    Uses the backend's own streaming path when it has one and falls back to
    rendering the batch eagerly when it does not — so a second
    ``RenderBackend`` implementation stays a drop-in, which is the whole point
    of the seam.
    """
    backend = get_backend()
    stream = getattr(backend, "render_stream", None)
    if stream is not None:
        async for artifact in stream(request):
            yield artifact
        return
    for artifact in await backend.render(request):
        yield artifact


async def _stream_zip_to_storage(
    request: RenderRequest,
    *,
    job_id: int,
    stem: str,
    guild_id: int,
    heartbeat: Heartbeat,
) -> ArtifactLocation:
    """Build the archive on disk, then put the file where it belongs.

    Peak memory is one artifact plus the zip's compressor state, instead of
    every rendered artifact and a second full copy in the zip buffer
    (:func:`_write_archive`). The temp file is removed either way; a failed
    job leaves nothing behind.

    The routing decision is made on the **assembled** size rather than on the
    pre-flight estimate, because the estimate counts stored blob bytes and the
    archive is compressed: an export the estimate put over the line can come
    out under it, and handing that back as a download is the better answer.
    The estimate still drives what the wizard warns about before submitting.
    """
    from app.services.export import delivery

    # Same naming as the eager path so the download endpoint recovers the same
    # filename: `exports/{job_id}-{stem}.zip`, prefix stripped on the way out.
    key = f"exports/{job_id}-{stem}.zip"
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as handle:
        tmp_path = Path(handle.name)
    try:
        await _write_archive(request, tmp_path, heartbeat)
        size = tmp_path.stat().st_size
        if size > settings.EXPORT_MAX_DOWNLOAD_BYTES:
            if not delivery.is_configured():
                from app.core.messages import ExportMessages

                raise ExportError(ExportMessages.EXPORT_DESTINATION_REQUIRED)
            destination_ref = await while_beating(
                asyncio.to_thread(
                    delivery.deliver,
                    tmp_path,
                    guild_id=guild_id,
                    filename=f"{stem}-{job_id}.zip",
                ),
                heartbeat,
                every=HEARTBEAT_SECONDS,
                finish=True,
            )
            return ArtifactLocation(destination_ref=destination_ref)
        storage = get_guild_storage(request.guild_id)
        await while_beating(
            asyncio.to_thread(
                storage.write_file, key, tmp_path, content_type="application/zip"
            ),
            heartbeat,
            every=HEARTBEAT_SECONDS,
            finish=True,
        )
    finally:
        await asyncio.to_thread(tmp_path.unlink, missing_ok=True)
    return ArtifactLocation(artifact_ref=key)


def _is_stored(item: RenderItem, request: RenderRequest) -> bool:
    """Whether ``item`` is a stored file that goes out unconverted, which the
    engine copies from storage rather than having it rendered."""
    return (item.format or request.format) == "file"


def _stored_name(item: RenderItem, request: RenderRequest) -> str:
    """The name a stored file goes out under: the adapter's path for it, else
    its own name."""
    return (
        item.filename
        or (f"{item.key}.file" if item.format is not None else None)
        or str(item.data.get("filename") or "")
        or f"{item.key}.{request.format}"
    )


async def _write_archive(
    request: RenderRequest, path: Path, heartbeat: Heartbeat
) -> None:
    """Write the request's archive to ``path``: each artifact rendered in
    turn, and each stored file that goes in unconverted copied from storage
    into its entry a piece at a time, however large. Each entry is compressed
    in a thread, one at a time, so the event loop keeps serving while a large
    archive is built."""
    storage = get_guild_storage(request.guild_id)
    copied = [item for item in request.batch if _is_stored(item, request)]
    rendered = replace(
        request,
        batch=tuple(item for item in request.batch if not _is_stored(item, request)),
    )
    taken: set[str] = set()
    archive = await asyncio.to_thread(zipfile.ZipFile, path, "w", zipfile.ZIP_DEFLATED)
    try:
        async for artifact in render_artifacts(rendered):
            name = artifact.filename or f"{artifact.key}.{request.format}"
            name = _dedupe_name(name, taken)
            taken.add(name)
            await asyncio.to_thread(archive.writestr, name, artifact.content)
            await heartbeat()
        for item in copied:
            name = _dedupe_name(_stored_name(item, request), taken)
            taken.add(name)
            await _copy_stored(
                archive, name, storage, str(item.data["storage_key"]), heartbeat
            )
            await heartbeat()
    finally:
        await asyncio.to_thread(archive.close)


def _store_again(
    storage: StorageBackend, key: str, target: str, content_type: str | None
) -> None:
    """Store the stored file ``key`` again as ``target``, from its own file on
    disk or through a temporary one a piece at a time, however large.
    Blocking; run it in a thread."""
    blob = storage.open_readable(key)
    if blob is None:
        raise FileNotFoundError(key)
    content_type = content_type or blob.content_type
    if blob.path is not None:
        storage.write_file(target, blob.path, content_type=content_type)
        return
    with tempfile.NamedTemporaryFile(prefix="export-") as spool:
        for piece in blob_pieces(blob):
            spool.write(piece)
        spool.flush()
        storage.write_file(target, Path(spool.name), content_type=content_type)


async def _copy_stored(
    archive: zipfile.ZipFile,
    name: str,
    storage: StorageBackend,
    key: str,
    heartbeat: Heartbeat,
) -> None:
    """Write the stored file ``key`` into ``archive`` as ``name``, a piece at a
    time, each read and written in a thread, with ``heartbeat`` awaited
    between pieces so a large file keeps the job alive. A heartbeat that
    raises stops the copy with its entry closed, so the archive still
    closes."""
    blob = await asyncio.to_thread(storage.open_readable, key)
    if blob is None:
        raise FileNotFoundError(key)
    pieces = blob_pieces(blob)
    entry = await asyncio.to_thread(archive.open, name, "w", force_zip64=True)
    try:
        while (piece := await asyncio.to_thread(next, pieces, None)) is not None:
            await asyncio.to_thread(entry.write, piece)
            await heartbeat()
    finally:
        await asyncio.to_thread(entry.close)
        pieces.close()


def _bundle_stem(source: str, tz: str | None) -> str:
    """The zip's name shares the caller's timezone with the entry names the
    adapters produce — near-midnight exports must not disagree on the date."""
    date = datetime.now(resolve_zone(tz)).strftime("%Y-%m-%d")
    return f"{source}-{date}"


def _bundle(
    artifacts: list[RenderedArtifact],
    *,
    format: str,
    stem: str,
    force_zip: bool = False,
) -> RenderedArtifact:
    """One artifact passes through untouched; a batch of N packages into a
    single zip (the selection-export delivery: N entities, one download).
    Entry names come from each artifact's own filename (or ``{key}.{format}``)
    and collide only when two entities share a title — deduped with a numeric
    suffix so both survive. ``force_zip`` wraps even a single artifact — a
    backup is a zip by contract (an empty initiative's backup is just its
    manifest and must still download as an importable archive)."""
    if len(artifacts) == 1 and not force_zip:
        return artifacts[0]
    if not artifacts:  # a selector that matched nothing — nothing to package
        from app.core.messages import ExportMessages

        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
    import io
    import zipfile

    buffer = io.BytesIO()
    taken: set[str] = set()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for artifact in artifacts:
            name = artifact.filename or f"{artifact.key}.{format}"
            name = _dedupe_name(name, taken)
            taken.add(name)
            archive.writestr(name, artifact.content)
    return RenderedArtifact(
        key=stem,
        content_type="application/zip",
        content=buffer.getvalue(),
        filename=f"{stem}.zip",
    )


def _dedupe_name(name: str, taken: set[str]) -> str:
    if name not in taken:
        return name
    if "." in name:
        base, ext = name.rsplit(".", 1)
        pattern = f"{base} ({{n}}).{ext}"
    else:
        pattern = f"{name} ({{n}})"
    n = 2
    while pattern.format(n=n) in taken:
        n += 1
    return pattern.format(n=n)
