"""Import endpoints: envelopes, foreign-source files, Jira, and backup restores.

Every route here writes, so every route re-checks that the community is
writable. The engine behind them is shared: whatever file or site the work
arrived from, it becomes an envelope, and one apply path puts the rows in.

NOTE: the job routes use literal paths plus a parametric ``/{job_id}``; every
literal route MUST stay declared before the parametric ones.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from sqlmodel import select

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    require_seat,
    GuildContextDep,
)
from app.core.body_limit import MULTIPART_SLACK_BYTES, max_body
from app.core.messages import ImportEngineMessages
from app.core.version import get_version
from app.models.platform.user import User
from app.models.tenant.import_job import ImportJob, ImportJobStatus
from app.schemas.tenant.atlassian import (
    AtlassianConnectRequest,
    AtlassianConnectResponse,
    AtlassianImportRequest,
)
from app.schemas.tenant.import_job import (
    EnvelopeImportRequest,
    EnvelopeImportResponse,
    ForeignImportRequest,
    ForeignPreview,
    ForeignSourceOption,
    ImportJobRead,
    serialize_import_job,
)
from app.services.import_engine import atlassian as atlassian_service
from app.services.import_engine import atlassian_job
from app.services.import_engine import backup as backup_service
from app.services.import_engine import engine as import_engine
from app.services.import_engine import envelope_archive
from app.services.import_engine import foreign as foreign_service
from app.services.import_engine.contract import (
    InlineImport,
)
from app.services.import_engine.engine import (
    spooled_upload,
)
from app.services.import_engine import limits as import_limits

logger = logging.getLogger(__name__)

router = APIRouter()


_LIST_LIMIT = 50

#: The most property names one confirm may untick.
_MAX_EXCLUDED_PROPERTIES = 500

#: The most an Atlassian connect or import request may carry. A connect is a
#: site URL, an account's address and an API token; a start is a credential
#: id, an initiative and at most 200 short project keys. Generous for either
#: and still far too small to be worth anybody's while as a buffer.
ATLASSIAN_MAX_REQUEST_BYTES = 16 * 1024


def _envelope_bytes() -> int:
    return import_limits.IMPORT_MAX_ENVELOPE_BYTES


def _upload_bytes() -> int:
    """A backup, a Confluence space's HTML export, or one tool's export zipped
    with its files, and the framing multipart adds around it."""
    return import_limits.IMPORT_MAX_BACKUP_UPLOAD_BYTES + MULTIPART_SLACK_BYTES


def _require_writable(guild_context: GuildContext) -> None:
    """Imports are writes, always — no inline carve-out for read-only actors
    (the inverse of the export engine's read-friendly inline path). A guild in
    read_only lifecycle can't author rows, and neither can a grantee: a grant
    reaches existing content, whatever level it carries."""
    if guild_context.content_read_only or guild_context.is_pam:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ImportEngineMessages.IMPORT_WRITE_REQUIRED,
        )


@router.post("/envelope", response_model=None, status_code=status.HTTP_201_CREATED)
@max_body(_envelope_bytes, ImportEngineMessages.IMPORT_TOO_LARGE)
async def import_envelope(
    payload: EnvelopeImportRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Response:
    """Import a previously-exported JSON envelope (any tool — the envelope's
    ``type`` field selects the importer) into the chosen initiative. Requires
    the tool's create permission there.

    Small envelopes apply immediately and return ``201`` with the result.
    Anything else returns ``202`` with a job: ``queued`` for one that is
    merely large, or ``staged`` for one quoting people nobody here can place,
    whose ``plan`` names them and which starts on
    ``POST /imports/jobs/{id}/confirm``."""
    # Byte bound (IMPORT_MAX_ENVELOPE_BYTES, declared by ``max_body``) is
    # enforced by BodySizeLimitMiddleware at the ASGI seam — a handler-level
    # check would run only after FastAPI had already buffered and parsed the
    # body.
    _require_writable(guild_context)
    outcome = await import_engine.start_envelope_import(
        session,
        user=current_user,
        guild_id=guild_context.guild_id,
        initiative_id=payload.initiative_id,
        envelope=payload.envelope,
    )

    if isinstance(outcome, InlineImport):
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content=EnvelopeImportResponse(result=outcome.result).model_dump(
                mode="json"
            ),
        )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=serialize_import_job(
            outcome, guild_id=guild_context.guild_id
        ).model_dump(mode="json"),
    )


@router.post(
    "/envelope/archive", response_model=None, status_code=status.HTTP_201_CREATED
)
@max_body(_upload_bytes, ImportEngineMessages.IMPORT_TOO_LARGE)
async def import_envelope_archive(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    file: UploadFile = File(...),
    initiative_id: int = Form(...),
    envelope_type: Optional[str] = Form(
        default=None,
        description="The envelope type the import was started for; a zip "
        "holding another tool's export is refused",
    ),
) -> Response:
    """Import an export that travels as a zip — a catalog with its pictures —
    into the chosen initiative. The zip holds one envelope at its top level and
    the files it names under ``assets/``; the files are stored first, then the
    envelope imports exactly as ``POST /imports/envelope`` imports one, with
    the same responses."""
    _require_writable(guild_context)
    async with spooled_upload(
        file.file, max_bytes=import_limits.IMPORT_MAX_BACKUP_UPLOAD_BYTES
    ) as payload:
        outcome = await envelope_archive.start_envelope_archive_import(
            session,
            user=current_user,
            guild_id=guild_context.guild_id,
            initiative_id=initiative_id,
            payload=payload,
            expected_type=envelope_type,
        )

    if isinstance(outcome, InlineImport):
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content=EnvelopeImportResponse(result=outcome.result).model_dump(
                mode="json"
            ),
        )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=serialize_import_job(
            outcome, guild_id=guild_context.guild_id
        ).model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------
# Imports from another product's export file
# ---------------------------------------------------------------------------


@router.post("/foreign/{source}/preview", response_model=ForeignPreview)
@max_body(_envelope_bytes, ImportEngineMessages.IMPORT_TOO_LARGE)
async def preview_foreign_import(
    source: str,
    content: Annotated[str, Body(media_type="text/plain")],
    _current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ForeignPreview:
    """Say what an uploaded export holds, without keeping any of it.

    Nothing is written and nothing is staged: the file is read, described,
    and forgotten. The description is what the wizard needs to ask its one
    question — which list, or what to call this — and the answer comes back
    with the file itself on the import.

    Writable membership, like every other import entry point: this reads
    somebody's file on the community's behalf, and a community nobody can
    write to has nothing to read it for.
    """
    _require_writable(guild_context)
    foreign_source = foreign_service.get_source(source)
    options = foreign_service.read_preview(foreign_source, content)
    return ForeignPreview(
        source=foreign_source.key,
        picks_one=foreign_source.picks_one,
        options=[
            ForeignSourceOption(
                key=option.key, name=option.name, task_count=option.task_count
            )
            for option in options
        ],
    )


@router.post(
    "/foreign/{source}", response_model=None, status_code=status.HTTP_201_CREATED
)
@max_body(_envelope_bytes, ImportEngineMessages.IMPORT_TOO_LARGE)
async def import_foreign(
    source: str,
    payload: ForeignImportRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Response:
    """Import the chosen part of another product's export.

    The file becomes the envelope a project export writes, and from there it
    is an ordinary import: the same ceilings, the same people step, the same
    worker, the same report. Nothing past this point knows which product the
    rows came from.

    Answers exactly as ``/imports/envelope`` does — 201 with the counts when
    it applied in the request, 202 with the job when it did not.
    """
    _require_writable(guild_context)
    foreign_source = foreign_service.get_source(source)
    mapped = foreign_service.build(
        foreign_source,
        payload.content,
        selection=payload.selection,
        app_version=get_version(),
    )
    started = await import_engine.start_envelope_import(
        session,
        user=current_user,
        guild_id=guild_context.guild_id,
        initiative_id=payload.initiative_id,
        envelope=mapped.envelope,
    )

    if isinstance(started, InlineImport):
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content=EnvelopeImportResponse(result=started.result).model_dump(
                mode="json"
            ),
        )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=serialize_import_job(
            started, guild_id=guild_context.guild_id
        ).model_dump(mode="json"),
    )


@router.post(
    "/atlassian/connect",
    response_model=AtlassianConnectResponse,
    status_code=status.HTTP_201_CREATED,
)
@max_body(lambda: ATLASSIAN_MAX_REQUEST_BYTES, ImportEngineMessages.IMPORT_TOO_LARGE)
async def connect_atlassian(
    payload: AtlassianConnectRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> AtlassianConnectResponse:
    """Prove an Atlassian API token and say what the site holds.

    One request, because the two questions are the same one: the only honest
    proof that a token works is using it, so connecting *is* the first
    listing. It returns the Jira projects and Confluence spaces the token can
    see, with rough counts.

    Nothing is kept. The token is used for the length of this request and
    dropped; the request that actually starts an import carries it again, and
    that one has a job row to hold it on.

    Real membership of a writable guild, like every other import entry point.
    Which initiative the work lands in is not asked here and not trusted from
    here — the target and the create permission for it are resolved on the
    start, and again by the worker at apply time.
    """
    _require_writable(guild_context)
    if guild_context.grant is not None:
        # A break-glass or support grant reaches existing content; it does not
        # get to make this server talk to somebody else's on its behalf.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ImportEngineMessages.IMPORT_WRITE_REQUIRED,
        )

    credential = atlassian_service.AtlassianCredential(
        site_url=atlassian_service.normalize_site_url(payload.site_url),
        email=payload.email.strip(),
        api_token=payload.api_token,
    )
    jira, confluence = await atlassian_service.probe_site(credential)

    return AtlassianConnectResponse(
        site_url=credential.site_url,
        jira=jira,
        confluence=confluence,
    )


@router.post(
    "/atlassian/import",
    response_model=ImportJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
@max_body(lambda: ATLASSIAN_MAX_REQUEST_BYTES, ImportEngineMessages.IMPORT_TOO_LARGE)
async def start_atlassian_import(
    payload: AtlassianImportRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ImportJobRead:
    """Start reading Jira projects and Confluence spaces into an initiative.

    One job for both: projects arrive as projects, each space as a wiki, and
    a link between an issue and a page read together is joined when the
    bundle is applied. Carries the same token the connect proved, stored
    encrypted on the job row and cleared the moment that job is over. The job
    comes back ``queued``; the worker moves it to ``fetching`` while it reads
    the site, filling ``plan.atlassian`` with counts as it goes, and parks it
    at ``staged`` with the full plan — the people both products name included
    — for ``POST /imports/jobs/{id}/confirm``.

    The initiative needs projects switched on for projects, wikis for spaces,
    and the caller needs to be able to create them there. That is checked
    now, again before the site is read, and again when the bundle is applied."""
    _require_writable(guild_context)
    if guild_context.grant is not None:
        # A grant reaches existing content, not this server's outbound
        # connections.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ImportEngineMessages.IMPORT_WRITE_REQUIRED,
        )
    job = await atlassian_job.start_import(
        session,
        user=current_user,
        guild_id=guild_context.guild_id,
        credential=atlassian_service.AtlassianCredential(
            site_url=atlassian_service.normalize_site_url(payload.site_url),
            email=payload.email.strip(),
            api_token=payload.api_token,
        ),
        initiative_id=payload.initiative_id,
        project_keys=payload.project_keys,
        space_keys=payload.space_keys,
        include_comments=payload.include_comments,
        include_attachments=payload.include_attachments,
    )
    return serialize_import_job(job, guild_id=guild_context.guild_id)


@router.post(
    "/atlassian/export",
    response_model=ImportJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
@max_body(_upload_bytes, ImportEngineMessages.IMPORT_TOO_LARGE)
async def start_confluence_export_import(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    file: UploadFile = File(...),
    initiative_id: int = Form(...),
    include_attachments: bool = Form(True),
) -> ImportJobRead:
    """Start reading a Confluence space's HTML export into an initiative.

    The zip Confluence's "Export space → HTML" writes, for a site this server
    cannot reach or somebody would rather not hand a token to. It is staged
    and the job comes back ``queued``; the worker converts it the way it reads
    a site, and parks it at ``staged`` with the same plan for
    ``POST /imports/jobs/{id}/confirm``. The initiative needs wikis switched on
    and the caller able to create one there."""
    _require_writable(guild_context)
    if guild_context.grant is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ImportEngineMessages.IMPORT_WRITE_REQUIRED,
        )
    async with spooled_upload(
        file.file, max_bytes=import_limits.IMPORT_MAX_BACKUP_UPLOAD_BYTES
    ) as payload:
        job = await atlassian_job.start_export(
            session,
            user=current_user,
            guild_id=guild_context.guild_id,
            initiative_id=initiative_id,
            payload=payload,
            include_attachments=include_attachments,
        )
    return serialize_import_job(job, guild_id=guild_context.guild_id)


@router.get("/jobs", response_model=list[ImportJobRead])
async def list_import_jobs(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> list[ImportJobRead]:
    """The caller's import jobs, newest first (RLS scopes the rows: own rows,
    or the whole guild for a guild admin)."""
    jobs = await session.exec(
        select(ImportJob).order_by(ImportJob.created_at.desc()).limit(_LIST_LIMIT)
    )
    return [serialize_import_job(job, guild_id=guild_context.guild_id) for job in jobs]


@router.get("/jobs/{job_id}", response_model=ImportJobRead)
async def get_import_job(
    job_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ImportJobRead:
    job = await session.get(ImportJob, job_id)
    if job is None:  # includes rows RLS hides — 404, never 403
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ImportEngineMessages.IMPORT_JOB_NOT_FOUND,
        )
    return serialize_import_job(job, guild_id=guild_context.guild_id)


@router.delete("/jobs/{job_id}", response_model=ImportJobRead)
async def cancel_import_job(
    job_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ImportJobRead:
    """Cancel a job that hasn't started applying (staged, queued, or still
    fetching from its source); its staged payload is deleted. A fetch writes
    nothing but that payload, so stopping one mid-read is safe — the worker
    notices at the next project and throws away what it had. A running or
    terminal job is not cancellable — 409 (an interrupted apply would leave
    half-committed content). The row is locked, as the worker locks it to
    claim, so the status read here is the one the cancel replaces."""
    job = await session.get(ImportJob, job_id, with_for_update=True)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ImportEngineMessages.IMPORT_JOB_NOT_FOUND,
        )
    if job.status not in (
        ImportJobStatus.staged,
        ImportJobStatus.queued,
        ImportJobStatus.fetching,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ImportEngineMessages.IMPORT_NOT_CANCELLABLE,
        )
    await asyncio.to_thread(
        import_engine.delete_payload, guild_context.guild_id, job.payload_ref
    )
    # Everything the job was lent goes back with the payload — a cancelled
    # import has no further use for the secret it was given.
    job.secret_encrypted = None
    job.status = ImportJobStatus.cancelled
    job.payload_ref = None
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return serialize_import_job(job, guild_id=guild_context.guild_id)


# ---------------------------------------------------------------------------
# Backup-zip imports (guild admin only)
# ---------------------------------------------------------------------------


@router.post(
    "/backup", response_model=ImportJobRead, status_code=status.HTTP_201_CREATED
)
@max_body(_upload_bytes, ImportEngineMessages.IMPORT_TOO_LARGE)
async def upload_backup(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    file: UploadFile = File(...),
) -> ImportJobRead:
    """Upload a backup zip and get its pre-flight plan. The zip is staged in
    guild storage and the job parked as ``staged`` (nothing is imported yet);
    ``POST /imports/jobs/{id}/confirm`` starts the apply. Unconfirmed staged
    backups expire after IMPORT_STAGED_TTL_HOURS. The community's seat only."""
    require_seat(guild_context, detail=ImportEngineMessages.IMPORT_SUPERADMIN_REQUIRED)
    _require_writable(guild_context)
    guild_id = guild_context.guild_id

    # Byte cap: BodySizeLimitMiddleware already rejected an oversized or
    # chunked-over-cap request at the ASGI seam; the bounded copy to a
    # temporary file is the in-process backstop.
    async with spooled_upload(
        file.file, max_bytes=import_limits.IMPORT_MAX_BACKUP_UPLOAD_BYTES
    ) as payload:
        job = await backup_service.stage_backup_job(
            session,
            guild_id=guild_id,
            user=current_user,
            payload=payload,
            status=ImportJobStatus.staged,
        )
    await session.commit()
    await session.refresh(job)
    return serialize_import_job(job, guild_id=guild_context.guild_id)


@router.post("/jobs/{job_id}/confirm", response_model=ImportJobRead)
async def confirm_import(
    job_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    body: Optional[dict] = None,
) -> ImportJobRead:
    """Confirm a staged import: flips it to ``queued`` for the worker.

    Optional body ``{"include": {tool: bool}}`` narrows which tools apply
    (backup only; omitted tools default to included), and ``{"people_map":
    {handle: user id}}`` says who each name the archive quotes is here — the
    answers to the wizard's people step. ``{"exclude_properties": [name]}``
    names properties unticked on the review, which are then not created, and
    whose values are left out with them. All are recorded on the job and read
    at apply time; the mapping is re-checked against real membership there,
    because this confirm may be hours old by then.

    Two kinds of job reach this, and they are gated differently because they
    were created differently. A **backup** puts a whole community back, so it
    is the seat only — re-checked here and again at apply time. A lone
    **envelope** is one thing its creator already had the create permission
    for when they dropped it; it is staged only to ask who the handles in it
    are, so that creator is the one who answers, and nobody else confirms on
    their behalf."""
    _require_writable(guild_context)
    job = await session.get(ImportJob, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ImportEngineMessages.IMPORT_JOB_NOT_FOUND,
        )
    if job.source == "backup":
        require_seat(
            guild_context, detail=ImportEngineMessages.IMPORT_SUPERADMIN_REQUIRED
        )
    elif job.created_by != current_user.id:
        # RLS lets a guild admin read the row; answering somebody else's
        # people step is a different thing from being able to see it.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ImportEngineMessages.IMPORT_NOT_CONFIRMABLE,
        )
    if job.status != ImportJobStatus.staged:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ImportEngineMessages.IMPORT_NOT_CONFIRMABLE,
        )
    # A staged job whose TTL already elapsed is expired NOW, not silently on
    # GC's next pass: confirming it would return 200 and then vanish queued
    # (GC sweeps expired queued rows too) with no notification.
    now = datetime.now(timezone.utc)
    if job.expires_at is not None and job.expires_at <= now:
        await asyncio.to_thread(
            import_engine.delete_payload, guild_context.guild_id, job.payload_ref
        )
        job.secret_encrypted = None
        job.status = ImportJobStatus.expired
        job.payload_ref = None
        session.add(job)
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ImportEngineMessages.IMPORT_NOT_CONFIRMABLE,
        )
    include = (body or {}).get("include") if job.source == "backup" else None
    if include is not None:
        if not isinstance(include, dict) or not all(
            isinstance(v, bool) for v in include.values()
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ImportEngineMessages.IMPORT_INVALID_PARAMS,
            )
        job.params = {**(job.params or {}), "include": include}
    people_map = (body or {}).get("people_map")
    if people_map is not None:
        if not isinstance(people_map, dict) or not all(
            isinstance(handle, str) and isinstance(user_id, int)
            for handle, user_id in people_map.items()
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ImportEngineMessages.IMPORT_INVALID_PARAMS,
            )
        # Stored as given; the ids are proved to be members of this guild at
        # apply time, on the session that will actually write the rows.
        job.params = {**(job.params or {}), "people_map": people_map}
    exclude_properties = (body or {}).get("exclude_properties")
    if exclude_properties is not None:
        # The review's unticked properties, by the names the plan listed.
        # Bounded like any list a request supplies: a few hundred short names
        # is more than any plan carries.
        if (
            not isinstance(exclude_properties, list)
            or len(exclude_properties) > _MAX_EXCLUDED_PROPERTIES
            or not all(
                isinstance(name, str) and 0 < len(name) <= 255
                for name in exclude_properties
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ImportEngineMessages.IMPORT_INVALID_PARAMS,
            )
        job.params = {**(job.params or {}), "exclude_properties": exclude_properties}
    job.status = ImportJobStatus.queued
    # Fresh TTL window: the confirmed job now waits on the worker, and a
    # nearly-elapsed staging TTL must not let GC sweep it out of the queue.
    job.expires_at = now + timedelta(hours=import_limits.IMPORT_STAGED_TTL_HOURS)
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return serialize_import_job(job, guild_id=guild_context.guild_id)
