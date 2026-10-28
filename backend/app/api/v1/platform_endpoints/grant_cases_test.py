"""An access grant and the operations case it serves: naming the case,
what the case is told, what a grant did, and the case's list of grants."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.intake import IntakeStream
from app.core.messages import AccessGrantMessages
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.models.platform.access_grant import AccessGrant
from app.models.platform.access_grant_activity import AccessGrantActivity
from app.models.platform.app_setting import AppSetting
from app.models.platform.guild import CommunityRole
from app.models.platform.user import User
from app.models.tenant.comment import Comment
from app.models.tenant.intake import IntakeBinding
from app.models.tenant.task import Task, TaskStatus, TaskStatusCategory
from app.services.platform import grant_cases
from app.services.platform.intake import CaseRefs, open_case
from app.services.tenant import task_statuses as task_statuses_service
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.testing import (
    Actor,
    create_guild,
    create_resource_grant,
    create_user,
    get_auth_headers,
)

GRANTS = "/api/v1/access-grants/"


async def _statuses(session: AsyncSession, project_id: int) -> dict:
    rows = (
        await session.exec(
            select(TaskStatus).where(TaskStatus.project_id == project_id)
        )
    ).all()
    by_category: dict = {}
    for row in sorted(rows, key=lambda r: r.position):
        by_category.setdefault(TaskStatusCategory(row.category), int(row.id))
    return by_category


@pytest.fixture
async def desk(session: AsyncSession, acting_user):
    """An operations community taking support and feedback cases, with a
    support agent who works them."""
    staff = await acting_user(
        guild_role=CommunityRole.admin, initiative=True, project=True
    )
    guild_id = staff.guild.id
    await set_rls_context(session, Unattributed())
    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    row = row or AppSetting(id=1)
    row.operations_guild_id = guild_id
    session.add(row)
    await session.commit()

    await set_rls_context(session, SystemGuild(guild_id))
    await task_statuses_service.ensure_default_statuses(
        session, staff.project.id, locale="en"
    )
    statuses = await _statuses(session, staff.project.id)
    for stream in (IntakeStream.support, IntakeStream.feedback):
        session.add(
            IntakeBinding(
                stream=stream,
                project_id=staff.project.id,
                active_status_id=statuses[TaskStatusCategory.in_progress],
            )
        )
    await session.commit()
    await set_rls_context(session, Unattributed())

    agent = await acting_user(
        "support",
        guild_role=CommunityRole.member,
        guild=staff.guild,
        initiative=staff.initiative,
        initiative_role="member",
    )
    # The project the cases land in is shared with the staff who work them.
    await create_resource_grant(
        session, staff.project, level=ResourceAccessLevel.write, user=agent.user
    )
    await set_rls_context(session, Unattributed())
    return {"staff": staff, "agent": agent, "statuses": statuses, "guild_id": guild_id}


async def _case(stream=IntakeStream.support, subject_guild=None) -> int:
    outcome = await open_case(
        stream,
        title="Cannot open a project",
        refs=CaseRefs(subject_guild=subject_guild) if subject_guild else None,
    )
    assert outcome is not None
    return outcome.task_id


async def _request(client: AsyncClient, agent: Actor, guild_id: int, **body):
    return await client.post(
        GRANTS,
        json={"community_id": guild_id, "reason": "the case", **body},
        headers=agent.headers,
    )


async def _notes(session: AsyncSession, desk: dict, task_id: int) -> list[Comment]:
    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    notes = (
        await session.exec(
            select(Comment)
            .where(Comment.task_id == task_id)
            .where(Comment.system_kind.is_not(None))
            .order_by(Comment.id)
        )
    ).all()
    await set_rls_context(session, Unattributed())
    return list(notes)


# ── Naming the case ──────────────────────────────────────────────────────────


async def test_a_request_must_name_a_case_where_cases_are_taken(
    client: AsyncClient, session: AsyncSession, desk
):
    target = await create_guild(session)
    response = await _request(client, desk["agent"], target.id)
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == AccessGrantMessages.CASE_REQUIRED


async def test_a_request_for_a_case_tells_the_case_and_names_its_community(
    client: AsyncClient, session: AsyncSession, desk, capfd
):
    from app.core.audit_events import AuditEventType
    from app.testing.audit import emitted

    target = await create_guild(session)
    task_id = await _case()

    emitted(capfd)
    response = await _request(client, desk["agent"], target.id, case_task_id=task_id)
    assert response.status_code == 201, response.text
    assert response.json()["case_task_id"] == task_id
    (linked,) = emitted(capfd, AuditEventType.ACCESS_GRANT_CASE_LINKED)
    assert linked["target"] == {"type": "access_grant", "id": response.json()["id"]}
    assert linked["detail"]["case_task_id"] == task_id

    (requested,) = await _notes(session, desk, task_id)
    assert requested.system_kind == "grant_requested"
    assert desk["agent"].user.username in requested.content
    assert f"#{target.id}" in requested.content

    # The case is now about that community: a grant for another is refused.
    other = await create_guild(session)
    refused = await _request(client, desk["agent"], other.id, case_task_id=task_id)
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == AccessGrantMessages.CASE_OTHER_COMMUNITY


async def test_a_case_about_another_community_is_refused(
    client: AsyncClient, session: AsyncSession, desk
):
    target = await create_guild(session)
    other = await create_guild(session)
    task_id = await _case(subject_guild=other.id)
    response = await _request(client, desk["agent"], target.id, case_task_id=task_id)
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == AccessGrantMessages.CASE_OTHER_COMMUNITY


async def test_feedback_is_no_reason_for_access(
    client: AsyncClient, session: AsyncSession, desk
):
    target = await create_guild(session)
    task_id = await _case(IntakeStream.feedback)
    response = await _request(client, desk["agent"], target.id, case_task_id=task_id)
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == AccessGrantMessages.CASE_NOT_LINKABLE


async def test_a_closed_case_is_no_reason_for_access(
    client: AsyncClient, session: AsyncSession, desk
):
    target = await create_guild(session)
    task_id = await _case()
    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    task = (await session.exec(select(Task).where(Task.id == task_id))).one()
    task.task_status_id = desk["statuses"][TaskStatusCategory.done]
    session.add(task)
    await session.commit()
    await set_rls_context(session, Unattributed())

    response = await _request(client, desk["agent"], target.id, case_task_id=task_id)
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == AccessGrantMessages.CASE_CLOSED


async def test_a_case_the_requester_cannot_read_answers_as_none(
    client: AsyncClient, session: AsyncSession, desk, acting_user
):
    target = await create_guild(session)
    task_id = await _case()
    outsider = await acting_user("support")
    response = await _request(client, outsider, target.id, case_task_id=task_id)
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == AccessGrantMessages.CASE_NOT_FOUND


async def test_the_picker_lists_open_cases_the_reader_can_read(
    client: AsyncClient, session: AsyncSession, desk
):
    support_case = await _case()
    feedback_case = await _case(IntakeStream.feedback)
    response = await client.get(f"{GRANTS}cases", headers=desk["agent"].headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["required"] is True
    listed = {case["task_id"]: case for case in body["items"]}
    assert listed[support_case]["community_notice"] == "always"
    assert feedback_case not in listed


async def test_a_member_has_no_picker(client: AsyncClient, session: AsyncSession, desk):
    member = await create_user(session)
    response = await client.get(f"{GRANTS}cases", headers=get_auth_headers(member))
    assert response.status_code == 403, response.text


# ── Deciding ─────────────────────────────────────────────────────────────────


async def test_approving_tells_the_case_and_puts_it_to_work(
    client: AsyncClient, session: AsyncSession, desk, acting_user
):
    target = await create_guild(session)
    task_id = await _case()
    requested = await _request(client, desk["agent"], target.id, case_task_id=task_id)
    grant_id = requested.json()["id"]
    owner = await acting_user("owner")

    approved = await client.post(
        f"{GRANTS}{grant_id}/approve", json={}, headers=owner.headers
    )
    assert approved.status_code == 200, approved.text

    kinds = [note.system_kind for note in await _notes(session, desk, task_id)]
    assert kinds == ["grant_requested", "grant_decided"]
    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    task = (await session.exec(select(Task).where(Task.id == task_id))).one()
    assert task.task_status_id == desk["statuses"][TaskStatusCategory.in_progress]
    await set_rls_context(session, Unattributed())


async def test_the_case_lists_its_grants(
    client: AsyncClient, session: AsyncSession, desk
):
    target = await create_guild(session)
    task_id = await _case()
    await _request(client, desk["agent"], target.id, case_task_id=task_id)
    staff = desk["staff"]
    response = await client.get(
        staff.g(f"/tasks/{task_id}/case"), headers=staff.headers
    )
    assert response.status_code == 200, response.text
    (grant,) = response.json()["grants"]
    assert grant["community_id"] == target.id
    assert grant["user"]["id"] == desk["agent"].user.id
    assert grant["status"] == "pending"


# ── What a grant did ─────────────────────────────────────────────────────────


async def _live_grant(session: AsyncSession, *, user, guild_id: int, case: int, ago):
    now = datetime.now(timezone.utc)
    grant = AccessGrant(
        user_id=user.id,
        guild_id=guild_id,
        access_level="read",
        status="approved",
        reason="the case",
        requested_duration_minutes=240,
        requested_by_id=user.id,
        approved_by_id=user.id,
        decided_at=now - ago,
        expires_at=now + timedelta(hours=2),
        case_task_id=case,
    )
    session.add(grant)
    await session.commit()
    return grant


async def test_a_request_through_a_grant_is_recorded(
    client: AsyncClient, session: AsyncSession, desk, acting_user
):
    owner_of = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    task_id = await _case()
    grant = await _live_grant(
        session,
        user=desk["agent"].user,
        guild_id=owner_of.guild.id,
        case=task_id,
        ago=timedelta(minutes=5),
    )
    response = await client.get(
        owner_of.g(f"/initiatives/{owner_of.initiative.id}"),
        headers=desk["agent"].headers,
    )
    assert response.status_code == 200, response.text

    await set_rls_context(session, Unattributed())
    (row,) = (
        await session.exec(
            select(AccessGrantActivity).where(AccessGrantActivity.grant_id == grant.id)
        )
    ).all()
    assert row.method == "GET"
    assert row.is_write is False
    assert "{initiative_id}" in row.route


async def test_a_live_grant_reports_hourly_and_an_ended_one_in_full(
    session: AsyncSession, desk
):
    target = await create_guild(session)
    task_id = await _case()
    grant = await _live_grant(
        session,
        user=desk["agent"].user,
        guild_id=target.id,
        case=task_id,
        ago=timedelta(minutes=90),
    )
    grant_id = grant.id
    now = datetime.now(timezone.utc)
    for minutes, method, target_type in (
        (60, "GET", "task"),
        (50, "GET", "task"),
        (40, "PATCH", "task"),
    ):
        session.add(
            AccessGrantActivity(
                grant_id=grant.id,
                occurred_at=now - timedelta(minutes=minutes),
                method=method,
                route="/api/v1/c/{community_id}/tasks/{task_id}",
                status=200,
                is_write=method != "GET",
                target_type=target_type,
                target_id=12,
            )
        )
    await session.commit()

    await set_rls_context(session, Unattributed())
    assert await grant_cases.report_activity(session, now=now) == 1
    (interim,) = await _notes(session, desk, task_id)
    assert interim.system_kind == "grant_digest"
    assert "task ×2" in interim.content
    assert "PATCH /api/v1/c/{community_id}/tasks/{task_id} (task 12)" in interim.content

    # Nothing new within the hour: nothing told.
    await set_rls_context(session, Unattributed())
    assert await grant_cases.report_activity(session, now=now) == 0

    await set_rls_context(session, Unattributed())
    assert await grant_cases.report_activity(session, now=now + timedelta(hours=3)) == 1
    final = (await _notes(session, desk, task_id))[-1]
    assert "has ended" in final.content
    assert "Changed 1 times" in final.content
    await set_rls_context(session, Unattributed())
    session.expire_all()
    closed = (
        await session.exec(select(AccessGrant).where(AccessGrant.id == grant_id))
    ).one()
    assert closed.closed_out_at is not None


def test_a_digest_lists_only_so_many_changes():
    now = datetime.now(timezone.utc)
    shown = [
        AccessGrantActivity(
            grant_id=1,
            occurred_at=now,
            method="POST",
            route="/x",
            status=201,
            is_write=True,
        )
        for _ in range(grant_cases.WRITES_LISTED)
    ]
    summary = grant_cases.ActivitySummary(
        reads={"task": 3}, write_count=grant_cases.WRITES_LISTED + 5, writes=shown
    )
    text = grant_cases.digest_text(summary, heading="Heading")
    assert "Read 3 times: task ×3." in text
    assert "…and 5 more." in text


async def test_an_ended_grant_waits_for_requests_still_finishing(
    session: AsyncSession, desk
):
    """A request the grant let in may finish just after it ends, and is
    recorded then; the full account waits for it."""
    target = await create_guild(session)
    task_id = await _case()
    grant = await _live_grant(
        session,
        user=desk["agent"].user,
        guild_id=target.id,
        case=task_id,
        ago=timedelta(minutes=30),
    )
    ended_at = grant.expires_at
    await set_rls_context(session, Unattributed())
    assert (
        await grant_cases.report_activity(
            session, now=ended_at + grant_cases.ENDED_GRACE / 2
        )
        == 0
    )
    await set_rls_context(session, Unattributed())
    assert (
        await grant_cases.report_activity(
            session, now=ended_at + grant_cases.ENDED_GRACE * 2
        )
        == 1
    )


async def test_two_requests_for_one_unnamed_case_settle_one_community(
    session: AsyncSession, desk
):
    first = await create_guild(session)
    second = await create_guild(session)
    task_id = await _case()
    assert await grant_cases.claim(task_id, guild_id=first.id) == "named"
    assert await grant_cases.claim(task_id, guild_id=second.id) == "other"
    assert await grant_cases.claim(task_id, guild_id=first.id) == "held"
    # A grant that then fails to be made gives the case back unnamed.
    await grant_cases.unclaim(task_id, guild_id=first.id)
    assert await grant_cases.claim(task_id, guild_id=second.id) == "named"


async def test_the_picker_finds_a_case_by_title_or_number(
    client: AsyncClient, session: AsyncSession, desk
):
    task_id = await _case()
    for term in ("open a project", f"#{task_id}", str(task_id)):
        response = await client.get(
            f"{GRANTS}cases", params={"search": term}, headers=desk["agent"].headers
        )
        assert response.status_code == 200, response.text
        assert [c["task_id"] for c in response.json()["items"]] == [task_id]
    response = await client.get(
        f"{GRANTS}cases",
        params={"search": "nothing like it"},
        headers=desk["agent"].headers,
    )
    assert response.json()["items"] == []


async def test_a_suspension_under_a_grant_is_told_to_its_case(
    client: AsyncClient, session: AsyncSession, desk
):
    from app.models.platform.user import UserRole

    target = await create_guild(session)
    task_id = await _case()
    moderator = await create_user(session, role=UserRole.moderator)
    grant = await _live_grant(
        session, user=moderator, guild_id=target.id, case=task_id, ago=timedelta(0)
    )
    grant.access_level = "moderate"
    session.add(grant)
    await session.commit()

    response = await client.post(
        f"/api/v1/settings/communities/{target.id}/suspension",
        json={"suspended": True},
        headers=get_auth_headers(moderator),
    )
    assert response.status_code == 200, response.text
    (note,) = await _notes(session, desk, task_id)
    assert note.system_kind == "guild_act"
    assert "suspended community" in note.content


# ── Acts on an account ───────────────────────────────────────────────────────


async def test_an_account_act_for_a_case_is_told_to_it(
    client: AsyncClient, session: AsyncSession, desk, acting_user
):
    moderator = await acting_user(
        "moderator",
        guild_role=CommunityRole.member,
        guild=desk["staff"].guild,
        initiative=desk["staff"].initiative,
        initiative_role="member",
    )
    await create_resource_grant(
        session,
        desk["staff"].project,
        level=ResourceAccessLevel.write,
        user=moderator.user,
    )
    await set_rls_context(session, Unattributed())
    member = await create_user(session)
    task_id = await _case()

    response = await client.post(
        f"/api/v1/operator/users/{member.id}/suspension",
        params={"case_task_id": task_id},
        json={"suspended": True, "reason": "spam"},
        headers=moderator.headers,
    )
    assert response.status_code == 200, response.text
    (note,) = await _notes(session, desk, task_id)
    assert note.system_kind == "account_act"
    assert note.content == (
        f"{moderator.user.username}#{moderator.user.discriminator:04d} suspended "
        f"account {member.username}#{member.discriminator:04d} (#{member.id})."
    )


async def test_an_account_act_names_only_a_case_its_actor_reads(
    client: AsyncClient, session: AsyncSession, desk
):
    from app.models.platform.user import UserRole, UserStatus

    moderator = await create_user(session, role=UserRole.moderator)
    member = await create_user(session)
    task_id = await _case()

    response = await client.post(
        f"/api/v1/operator/users/{member.id}/suspension",
        params={"case_task_id": task_id},
        json={"suspended": True},
        headers=get_auth_headers(moderator),
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == AccessGrantMessages.CASE_NOT_FOUND
    # Refused before it acted.
    await session.refresh(member)
    assert member.status == UserStatus.active
    assert await _notes(session, desk, task_id) == []


async def test_an_account_act_without_a_case_tells_nothing(
    client: AsyncClient, session: AsyncSession, desk
):
    from app.models.platform.user import UserRole

    support = await create_user(session, role=UserRole.support)
    member = await create_user(session)
    task_id = await _case()
    response = await client.delete(
        f"/api/v1/operator/users/{member.id}/sessions",
        headers=get_auth_headers(support),
    )
    assert response.status_code == 200, response.text
    assert await _notes(session, desk, task_id) == []


async def test_a_request_finishing_after_close_out_is_told_on_its_own(
    session: AsyncSession, desk
):
    target = await create_guild(session)
    task_id = await _case()
    grant = await _live_grant(
        session,
        user=desk["agent"].user,
        guild_id=target.id,
        case=task_id,
        ago=timedelta(minutes=30),
    )
    grant_id = grant.id
    closed_at = grant.expires_at + grant_cases.ENDED_GRACE * 2
    await set_rls_context(session, Unattributed())
    assert await grant_cases.report_activity(session, now=closed_at) == 1

    session.add(
        AccessGrantActivity(
            grant_id=grant_id,
            occurred_at=closed_at + timedelta(minutes=1),
            method="PATCH",
            route="/api/v1/c/{community_id}/tasks/{task_id}",
            status=200,
            is_write=True,
            target_type="task",
            target_id=12,
        )
    )
    await session.commit()
    await set_rls_context(session, Unattributed())
    later = closed_at + timedelta(minutes=5)
    assert await grant_cases.report_activity(session, now=later) == 1
    final = (await _notes(session, desk, task_id))[-1]
    assert "requests it had let in finished" in final.content
    assert "(task 12)" in final.content
    # Told once.
    await set_rls_context(session, Unattributed())
    assert await grant_cases.report_activity(session, now=later) == 0


async def test_a_refused_request_leaves_its_case_unnamed(
    client: AsyncClient, session: AsyncSession, desk
):
    """A grant the server refuses settles nothing on the case it named."""
    task_id = await _case()
    response = await _request(client, desk["agent"], 999_999, case_task_id=task_id)
    assert response.status_code == 404, response.text
    other = await create_guild(session)
    assert await grant_cases.claim(task_id, guild_id=other.id) == "named"


async def test_releasing_keeps_a_name_another_grant_rests_on(
    session: AsyncSession, desk
):
    target = await create_guild(session)
    other = await create_guild(session)
    task_id = await _case()
    assert await grant_cases.claim(task_id, guild_id=target.id) == "named"
    # A second request found it named so, and its grant was made.
    await _live_grant(
        session,
        user=desk["agent"].user,
        guild_id=target.id,
        case=task_id,
        ago=timedelta(0),
    )
    # The first one's grant then failed: its release leaves the name.
    await grant_cases.unclaim(task_id, guild_id=target.id)
    assert await grant_cases.claim(task_id, guild_id=other.id) == "other"


async def test_a_summary_that_could_not_be_written_is_tried_again(
    session: AsyncSession, desk, monkeypatch
):
    target = await create_guild(session)
    task_id = await _case()
    grant = await _live_grant(
        session,
        user=desk["agent"].user,
        guild_id=target.id,
        case=task_id,
        ago=timedelta(minutes=30),
    )
    grant_id = grant.id
    ended = grant.expires_at + grant_cases.ENDED_GRACE * 2

    async def unwritable(*_args, **_kwargs) -> bool:
        return False

    with monkeypatch.context() as patched:
        patched.setattr(grant_cases, "note", unwritable)
        await set_rls_context(session, Unattributed())
        assert await grant_cases.report_activity(session, now=ended) == 0

    await set_rls_context(session, Unattributed())
    session.expire_all()
    pending = (
        await session.exec(select(AccessGrant).where(AccessGrant.id == grant_id))
    ).one()
    assert pending.closed_out_at is None
    await set_rls_context(session, Unattributed())
    assert await grant_cases.report_activity(session, now=ended) == 1


async def test_suspending_a_suspended_account_tells_its_case_nothing(
    client: AsyncClient, session: AsyncSession, desk, acting_user
):
    from app.models.platform.user import UserStatus

    moderator = await acting_user(
        "moderator",
        guild_role=CommunityRole.member,
        guild=desk["staff"].guild,
        initiative=desk["staff"].initiative,
        initiative_role="member",
    )
    await create_resource_grant(
        session,
        desk["staff"].project,
        level=ResourceAccessLevel.write,
        user=moderator.user,
    )
    await set_rls_context(session, Unattributed())
    member = await create_user(session, status=UserStatus.suspended)
    task_id = await _case()
    response = await client.post(
        f"/api/v1/operator/users/{member.id}/suspension",
        params={"case_task_id": task_id},
        json={"suspended": True},
        headers=moderator.headers,
    )
    assert response.status_code == 200, response.text
    assert await _notes(session, desk, task_id) == []


async def test_a_grant_whose_case_is_gone_is_closed_out_untold(
    session: AsyncSession, desk
):
    target = await create_guild(session)
    task_id = await _case()
    assert await grant_cases.case_exists(task_id)
    # One in the trash may be restored, so it is still there.
    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    trashed = (await session.exec(select(Task).where(Task.id == task_id))).one()
    trashed.deleted_at = datetime.now(timezone.utc)
    session.add(trashed)
    await session.commit()
    await set_rls_context(session, Unattributed())
    assert await grant_cases.case_exists(task_id)
    purged = task_id + 10_000
    assert not await grant_cases.case_exists(purged)
    grant = await _live_grant(
        session,
        user=desk["agent"].user,
        guild_id=target.id,
        case=purged,
        ago=timedelta(minutes=30),
    )
    grant_id = grant.id
    ended = grant.expires_at + grant_cases.ENDED_GRACE * 2
    await set_rls_context(session, Unattributed())
    assert await grant_cases.report_activity(session, now=ended) == 0

    await set_rls_context(session, Unattributed())
    session.expire_all()
    closed = (
        await session.exec(select(AccessGrant).where(AccessGrant.id == grant_id))
    ).one()
    assert closed.closed_out_at is not None


# ── Telling the community ────────────────────────────────────────────────────


async def _letters(session: AsyncSession, user_id: int) -> list:
    from app.models.platform.email_outbox import EmailOutboxItem

    session.expire_all()
    return list(
        (
            await session.exec(
                select(EmailOutboxItem).where(EmailOutboxItem.user_id == user_id)
            )
        ).all()
    )


@pytest.fixture
def mail_on(monkeypatch):
    from unittest.mock import AsyncMock

    from app.services import email as email_service

    monkeypatch.setattr(email_service, "email_configured", AsyncMock(return_value=True))


async def test_support_access_always_tells_the_community_when_it_starts(
    client: AsyncClient, session: AsyncSession, desk, acting_user, mail_on
):
    seat_id = (await create_user(session)).id
    target = await create_guild(
        session, creator=await session.get(User, seat_id), name="Lantern Club"
    )
    target_id = target.id
    task_id = await _case()
    requested = await _request(
        client,
        desk["agent"],
        target_id,
        case_task_id=task_id,
        community_notice="none",
    )
    assert requested.status_code == 201, requested.text
    assert requested.json()["community_notice"] == "when_granted"
    # Asked for is not yet given: nothing is said until it is.
    assert await _letters(session, seat_id) == []

    owner = await acting_user("owner")
    approved = await client.post(
        f"{GRANTS}{requested.json()['id']}/approve", json={}, headers=owner.headers
    )
    assert approved.status_code == 200, approved.text
    (letter,) = await _letters(session, seat_id)
    assert letter.security is True
    assert letter.subject == "Platform staff have access to Lantern Club"
    assert "read-only" in letter.body
    assert "support case" in letter.body


async def test_a_security_case_may_tell_the_community_once_access_ends(
    client: AsyncClient, session: AsyncSession, desk, mail_on
):
    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    session.add(
        IntakeBinding(stream=IntakeStream.security, project_id=desk["staff"].project.id)
    )
    await session.commit()
    await set_rls_context(session, Unattributed())
    seat_id = (await create_user(session)).id
    target = await create_guild(session, creator=await session.get(User, seat_id))
    task_id = await _case(IntakeStream.security)

    requested = await _request(
        client,
        desk["agent"],
        target.id,
        case_task_id=task_id,
        community_notice="when_ended",
        access_level="read",
        settings_level="admin",
    )
    assert requested.status_code == 201, requested.text
    grants = (
        await session.exec(
            select(AccessGrant).where(AccessGrant.case_task_id == task_id)
        )
    ).all()
    assert {grant.community_notice for grant in grants} == {"when_ended"}

    # Both were given, together, and have since ended.
    now = datetime.now(timezone.utc)
    for grant in grants:
        grant.status = "approved"
        grant.decided_at = now - timedelta(hours=2)
        grant.expires_at = now - timedelta(hours=1)
        session.add(grant)
    await session.commit()
    assert await _letters(session, seat_id) == []

    await set_rls_context(session, Unattributed())
    await grant_cases.report_activity(session, now=now)
    (letter,) = await _letters(session, seat_id)
    assert letter.subject.startswith("Platform staff had access to")
    assert "read-only" in letter.body
    assert "community-settings (admin)" in letter.body
    assert "security case" in letter.body


async def test_telling_the_community_is_chosen_only_where_offered(
    client: AsyncClient, session: AsyncSession, desk, acting_user
):
    owner = await acting_user("operator")
    target = await create_guild(session)
    response = await client.post(
        f"{GRANTS}break-glass",
        json={
            "community_id": target.id,
            "reason": "an emergency",
            "community_notice": "when_granted",
        },
        headers=owner.headers,
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == AccessGrantMessages.COMMUNITY_NOTICE_NOT_OFFERED
