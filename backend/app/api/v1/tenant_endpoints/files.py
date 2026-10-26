import asyncio
import logging
from datetime import datetime, timezone
from typing import Annotated, Any, List, Optional

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File as FormFile,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response
from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.search import SearchEntityType
from app.core.body_limit import max_document_body
from app.services.permissions import Action
from app.services.tenant import content_references
from app.services.tenant.relationships import Endpoint
from app.api.actor_route import ActorRoute
from app.api.deps import (
    CommunityIdPath,
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    IncludeDeletedDep,
    RLSSessionDep,
    plugin_scope,
    SessionDep,
    UploadUserDep,
    establish_guild_access,
    get_current_active_user,
    GuildAccessError,
    GuildContext,
    GuildContextDep,
)
from app.core.messages import (
    CommonMessages,
    FileMessages,
)
from app.core.rate_limit import limiter
from app.db.session import require_actor_context
from app.models.tenant.file import (
    File,
    FileVersion,
    FileType,
)
from app.models.platform.notification import NotificationType
from app.models.platform.user import User
from app.schemas.tenant.file import (
    FileCreate,
    FileVersionRead,
    FileRead,
    FileSummary,
    FileUpdate,
    serialize_file,
    serialize_file_summary,
    SpreadsheetImportRead,
)
from app.schemas.tenant.resource_grant import initiative_readable
from app.schemas.ai_generation import AIStreamEvent
from app.services.tenant import attachments as attachments_service
from app.services.tenant import file_versions
from app.services import storage_config
from app.services.storage import build_upload_response, get_guild_storage
from app.api import resource_access
from app.core.tools import Tool
from app.services.tenant import body_states
from app.services.tenant import comments as comments_service
from app.services.tenant import files as files_service
from app.services.tenant import ownership as ownership_service
from app.services.tenant import properties as properties_service
from app.services.tenant import tags as tags_service
from app.services.tenant.names import ensure_name_free
from app.services.tenant import tool_listing
from app.services import notifications as notifications_service
from app.services import reachability
from app.services import ai_generation
from app.services.tenant import spreadsheet_import
from app.services.tenant.collaboration import (
    collaboration_manager,
    content_version,
    current_content,
    versioned,
    written_into,
)

logger = logging.getLogger(__name__)


router = APIRouter(route_class=ActorRoute)

#: The routes an installed plug-in may call, under the files scopes.
FilesRead = Annotated[ActorContext, Depends(plugin_scope("files:read"))]
FilesWrite = Annotated[ActorContext, Depends(plugin_scope("files:write"))]


def _file_download_response(
    *, guild_id: int, version: FileVersion, inline: bool
) -> Response:
    """Build a hardened download response for one version's stored file.

    Shared by the current-file download and the per-version download so
    the filename checks and SVG/HTML response hardening can't drift
    between the two endpoints. Serves through the guild's storage backend
    (local FileResponse or S3 streaming proxy) via :func:`build_upload_response`.
    """
    content_type = version.file_content_type
    original_filename = version.original_filename
    filename = version.file_url.split("/")[-1]
    blob = get_guild_storage(guild_id).open_readable(filename)
    if blob is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    headers: dict[str, str] = {"X-Content-Type-Options": "nosniff"}
    ext = (original_filename or filename).rsplit(".", 1)[-1].lower()
    normalized_type = (content_type or "").lower()
    if (
        ext in ("svg", "html", "htm")
        or "svg" in normalized_type
        or "html" in normalized_type
    ):
        if inline:
            # Shown as a static page: sandboxed, with no scripts and no forms,
            # and framed only by the in-app file viewer on this origin.
            # X-Frame-Options set here overrides the SecurityHeadersMiddleware
            # global DENY (it uses setdefault); frame-ancestors 'self' is the
            # CSP equivalent.
            headers["Content-Security-Policy"] = (
                "sandbox; script-src 'none'; form-action 'none'; frame-ancestors 'self'"
            )
            headers["X-Frame-Options"] = "SAMEORIGIN"
        else:
            # Non-inline downloads are sent as attachments; keep the strict
            # script-src and let the global X-Frame-Options: DENY stand.
            headers["Content-Security-Policy"] = "script-src 'none'"

    if inline:
        return build_upload_response(blob, media_type=content_type, headers=headers)
    return build_upload_response(
        blob, filename=original_filename or filename, headers=headers
    )


def visible_file_conditions(
    context: ActorContext,
    user_id: int | None,
    *,
    initiative_id: Optional[int] = None,
    search: Optional[str] = None,
    tag_ids: Optional[List[int]] = None,
    untagged: Optional[bool] = None,
    is_template: Optional[bool] = None,
    file_type: Optional[FileType] = None,
):
    """WHERE conditions for visible-file queries — the list and the tag
    counts beside it, so the sidebar's numbers match the rows under them.

    The guild, the files switch, sharing, the search box and the tag filter
    are the shared set (:func:`tool_listing.base_conditions`); the rest are the
    file list's own. The archive answer is the caller's, since the tag
    counts take their own ``archived`` parameter.
    """
    conditions = tool_listing.base_conditions(
        Tool.file,
        File,
        user_id,
        context=context,
        initiative_id=initiative_id,
        search=search,
        tag_ids=tag_ids,
    )

    if is_template is not None:
        conditions.append(File.is_template == is_template)

    if file_type is not None:
        conditions.append(File.file_type == file_type)

    if untagged:
        conditions.append(
            tags_service.untagged_clause(
                tags_service.TOOL_TAG_LINKS[Tool.file], File.id
            )
        )

    return conditions


async def serialize_file_page(
    session: AsyncSession, user_id: int | None, files: list[File]
) -> list[FileSummary]:
    """Serialize one page of files — the rows a file list answers with.

    Everything a card shows beyond the row itself (its tags, its comment count)
    is a grouped query over the whole page, run
    once here rather than per row. The order is already settled by the caller
    and is preserved.

    Both file lists run this: the guild-wide one through
    ``tool_lists.TOOL_LISTS``, and the cross-guild ``/me/files`` through
    ``me_tools.MY_TOOL_LISTS``.
    """
    await tags_service.annotate_tags(session, files)
    await properties_service.annotate_properties(session, files)
    await comments_service.annotate_comment_counts(session, files, column="file_id")
    await ownership_service.annotate_owner_plugins(session, files)
    context = require_actor_context(session)
    return [
        serialize_file_summary(file, context=context, user_id=user_id) for file in files
    ]


@router.post("/", response_model=FileRead, status_code=status.HTTP_201_CREATED)
@max_document_body
async def create_file(
    file_in: FileCreate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: FilesWrite,
) -> FileRead:
    resource_access.refuse_plugin_sharing(guild_context, file_in, "grants")
    initiative = await resource_access.prepare_create(
        session, Tool.file, file_in.initiative_id, current_user, guild_context
    )
    name = file_in.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=FileMessages.NAME_REQUIRED,
        )

    await ensure_name_free(
        session,
        File.name,
        name,
        File.initiative_id == initiative.id,
        detail=FileMessages.NAME_ALREADY_EXISTS,
    )

    normalized_content = files_service.normalize_file_content(
        file_in.content,
        file_type=file_in.file_type,
    )

    file = File(
        name=name,
        initiative_id=initiative.id,
        file_type=file_in.file_type,
        content=normalized_content,
        created_by=guild_context.user_id,
        featured_image_url=file_in.featured_image_url,
        is_template=file_in.is_template,
    )
    session.add(file)
    await session.flush()

    await resource_access.grant_initial_sharing(
        session,
        guild_context,
        Tool.file,
        user=current_user,
        resource_id=file.id,
        initiative_id=initiative.id,
        payload=file_in,
        grants=file_in.grants,
    )

    # What the new body points at becomes `references` edges.
    await content_references.sync_for_entity(
        session,
        Endpoint(SearchEntityType.file, file.id),
        body=file.content,
        author_id=guild_context.user_id,
    )
    await attachments_service.claim_uploads(session, file)

    await properties_service.write_on_create(session, file, file_in.properties)
    await session.commit()
    return await read_after_write(session, file.id, current_user, guild_context)


@router.post("/upload", response_model=FileRead, status_code=status.HTTP_201_CREATED)
async def upload_file(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    name: str = Form(...),
    initiative_id: int = Form(...),
    upload: UploadFile = FormFile(..., alias="file"),
) -> FileRead:
    """Upload a file (PDF, DOCX, etc.)."""
    initiative = await resource_access.prepare_create(
        session, Tool.file, initiative_id, current_user, guild_context
    )
    name = name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=FileMessages.NAME_REQUIRED,
        )
    await ensure_name_free(
        session,
        File.name,
        name,
        File.initiative_id == initiative.id,
        detail=FileMessages.NAME_ALREADY_EXISTS,
    )
    stored = await _store_file(
        session, guild_context, upload, initiative_id=initiative.id
    )

    # Create file record. A picture is its own featured image, set here so
    # it is written with the row: the uploader's owner grant is only added
    # below, so a later UPDATE in this transaction is not theirs to make yet.
    file = File(
        name=name,
        initiative_id=initiative.id,
        content={},  # An uploaded file has no content of its own
        created_by=current_user.id,
        file_type=FileType.file,
        featured_image_url=_featured(stored["file_url"], stored["file_content_type"]),
    )
    session.add(file)
    await session.flush()

    await resource_access.grant_initial_sharing(
        session,
        guild_context,
        Tool.file,
        user=current_user,
        resource_id=file.id,
        initiative_id=initiative.id,
        payload=None,
        grants=initiative_readable(),
    )
    # The grants land before the version row: writing a version is the
    # file owner's to do, and the uploader is its owner only once the
    # grant exists.
    await session.flush()

    version = await file_versions.add_version(
        session, file, created_by=current_user.id, **stored
    )
    await file_versions.commit_version(session, guild_context.guild_id, version)
    return await read_after_write(session, file.id, current_user, guild_context)


def _normalize_mime(mime: str | None) -> str:
    """Normalize a MIME type for version type-match comparison."""
    normalized = (mime or "").lower().strip()
    if normalized == "image/jpg":
        return "image/jpeg"
    return normalized


def _featured(file_url: str, content_type: str | None) -> str | None:
    """A picture is its own featured image; any other file shows none."""
    return file_url if (content_type or "").startswith("image/") else None


async def _store_file(
    session: AsyncSession,
    guild_context: GuildContext,
    upload: UploadFile,
    *,
    initiative_id: int,
    keep_type: str | None = None,
) -> dict[str, Any]:
    """Read an uploaded file, check it and store it, and return the version
    columns it was stored as. ``keep_type`` refuses a file of another type."""
    guild_id = guild_context.guild_id
    # Pick up a backend/credential change saved in another worker before writing.
    await storage_config.ensure_storage_config_fresh(session)
    # Read the body with a hard cap so an over-limit upload is rejected before
    # the whole payload is buffered into memory.
    try:
        contents = await attachments_service.read_upload_bounded(
            upload, attachments_service.MAX_FILE_SIZE
        )
    except attachments_service.FileTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=FileMessages.FILE_TOO_LARGE,
        )
    try:
        mime_type, extension = attachments_service.validate_file(
            content=contents,
            filename=upload.filename,
            content_type=upload.content_type,
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=FileMessages.INVALID_FILE,
        )
    if keep_type is not None and _normalize_mime(mime_type) != _normalize_mime(
        keep_type
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=FileMessages.VERSION_TYPE_MISMATCH,
        )
    await attachments_service.enforce_storage_quota(
        session, guild_id=guild_id, incoming_bytes=len(contents)
    )
    file_url = await attachments_service.store_upload(
        session,
        guild_id=guild_id,
        filename=attachments_service.new_upload_filename(extension),
        data=contents,
        content_type=mime_type,
        created_by=guild_context.user_id,
        initiative_id=initiative_id,
    )
    return {
        "file_url": file_url,
        "file_content_type": mime_type,
        "file_size": len(contents),
        "original_filename": upload.filename,
    }


@router.post(
    "/{file_id}/versions",
    response_model=FileVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_file_version(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    file_id: int,
    upload: UploadFile = FormFile(..., alias="file"),
) -> FileVersionRead:
    """Upload a new version of an uploaded file. Requires write access."""
    file = await resource_access.load_authorized(
        session, Tool.file, file_id, current_user, guild_context, access="write"
    )
    if file.file_type != FileType.file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=FileMessages.NOT_AN_UPLOADED_FILE,
        )
    # A new version keeps the type of the one it replaces.
    current = file.current_version
    stored = await _store_file(
        session,
        guild_context,
        upload,
        initiative_id=file.initiative_id,
        keep_type=current.file_content_type if current is not None else None,
    )
    version = await file_versions.add_version(
        session, file, created_by=current_user.id, **stored
    )
    featured = _featured(version.file_url, version.file_content_type)
    if featured is not None:
        file.featured_image_url = featured
    await file_versions.commit_version(
        session,
        guild_context.guild_id,
        version,
        conflict=True,
    )
    return file_versions.read(FileVersionRead, version, file)


@router.get("/{file_id}/versions", response_model=List[FileVersionRead])
async def list_file_versions(
    file_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[FileVersionRead]:
    """List all stored versions of an uploaded file, newest first. Read access."""
    file = await resource_access.load_authorized(
        session, Tool.file, file_id, current_user, guild_context
    )
    if file.file_type != FileType.file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=FileMessages.NOT_AN_UPLOADED_FILE,
        )

    return [
        file_versions.read(FileVersionRead, version, file)
        for version in await file_versions.versions_newest_first(session, file)
    ]


@router.delete(
    "/{file_id}/versions/{version_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_file_version(
    file_id: int,
    version_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Delete a version of an uploaded file. Owner only. Deleting the current
    version promotes the previous one; deleting the last version is blocked."""
    file = await resource_access.load_authorized(
        session,
        Tool.file,
        file_id,
        current_user,
        guild_context,
        action=Action.delete,
    )
    if file.file_type != FileType.file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=FileMessages.NOT_AN_UPLOADED_FILE,
        )
    deleted = await file_versions.delete_version(session, file, version_id)
    # A featured image that was the deleted file follows the current one.
    current = file.current_version
    if current is not None and file.featured_image_url == deleted.file_url:
        file.featured_image_url = _featured(current.file_url, current.file_content_type)
    await session.commit()
    await file_versions.release_files(guild_context.guild_id, deleted)


@router.get("/{file_id}", response_model=FileRead)
async def read_file(
    file_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: FilesRead,
    include_deleted: IncludeDeletedDep = False,
    include_content: Annotated[
        bool,
        Query(
            description=(
                "Include the file body. Pass false for the metadata alone —"
                " a file's body is the largest thing this API returns, and a"
                " caller reacting to a change (a name, a tag, a property) does"
                " not need it. Everything else is unchanged."
            )
        ),
    ] = True,
) -> FileRead:
    file = await resource_access.load_authorized(
        session,
        Tool.file,
        file_id,
        current_user,
        guild_context,
        access="read",
        hydrated=True,
    )
    read = serialize_file(
        file,
        user_id=guild_context.user_id,
        include_content=include_content,
        context=guild_context,
    )
    if not include_content:
        return read
    return await versioned(read, guild_context.guild_id, SearchEntityType.file.value)


@router.patch("/{file_id}", response_model=FileRead)
@max_document_body
async def update_file(
    file_id: int,
    file_in: FileUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: FilesWrite,
) -> FileRead:
    file = await resource_access.load_authorized(
        session, Tool.file, file_id, current_user, guild_context, access="write"
    )
    updated = False
    update_data = file_in.model_dump(exclude_unset=True)
    removed_upload_urls: set[str] = set()
    released: set[str] = set()
    previous_featured_url = file.featured_image_url

    if "name" in update_data:
        name = (update_data["name"] or "").strip()
        if not name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=FileMessages.NAME_REQUIRED,
            )
        await ensure_name_free(
            session,
            File.name,
            name,
            File.initiative_id == file.initiative_id,
            File.id != file.id,
            detail=FileMessages.NAME_ALREADY_EXISTS,
        )
        file.name = name
        updated = True

    content_updated = False
    room = (
        collaboration_manager.live_room(
            guild_context.guild_id, SearchEntityType.file.value, file.id
        )
        if "content" in update_data
        else None
    )
    version = update_data.get("content_version")
    if room is not None and (version is None or not room.renders_content):
        # A live room is the writer of both of the file's views. A body
        # that names no version may describe one the session has moved on
        # from, and a body the browser renders is reconciled by its editors,
        # so either is refused rather than taken and reported as saved.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=CommonMessages.LIVE_SESSION_OWNS_CONTENT,
        )
    if room is not None:
        # The writer read what the session holds now: the change goes into
        # it, reaches the open editors, and is saved with their edits.
        live_content = files_service.normalize_file_content(
            update_data["content"], file_type=file.file_type
        )
        if not await room.write(live_content, version, user_id=guild_context.user_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=CommonMessages.CONTENT_CHANGED,
            )
        updated = True
    elif "content" in update_data:
        # Locked until this write commits, so a write naming the same version
        # reads this one's content.
        await session.refresh(file, ["content"], with_for_update=True)
        if version is not None and content_version(file.content) != version:
            # The writer says which content it changed. Anything since would
            # be undone by writing this whole body over it, so the write is
            # refused and the writer reads again.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=CommonMessages.CONTENT_CHANGED,
            )
        previous_content_urls = attachments_service.extract_upload_urls(file.content)
        file.content = files_service.normalize_file_content(
            update_data["content"],
            file_type=file.file_type,
        )
        new_content_urls = attachments_service.extract_upload_urls(file.content)
        removed_upload_urls.update(previous_content_urls - new_content_urls)
        # No room is live, so this edit is the newest thing about the
        # file. Its stored Yjs state has it written in, so the next
        # session opens on it with its history.
        body = body_states.for_kind(file.file_type)
        if body is not None:
            await session.refresh(file, ["yjs_state"])
            file.yjs_state = await written_into(body, file.yjs_state, file.content)
        else:
            file.yjs_state = None
        content_updated = True
        updated = True

    if "featured_image_url" in update_data:
        file.featured_image_url = update_data["featured_image_url"]
        if previous_featured_url and previous_featured_url != file.featured_image_url:
            removed_upload_urls.add(previous_featured_url)
        updated = True

    if "is_template" in update_data:
        file.is_template = bool(update_data["is_template"])
        updated = True

    if updated:
        file.updated_at = datetime.now(timezone.utc)
        session.add(file)
        if content_updated:
            await content_references.sync_for_entity(
                session,
                Endpoint(SearchEntityType.file, file.id),
                body=file.content,
                author_id=guild_context.user_id,
            )
        await attachments_service.claim_uploads(session, file)
        # What the edit took out goes once nothing else shows it. An installed
        # plug-in does not manage the community's uploads; what its edit let go of
        # stays for a person to clear.
        await session.commit()
        if current_user is not None and removed_upload_urls:
            released = await attachments_service.release_unshown(
                guild_context.guild_id, removed_upload_urls
            )
        # Invalidate any in-memory collaboration room so the next session
        # loads fresh state from the database. If a room has active
        # collaborators their in-memory state wins until they disconnect.
        if content_updated:
            await collaboration_manager.invalidate_room_if_empty(
                guild_context.guild_id, SearchEntityType.file.value, file.id
            )
    attachments_service.delete_blobs(guild_context.guild_id, released)
    return await read_after_write(session, file.id, current_user, guild_context)


@router.post("/{file_id}/mentions", status_code=status.HTTP_204_NO_CONTENT)
async def notify_mentions(
    file_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    mentioned_user_ids: List[int] = Body(..., embed=True),
) -> None:
    """Notify users that they were mentioned in a file."""
    if not mentioned_user_ids:
        return
    file = await resource_access.load_authorized(
        session, Tool.file, file_id, current_user, guild_context, access="write"
    )
    name = await notifications_service.actor_name(session, current_user)
    await notifications_service.notify(
        session,
        NotificationType.mention,
        mentioned_user_ids,
        about=(Tool.file.value, file.id),
        key="mention.file",
        values={"actor": name, "file": file.name},
        data={
            "entity_type": Tool.file.value,
            "entity_id": file.id,
            "mentioned_by_name": name,
            "mentioned_by_id": current_user.id,
        },
        actor=current_user,
        # The editor reports mentions as it saves: an unread line absorbs the
        # next report rather than mailing again.
        rollup_key=f"file-body:{file.id}",
    )
    await session.commit()


@router.post(
    "/{file_id}/ai/summary",
    response_class=ai_generation.AIStreamResponse,
    responses={200: {"model": AIStreamEvent}},
)
async def generate_summary(
    file_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ai_generation.AIStreamResponse:
    """A summary of a file, streamed as it is written.

    Requires read access to the file. Only works for native (editor)
    files.
    """
    file = await resource_access.load_authorized(
        session, Tool.file, file_id, current_user, guild_context
    )
    if file.file_type != FileType.native:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=FileMessages.AI_NATIVE_ONLY,
        )
    await session.refresh(file, ["content"])
    content = await current_content(
        guild_context.guild_id, SearchEntityType.file.value, file.id, file.content
    )
    await ai_generation.record_request(
        session,
        user=current_user,
        guild_id=guild_context.guild_id,
        purpose="summary",
        target_type="file",
        target_id=file.id,
        initiative_id=file.initiative_id,
    )
    return ai_generation.AIStreamResponse(
        await ai_generation.summarize(
            session,
            current_user,
            guild_context.guild_id,
            title=file.name,
            content=content,
        )
    )


async def read_after_write(
    session: RLSSessionDep,
    file_id: int,
    user: Optional[User],
    guild_context: ActorContext,
    *,
    populate_existing: bool = False,
) -> FileRead:
    """The file a write answers with: re-read after the commit with
    everything a ``FileRead`` reads, and serialized. ``populate_existing``
    refreshes a copy already in the session.

    Registered in ``tool_lists.TOOL_LISTS`` so the shared sharing route
    (``tool_grants.py``) answers in this tool's own shape.
    """
    file = await files_service.get_file_hydrated(
        session, file_id, populate_existing=populate_existing
    )
    if not file:
        raise await reachability.missing_or_denied(
            Tool.file,
            file_id,
            guild_context.user_id,
            guild_context.guild_id,
        )
    return await versioned(
        serialize_file(file, user_id=guild_context.user_id, context=guild_context),
        guild_context.guild_id,
        SearchEntityType.file.value,
    )


async def _load_download_file(
    session: AsyncSession, current_user, guild_id: int, file_id: int
):
    """Load an uploaded ``File`` by id from the path-addressed guild schema,
    with the eager loads the access check needs.

    Downloads are served via iframe/window.open, which can't send headers, so
    the guild rides in the ``/c/{community_id}`` path segment and names exactly the
    schema to read. Access is re-validated here (membership or live PAM grant).
    Leaves the session routed into the guild so a follow-up version query runs
    in the same schema.

    Returns ``(file, context)`` — the standing the seam computed for this
    reader in that community — or ``(None, None)`` when there's no access, no
    schema, or no such file in the addressed guild. All of those are an
    indistinguishable 404 to the caller, so existence is never confirmed across
    guilds.
    """
    from app.db.schema_provisioning import guild_schema_name

    # If the guild schema/role isn't provisioned, establish_guild_access would
    # fault rather than 404. The catalog answers
    # this for any login.
    schema_exists = (
        await session.exec(
            text("SELECT 1 FROM pg_namespace WHERE nspname = :ns"),
            params={"ns": guild_schema_name(int(guild_id))},
        )
    ).first()
    if schema_exists is None:
        return None, None

    # Route into the guild through the single entry point — same resolution and
    # applied context (membership / live PAM / break-glass, then SET ROLE +
    # standing) as REST and the realtime sockets, on the request login, so the
    # row arrives with the level this reader holds on it.
    try:
        ctx = await establish_guild_access(session, current_user, int(guild_id))
    except GuildAccessError:
        return None, None

    return await files_service.get_file_for_grants(session, file_id), ctx


@router.get("/{file_id}/download", include_in_schema=False)
@limiter.limit("30/minute")
async def download_file(
    request: Request,
    guild_id: CommunityIdPath,
    file_id: int,
    current_user: UploadUserDep,
    # SessionDep (not RLSSessionDep) because the loader routes the session
    # into the path-addressed guild's schema itself after validating access.
    session: SessionDep,
    inline: bool = False,
) -> Response:
    """Download an uploaded file — requires read permission on the file."""
    file, context = await _load_download_file(session, current_user, guild_id, file_id)
    if file is None:
        raise await reachability.missing_or_denied(
            Tool.file,
            file_id,
            int(current_user.id),
            int(guild_id),
        )
    version = file.current_version
    if file.file_type != FileType.file or version is None:
        raise Tool.file.not_found()

    resource_access.authorize(
        Tool.file, file, current_user, access="read", context=context
    )

    logger.info(
        "file_download file_id=%d user=%d inline=%s",
        file_id,
        current_user.id,
        inline,
    )
    return _file_download_response(guild_id=guild_id, version=version, inline=inline)


@router.get("/{file_id}/versions/{version_id}/download", include_in_schema=False)
@limiter.limit("30/minute")
async def download_file_version(
    request: Request,
    guild_id: CommunityIdPath,
    file_id: int,
    version_id: int,
    current_user: UploadUserDep,
    # Same rationale as download_file: the loader validates access
    # and routes the session into the path-addressed guild's schema.
    session: SessionDep,
    inline: bool = False,
) -> Response:
    """Download a specific stored version of an uploaded file — read permission."""
    file, context = await _load_download_file(session, current_user, guild_id, file_id)
    if file is None:
        raise await reachability.missing_or_denied(
            Tool.file,
            file_id,
            int(current_user.id),
            int(guild_id),
        )
    if file.file_type != FileType.file:
        raise Tool.file.not_found()

    resource_access.authorize(
        Tool.file, file, current_user, access="read", context=context
    )

    version_result = await session.exec(
        select(FileVersion).where(
            FileVersion.id == version_id,
            FileVersion.file_id == file_id,
        )
    )
    version = version_result.one_or_none()
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CommonMessages.VERSION_NOT_FOUND,
        )

    logger.info(
        "file_version_download file_id=%d version_id=%d user=%d inline=%s",
        file_id,
        version_id,
        current_user.id,
        inline,
    )
    return _file_download_response(guild_id=guild_id, version=version, inline=inline)


@router.post(
    "/{file_id}/spreadsheet/import",
    response_model=SpreadsheetImportRead,
)
async def import_spreadsheet_file(
    file_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    upload: UploadFile = FormFile(..., alias="file"),
) -> SpreadsheetImportRead:
    """Read a CSV/XLSX file into sheets, for the caller to add to this workbook.

    The file is the permission scope rather than the destination — nothing
    here writes to it. The sheets go back to the editor, which adds them to the
    live document in a single transaction, so the whole import is one thing to
    undo and peers receive it as one change.

    Parsing is server-side for the same reason rendering is: the workbook
    libraries are here, and the result goes through the same normalizer a
    created spreadsheet does, so an imported sheet is the same kind of object
    as any other.
    """
    file = await resource_access.load_authorized(
        session, Tool.file, file_id, current_user, guild_context, access="write"
    )
    if file.file_type != FileType.spreadsheet:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=FileMessages.SPREADSHEET_INVALID_PAYLOAD,
        )

    # Bounded read, so an over-sized file is refused before it is buffered.
    try:
        contents = await attachments_service.read_upload_bounded(
            upload, attachments_service.MAX_FILE_SIZE
        )
    except attachments_service.FileTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=FileMessages.FILE_TOO_LARGE,
        )

    # Parsing a workbook is CPU work, so it runs off the event loop.
    sheets = await asyncio.to_thread(
        spreadsheet_import.parse_spreadsheet_file, upload.filename or "", contents
    )

    return SpreadsheetImportRead(sheets=sheets)
