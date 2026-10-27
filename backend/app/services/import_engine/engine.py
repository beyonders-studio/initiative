"""Import engine: the shared create path for envelope imports.

Mirrors the export engine's ``start_export`` (registry → bound → inline-or-
job with an advisory-locked per-user cap) with one inversion: **imports are
writes, always** — the caller must already be a writable actor (endpoints
enforce it), and every apply inserts rows as the importing user.

A payload too large to apply inline is staged behind the guild's storage
backend (the job row references it and never holds content) and applied by
the worker on a fresh creator-routed session.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator, BinaryIO

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db import gucs
from app.db.session import raise_flag, routed_guild_id
from app.core.messages import ImportEngineMessages
from app.models.platform.guild import CommunityRole
from app.models.platform.user import User
from app.models.tenant.import_job import ImportJob, ImportJobStatus
from app.models.tenant.initiative import Initiative
from app.core.legacy_references import rewrite_body, rewrite_ref, rewrite_text
from app.core.tools import Tool, tool_envelope_type, tool_for_create_permission
from app.schemas.tenant.import_job import BackupPlanPerson, EnvelopeImportPlan
from app.services.import_engine.common import (
    handle_key,
    load_guild_member_handles,
)
from app.services.import_engine.contract import (
    EnvelopeImporter,
    EnvelopeImportResult,
    ImportEngineError,
    InlineImport,
)
from app.services.import_engine import limits as import_limits

# Statuses that count against the per-user active-job cap.
_ACTIVE_STATUSES = (
    ImportJobStatus.staged,
    # A fetch is the slowest thing a job does and the one most worth
    # capping — it is somebody else's API being read on our schedule.
    ImportJobStatus.fetching,
    ImportJobStatus.queued,
    ImportJobStatus.running,
)


#: How an archive or an envelope written by an older build names files (once
#: documents): the manifest's tool, its tool switches and envelope type, the
#: keys holding a file's type and the files filed in a wiki or attached to an
#: item, the refs naming one, and the role permissions for the tool. Read on
#: restore and on a lone envelope's import, and rewritten to this build's names
#: before anything else looks at them; nothing writes them. A gallery's backup
#: entry is filed with the files, since its pictures are restored as files and
#: a collection.
_LEGACY_ENVELOPE_TYPES = {"initiative-document": tool_envelope_type(Tool.file)}
_LEGACY_TOOLS = {"document": Tool.file.value}
_LEGACY_ENTRY_TOOLS = {**_LEGACY_TOOLS, "gallery": Tool.file.value}
_LEGACY_KEYS = {"documents": "files", "document_type": "file_type"}
_LEGACY_PERMISSIONS = {
    "documents_enabled": Tool.file.view_permission,
    "create_documents": Tool.file.create_permission,
}


def current_shape(value: Any) -> Any:
    """``value``, read from an archive or an envelope, with the names an
    older build gave files spelled as this one spells them, and every
    reference in a body as well. A gallery's pictures are restored with no id
    to name them by, so a reference to one is its words."""
    if isinstance(value, str):
        return rewrite_text(value, {})
    if isinstance(value, list):
        return [current_shape(item) for item in value]
    if not isinstance(value, dict):
        return value
    value = rewrite_body(value, {})
    shaped = {
        _LEGACY_KEYS.get(key, key): current_shape(item) for key, item in value.items()
    }
    tools = shaped.get("tools")
    if isinstance(tools, dict):
        shaped["tools"] = {
            _LEGACY_TOOLS.get(key, key): item for key, item in tools.items()
        }
    kind = shaped.get("type")
    if isinstance(kind, str) and kind in _LEGACY_ENVELOPE_TYPES:
        shaped["type"] = _LEGACY_ENVELOPE_TYPES[kind]
    tool = shaped.get("tool")
    if isinstance(tool, str) and tool in _LEGACY_ENTRY_TOOLS:
        shaped["tool"] = _LEGACY_ENTRY_TOOLS[tool]
    ref = shaped.get("external_ref")
    if isinstance(ref, str):
        shaped["external_ref"] = rewrite_ref(ref, {}) or ref
    permissions = shaped.get("permissions")
    if isinstance(permissions, list):
        shaped["permissions"] = [
            _LEGACY_PERMISSIONS.get(key, key) if isinstance(key, str) else key
            for key in permissions
        ]
    return shaped


def get_importer(envelope_type: str) -> EnvelopeImporter:
    from app.services.import_engine.importers import IMPORTERS

    importer = IMPORTERS.get(envelope_type)
    if importer is None:
        raise ImportEngineError(ImportEngineMessages.IMPORT_UNKNOWN_TYPE)
    return importer


async def load_target_initiative(
    session: AsyncSession,
    *,
    guild_id: int,
    initiative_id: Any,
    importer: EnvelopeImporter,
    user: User,
) -> Initiative:
    """Resolve + authorize the import target: the initiative must be
    reachable under the caller's RLS (unreachable is indistinguishable from
    absent — 404), its tool master switch must be on, and the caller must
    hold the importer's create permission (guild admins bypass, like every
    create path)."""
    from app.models.tenant.initiative import PermissionKey
    from app.services import rls as rls_service
    from app.services.platform import guilds as guilds_service

    try:
        initiative_id = int(initiative_id)
    except (TypeError, ValueError):
        raise ImportEngineError(ImportEngineMessages.IMPORT_INVALID_PARAMS)

    initiative = (
        await session.exec(
            select(Initiative).where(
                Initiative.id == initiative_id,
            )
        )
    ).one_or_none()
    if initiative is None:
        raise ImportEngineError(
            ImportEngineMessages.IMPORT_INVALID_PARAMS, status_code=404
        )

    # Tool master switch, derived from the Tool enum (the single source of
    # the create_*/​*_enabled naming) — never by string surgery on the
    # permission key. Registry construction already proved the mapping exists
    # (importers/__init__.py), so a miss here is impossible, not "default on".
    permission = PermissionKey(importer.permission)
    tool = tool_for_create_permission(permission.value)
    if not getattr(initiative, tool.view_permission):
        raise ImportEngineError(
            ImportEngineMessages.IMPORT_TOOL_DISABLED, status_code=400
        )

    membership = await guilds_service.get_membership(
        session, guild_id=guild_id, user_id=user.id
    )
    is_admin = membership is not None and membership.role.reaches(CommunityRole.admin)
    if not is_admin:
        has_perm = await rls_service.check_initiative_permission(
            session,
            initiative_id=initiative.id,
            user=user,
            permission_key=permission,
        )
        if not has_perm:
            raise ImportEngineError(
                ImportEngineMessages.IMPORT_PERMISSION_REQUIRED, status_code=403
            )
    return initiative


async def plan_envelope_people(
    session: AsyncSession, *, guild_id: int, importer: EnvelopeImporter, validated: Any
) -> list[BackupPlanPerson]:
    """Everybody the envelope quotes, with a suggestion where one is certain.

    The lone-envelope counterpart of ``backup.plan_backup``'s people pass, and
    filled by the same rule: ``suggested_user_id`` only on an **exact** handle
    match against the community's roster. A display name that merely looks
    similar is how one person's words end up under another person's face, and
    it is the reason there is a step to ask at all.

    Empty for every importer whose envelopes name nobody, which is most of
    them — the roster is not even read in that case.
    """
    people = importer.people(validated)
    if not people:
        return []
    roster = await load_guild_member_handles(session, guild_id=guild_id)
    return [
        BackupPlanPerson(
            handle=person.handle,
            name=person.name,
            comment_count=person.comment_count,
            suggested_user_id=roster.get(handle_key(person.handle)),
        )
        for person in people
    ]


async def start_envelope_import(
    session: AsyncSession,
    *,
    user: User,
    guild_id: int,
    initiative_id: int,
    envelope: dict[str, Any],
) -> InlineImport | ImportJob:
    """The shared create path: validate + authorize under RLS, bound, then
    auto-select delivery.

    Three outcomes, and the first of them is the one worth stating:

    * **Staged**, when the envelope quotes somebody nobody here can be sure
      of. The job parks at ``staged`` with a plan naming those people, and
      ``POST /imports/jobs/{id}/confirm`` starts the apply with the answers —
      the same two-step a backup takes, for the same reason. It asks only
      when there is something to ask: an envelope quoting nobody, or one
      where every handle is an exact match for a member, is applied straight
      away, because the confirm screen's own defaults would do the same thing
      and interrupting somebody to agree with themselves is not a step.
    * **Inline**, at or under IMPORT_INLINE_MAX_ROWS — applied in-request,
      no job row.
    * **Queued**, above it — the payload is staged and the worker
      re-validates and applies it under the creator's RLS session.
    """
    envelope = current_shape(envelope)
    envelope_type = envelope.get("type")
    if not isinstance(envelope_type, str):
        raise ImportEngineError(ImportEngineMessages.IMPORT_UNKNOWN_TYPE)
    importer = get_importer(envelope_type)
    validated = importer.validate(envelope)
    initiative = await load_target_initiative(
        session,
        guild_id=guild_id,
        initiative_id=initiative_id,
        importer=importer,
        user=user,
    )

    rows = importer.count(validated)
    if rows > import_limits.IMPORT_MAX_ROWS:
        raise ImportEngineError(ImportEngineMessages.IMPORT_TOO_LARGE)

    people = await plan_envelope_people(
        session, guild_id=guild_id, importer=importer, validated=validated
    )
    unplaced = [person for person in people if person.suggested_user_id is None]

    if not unplaced and rows <= import_limits.IMPORT_INLINE_MAX_ROWS:
        result = await apply_one_envelope(
            session,
            importer=importer,
            envelope=validated,
            target_initiative=initiative,
            user=user,
        )
        await session.commit()
        return InlineImport(result=result)

    await count_active_jobs_locked(session, user=user)

    payload_ref = await asyncio.to_thread(_stage_envelope, guild_id, envelope)
    job = ImportJob(
        created_by=user.id,
        source=envelope_type,
        params={"initiative_id": initiative.id},
        payload_ref=payload_ref,
        # A staged job is waiting on a person; a queued one is waiting on the
        # worker. The plan rides along only in the first case, because it is
        # the question being asked.
        plan=EnvelopeImportPlan(people=people).model_dump(mode="json")
        if unplaced
        else None,
        status=ImportJobStatus.staged if unplaced else ImportJobStatus.queued,
        expires_at=datetime.now(timezone.utc)
        + timedelta(hours=import_limits.IMPORT_STAGED_TTL_HOURS),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def apply_one_envelope(
    session: AsyncSession,
    *,
    importer: EnvelopeImporter,
    envelope: Any,
    target_initiative: Initiative,
    user: User,
    people_map: Any = None,
    exclude_properties: Any = None,
) -> "EnvelopeImportResult":
    """Apply one envelope and then resolve the links it asserted.

    A lone envelope is the degenerate case of the deferred pass, not a
    different path: it registers what it created, records what it pointed
    at, and resolves the pairs where both ends happened to be in the same
    file. Every ref naming something outside it is counted as unresolved —
    which is the honest answer, and the same one a backup gives.

    ``people_map`` is whatever a confirm recorded. A lone envelope usually
    arrives without one — there is no step in that flow to ask — and then
    the handles in it are matched against the target initiative's own
    members, or carried as names.
    """
    from app.services.import_engine.context import (
        ImportContext,
        excluded_property_names,
        exported_from_here,
    )
    from app.services.import_engine.people import resolve_people_map
    from app.services.import_engine.references import resolve_references

    guild_id = routed_guild_id(session)
    context = ImportContext(
        people=await resolve_people_map(session, guild_id=guild_id, raw=people_map),
        excluded_properties=excluded_property_names(exclude_properties),
        same_community=exported_from_here(
            getattr(envelope, "source_instance_url", None),
            getattr(envelope, "source_guild_id", None),
            guild_id=guild_id,
        ),
    )
    await raise_flag(session, gucs.IMPORTING)
    result = await importer.apply(
        session,
        envelope=envelope,
        target_initiative=target_initiative,
        importer=user,
        context=context,
    )
    await raise_flag(session, gucs.IMPORTING, False)
    resolution = await context.links.resolve(session, created_by=user.id)
    result.links_created = resolution.created
    result.links_unresolved = resolution.unresolved
    await resolve_references(session, context, author_id=user.id)
    return result


async def count_active_jobs_locked(session: AsyncSession, *, user: User) -> None:
    """Enforce the per-user active-job cap under a transaction-scoped
    advisory lock, so concurrent requests can't race past it (the lock is
    released at the caller's commit). Raises IMPORT_JOB_LIMIT_REACHED."""
    await advisory_lock(session, LockNamespace.IMPORT_CAP, user.id)
    active = (
        await session.exec(
            select(func.count())
            .select_from(ImportJob)
            .where(
                ImportJob.created_by == user.id,
                ImportJob.status.in_(_ACTIVE_STATUSES),
            )
        )
    ).one()
    if active >= import_limits.IMPORT_MAX_ACTIVE_JOBS_PER_USER:
        raise ImportEngineError(
            ImportEngineMessages.IMPORT_JOB_LIMIT_REACHED, status_code=429
        )


def stage_payload(guild_id: int, payload: bytes, *, suffix: str) -> str:
    """Write an import payload behind the guild's storage backend and return
    its key. Payloads are deliberately NOT registered in ``uploads`` — they
    are engine-internal, unreachable via the media route, and deleted when
    the job reaches a terminal state (or by GC on expiry)."""
    from app.services.storage import get_guild_storage

    key = f"imports/{uuid.uuid4().hex}.{suffix}"
    content_type = "application/json" if suffix == "json" else "application/zip"
    get_guild_storage(guild_id).write(key, payload, content_type=content_type)
    return key


def _stage_envelope(guild_id: int, envelope: dict[str, Any]) -> str:
    """Serialize an envelope and stage it. Blocking; run it in a thread."""
    return stage_payload(guild_id, json.dumps(envelope).encode("utf-8"), suffix="json")


def stage_payload_file(guild_id: int, path: Path, *, suffix: str) -> str:
    """:func:`stage_payload` for a payload already on disk, which is copied
    to storage without being read into memory. Blocking; run it in a
    thread."""
    from app.services.storage import get_guild_storage

    key = f"imports/{uuid.uuid4().hex}.{suffix}"
    content_type = "application/json" if suffix == "json" else "application/zip"
    get_guild_storage(guild_id).write_file(key, path, content_type=content_type)
    return key


#: How much of an upload is copied at a time.
_SPOOL_CHUNK_BYTES = 1024 * 1024


def _spool_to_file(source: BinaryIO, max_bytes: int) -> Path:
    """Copy ``source`` to a temporary file a chunk at a time, stopping with
    ``IMPORT_TOO_LARGE`` once it passes ``max_bytes``."""
    import tempfile

    handle = tempfile.NamedTemporaryFile(
        prefix="import-upload-", suffix=".zip", delete=False
    )
    path = Path(handle.name)
    try:
        with handle:
            total = 0
            while True:
                chunk = source.read(min(_SPOOL_CHUNK_BYTES, max_bytes + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ImportEngineError(
                        ImportEngineMessages.IMPORT_TOO_LARGE, status_code=413
                    )
                handle.write(chunk)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


@asynccontextmanager
async def spooled_upload(source: BinaryIO, *, max_bytes: int) -> AsyncIterator[Path]:
    """An uploaded file as a local file for the length of the block.

    Copied off the event loop a chunk at a time, so no more than one chunk is
    in memory, and refused with ``IMPORT_TOO_LARGE`` (413) once it passes
    ``max_bytes``. The copy is removed after the block.
    """
    path = await asyncio.to_thread(_spool_to_file, source, max_bytes)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def _spool_payload(guild_id: int, payload_ref: str) -> tuple[Path, bool] | None:
    """Where a staged payload can be read as a file, and whether that file is
    a temporary copy the caller removes."""
    import tempfile

    from app.services.storage import get_guild_storage

    blob = get_guild_storage(guild_id).open_readable(payload_ref)
    if blob is None:
        return None
    if blob.path is not None:
        return Path(blob.path), False
    if blob.stream is None:
        return None
    handle = tempfile.NamedTemporaryFile(prefix="import-payload-", delete=False)
    try:
        with handle:
            for chunk in blob.stream:
                handle.write(chunk)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise
    return Path(handle.name), True


@asynccontextmanager
async def open_payload(guild_id: int, payload_ref: str) -> AsyncIterator[Path | None]:
    """A staged payload as a local file for the length of the block, or
    ``None`` when the blob is gone.

    Local storage hands back the stored file itself; an object store's is
    copied to a temporary file first, a chunk at a time, and removed after.
    Either way the payload is never held in memory whole.
    """
    spooled = await asyncio.to_thread(_spool_payload, guild_id, payload_ref)
    if spooled is None:
        yield None
        return
    path, temporary = spooled
    try:
        yield path
    finally:
        if temporary:
            path.unlink(missing_ok=True)


def read_payload(guild_id: int, payload_ref: str) -> bytes | None:
    """Read a staged payload back from the guild's storage backend (local FS
    path or S3 stream transparently). None when the blob is gone."""
    from app.services.storage import get_guild_storage

    blob = get_guild_storage(guild_id).open_readable(payload_ref)
    if blob is None:
        return None
    if blob.path is not None:
        return Path(blob.path).read_bytes()
    if blob.stream is None:
        return None
    return b"".join(blob.stream)


def delete_payload(guild_id: int, payload_ref: str | None) -> None:
    """Best-effort staged-payload cleanup — a failing delete must not fail
    the job transition (GC re-tries expired rows)."""
    if not payload_ref:
        return
    from app.services.storage import get_guild_storage

    try:
        get_guild_storage(guild_id).delete(payload_ref)
    except Exception:  # pragma: no cover - backend-specific failures
        pass
