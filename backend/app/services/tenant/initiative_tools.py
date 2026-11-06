"""An initiative's tools and roles, once its community's defaults apply.

A community may set a tool's switch, and what the built-in member role may
do, for every initiative in it (``COMMUNITY_DEFAULT_KEYS``, its
``initiative_rules`` rows with no initiative); its value stands over the
initiative's own. While it keeps initiatives to their built-in roles, what it
set for members holds for every custom role that is not a manager's too.

The request's standing applies them for the gates and ``initiative_actions()``
(``app.db.guild_standing``); these answer the same question for everything
else, from the standing where the session has one and from the rows where it
does not.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.db.guild_standing import ActorContext
from app.db.session import actor_context
from app.models.tenant.initiative import (
    BUILTIN_MEMBER_ROLE,
    INITIATIVE_CUSTOM_ROLES,
    INITIATIVE_MEMBER_PREFIX,
    INITIATIVE_TOOL_KEYS,
    Initiative,
    InitiativeRoleModel,
    InitiativeRule,
)


def _community(key: str):
    """The community's row for ``key``, over an alias of its own so it never
    correlates with a query that reads ``initiative_rules`` too."""
    row = aliased(InitiativeRule)
    return row, and_(row.initiative_id.is_(None), row.key == key)  # type: ignore[union-attr]


def community_switch(context: ActorContext, tool: Tool) -> bool | None:
    """The switch the community set for ``tool`` in every initiative, or
    ``None`` where each initiative sets its own."""
    if f"{tool.value}=on" in context.community_tools:
        return True
    if f"{tool.value}=off" in context.community_tools:
        return False
    return None


def tool_on(context: ActorContext, initiative: Any, tool: Tool) -> bool:
    """Whether ``tool`` is on in ``initiative``, by the request's standing."""
    switch = community_switch(context, tool)
    if switch is None:
        return bool(getattr(initiative, tool.view_permission))
    return switch


async def tool_on_in(session: AsyncSession, initiative: Any, tool: Tool) -> bool:
    """:func:`tool_on` for a caller holding only a session: by its standing
    where it has one, and by the community's row where it does not (the
    system's own reads)."""
    context = actor_context(session)
    if context is not None:
        return tool_on(context, initiative, tool)
    row, where = _community(INITIATIVE_TOOL_KEYS[tool])
    switch = await session.scalar(select(row.enabled).where(where))
    if switch is None:
        return bool(getattr(initiative, tool.view_permission))
    return switch


def tool_on_sql(tool: Tool) -> ColumnElement[bool]:
    """:func:`tool_on` over ``initiatives`` rows, for a query's filter. The
    community's row is read once for the statement."""
    row, where = _community(INITIATIVE_TOOL_KEYS[tool])
    return func.coalesce(
        select(row.enabled).where(where).scalar_subquery(),
        getattr(Initiative, tool.view_permission),
    )


def member_permission_sql(
    role: type[InitiativeRoleModel] | Any, key: str
) -> ColumnElement[bool]:
    """What the community set ``key`` to, where it holds for ``role``: the
    built-in member role, or a custom role that is not a manager's while the
    community keeps initiatives to their built-in roles. ``NULL`` otherwise,
    for the role's own row to decide."""
    value, where = _community(f"{INITIATIVE_MEMBER_PREFIX}{key}")
    off, custom_roles = _community(INITIATIVE_CUSTOM_ROLES)
    held = or_(
        and_(role.is_builtin, role.name == BUILTIN_MEMBER_ROLE),
        and_(
            ~role.is_builtin,
            ~role.is_manager,
            exists().where(custom_roles, off.enabled.is_(False)),  # type: ignore[union-attr]
        ),
    )
    return case(
        (held, select(value.enabled).where(where).scalar_subquery()), else_=None
    )
