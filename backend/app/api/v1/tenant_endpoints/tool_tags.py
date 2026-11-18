"""Tagging a tool — one route, mounted once for every tool.

``PUT /{tool}/{id}/tags`` replaces a tool's tags. Loading and authorization go
through the resource-access registry and the assignment through the tag-link
registry, so a new ``Tool`` member gets the route with nothing written. What
lives inside a tool (a task, an event, a page, a collection) takes ``tag_ids``
on its own update instead.
"""

# NOT ``from __future__ import annotations``: the handlers are built per tool
# with ``resource_access.id_path`` closing over a local, and stringized
# annotations re-evaluate it where that local is out of scope.

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import select

from app.api import resource_access
from app.api.deps import GuildContextDep, RLSSessionDep, get_current_active_user
from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.tag import Tag
from app.schemas.tenant.tag import TagSetRequest, TagSummary
from app.services.content_sockets import sockets
from app.services.tenant import required_fields
from app.services.tenant import tags as tags_service

router = APIRouter()

CurrentUserDep = Annotated[User, Depends(get_current_active_user)]


def _mount(tool: Tool) -> None:
    """Mount ``PUT`` ``/{id}/tags`` for one tool."""
    entity_id_param = Annotated[int, resource_access.id_path(tool.value)]

    async def set_tags(
        entity_id: entity_id_param,
        tags_in: TagSetRequest,
        session: RLSSessionDep,
        current_user: CurrentUserDep,
        guild_context: GuildContextDep,
    ) -> list[TagSummary]:
        """Replace its tags with the ones listed and answer with its new tags.
        Requires write access."""
        row = await resource_access.load_authorized(
            session,
            tool,
            entity_id,
            current_user,
            guild_context,
            access="write",
        )
        required = await required_fields.required_of(session, guild_context, row)
        tag_ids = await tags_service.set_entity_tags(
            session,
            tags_service.TOOL_TAG_LINKS[tool],
            guild_id=guild_context.guild_id,
            entity_id=row.id,
            tag_ids=tags_in.tag_ids,
        )
        row.updated_at = datetime.now(UTC)
        session.add(row)
        await required_fields.refuse_emptied(session, required)
        await session.commit()

        sockets.signal(guild_context.guild_id, tool, row.id, "updated")

        if not tag_ids:
            return []
        # Re-read under the session-wide soft-delete filter. A tag trashed by a
        # concurrent request between the write above and this read is filtered
        # out here — skip it rather than KeyError (the tag service drops an
        # assignment whose tag is gone the same way), so the race returns a
        # clean list, never a 500.
        tags_by_id = {
            tag.id: tag
            for tag in (
                await session.exec(select(Tag).where(Tag.id.in_(tag_ids)))
            ).all()
        }
        return [
            TagSummary(id=tag.id, name=tag.name, color=tag.color)
            for tag_id in tag_ids
            if (tag := tags_by_id.get(tag_id)) is not None
        ]

    router.add_api_route(
        f"/{tool.route_segment}/{{{resource_access.path_param_of(tool.value)}}}/tags",
        set_tags,
        methods=["PUT"],
        response_model=list[TagSummary],
        name=f"set_{tool.value}_tags",
    )


for _tool in Tool:
    _mount(_tool)
