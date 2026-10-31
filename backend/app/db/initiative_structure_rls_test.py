"""An initiative's structure is written by whoever manages it.

Each test writes on the real request login, routed through the seam, with no
guard of its own: what the database accepts is what the managed policies allow.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import select

from app.models.platform.guild import CommunityRole
from app.models.platform.user import UserRole
from app.models.tenant.initiative import InitiativeMember, InitiativeRule
from app.services.tenant import initiatives as initiatives_service
from app.testing import (
    create_access_grant,
    create_guild_membership,
    create_initiative,
    create_user,
    route_as,
)
from app.testing.schema_harness import route_session_to_guild


async def _writing_as(role_session, *, user_id: int, guild_id: int):
    s = await role_session("app_user")
    await route_as(s, user_id=user_id, guild_id=guild_id)
    return s


async def _member_role_id(session, initiative, guild_id: int) -> int:
    await route_session_to_guild(session, guild_id)
    role = await initiatives_service.get_member_role(
        session, initiative_id=initiative.id
    )
    assert role is not None and role.id is not None
    return role.id


async def _is_member(session, initiative, guild_id: int, user_id: int) -> bool:
    await route_session_to_guild(session, guild_id)
    row = (
        await session.exec(
            select(InitiativeMember).where(
                InitiativeMember.initiative_id == initiative.id,
                InitiativeMember.user_id == user_id,
            )
        )
    ).first()
    return row is not None


async def _add(s, initiative, user_id: int, role_id: int) -> None:
    s.add(
        InitiativeMember(initiative_id=initiative.id, user_id=user_id, role_id=role_id)
    )
    await s.commit()


async def test_a_manager_adds_a_member(session, acting_user, role_session):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    manager = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="project_manager",
    )
    newcomer = await create_user(session)
    await create_guild_membership(session, user=newcomer, guild=a.guild)
    role_id = await _member_role_id(session, a.initiative, a.guild.id)
    s = await _writing_as(role_session, user_id=manager.user.id, guild_id=a.guild.id)
    await _add(s, a.initiative, newcomer.id, role_id)
    assert await _is_member(session, a.initiative, a.guild.id, newcomer.id)


async def test_a_member_does_not_add_a_member(session, acting_user, role_session):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    newcomer = await create_user(session)
    await create_guild_membership(session, user=newcomer, guild=a.guild)
    role_id = await _member_role_id(session, a.initiative, a.guild.id)
    s = await _writing_as(role_session, user_id=member.user.id, guild_id=a.guild.id)
    with pytest.raises(DBAPIError, match="row-level security"):
        await _add(s, a.initiative, newcomer.id, role_id)
    await s.rollback()
    assert not await _is_member(session, a.initiative, a.guild.id, newcomer.id)


async def test_a_member_joins_an_open_initiative_and_not_a_private_one(
    session, acting_user, role_session
):
    a = await acting_user(guild_role=CommunityRole.admin)
    open_one = await create_initiative(session, a.guild, a.user, join_policy="open")
    private_one = await create_initiative(session, a.guild, a.user)
    member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    open_role = await _member_role_id(session, open_one, a.guild.id)
    private_role = await _member_role_id(session, private_one, a.guild.id)

    s = await _writing_as(role_session, user_id=member.user.id, guild_id=a.guild.id)
    await _add(s, open_one, member.user.id, open_role)
    assert await _is_member(session, open_one, a.guild.id, member.user.id)

    s = await _writing_as(role_session, user_id=member.user.id, guild_id=a.guild.id)
    with pytest.raises(DBAPIError, match="row-level security"):
        await _add(s, private_one, member.user.id, private_role)
    await s.rollback()
    assert not await _is_member(session, private_one, a.guild.id, member.user.id)


async def test_a_content_grant_manages_no_roster(session, acting_user, role_session):
    """Editing existing content is not membership management."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    support = await create_user(session, role=UserRole.support)
    await create_access_grant(
        session, user=support, guild=a.guild, access_level="read_write"
    )
    newcomer = await create_user(session)
    await create_guild_membership(session, user=newcomer, guild=a.guild)
    role_id = await _member_role_id(session, a.initiative, a.guild.id)
    s = await _writing_as(role_session, user_id=support.id, guild_id=a.guild.id)
    with pytest.raises(DBAPIError, match="row-level security"):
        await _add(s, a.initiative, newcomer.id, role_id)
    await s.rollback()
    assert not await _is_member(session, a.initiative, a.guild.id, newcomer.id)


@pytest.mark.parametrize("rung", ["admin", "superadmin"])
async def test_a_settings_rung_beside_read_write_manages_the_roster(
    session, acting_user, role_session, rung
):
    """The two asks together: the rung names the surface, the read_write grant
    lets it be changed — the roster included, at either rung."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    support = await create_user(session, role=UserRole.support)
    await create_access_grant(
        session, user=support, guild=a.guild, access_level=rung, purpose="settings"
    )
    await create_access_grant(
        session, user=support, guild=a.guild, access_level="read_write"
    )
    newcomer = await create_user(session)
    await create_guild_membership(session, user=newcomer, guild=a.guild)
    role_id = await _member_role_id(session, a.initiative, a.guild.id)
    s = await _writing_as(role_session, user_id=support.id, guild_id=a.guild.id)
    await _add(s, a.initiative, newcomer.id, role_id)
    assert await _is_member(session, a.initiative, a.guild.id, newcomer.id)


async def test_a_settings_rung_alone_reads_the_roster_and_does_not_write_it(
    session, acting_user, role_session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    support = await create_user(session, role=UserRole.support)
    await create_access_grant(
        session, user=support, guild=a.guild, access_level="admin", purpose="settings"
    )
    newcomer = await create_user(session)
    await create_guild_membership(session, user=newcomer, guild=a.guild)
    role_id = await _member_role_id(session, a.initiative, a.guild.id)
    s = await role_session("app_user")
    await route_as(s, user_id=support.id, guild_id=a.guild.id, settings=True)
    assert list(await s.exec(select(InitiativeMember.user_id))) == [a.user.id]
    with pytest.raises(DBAPIError, match="permission denied|row-level security"):
        await _add(s, a.initiative, newcomer.id, role_id)
    await s.rollback()
    assert not await _is_member(session, a.initiative, a.guild.id, newcomer.id)


async def test_the_administrator_adds_a_member_anywhere(
    session, acting_user, role_session
):
    a = await acting_user(guild_role=CommunityRole.admin)
    initiative = await create_initiative(session, a.guild, a.user)
    admin = await acting_user(guild_role=CommunityRole.admin, guild=a.guild)
    newcomer = await create_user(session)
    await create_guild_membership(session, user=newcomer, guild=a.guild)
    role_id = await _member_role_id(session, initiative, a.guild.id)
    s = await _writing_as(role_session, user_id=admin.user.id, guild_id=a.guild.id)
    await _add(s, initiative, newcomer.id, role_id)
    assert await _is_member(session, initiative, a.guild.id, newcomer.id)


async def test_only_an_admin_writes_the_communitys_initiative_defaults(
    acting_user, role_session
):
    """The community's own ``initiative_rules`` rows, the ones with no
    initiative, are its admins' to write: a manager of every initiative in it
    writes none."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    pm = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="project_manager",
    )

    async def writes(actor) -> bool:
        s = await _writing_as(
            role_session, user_id=actor.user.id, guild_id=admin.guild.id
        )
        s.add(InitiativeRule(key="initiative_tool.post", enabled=False))
        try:
            await s.commit()
        except DBAPIError:
            return False
        finally:
            await s.rollback()
        return True

    assert not await writes(pm)
    assert await writes(admin)


async def test_whether_an_initiative_auto_joins_or_is_archived_is_the_communitys(
    acting_user, role_session
):
    """Its managers rename it; joining new members to it and archiving it are
    the community's: a holder of the initiatives surface."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    manager = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="project_manager",
    )
    iid = admin.initiative.id

    async def changes(actor, assignment: str) -> bool:
        s = await _writing_as(
            role_session, user_id=actor.user.id, guild_id=admin.guild.id
        )
        try:
            await s.exec(text(f"UPDATE initiatives SET {assignment} WHERE id = {iid}"))
            await s.commit()
        except DBAPIError:
            return False
        finally:
            await s.rollback()
        return True

    assert await changes(manager, "name = 'Renamed'")
    assert not await changes(manager, "join_policy = 'open', auto_join = true")
    assert not await changes(manager, "archived_at = now()")
    assert await changes(admin, "join_policy = 'open', auto_join = true")
    assert await changes(admin, "archived_at = now()")


async def test_a_private_initiative_reads_as_absent_to_anybody_not_in_it(
    session, acting_user, role_session
):
    """Its row, not only its content: its members, the community's admin and
    the system engine read it; another member of the community reads none,
    while an initiative on offer stays readable to them."""
    admin = await acting_user(guild_role=CommunityRole.admin)
    private_one = await create_initiative(session, admin.guild, admin.user)
    open_one = await create_initiative(
        session, admin.guild, admin.user, join_policy="open"
    )
    insider = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=private_one,
        initiative_role="member",
    )
    outsider = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)
    ids = (private_one.id, open_one.id)

    async def reads(actor) -> set[int]:
        s = await _writing_as(
            role_session, user_id=actor.user.id, guild_id=admin.guild.id
        )
        rows = await s.exec(text(f"SELECT id FROM initiatives WHERE id IN {ids}"))
        return set(rows.scalars().all())

    assert await reads(admin) == set(ids)
    assert await reads(insider) == set(ids)
    assert await reads(outsider) == {open_one.id}


async def test_a_member_defines_a_field_and_only_a_manager_reshapes_it(
    acting_user, role_session
):
    """Any member defines an initiative's field and adds options to it as they
    pick a value nobody offered; renaming or removing it is its managers'."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    manager = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="project_manager",
    )
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    iid = admin.initiative.id

    async def runs(actor, sql: str) -> bool:
        s = await _writing_as(
            role_session, user_id=actor.user.id, guild_id=admin.guild.id
        )
        try:
            changed = (await s.exec(text(sql))).rowcount
            await s.commit()
        except DBAPIError:
            return False
        finally:
            await s.rollback()
        return changed > 0

    assert await runs(
        member,
        "INSERT INTO metadata_definitions"
        " (initiative_id, name, type, position, options, created_at, updated_at)"
        f" VALUES ({iid}, 'Stage', 'select', 0, '[{{\"value\": \"a\"}}]'::jsonb,"
        " now(), now())",
    )
    field = f"name = 'Stage' AND initiative_id = {iid}"
    assert await runs(
        member,
        "UPDATE metadata_definitions SET options = options"
        f' || \'[{{"value": "b"}}]\'::jsonb WHERE {field}',
    )
    # An option already there keeps its label: a second one with its value is
    # not an addition.
    assert not await runs(
        member,
        "UPDATE metadata_definitions SET options = options"
        f' || \'[{{"value": "a", "label": "Changed"}}]\'::jsonb WHERE {field}',
    )
    assert not await runs(
        member, f"UPDATE metadata_definitions SET name = 'Phase' WHERE {field}"
    )
    assert not await runs(
        member, f"UPDATE metadata_definitions SET options = '[]'::jsonb WHERE {field}"
    )
    assert not await runs(member, f"DELETE FROM metadata_definitions WHERE {field}")
    assert await runs(
        manager, f"UPDATE metadata_definitions SET name = 'Phase' WHERE {field}"
    )
    assert await runs(
        manager,
        f"DELETE FROM metadata_definitions WHERE name = 'Phase' AND initiative_id = {iid}",
    )
