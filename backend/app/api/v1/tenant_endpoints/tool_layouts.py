"""How an instance of a tool draws its items: its layouts, one per kind,
each read as shipped until it is changed, and changed on its own.

A target is one instance of a tool (``tool`` and ``tool_id``: a project), or,
for a tool the initiative shares, the initiative (``tool`` and
``initiative_id``: its calendar), or a collection (``tool`` is ``collection``).
Reading follows reading the instance, or being in the initiative. Changing a
layout follows the ``configure`` action on the instance — its owner, the
initiative's managers, the community's admins — with write access to it, for
a shared tool managing the initiative, and for a collection changing it.

A tool plug-in's table is named by its kind, in the place its rows are listed:
its tool's own in the initiative (``initiative_id``), as a shared tool's are;
an item's under the row it sits in (``tool_id``), changed as that row's
instance's are. Its layouts name the table's fields, which only its
declaration knows, so they are checked against it as they are stored and read
back as stored.
"""

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import undefer
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import resource_access
from app.api.deps import (
    GuildContext,
    GuildContextDep,
    RLSSessionDep,
    get_current_active_user,
)
from app.core.messages import InitiativeMessages, KindMessages, ToolLayoutMessages
from app.core.tools import (
    INSTANCE_LAYOUT_TOOLS,
    KINDS,
    LAYOUT_KIND_TARGETS,
    LAYOUTS_PER_INSTANCE,
    LAYOUTS_SHARED,
    Tool,
    kind_refusal,
)
from app.db.base import MODELS_BY_TABLE
from app.db.tool_rows import locate
from app.models.platform.guild import AdminSurface
from app.models.platform.user import User
from app.models.tenant._mixins import tool_models
from app.models.tenant.initiative import Initiative
from app.schemas.tenant.tool_layout import (
    InitiativeToolLayoutsRead,
    LayoutWrite,
    ToolLayoutDefaultWrite,
    ToolLayoutSetRead,
    ToolLayoutWrite,
    ToolPluginLayoutWrite,
)
from app.services import permissions as permissions_service
from app.services.permissions import Action
from app.services.tenant import plugin_tool_rows
from app.services.tenant import tool_layouts as tool_layouts_service
from app.services.tenant.tool_layouts import Target

router = APIRouter(prefix="/layouts")

CurrentUser = Annotated[User, Depends(get_current_active_user)]

#: The target a request names: a tool, a collection, or a tool plug-in's
#: table by its kind.
ToolQuery = Annotated[str, Query(description="What the layouts are for")]
InstanceQuery = Annotated[int | None, Query()]


@dataclass(frozen=True)
class _Resolved:
    """A target, whether the reader may change its layouts, and the instance
    it names (None for a shared tool)."""

    target: Target
    can_configure: bool
    row: Any
    #: A tool plug-in's table's: its layouts name the table's own fields.
    plugin: bool = False


def _invalid() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ToolLayoutMessages.TARGET_INVALID,
    )


def _manages(context: GuildContext, initiative_id: int) -> bool:
    """Whether the reader may change an initiative's own layouts: manage it,
    while its content is open."""
    return not context.content_read_only and (
        context.holds_surface(AdminSurface.initiatives)
        or initiative_id in context.manager_initiatives
    )


async def _resolve_plugin(
    session: AsyncSession,
    context: GuildContext,
    kind: str,
    tool_id: int | None,
    initiative_id: int | None,
) -> _Resolved | None:
    """A tool plug-in's table's target, or None for a kind no installed tool
    has. Its tool's own rows are the initiative's, where the tool is on; an
    item's are the row's they sit under, read as that row is."""
    tools = context.tools
    located = locate(tools, kind)
    if located is None:
        return None
    under = plugin_tool_rows.placed(located, initiative_id, tool_id)
    if under is None:
        raise _invalid()
    if plugin_tool_rows.parent_column(located) is None:
        await _require_initiative(session, context, under)
        await plugin_tool_rows.require_on(session, located, under)
        return _Resolved(
            Target(kind, None, under), _manages(context, under), None, plugin=True
        )
    parent = plugin_tool_rows.parent_of(located, tools)
    row = await plugin_tool_rows.load_authorized(session, context, parent, tools, under)
    return _Resolved(
        Target(kind, under, int(row.tool["initiative_id"])),
        _configures(row),
        row,
        plugin=True,
    )


async def _resolve(
    session: AsyncSession,
    context: GuildContext,
    user: User,
    target: str,
    tool_id: int | None,
    initiative_id: int | None,
) -> _Resolved:
    invalid = _invalid()
    plugin = await _resolve_plugin(session, context, target, tool_id, initiative_id)
    if plugin is not None:
        return plugin
    if target in LAYOUT_KIND_TARGETS:
        if tool_id is None or initiative_id is not None:
            raise invalid
        model: Any = MODELS_BY_TABLE[KINDS[target].table]
        row = await resource_access.load_child(session, model, tool_id)
        return _Resolved(
            Target(target, tool_id, row.initiative_id),
            await resource_access.may_change(session, row, context),
            row,
        )
    if target not in {tool.value for tool in Tool}:
        raise invalid
    tool = Tool(target)
    if tool in LAYOUTS_PER_INSTANCE:
        if tool_id is None or initiative_id is not None:
            raise invalid
        row = await resource_access.load_authorized(
            session, tool, tool_id, user, context
        )
        if row.initiative_id is None:
            raise invalid
        return _Resolved(
            Target(tool, tool_id, row.initiative_id), _configures(row), row
        )

    if tool not in LAYOUTS_SHARED or tool_id is not None or initiative_id is None:
        raise invalid
    await _require_initiative(session, context, initiative_id)
    return _Resolved(
        Target(tool, None, initiative_id), _manages(context, initiative_id), None
    )


def _configures(row: Any) -> bool:
    """Whether the reader may change an instance's layouts: configure it, with
    write access to it, as the database answered when it loaded the row."""
    return permissions_service.allows(
        row, Action.configure
    ) and permissions_service.allows(row, Action.contribute)


async def _require_initiative(
    session: AsyncSession, context: GuildContext, initiative_id: int
) -> None:
    """A 404 unless the initiative exists and the reader is in it."""
    found = await session.exec(
        select(Initiative.id).where(Initiative.id == initiative_id)
    )
    if found.one_or_none() is None or not (
        context.is_admin
        or context.is_pam
        or initiative_id in context.member_initiatives
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.NOT_FOUND,
        )


def _require_configure(resolved: _Resolved, context: GuildContext) -> None:
    if resolved.plugin and resolved.row is not None:
        located = locate(context.tools, resolved.target.tool)
        assert located is not None
        for action in (Action.configure, Action.contribute):
            permissions_service.require_access(
                permissions_service.DacResource(located.tool),
                resolved.row,
                context=context,
                action=action,
            )
        return
    if resolved.target.tool in LAYOUT_KIND_TARGETS:
        if not resolved.can_configure:
            raise kind_refusal(
                resolved.target.tool, KindMessages.WRITE_ACCESS_REQUIRED, 403
            )
        return
    if resolved.row is None:
        if not resolved.can_configure:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=InitiativeMessages.MANAGER_REQUIRED,
            )
        return
    resource = permissions_service.DAC_RESOURCES[Tool(resolved.target.tool)]
    for action in (Action.configure, Action.contribute):
        permissions_service.require_access(
            resource, resolved.row, context=context, action=action
        )


async def _read(
    session: AsyncSession, context: GuildContext, resolved: _Resolved
) -> ToolLayoutSetRead | JSONResponse:
    """The target's set. A tool plug-in's names its table's fields, which were
    held to its declaration as they were stored, and is sent as read."""
    rows = await tool_layouts_service.list_rows(session, resolved.target)
    types = await tool_layouts_service.item_types(session, resolved.target)
    read = ToolLayoutSetRead(
        layouts=tool_layouts_service.read_set(
            resolved.target.tool, rows, types, context.tools
        ),
        can_configure=resolved.can_configure,
    )
    return JSONResponse(read.model_dump(mode="json")) if resolved.plugin else read


#: An Initiative tool's layout, as a request that changes one writes it.
_TOOL_LAYOUT_WRITE: TypeAdapter[Any] = TypeAdapter(ToolLayoutWrite)


def _written(resolved: _Resolved, payload: LayoutWrite) -> LayoutWrite:
    """The change as the target takes it: a tool plug-in's table's is held to
    its declaration by the service; an Initiative tool's is its own write, or
    refused as a malformed body would have been."""
    if resolved.plugin or not isinstance(payload, ToolPluginLayoutWrite):
        return payload
    try:
        return _TOOL_LAYOUT_WRITE.validate_python(payload.model_dump())
    except ValidationError as error:
        raise RequestValidationError(
            [{**each, "loc": ("body", *each["loc"])} for each in error.errors()]
        ) from None


async def _configured(
    session: AsyncSession,
    context: GuildContext,
    user: User,
    tool: str,
    tool_id: int | None,
    initiative_id: int | None,
) -> _Resolved:
    """The target, once the reader is known to be allowed to change it."""
    resolved = await _resolve(session, context, user, tool, tool_id, initiative_id)
    _require_configure(resolved, context)
    return resolved


@router.get("/", response_model=ToolLayoutSetRead)
async def get_layouts(
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    tool: ToolQuery,
    tool_id: InstanceQuery = None,
    initiative_id: InstanceQuery = None,
) -> ToolLayoutSetRead | JSONResponse:
    """The target's layouts, each as it changed it or as shipped
    (``updated_at`` null)."""
    resolved = await _resolve(
        session, guild_context, current_user, tool, tool_id, initiative_id
    )
    return await _read(session, guild_context, resolved)


@router.get("/initiative", response_model=list[InitiativeToolLayoutsRead])
async def get_initiative_layouts(
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    initiative_id: int = Query(),
) -> list[InitiativeToolLayoutsRead]:
    """The layouts of every instance in the initiative the reader can open,
    of each tool whose instances lay out their own items (a project's), by
    tool and name, for the initiative's settings. A layout is changed on its
    own target."""
    await _require_initiative(session, guild_context, initiative_id)
    found: list[InitiativeToolLayoutsRead] = []
    for tool in INSTANCE_LAYOUT_TOOLS:
        model: Any = tool_models()[tool.plural]
        # Which instances the reader can open is their own policy's answer.
        rows = (
            await session.exec(
                select(model)
                .where(
                    model.initiative_id == initiative_id,
                    col(model.archived_at).is_(None),
                    col(model.deleted_at).is_(None),
                )
                .options(undefer(model.actions))
                .order_by(col(model.name), col(model.id))
            )
        ).all()
        stored = await tool_layouts_service.rows_by_instance(
            session, initiative_id, tool, [row.id for row in rows]
        )
        types = await tool_layouts_service.item_types_by_instance(
            session, tool, [row.id for row in rows]
        )
        found += [
            InitiativeToolLayoutsRead(
                tool=tool,
                tool_id=row.id,
                name=row.name,
                layouts=tool_layouts_service.read_set(
                    tool, stored.get(row.id, []), types.get(row.id, [])
                ),
                can_configure=_configures(row),
            )
            for row in rows
        ]
    return found


@router.put("/", response_model=ToolLayoutSetRead)
async def put_layout(
    payload: Annotated[LayoutWrite, Body()],
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    tool: ToolQuery,
    tool_id: InstanceQuery = None,
    initiative_id: InstanceQuery = None,
) -> ToolLayoutSetRead | JSONResponse:
    """Change one of the target's layouts, leaving the others as they are."""
    resolved = await _configured(
        session, guild_context, current_user, tool, tool_id, initiative_id
    )
    await tool_layouts_service.save(
        session, resolved.target, _written(resolved, payload)
    )
    await session.commit()
    return await _read(session, guild_context, resolved)


@router.put("/default", response_model=ToolLayoutSetRead)
async def put_default_layout(
    payload: ToolLayoutDefaultWrite,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    tool: ToolQuery,
    tool_id: InstanceQuery = None,
    initiative_id: InstanceQuery = None,
) -> ToolLayoutSetRead | JSONResponse:
    """Open the target on one of its lists."""
    resolved = await _configured(
        session, guild_context, current_user, tool, tool_id, initiative_id
    )
    await tool_layouts_service.save_default(session, resolved.target, payload.kind)
    await session.commit()
    return await _read(session, guild_context, resolved)


@router.delete("/{kind}", response_model=ToolLayoutSetRead)
async def reset_layout(
    kind: str,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    tool: ToolQuery,
    tool_id: InstanceQuery = None,
    initiative_id: InstanceQuery = None,
    task_type_id: InstanceQuery = None,
) -> ToolLayoutSetRead | JSONResponse:
    """Draw one of the target's layouts as shipped again: a project's task
    page names the type of task it is for."""
    resolved = await _configured(
        session, guild_context, current_user, tool, tool_id, initiative_id
    )
    await tool_layouts_service.reset(session, resolved.target, kind, task_type_id)
    await session.commit()
    return await _read(session, guild_context, resolved)
