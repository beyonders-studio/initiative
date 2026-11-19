"""An initiative's tools and roles, once its community's defaults apply.

Each initiative's own switch for a tool is one of its ``initiative_rules``
rows: no role, no install, the tool's view key (``Initiative.switched_on``
holds the keys whose row is on). A tool with no row is off.

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

from collections.abc import Mapping
from typing import Any

from sqlalchemy import and_, case, exists, func, not_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
    return row, and_(
        row.initiative_id.is_(None),  # type: ignore[union-attr]
        row.install_id.is_(None),  # type: ignore[union-attr]
        row.key == key,
    )


def community_switch(context: ActorContext, tool: Tool) -> bool | None:
    """The switch the community set for ``tool`` in every initiative, or
    ``None`` where each initiative sets its own."""
    if f"{tool.value}=on" in context.community_tools:
        return True
    if f"{tool.value}=off" in context.community_tools:
        return False
    return None


def own_switch(initiative: Any, tool: Tool) -> bool:
    """Whether ``initiative``'s own switch has ``tool`` on, beneath anything
    its community set."""
    return tool.view_permission in (initiative.switched_on or ())


def switches(tools: Mapping[Tool, bool]) -> dict[Tool, bool]:
    """Every tool's switch for a new initiative: ``tools`` where it names one,
    the tool's record otherwise."""
    return {tool: tools.get(tool, tool.spec.on_by_default) for tool in Tool}


async def write_switches(
    session: AsyncSession, initiative_id: int, tools: Mapping[Tool, bool]
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


async def write_plugin_tool_rules(
    session: AsyncSession, *, initiative_id: int | None = None
) -> None:
    """Give every installed tool plug-in's tool what a built-in tool has in an
    initiative: its switch, on, and each role's keys, as a built-in role holds
    a tool's (a manager both, anyone else viewing it and not creating it). In
    ``initiative_id``, or in every initiative. The rows are the install's.
    Rows already there are kept as they are."""
    from app.models.tenant.guild_plugin import GuildPlugin
    from app.models.tenant.initiative import Initiative, InitiativeRoleModel
    from app.services.marketplace.tool_plugins import TOOL, tool_kinds

    installs = (
        await session.exec(
            select(GuildPlugin.id, GuildPlugin.listing_uid, GuildPlugin.definition)
            .where(GuildPlugin.plugin_kind == TOOL)
            .order_by(GuildPlugin.id)
        )
    ).all()
    if not installs:
        return
    initiatives = select(Initiative.id)
    roles = select(
        InitiativeRoleModel.id,
        InitiativeRoleModel.initiative_id,
        InitiativeRoleModel.is_manager,
    )
    if initiative_id is not None:
        initiatives = initiatives.where(Initiative.id == initiative_id)
        roles = roles.where(InitiativeRoleModel.initiative_id == initiative_id)
    initiative_ids = (await session.exec(initiatives)).scalars().all()
    role_rows = (await session.exec(roles)).all()
    rows: list[dict[str, Any]] = []
    for install_id, listing_uid, definition in installs:
        kind = tool_kinds(definition, listing_uid=listing_uid)[0]
        view, create = f"{kind}:enabled", f"{kind}:create"
        rows += [
            {
                "initiative_id": i,
                "initiative_role_id": None,
                "key": view,
                "enabled": True,
                "install_id": install_id,
            }
            for i in initiative_ids
        ]
        rows += [
            {
                "initiative_id": role_initiative,
                "initiative_role_id": role_id,
                "key": key,
                "enabled": enabled,
                "install_id": install_id,
            }
            for role_id, role_initiative, is_manager in role_rows
            for key, enabled in ((view, True), (create, bool(is_manager)))
        ]
    if rows:
        await session.exec(
            pg_insert(InitiativeRule)
            .values(rows)
            .on_conflict_do_nothing(constraint="uq_initiative_rules_subject")
        )


def tool_on(context: ActorContext, initiative: Any, tool: Tool) -> bool:
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
        exists().where(
            own.initiative_id == Initiative.id,
            own.initiative_role_id.is_(None),  # type: ignore[union-attr]
            own.install_id.is_(None),  # type: ignore[union-attr]
            own.key == tool.view_permission,
            own.enabled.is_(True),  # type: ignore[union-attr]
        ),
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
            exists().where(custom_roles, off.enabled.is_(False)),  # type: ignore[union-attr]
        ),
    )
    return case(
        (held, select(value.enabled).where(where).scalar_subquery()), else_=None
    )
