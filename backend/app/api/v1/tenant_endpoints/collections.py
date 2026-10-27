"""Collections: groups of files in an initiative's Files.

A collection has no sharing. It is seen by whoever can open a file in it, and
changed — renamed, described, tagged, filled, emptied, trashed — by whoever's
role creates files in its initiative. Adding a file also takes being able to
open it. What is in a collection is listed by the Files list itself
(``GET /collections/{id}/files``, in ``tool_lists``).
"""

from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import selectinload
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import resource_access
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    GuildContext,
    plugin_scope,
)
from app.core.messages import CollectionMessages
from app.core.tools import KINDS, Tool
from app.db.frozen import row_is_frozen
from app.models.tenant.collection import Collection
from app.models.tenant.initiative import Initiative
from app.schemas.tenant.share_request import HiddenFiles
from app.schemas.tenant.collection import (
    MAX_FILES_PER_CHANGE,
    CollectionCan,
    CollectionCreate,
    CollectionFiles,
    CollectionListResponse,
    CollectionRead,
    CollectionUpdate,
    serialize_collection,
)
from app.services.permissions import Action
from app.services.tenant import archive as archive_service
from app.services.tenant import collections as collections_service
from app.services.tenant import properties as properties_service
from app.services.tenant import share_requests as share_requests_service
from app.services.tenant import tags as tags_service
from app.services.tenant.soft_delete import trash

router = APIRouter(route_class=ActorRoute)

#: A collection is part of Files, so a plug-in reaches it with the files scopes.
FilesRead = Annotated[ActorContext, Depends(plugin_scope("files:read"))]
FilesWrite = Annotated[ActorContext, Depends(plugin_scope("files:write"))]

_TAGS = tags_service.TAG_LINKS["collection"]


async def _require_readable(
    session: AsyncSession, initiative_id: int, file_ids: List[int]
) -> None:
    """A 422 unless every file is a live one of the initiative the reader can
    open."""
    found = await collections_service.readable_file_ids(
        session, initiative_id, file_ids
    )
    if found != set(file_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=CollectionMessages.FILE_NOT_AVAILABLE,
        )


async def _serialize(
    session: AsyncSession, rows: List[Collection], context: ActorContext
) -> List[CollectionRead]:
    cards = await collections_service.annotate(session, rows)
    # A plug-in knows of nothing it can't read, so it is asked nothing.
    hidden = (
        await share_requests_service.hidden_file_counts(
            session, user_id=context.user_id, collection_ids=[row.id for row in rows]
        )
        if isinstance(context, GuildContext)
        else {}
    )
    # The answer is the initiative's, and whether the row is put away: asked
    # once for each. Taking one out of the archive asks only after what is
    # above it, the initiative.
    editable: dict[tuple[int, bool], bool] = {}
    restorable: dict[int, bool] = {}
    reads: List[CollectionRead] = []
    for row in rows:
        key = (row.initiative_id, row_is_frozen(row))
        if key not in editable:
            editable[key] = await resource_access.may_change(session, row, context)
        archived = row.archived_at is not None
        if archived and row.initiative_id not in restorable:
            restorable[row.initiative_id] = await resource_access.may_change(
                session, row, context, action=Action.unarchive
            )
        reads.append(
            serialize_collection(
                row,
                context=context,
                file_count=cards[row.id].file_count,
                hidden_files=HiddenFiles(
                    count=hidden.get(row.id, (0, 0))[0],
                    requested=hidden.get(row.id, (0, 0))[1],
                ),
                cover=cards[row.id].cover,
                can=CollectionCan(
                    edit=editable[key],
                    unarchive=archived and restorable[row.initiative_id],
                ),
            )
        )
    return reads


async def _read(
    session: AsyncSession, collection_id: int, context: ActorContext
) -> CollectionRead:
    row = await collections_service.get_collection(
        session, collection_id, populate_existing=True
    )
    if row is None:
        raise KINDS["collection"].not_found()
    (read,) = await _serialize(session, [row], context)
    return read


@router.get("/", response_model=CollectionListResponse)
async def list_collections(
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: FilesRead,
    initiative_id: int = Query(),
    archived: Optional[bool] = Query(
        default=None, description=archive_service.ARCHIVED_QUERY_DESCRIPTION
    ),
) -> CollectionListResponse:
    """The initiative's collections the reader can see — those holding a file
    they can open — most recently changed first, each with how many of its
    files they can see and a cover they can open."""
    rows = list(
        (
            await session.exec(
                select(Collection)
                .join(Initiative, col(Initiative.id) == Collection.initiative_id)
                .where(
                    Collection.initiative_id == initiative_id,
                    archive_service.archive_filter_clause(Collection, archived),
                    col(Initiative.files_enabled).is_(True),
                )
                .options(selectinload(Collection.initiative))
                .order_by(col(Collection.updated_at).desc(), col(Collection.id).desc())
            )
        ).all()
    )
    return CollectionListResponse(items=await _serialize(session, rows, guild_context))


@router.post("/", response_model=CollectionRead, status_code=status.HTTP_201_CREATED)
async def create_collection(
    payload: CollectionCreate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: FilesWrite,
) -> CollectionRead:
    """Make a collection of files. It starts with the files named, each one a
    file of the initiative the reader can open. Takes the initiative role's
    right to create files."""
    initiative = await resource_access.prepare_create(
        session, Tool.file, payload.initiative_id, current_user, guild_context
    )
    await _require_readable(session, initiative.id, payload.file_ids)
    collection = Collection(
        initiative_id=initiative.id,
        name=payload.name.strip(),
        description=(payload.description or "").strip() or None,
        created_by=guild_context.user_id,
    )
    session.add(collection)
    await session.flush()
    await collections_service.add_files(
        session, collection, payload.file_ids, added_by=guild_context.user_id
    )
    if payload.tag_ids:
        await tags_service.set_entity_tags(
            session,
            _TAGS,
            guild_id=guild_context.guild_id,
            entity_id=collection.id,
            tag_ids=payload.tag_ids,
        )
    await properties_service.write_on_create(session, collection, payload.properties)
    await session.commit()
    return await _read(session, collection.id, guild_context)


@router.get("/{collection_id}", response_model=CollectionRead)
async def read_collection(
    collection_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: FilesRead,
) -> CollectionRead:
    await resource_access.load_child(session, Collection, collection_id)
    return await _read(session, collection_id, guild_context)


@router.patch("/{collection_id}", response_model=CollectionRead)
async def update_collection(
    collection_id: int,
    payload: CollectionUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: FilesWrite,
) -> CollectionRead:
    """Rename, describe, tag, set the cover of, or switch the comments of a
    collection."""
    collection = await resource_access.load_child(
        session, Collection, collection_id, access="write"
    )
    data = payload.model_dump(exclude_unset=True, exclude={"properties", "tag_ids"})
    if data.get("name") is not None:
        collection.name = data["name"].strip()
    if "description" in data:
        collection.description = (data["description"] or "").strip() or None
    if "cover_file_id" in data:
        cover = data["cover_file_id"]
        if cover is not None and not await collections_service.holds(
            session, collection.id, cover
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=CollectionMessages.COVER_NOT_IN_COLLECTION,
            )
        collection.cover_file_id = cover
    if data.get("comments_enabled") is not None:
        collection.comments_enabled = data["comments_enabled"]
    if payload.tag_ids is not None:
        await tags_service.set_entity_tags(
            session,
            _TAGS,
            guild_id=guild_context.guild_id,
            entity_id=collection.id,
            tag_ids=payload.tag_ids,
        )
    await properties_service.write_on_update(session, collection, payload.properties)
    collection.updated_at = datetime.now(timezone.utc)
    session.add(collection)
    await session.commit()
    return await _read(session, collection_id, guild_context)


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(
    collection_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: FilesWrite,
) -> None:
    """Send a collection to the trash. Its files stay where they are."""
    collection = await resource_access.load_child(
        session, Collection, collection_id, access="write"
    )
    await trash(session, collection, deleted_by_user_id=guild_context.user_id)
    await session.commit()


@router.post("/{collection_id}/files", response_model=CollectionRead)
async def add_collection_files(
    collection_id: int,
    payload: CollectionFiles,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: FilesWrite,
) -> CollectionRead:
    """Put files in a collection: each a file of its initiative the reader can
    open. One already in it stays as it is."""
    collection = await resource_access.load_child(
        session, Collection, collection_id, access="write"
    )
    await _require_readable(session, collection.initiative_id, payload.file_ids)
    await collections_service.add_files(
        session, collection, payload.file_ids, added_by=guild_context.user_id
    )
    await session.commit()
    return await _read(session, collection_id, guild_context)


@router.delete("/{collection_id}/files", status_code=status.HTTP_204_NO_CONTENT)
async def remove_collection_files(
    collection_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: FilesWrite,
    file_ids: Annotated[
        List[int], Query(min_length=1, max_length=MAX_FILES_PER_CHANGE)
    ],
) -> None:
    """Take files out of a collection. The files stay where they are. A
    collection left with no file goes to the trash."""
    collection = await resource_access.load_child(
        session, Collection, collection_id, access="write"
    )
    await collections_service.remove_files(session, collection, file_ids)
    await session.commit()
