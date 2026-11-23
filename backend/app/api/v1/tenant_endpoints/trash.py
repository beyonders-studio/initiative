"""Trash-can endpoints: list / restore / immediate-purge.

Guild routes operate on the guild in the ``/c/{community_id}`` path; the
cross-guild ``/me/trash`` view (see ``me_trash.py``) spans the user's guilds.
A guild's listing is one statement: a UNION ALL over the trashable models,
each leg selecting only the columns a :class:`TrashItem` carries, ordered and
paged in SQL, with the deleter's name joined onto the page.

Cascade dedup: children whose parent was cascaded-trashed at the same
``deleted_at`` (over the same edges the cascade walks) are filtered out so the trash table doesn't list 200 tasks
under a deleted project — just the project. Restoring the parent
resurfaces the children automatically (see ``soft_delete.py``).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import (
    Subquery,
    Table,
    Text,
    and_,
    cast,
    func,
    literal,
    select,
    union_all,
)
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    GuildContext,
    GuildContextDep,
    RLSSessionDep,
    get_current_active_user,
    require_surface,
)
from app.core.audit_events import AuditEventType
from app.core.messages import TrashMessages
from app.core.tool_set import BUILTIN_TOOLS, KEPT_TOOL_SETS, ToolSet
from app.core.user_display import display_name
from app.db.base import MODELS_BY_TABLE
from app.db.query import build_paginated_response
from app.db.session import routed_tools
from app.db.soft_delete_filter import select_including_deleted
from app.db.tool_rows import load_row, locate
from app.models.platform.guild import AdminSurface
from app.models.platform.user import User, UserStatus
from app.models.platform.user_profile_view import MemberProfile
from app.models.tenant._mixins import ActorKind
from app.models.tenant.comment import Comment
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.task import Task
from app.schemas.tenant.trash import (
    RestoreResponse,
    TrashItem,
    TrashListResponse,
)
from app.services import audit as audit_service
from app.services.platform import guilds as guilds_service
from app.services.tenant import attachments as attachments_service
from app.services.tenant import column_limits, content_references
from app.services.tenant import ownership as ownership_service
from app.services.tenant.lifecycle_tree import cascade_parents, trash_kinds
from app.services.tenant.soft_delete import (
    hard_purge_entity,
    restore_entity,
)

router = APIRouter()


@lru_cache(KEPT_TOOL_SETS)
def entity_registry(tools: ToolSet) -> dict[str, tuple[Table, str]]:
    """Wire name -> (table, the column that labels its rows), for every kind
    with the trash in a community with ``tools``: a model's
    ``display_field``, and a tool plug-in's row its name."""
    return {
        kind: (table, model.display_field() if model else "name")  # type: ignore[attr-defined]
        for kind, table in trash_kinds(tools).items()
        for model in (MODELS_BY_TABLE.get(table.name),)
    }


#: :func:`entity_registry` of the built-in tools.
ENTITY_REGISTRY: dict[str, tuple[Table, str]] = entity_registry(BUILTIN_TOOLS)


#: A trash listing's page window.
TrashPage = Annotated[int, Query(ge=1)]
TrashPageSize = Annotated[int, Query(ge=1, le=100)]

_NAME_LIMIT = 80


def _truncate(value: str, *, limit: int = _NAME_LIMIT) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def _trashed(tools: ToolSet, only_deleted_by: int | None) -> Subquery:
    """This guild's trash listing, one UNION ALL leg per trashable table of a
    community with ``tools``.

    ``only_deleted_by`` narrows to one user's deletions (the personal view);
    ``None`` lists everything (the admin view).
    """
    upwards = cascade_parents(tools)
    legs = []
    for entity_type, (table, name_field) in entity_registry(tools).items():
        leg = select(
            literal(entity_type, Text).label("entity_type"),
            table.c.id.label("entity_id"),
            # One character past the limit is enough to tell a name was cut.
            func.left(cast(table.c[name_field], Text), _NAME_LIMIT + 1).label("name"),
            table.c.deleted_at,
            table.c.deleted_by,
            table.c.deleted_by_kind,
            table.c.purge_at,
        ).where(table.c.deleted_at.is_not(None))
        if only_deleted_by is not None:
            leg = leg.where(
                table.c.deleted_by_kind == ActorKind.member,
                table.c.deleted_by == only_deleted_by,
            )

        # Cascade dedup: exclude children whose parent (any of them) is also
        # trashed at the same deleted_at — they come back with it, and one of
        # them restored alone would sit under a parent that is still in the
        # bin. Alias the parent — required when the parent is the same table as
        # the child (Comment threaded replies via parent_comment_id), otherwise
        # unaliased ``Comment.id == Comment.parent_comment_id`` references the
        # same row in both clauses.
        for edge in upwards.get(table, []):
            parent = edge.table.alias()
            leg = leg.where(
                ~select(parent.c.id)
                .where(edge.ties(table, parent))
                .where(parent.c.deleted_at == table.c.deleted_at)
                .exists()
            )
        legs.append(leg)
    return union_all(*legs).subquery("trashed")


def _newest_first(rows: Subquery) -> tuple:
    """Most recently trashed first; kind then id, both descending, break a tie.

    The kind compares bytewise, which is how :func:`page_across_guilds` compares
    it when ``/me/trash`` merges guilds."""
    return (
        rows.c.deleted_at.desc(),
        rows.c.entity_type.collate("C").desc(),
        rows.c.entity_id.desc(),
    )


def _deleted_by_display(row) -> str:
    # Initiative and an uninstalled plug-in are named by the client.
    if row.deleted_by_kind != ActorKind.member:
        return row.plugin_name or ""
    if row.deleted_by is None:
        return "Deleted user"
    # Mirror frontend getUserDisplayName: anonymized rows have wiped PII, so
    # we surface the id rather than the empty/synthetic name fields.
    if row.profile_id is None or row.status == UserStatus.anonymized:
        return f"Deleted user #{row.deleted_by}"
    return display_name(row) or f"User #{row.deleted_by}"


async def trash_page(
    session: AsyncSession,
    guild_id: int,
    *,
    only_deleted_by: int | None,
    limit: int,
    offset: int = 0,
) -> tuple[list[TrashItem], int]:
    """One window of a guild's trash, newest first, and how much it holds.

    The deleter's name is joined onto the window alone, read through the
    guild's own member view so it is named the way the guild names people.
    """
    trashed = _trashed(routed_tools(session), only_deleted_by)
    window = (
        select(trashed)
        .order_by(*_newest_first(trashed))
        .limit(limit)
        .offset(offset)
        .subquery("page_rows")
    )
    rows = await session.exec(
        select_including_deleted(
            window,
            MemberProfile.id.label("profile_id"),
            MemberProfile.status,
            MemberProfile.display_name,
            MemberProfile.username,
            MemberProfile.discriminator,
            GuildPlugin.name.label("plugin_name"),
        )
        .select_from(window)
        .outerjoin(
            MemberProfile,
            and_(
                window.c.deleted_by_kind == ActorKind.member,
                MemberProfile.id == window.c.deleted_by,
            ),
        )
        .outerjoin(
            GuildPlugin,
            and_(
                window.c.deleted_by_kind == ActorKind.plugin,
                GuildPlugin.id == window.c.deleted_by,
            ),
        )
        .order_by(*_newest_first(window))
    )
    items = [
        TrashItem(
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            community_id=guild_id,
            name=_truncate(row.name or ""),
            deleted_at=row.deleted_at,
            deleted_by_id=row.deleted_by,
            deleted_by_kind=row.deleted_by_kind,
            deleted_by_display=_deleted_by_display(row),
            purge_at=row.purge_at,
        )
        for row in rows
    ]
    count = await session.exec(
        select_including_deleted(func.count()).select_from(trashed)
    )
    return items, count.one()


@router.get("/", response_model=TrashListResponse)
async def list_community_trash(
    session: RLSSessionDep,
    guild_context: Annotated[
        GuildContext, Depends(require_surface(AdminSurface.trash))
    ],
    page: TrashPage = 1,
    page_size: TrashPageSize = 50,
) -> TrashListResponse:
    """The active guild's trash, newest first, for whoever holds the trash.

    This is the guild settings trash view. Members use the user-scoped
    ``GET /me/trash`` for their own deletions; they never reach this endpoint.
    """
    items, total_count = await trash_page(
        session,
        guild_context.guild_id,
        only_deleted_by=None,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    retention_days = await guilds_service.get_guild_retention_days(session)
    return TrashListResponse(
        **build_paginated_response(
            items, total_count, page, page_size, retention_days=retention_days
        )
    )


async def _load_trash_entity(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: int,
    for_update: bool = False,
) -> Any:
    """Load a trashed entity (404 unless it's in this guild's trash and still
    soft-deleted).

    ``for_update`` takes a row lock so the ``deleted_at`` check and a follow-up
    hard delete are atomic against a concurrent restore: under READ COMMITTED a
    restore that commits between the SELECT and the DELETE would otherwise be
    visible, and the PK delete would permanently remove a now-live row. With the
    lock, a racing restore serializes — either it commits first and this returns
    404 (deleted_at is NULL), or it blocks on the lock until the purge commits and
    the row is gone.
    """
    tools = routed_tools(session)
    entry = entity_registry(tools).get(entity_type)
    located = locate(tools, entity_type)
    if entry is None:
        entity = None
    elif located is not None:
        entity = await load_row(
            session, located, tools, entity_id, for_update=for_update, trashed=True
        )
    else:
        model = MODELS_BY_TABLE[entry[0].name]
        stmt = select_including_deleted(model).where(model.id == entity_id)  # type: ignore[attr-defined]
        if for_update:
            stmt = stmt.with_for_update()
        entity = (await session.exec(stmt)).one_or_none()
    if entity is None or entity.deleted_at is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=TrashMessages.NOT_FOUND
        )
    return entity


@router.post(
    "/{entity_type}/{entity_id}/restore",
    status_code=status.HTTP_200_OK,
    response_model=RestoreResponse,
)
async def restore_trash_entity(
    entity_type: str,
    entity_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
):
    """Restore a trashed entity."""
    entity = await _load_trash_entity(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
    )

    # Permission: regular users can only restore their own deletions.
    if not guild_context.holds_surface(AdminSurface.trash) and (
        getattr(entity, "deleted_by_kind", None) != ActorKind.member
        or getattr(entity, "deleted_by", None) != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=TrashMessages.PURGE_REQUIRES_ADMIN,
        )

    await restore_entity(session, entity)
    # A task back out of the trash goes back into its column, unless archived.
    if isinstance(entity, Task) and entity.archived_at is None:
        await column_limits.refuse_full_columns(
            session, guild_context, entity.project_id, [entity]
        )

    # A comment back in the conversation puts back what it alone pointed at.
    if isinstance(entity, Comment):
        await content_references.sync_for_comment(
            session, entity, author_id=current_user.id
        )

    # Quality-of-life: a tool trashed before its owner left comes back unowned.
    # If whoever wrote it is still in the guild, give it back to them. If not,
    # it stays unowned — there is nobody obvious to pick, so nothing is guessed.
    await ownership_service.restore_ownership_to_author(
        session, row=entity, guild_id=guild_context.guild_id
    )

    await session.commit()
    return RestoreResponse(restored=True)


@router.delete(
    "/{entity_type}/{entity_id}/purge",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def purge_trash_entity(
    entity_type: str,
    entity_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Response:
    """Hard-purge a trashed entity. Guild-admin only, fully guild-scoped.

    Runs entirely on the routed guild-admin RLS session — no standing-BYPASSRLS
    ``app_admin`` connection. The guild-schema content tables carry PERMISSIVE
    ``initiative_member_delete`` policies that defer to ``initiative_access``,
    whose community-admin leg (``app.guild_admin = 'true'``) admits the routed
    admin for the hard delete, beside the RESTRICTIVE purge guard, which asks
    for the community's trash, so the guild role itself does it.
    ``_load_trash_entity`` 404s unless the entity is in THIS guild's trash (and
    still soft-deleted) — that is the authorization boundary — and
    ``for_update=True`` locks the row so a concurrent restore can't slip in
    between the ``deleted_at`` check and the delete (which would otherwise
    permanently remove a just-restored live row).
    """
    if not guild_context.holds_surface(AdminSurface.trash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=TrashMessages.PURGE_REQUIRES_ADMIN,
        )

    entity = await _load_trash_entity(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        for_update=True,
    )
    released = await hard_purge_entity(session, entity)
    await audit_service.record(
        session,
        event_type=AuditEventType.TRASH_PURGED,
        actor_user_id=current_user.id,
        guild_id=guild_context.guild_id,
        target_type=entity_type,
        target_id=entity_id,
        detail={"via": "admin"},
    )
    await session.commit()
    attachments_service.delete_blobs(guild_context.guild_id, released)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
