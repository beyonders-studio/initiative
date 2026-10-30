"""Appealing a suspension: the one ticket a suspended account may file, which
it follows and answers from its time-out screen."""

from __future__ import annotations

import json

import pytest
from sqlmodel import select

from app.core.intake import IntakeStream
from app.core.messages import AppealMessages, AuthMessages, TicketMessages
from app.db import filer_access
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.models.platform.app_setting import AppSetting
from app.models.platform.guild import CommunityRole
from app.models.platform.user import UserRole
from app.models.tenant.comment import Comment, CommentAudience
from app.models.tenant.intake import IntakeBinding, IntakeCase
from app.models.tenant.task import Task, TaskStatus, TaskStatusCategory
from app.services.platform.intake import CaseFiler, open_case
from app.services.tenant import task_statuses as task_statuses_service
from app.testing import create_user, get_auth_headers

TICKETS = "/api/v1/me/tickets"


@pytest.fixture
async def appeals_desk(session, acting_user):
    """An operations community taking moderation cases and help requests,
    with its filer role provisioned."""
    staff = await acting_user(
        guild_role=CommunityRole.admin, initiative=True, project=True
    )
    guild_id = staff.guild.id
    await set_rls_context(session, Unattributed())
    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    if row is None:
        row = AppSetting(id=1)
    row.operations_guild_id = guild_id
    session.add(row)
    await session.commit()

    await set_rls_context(session, SystemGuild(guild_id))
    await task_statuses_service.ensure_default_statuses(
        session, staff.project.id, locale="en"
    )
    for stream in (IntakeStream.moderation, IntakeStream.support):
        session.add(IntakeBinding(stream=stream, project_id=staff.project.id))
    await session.commit()
    await set_rls_context(session, Unattributed())
    await filer_access.provision_filer_access(guild_id)

    yield {"staff": staff, "guild_id": guild_id, "project_id": staff.project.id}
    await session.rollback()
    await filer_access.deprovision_filer_access(guild_id)


async def _suspend(client, session, user, reason="Spam in three communities"):
    moderator = await create_user(session, role=UserRole.moderator)
    response = await client.post(
        f"/api/v1/operator/users/{user.id}/suspension",
        headers=get_auth_headers(moderator),
        json={"suspended": True, "reason": reason},
    )
    assert response.status_code == 200, response.text


async def _appeal(client, headers, body="It was my sister.", files=None):
    payload = {"stream": "moderation", "type": "appeal", "body": body}
    return await client.post(
        TICKETS,
        data={"payload": json.dumps(payload)},
        files=files,
        headers=headers,
    )


async def test_a_suspended_account_appeals_and_follows_it(
    client, session, appeals_desk
):
    """Filed from the time-out screen, connected to the account, and read
    back there as a conversation it may answer."""
    account = await create_user(session)
    await _suspend(client, session, account)
    headers = get_auth_headers(account)

    screen = (await client.get("/api/v1/me/time-out", headers=headers)).json()
    assert screen["can_appeal"] is True
    assert screen["appeal_task_id"] is None

    filed = await _appeal(client, headers)
    assert filed.status_code == 202, filed.text

    await set_rls_context(session, SystemGuild(appeals_desk["guild_id"]))
    case = (await session.exec(select(IntakeCase))).one()
    assert case.stream == IntakeStream.moderation
    assert case.topic == "appeal"
    assert case.filer_user_id == account.id
    task = (await session.exec(select(Task).where(Task.id == case.task_id))).one()
    assert "Spam in three communities" in task.description
    await set_rls_context(session, Unattributed())

    screen = (await client.get("/api/v1/me/time-out", headers=headers)).json()
    assert screen["appeal_task_id"] == case.task_id

    detail = await client.get(f"{TICKETS}/{case.task_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["topic"] == "appeal"
    assert body["conversation"] == "open"
    assert body["can_reply"] is True
    assert body["evidence"]["max_files"] == 0

    answered = await client.post(
        f"{TICKETS}/{case.task_id}/replies",
        data={"body": "And I have changed my password."},
        headers=headers,
    )
    assert answered.status_code == 201, answered.text


async def test_one_appeal_is_open_at_a_time(client, session, appeals_desk):
    account = await create_user(session)
    await _suspend(client, session, account)
    headers = get_auth_headers(account)

    assert (await _appeal(client, headers)).status_code == 202
    again = await _appeal(client, headers, body="Please.")
    assert again.status_code == 409, again.text
    assert again.json()["detail"] == TicketMessages.TOO_MANY_OPEN

    await set_rls_context(session, SystemGuild(appeals_desk["guild_id"]))
    done = (
        await session.exec(
            select(TaskStatus).where(
                TaskStatus.project_id == appeals_desk["project_id"],
                TaskStatus.category == TaskStatusCategory.done,
            )
        )
    ).first()
    task = (await session.exec(select(Task))).one()
    task.task_status_id = done.id
    session.add(task)
    await session.commit()
    await set_rls_context(session, Unattributed())

    assert (await _appeal(client, headers, body="Please.")).status_code == 202


async def test_an_appeal_does_not_count_against_reports(
    client, session, acting_user, appeals_desk
):
    """The cap is the appeal's own: the account's reports are not appeals."""
    account = await create_user(session)
    await open_case(
        IntakeStream.moderation,
        title="An earlier report",
        filer=CaseFiler(user_id=account.id, subject=None, words="Spam."),
    )
    await _suspend(client, session, account)
    assert (await _appeal(client, get_auth_headers(account))).status_code == 202


async def test_an_account_in_good_standing_has_nothing_to_appeal(
    client, acting_user, appeals_desk
):
    member = await acting_user()
    response = await _appeal(client, member.headers)
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == AppealMessages.NOT_SUSPENDED


async def test_a_suspended_account_files_nothing_else(client, session, appeals_desk):
    account = await create_user(session)
    await _suspend(client, session, account)
    payload = {
        "stream": "support",
        "type": "account",
        "subject": "Let me back in",
        "body": "Please.",
    }
    response = await client.post(
        TICKETS,
        data={"payload": json.dumps(payload)},
        headers=get_auth_headers(account),
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == AuthMessages.ACCOUNT_SUSPENDED


async def test_a_suspended_account_answers_on_its_appeal_alone(
    client, session, appeals_desk
):
    """It reads its other tickets — they are its own — but answers none."""
    account = await create_user(session)
    outcome = await open_case(
        IntakeStream.support,
        title="Help",
        filer=CaseFiler(user_id=account.id, subject="Help", words="Help."),
    )
    assert outcome is not None
    await _suspend(client, session, account)
    headers = get_auth_headers(account)

    listed = await client.get(TICKETS, headers=headers)
    assert listed.status_code == 200, listed.text
    assert [t["task_id"] for t in listed.json()["items"]] == [outcome.task_id]

    response = await client.post(
        f"{TICKETS}/{outcome.task_id}/replies",
        data={"body": "Still here."},
        headers=headers,
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == AuthMessages.ACCOUNT_SUSPENDED


async def test_an_appeal_is_words_alone(client, session, appeals_desk):
    account = await create_user(session)
    await _suspend(client, session, account)
    response = await _appeal(
        client,
        get_auth_headers(account),
        files=[("files", ("note.txt", b"words", "text/plain"))],
    )
    assert response.status_code == 400, response.text


async def test_the_team_answers_an_appeal(client, session, appeals_desk):
    """Moderation cases are not conversations; an appeal is one, so the team
    may write to whoever filed it."""
    account = await create_user(session)
    await _suspend(client, session, account)
    assert (await _appeal(client, get_auth_headers(account))).status_code == 202

    await set_rls_context(session, SystemGuild(appeals_desk["guild_id"]))
    case = (await session.exec(select(IntakeCase))).one()
    await set_rls_context(session, Unattributed())

    staff = appeals_desk["staff"]
    response = await client.post(
        staff.g("/comments/"),
        json={
            "content": "We have lifted it.",
            "task_id": case.task_id,
            "audience": "filer",
        },
        headers=staff.headers,
    )
    assert response.status_code == 201, response.text

    detail = (
        await client.get(f"{TICKETS}/{case.task_id}", headers=get_auth_headers(account))
    ).json()
    said = [m["content"] for m in detail["messages"] if not m["mine"]]
    assert said == ["We have lifted it."]


async def test_with_nothing_bound_the_screen_offers_the_address(client, session):
    account = await create_user(session)
    await _suspend(client, session, account)
    headers = get_auth_headers(account)

    screen = (await client.get("/api/v1/me/time-out", headers=headers)).json()
    assert screen["can_appeal"] is False
    response = await _appeal(client, headers)
    assert response.status_code == 503, response.text
    assert response.json()["detail"] == AppealMessages.NOWHERE_TO_SEND


async def test_a_report_still_has_no_conversation(client, session, appeals_desk):
    """The appeal's conversation is its own; a report stays one-way."""
    account = await create_user(session)
    outcome = await open_case(
        IntakeStream.moderation,
        title="A report",
        filer=CaseFiler(user_id=account.id, subject=None, words="Spam."),
    )
    assert outcome is not None
    detail = (
        await client.get(
            f"{TICKETS}/{outcome.task_id}", headers=get_auth_headers(account)
        )
    ).json()
    assert detail["conversation"] == "none"
    assert detail["can_reply"] is False

    await set_rls_context(session, SystemGuild(appeals_desk["guild_id"]))
    said = (
        await session.exec(select(Comment).where(Comment.task_id == outcome.task_id))
    ).all()
    assert [c.audience for c in said] == [CommentAudience.filer]
    await set_rls_context(session, Unattributed())


async def test_a_suspended_account_appeals_without_the_factor_it_cannot_enrol(
    client, session, appeals_desk
):
    """Its time-out screen is reachable without the deployment's second
    factor, and a suspended account cannot enrol one, so its appeal is too.
    An active account is still asked."""
    from app.core.login_methods import SecondFactorRequirement
    from app.services.platform import rules

    account = await create_user(session)
    await _suspend(client, session, account)
    await set_rls_context(session, Unattributed())
    await rules.put(
        session, "second_factor_requirement", SecondFactorRequirement.everyone
    )
    await session.commit()
    headers = get_auth_headers(account)

    assert (await _appeal(client, headers)).status_code == 202
    listed = await client.get(TICKETS, headers=headers)
    assert listed.status_code == 200, listed.text
    task_id = listed.json()["items"][0]["task_id"]
    assert (
        await client.get(f"{TICKETS}/{task_id}", headers=headers)
    ).status_code == 200
    answered = await client.post(
        f"{TICKETS}/{task_id}/replies", data={"body": "Still me."}, headers=headers
    )
    assert answered.status_code == 201, answered.text

    active = await create_user(session)
    refused = await client.get(TICKETS, headers=get_auth_headers(active))
    assert refused.status_code == 401, refused.text
