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

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import Subquery, Text, cast, func, literal, select, union_all
from sqlalchemy.orm import aliased
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    require_surface,
    GuildContextDep,
)
from app.core.audit_events import AuditEventType
from app.core.messages import TrashMessages
from app.core.tools import TRASH_TARGETS, plural_of
from app.db.base import MODELS_BY_TABLE
from app.db.query import build_paginated_response
from app.db.soft_delete_filter import SOFT_DELETE_MODELS, select_including_deleted
from app.models.tenant.comment import Comment
from app.models.tenant.task import Task
from app.models.platform.guild import AdminSurface
from app.models.platform.user import User, UserStatus
from app.models.platform.user_profile_view import MemberProfile
from app.schemas.tenant.trash import (
    EntityType,
    RestoreResponse,
    TrashItem,
    TrashListResponse,
)
from app.services import audit as audit_service
from app.services.platform import guilds as guilds_service
from app.services.tenant import ownership as ownership_service
from app.core.user_display import display_name
from app.services.tenant import attachments as attachments_service
from app.services.tenant import column_limits
from app.services.tenant import content_references
from app.services.tenant.lifecycle_tree import CASCADE_PARENTS
from app.services.tenant.soft_delete import (
    hard_purge_entity,
    restore_entity,
)


router = APIRouter()


def _entry(target: str) -> tuple[type[SQLModel], str]:
    model = MODELS_BY_TABLE[plural_of(target)]
    if model not in SOFT_DELETE_MODELS:  # pragma: no cover — a registry mistake
        raise RuntimeError(f"{target} names no model with a trash can")
    return model, model.display_field()


#: Wire name -> (model, the column that labels its rows). A target's table is
#: its own plural and its label is the model's ``display_field``, so neither is
#: written down here; a target with no soft-deletable model behind it fails at
#: import rather than at request time.
ENTITY_REGISTRY: dict[str, tuple[type[SQLModel], str]] = {
    target: _entry(target) for target in TRASH_TARGETS
}


#: A trash listing's page window.
TrashPage = Annotated[int, Query(ge=1)]
TrashPageSize = Annotated[int, Query(ge=1, le=100)]

_NAME_LIMIT = 80


def _truncate(value: str, *, limit: int = _NAME_LIMIT) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def _trashed(only_deleted_by: Optional[int]) -> Subquery:
    """This guild's trash listing, one UNION ALL leg per trashable model.

    ``only_deleted_by`` narrows to one user's deletions (the personal view);
    ``None`` lists everything (the admin view).
    """
    legs = []
    for entity_type, (model, name_field) in ENTITY_REGISTRY.items():
        leg = select(
            literal(entity_type, Text).label("entity_type"),
            model.id.label("entity_id"),
            # One character past the limit is enough to tell a name was cut.
            func.left(cast(getattr(model, name_field), Text), _NAME_LIMIT + 1).label(
                "name"
            ),
            model.deleted_at,
            model.deleted_by,
            model.purge_at,
        ).where(model.deleted_at.is_not(None))
        if only_deleted_by is not None:
            leg = leg.where(model.deleted_by == only_deleted_by)

        # Cascade dedup: exclude children whose parent (any of them) is also
        # trashed at the same deleted_at — they come back with it, and one of
        # them restored alone would sit under a parent that is still in the
        # bin. Alias the parent — required when the parent is the same table as
        # the child (Comment threaded replies via parent_comment_id), otherwise
        # unaliased ``Comment.id == Comment.parent_comment_id`` references the
        # same row in both clauses.
        for parent_model, fk_col in CASCADE_PARENTS.get(model, []):
            parent = aliased(parent_model)
            leg = leg.where(
                ~select(parent.id)
                .where(parent.id == getattr(model, fk_col))
                .where(parent.deleted_at == model.deleted_at)
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
    only_deleted_by: Optional[int],
    limit: int,
    offset: int = 0,
) -> tuple[list[TrashItem], int]:
    """One window of a guild's trash, newest first, and how much it holds.

    The deleter's name is joined onto the window alone, read through the
    guild's own member view so it is named the way the guild names people.
    """
    trashed = _trashed(only_deleted_by)
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
        )
        .select_from(window)
        .outerjoin(MemberProfile, MemberProfile.id == window.c.deleted_by)
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
    entity_type: EntityType,
    entity_id: int,
    for_update: bool = False,
) -> SQLModel:
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
    spec = ENTITY_REGISTRY.get(entity_type)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=TrashMessages.UNKNOWN_ENTITY_TYPE,
        )
    model, _ = spec
    stmt = select_including_deleted(model).where(model.id == entity_id)
    if for_update:
        stmt = stmt.with_for_update()
    result = await session.exec(stmt)
    entity = result.one_or_none()
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
    entity_type: EntityType,
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
    if (
        not guild_context.holds_surface(AdminSurface.trash)
        and getattr(entity, "deleted_by", None) != current_user.id
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
    entity_type: EntityType,
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
        target_type=entity_type.value,
        target_id=entity_id,
        detail={"via": "admin"},
    )
    await session.commit()
    attachments_service.delete_blobs(guild_context.guild_id, released)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
