"""An initiative's tools and member role, once its community's defaults apply.

A community may set a tool's switch, and what the built-in member role may
do, for every initiative in it (``COMMUNITY_DEFAULT_KEYS``, its
``initiative_rules`` rows with no initiative); its value stands over the
initiative's own. The request's standing
carries the community's tool switches (``community_tools``) and applies its
member permissions to the role grants, so the gates, ``initiative_actions()``
and these answer from the same rows.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, case, false, literal_column, select, true
from sqlalchemy.sql.elements import ColumnElement

from app.core.tools import Tool
from app.db import gucs
from app.db.guild_standing import ActorContext
from app.models.tenant.initiative import (
    BUILTIN_MEMBER_ROLE,
    INITIATIVE_MEMBER_PREFIX,
    Initiative,
    InitiativeRoleModel,
    InitiativeRule,
)


def community_switch(context: ActorContext, tool: Tool) -> bool | None:
    """The switch the community set for ``tool`` in every initiative, or
    ``None`` where each initiative sets its own."""
    if f"{tool.value}=on" in context.community_tools:
        return True
    if f"{tool.value}=off" in context.community_tools:
        return False
    return None


def tool_on(context: ActorContext | None, initiative: Any, tool: Tool) -> bool:
    """Whether ``tool`` is on in ``initiative``. Without a standing (the
    system's own reads) there are no community switches to apply."""
    switch = None if context is None else community_switch(context, tool)
    if switch is None:
        return bool(getattr(initiative, tool.view_permission))
    return switch


def tool_on_sql(tool: Tool) -> ColumnElement[bool]:
    """:func:`tool_on` over ``initiatives`` rows, for a query's filter: read
    from the standing the session's transaction carries."""
    switches = gucs.COMMUNITY_TOOLS.sql
    return case(
        (literal_column(f"'{tool.value}=on' = ANY ({switches})"), true()),
        (literal_column(f"'{tool.value}=off' = ANY ({switches})"), false()),
        else_=getattr(Initiative, tool.view_permission),
    )


def member_permission_sql(
    role: type[InitiativeRoleModel] | Any, key: str
) -> ColumnElement[bool]:
    """What the community set ``key`` to for the built-in member role, where
    ``role`` is that role; ``NULL`` otherwise, for the role's own row to
    decide."""
    community = (
        select(InitiativeRule.enabled)
        .where(
            InitiativeRule.initiative_id.is_(None),  # type: ignore[union-attr]
            InitiativeRule.key == f"{INITIATIVE_MEMBER_PREFIX}{key}",
        )
        .scalar_subquery()
    )
    return case(
        (and_(role.is_builtin, role.name == BUILTIN_MEMBER_ROLE), community),
        else_=None,
    )
