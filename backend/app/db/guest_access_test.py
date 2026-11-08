"""What a guest's request reaches, held by the database: the items shared with
them and the initiatives they are in, and nothing community-wide."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.guild_standing import compute_guild_standing
from app.db.request_context import Member
from app.db.session import set_rls_context
from app.models.platform.guild import CommunityRole, CommunityStatus
from app.models.tenant.comment import Comment
from app.models.tenant.custom_role import CustomRole, CustomRoleMember
from app.models.tenant.project import Project
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.services.platform import app_settings as app_settings_service
from app.services.platform import rules
from app.testing import (
    create_guest,
    create_guild_calendar,
    create_initiative,
    create_initiative_member,
    create_project,
    create_resource_grant,
    create_task,
    create_upload,
    get_auth_headers,
    grant_role_permission,
)
from app.testing.routing import route_as
from app.testing.schema_harness import route_session_to_guild


@pytest.fixture(autouse=True)
async def _guests_on(session):
    await app_settings_service.ensure_settings_row(session)
    await rules.put(session, "guests_enabled", True)
    await session.commit()


async def _ids(s, sql: str) -> set[int]:
    return set((await s.exec(text(sql))).scalars().all())


async def _routed(role_session, user_id: int, guild_id: int):
    s = await role_session("app_user")
    return s, await route_as(s, user_id=user_id, guild_id=guild_id)


async def test_a_guest_given_one_item_reaches_it_and_nothing_else_there(
    session, acting_user, role_session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    other = await create_project(session, a.initiative, a.user)
    task = await create_task(session, a.project)
    await create_task(session, other)
    guest = await create_guest(session, a.guild)
    await create_resource_grant(session, a.project, user=guest)
    initiative_id, project_id, task_id, guest_id = (
        a.initiative.id,
        a.project.id,
        task.id,
        guest.id,
    )

    s, context = await _routed(role_session, guest_id, a.guild.id)

    assert context.guest and context.guest_item_initiatives == (initiative_id,)
    assert context.member_initiatives == ()
    assert (await s.exec(text("SELECT current_user"))).scalar().endswith("_guest")
    assert await _ids(s, "SELECT id FROM projects") == {project_id}
    assert await _ids(s, "SELECT id FROM tasks") == {task_id}
    assert await _ids(s, "SELECT id FROM initiatives") == {initiative_id}
    assert await _ids(s, "SELECT user_id FROM initiative_members") == set()
    assert await _ids(s, "SELECT user_id FROM resource_grants") == {guest_id}
    s.add(Project(name="Mine", initiative_id=initiative_id, created_by=guest_id))
    with pytest.raises(DBAPIError):
        await s.flush()


async def test_a_guest_opens_a_project_shared_with_them(client, session, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    guest = await create_guest(session, a.guild)
    await create_resource_grant(session, a.project, user=guest)

    response = await client.get(
        a.g(f"/projects/{a.project.id}"), headers=get_auth_headers(guest)
    )

    assert response.status_code == 200, response.text


async def test_a_guest_makes_a_project_that_is_theirs_alone(
    client, session, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await grant_role_permission(session, a.initiative, "create_projects")
    guest = await create_guest(session, a.guild)
    await create_initiative_member(session, a.initiative, guest)

    response = await client.post(
        a.g("/projects/"),
        headers=get_auth_headers(guest),
        json={"name": "Mine", "initiative_id": a.initiative.id},
    )

    assert response.status_code == 201, response.text


async def test_a_guest_reads_the_files_of_the_initiatives_it_reaches(
    session, acting_user, role_session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    guest = await create_guest(session, a.guild)
    await create_resource_grant(session, a.project, user=guest)
    now = datetime.now(timezone.utc)
    shown = await create_upload(
        session, a.guild, a.user, initiative_id=a.initiative.id, claimed_at=now
    )
    await create_upload(session, a.guild, a.user, claimed_at=now)
    shown_id, guest_id = shown.id, guest.id

    s, _ = await _routed(role_session, guest_id, a.guild.id)

    assert await _ids(s, "SELECT id FROM uploads") == {shown_id}


@pytest.mark.parametrize(
    ("level", "held", "renamed"),
    [
        (ResourceAccessLevel.read, "read", 0),
        (ResourceAccessLevel.write, "write", 1),
        # A guest is never more than a writer.
        (ResourceAccessLevel.owner, "write", 1),
    ],
)
async def test_a_guest_holds_what_was_shared_and_at_most_write(
    session, acting_user, role_session, level, held, renamed
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    guest = await create_guest(session, a.guild)
    if level is ResourceAccessLevel.owner:
        project = await create_project(session, a.initiative, guest)
    else:
        project = await create_project(session, a.initiative, a.user)
        await create_resource_grant(session, project, user=guest, level=level)
    project_id, initiative_id, guest_id = project.id, a.initiative.id, guest.id

    s, _ = await _routed(role_session, guest_id, a.guild.id)
    level_held, actions = (
        await s.exec(
            text(
                "SELECT resource_level('project', :p, :u, :i, current_standing()),"
                " resource_actions('project', :p, :u, :i, NULL, NULL,"
                " current_standing())"
            ).bindparams(p=project_id, u=guest_id, i=initiative_id)
        )
    ).one()
    result = await s.exec(
        text("UPDATE projects SET name = 'Renamed' WHERE id = :p").bindparams(
            p=project_id
        )
    )

    assert level_held == held
    assert not {"share", "export", "configure", "delete"} & set(actions)
    assert result.rowcount == renamed


async def test_a_guest_in_an_initiative_reaches_it_as_its_members_do_and_no_other(
    session, acting_user, role_session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    shared = await create_project(session, a.initiative, a.user)
    await create_resource_grant(session, shared, all_initiative_members=True)
    elsewhere = await create_initiative(session, a.guild, a.user)
    hidden = await create_project(session, elsewhere, a.user)
    await create_resource_grant(session, hidden, all_initiative_members=True)
    guest = await create_guest(session, a.guild)
    await create_initiative_member(session, a.initiative, guest)
    ids = (a.initiative.id, shared.id, a.user.id, guest.id)

    s, context = await _routed(role_session, guest.id, a.guild.id)

    initiative_id, shared_id, admin_id, guest_id = ids
    assert context.member_initiatives == (initiative_id,)
    assert await _ids(s, "SELECT id FROM projects") == {shared_id}
    assert await _ids(s, "SELECT id FROM initiatives") == {initiative_id}
    assert await _ids(s, "SELECT user_id FROM initiative_members") == {
        admin_id,
        guest_id,
    }


async def test_a_guest_whose_role_creates_makes_a_project_it_writes(
    session, acting_user, role_session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await grant_role_permission(session, a.initiative, "create_projects")
    guest = await create_guest(session, a.guild)
    await create_initiative_member(session, a.initiative, guest)
    initiative_id, guest_id = a.initiative.id, guest.id

    s, _ = await _routed(role_session, guest_id, a.guild.id)
    project = Project(name="Mine", initiative_id=initiative_id, created_by=guest_id)
    s.add(project)
    await s.flush()
    held = (
        await s.exec(
            text(
                "SELECT resource_level('project', :p, :u, :i, current_standing())"
            ).bindparams(p=project.id, u=guest_id, i=initiative_id)
        )
    ).scalar()

    assert held == "write"


async def test_a_community_wide_share_reaches_members_and_not_guests(
    session, acting_user, role_session
):
    a = await acting_user(guild_role=CommunityRole.admin)
    calendar = await create_guild_calendar(session, a.guild, a.user)
    member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    guest = await create_guest(session, a.guild)
    guild_id, calendar_id = a.guild.id, calendar.id

    as_member, _ = await _routed(role_session, member.user.id, guild_id)
    as_guest, _ = await _routed(role_session, guest.id, guild_id)

    assert await _ids(as_member, "SELECT id FROM calendars") == {calendar_id}
    assert await _ids(as_guest, "SELECT id FROM calendars") == set()


@pytest.mark.parametrize("reached", [True, False])
async def test_a_guest_comments_on_what_it_reaches_only(
    session, acting_user, role_session, reached
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project)
    guest = await create_guest(session, a.guild)
    if reached:
        await create_resource_grant(session, a.project, user=guest)
    task_id, guest_id = task.id, guest.id

    s, _ = await _routed(role_session, guest_id, a.guild.id)
    s.add(Comment(content="Looks good", task_id=task_id, created_by=guest_id))

    if reached:
        await s.flush()
    else:
        with pytest.raises(DBAPIError):
            await s.flush()


async def test_a_guest_reads_its_own_membership_and_no_one_in_public(
    session, acting_user, role_session
):
    a = await acting_user(guild_role=CommunityRole.admin)
    guest = await create_guest(session, a.guild)
    guest_id = guest.id

    s, _ = await _routed(role_session, guest_id, a.guild.id)

    assert await _ids(s, "SELECT user_id FROM public.guild_memberships") == {guest_id}
    with pytest.raises(DBAPIError, match="permission denied"):
        await s.exec(text("SELECT id FROM public.users"))


async def test_a_guest_in_a_read_only_community_changes_nothing(
    session, acting_user, role_session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    guest = await create_guest(session, a.guild)
    await create_resource_grant(
        session, a.project, user=guest, level=ResourceAccessLevel.write
    )
    a.guild.status = CommunityStatus.read_only.value
    session.add(a.guild)
    await session.commit()
    project_id = a.project.id

    s, _ = await _routed(role_session, guest.id, a.guild.id)

    assert (await s.exec(text("SELECT current_user"))).scalar().endswith("_guest_ro")
    assert await _ids(s, "SELECT id FROM projects") == {project_id}
    with pytest.raises(DBAPIError, match="permission denied"):
        await s.exec(text("UPDATE projects SET name = 'Renamed'"))


async def test_a_guest_row_under_any_other_role_is_no_membership(
    session, acting_user, role_session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    guest = await create_guest(session, a.guild)
    await create_initiative_member(session, a.initiative, guest)
    s, context = await _routed(role_session, guest.id, a.guild.id)

    await set_rls_context(
        s,
        Member(
            guild_id=context.guild_id,
            user_id=context.user_id,
            standing=replace(context, guild_role=CommunityRole.member.value),
        ),
    )
    standing = await compute_guild_standing(s)

    assert standing["guest"] == "false"
    assert standing["member_initiatives"] == ""


async def test_a_guests_standing_reads_their_own_custom_role_and_holds_nothing(
    session, acting_user, role_session
):
    a = await acting_user(guild_role=CommunityRole.admin)
    guest = await create_guest(session, a.guild)
    await route_session_to_guild(session, a.guild.id)
    role = CustomRole(name="Visitors", base_rung="member", surfaces=["invites"])
    session.add(role)
    await session.flush()
    session.add(CustomRoleMember(user_id=guest.id, role_id=role.id))
    await session.commit()

    _s, context = await _routed(role_session, guest.id, a.guild.id)
    assert context.held_surfaces == ()
