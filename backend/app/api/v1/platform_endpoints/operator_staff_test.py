"""What each rung of staff is offered on an account, and the account actions
added for them: signing an account out everywhere, clearing how it appears,
and the cases it has."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel import select

from app.models.platform.guild import CommunityRole, GuildMembership
from app.models.platform.user import User, UserRole, UserStatus
from app.testing import (
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
    make_operations_community,
)

USERS = "/api/v1/operator/users"


async def _row(client: AsyncClient, actor: User, target: User) -> dict:
    response = await client.get(
        USERS,
        params={"search": f"{target.username}#{target.discriminator:04d}"},
        headers=get_auth_headers(actor),
    )
    assert response.status_code == 200, response.text
    (row,) = [r for r in response.json()["items"] if r["id"] == target.id]
    return row


async def test_a_moderator_is_offered_moderation_alone(client, session):
    moderator = await create_user(session, role=UserRole.moderator)
    member = await create_user(
        session, custom_status={"text": "hello"}, profile_decorations={"banner": "x"}
    )
    actions = (await _row(client, moderator, member))["allowed_actions"]
    assert set(actions) == {
        "rename",
        "clear_custom_status",
        "clear_decorations",
        "suspend",
    }


async def test_support_is_offered_moderation_and_recovery(client, session):
    support = await create_user(session, role=UserRole.support)
    member = await create_user(
        session, custom_status={"text": "hello"}, profile_decorations={"banner": "x"}
    )
    actions = (await _row(client, support, member))["allowed_actions"]
    assert {
        "rename",
        "clear_custom_status",
        "clear_decorations",
        "suspend",
        "sign_out_everywhere",
    } <= set(actions)
    # A rung they do not hold.
    assert "change_role" not in actions
    assert "delete" not in actions


async def test_nothing_is_offered_on_a_higher_rung_or_on_oneself(client, session):
    moderator = await create_user(session, role=UserRole.moderator)
    operator = await create_user(session, role=UserRole.operator)
    assert (await _row(client, moderator, operator))["allowed_actions"] == []
    assert (await _row(client, moderator, moderator))["allowed_actions"] == []


async def test_a_moderator_still_acts_on_another_moderator(client, session):
    """At or below their own rung, as a suspension has always been."""
    moderator = await create_user(session, role=UserRole.moderator)
    other = await create_user(session, role=UserRole.moderator)
    assert "suspend" in (await _row(client, moderator, other))["allowed_actions"]


async def test_a_suspended_account_offers_lifting_not_suspending(client, session):
    moderator = await create_user(session, role=UserRole.moderator)
    held = await create_user(session, status=UserStatus.suspended)
    actions = (await _row(client, moderator, held))["allowed_actions"]
    assert "unsuspend" in actions
    assert "suspend" not in actions


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PATCH", "/username"),
        ("DELETE", "/avatar"),
        ("DELETE", "/sessions"),
        ("DELETE", "/profile/decorations"),
        ("DELETE", "/sign-in-lock"),
        ("DELETE", "/api-keys"),
        ("DELETE", "/age-block"),
    ],
)
async def test_staff_act_on_their_own_account_from_their_settings(
    client, session, method, path
):
    operator = await create_user(session, role=UserRole.operator)
    response = await client.request(
        method,
        f"{USERS}/{operator.id}{path}",
        headers=get_auth_headers(operator),
        json={"username": "renamed"} if method == "PATCH" else None,
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "OPERATOR_CANNOT_ACT_ON_SELF"


async def test_signing_an_account_out_everywhere(client, session, capfd):
    from app.core.audit_events import AuditEventType
    from app.testing.audit import emitted

    support = await create_user(session, role=UserRole.support)
    member = await create_user(session)

    response = await client.delete(
        f"{USERS}/{member.id}/sessions", headers=get_auth_headers(support)
    )
    assert response.status_code == 200, response.text
    (line,) = emitted(capfd, AuditEventType.USER_SESSIONS_REVOKED)
    assert line["target_user_id"] == member.id
    assert line["actor_user_id"] == support.id


async def test_an_access_token_handed_out_before_signing_out_stops_working(
    client, session
):
    support = await create_user(session, role=UserRole.support)
    member = await create_user(session)
    before = get_auth_headers(member)
    assert (await client.get("/api/v1/me", headers=before)).status_code == 200

    response = await client.delete(
        f"{USERS}/{member.id}/sessions", headers=get_auth_headers(support)
    )
    assert response.status_code == 200, response.text
    assert (await client.get("/api/v1/me", headers=before)).status_code == 401


async def test_a_moderator_cannot_sign_anybody_out(client, session):
    moderator = await create_user(session, role=UserRole.moderator)
    member = await create_user(session)
    response = await client.delete(
        f"{USERS}/{member.id}/sessions", headers=get_auth_headers(moderator)
    )
    assert response.status_code == 403, response.text


async def test_clearing_the_status_line_and_decorations(client, session):
    moderator = await create_user(session, role=UserRole.moderator)
    member = await create_user(
        session, custom_status={"text": "rude"}, profile_decorations={"banner": "x"}
    )
    member_id = member.id
    headers = get_auth_headers(moderator)

    cleared = await client.delete(
        f"{USERS}/{member_id}/profile/custom_status", headers=headers
    )
    assert cleared.status_code == 200, cleared.text
    assert "clear_custom_status" not in cleared.json()["allowed_actions"]
    cleared = await client.delete(
        f"{USERS}/{member_id}/profile/decorations", headers=headers
    )
    assert cleared.status_code == 200, cleared.text

    session.expire_all()
    refreshed = (await session.exec(select(User).where(User.id == member_id))).one()
    assert refreshed.custom_status == {}
    assert refreshed.profile_decorations == {}


async def test_clearing_the_names_an_account_goes_by_in_its_communities(
    client, session
):
    moderator = await create_user(session, role=UserRole.moderator)
    member = await create_user(session)
    member_id = member.id
    for _ in range(2):
        guild = await create_guild(session)
        membership = await create_guild_membership(
            session, user=member, guild=guild, role=CommunityRole.member
        )
        membership.display_name = "Something rude"
        session.add(membership)
        await session.commit()

    assert (
        "clear_display_names"
        in (await _row(client, moderator, member))["allowed_actions"]
    )
    cleared = await client.delete(
        f"{USERS}/{member_id}/profile/display_names",
        headers=get_auth_headers(moderator),
    )
    assert cleared.status_code == 200, cleared.text

    session.expire_all()
    names = (
        await session.exec(
            select(GuildMembership.display_name).where(
                GuildMembership.user_id == member_id
            )
        )
    ).all()
    assert names and all(name is None for name in names)


async def test_an_unknown_profile_field_is_refused(client, session):
    moderator = await create_user(session, role=UserRole.moderator)
    member = await create_user(session)
    response = await client.delete(
        f"{USERS}/{member.id}/profile/avatar_url", headers=get_auth_headers(moderator)
    )
    assert response.status_code == 422, response.text


async def test_cases_an_account_has_are_counted_and_listed(
    client, session, acting_user
):
    from app.core.intake import IntakeStream
    from app.db.request_context import SystemGuild, Unattributed
    from app.db.session import set_rls_context
    from app.models.tenant.intake import IntakeBinding
    from app.services.platform.intake import CaseFiler, CaseRefs, open_case

    staff = await acting_user(
        guild_role=CommunityRole.admin, initiative=True, project=True
    )
    await make_operations_community(session, staff.guild.id)
    await set_rls_context(session, SystemGuild(staff.guild.id))
    for stream in (IntakeStream.support, IntakeStream.moderation):
        session.add(IntakeBinding(stream=stream, project_id=staff.project.id))
    await session.commit()
    await set_rls_context(session, Unattributed())

    member = await create_user(session)
    filed = await open_case(
        IntakeStream.support,
        title="Help",
        filer=CaseFiler(user_id=member.id, subject="Help", words="Help."),
    )
    about = await open_case(
        IntakeStream.moderation,
        title="About them",
        refs=CaseRefs(subject_user=member.id),
    )
    assert filed is not None and about is not None

    support = await create_user(session, role=UserRole.support)
    assert (await _row(client, support, member))["open_case_count"] == 2
    listed = await client.get(
        f"{USERS}/{member.id}/cases", headers=get_auth_headers(support)
    )
    assert listed.status_code == 200, listed.text
    by_task = {case["task_id"]: case for case in listed.json()}
    assert by_task[filed.task_id]["filed"] is True
    assert by_task[about.task_id]["filed"] is False
    assert by_task[about.task_id]["community_id"] == staff.guild.id
    assert by_task[about.task_id]["project_id"] == staff.project.id
    assert set(by_task[filed.task_id]) == {
        "task_id",
        "stream",
        "community_id",
        "initiative_id",
        "project_id",
        "filed",
    }
