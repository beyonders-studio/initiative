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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import CodedError
from app.core.config import settings
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.models.platform.user import User
from app.models.tenant.data_job import DataJob, DataJobDirection, DataJobStatus
from app.services.export.contract import (
    RenderBackend,
    RenderedArtifact,
    RenderRequest,
)
from app.services.export.local_backend import LocalRenderBackend
from app.services.storage import get_guild_storage
from app.services.export import limits as export_limits
from app.core.user_input_validators import resolve_zone
from app.core.user_display import name_here


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
    content: bytes


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
        artifacts = await get_backend().render(request)
        artifact = await asyncio.to_thread(
            _bundle,
            artifacts,
            format=format,
            stem=_bundle_stem(source, params.get("tz")),
            force_zip=getattr(adapter, "force_zip", False),
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
    if getattr(ADAPTERS.get(source), "force_zip", False):
        # The aggregate sources assemble on disk: a whole community's archive
        # is not something to hold in memory twice (once as rendered
        # artifacts, once as the zip) just to hand it to storage.
        return await _stream_zip_to_storage(
            request,
            job_id=job_id,
            stem=stem,
            guild_id=request.guild_id,
            heartbeat=beat,
        )

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
    every rendered artifact and a second full copy in the zip buffer. The temp
    file is removed either way; a failed job leaves nothing behind.

    The routing decision is made on the **assembled** size rather than on the
    pre-flight estimate, because the estimate counts stored blob bytes and the
    archive is compressed: an export the estimate put over the line can come
    out under it, and handing that back as a download is the better answer.
    The estimate still drives what the wizard warns about before submitting.
    """
    from app.services.export import delivery
    import tempfile
    import zipfile
    from pathlib import Path

    # Same naming as the eager path so the download endpoint recovers the same
    # filename: `exports/{job_id}-{stem}.zip`, prefix stripped on the way out.
    key = f"exports/{job_id}-{stem}.zip"
    handle = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    handle.close()
    tmp_path = Path(handle.name)
    try:
        taken: set[str] = set()
        # Each entry is compressed in a thread, one at a time, so the event
        # loop keeps serving while a large archive is built.
        archive = await asyncio.to_thread(
            zipfile.ZipFile, tmp_path, "w", zipfile.ZIP_DEFLATED
        )
        try:
            async for artifact in render_artifacts(request):
                name = artifact.filename or f"{artifact.key}.{request.format}"
                name = _dedupe_name(name, taken)
                taken.add(name)
                await asyncio.to_thread(archive.writestr, name, artifact.content)
                await heartbeat()
        finally:
            await asyncio.to_thread(archive.close)
        size = tmp_path.stat().st_size
        if size > settings.EXPORT_MAX_DOWNLOAD_BYTES:
            if not delivery.is_configured():
                from app.core.messages import ExportMessages

                raise ExportError(ExportMessages.EXPORT_DESTINATION_REQUIRED)
            destination_ref = await asyncio.to_thread(
                delivery.deliver,
                tmp_path,
                guild_id=guild_id,
                filename=f"{stem}-{job_id}.zip",
            )
            return ArtifactLocation(destination_ref=destination_ref)
        storage = get_guild_storage(request.guild_id)
        await asyncio.to_thread(
            storage.write_file, key, tmp_path, content_type="application/zip"
        )
    finally:
        await asyncio.to_thread(tmp_path.unlink, missing_ok=True)
    return ArtifactLocation(artifact_ref=key)


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
