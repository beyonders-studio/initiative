"""Catalog endpoints — a collection of pictures in an initiative.

Creation is gated at the initiative level (catalogs_enabled + create_catalogs);
everything after that flows from the catalog's resource-grant DAC
(``resource_grants`` + ``PUT /{id}/grants``), like every other tool.

Two things here are the catalog's own rather than the generic tool shape:

* **Pictures are content, not tools.** A picture is reached only through its
  catalog — ``/catalogs/{id}/images/…`` — and adding, replacing or removing
  one asks for **write** access on the catalog, the way editing a task asks
  for write on its project. Deleting a stored *version* asks for the owner,
  because it destroys history rather than editing the present.
* **The picture list scrolls.** It pages in forties and takes an ``until``
  anchor, so the client fetches ahead of the reader and a timeline rail can
  jump a long catalog to a month without paging through everything since —
  the same arrangement a board has.

Uploads are validated from their bytes alone: the format and pixel size are
read from the header and the client's ``Content-Type`` is not consulted. Only
after that does anything decode a pixel — to make the thumbnail, boxed so a
picture that cannot be thumbnailed is still stored.
"""

from datetime import datetime, timezone
from typing import Annotated, Any, List, Optional, cast

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import resource_access
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    GuildContextDep,
    IncludeDeletedDep,
    RLSSessionDep,
    get_current_active_user,
    plugin_scope,
)
from app.core.messages import (
    ImageMessages,
    CatalogMessages,
)
from app.core.tools import KINDS, Tool
from app.db.query import apply_pagination, build_paginated_response
from app.models.platform.user import User
from app.models.tenant.catalog import Catalog, CatalogItem, CatalogItemVersion
from app.schemas.base import MentionStr
from app.schemas.tenant.catalog import (
    CatalogCreate,
    CatalogItemBulkDelete,
    CatalogItemBulkDeleteResponse,
    CatalogItemListResponse,
    CatalogItemRead,
    CatalogItemUpdate,
    CatalogItemVersionRead,
    CatalogRead,
    CatalogUpdate,
    serialize_catalog_item,
)
from app.schemas.tenant.tool import serialize_tool
from app.schemas.tenant.timeline import TimelineResponse
from app.services.permissions import Action
from app.services import storage_config
from app.services.tenant import attachments as attachments_service
from app.services.tenant import overwrites
from app.services.tenant import file_versions
from app.services.tenant import catalogs as catalogs_service
from app.services.tenant import plugin_metadata
from app.services.tenant import properties as properties_service
from app.services.tenant import tags as tags_service
from app.services.tenant import timeline as timeline_service

#: How many pictures one page carries. A picture is a thumbnail and a few
#: fields, so this is generous — the point is that the grid fetches the next
#: page as somebody nears the bottom, not that anyone pages by hand.
IMAGE_PAGE_SIZE = 40
MAX_IMAGE_PAGE_SIZE = 200

router = APIRouter(route_class=ActorRoute)
#: An item's own routes, mounted at the guild root: an event envelope names an
#: item by its own id, so it is addressable without its catalog. Only listing
#: and adding name the catalog.
items_router = APIRouter(route_class=ActorRoute)

#: The routes an installed plug-in may call, under the catalogs scopes.
CatalogsRead = Annotated[ActorContext, Depends(plugin_scope("catalogs:read"))]
CatalogsWrite = Annotated[ActorContext, Depends(plugin_scope("catalogs:write"))]
CurrentUserDep = Annotated[User, Depends(get_current_active_user)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _refetch_item(session: RLSSessionDep, item_id: int) -> CatalogItem:
    item = await resource_access.reload_child(session, CatalogItem, item_id)
    await catalogs_service.annotate_version_counts(session, [item])
    return item


async def _read_picture(
    session: RLSSessionDep,
    guild_context: ActorContext,
    file: UploadFile,
) -> tuple[bytes, str, str, int, int, catalogs_service.Thumbnail | None]:
    """Read and validate an upload, then render its thumbnail.

    Returns the picture's bytes, content type, extension and pixel size, and
    the thumbnail (``None`` where one was not made). The size is Pillow's
    where a thumbnail was made — it has applied the EXIF orientation the
    header check cannot see — and the header's otherwise.
    """
    try:
        contents = await attachments_service.read_upload_bounded(
            file, catalogs_service.MAX_IMAGE_BYTES
        )
    except attachments_service.FileTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=CatalogMessages.IMAGE_TOO_LARGE,
        )
    try:
        header, extension = catalogs_service.validate_image(contents)
    except catalogs_service.EmptyImageError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ImageMessages.IMAGE_EMPTY,
        )
    except catalogs_service.InvalidImageError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ImageMessages.IMAGE_INVALID,
        )

    # The second half of the gate: a header says what a file claims, and the
    # decode says whether it is one. A refusal here is the same 400 a bad
    # header gets — the caller sent something that is not a picture.
    try:
        thumbnail = catalogs_service.render_thumbnail(contents)
    except catalogs_service.InvalidImageError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ImageMessages.IMAGE_INVALID,
        )
    width, height = (
        (thumbnail.source_width, thumbnail.source_height)
        if thumbnail is not None
        else (header.width, header.height)
    )
    incoming = len(contents) + (len(thumbnail.data) if thumbnail else 0)
    await attachments_service.enforce_storage_quota(
        session, guild_id=guild_context.guild_id, incoming_bytes=incoming
    )
    return contents, header.content_type, extension, width, height, thumbnail


async def _store_blob(
    session: RLSSessionDep,
    guild_context: ActorContext,
    catalog: Catalog,
    contents: bytes,
    extension: str,
    content_type: str,
) -> str:
    """Store one blob of ``catalog``'s and return its served URL."""
    return await attachments_service.store_upload(
        session,
        guild_id=guild_context.guild_id,
        filename=attachments_service.new_upload_filename(extension),
        data=contents,
        content_type=content_type,
        created_by=guild_context.user_id,
        initiative_id=catalog.initiative_id,
    )


async def _store_picture(
    session: RLSSessionDep,
    guild_context: ActorContext,
    catalog: Catalog,
    file: UploadFile,
) -> dict[str, Any]:
    """Read, check and store an uploaded picture and its thumbnail, and return
    the version columns they were stored as."""
    # Pick up a backend/credential change saved in another worker before writing.
    await storage_config.ensure_storage_config_fresh(session)
    contents, mime, extension, width, height, thumb = await _read_picture(
        session, guild_context, file
    )
    file_url = await _store_blob(
        session, guild_context, catalog, contents, extension, mime
    )
    thumbnail_url = (
        await _store_blob(
            session,
            guild_context,
            catalog,
            thumb.data,
            thumb.extension,
            thumb.content_type,
        )
        if thumb is not None
        else None
    )
    return {
        "file_url": file_url,
        "thumbnail_url": thumbnail_url,
        "file_content_type": mime,
        "file_size": len(contents),
        "original_filename": file.filename,
        "width": width,
        "height": height,
    }


def _item_scope(
    catalog: Catalog,
    *,
    tag_ids: Optional[List[int]],
    search: Optional[str],
) -> list:
    """Which of a catalog's pictures a request is asking about.

    Sharing was settled on the catalog — reaching this means reaching every
    picture in it — so the legs here only narrow: the catalog, the tag
    filter, and the search box. Tags are ANY-of: "everything still awaiting a
    decision" is one tag, and asking for two is asking for either.
    """
    conditions = [CatalogItem.catalog_id == catalog.id]
    if tag_ids:
        conditions.append(
            CatalogItem.id.in_(
                tags_service.tagged_entity_ids(
                    tags_service.TAG_LINKS["catalog_item"], tuple(tag_ids)
                )
            )
        )
    if search and search.strip():
        needle = f"%{search.strip()}%"
        conditions.append(
            func.coalesce(CatalogItem.title, "").ilike(needle)
            | func.coalesce(CatalogItem.caption, "").ilike(needle)
            | CatalogItem.current_version.has(
                CatalogItemVersion.original_filename.ilike(needle)
            )
        )
    return conditions


# ---------------------------------------------------------------------------
# Catalogs
# ---------------------------------------------------------------------------


@router.get("/{catalog_id}", response_model=CatalogRead)
async def read_catalog(
    catalog_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CatalogsRead,
    include_deleted: IncludeDeletedDep = False,
) -> CatalogRead:
    catalog = await resource_access.load_authorized(
        session, Tool.catalog, catalog_id, current_user, guild_context, hydrated=True
    )
    return serialize_tool(
        CatalogRead, catalog, user_id=guild_context.user_id, context=guild_context
    )


@router.post("/", response_model=CatalogRead, status_code=status.HTTP_201_CREATED)
async def create_catalog(
    catalog_in: CatalogCreate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CatalogsWrite,
) -> CatalogRead:
    """Create a catalog. Requires create_catalogs permission on the
    initiative (or guild admin); the creator gets the owner grant."""
    resource_access.refuse_plugin_sharing(guild_context, catalog_in, "grants")
    initiative = await resource_access.prepare_create(
        session, Tool.catalog, catalog_in.initiative_id, current_user, guild_context
    )

    catalog = Catalog(
        initiative_id=initiative.id,
        created_by=guild_context.user_id,
        name=catalog_in.name.strip(),
        description=(catalog_in.description or "").strip() or None,
    )
    session.add(catalog)
    await session.flush()

    await resource_access.grant_initial_sharing(
        session,
        guild_context,
        Tool.catalog,
        user=current_user,
        resource_id=catalog.id,
        initiative_id=initiative.id,
        payload=catalog_in,
        grants=catalog_in.grants,
    )
    if catalog_in.tag_ids:
        await tags_service.set_entity_tags(
            session,
            tags_service.TOOL_TAG_LINKS[Tool.catalog],
            guild_id=guild_context.guild_id,
            entity_id=catalog.id,
            tag_ids=catalog_in.tag_ids,
        )
    await attachments_service.claim_uploads(session, catalog)
    await properties_service.write_on_create(session, catalog, catalog_in.properties)
    await session.commit()
    return await read_after_write(session, catalog.id, current_user, guild_context)


@router.patch("/{catalog_id}", response_model=CatalogRead)
async def update_catalog(
    catalog_id: int,
    catalog_in: CatalogUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CatalogsWrite,
) -> CatalogRead:
    """Rename, describe, or choose the cover. Requires write access."""
    catalog = await resource_access.load_authorized(
        session, Tool.catalog, catalog_id, current_user, guild_context, access="write"
    )
    update_data = catalog_in.model_dump(exclude_unset=True)
    updated = False

    if "name" in update_data and update_data["name"] is not None:
        catalog.name = update_data["name"].strip()
        updated = True
    if "description" in update_data:
        catalog.description = (update_data["description"] or "").strip() or None
        updated = True
    if "cover_item_id" in update_data:
        cover_id = update_data["cover_item_id"]
        if cover_id is not None:
            cover = await session.exec(
                select(CatalogItem.id).where(
                    CatalogItem.id == cover_id, CatalogItem.catalog_id == catalog.id
                )
            )
            if cover.one_or_none() is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=CatalogMessages.COVER_NOT_IN_CATALOG,
                )
        catalog.cover_item_id = cover_id
        updated = True

    if updated:
        catalog.updated_at = datetime.now(timezone.utc)
        session.add(catalog)
        await attachments_service.claim_uploads(session, catalog)
        await session.commit()

    return await read_after_write(session, catalog.id, current_user, guild_context)


async def read_after_write(
    session: RLSSessionDep,
    catalog_id: int,
    user: Optional[User],
    guild_context: ActorContext,
) -> CatalogRead:
    """The catalog a write answers with: re-read after the commit, serialized.

    Registered in ``tool_lists.TOOL_LISTS`` so the shared sharing route
    (``tool_grants.py``) answers in this tool's own shape.
    """
    hydrated = await catalogs_service.get_catalog_hydrated(
        session, catalog_id, populate_existing=True
    )
    if hydrated is None:
        raise Tool.catalog.not_found()
    return serialize_tool(
        CatalogRead, hydrated, user_id=guild_context.user_id, context=guild_context
    )


# ---------------------------------------------------------------------------
# Pictures
# ---------------------------------------------------------------------------


@router.get("/{catalog_id}/items", response_model=CatalogItemListResponse)
async def list_catalog_items(
    catalog_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CatalogsRead,
    tag_ids: Optional[List[int]] = Query(
        default=None, description="Only pictures carrying ANY of these tags."
    ),
    search: Optional[str] = Query(
        default=None, description="Match on title, caption or filename."
    ),
    oldest_first: bool = Query(
        default=False,
        description="Read the catalog in the order it was filled rather than newest first.",
    ),
    until: Optional[datetime] = Query(
        default=None,
        description=(
            "Start the list at this instant, inclusive, measured by upload "
            "time — which is what the list is ordered by. This is how a "
            "timeline jumps to a month without paging through everything "
            "since. It follows the list's own direction: newest first it is a "
            "ceiling and the page walks back from it, oldest first a floor "
            "and the page walks forward, so pair it with the matching end of "
            "the timeline bucket."
        ),
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=IMAGE_PAGE_SIZE, ge=1, le=MAX_IMAGE_PAGE_SIZE),
) -> CatalogItemListResponse:
    """One page of a catalog's pictures, newest first.

    Reaching the catalog is the whole gate: its pictures are its content, so
    there is no per-picture sharing to consult.
    """
    catalog = await resource_access.load_authorized(
        session, Tool.catalog, catalog_id, current_user, guild_context
    )
    conditions = _item_scope(catalog, tag_ids=tag_ids, search=search)
    if until is not None:
        conditions.append(
            catalogs_service.anchored_clause(until, oldest_first=oldest_first)
        )

    count_subq = select(CatalogItem.id).where(*conditions).subquery()
    total_count = (
        await session.exec(select(func.count()).select_from(count_subq))
    ).one()

    stmt = apply_pagination(
        select(CatalogItem)
        .where(*conditions)
        .options(*catalogs_service.item_loader_options())
        .order_by(*catalogs_service.item_order(oldest_first=oldest_first)),
        page,
        page_size,
    )
    items = list((await session.exec(stmt)).unique().all())
    await tags_service.annotate_tags(session, items)
    await properties_service.annotate_properties(session, items)
    await catalogs_service.annotate_version_counts(session, items)
    items = [serialize_catalog_item(i, context=guild_context) for i in items]
    return CatalogItemListResponse(
        **build_paginated_response(items, total_count, page, page_size)
    )


@router.get("/{catalog_id}/items/timeline", response_model=TimelineResponse)
async def get_catalog_item_timeline(
    catalog_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CatalogsRead,
    tag_ids: Optional[List[int]] = Query(default=None),
    search: Optional[str] = Query(default=None),
    tz: Optional[str] = Query(
        default=None,
        description=(
            "IANA zone the month boundaries are cut in, e.g. Pacific/Auckland. "
            "Defaults to UTC."
        ),
    ),
) -> TimelineResponse:
    """The months this catalog has pictures in, newest first — what the
    timeline rail is drawn from. Takes the same filters the list does, so the
    rail is a picture of the list as it currently stands."""
    catalog = await resource_access.load_authorized(
        session, Tool.catalog, catalog_id, current_user, guild_context
    )
    conditions = _item_scope(catalog, tag_ids=tag_ids, search=search)
    return TimelineResponse(
        buckets=await timeline_service.month_buckets(
            session, date_expr=CatalogItem.created_at, conditions=conditions, tz=tz
        )
    )


@router.post(
    "/{catalog_id}/items",
    response_model=CatalogItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_catalog_item(
    catalog_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CatalogsWrite,
    file: UploadFile = File(...),
    title: Optional[str] = Form(default=None),
    caption: Annotated[Optional[MentionStr], Form()] = None,
) -> CatalogItemRead:
    """Add one picture to a catalog. Requires write access.

    One picture per request, so a drop of forty files is forty requests the
    client can run a few at a time and report on one by one — and one that
    fails does not take the other thirty-nine with it.
    """
    catalog = await resource_access.load_authorized(
        session, Tool.catalog, catalog_id, current_user, guild_context, access="write"
    )
    stored = await _store_picture(session, guild_context, catalog, file)

    now = datetime.now(timezone.utc)
    item = CatalogItem(
        catalog_id=catalog.id,
        title=(title or "").strip()[:255] or None,
        caption=(caption or "").strip() or None,
        created_by=guild_context.user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(item)
    await session.flush()
    version = await file_versions.add_version(
        session, item, created_by=guild_context.user_id, **stored
    )
    # A catalog that just gained a picture has changed, and the list orders by
    # that.
    catalog.updated_at = now
    session.add(catalog)
    await file_versions.commit_version(session, guild_context.guild_id, version)

    hydrated = await _refetch_item(session, item.id)
    return serialize_catalog_item(hydrated, context=guild_context)


@items_router.get("/catalog-items/{item_id}", response_model=CatalogItemRead)
async def read_catalog_item(
    item_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CatalogsRead,
) -> CatalogItemRead:
    item = await resource_access.load_child(session, CatalogItem, item_id)
    await catalogs_service.annotate_version_counts(session, [item])
    return await _serialized_item(session, item, guild_context)


async def _serialized_item(
    session: AsyncSession, item: CatalogItem, context: ActorContext
) -> CatalogItemRead:
    """One picture as its own read answers it: with the plug-ins' values on it."""
    values = await plugin_metadata.values_on(
        session, "catalog_item", {item.id: cast(Catalog, item.catalog).initiative_id}
    )
    return serialize_catalog_item(
        item, context=context, plugin_values=values.get(item.id, ())
    )


@items_router.patch("/catalog-items/{item_id}", response_model=CatalogItemRead)
async def update_catalog_item(
    item_id: int,
    item_in: CatalogItemUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CatalogsWrite,
) -> CatalogItemRead:
    """Retitle, caption, retag or set the properties of a picture. Requires
    write access on the catalog."""
    item = await resource_access.load_child(
        session, CatalogItem, item_id, access="write"
    )
    if "caption_base" in item_in.model_fields_set:
        await overwrites.refuse_written_over(
            session, item, "caption", item_in.caption_base
        )
    update_data = item_in.model_dump(exclude_unset=True, exclude={"caption_base"})
    if "title" in update_data:
        item.title = (update_data["title"] or "").strip() or None
    if "caption" in update_data:
        item.caption = (update_data["caption"] or "").strip() or None
    if "tag_ids" in update_data and update_data["tag_ids"] is not None:
        await tags_service.set_entity_tags(
            session,
            tags_service.TAG_LINKS["catalog_item"],
            guild_id=guild_context.guild_id,
            entity_id=item.id,
            tag_ids=update_data["tag_ids"],
        )
    await properties_service.write_on_update(session, item, item_in.properties)
    item.updated_at = datetime.now(timezone.utc)
    session.add(item)
    await attachments_service.claim_uploads(session, item)
    await session.commit()
    hydrated = await _refetch_item(session, item.id)
    return await _serialized_item(session, hydrated, guild_context)


@items_router.delete("/catalog-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_catalog_item(
    item_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> None:
    """Send a picture to the trash. Requires write access on the catalog —
    removing a picture is editing the catalog, and it can be restored."""
    from app.services.tenant.soft_delete import trash

    item = await resource_access.load_child(
        session, CatalogItem, item_id, access="write"
    )
    catalog = cast(Catalog, item.catalog)
    await trash(
        session,
        item,
        deleted_by_user_id=guild_context.user_id,
    )
    if catalog.cover_item_id == item.id:
        # The list falls back to the newest picture rather than a trashed one.
        catalog.cover_item_id = None
        session.add(catalog)
    await session.commit()


@router.post(
    "/{catalog_id}/items/bulk-delete",
    response_model=CatalogItemBulkDeleteResponse,
)
async def bulk_delete_catalog_items(
    catalog_id: int,
    payload: CatalogItemBulkDelete,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> CatalogItemBulkDeleteResponse:
    """Send a selection of pictures to the trash in one transaction. Requires
    write access on the catalog — the same gate removing one asks — and
    refuses the whole request if any id is not one of this catalog's own,
    rather than trashing the rest and reporting a partial success."""
    from app.services.platform import guilds as guilds_service
    from app.services.tenant.soft_delete import soft_delete_entity

    catalog = await resource_access.load_authorized(
        session, Tool.catalog, catalog_id, current_user, guild_context, access="write"
    )
    ids = list(dict.fromkeys(payload.item_ids))
    items = list(
        (
            await session.exec(
                select(CatalogItem).where(
                    CatalogItem.catalog_id == catalog.id, CatalogItem.id.in_(ids)
                )
            )
        ).all()
    )
    if len(items) != len(ids):
        raise KINDS["catalog_item"].not_found()
    retention_days = await guilds_service.get_guild_retention_days(session)
    for item in items:
        await soft_delete_entity(
            session,
            item,
            deleted_by_user_id=guild_context.user_id,
            retention_days=retention_days,
        )
    if catalog.cover_item_id in ids:
        catalog.cover_item_id = None
        session.add(catalog)
    await session.commit()
    return CatalogItemBulkDeleteResponse(deleted_count=len(items))


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


@items_router.post(
    "/catalog-items/{item_id}/versions",
    response_model=CatalogItemVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_catalog_item_version(
    item_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CatalogsWrite,
    file: UploadFile = File(...),
) -> CatalogItemVersionRead:
    """Replace a picture with a new rendition, keeping the old one as history.
    Requires write access on the catalog."""
    item = await resource_access.load_child(
        session, CatalogItem, item_id, access="write"
    )
    stored = await _store_picture(session, guild_context, item.catalog, file)
    version = await file_versions.add_version(
        session, item, created_by=guild_context.user_id, **stored
    )
    await file_versions.commit_version(
        session,
        guild_context.guild_id,
        version,
        conflict=True,
    )
    return file_versions.read(CatalogItemVersionRead, version, item)


@items_router.get(
    "/catalog-items/{item_id}/versions",
    response_model=List[CatalogItemVersionRead],
)
async def list_catalog_item_versions(
    item_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CatalogsRead,
) -> List[CatalogItemVersionRead]:
    """Every stored rendition of a picture, newest first."""
    item = await resource_access.load_child(session, CatalogItem, item_id)
    return [
        file_versions.read(CatalogItemVersionRead, version, item)
        for version in await file_versions.versions_newest_first(session, item)
    ]


@items_router.delete(
    "/catalog-items/{item_id}/versions/{version_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_catalog_item_version(
    item_id: int,
    version_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CatalogsWrite,
) -> None:
    """Delete one rendition of a picture. Owner only. Deleting the current
    one promotes the previous; deleting the last is refused — remove the
    picture instead."""
    item = await resource_access.load_child(
        session, CatalogItem, item_id, action=Action.delete
    )
    deleted = await file_versions.delete_version(session, item, version_id)
    await session.commit()
    await file_versions.release_files(guild_context.guild_id, deleted)
