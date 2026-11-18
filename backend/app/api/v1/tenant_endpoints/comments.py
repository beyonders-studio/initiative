"""Comments: a thread is read and added to at what it is said on, one comment
by its id.

``GET``/``POST /{segment}/{id}/comments`` is mounted once for every kind that
takes comments (``COMMENT_TARGETS``), at that kind's own path, so a new kind
gets its thread with nothing written here. The routes by comment id are under
``/comments``.
"""

# NOT ``from __future__ import annotations``: the thread routes are built per
# kind with ``Annotated[int, Path(alias=...)]`` closing over a local, and
# stringized annotations re-evaluate it where that local is out of scope.

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status

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
from app.core.tools import COMMENT_TARGETS, KINDS
from app.models.platform.user import User
from app.schemas.tenant.comment import (
    CommentCreate,
    CommentListResponse,
    CommentRead,
    CommentUpdate,
    RecentActivityEntry,
)
from app.services import notifications as notifications_service
from app.services.tenant import attachments as attachments_service
from app.services.tenant import comments as comments_service

router = APIRouter(route_class=ActorRoute)
#: The threads, mounted at each subject's own path.
subject_router = APIRouter(route_class=ActorRoute)
#: The routes an installed plug-in may call, under the comments scopes.
CommentsRead = Annotated[ActorContext, Depends(plugin_scope("comments:read"))]
CommentsWrite = Annotated[ActorContext, Depends(plugin_scope("comments:write"))]


def subject_segment(kind: str) -> str:
    """The path a kind's thread is served under (``wiki_page`` →
    ``wiki-pages``): its table, in kebab case, as every tool's own is."""
    return KINDS[kind].table.replace("_", "-")


def _mount_thread(kind: str) -> None:
    """Mount ``GET`` and ``POST`` ``/{segment}/{id}/comments`` for one kind."""
    param = f"{kind}_id"
    subject_id_param = Annotated[
        int, Path(alias=param, title=param.replace("_", " ").title(), gt=0)
    ]

    async def create(
        subject_id: subject_id_param,
        comment_in: CommentCreate,
        session: ActorSessionDep,
        current_user: ActorUserDep,
        guild_context: CommentsWrite,
    ) -> CommentRead:
        """Post a comment on it. An installed plug-in posts as itself: the
        comment names no author, and the notices it sends name the plug-in."""
        author = await notifications_service.author_of(
            session, guild_context, current_user
        )
        comment = await comments_service.create_comment(
            session,
            author=author,
            guild_id=guild_context.guild_id,
            content=comment_in.content,
            parent_comment_id=comment_in.parent_comment_id,
            audience=comment_in.audience,
            subject=(kind, subject_id),
        )
        await session.commit()
        return comments_service.serialize_comment(
            comment, viewer_id=guild_context.user_id
        )

    async def read_thread(
        subject_id: subject_id_param,
        session: ActorSessionDep,
        current_user: ActorUserDep,
        guild_context: CommentsRead,
        limit: int = Query(default=20, ge=1, le=100),
        cursor: str | None = Query(default=None),
    ) -> CommentListResponse:
        """One page of its thread: ``limit`` conversations, newest first, each
        with every reply under it. Follow ``next_cursor`` for older
        conversations."""
        page = await comments_service.list_comments(
            session,
            user=current_user,
            guild_id=guild_context.guild_id,
            subject=(kind, subject_id),
            limit=limit,
            cursor=cursor,
        )
        return CommentListResponse(
            comments=[
                comments_service.serialize_comment(
                    comment, viewer_id=guild_context.user_id
                )
                for comment in page.comments
            ],
            next_cursor=page.next_cursor,
            locked=page.locked,
            can_moderate=page.can_moderate,
        )

    path = f"/{subject_segment(kind)}/{{{param}}}/comments"
    subject_router.add_api_route(
        path,
        create,
        methods=["POST"],
        response_model=CommentRead,
        status_code=status.HTTP_201_CREATED,
        name=f"create_{kind}_comment",
        tags=["comments"],
    )
    subject_router.add_api_route(
        path,
        read_thread,
        methods=["GET"],
        response_model=CommentListResponse,
        name=f"list_{kind}_comments",
        tags=["comments"],
    )


for _kind in COMMENT_TARGETS:
    _mount_thread(_kind)


@router.get("/recent", response_model=list[RecentActivityEntry])
async def recent_comments(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    limit: int = Query(default=10, ge=1, le=50),
) -> list[RecentActivityEntry]:
    """Return the most recent comments across the guild.

    Only returns comments on parents the current user has DAC permission to
    view (direct user permission or role-based). Initiative-level filtering is
    handled by RLS on the joined parent tables.
    """
    return await comments_service.recent_activity(
        session, viewer_id=current_user.id, limit=limit
    )


@router.get("/{comment_id}", response_model=CommentRead)
async def read_comment(
    comment_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CommentsRead,
    include_deleted: IncludeDeletedDep = False,
) -> CommentRead:
    """One comment by id — the read-back for a ``comments.*`` event."""
    comment = await comments_service.get_comment(
        session,
        comment_id=comment_id,
        user=current_user,
        guild_id=guild_context.guild_id,
    )
    return comments_service.serialize_comment(comment, viewer_id=guild_context.user_id)


@router.patch("/{comment_id}", response_model=CommentRead)
async def update_comment(
    comment_id: int,
    comment_in: CommentUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CommentRead:
    """Update a comment. Only the original author can edit."""
    comment, let_go = await comments_service.update_comment(
        session,
        comment_id=comment_id,
        user=current_user,
        guild_id=guild_context.guild_id,
        content=comment_in.content,
    )
    # Note: Content validation (empty string) is handled by Pydantic schema (422).

    # No refresh here: the service already flushed the edit and loaded the
    # author, and a bare refresh() expires every attribute including that
    # relationship — serializing would then lazy-load it mid-request.
    await session.commit()
    # A picture taken out of the comment goes once the edit has landed.
    released_images = await attachments_service.release_unshown(
        guild_context.guild_id, let_go, pasted_only=True
    )
    attachments_service.delete_blobs(guild_context.guild_id, released_images)
    response = comments_service.serialize_comment(comment, viewer_id=current_user.id)
    return response


@router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    await comments_service.delete_comment(
        session,
        comment_id=comment_id,
        user=current_user,
        guild_id=guild_context.guild_id,
    )

    await session.commit()
