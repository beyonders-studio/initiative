"""Export endpoints: create (auto inline-vs-job), poll, and download.

The artifact is content, so its download is a gated read: the download route
loads the ExportJob row under RLS (own-row + guild-admin policies), asks again
that the caller reaches every initiative the artifact holds, and only then
streams the file from the guild's storage backend. Artifacts are deliberately
never registered in ``uploads``, so the guild-wide ``/uploads/{community_id}/…``
media route cannot serve them: an export is a per-user snapshot and may contain
initiative-isolated content the rest of the guild must not reach.

Every tool exports through one route, ``GET /{tool}``: the formats it offers
are its adapter's in ``ADAPTERS``.
"""

import json
from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Annotated, Any, List, Literal, Optional, Union

from pydantic import Field

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, not_
from sqlmodel import select

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    require_seat,
    GuildContextDep,
)
from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.core.messages import ExportMessages, InitiativeMessages
from app.core.tools import Tool, tool_export_source
from app.core.user_display import display_name
from app.models.platform.user import User
from app.models.platform.user_profile_view import MemberProfile
from app.models.tenant.export_job import ExportJob, ExportJobStatus
from app.models.tenant.initiative import Initiative
from app.schemas.query import DateBucket
from app.schemas.tenant.backup_export import BackupEstimate
from app.schemas.tenant.tool_layout import (
    MAX_FIELD_ID_LENGTH,
    MAX_HIDDEN_GROUPS,
    MAX_NODES,
)
from app.schemas.tenant.export_job import (
    ExportJobRead,
    CommunityExportStatus,
    artifact_expired,
    serialize_export_job,
)
from app.services import audit as audit_service
from app.services.platform import rules
from app.services.export.adapters import ADAPTERS
from app.services.export.adapters.backup import (
    GuildExportAdapter,
    InitiativeExportAdapter,
)
from app.services.export.engine import InlineExport, start_export
from app.services.storage import (
    build_upload_response,
    content_disposition_attachment,
    get_guild_storage,
)
from app.services.export import limits as export_limits
from app.services.membership import initiative_scope_clause
from app.services.tenant.initiatives import keeps_content_in

router = APIRouter()

CurrentUserDep = Annotated[User, Depends(get_current_active_user)]

_LIST_LIMIT = 50


def _inline_response(result: InlineExport) -> Response:
    # The filename can carry user text (file titles, original upload
    # names) — the helper escapes it (RFC 5987) so it can't break the header.
    return Response(
        content=result.content,
        media_type=result.content_type,
        headers={
            "Content-Disposition": content_disposition_attachment(result.filename)
        },
    )


def _allow_job(guild_context: GuildContext) -> bool:
    """Enqueueing a job authors a row. A guild in read_only lifecycle can't
    write, and neither can a grantee: a grant reaches existing content. Inline
    export stays available to all — it is a formatted read."""
    if guild_context.content_read_only:
        return False
    if guild_context.is_pam:
        return False
    return True


def _job_response(
    job: ExportJob, *, guild_id: int, status_code: int = status.HTTP_200_OK
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=serialize_export_job(job, guild_id=guild_id).model_dump(mode="json"),
    )


async def _start_export(
    session: RLSSessionDep,
    current_user: User,
    guild_context: GuildContext,
    *,
    source: str,
    format: str,
    params: dict[str, Any],
) -> Union[InlineExport, ExportJob]:
    """Start an export through the engine: rendered here when it is small, or
    queued as a job the caller polls."""
    return await start_export(
        session,
        user=current_user,
        guild_id=guild_context.guild_id,
        source=source,
        format=format,
        params=params,
        allow_job=_allow_job(guild_context),
    )


def _export_response(
    result: Union[InlineExport, ExportJob], guild_context: GuildContext
) -> Response:
    """The file itself for an inline export; ``202`` and the job for a queued
    one."""
    if isinstance(result, InlineExport):
        return _inline_response(result)
    return _job_response(
        result, guild_id=guild_context.guild_id, status_code=status.HTTP_202_ACCEPTED
    )


@router.get("/tasks", response_model=None)
async def export_tasks(
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
    # Literal so the HTTP layer 422s garbage and OpenAPI carries the enum;
    # grows as formats land. The registry still guards per-source combos.
    format: Literal["pdf", "csv", "xlsx", "md"] = Query(default="pdf"),
    conditions: Optional[str] = Query(
        default=None, description="Same JSON filter conditions as the task list"
    ),
    sorting: Optional[str] = Query(
        default=None, description="Same JSON sort fields as the task list"
    ),
    tz: Optional[str] = Query(default=None, description="IANA timezone name"),
    include_archived: bool = Query(default=False),
    layout: Literal["table", "checklist", "detailed"] = Query(
        default="table",
        description=(
            "Report layout. Markdown: a table (default) or a GitHub-style task "
            "list (checklist). PDF: the default table, or 'detailed' for a "
            "one-task-per-page report with description, checklist and comments. "
            "Ignored by csv/xlsx."
        ),
    ),
    group_by: Optional[str] = Query(
        default=None,
        max_length=64,
        description=(
            "The field the list is grouped by, as GET /tasks/groups takes it: "
            "each task is listed under every group it is in, the groups in the "
            "list's order"
        ),
    ),
    bucket: Optional[DateBucket] = Query(
        default=None, description="For a date: the bucket of the calendar it groups by"
    ),
    hidden_groups: Optional[List[str]] = Query(
        default=None,
        max_length=MAX_HIDDEN_GROUPS,
        description="The keys of the groups the list leaves out",
    ),
    columns: Optional[
        List[Annotated[str, Field(max_length=MAX_FIELD_ID_LENGTH)]]
    ] = Query(
        default=None,
        max_length=MAX_NODES,
        description=(
            "The layout fields the list's table shows, in order (``title``, "
            "``dueDate``, ``property:<id>``, ``plugin:<install>:<key>``). "
            "The status follows them, as the table draws it."
        ),
    ),
    detail: Optional[
        List[Annotated[str, Field(max_length=MAX_FIELD_ID_LENGTH)]]
    ] = Query(
        default=None,
        max_length=MAX_NODES,
        description=(
            "For the detailed PDF: the task page's parts in its order, its "
            "fields and ``status``, ``dates``, ``properties``, ``description``, "
            "``checklist`` and ``comments``"
        ),
    ),
) -> Union[Response, JSONResponse]:
    """Export the task list (the same visibility and filters as ``GET
    /tasks/``) as a formatted file. Small results render inline and return
    the file directly; large results return ``202`` with a queued job to poll
    and download."""
    result = await _start_export(
        session,
        current_user,
        guild_context,
        source="tasks",
        format=format,
        params={
            "conditions": conditions,
            "sorting": sorting,
            "tz": tz,
            "include_archived": include_archived,
            "layout": layout,
            "group_by": group_by,
            "bucket": bucket.value if bucket else None,
            "hidden_groups": hidden_groups,
            "columns": columns,
            "detail": detail,
        },
    )
    return _export_response(result, guild_context)


@router.get("/events", response_model=None)
async def export_events(
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
    format: Literal["ics"] = Query(default="ics"),
    initiative_id: Optional[int] = Query(default=None),
    scope: Optional[Literal["community"]] = Query(default=None),
    calendar_ids: Optional[List[int]] = Query(default=None),
    exclude_calendar_ids: Optional[List[int]] = Query(
        default=None, description="Calendars to leave out, such as hidden ones"
    ),
    property_filters: Optional[str] = Query(
        default=None, description="Same JSON property filters as the event list"
    ),
    start_after: Optional[datetime] = Query(
        default=None, description="Same date range as the event list"
    ),
    start_before: Optional[datetime] = Query(default=None),
    tz: Optional[str] = Query(
        default=None,
        max_length=64,
        description="IANA timezone for the file name's date",
    ),
) -> Union[Response, JSONResponse]:
    """Export calendar events (the same visibility and filters as ``GET
    /calendar-events/``) as one iCalendar file: every date, unless a range is
    given. A repeating event starting in the range travels whole, with its
    changed occurrences. Small results return the file directly; large results
    return ``202`` with a queued job to poll and download."""
    result = await _start_export(
        session,
        current_user,
        guild_context,
        source="events",
        format=format,
        params={
            "initiative_id": initiative_id,
            "scope": scope,
            "calendar_ids": calendar_ids,
            "exclude_calendar_ids": exclude_calendar_ids,
            "property_filters": property_filters,
            "start_after": start_after.isoformat() if start_after else None,
            "start_before": start_before.isoformat() if start_before else None,
            "tz": tz,
        },
    )
    return _export_response(result, guild_context)


def _parse_json_param(raw: Optional[str]) -> Optional[dict]:
    """`include`/`formats` arrive as JSON-string query params (the same
    convention as the task list's `conditions`). Shape validation happens in
    the adapter at count time; here we only reject non-JSON/non-object."""
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ExportMessages.EXPORT_INVALID_PARAMS,
        )
    if not isinstance(value, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ExportMessages.EXPORT_INVALID_PARAMS,
        )
    return value


_FILTERS_DESCRIPTION = (
    "JSON object of tool→filters narrowing what each tool exports: the tool's "
    "own list filters (as its list route takes them, such as "
    '``{"queue": {"tag_ids": [3]}}``), and for calendars an ``events`` date '
    "range. ``archived`` omitted exports live and archived rows alike."
)


async def _guild_export_available_at(session) -> Optional[datetime]:
    """When the next whole-community export may start — ``None`` for now.

    A whole community's content is not a thing to re-read on a loop. The bound
    that actually matters for what this costs a deployment: one community-wide
    export per the deployment's ``community_export_cooldown_hours``, counted across the community
    rather than per person, so a second admin does not reset it. Failed and
    expired jobs do not hold the door — only work that was really done counts.

    One definition, asked twice: the gate below refuses on it and the status
    endpoint reports it, so what the settings page says and what the door
    does cannot come apart.
    """
    hours = (await rules.platform_values(session))["community_export_cooldown_hours"]
    if hours <= 0:
        return None
    window = timedelta(hours=hours)
    started_at = (
        await session.exec(
            select(ExportJob.created_at)
            .where(
                ExportJob.source == "community",
                ExportJob.status.in_(
                    (
                        ExportJobStatus.queued,
                        ExportJobStatus.running,
                        ExportJobStatus.done,
                    )
                ),
                ExportJob.created_at >= datetime.now(timezone.utc) - window,
            )
            .order_by(ExportJob.created_at.desc())
            .limit(1)
        )
    ).first()
    return started_at + window if started_at is not None else None


async def _require_guild_cooldown_elapsed(session) -> None:
    """Refuse a community-wide export inside the cooldown, saying how long is
    left — the same number the settings page counts down."""
    available_at = await _guild_export_available_at(session)
    if available_at is None:
        return
    seconds_left = (available_at - datetime.now(timezone.utc)).total_seconds()
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=ExportMessages.EXPORT_COOLDOWN_ACTIVE,
        headers={"Retry-After": str(max(1, ceil(seconds_left)))},
    )


# NOTE: literal paths below must stay declared before the parametric
# ``/{job_id}`` routes, or "estimate" would be parsed as a job id.
@router.get("/estimate", response_model=BackupEstimate)
async def estimate_aggregate_export(
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
    scope: Literal["initiative", "community"] = Query(),
    initiative_id: Optional[int] = Query(
        default=None, description="Required when scope=initiative"
    ),
    include_uploads: bool = Query(default=True),
    filters: Optional[str] = Query(default=None, description=_FILTERS_DESCRIPTION),
) -> BackupEstimate:
    """Pre-flight numbers for the export wizard: per-tool entity counts and
    the uploads footprint (approximate — embedded document images resolve at
    build time), plus the row/byte ceilings so the client can warn before
    submitting. Guild scope requires the community's seat."""
    from app.services.export.adapters.backup import estimate_backup

    if scope == "community":
        require_seat(guild_context, detail=ExportMessages.EXPORT_SUPERADMIN_REQUIRED)
    return await estimate_backup(
        session,
        current_user,
        guild_context.guild_id,
        # A backup records its scope as "guild" in its manifest.
        scope="guild" if scope == "community" else scope,
        initiative_id=initiative_id,
        include_uploads=include_uploads,
        filters=_parse_json_param(filters),
    )


@router.get("/initiative", response_model=None)
async def export_initiative(
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
    initiative_id: int = Query(),
    mode: Literal["backup", "report"] = Query(default="backup"),
    include: Optional[str] = Query(
        default=None,
        description=(
            'JSON object of tool→bool, e.g. {"project": true, "queue": false}. '
            "Omitted = every tool."
        ),
    ),
    formats: Optional[str] = Query(
        default=None,
        description=(
            "Report mode: JSON object of tool→format; the file entry is a "
            'nested map, e.g. {"project": "pdf", "file": {"lexical": "md", '
            '"sheet": "xlsx"}}. Unlisted tools use their backup format.'
        ),
    ),
    include_uploads: bool = Query(
        default=True, description="Backup mode: bundle referenced upload blobs"
    ),
    filters: Optional[str] = Query(default=None, description=_FILTERS_DESCRIPTION),
    tz: Optional[str] = Query(
        default=None, max_length=64, description="IANA timezone for report timestamps"
    ),
) -> Union[Response, JSONResponse]:
    """Export a whole initiative as one zip: ``backup`` bundles every included
    tool's importable JSON envelope plus a ``manifest.json`` (optionally with
    the upload blobs the files reference); ``report`` renders each tool in
    the caller's chosen format. Requires reaching the initiative; per-entity
    sharing applies throughout, and projects are included with read access.
    Always returns ``202`` with a queued job to poll and download."""
    result = await _start_export(
        session,
        current_user,
        guild_context,
        source="initiative",
        format="zip",
        params={
            "initiative_id": initiative_id,
            "mode": mode,
            "include": _parse_json_param(include),
            "formats": _parse_json_param(formats),
            "include_uploads": include_uploads,
            "filters": _parse_json_param(filters),
            "tz": tz,
        },
    )

    job_id = None if isinstance(result, InlineExport) else result.id
    await audit_service.record(
        session,
        event_type=AuditEventType.INITIATIVE_EXPORTED,
        actor_user_id=current_user.id,
        guild_id=guild_context.guild_id,
        target_type="export_job" if job_id is not None else "initiative",
        target_id=job_id if job_id is not None else initiative_id,
        detail={
            "mode": mode,
            "include_uploads": include_uploads,
            "initiative_id": initiative_id,
            "job_id": job_id,
        },
    )
    await session.commit()
    # An aggregate export is always a job.
    return _export_response(result, guild_context)


@router.get("/community", response_model=None)
async def export_community(
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
    mode: Literal["backup", "report"] = Query(default="backup"),
    include: Optional[str] = Query(
        default=None, description="JSON object of tool→bool; omitted = every tool"
    ),
    formats: Optional[str] = Query(
        default=None,
        description="Report mode: JSON object of tool→format (see /exports/initiative)",
    ),
    include_uploads: bool = Query(
        default=True, description="Backup mode: bundle referenced upload blobs"
    ),
    filters: Optional[str] = Query(default=None, description=_FILTERS_DESCRIPTION),
    tz: Optional[str] = Query(
        default=None, max_length=64, description="IANA timezone for report timestamps"
    ),
) -> Union[Response, JSONResponse]:
    """Export the whole guild — every initiative the same way
    ``/exports/initiative`` exports one, in a single zip. The community's seat
    only (held outright; the adapter re-checks at render time so a vacated
    seat fails the job closed), and once per cooldown window. Always returns
    ``202`` with a queued job to poll and download."""
    require_seat(guild_context, detail=ExportMessages.EXPORT_SUPERADMIN_REQUIRED)
    await _require_guild_cooldown_elapsed(session)
    result = await _start_export(
        session,
        current_user,
        guild_context,
        source="community",
        format="zip",
        params={
            "mode": mode,
            "include": _parse_json_param(include),
            "formats": _parse_json_param(formats),
            "include_uploads": include_uploads,
            "filters": _parse_json_param(filters),
            "tz": tz,
        },
    )

    job_id = None if isinstance(result, InlineExport) else result.id
    await audit_service.record(
        session,
        event_type=AuditEventType.GUILD_EXPORTED,
        actor_user_id=current_user.id,
        guild_id=guild_context.guild_id,
        target_type="export_job" if job_id is not None else "guild",
        target_id=job_id if job_id is not None else guild_context.guild_id,
        detail={
            "mode": mode,
            "include_uploads": include_uploads,
            "job_id": job_id,
        },
    )
    await session.commit()
    # An aggregate export is always a job.
    return _export_response(result, guild_context)


@router.get("/community/status", response_model=CommunityExportStatus)
async def read_community_export_status(
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> CommunityExportStatus:
    """The state of this community's whole-community export, before anybody
    opens the wizard: the last one taken — who took it, how it ended, and
    whether its archive is still there — and when the next one may start.

    Seat-only, like the export it describes. Two bounded reads: the newest
    ``guild`` job, and the cooldown the create route enforces.
    """
    require_seat(guild_context, detail=ExportMessages.EXPORT_SUPERADMIN_REQUIRED)
    latest = (
        await session.exec(
            select(ExportJob)
            .where(ExportJob.source == "community")
            .order_by(ExportJob.created_at.desc())
            .limit(1)
        )
    ).first()
    # Read through the member view, so the name is the one set in this
    # community, or the handle, as everywhere else. Empty where the account is gone;
    # the page says who it was missing in its own words.
    started_by = None
    if latest is not None:
        started_by = display_name(await session.get(MemberProfile, latest.created_by))
    return CommunityExportStatus(
        cooldown_hours=(await rules.platform_values(session))[
            "community_export_cooldown_hours"
        ],
        next_available_at=await _guild_export_available_at(session),
        latest=serialize_export_job(latest, guild_id=guild_context.guild_id)
        if latest is not None
        else None,
        latest_started_by=started_by or None,
    )


@router.get("/jobs", response_model=list[ExportJobRead])
async def list_export_jobs(
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> list[ExportJobRead]:
    """The caller's export jobs, newest first (RLS scopes the rows: own rows,
    or the whole guild for a guild admin)."""
    jobs = await session.exec(
        select(ExportJob).order_by(ExportJob.created_at.desc()).limit(_LIST_LIMIT)
    )
    return [serialize_export_job(job, guild_id=guild_context.guild_id) for job in jobs]


@router.get("/jobs/{job_id}", response_model=ExportJobRead)
async def get_export_job(
    job_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> ExportJobRead:
    job = await session.get(ExportJob, job_id)
    if job is None:  # includes rows RLS hides — 404, never 403
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ExportMessages.EXPORT_JOB_NOT_FOUND,
        )
    return serialize_export_job(job, guild_id=guild_context.guild_id)


async def _require_reach(
    session: RLSSessionDep, user: User, initiative_ids: list[int]
) -> None:
    """Refuse unless the caller reaches every initiative in ``initiative_ids``
    that still exists. One deleted since the render, in the trash or purged,
    is skipped."""
    if not initiative_ids:
        return
    unreached = (
        await session.exec(
            select(func.count())
            .select_from(Initiative)
            .where(
                Initiative.id.in_(initiative_ids),
                Initiative.deleted_at.is_(None),
                not_(initiative_scope_clause(user.id, Initiative.id)),
            )
        )
    ).one()
    if unreached:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ExportMessages.EXPORT_OUT_OF_REACH,
        )


@router.get("/jobs/{job_id}/download")
async def download_export_artifact(
    job_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> Response:
    """Stream a finished export's artifact. The RLS-gated job lookup and the
    initiatives the artifact holds are the authorization, asked now rather
    than when it was rendered; storage is touched only after both pass."""
    job = await session.get(ExportJob, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ExportMessages.EXPORT_JOB_NOT_FOUND,
        )
    if artifact_expired(job):
        # Past its expiry the artifact is gone or about to be: the next GC
        # pass deletes it, and until then it is no longer served.
        raise HTTPException(
            status_code=status.HTTP_410_GONE, detail=ExportMessages.EXPORT_EXPIRED
        )
    if job.status != ExportJobStatus.done or not job.artifact_ref:
        # A delivered job is finished and has nothing to download — it was
        # written to the operator's destination, which the job row names.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ExportMessages.EXPORT_DELIVERED
            if job.destination_ref
            else ExportMessages.EXPORT_NOT_READY,
        )
    if job.initiative_ids is None:
        # Rendered before the job recorded what it holds.
        raise HTTPException(
            status_code=status.HTTP_410_GONE, detail=ExportMessages.EXPORT_EXPIRED
        )
    if job.source == "community":
        require_seat(guild_context, detail=ExportMessages.EXPORT_SUPERADMIN_REQUIRED)
    await _require_reach(session, current_user, job.initiative_ids)
    # An initiative's export is served, as it is taken, to those who manage it.
    if job.source == InitiativeExportAdapter.source:
        held = await session.exec(
            select(Initiative.actions).where(
                Initiative.id.in_(job.initiative_ids),
                Initiative.deleted_at.is_(None),
            )
        )
        if any("manage" not in (actions or ()) for actions in held):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=InitiativeMessages.MANAGER_REQUIRED,
            )
    # The backups take an initiative that keeps its content in; any other file
    # is refused once one of the initiatives it holds does.
    if job.source not in (
        InitiativeExportAdapter.source,
        GuildExportAdapter.source,
    ) and await keeps_content_in(session, job.initiative_ids):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=InitiativeMessages.CONTENT_KEPT_IN,
        )
    storage = get_guild_storage(guild_context.guild_id)
    # Recover the download name from the artifact key. A named artifact
    # (passthrough / .lexical) is stored as `exports/{job_id}-{filename}`;
    # strip the `{job_id}-` prefix back off. A generic artifact is
    # `exports/{job_id}.{format}` — no such prefix, so use the generic name.
    # build_upload_response escapes the name (RFC 5987) — original filenames
    # are user text and must not break out of the header.
    basename = job.artifact_ref.rsplit("/", 1)[-1]
    named_prefix = f"{job.id}-"
    if basename.startswith(named_prefix):
        filename = basename[len(named_prefix) :]
    else:
        filename = f"{job.source}-{job.id}.{job.format}"

    # Where the operator has turned it on and the backend can sign a URL,
    # redirect to it: the bytes then travel from the object store to the
    # client instead of through this process for the length of the download.
    # The authorization is unchanged — the checks above decided this, and the
    # URL is minted only after they passed. A filesystem backend signs nothing
    # and returns None, so those deployments keep the proxied response
    # whatever the setting says.
    signed = (
        storage.presign_get(
            job.artifact_ref,
            ttl=export_limits.EXPORT_DOWNLOAD_URL_TTL_SECONDS,
            filename=filename,
        )
        if settings.EXPORT_PRESIGNED_DOWNLOADS
        else None
    )
    if signed:
        return RedirectResponse(
            url=signed, status_code=status.HTTP_307_TEMPORARY_REDIRECT
        )

    blob = storage.open_readable(job.artifact_ref)
    if blob is None:  # GC'd or missing — fail closed
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ExportMessages.EXPORT_JOB_NOT_FOUND,
        )
    return build_upload_response(blob, filename=filename)


#: The format asked for when none is. A file has none: which formats are
#: valid depends on its type, so the caller names one.
_DEFAULT_FORMATS: dict[Tool, Optional[str]] = {
    Tool.file: None,
    Tool.calendar: "ics",
}

#: What each tool exports to, from its adapter.
_TOOL_FORMATS = {tool: ADAPTERS[tool_export_source(tool)].formats for tool in Tool}

#: Every format some tool exports, so OpenAPI carries the choices and an
#: unknown one is refused at the HTTP layer. Which of them a given tool takes
#: is its adapter's answer, which the engine checks.
_ALL_FORMATS = tuple(sorted({f for formats in _TOOL_FORMATS.values() for f in formats}))
ToolExportFormat: Any = Literal[_ALL_FORMATS]  # ty: ignore[invalid-type-form]


@router.get("/{tool}", response_model=None)
async def export_tool(
    tool: Tool,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
    ids: Optional[list[int]] = Query(
        default=None,
        description="What to export: one artifact per id, zipped when there is "
        "more than one",
    ),
    format: Optional[ToolExportFormat] = Query(
        default=None,
        description="One of the tool's export formats ("
        + "; ".join(f"{t.value}: {', '.join(f)}" for t, f in _TOOL_FORMATS.items())
        + "). ``json`` is the importable envelope. A file's formats depend on "
        "its type, so it has no default; a calendar defaults to ``ics``, every "
        "other tool to ``json``",
    ),
    initiative_id: Optional[int] = Query(
        default=None,
        description="Calendars only: with no ids, every calendar the caller may "
        "export in this initiative",
    ),
    filters: Optional[str] = Query(
        default=None,
        description="JSON object narrowing the export: the tool's own list "
        "filters, and for calendars an ``events`` date range "
        '(``{"events": {"start_after": …, "start_before": …}}``)',
    ),
    tz: Optional[str] = Query(
        default=None, max_length=64, description="IANA timezone for report timestamps"
    ),
) -> Response:
    """Export a selection of one tool's entities. Each takes the owner rung on
    it. Small selections return the file inline; large ones return ``202`` with
    a queued job to poll and download."""
    params: dict[str, Any] = {
        f"{tool.value}_ids": ids,
        "filters": _parse_json_param(filters),
        "tz": tz,
    }
    if initiative_id is not None:
        params["initiative_id"] = initiative_id
    result = await _start_export(
        session,
        current_user,
        guild_context,
        source=tool_export_source(tool),
        format=format or _DEFAULT_FORMATS.get(tool, "json") or "",
        params=params,
    )
    return _export_response(result, guild_context)
