"""The plan and status triggers of migrations 0364 and 0561, on the real
logins.

Every write here runs twice over: with ``public.billing_managed()`` answering
false, where it must land, and answering true, where only the moves the rule
names may. A trigger that refused everything would pass the second half alone.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.public_rls import role_name
from app.testing import create_guild
from app.testing.billing_managed import billing_manages_plans


async def _set_recorded(session: AsyncSession, guild_id: int, value: str | None):
    await session.exec(
        text(
            "UPDATE public.guild_administration SET billing_status = :v"
            " WHERE guild_id = :g"
        ).bindparams(v=value, g=guild_id)
    )
    await session.commit()


async def _set_status(session: AsyncSession, guild_id: int, value: str) -> None:
    await session.exec(
        text("UPDATE public.guilds SET status = :v WHERE id = :g").bindparams(
            v=value, g=guild_id
        )
    )
    await session.commit()


async def _as_system(role_session, sql: str, **params) -> None:
    s = await role_session("app_admin")
    try:
        await s.exec(text(sql).bindparams(**params))
        await s.commit()
    finally:
        await s.rollback()


async def _as_billing(role_session, guild_id: int, sql: str, **params) -> None:
    s = await role_session("app_user")
    try:
        await s.exec(
            text(
                "SELECT set_config('role', :role, true),"
                " set_config('app.billing_guild_id', :g, true)"
            ).bindparams(
                role=role_name("initiative_billing"),
                g=str(guild_id),
            )
        )
        await s.exec(text(sql).bindparams(**params))
        await s.commit()
    finally:
        await s.rollback()


#: A cap is a deployment row of the community's rules.
_CAPS = (
    "INSERT INTO public.community_rules (guild_id, key, set_by, amount, updated_at)"
    " VALUES (:g, 'max_users', 'deployment', :v, now())"
)
_STATUS = "UPDATE public.guilds SET status = :v WHERE id = :g"


async def _status_of(session: AsyncSession, guild_id: int) -> str:
    session.expire_all()
    return (
        await session.exec(
            text("SELECT status FROM public.guilds WHERE id = :g").bindparams(
                g=guild_id
            )
        )
    ).one()[0]


async def test_the_function_answers_false_until_boot_renders_it(session):
    assert (await session.exec(text("SELECT public.billing_managed()"))).one()[
        0
    ] is False


async def test_the_system_engine_sets_the_plan_where_billing_does_not(
    session, role_session
):
    gid = (await create_guild(session)).id

    await _as_system(role_session, _CAPS, v=25, g=gid)
    await _as_system(role_session, _STATUS, v="read_only", g=gid)

    assert await _status_of(session, gid) == "read_only"


async def test_a_restore_lands_at_any_status_where_billing_does_not_set_plans(
    session, role_session
):
    gid = (await create_guild(session)).id
    await _set_recorded(session, gid, "read_only")
    await _set_status(session, gid, "deleted")

    await _as_system(role_session, _STATUS, v="active", g=gid)

    assert await _status_of(session, gid) == "active"


async def test_nobody_but_billing_sets_the_plan_where_billing_does(
    session, role_session
):
    gid = (await create_guild(session)).id
    async with billing_manages_plans(session):
        with pytest.raises(DBAPIError, match="COMMUNITY_PLAN_SET_BY_BILLING"):
            await _as_system(role_session, _CAPS, v=25, g=gid)
        # The superuser is held to it too.
        with pytest.raises(DBAPIError, match="COMMUNITY_PLAN_SET_BY_BILLING"):
            await session.exec(text(_CAPS).bindparams(v=25, g=gid))
        await session.rollback()

        await _as_billing(role_session, gid, _CAPS, v=25, g=gid)


async def test_a_community_takes_its_plan_with_it_where_billing_sets_plans(
    session, role_session
):
    """Its rows going with the community is not a write anybody made."""
    gid = (await create_guild(session)).id
    await _as_system(role_session, _CAPS, v=25, g=gid)
    async with billing_manages_plans(session):
        await _as_system(role_session, "DELETE FROM public.guilds WHERE id = :g", g=gid)

    assert (
        await session.exec(
            text(
                "SELECT count(*) FROM public.community_rules WHERE guild_id = :g"
            ).bindparams(g=gid)
        )
    ).one()[0] == 0


@pytest.mark.parametrize(
    "start,recorded,target,lands",
    [
        pytest.param("active", None, "suspended", True, id="suspend"),
        pytest.param("on_hold", "on_hold", "suspended", True, id="suspend-on-hold"),
        pytest.param("active", None, "read_only", False, id="active-to-read-only"),
        pytest.param("active", None, "on_hold", False, id="active-to-on-hold"),
        pytest.param("suspended", "on_hold", "on_hold", True, id="lift-to-recorded"),
        pytest.param("suspended", None, "active", True, id="lift-to-active"),
        pytest.param("suspended", "on_hold", "active", False, id="lift-elsewhere"),
        pytest.param("active", None, "deleted", True, id="delete"),
        pytest.param("deleted", None, "active", True, id="restore"),
        pytest.param("deleted", None, "read_only", False, id="restore-unrecorded"),
        pytest.param(
            "deleted", "read_only", "read_only", True, id="restore-to-recorded"
        ),
        pytest.param("deleted", "read_only", "active", False, id="restore-elsewhere"),
        pytest.param("deleted", "read_only", "suspended", True, id="restore-suspended"),
    ],
)
async def test_the_operators_status_moves_where_billing_sets_plans(
    session, role_session, start, recorded, target, lands
):
    gid = (await create_guild(session)).id
    await _set_status(session, gid, start)
    await _set_recorded(session, gid, recorded)

    async with billing_manages_plans(session):
        if lands:
            await _as_system(role_session, _STATUS, v=target, g=gid)
            assert await _status_of(session, gid) == target
        else:
            with pytest.raises(DBAPIError, match="COMMUNITY_STATUS_SET_BY_BILLING"):
                await _as_system(role_session, _STATUS, v=target, g=gid)
            assert await _status_of(session, gid) == start


@pytest.mark.parametrize(
    "start,target,lands",
    [
        pytest.param("active", "on_hold", True, id="hold"),
        pytest.param("on_hold", "read_only", True, id="between-its-own"),
        pytest.param("active", "suspended", False, id="suspend"),
        pytest.param("suspended", "active", False, id="lift"),
        pytest.param("deleted", "active", False, id="restore"),
    ],
)
async def test_billing_moves_only_between_its_own_statuses(
    session, role_session, start, target, lands
):
    gid = (await create_guild(session)).id
    await _set_status(session, gid, start)

    async with billing_manages_plans(session):
        if lands:
            await _as_billing(role_session, gid, _STATUS, v=target, g=gid)
            assert await _status_of(session, gid) == target
        else:
            with pytest.raises(DBAPIError, match="COMMUNITY_STATUS_SET_BY_BILLING"):
                await _as_billing(role_session, gid, _STATUS, v=target, g=gid)
            assert await _status_of(session, gid) == start
