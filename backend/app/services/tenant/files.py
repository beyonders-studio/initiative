from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import selectinload, undefer
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import CodedError
from app.core.search import SearchEntityType
from app.core.file_types import FileType, is_stored
from app.models.tenant.file import File
from app.models.tenant.resource_grant import ResourceGrant
from app.core.references import unresolve_wikilinks_to
from app.core.messages import FileMessages
from app.services.tenant import attachments as attachments_service
from app.services.tenant import body_states
from app.services.tenant import comments as comments_service
from app.services.tenant import content_references
from app.services.tenant import file_versions
from app.services.tenant import ownership as ownership_service
from app.services.tenant import properties as properties_service
from app.services.tenant import tags as tags_service
from app.services.tenant.collaboration import collaboration_manager, written_into
from app.db.session import routed_guild_id

if TYPE_CHECKING:  # pragma: no cover
    from app.db.guild_standing import ActorContext


def _empty_paragraph() -> dict[str, Any]:
    return {
        "children": [],
        "direction": None,
        "format": "",
        "indent": 0,
        "type": "paragraph",
        "version": 1,
    }


def _empty_state() -> dict[str, Any]:
    return {
        "root": {
            "children": [_empty_paragraph()],
            "direction": None,
            "format": "",
            "indent": 0,
            "type": "root",
            "version": 1,
        }
    }


EMPTY_LEXICAL_STATE = _empty_state()


class FileContentError(CodedError, ValueError):
    """Raised when file content fails type-specific validation, with a
    ``FileMessages`` code. Inheriting from ValueError keeps bare
    ``except ValueError`` catches working for callers that don't care about
    the structured code.
    """


def normalize_file_content(
    payload: dict[str, Any] | None,
    *,
    file_type: FileType = FileType.lexical,
) -> dict[str, Any]:
    """Normalize content JSONB based on file type.

    - lexical: ensure a Lexical root with at least one paragraph child
    - excalidraw: ensure the Excalidraw scene shape {elements, appState, files}
    - a stored type: content is just a passthrough dict (usually empty)
    """
    if is_stored(file_type):
        return payload if isinstance(payload, dict) else {}

    if file_type == FileType.excalidraw:
        if not isinstance(payload, dict):
            return {"elements": [], "appState": {}, "files": {}}
        return {
            "elements": payload.get("elements") or [],
            "appState": payload.get("appState") or {},
            "files": payload.get("files") or {},
        }

    if file_type == FileType.url:
        if not isinstance(payload, dict):
            raise FileContentError(FileMessages.SMART_LINK_URL_REQUIRED)
        url = str(payload.get("url") or "").strip()
        if not url:
            raise FileContentError(FileMessages.SMART_LINK_URL_REQUIRED)
        if not (url.startswith("http://") or url.startswith("https://")):
            raise FileContentError(FileMessages.SMART_LINK_URL_INVALID)
        return {"url": url}

    if file_type == FileType.sheet:
        # Imported lazily to avoid a circular import: files_spreadsheet
        # imports FileContentError from this module.
        from app.services.tenant.files_spreadsheet import (
            normalize_spreadsheet_content,
        )

        return normalize_spreadsheet_content(payload)

    # lexical (default)
    if not isinstance(payload, dict):
        return deepcopy(EMPTY_LEXICAL_STATE)
    root = payload.get("root")
    if not isinstance(root, dict):
        payload["root"] = deepcopy(EMPTY_LEXICAL_STATE["root"])
        return payload
    children = root.get("children")
    if not isinstance(children, list) or not children:
        root["children"] = [_empty_paragraph()]
    return payload


def list_loader_options() -> list:
    """Eager-load what a file *list* row needs: its initiative, the level
    the request holds on it, a link file's address, its sharing with the
    grant holders (the owner is reported by name), and the property values its
    card shows. Not the body, which a list does not show."""
    return [
        selectinload(File.initiative),
        undefer(File.actions),
        undefer(File.smart_link_url),
        selectinload(File.grants).selectinload(ResourceGrant.user),
    ]


async def get_file_hydrated(
    session: AsyncSession, file_id: int, *, populate_existing: bool = False
) -> File | None:
    """Load a file with everything a serialized ``FileRead`` or an
    export reads: the list loader's eager loads and the body, plus the tags,
    comment count and owning plug-in a response carries.
    :func:`get_file_for_grants` carries the list loads alone, which is what
    the access decision needs. Uniform ``(session, id)`` shape, the one ``resource_access``
    registers a loader by.
    """
    statement = (
        select(File)
        .where(File.id == file_id)
        .options(*list_loader_options(), undefer(File.content))
    )
    if populate_existing:
        # Refresh a file already in the identity map, for a re-read after a
        # commit (expire_on_commit=False otherwise keeps stale collections).
        statement = statement.execution_options(populate_existing=True)
    file = (await session.exec(statement)).one_or_none()
    if file:
        await tags_service.annotate_tags(session, [file])
        await properties_service.annotate_properties(session, [file])
        await comments_service.annotate_comment_counts(
            session, [file], column="file_id"
        )
        await ownership_service.annotate_owner_plugins(session, [file])
    return file


async def get_file_for_grants(session: AsyncSession, file_id: int) -> File | None:
    """Load a file as a list row carries it — its ``grants`` (owner
    resolution) and the level the request holds on it, without the body the
    grant flow never reads. RLS scopes the row to the request's guild, so no
    explicit guild filter. Uniform ``(session, id)`` shape so
    ``resource_access`` can register it like the others."""
    statement = select(File).where(File.id == file_id).options(*list_loader_options())
    return (await session.exec(statement)).one_or_none()


async def copy_contents(
    session: AsyncSession, source: File, copy: File, actor: ActorContext
) -> list[Any]:
    """Finish ``copy``, a duplicate of ``source`` already shared. Its pictures
    and stored file are copied rather than shared, so each file's can be
    released on its own; an uploaded file's copy starts again at version 1.
    Makes no rows inside it."""
    content = normalize_file_content(copy.content, file_type=copy.file_type)
    current = source.current_version
    file_url = current.file_url if current is not None else None
    copies = await attachments_service.copy_uploads(
        session,
        [
            *attachments_service.extract_upload_urls(content),
            copy.featured_image_url,
            file_url,
        ],
        guild_id=actor.guild_id,
        created_by=actor.user_id,
        initiative_id=copy.initiative_id,
    )

    def copied(url: str | None) -> str | None:
        return copies.get(attachments_service.normalize_upload_url(url) or "", url)

    copy.content = attachments_service.replace_upload_urls(content, copies)
    copy.featured_image_url = copied(copy.featured_image_url)
    if current is not None:
        # A plug-in is never an author: its copy names the file's uploader.
        file_versions.copy_version(
            session,
            current,
            copy,
            file_url=copied(file_url),
            created_by=actor.user_id or current.created_by,
        )
    return []


async def unresolve_wikilinks_to_file(
    session: AsyncSession,
    *,
    deleted_file_id: int,
) -> None:
    """Blank every ``[[ ]]`` pointing at a file that is being hard-purged.

    The link nodes stay and render as unresolved, which is what the editor shows
    for a link whose target was never picked. Their ``references`` edges go with
    the file itself, through the purge path's own sweep.

    Called by ``hard_purge_entity`` before the DELETEs are issued, while the
    edges naming the file are still there to find the files that carry
    those links. Trashed ones are included — a file restored after the purge
    must not come back with a dangling link.
    """

    linking_files = await content_references.referencing_files(session, deleted_file_id)

    # Files whose in-memory collaboration room has to be retired, so
    # a room's save cannot write the pre-repair content back over this.
    affected_doc_ids: list[int] = []

    for doc in linking_files:
        if doc.content and isinstance(doc.content, dict):
            updated_content = deepcopy(doc.content)
            if unresolve_wikilinks_to(updated_content, deleted_file_id):
                doc.content = updated_content
                # A session opens on the Yjs state, so the repair is written
                # into it too.
                await session.refresh(doc, ["yjs_state"])
                doc.yjs_state = await written_into(
                    body_states.LEXICAL, doc.yjs_state, updated_content
                )
                flag_modified(doc, "content")
                session.add(doc)
                affected_doc_ids.append(doc.id)

    await session.flush()

    # Invalidate any in-memory collaboration rooms for affected files
    # This prevents a room's save from overwriting our changes when users disconnect
    # Note: If a room has active collaborators, they'll have stale wikilinks until reload
    # Rooms are keyed by (guild, file), and the files above were read
    # through this session, so the guild it is routed to is theirs. An unrouted
    # session reaches no guild schema and so has no room to invalidate.
    guild_id = routed_guild_id(session)
    if guild_id is not None:
        for doc_id in affected_doc_ids:
            await collaboration_manager.invalidate_room_if_empty(
                guild_id, SearchEntityType.file.value, doc_id
            )
