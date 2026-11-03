"""Guests: a membership row with an end. It admits its holder until then,
takes no seat, and only on the demo deployment carries a rung above ``guest``."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func
from sqlalchemy.exc import DBAPIError
from sqlmodel import select

from app.core.messages import GuildMessages
from app.core.tools import Tool
from app.db.request_context import SystemGuild
from app.db.session import set_rls_context
from app.models.platform.guild import CommunityRole, GuildInvite, GuildMembership
from app.models.platform.notification import Notification, NotificationType
from app.models.platform.user_profile_view import MemberProfile
from app.models.tenant.guest_invite_grant import GuestInviteGrant
from app.schemas.platform.guild import CommunityInviteGrant
from app.models.tenant.initiative import InitiativeMember
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.services import cross_guild
from app.services import permissions as permissions_service
from app.services.platform import app_settings as app_settings_service
from app.services.platform import rules
from app.services.platform import contacts as contacts_service
from app.services.platform import guests
from app.services.platform import guilds as guilds_service
from app.services.platform import users as users_service
from app.services.tenant import named_people
from app.testing.routing import route_as
from app.testing import (
    create_guest,
    create_guild,
    create_guild_calendar,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_project,
    create_resource_grant,
    create_task,
    create_user,
    drain_notices,
    get_auth_headers,
)

HOUR = timedelta(hours=1)


async def _platform(session, *, guests_enabled: bool = True, demo_mode: bool = False):
    row = await app_settings_service.ensure_settings_row(session)
    row.demo_mode = demo_mode
    session.add(row)
    await rules.put(session, "guests_enabled", guests_enabled)
    await session.commit()


@pytest.mark.parametrize(
    ("guests_enabled", "demo_mode", "ends_in", "admitted"),
    [
        (True, True, HOUR, True),
        (True, True, -HOUR, False),
        # Guests are off on the platform.
        (False, True, HOUR, False),
        # A rung above guest, away from the demo deployment.
        (True, False, HOUR, False),
    ],
)
async def test_a_guest_is_admitted_until_its_end_and_as_the_platform_allows(
    client, acting_user, session, guests_enabled, demo_mode, ends_in, admitted
):
    a = await acting_user(guild_role=CommunityRole.admin)
    await _platform(session, guests_enabled=guests_enabled, demo_mode=demo_mode)
    guest = await create_guest(
        session, a.guild, role=CommunityRole.superadmin, ends_in=ends_in
    )
    guild_id, guest_id = a.guild.id, guest.id

    response = await client.get(
        f"/api/v1/c/{guild_id}/initiatives/", headers=get_auth_headers(guest)
    )
    holds_seat = (
        await session.exec(select(func.guild_superadmin(guild_id, guest_id)))
    ).one()

    assert response.status_code == (200 if admitted else 403), response.text
    assert holds_seat is admitted


async def test_guests_take_no_seat_and_are_not_on_the_roster(acting_user, session):
    a = await acting_user(guild_role=CommunityRole.admin)
    await _platform(session, demo_mode=True)
    await create_guest(session, a.guild, role=CommunityRole.admin)
    await create_guest(session, a.guild)
    guild_id = a.guild.id

    listed = (
        await session.exec(
            users_service.guild_members(select(MemberProfile.id), guild_id=guild_id)
        )
    ).all()

    assert await guilds_service.count_members(session, guild_id=guild_id) == 1
    assert await guilds_service.count_members_by_guild(
        session, guild_ids=[guild_id]
    ) == {guild_id: 1}
    assert listed == [a.user.id]


async def test_a_picker_scoped_to_content_names_a_guest_and_the_roster_does_not(
    client, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _platform(session)
    guest = await create_guest(session, a.guild)
    await create_initiative_member(session, a.initiative, guest)
    guest_id = guest.id

    async def found(**params) -> set[int]:
        response = await client.get(
            a.g("/users/search"), params=params, headers=a.headers
        )
        assert response.status_code == 200, response.text
        return {row["id"] for row in response.json()["items"]}

    assert guest_id in await found(initiative_id=a.initiative.id)
    assert guest_id in await found(user_id=guest_id)
    assert guest_id not in await found()


async def test_an_ended_guest_is_swept_away(acting_user, session, monkeypatch):
    a = await acting_user(guild_role=CommunityRole.admin)
    await _platform(session)
    ended = await create_guest(session, a.guild, ends_in=-HOUR)
    staying = await create_guest(session, a.guild)
    rejoined = await create_guest(session, a.guild, ends_in=-HOUR)
    guild_id, ended_id, staying_id = a.guild.id, ended.id, staying.id
    rejoined_id = rejoined.id
    # Found ended, then back as a member before the sweep reaches the guild.
    each_guild = guests.each_guild

    async def rejoin_first(visits, **kwargs):
        membership = (
            await session.exec(
                select(GuildMembership).where(
                    GuildMembership.guild_id == guild_id,
                    GuildMembership.user_id == rejoined_id,
                )
            )
        ).one()
        membership.role, membership.guest_until = CommunityRole.member, None
        session.add(membership)
        await session.commit()
        await each_guild(visits, **kwargs)

    monkeypatch.setattr(guests, "each_guild", rejoin_first)

    await guests.end_expired_guests()

    session.expire_all()
    remaining = set(
        (
            await session.exec(
                select(GuildMembership.user_id).where(
                    GuildMembership.guild_id == guild_id
                )
            )
        ).all()
    )
    assert ended_id not in remaining
    assert {staying_id, rejoined_id} <= remaining


async def test_a_guest_rung_is_not_changed_as_a_member_role(
    client, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.superadmin)
    await _platform(session)
    guest = await create_guest(session, a.guild)

    response = await client.patch(
        f"/api/v1/communities/{a.guild.id}/members/{guest.id}",
        json={"role": "member"},
        headers=a.headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == GuildMessages.COMMUNITY_ROLE_NOT_ASSIGNABLE


async def test_boot_records_whether_this_is_the_demo(session):
    for demo_mode in (True, False):
        await app_settings_service.record_running_version(
            session, version="9.9.9", demo_mode=demo_mode
        )
        await session.commit()
        row = await app_settings_service.ensure_settings_row(session)
        assert row.demo_mode is demo_mode


async def test_a_guest_opens_a_shared_task_and_finds_it_across_communities(
    client, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await _platform(session)
    task = await create_task(session, a.project)
    guest = await create_guest(session, a.guild)
    await create_resource_grant(session, a.project, user=guest)
    headers, project_id = get_auth_headers(guest), a.project.id

    opened = await client.get(a.g(f"/tasks/{task.id}"), headers=headers)
    case = await client.get(a.g(f"/tasks/{task.id}/case"), headers=headers)
    mine = await client.get("/api/v1/me/projects", headers=headers)

    assert opened.status_code == 200, opened.text
    assert case.status_code == 404, case.text
    assert [p["id"] for p in mine.json()["items"]] == [project_id]


async def test_a_guest_holds_no_community_wide_reach_and_is_marked_on_a_roster(
    client, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _platform(session)
    guest = await create_guest(session, a.guild)
    await create_initiative_member(session, a.initiative, guest)
    guest_id = guest.id

    async def community_wide(headers) -> bool:
        response = await client.get("/api/v1/communities/", headers=headers)
        return response.json()[0]["can"]["community_wide"]

    roster = await client.get(
        a.g(f"/initiatives/{a.initiative.id}/members"), headers=a.headers
    )

    assert await community_wide(a.headers) is True
    assert await community_wide(get_auth_headers(guest)) is False
    marked = {m["user"]["id"]: m["guest_until"] for m in roster.json()["items"]}
    assert marked[guest_id] is not None and marked[a.user.id] is None


async def test_a_guest_given_items_opens_their_initiative_but_not_its_roster(
    client, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await _platform(session)
    guest = await create_guest(session, a.guild)
    await create_resource_grant(session, a.project, user=guest)
    headers, initiative_id = get_auth_headers(guest), a.initiative.id

    listed = await client.get(a.g("/initiatives/"), headers=headers)
    opened = await client.get(a.g(f"/initiatives/{initiative_id}"), headers=headers)
    roster = await client.get(
        a.g(f"/initiatives/{initiative_id}/members"), headers=headers
    )

    assert [i["id"] for i in listed.json()] == [initiative_id]
    assert opened.status_code == 200, opened.text
    assert opened.json()["can"]["roster"] is False
    assert opened.json()["can"]["create"] == []
    assert roster.status_code == 403


async def test_a_guests_community_is_left_out_where_members_are_offered_more(
    client, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin)
    elsewhere = await acting_user(guild_role=CommunityRole.admin)
    await _platform(session)
    guest = await create_guest(session, a.guild)
    await create_guild_membership(session, user=guest, guild=elsewhere.guild)
    guild_id, elsewhere_id, guest_id = a.guild.id, elsewhere.guild.id, guest.id

    shared = await cross_guild.member_guild_ids(session, guest_id)
    offered = await cross_guild.member_guild_ids(session, guest_id, guests=False)
    contacts = await contacts_service.ordered_member_guilds(session, user_id=guest_id)

    assert shared == sorted([guild_id, elsewhere_id])
    assert offered == [elsewhere_id]
    assert [row[0] for row in contacts] == [elsewhere_id]


@pytest.mark.parametrize(
    ("max_guests", "ended", "admitted"),
    [
        (None, False, True),
        (2, False, True),
        (1, False, False),
        # A guest whose time ran out leaves room before the sweep removes them.
        (1, True, True),
        # The community takes no new guests.
        (0, False, False),
    ],
)
async def test_a_new_guest_waits_on_the_guest_cap_and_not_on_a_seat(
    session, max_guests, ended, admitted
):
    guild = await create_guild(session, max_users=1, max_guests=max_guests)
    await create_guild_membership(session, user=await create_user(session), guild=guild)
    await create_guest(session, guild, ends_in=-HOUR if ended else HOUR)
    newcomer = await create_user(session)
    guild_id, newcomer_id = guild.id, newcomer.id

    join = guilds_service.ensure_membership(
        session,
        guild_id=guild_id,
        user_id=newcomer_id,
        role=CommunityRole.guest,
        guest_until=datetime.now(timezone.utc) + HOUR,
    )

    if admitted:
        membership = await join
        assert membership.guest_until is not None
        assert await guilds_service.count_members(session, guild_id=guild_id) == 1
    else:
        with pytest.raises(guilds_service.GuildCapacityError) as refused:
            await join
        assert refused.value.code == GuildMessages.COMMUNITY_GUEST_LIMIT_REACHED


async def _heard(user_id: int) -> set[str]:
    from app.db.session import SystemSessionLocal

    await drain_notices()
    async with SystemSessionLocal() as system_session:
        rows = await system_session.exec(
            select(Notification.type).where(Notification.user_id == user_id)
        )
        return {str(kind) for kind in rows}


async def test_a_guest_given_an_item_hears_of_it_and_is_heard_there(
    client, acting_user, session
):
    await _platform(session)
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_resource_grant(session, a.project, all_initiative_members=True)
    guest = await create_guest(session, a.guild)
    await create_resource_grant(session, a.project, user=guest)
    project_id, guest_id, member_id = a.project.id, guest.id, member.user.id
    username = member.user.username

    assigned = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={"project_id": project_id, "title": "Review", "assignee_ids": [guest_id]},
    )
    assert assigned.status_code == 201, assigned.text
    posted = await client.post(
        a.g("/comments/"),
        headers=get_auth_headers(guest),
        json={
            "task_id": assigned.json()["id"],
            "content": f"Done @[{username}]({member_id})",
        },
    )
    assert posted.status_code == 201, posted.text

    assert NotificationType.task_assignment.value in await _heard(guest_id)
    assert NotificationType.mention.value in await _heard(member_id)


@pytest.mark.parametrize(
    ("guests_enabled", "ends_in", "projects_on", "heard"),
    [
        (True, HOUR, True, True),
        # Guests are off on the platform.
        (False, HOUR, True, False),
        # The guest's time ran out, and the sweep has not been by.
        (True, -HOUR, True, False),
        # The initiative has projects switched off.
        (True, HOUR, False, False),
    ],
)
async def test_a_guest_hears_of_an_item_only_while_it_reaches_it(
    acting_user, session, guests_enabled, ends_in, projects_on, heard
):
    await _platform(session, guests_enabled=guests_enabled)
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    calendar = await create_guild_calendar(session, a.guild, a.user)
    guest = await create_guest(session, a.guild, ends_in=ends_in)
    await create_resource_grant(session, a.project, user=guest)
    a.initiative.projects_enabled = projects_on
    session.add(a.initiative)
    await session.commit()
    project = named_people.Governing.of(Tool.project, a.project)
    everyone = named_people.Governing.of(Tool.calendar, calendar)
    guild_id, guest_id, member_id = a.guild.id, guest.id, member.user.id

    await set_rls_context(session, SystemGuild(guild_id))
    told = await permissions_service.audience(session, Tool.project, [a.project])
    told_all = await permissions_service.audience(session, Tool.calendar, [calendar])

    reaches = {guest_id} if heard else set()
    assert told.get(project.resource_id, set()) & {guest_id} == reaches
    assert await named_people.readers(session, project, [guest_id]) == reaches
    # A share with the whole community is its members', not its guests'.
    assert told_all[everyone.resource_id] & {guest_id, member_id} == {member_id}
    assert await named_people.readers(session, everyone, [guest_id, member_id]) == {
        member_id
    }


def _days_from_now(until: datetime) -> float:
    return (until - datetime.now(timezone.utc)) / timedelta(days=1)


async def test_a_guest_invite_makes_a_guest_for_the_shortest_limit(
    client, acting_user, session
):
    owner = await acting_user()
    seat = await acting_user(guild_role=CommunityRole.superadmin)
    joiner = await acting_user()
    guild_id = seat.guild.id

    platform = await client.put(
        "/api/v1/settings/community",
        json={
            "community_directory_enabled": False,
            "guests_enabled": True,
            "max_guest_days": 20,
        },
        headers=owner.headers,
    )
    assert platform.json()["max_guest_days"] == 20, platform.text
    limited = await client.patch(
        f"/api/v1/communities/{guild_id}/auth-settings",
        json={"guest_max_days": 10},
        headers=seat.headers,
    )
    assert limited.json()["guest_max_days"] == 10, limited.text
    assert limited.json()["guest_max_days_by_platform"] == 20
    made = await client.post(
        f"/api/v1/communities/{guild_id}/invites",
        json={"guest_days": 30},
        headers=seat.headers,
    )
    assert made.json()["guest_days"] == 10, made.text
    status = await client.get(f"/api/v1/communities/invite/{made.json()['code']}")
    assert status.json()["guest_days"] == 10

    joined = await client.post(
        "/api/v1/communities/invite/accept",
        json={"code": made.json()["code"]},
        headers=joiner.headers,
    )

    assert joined.status_code == 200, joined.text
    membership = await guilds_service.get_membership(
        session, guild_id=guild_id, user_id=joiner.user.id
    )
    assert membership is not None and membership.role == CommunityRole.guest
    assert membership.guest_until is not None
    assert 9.9 < _days_from_now(membership.guest_until) <= 10


async def test_no_guest_invite_while_guests_are_off(client, acting_user, session):
    a = await acting_user(guild_role=CommunityRole.admin)
    await _platform(session, guests_enabled=False)

    response = await client.post(
        f"/api/v1/communities/{a.guild.id}/invites",
        json={"guest_days": 7},
        headers=a.headers,
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == GuildMessages.COMMUNITY_GUESTS_DISABLED


async def test_an_admin_lists_extends_and_makes_a_guest_a_member(
    client, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    await _platform(session)
    guest = await create_guest(session, a.guild)
    guild_id, guest_id = a.guild.id, guest.id
    guests_url = f"/api/v1/communities/{guild_id}/guests/{guest_id}"

    listed = await client.get(
        a.g("/users/"), params={"guests": True}, headers=a.headers
    )
    refused = await client.get(
        a.g("/users/"), params={"guests": True}, headers=member.headers
    )
    extended = await client.patch(guests_url, json={"days": 5}, headers=a.headers)
    extended_until = (
        await guilds_service.get_membership(
            session, guild_id=guild_id, user_id=guest_id
        )
    ).guest_until
    made_member = await client.post(f"{guests_url}/member", headers=a.headers)
    session.expire_all()
    after_joining = await guilds_service.get_membership(
        session, guild_id=guild_id, user_id=guest_id
    )

    assert [row["id"] for row in listed.json()["items"]] == [guest_id], listed.text
    assert listed.json()["items"][0]["guest_until"] is not None
    assert refused.status_code == 403
    assert extended.status_code == 204, extended.text
    assert extended_until is not None and 4.9 < _days_from_now(extended_until) <= 5
    assert made_member.status_code == 204, made_member.text
    assert after_joining is not None
    assert after_joining.guest_until is None
    assert after_joining.role == CommunityRole.member
    again = await client.patch(guests_url, json={"days": 5}, headers=a.headers)
    assert again.status_code == 404
    assert again.json()["detail"] == GuildMessages.NOT_A_GUEST


@pytest.mark.parametrize(("max_guests", "brought_back"), [(None, True), (1, False)])
async def test_bringing_back_an_ended_guest_takes_a_place(
    session, max_guests, brought_back
):
    guild = await create_guild(session, max_guests=max_guests)
    await _platform(session)
    ended = await create_guest(session, guild, ends_in=-HOUR)
    await create_guest(session, guild)
    admin_id, guild_id, ended_id = guild.created_by, guild.id, ended.id

    extend = guilds_service.extend_guest(
        session, guild_id=guild_id, user_id=ended_id, days=3, actor_user_id=admin_id
    )

    if brought_back:
        assert (await extend).guest_until > datetime.now(timezone.utc)
    else:
        with pytest.raises(guilds_service.GuildCapacityError):
            await extend


async def test_an_ended_guest_spends_no_invite_before_the_sweep(
    client, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin)
    await _platform(session)
    ended = await create_guest(session, a.guild, ends_in=-HOUR)
    invite, code = await guilds_service.create_guild_invite(
        session, guild_id=a.guild.id, created_by=a.user.id, guest_days=7
    )
    await session.commit()
    invite_id = invite.id

    response = await client.post(
        "/api/v1/communities/invite/accept",
        json={"code": code},
        headers=get_auth_headers(ended),
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == GuildMessages.GUEST_TIME_ENDED
    session.expire_all()
    assert (await session.get(GuildInvite, invite_id)).uses == 0


async def test_admins_see_their_guests_while_guests_are_off(
    client, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin)
    await _platform(session, guests_enabled=False)
    guest = await create_guest(session, a.guild)
    guest_id = guest.id

    listed = await client.get(
        a.g("/users/"), params={"guests": True}, headers=a.headers
    )

    assert [row["id"] for row in listed.json()["items"]] == [guest_id], listed.text


async def test_a_guest_invite_gives_what_it_names(client, acting_user, session):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    joined_whole = await create_initiative(session, a.guild, a.user)
    joiner = await acting_user()
    await _platform(session)
    ids = (a.guild.id, a.initiative.id, a.project.id, joined_whole.id)
    guild_id, initiative_id, project_id, whole_id = ids

    made = await client.post(
        f"/api/v1/communities/{guild_id}/invites",
        json={
            "guest_days": 7,
            "grants": [
                {"initiative_id": whole_id},
                {
                    "initiative_id": initiative_id,
                    "resource_type": "project",
                    "resource_id": project_id,
                    "level": "write",
                },
            ],
        },
        headers=a.headers,
    )
    assert made.status_code == 201, made.text
    listed = await client.get(
        f"/api/v1/communities/{guild_id}/invites", headers=a.headers
    )
    assert len(listed.json()[0]["grants"]) == 2

    joined = await client.post(
        "/api/v1/communities/invite/accept",
        json={"code": made.json()["code"]},
        headers=joiner.headers,
    )
    opened = await client.get(
        f"/api/v1/c/{guild_id}/projects/{project_id}", headers=joiner.headers
    )

    assert joined.status_code == 200, joined.text
    assert opened.status_code == 200, opened.text
    await set_rls_context(session, SystemGuild(guild_id))
    assert (
        await session.exec(
            select(InitiativeMember.initiative_id).where(
                InitiativeMember.user_id == joiner.user.id
            )
        )
    ).all() == [whole_id]
    assert (
        await session.exec(
            select(ResourceGrant.level).where(ResourceGrant.user_id == joiner.user.id)
        )
    ).all() == [ResourceAccessLevel.write]


async def test_a_guest_invite_names_only_what_the_community_holds_there(
    client, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    elsewhere = await create_initiative(session, a.guild, a.user)
    await _platform(session)

    made = await client.post(
        f"/api/v1/communities/{a.guild.id}/invites",
        json={
            "guest_days": 7,
            "grants": [
                {
                    "initiative_id": elsewhere.id,
                    "resource_type": "project",
                    "resource_id": a.project.id,
                    "level": "read",
                }
            ],
        },
        headers=a.headers,
    )

    assert made.status_code == 404, made.text
    assert made.json()["detail"] == GuildMessages.GUEST_GRANT_NOT_FOUND


async def test_what_an_invite_gives_is_its_administrations_alone(
    acting_user, session, role_session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member, guild=a.guild, initiative=a.initiative
    )
    await _platform(session)
    invite, _ = await guilds_service.create_guild_invite(
        session, guild_id=a.guild.id, created_by=a.user.id, guest_days=7
    )
    await set_rls_context(session, SystemGuild(a.guild.id))
    session.add(GuestInviteGrant(invite_id=invite.id, initiative_id=a.initiative.id))
    await session.commit()
    guild_id, invite_id, initiative_id = a.guild.id, invite.id, a.initiative.id

    as_admin = await role_session("app_user")
    await route_as(as_admin, user_id=a.user.id, guild_id=guild_id)
    as_member = await role_session("app_user")
    await route_as(as_member, user_id=member.user.id, guild_id=guild_id)

    assert len((await as_admin.exec(select(GuestInviteGrant))).all()) == 1
    assert (await as_member.exec(select(GuestInviteGrant))).all() == []
    as_member.add(GuestInviteGrant(invite_id=invite_id, initiative_id=initiative_id))
    with pytest.raises(DBAPIError):
        await as_member.flush()


async def test_an_item_archived_since_is_skipped_and_the_rest_given(
    client, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    joiner = await acting_user()
    await _platform(session)
    guild_id, initiative_id, project_id = a.guild.id, a.initiative.id, a.project.id
    _, code = await guilds_service.create_guild_invite(
        session,
        guild_id=guild_id,
        created_by=a.user.id,
        guest_days=7,
        grants=[
            CommunityInviteGrant(initiative_id=initiative_id),
            CommunityInviteGrant(
                initiative_id=initiative_id,
                resource_type=Tool.project,
                resource_id=project_id,
                level="read",
            ),
        ],
    )
    a.project.archived_at = datetime.now(timezone.utc)
    session.add(a.project)
    await session.commit()

    joined = await client.post(
        "/api/v1/communities/invite/accept",
        json={"code": code},
        headers=joiner.headers,
    )

    assert joined.status_code == 200, joined.text
    await set_rls_context(session, SystemGuild(guild_id))
    assert (
        await session.exec(
            select(InitiativeMember.initiative_id).where(
                InitiativeMember.user_id == joiner.user.id
            )
        )
    ).all() == [initiative_id]
    assert (
        await session.exec(
            select(ResourceGrant.id).where(ResourceGrant.user_id == joiner.user.id)
        )
    ).all() == []


async def test_an_invite_naming_an_archived_initiative_is_withdrawn(
    client, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _platform(session)
    invite, _ = await guilds_service.create_guild_invite(
        session,
        guild_id=a.guild.id,
        created_by=a.user.id,
        guest_days=7,
        grants=[CommunityInviteGrant(initiative_id=a.initiative.id)],
    )
    a.initiative.archived_at = datetime.now(timezone.utc)
    session.add(a.initiative)
    await session.commit()
    guild_id, invite_id = a.guild.id, invite.id

    withdrawn = await client.delete(
        f"/api/v1/communities/{guild_id}/invites/{invite_id}", headers=a.headers
    )

    assert withdrawn.status_code == 204, withdrawn.text
    session.expire_all()
    assert await session.get(GuildInvite, invite_id) is None


@pytest.mark.parametrize("way", ["leaves", "removed", "expires"])
async def test_a_guest_given_only_an_item_keeps_no_grant_on_leaving(
    client, acting_user, session, way
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await _platform(session)
    guest = await create_guest(
        session, a.guild, ends_in=-HOUR if way == "expires" else HOUR
    )
    await create_resource_grant(session, a.project, user=guest)
    # An archived item's share goes as well.
    archived = await create_project(session, a.initiative, a.user)
    await create_resource_grant(session, archived, user=guest)
    archived.archived_at = datetime.now(timezone.utc)
    session.add(archived)
    await session.commit()
    guild_id, guest_id = a.guild.id, guest.id

    if way == "leaves":
        response = await client.delete(
            f"/api/v1/communities/{guild_id}/leave", headers=get_auth_headers(guest)
        )
        assert response.status_code == 204, response.text
    elif way == "removed":
        response = await client.delete(a.g(f"/users/{guest_id}"), headers=a.headers)
        assert response.status_code == 204, response.text
    else:
        await guests.end_expired_guests()

    session.expire_all()
    await set_rls_context(session, SystemGuild(guild_id))
    assert (
        await session.exec(
            select(ResourceGrant.id).where(ResourceGrant.user_id == guest_id)
        )
    ).all() == []


async def test_a_guest_can_leave(client, acting_user, session):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await _platform(session)
    guest = await create_guest(session, a.guild)
    await create_resource_grant(session, a.project, user=guest)
    guild_id, guest_id = a.guild.id, guest.id

    response = await client.delete(
        f"/api/v1/communities/{guild_id}/leave", headers=get_auth_headers(guest)
    )

    assert response.status_code == 204, response.text
    assert (
        await guilds_service.get_membership(
            session, guild_id=guild_id, user_id=guest_id
        )
        is None
    )
