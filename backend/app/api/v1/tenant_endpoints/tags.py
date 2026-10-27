from datetime import datetime, timezone
from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, literal, union_all
from sqlalchemy import update as sa_update
from sqlalchemy.orm import selectinload, undefer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import resource_access
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    IncludeDeletedDep,
    RLSSessionDep,
    SessionDep,
    plugin_scope,
    get_current_active_user,
    GuildContextDep,
)
from app.core.plugin_scopes import tool_resource
from app.core.messages import PluginMessages, TagMessages
from app.api.v1.tenant_endpoints.tool_lists import TOOL_LISTS, view_conditions
from app.core.tools import KINDS, Tool
from app.models.tenant.initiative import Initiative
from app.db.guild_standing import GuildContext, InstallContext
from app.db.initiative_rls import governing_path
from app.db.query import build_paginated_response, paginated_query
from app.models.tenant._mixins import ArchiveMixin
from app.models.tenant.tag import Tag
from app.models.platform.user import User
from app.services.tenant import tags as tags_service
from app.services.tenant.archive import archive_filter_clause
from app.services.tenant.names import ensure_name_free
from app.services.tenant.soft_delete import trash
from app.schemas.tenant.tag import (
    TagBulkEditRequest,
    TagBulkEditResponse,
    TagCreate,
    TagEntityCountsResponse,
    TagRead,
    TagTarget,
    serialize_tag,
    TagUpdate,
    TaggedEntitiesResponse,
    TaggedEntity,
)

# The tag dictionary is a guild-wide folksonomy BY DESIGN: every guild member
# (initiative membership not required) may list, create, rename, recolor, and
# trash tags, so the only gate here is guild membership. Hard purge alone is
# admin-gated (the RESTRICTIVE RLS policy on ``tags``). Pinned by
# ``test_any_guild_member_can_manage_the_tag_dictionary``.
router = APIRouter(route_class=ActorRoute)

#: The routes an installed plug-in may call, under the tags scopes.
TagsRead = Annotated[ActorContext, Depends(plugin_scope("tags:read"))]
TagsWrite = Annotated[ActorContext, Depends(plugin_scope("tags:write"))]


def _governing(
    spec: tags_service.TagLinkSpec,
) -> tuple[Tool, tuple[tuple[str, str], ...]]:
    """The tool whose sharing governs a taggable kind, and the join chain from
    the kind's table to it — ``()`` where the row is the tool itself. Read from
    the registry the kind's RLS policy is rendered from."""
    governed = governing_path(str(spec.entity.__tablename__))
    if governed is None:  # pragma: no cover - every tag target has a tool
        raise RuntimeError(f"no single tool governs {spec.entity.__tablename__!r}")
    return governed


def _require_install_tagging_scopes(actor: ActorContext, target: str) -> None:
    """Raise 403 unless an installed plug-in's standing also holds what tagging
    ``target`` writes beside the tag: the write scope of the tool that governs
    the tagged thing, and ``relationships:write`` for the assignment itself,
    which is stored as a relationship. A person passes."""
    if not isinstance(actor, InstallContext):
        return
    tool = KINDS[target].tool
    needed = ["relationships:write", f"{tool_resource(tool).value}:write"]
    if not all(actor.holds(scope) for scope in needed):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PluginMessages.SCOPE_REQUIRED,
        )


async def _get_tag_or_404(session: SessionDep, tag_id: int, guild_id: int) -> Tag:
    """Fetch a tag by ID, ensuring it belongs to the specified guild."""
    stmt = select(Tag).where(Tag.id == tag_id)
    result = await session.exec(stmt)
    tag = result.one_or_none()
    if tag is None:
        raise KINDS["tag"].not_found()
    return tag


@router.get("/", response_model=List[TagRead])
async def list_tags(
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: TagsRead,
) -> list[TagRead]:
    """List all tags in the current guild."""
    stmt = select(Tag).order_by(Tag.name.asc())
    result = await session.exec(stmt)
    return [serialize_tag(tag, guild_id=guild_context.guild_id) for tag in result.all()]


@router.post("/", response_model=TagRead, status_code=status.HTTP_201_CREATED)
async def create_tag(
    tag_in: TagCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> TagRead:
    """Create a new tag in the current guild."""
    await ensure_name_free(
        session, Tag.name, tag_in.name, detail=TagMessages.NAME_ALREADY_EXISTS
    )

    tag = Tag(
        name=tag_in.name.strip(),
        color=tag_in.color,
    )
    session.add(tag)
    await session.commit()
    await session.refresh(tag)
    return serialize_tag(tag, guild_id=guild_context.guild_id)


@router.post("/bulk", response_model=TagBulkEditResponse)
async def bulk_edit_tags(
    payload: TagBulkEditRequest,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: TagsWrite,
) -> TagBulkEditResponse:
    """Add and/or remove tags across many entities of one type, atomically.

    Every target is authorized with write on the tool that governs it, read
    from the registry its RLS policy is rendered from: a tool row asks itself,
    a sub-resource (a task, a queue item, a wiki page, …) asks its parent tool.
    Nothing is applied unless every target passes — one transaction, and a
    parent tool's ``updated_at`` moves once for all of its sub-resources rather
    than once per row.
    """
    target = payload.target_type.value
    _require_install_tagging_scopes(guild_context, target)
    spec = tags_service.TAG_LINKS[target]
    add_ids = await tags_service.validate_guild_tag_ids(
        session, guild_context.guild_id, payload.add_tag_ids
    )
    remove_ids = list(dict.fromkeys(payload.remove_tag_ids))
    target_ids = list(dict.fromkeys(payload.target_ids))

    if KINDS[target].standalone:
        # Answers for itself: each is changed by its own rule.
        for entity_id in target_ids:
            await resource_access.load_child(
                session, spec.entity, entity_id, access="write"
            )
    else:
        tool, chain = _governing(spec)
        parent_ids = target_ids
        if chain:
            ((parent_fk, _parent_table),) = chain
            rows = (
                await session.exec(
                    select(spec.entity.id, getattr(spec.entity, parent_fk)).where(
                        spec.entity.id.in_(target_ids)
                    )
                )
            ).all()
            if len(rows) != len(target_ids):
                raise KINDS[target].not_found()
            parent_ids = list(dict.fromkeys(parent_id for _, parent_id in rows))
        # One load for every governing row, with what the decision reads: the
        # actions the database answered and the initiative's switches.
        parent = tags_service.TOOL_TAG_LINKS[tool].entity
        loaded = {
            row.id: row
            for row in (
                await session.exec(
                    select(parent)
                    .where(parent.id.in_(parent_ids))
                    .options(selectinload(parent.initiative), undefer(parent.actions))
                )
            ).all()
        }
        for parent_id in parent_ids:
            row = loaded.get(parent_id)
            if row is None:
                # Out of sight: the single loader names the refusal — 404, or 403
                # to a reader in the initiative whom sharing refused.
                await resource_access.load_authorized(
                    session,
                    tool,
                    parent_id,
                    current_user,
                    guild_context,
                    access="write",
                )
            else:
                resource_access.authorize(
                    tool, row, current_user, context=guild_context, access="write"
                )
        if chain:
            await session.exec(
                sa_update(parent)
                .where(parent.id.in_(parent_ids))
                .values(updated_at=datetime.now(timezone.utc))
            )

    await tags_service.bulk_edit_tags(
        session,
        spec,
        entity_ids=target_ids,
        add_tag_ids=add_ids,
        remove_tag_ids=remove_ids,
    )
    await session.commit()

    return TagBulkEditResponse(updated_count=len(target_ids))


@router.get("/{tag_id}", response_model=TagRead)
async def get_tag(
    tag_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    include_deleted: IncludeDeletedDep = False,
) -> TagRead:
    """Get a specific tag by ID."""
    tag = await _get_tag_or_404(session, tag_id, guild_context.guild_id)
    return serialize_tag(tag, guild_id=guild_context.guild_id)


@router.patch("/{tag_id}", response_model=TagRead)
async def update_tag(
    tag_id: int,
    tag_in: TagUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> TagRead:
    """Update a tag's name or color."""
    tag = await _get_tag_or_404(session, tag_id, guild_context.guild_id)

    update_data = tag_in.model_dump(exclude_unset=True)
    if "name" in update_data and update_data["name"] is not None:
        await ensure_name_free(
            session,
            Tag.name,
            update_data["name"],
            Tag.id != tag.id,
            detail=TagMessages.NAME_ALREADY_EXISTS,
        )
        tag.name = update_data["name"].strip()

    if "color" in update_data and update_data["color"] is not None:
        tag.color = update_data["color"]

    tag.updated_at = datetime.now(timezone.utc)
    session.add(tag)
    await session.commit()
    await session.refresh(tag)
    return serialize_tag(tag, guild_id=guild_context.guild_id)


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Soft-delete a tag. The tag moves to the guild's trash; junction rows
    stay in place (reads hide them via the soft-delete filter) and fall with
    the tag's ORM relationship cascade on hard purge."""
    tag = await _get_tag_or_404(session, tag_id, guild_context.guild_id)
    await trash(
        session,
        tag,
        deleted_by_user_id=current_user.id,
    )
    await session.commit()


async def _tagged_conditions(
    kind: str,
    tag_id: int,
    session: AsyncSession,
    current_user: User,
    guild_context: GuildContext,
) -> list:
    """The WHERE for the things of one kind carrying ``tag_id``, as the tag's
    page lists them.

    A tool's row is narrowed exactly as the tool's own community-wide list
    narrows its ``active`` view, so a tab's count and the table under it agree.
    A sub-resource is shared as part of its tool, so it is listed only when its
    parent passes that same list, and leaves out its own archive where it has
    one.
    """
    spec = tags_service.TAG_LINKS[kind]
    model = spec.entity
    if KINDS[kind].standalone:
        # No tool row to pass a list: the reader's policies on the row decide
        # whether it is listed, beside its tool's switch.
        tool = KINDS[kind].tool
        return [
            model.id.in_(tags_service.tagged_entity_ids(spec, [tag_id])),
            archive_filter_clause(model, None),
            model.initiative_id.in_(
                select(Initiative.id).where(
                    getattr(Initiative, tool.view_permission).is_(True)
                )
            ),
        ]
    tool, chain = _governing(spec)
    tool_list = TOOL_LISTS[tool]
    if not chain:
        return await view_conditions(
            tool_list,
            session,
            current_user,
            guild_context,
            **tool_list.views["active"],
            tag_ids=[tag_id],
        )
    parents = select(tool_list.model.id).where(
        *await view_conditions(
            tool_list,
            session,
            current_user,
            guild_context,
            **tool_list.views["active"],
        )
    )
    conditions = [
        model.id.in_(tags_service.tagged_entity_ids(spec, [tag_id])),
        getattr(model, chain[0][0]).in_(parents),
    ]
    if issubclass(model, ArchiveMixin):
        conditions.append(archive_filter_clause(model, None))
    return conditions


@router.get("/{tag_id}/counts", response_model=TagEntityCountsResponse)
async def get_tag_counts(
    tag_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> TagEntityCountsResponse:
    """How many things of each taggable kind carry this tag, in one statement.

    A tag reaches across every initiative in the community, so this counts
    what has been shared with the reader — the same rule the community-wide
    tool lists and the ``/me/*`` views follow. A guild admin's authority over
    any one initiative is unchanged; it is asked about by opening that
    initiative, not by opening a tag. Each figure is the ``total_count`` of
    the list the tag's page shows for that kind.
    """
    tag = await _get_tag_or_404(session, tag_id, guild_context.guild_id)
    selects = [
        select(literal(kind), func.count())
        .select_from(spec.entity)
        .where(
            *await _tagged_conditions(
                kind, tag.id, session, current_user, guild_context
            )
        )
        for kind, spec in tags_service.TAG_LINKS.items()
    ]
    rows = (await session.exec(union_all(*selects))).all()
    return TagEntityCountsResponse(
        counts={kind: count for kind, count in rows if count}
    )


@router.get("/{tag_id}/entities", response_model=TaggedEntitiesResponse)
async def get_tag_entities(
    tag_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    kind: Annotated[TagTarget, Query(description="The taggable kind to list")],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> TaggedEntitiesResponse:
    """One page of the things of one kind carrying this tag, by name.

    Shared with the reader on the same rule as ``GET /tags/{id}/counts``, whose
    figure for ``kind`` is this list's ``total_count``. Each row names itself
    and the tool it lives in, the way a search hit does, which is everything a
    client needs to address it.
    """
    tag = await _get_tag_or_404(session, tag_id, guild_context.guild_id)
    spec = tags_service.TAG_LINKS[kind.value]
    model = spec.entity
    label = getattr(model, model.display_field())
    standalone = KINDS[kind.value].standalone
    if standalone:
        # In no one instance of a tool: it names none.
        tool, chain, parent = None, (), model
        tool_id, parent_label = literal(None), literal("")
    else:
        tool, chain = _governing(spec)
        parent = tags_service.TOOL_TAG_LINKS[tool].entity
        tool_id = getattr(model, chain[0][0]) if chain else model.id
        parent_label = getattr(parent, parent.display_field())
    updated_at = getattr(model, "updated_at", None)
    conditions = await _tagged_conditions(
        kind.value, tag.id, session, current_user, guild_context
    )

    statement = (
        select(
            model.id,
            label,
            parent.initiative_id,
            tool_id,
            parent_label,
            updated_at if updated_at is not None else literal(None),
        )
        .select_from(model)
        .where(*conditions)
        .order_by(func.lower(label), model.id)
    )
    if chain:
        statement = statement.join(parent, parent.id == tool_id)
    count_statement = select(func.count()).select_from(model).where(*conditions)
    rows, total_count, page = await paginated_query(
        session, statement, count_statement, page, page_size
    )
    items = [
        TaggedEntity(
            entity_type=spec.kind,
            entity_id=entity_id,
            title=title or "",
            initiative_id=initiative_id,
            tool=tool,
            tool_id=parent_id,
            tool_title=parent_title or "",
            updated_at=changed_at,
        )
        for entity_id, title, initiative_id, parent_id, parent_title, changed_at in rows
    ]
    return TaggedEntitiesResponse(
        **build_paginated_response(items, total_count, page, page_size)
    )
