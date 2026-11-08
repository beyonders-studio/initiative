"""Who can reach what, across one initiative.

The per-resource view already exists — every tool's own read carries its grants
and the sharing control edits them. What this adds is the aggregate: one list a
moderator can scan instead of opening eleven things to find the one shared too
widely.

It grants nothing. The people who can ask for it are the people who already
reach every item in the initiative, and what it returns is the same grants
those items carry.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select as sa_select
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.db.base import MODELS_BY_TABLE
from app.models.tenant.resource_grant import ResourceGrant


@dataclass(frozen=True)
class SharedResource:
    """One resource in the initiative, and how it is reached."""

    resource_type: str
    resource_id: int
    name: str | None
    #: True when every member of the initiative can reach it.
    all_initiative_members: bool
    #: How many people hold a grant of their own, owners included.
    user_grant_count: int
    #: How many roles hold one.
    role_grant_count: int


async def _names_for(
    session: AsyncSession, tool: Tool, ids: set[int]
) -> dict[int, str | None]:
    """``id -> label`` for one tool's rows.

    The label column is the model's own ``display_field`` — ``name`` for most,
    ``title`` for a few — so a tool that calls it something else is read
    correctly without a list here saying so.
    """
    model = MODELS_BY_TABLE.get(tool.plural)
    if model is None or not ids:
        return {}
    label = getattr(model, model.display_field(), None)
    if label is None:
        return {}
    rows = await session.exec(
        sa_select(model.id, label).where(model.id.in_(ids))  # type: ignore[attr-defined]
    )
    return {row[0]: row[1] for row in rows}


async def initiative_sharing(
    session: AsyncSession, *, initiative_id: int
) -> list[SharedResource]:
    """Every resource in the initiative that anybody has been given access to.

    Resources nobody has been granted anything on do not appear: there is
    nothing to say about them beyond what the initiative's own membership
    already decides.
    """
    grants = (
        await session.exec(
            select(ResourceGrant)
            .where(ResourceGrant.initiative_id == initiative_id)
            .order_by(ResourceGrant.resource_type, ResourceGrant.resource_id)
        )
    ).all()
    if not grants:
        return []

    by_resource: dict[tuple[str, int], list[ResourceGrant]] = {}
    for grant in grants:
        by_resource.setdefault(
            (str(grant.resource_type), grant.resource_id), []
        ).append(grant)

    # One lookup per tool that actually appears, rather than per resource.
    ids_by_tool: dict[Tool, set[int]] = {}
    for resource_type, resource_id in by_resource:
        try:
            tool = Tool(resource_type)
        except ValueError:
            continue
        ids_by_tool.setdefault(tool, set()).add(resource_id)
    names: dict[tuple[str, int], str | None] = {}
    for tool, ids in ids_by_tool.items():
        for resource_id, label in (await _names_for(session, tool, ids)).items():
            names[(tool.value, resource_id)] = label

    resources: list[SharedResource] = []
    for key, held in sorted(by_resource.items()):
        resource_type, resource_id = key
        resources.append(
            SharedResource(
                resource_type=resource_type,
                resource_id=resource_id,
                name=names.get(key),
                all_initiative_members=any(g.all_initiative_members for g in held),
                user_grant_count=sum(1 for g in held if g.user_id is not None),
                role_grant_count=sum(1 for g in held if g.role_id is not None),
            )
        )
    return resources
