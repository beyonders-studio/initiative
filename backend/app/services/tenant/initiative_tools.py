"""An initiative's tools and roles, once its community's defaults apply.

Each initiative's own switch for a tool is one of its ``initiative_rules``
rows: no role, no install, the tool's view key (``Initiative.switched_on``
holds the keys whose row is on). A tool with no row is off. A tool plug-in's
tool is one of the community's tools, and its rows are a built-in tool's.

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

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import and_, case, delete, func, not_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tool_set import ToolRecord, ToolSet
from app.core.tools import Tool
from app.db.guild_standing import ActorContext
from app.db.session import actor_context
from app.models.tenant.initiative import (
    BUILTIN_MEMBER_ROLE,
    BUILTIN_ROLES,
    INITIATIVE_CUSTOM_ROLES,
    INITIATIVE_MEMBER_PREFIX,
    INITIATIVE_TOOL_KEYS,
    Initiative,
    InitiativeRoleModel,
    InitiativeRule,
)
from app.models.tenant.resource_grant import ResourceGrant


def _community(key: str):
    """The community's row for ``key``, over an alias of its own so it never
    correlates with a query that reads ``initiative_rules`` too."""
    row = aliased(InitiativeRule)
    return row, and_(
        row.initiative_id.is_(None),  # type: ignore[union-attr]
        row.install_id.is_(None),  # type: ignore[union-attr]
        row.key == key,
    )


def community_switch(context: ActorContext, tool: Tool | ToolRecord) -> bool | None:
    """The switch the community set for ``tool`` in every initiative, or
    ``None`` where each initiative sets its own."""
    if f"{tool.value}=on" in context.community_tools:
        return True
    if f"{tool.value}=off" in context.community_tools:
        return False
    return None


def own_switch(initiative: Any, tool: Tool | ToolRecord) -> bool:
    """Whether ``initiative``'s own switch has ``tool`` on, beneath anything
    its community set."""
    return tool.view_permission in (initiative.switched_on or ())


def switches(asked: Mapping[Tool, bool], tools: ToolSet) -> dict[ToolRecord, bool]:
    """Every tool's switch for a new initiative in a community with
    ``tools``: ``asked`` where it names one, the tool's record otherwise."""
    named = {tool.value: on for tool, on in asked.items()}
    return {tool: named.get(tool.kind, tool.spec.on_by_default) for tool in tools}


async def write_switches(
    session: AsyncSession,
    initiative_id: int,
    tools: Mapping[Tool, bool] | Mapping[ToolRecord, bool],
) -> None:
    """Set ``initiative_id``'s own switch for each tool in ``tools``, leaving
    the others as they are."""
    if not tools:
        return
    statement = pg_insert(InitiativeRule).values(
        [
            {
                "initiative_id": initiative_id,
                "key": tool.view_permission,
                "enabled": enabled,
            }
            for tool, enabled in tools.items()
        ]
    )
    await session.exec(
        statement.on_conflict_do_update(  # type: ignore[call-overload]
            constraint="uq_initiative_rules_subject",
            set_={"enabled": statement.excluded.enabled},
        )
    )


#: Rule rows per INSERT, well under the values a statement binds.
_RULE_ROWS_PER_INSERT = 1000


async def write_installed_tools(session: AsyncSession, tools: ToolSet) -> None:
    """Give every initiative what it would hold of ``tools``' installed tools
    had they been there when it was made: each one's switch, on, and each
    role's keys for it, as ``BuiltinRole.holds`` says (a custom role's as the
    member role's). Rows already there are kept, so a switch turned off stays
    off. Once the community's rules are rendered with ``tools``."""
    switches = [tool.view_permission for tool in tools.installed]
    keys = {*switches, *(tool.create_permission for tool in tools.installed)}
    holds = {role.name: role.holds(tools) for role in BUILTIN_ROLES}
    member = holds[BUILTIN_MEMBER_ROLE]
    role = InitiativeRoleModel
    rows = [
        (initiative_id, None, key, True)
        for initiative_id in (await session.exec(select(Initiative.id))).scalars()
        for key in switches
    ] + [
        (initiative_id, role_id, key, enabled)
        for role_id, initiative_id, name, builtin in await session.exec(
            select(role.id, role.initiative_id, role.name, role.is_builtin)
        )
        for key, enabled in (holds.get(name, member) if builtin else member).items()
        if key in keys
    ]
    columns = ("initiative_id", "initiative_role_id", "key", "enabled")
    for start in range(0, len(rows), _RULE_ROWS_PER_INSERT):
        await session.exec(
            pg_insert(InitiativeRule)
            .values(
                [
                    dict(zip(columns, row))
                    for row in rows[start : start + _RULE_ROWS_PER_INSERT]
                ]
            )
            .on_conflict_do_nothing(constraint="uq_initiative_rules_subject")
        )


async def forget_tool(session: AsyncSession, kinds: Sequence[str]) -> None:
    """Delete the rules and grants naming a tool plug-in's kinds (its own
    first), whoever wrote them: what a later install's tables would otherwise
    meet, and what the community's rules rendered without it refuse."""
    await session.exec(
        delete(ResourceGrant).where(col(ResourceGrant.resource_type).in_(kinds))
    )
    await session.exec(
        delete(InitiativeRule).where(
            col(InitiativeRule.install_id).is_(None),
            col(InitiativeRule.key).contains(kinds[0], autoescape=True),
        )
    )


def tool_on(context: ActorContext, initiative: Any, tool: Tool | ToolRecord) -> bool:
    """Whether ``tool`` is on in ``initiative``, by the request's standing."""
    switch = community_switch(context, tool)
    if switch is None:
        return own_switch(initiative, tool)
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
        return own_switch(initiative, tool)
    return switch


def tool_on_sql(tool: Tool) -> ColumnElement[bool]:
    """:func:`tool_on` over ``initiatives`` rows, for a query's filter. The
    community's row is read once for the statement."""
    row, where = _community(INITIATIVE_TOOL_KEYS[tool])
    own = aliased(InitiativeRule)
    return func.coalesce(
        select(row.enabled).where(where).scalar_subquery(),
        select(own.key)
        .where(
            own.initiative_id == Initiative.id,
            own.initiative_role_id.is_(None),  # type: ignore[union-attr]
            own.install_id.is_(None),  # type: ignore[union-attr]
            own.key == tool.view_permission,
            own.enabled.is_(True),  # type: ignore[union-attr]
        )
        .exists(),
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
            not_(role.is_builtin),
            not_(role.is_manager),
            select(off.key).where(custom_roles, off.enabled.is_(False)).exists(),  # type: ignore[union-attr]
        ),
    )
    return case(
        (held, select(value.enabled).where(where).scalar_subquery()), else_=None
    )
