"""Deleting and duplicating a tool — one route each, mounted once for every tool.

``DELETE /{tool}/{id}`` puts a tool in the trash with everything inside it.
Nine copies of it said the same thing: load and authorize with the delete
action, hand the row to ``soft_delete.trash``, commit. None of that depends on
which tool it is, so the route is mounted per ``Tool`` straight out of the
resource-access registry rather than written nine times over.

What goes in with it is the lifecycle tree's (``services.tenant.lifecycle_tree``),
and restoring or purging it is the trash's (``tenant_endpoints/trash.py``).

Afterwards the tool's room is told it was deleted, so an open window refetches
and finds it gone.

Each route keeps the path, method, status code, tag and name its tool already
had, so the generated client is unchanged.

``POST /{tool}/{id}/duplicate`` copies a tool into an initiative: its own, or
the one the body names. The steps are ``app.api.tool_copy``'s, the same for
every tool, and the answer is the copy as the tool's own read returns it. An
installed plug-in reaches it for each tool that serves plug-ins, under the tool's
write scope, as it reaches the tool's create.
"""

# NOT ``from __future__ import annotations``: the handlers are built per tool
# with ``Annotated[int, Path(alias=cfg.path_param)]`` closing over a local, and
# stringized annotations re-evaluate it where that local is out of scope.

from enum import Enum
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, status

from app.api import resource_access, tool_copy
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
    plugin_scope,
)
from app.api.v1.tenant_endpoints.tool_lists import TOOL_LISTS, ToolListSpec
from app.core.tools import Tool
from app.models.platform.user import User
from app.schemas.tenant.tool import ToolDuplicateRequest
from app.services.content_sockets import sockets
from app.services.permissions import Action
from app.services.tenant import named_people
from app.services.tenant.soft_delete import trash

router = APIRouter(route_class=ActorRoute)

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]
CurrentUserDep = Annotated[User, Depends(get_current_active_user)]


def _title(path_param: str) -> str:
    """The schema title a parameter of this name would be given."""
    return path_param.replace("_", " ").title()


def _mount(tool: Tool, cfg: resource_access.ResourceAccessConfig) -> None:
    """Mount ``DELETE`` ``/{id}`` for one tool."""
    entity_id_param = Annotated[
        int, Path(alias=cfg.path_param, title=_title(cfg.path_param))
    ]

    async def delete(
        entity_id: entity_id_param,
        session: RLSSessionDep,
        current_user: CurrentUserDep,
        guild_context: GuildContextDep,
    ) -> None:
        """Move it to the trash with everything inside it. Restoring it brings
        all of that back; the trash purges it after the community's retention.
        Requires the delete right on it: its owner, or a guild admin."""
        row = await resource_access.load_authorized(
            session, tool, entity_id, current_user, guild_context, action=Action.delete
        )
        await trash(session, row, deleted_by_user_id=current_user.id)
        await session.commit()
        sockets.signal(guild_context.guild_id, tool, entity_id, "deleted")

    tags: list[str | Enum] = [TOOL_LISTS[tool].tag or tool.plural]
    router.add_api_route(
        f"/{tool.route_segment}/{{{cfg.path_param}}}",
        delete,
        methods=["DELETE"],
        status_code=status.HTTP_204_NO_CONTENT,
        name=f"delete_{tool.value}",
        tags=tags,
    )


_DUPLICATE_DOC = (
    "Copy it, with everything inside it, into an initiative: its own unless the "
    "body names another. Read is enough to copy a template; anything else needs "
    "write. The copy is shared as its source is while it stays in the same "
    "initiative, and carries the tags its maker may set: an installed plug-in's "
    "copy carries them only when it holds the scope to tag."
)


def _mount_duplicate(
    tool: Tool, cfg: resource_access.ResourceAccessConfig, spec: ToolListSpec
) -> None:
    """Mount ``POST`` ``/{id}/duplicate`` for one tool."""
    entity_id_param = Annotated[
        int, Path(alias=cfg.path_param, title=_title(cfg.path_param))
    ]
    copier = tool_copy.TOOL_COPIERS[tool]

    async def copy(
        session: Any,
        entity_id: int,
        body: ToolDuplicateRequest | None,
        current_user: User | None,
        guild_context: ActorContext,
    ):
        body = body or ToolDuplicateRequest()
        source = await tool_copy.load_source(
            session, tool, entity_id, current_user, guild_context
        )
        copied = await tool_copy.duplicate(
            session,
            tool,
            source,
            initiative_id=body.target_initiative_id,
            name=body.name,
            user=current_user,
            actor=guild_context,
            payload=body,
        )
        settled = named_people.Governing.of(tool, copied)
        await session.commit()
        # The people named inside the copy came with it; those its sharing
        # does not reach are let go, once that sharing is committed and can be
        # read from every session.
        await named_people.sweep(session, settled)
        await session.commit()
        copy_id = settled.resource_id
        if copier.announce is not None and current_user is not None:
            await copier.announce(session, copy_id, current_user)
            await session.commit()
        return await spec.read_row(session, copy_id, current_user, guild_context)

    if spec.serves_plugins:
        ToolWrite = Annotated[
            ActorContext, Depends(plugin_scope(f"{tool.plural}:write"))
        ]

        async def duplicate(
            entity_id: entity_id_param,
            session: ActorSessionDep,
            current_user: ActorUserDep,
            guild_context: ToolWrite,
            body: ToolDuplicateRequest | None = None,
        ):
            return await copy(session, entity_id, body, current_user, guild_context)

    else:

        async def duplicate(
            entity_id: entity_id_param,
            session: RLSSessionDep,
            current_user: CurrentUserDep,
            guild_context: GuildContextDep,
            body: ToolDuplicateRequest | None = None,
        ):
            return await copy(session, entity_id, body, current_user, guild_context)

    tags: list[str | Enum] = [spec.tag or tool.plural]
    router.add_api_route(
        f"/{tool.route_segment}/{{{cfg.path_param}}}/duplicate",
        duplicate,
        methods=["POST"],
        status_code=status.HTTP_201_CREATED,
        response_model=spec.read_model,
        name=f"duplicate_{tool.value}",
        description=_DUPLICATE_DOC,
        tags=tags,
    )


for _tool, _cfg in resource_access.RESOURCE_ACCESS.items():
    _mount(_tool, _cfg)
    if _tool in tool_copy.TOOL_COPIERS:
        _mount_duplicate(_tool, _cfg, TOOL_LISTS[_tool])
