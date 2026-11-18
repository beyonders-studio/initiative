"""Who writes an initiative's tool switch.

A switch is one of the initiative's ``initiative_rules`` rows (no role, no
install), written under the rules table's ``managed_*`` policies. Before it
was a row it was a column on ``initiatives``, written by whoever may update
the initiative. These hold the two to the same people, rung by rung, on the
request login routed through the seam, and through the route that writes it.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.guild import CommunityRole
from app.models.tenant.initiative import Initiative, InitiativeRule
from app.testing import Actor, create_initiative, route_session_to_guild

#: insufficient_privilege: a row a policy refuses.
_REFUSED = "42501"


@dataclass(frozen=True)
class _Workspace:
    admin: Actor
    a: Initiative
    b: Initiative


async def _workspace(session: AsyncSession, acting_user) -> _Workspace:
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    b = await create_initiative(session, owner.guild, owner.user)
    # The community admin under test is in no initiative.
    admin = await acting_user(guild_role=CommunityRole.admin, guild=owner.guild)
    return _Workspace(admin, owner.initiative, b)


async def _rung(acting_user, w: _Workspace, rung: str) -> Actor:
    guild = w.admin.guild
    if rung == "community admin":
        return w.admin
    if rung == "initiative manager":
        return await acting_user(guild=guild, initiative=w.a)
    if rung == "plain member":
        return await acting_user(guild=guild, initiative=w.a, initiative_role="member")
    if rung == "manager of another initiative":
        return await acting_user(guild=guild, initiative=w.b)
    return await acting_user(guild=guild)


#: Each rung, and whether it may change the initiative's setup.
RUNGS = {
    "community admin": True,
    "initiative manager": True,
    "plain member": False,
    "manager of another initiative": False,
    "community member in no initiative": False,
}


async def _attempt(session: AsyncSession, statement: sa.Executable) -> int | str:
    """The rows ``statement`` touched, or the SQLSTATE it raised, rolled back
    either way."""
    savepoint = await session.begin_nested()
    try:
        touched = (await session.exec(statement)).rowcount
    except DBAPIError as error:
        await savepoint.rollback()
        return getattr(error.orig, "sqlstate", None) or getattr(
            getattr(error.orig, "__cause__", None), "sqlstate", repr(error.orig)
        )
    await savepoint.rollback()
    return touched


def _switch(initiative_id: int, tool: Tool) -> sa.ColumnElement[bool]:
    return sa.and_(
        InitiativeRule.initiative_id == initiative_id,
        InitiativeRule.initiative_role_id.is_(None),  # type: ignore[union-attr]
        InitiativeRule.install_id.is_(None),  # type: ignore[union-attr]
        InitiativeRule.key == tool.view_permission,
    )


@pytest.mark.parametrize("rung", list(RUNGS))
async def test_a_switch_row_is_written_by_who_updates_the_initiative(
    session: AsyncSession, acting_user, reading_as, rung: str
) -> None:
    w = await _workspace(session, acting_user)
    actor = await _rung(acting_user, w, rung)
    # One tool's row is gone, for an INSERT to put back.
    await route_session_to_guild(session, w.admin.guild.id)
    await session.exec(sa.delete(InitiativeRule).where(_switch(w.a.id, Tool.contact)))
    await session.commit()

    reader = await reading_as(actor.user.id, w.admin.guild.id)
    initiative = await _attempt(
        reader,
        sa.update(Initiative)
        .where(Initiative.id == w.a.id)
        .values(name=Initiative.name),
    )
    rule = InitiativeRule.__table__  # type: ignore[attr-defined]
    answers = {
        "INSERT": await _attempt(
            reader,
            sa.insert(rule)
            .values(
                initiative_id=w.a.id, key=Tool.contact.view_permission, enabled=True
            )
            .inline(),
        ),
        "UPDATE": await _attempt(
            reader,
            sa.update(rule)
            .where(_switch(w.a.id, Tool.post))
            .values(enabled=sa.not_(rule.c.enabled)),
        ),
        "DELETE": await _attempt(
            reader, sa.delete(rule).where(_switch(w.a.id, Tool.post))
        ),
    }
    await reader.rollback()

    if RUNGS[rung]:
        assert initiative == 1
        assert answers == {"INSERT": 1, "UPDATE": 1, "DELETE": 1}
    else:
        assert initiative == 0
        assert answers == {"INSERT": _REFUSED, "UPDATE": 0, "DELETE": 0}


@pytest.mark.parametrize("rung", list(RUNGS))
async def test_the_route_switches_a_tool_for_the_same_rungs(
    session: AsyncSession, client, acting_user, rung: str
) -> None:
    w = await _workspace(session, acting_user)
    actor = await _rung(acting_user, w, rung)

    response = await client.patch(
        actor.g(f"/initiatives/{w.a.id}"),
        headers=actor.headers,
        json={"tools": {Tool.post.value: False}},
    )

    owner = await client.get(
        w.admin.g(f"/initiatives/{w.a.id}"), headers=w.admin.headers
    )
    if RUNGS[rung]:
        assert response.status_code == 200, response.text
        assert response.json()["tools"][Tool.post.value] is False
        assert owner.json()["tools"][Tool.post.value] is False
    else:
        assert response.status_code in (403, 404), response.text
        assert owner.json()["tools"][Tool.post.value] is True
