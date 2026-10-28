"""Custom property values on any tool or sub-tool — the one write route.

Every target in ``PROPERTY_TARGETS`` is written here and nowhere else; each
target's read carries its values as ``properties``. Which tool governs a target
and how a row reaches it come from the properties seam
(``metadata_service.PROPERTY_LINKS``), so a new tool is writable here the
moment it exists.
"""

from typing import Annotated, Any, List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select

from app.core.errors import CodedError
from app.core.tools import KINDS
from app.api import resource_access
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    plugin_scope_by,
)
from app.core.plugin_scopes import tool_resource
from app.schemas.tenant.property import (
    PropertySummary,
    PropertyTarget,
    PropertyValuesSetRequest,
)
from app.services.tenant import metadata as metadata_service

router = APIRouter(route_class=ActorRoute)

#: An installed plug-in writes a target's values with the write scope of the tool
#: that governs it — a task's with ``projects:write``.
PropertiesWrite = Annotated[
    ActorContext,
    Depends(
        plugin_scope_by(
            "target",
            {
                target: f"{tool_resource(spec.tool).value}:write"
                for target, spec in metadata_service.PROPERTY_LINKS.items()
            },
        )
    ),
]


@router.put("/{target}/{entity_id}", response_model=List[PropertySummary])
async def set_properties(
    target: PropertyTarget,
    entity_id: int,
    payload: PropertyValuesSetRequest,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: PropertiesWrite,
) -> List[PropertySummary]:
    """Replace the custom property values on one tool or sub-tool, or with
    ``merge`` write only the ones named and leave the rest, and change options
    of multi-select values against what each holds.

    Requires write on the tool that governs it: a tool itself, or the tool a
    sub-tool sits in (a task's project, an event's calendar). Each value's
    definition must belong to the same initiative, so a row that belongs to no
    initiative carries none. Values are validated against each definition's
    type and options. An installed plug-in names the person a person-valued
    property holds by its reference for them. An empty list clears them all.
    """
    spec = metadata_service.PROPERTY_LINKS[target.value]
    row: Any
    if not spec.shared:
        row = await resource_access.load_child(
            session, spec.model, entity_id, access="write"
        )
        initiative_id = row.initiative_id
    elif spec.via is None:
        row = await resource_access.load_authorized(
            session, spec.tool, entity_id, current_user, guild_context, access="write"
        )
        initiative_id = row.initiative_id
    else:
        row = (
            await session.exec(select(spec.model).where(spec.model.id == entity_id))
        ).one_or_none()
        if row is None:
            raise KINDS[target.value].not_found()
        governing = await resource_access.load_authorized(
            session,
            spec.tool,
            spec.governing_id(row),
            current_user,
            guild_context,
            access="write",
        )
        initiative_id = governing.initiative_id

    try:
        await metadata_service.set_values(
            session,
            row,
            payload.values,
            initiative_id=initiative_id,
            removed=payload.removed if payload.merge else None,
            options=payload.options,
        )
    except (HTTPException, CodedError):
        await session.rollback()
        raise
    await session.commit()
    summaries = await metadata_service.summaries_by_id(
        session, target.value, [entity_id]
    )
    return summaries.get(entity_id, [])
