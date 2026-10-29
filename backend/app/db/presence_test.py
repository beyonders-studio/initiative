"""What a member may know exists without opening it, held by the database:
the rows of the initiatives they are a member of, and nothing beyond them."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.models.platform.guild import CommunityRole
from app.services.platform import app_settings as app_settings_service
from app.services.platform import rules
from app.testing import (
    create_file,
    create_guest,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_project,
    create_resource_grant,
    create_task,
    create_user,
)
from app.testing.routing import route_as


@pytest.fixture(autouse=True)
async def _guests_on(session):
    await app_settings_service.ensure_settings_row(session)
    await rules.put(session, "guests_enabled", True)
    await session.commit()


async def _rows(s, sql: str) -> set[tuple]:
    return {tuple(row) for row in (await s.exec(text(sql))).all()}


async def _as(role_session, user_id: int, guild_id: int):
    s = await role_session("app_user")
    await route_as(s, user_id=user_id, guild_id=guild_id)
    return s


async def test_a_member_knows_what_is_in_their_initiative_and_no_more(
    session, acting_user, role_session
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    hidden = await create_file(session, a.initiative, a.user)
    await create_file(
        session, a.initiative, a.user, deleted_at=datetime.now(timezone.utc)
    )
    project = await create_project(session, a.initiative, a.user)
    task = await create_task(session, project)
    elsewhere = await create_initiative(session, a.guild, a.user)
    await create_file(session, elsewhere, a.user)
    reader = await create_user(session)
    await create_guild_membership(session, user=reader, guild=a.guild)
    await create_initiative_member(session, a.initiative, reader)
    ids = (a.initiative.id, hidden.id, project.id, task.id, reader.id)

    initiative_id, hidden_id, project_id, task_id, reader_id = ids
    s = await _as(role_session, reader_id, a.guild.id)

    assert await _rows(s, "SELECT id FROM files") == set()
    assert await _rows(
        s, "SELECT kind, id, initiative_id, trashed, tool, tool_id FROM entity_presence"
    ) == {
        # The trash reads as absent to a member, here as anywhere.
        ("file", hidden_id, initiative_id, False, "file", hidden_id),
        ("project", project_id, initiative_id, False, "project", project_id),
        ("task", task_id, initiative_id, False, "project", project_id),
    }


async def test_an_item_guest_knows_of_nothing_and_an_initiative_guest_as_members_do(
    session, acting_user, role_session
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    given = await create_file(session, a.initiative, a.user)
    hidden = await create_file(session, a.initiative, a.user)
    item_guest = await create_guest(session, a.guild)
    await create_resource_grant(session, given, user=item_guest)
    member_guest = await create_guest(session, a.guild)
    await create_initiative_member(session, a.initiative, member_guest)
    ids = (given.id, hidden.id, item_guest.id, member_guest.id)

    given_id, hidden_id, item_guest_id, member_guest_id = ids
    s = await _as(role_session, item_guest_id, a.guild.id)
    assert await _rows(s, "SELECT id FROM files") == {(given_id,)}
    # What they can open, and nothing else.
    assert await _rows(s, "SELECT id FROM entity_presence") == {(given_id,)}

    s = await _as(role_session, member_guest_id, a.guild.id)
    assert await _rows(s, "SELECT id FROM entity_presence WHERE kind = 'file'") == {
        (given_id,),
        (hidden_id,),
    }


async def test_nobody_writes_through_the_view(session, acting_user, role_session):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    file = await create_file(session, a.initiative, a.user)
    file_id, user_id = file.id, a.user.id

    s = await _as(role_session, user_id, a.guild.id)
    privileges = await _rows(
        s,
        "SELECT has_table_privilege('entity_presence', 'INSERT'),"
        " has_table_privilege('entity_presence', 'SELECT')",
    )
    assert privileges == {(False, True)}
    assert await _rows(s, f"SELECT id FROM entity_presence WHERE id = {file_id}") == {
        (file_id,)
    }
