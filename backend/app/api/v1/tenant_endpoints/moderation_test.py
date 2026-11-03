"""Reporting something, who can read the report, and settling it."""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient, Response
from sqlmodel import select

from app.core.moderation import ReportOutcome, ReportVenue
from app.core.tools import Tool
from app.db.session import set_rls_context
from app.models.platform.guild import CommunityRole
from app.core.intake import CaseField, IntakeStream
from app.models.platform.app_setting import AppSetting
from app.models.tenant.intake import IntakeBinding, IntakeCase
from app.models.tenant.metadata import MetadataDefinition, MetadataValue
from app.models.tenant.comment import Comment
from app.models.tenant.moderation import ModerationReport, ModerationReportReporter
from app.models.tenant.task import Task
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.testing import (
    create_resource_grant,
    create_comment,
    create_guild,
    create_initiative,
    create_project,
    create_guild_membership,
    create_initiative_member,
    create_marketplace_listing,
    create_task,
    create_user,
    emitted,
    get_auth_headers,
)
from app.db.request_context import SystemGuild, Unattributed


async def _report(client: AsyncClient, actor, **body) -> Response:
    """File a report the way every surface does: as a moderation ticket."""
    return await client.post(
        "/api/v1/me/tickets",
        data={"payload": json.dumps({"stream": "moderation", **body})},
        headers=actor.headers,
    )


def _reports_url(scene: dict) -> str:
    """Where an initiative's moderators read what has been reported."""
    return f"/api/v1/c/{scene['guild'].id}/initiatives/{scene['initiative'].id}/reports"


def _sharing_url(scene: dict) -> str:
    """Where they read what the initiative has shared."""
    return f"/api/v1/c/{scene['guild'].id}/initiatives/{scene['initiative'].id}/sharing"


async def _report_comment(client: AsyncClient, scene: dict, **body) -> Response:
    """The fixture's ordinary member reporting the fixture's comment.

    The reason is a closed enum that decides no venue and is asserted nowhere,
    so it has a default; anything a test does read back — ``detail``, a
    different ``target_type`` — it passes itself.
    """
    return await _report(
        client,
        scene["member"],
        **{
            "target_type": "comment",
            "target_id": scene["comment"].id,
            "reason": "spam",
            "community_id": scene["guild"].id,
            **body,
        },
    )


async def _report_and_read(client: AsyncClient, scene: dict, **body) -> dict:
    """File one report and read the single card a moderator gets for it."""
    filed = await _report_comment(client, scene, **body)
    assert filed.status_code == 202, filed.text

    listed = await client.get(_reports_url(scene), headers=scene["mod"].headers)
    assert listed.status_code == 200, listed.text
    (item,) = listed.json()["items"]
    assert listed.json()["total_count"] == 1
    return item


async def _filed_report_id(client: AsyncClient, session, scene: dict, **body) -> int:
    """File a report about the fixture's comment; the id it was recorded as."""
    filed = await _report_comment(client, scene, **body)
    assert filed.status_code == 202, filed.text

    await set_rls_context(session, SystemGuild(scene["guild"].id))
    report_id = (await session.exec(select(ModerationReport))).one().id
    await set_rls_context(session, Unattributed())
    return report_id


@pytest.fixture
async def scene(session, acting_user):
    """A moderator, an ordinary member, and a comment to report.

    The moderator is not the initiative's creator: the standing that opens this
    surface is the role's "Full access" flag, not having made the place.
    """
    owner = await acting_user(
        guild_role=CommunityRole.admin, initiative=True, project=True
    )
    mod = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="moderator",
    )
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    # Shared with the initiative, which is what makes the comment something an
    # ordinary member can see — and therefore something they can report. A
    # report is only ever about a thing the reporter could reach.
    await create_resource_grant(
        session,
        owner.project,
        all_initiative_members=True,
        level=ResourceAccessLevel.write,
    )

    task = await create_task(session, owner.project)
    comment = await create_comment(session, member.user, task=task)
    await set_rls_context(session, Unattributed())
    return {
        "guild": owner.guild,
        "initiative": owner.initiative,
        "admin": owner,
        "mod": mod,
        "member": member,
        "task": task,
        "comment": comment,
    }


@pytest.fixture
async def operations(session):
    """A deployment with somewhere for platform reports to go.

    A separate community, as it would be: the operations guild is an ordinary
    one that happens to be pointed at.
    """
    staff = await create_user(session)
    ops_guild = await create_guild(session, creator=staff)
    ops_initiative = await create_initiative(session, ops_guild, staff)
    ops_project = await create_project(session, ops_initiative, staff)

    await set_rls_context(session, Unattributed())
    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    if row is None:
        row = AppSetting(id=1)
    row.operations_guild_id = ops_guild.id
    session.add(row)
    await session.commit()

    await set_rls_context(session, SystemGuild(ops_guild.id))
    session.add(
        IntakeBinding(stream=IntakeStream.moderation, project_id=ops_project.id)
    )
    await session.commit()
    await set_rls_context(session, Unattributed())
    return {"guild": ops_guild, "project": ops_project}


async def test_reporting_community_content_lands_in_its_initiative(
    client, session, scene
):
    response = await _report_comment(
        client, scene, reason="harassment", detail="This is abusive."
    )
    assert response.status_code == 202, response.text
    assert response.json()["venue"] == ReportVenue.initiative.value

    await set_rls_context(session, SystemGuild(scene["guild"].id))
    report = (await session.exec(select(ModerationReport))).one()
    assert report.initiative_id == scene["initiative"].id
    assert report.target_type == "comment"
    assert report.outcome is None


async def test_reporting_identity_goes_to_the_platform(
    client, session, scene, operations
):
    """No community owns a complaint about a username."""
    response = await _report(
        client,
        scene["member"],
        target_type="username",
        target_id=scene["member"].user.id,
        reason="hate",
    )
    assert response.status_code == 202
    assert response.json()["venue"] == ReportVenue.platform.value

    # It landed as an ordinary intake case in the operations community.
    await set_rls_context(session, SystemGuild(operations["guild"].id))
    task = (
        await session.exec(
            select(Task).where(Task.project_id == operations["project"].id)
        )
    ).one()
    assert "username" in task.title


async def test_a_reporter_cannot_read_the_report_they_filed(client, scene):
    """Filing gains nothing: reading stays with the initiative's moderators."""
    await _report_comment(client, scene)

    listed = await client.get(_reports_url(scene), headers=scene["member"].headers)
    assert listed.status_code == 200
    assert listed.json()["items"] == []


async def test_a_moderator_reads_it(client, scene):
    item = await _report_and_read(client, scene, detail="Nonsense.")

    assert item["reporter_count"] == 1
    assert item["details"] == ["Nonsense."]
    # Who reported it is deliberately absent from the payload.
    assert "reporter_id" not in item
    assert "reporters" not in item


async def test_a_report_carries_what_was_reported(client, scene):
    """A moderator reads the comment on the card, not only that one exists."""
    item = await _report_and_read(client, scene, reason="harassment")

    assert item["target_excerpt"] == scene["comment"].content
    # A comment is read on the thing it was said on, so the link opens that —
    # the task itself, not the project the task is shared as part of.
    assert item["target_link"] == {
        "entity_type": "task",
        "entity_id": scene["task"].id,
        "tool": Tool.project.value,
        "tool_id": scene["task"].project_id,
    }


async def test_a_reported_task_is_addressed_by_its_project(client, scene):
    """Every kind gets the pair, not just a comment."""
    item = await _report_and_read(
        client, scene, target_type="task", target_id=scene["task"].id
    )

    assert item["target_excerpt"] == scene["task"].title
    assert item["target_link"] == {
        "entity_type": "task",
        "entity_id": scene["task"].id,
        "tool": Tool.project.value,
        "tool_id": scene["task"].project_id,
    }


async def test_a_deleted_target_leaves_the_report_without_one(client, session, scene):
    """The report stands; there is just nothing left to show or link to."""
    await _report_comment(client, scene, reason="harassment")

    await set_rls_context(session, SystemGuild(scene["guild"].id))
    comment = await session.get(Comment, scene["comment"].id)
    await session.delete(comment)
    await session.commit()
    await set_rls_context(session, Unattributed())

    listed = await client.get(_reports_url(scene), headers=scene["mod"].headers)
    item = listed.json()["items"][0]
    assert item["target_excerpt"] is None
    assert item["target_link"] is None


async def test_settling_closes_it_and_answers_with_the_whole_card(
    client, session, scene
):
    """The page replaces the card with this reply, so it carries everything the
    card did — the decision, the reporters behind it, and the reported thing."""
    report_id = await _filed_report_id(client, session, scene, detail="Nonsense.")

    response = await client.post(
        f"/api/v1/c/{scene['guild'].id}/reports/{report_id}/settle",
        json={"outcome": ReportOutcome.dismissed.value, "note": "Looked; fine."},
        headers=scene["mod"].headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "dismissed"
    assert body["decided_by"] == scene["mod"].user.id
    assert body["decided_at"] is not None
    assert body["reporter_count"] == 1
    assert body["details"] == ["Nonsense."]
    assert body["target_excerpt"] == scene["comment"].content


async def test_a_second_reporter_joins_the_open_report(client, session, scene):
    another = await create_user(session)
    await create_guild_membership(
        session, user=another, guild=scene["guild"], role=CommunityRole.member
    )
    await create_initiative_member(
        session, scene["initiative"], another, role_name="member"
    )
    await set_rls_context(session, Unattributed())

    for headers in (scene["member"].headers, get_auth_headers(another)):
        response = await client.post(
            "/api/v1/me/tickets",
            data={
                "payload": json.dumps(
                    {
                        "stream": "moderation",
                        "target_type": "comment",
                        "target_id": scene["comment"].id,
                        "reason": "spam",
                        "community_id": scene["guild"].id,
                    }
                )
            },
            headers=headers,
        )
        assert response.status_code == 202

    listed = await client.get(_reports_url(scene), headers=scene["mod"].headers)
    items = listed.json()["items"]
    assert len(items) == 1, "two people reporting one thing is one thing to decide"
    assert items[0]["reporter_count"] == 2


async def test_the_same_person_reporting_twice_does_not_raise_the_count(client, scene):
    """The count has to mean distinct people, or it means nothing."""
    for _ in range(3):
        await _report_comment(client, scene)

    listed = await client.get(_reports_url(scene), headers=scene["mod"].headers)
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["reporter_count"] == 1


async def test_a_community_a_reporter_is_not_in_places_nothing_there(
    client, session, scene, operations
):
    """Ids are unique only within a schema, so a named community is checked,
    and a reporter who cannot see the thing there cannot report it."""
    outsider = await create_user(session)
    await set_rls_context(session, Unattributed())

    response = await client.post(
        "/api/v1/me/tickets",
        data={
            "payload": json.dumps(
                {
                    "stream": "moderation",
                    "target_type": "comment",
                    "target_id": scene["comment"].id,
                    "reason": "spam",
                    "community_id": scene["guild"].id,
                }
            )
        },
        headers=get_auth_headers(outsider),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "MODERATION_TARGET_NOT_FOUND"

    await set_rls_context(session, SystemGuild(scene["guild"].id))
    assert (await session.exec(select(ModerationReport))).all() == []


async def test_a_settled_report_is_not_settled_again(client, session, scene):
    report_id = await _filed_report_id(client, session, scene)

    url = f"/api/v1/c/{scene['guild'].id}/reports/{report_id}/settle"
    first = await client.post(
        url, json={"outcome": "dismissed"}, headers=scene["mod"].headers
    )
    assert first.status_code == 200
    second = await client.post(
        url, json={"outcome": "content_removed"}, headers=scene["mod"].headers
    )
    assert second.status_code == 400
    assert second.json()["detail"] == "MODERATION_REPORT_ALREADY_SETTLED"


async def test_an_ordinary_member_cannot_settle(client, session, scene):
    report_id = await _filed_report_id(client, session, scene)

    response = await client.post(
        f"/api/v1/c/{scene['guild'].id}/reports/{report_id}/settle",
        json={"outcome": "dismissed"},
        headers=scene["member"].headers,
    )
    # RLS hides the row, so it is not there to settle.
    assert response.status_code == 404


async def test_reporting_something_that_is_not_reportable(client, scene):
    response = await _report(
        client,
        scene["member"],
        target_type="the_vibes",
        target_id=1,
        reason="spam",
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "MODERATION_UNKNOWN_TARGET_TYPE"


async def test_reporters_are_recorded_even_though_they_are_not_shown(
    client, session, scene
):
    """Held for dedupe and for an escalation to carry, not for display."""
    await _report_comment(client, scene)

    await set_rls_context(session, SystemGuild(scene["guild"].id))
    rows = (await session.exec(select(ModerationReportReporter))).all()
    assert [row.reporter_id for row in rows] == [scene["member"].user.id]


async def test_a_report_that_reaches_nobody_is_refused(client, scene):
    """Every install starts with no moderation project bound."""
    response = await _report(
        client,
        scene["member"],
        target_type="username",
        target_id=scene["member"].user.id,
        reason="hate",
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "MODERATION_NOWHERE_TO_SEND"


async def test_an_identity_target_that_does_not_exist_is_refused(client, scene):
    """Checked before it becomes work, so no task names a row that is not there."""
    response = await _report(
        client,
        scene["member"],
        target_type="username",
        target_id=999_999,
        reason="hate",
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "MODERATION_TARGET_NOT_FOUND"


async def test_the_list_is_paged(client, scene):
    response = await client.get(
        _reports_url(scene),
        params={"limit": 1, "offset": 0},
        headers=scene["mod"].headers,
    )
    assert response.status_code == 200
    assert len(response.json()["items"]) <= 1


async def test_escalating_with_nowhere_to_send_leaves_the_report_open(
    client, session, scene
):
    """Closing it as escalated would record a handover that never happened."""
    report_id = await _filed_report_id(client, session, scene, reason="harassment")

    response = await client.post(
        f"/api/v1/c/{scene['guild'].id}/reports/{report_id}/settle",
        json={"outcome": "escalated"},
        headers=scene["mod"].headers,
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "MODERATION_NOWHERE_TO_SEND"

    await set_rls_context(session, SystemGuild(scene["guild"].id))
    still = (
        await session.exec(
            select(ModerationReport).where(ModerationReport.id == report_id)
        )
    ).one()
    await session.refresh(still)
    assert still.outcome is None
    assert still.decided_at is None


async def test_escalating_opens_a_platform_case(client, session, scene, operations):
    """The one crossing between the two shapes, carrying the reporters."""
    report_id = await _filed_report_id(
        client, session, scene, reason="harassment", detail="They posted my address."
    )

    response = await client.post(
        f"/api/v1/c/{scene['guild'].id}/reports/{report_id}/settle",
        json={"outcome": "escalated", "note": "Not ours to settle."},
        headers=scene["mod"].headers,
    )
    assert response.status_code == 200
    assert response.json()["outcome"] == "escalated"

    await set_rls_context(session, SystemGuild(operations["guild"].id))
    task = (
        await session.exec(
            select(Task).where(Task.project_id == operations["project"].id)
        )
    ).one()
    assert "comment" in task.title
    # The reporters travel with an escalation: the platform is where good
    # faith is judged.
    assert str(scene["member"].user.id) in (task.description or "")
    # And so do their own words, which are what the platform judges.
    assert "They posted my address." in (task.description or "")
    # Named with its community, since content ids are numbered per community.
    case = (await session.exec(select(IntakeCase))).one()
    assert case.dedupe_key == (
        f"report:{scene['guild'].id}:comment:{scene['comment'].id}"
    )


@pytest.mark.parametrize(
    "stranger_to_the_reporter",
    [False, True],
    ids=["somebody in the same community", "somebody they have never met"],
)
async def test_any_account_can_be_reported_by_profile(
    client, session, scene, operations, stranger_to_the_reporter: bool
):
    """A profile is everyone's to read, so it is everyone's to report.

    The lookup runs on the reporter's own platform-scoped session, so the
    identity tables answer for an account they share nothing with just as they
    do for one they sit beside.
    """
    if stranger_to_the_reporter:
        target = await create_user(session)
        await set_rls_context(session, Unattributed())
    else:
        target = scene["mod"].user

    response = await _report(
        client,
        scene["member"],
        target_type="user_profile",
        target_id=target.id,
        reason="harassment",
    )

    assert response.status_code == 202
    assert response.json()["venue"] == ReportVenue.platform.value


async def test_a_marketplace_listing_is_reported_to_the_platform(
    client, session, scene, operations
):
    """A listing belongs to the server's catalog, so its operators get the
    report, and the case says which listing it was."""
    listing = await create_marketplace_listing(
        session,
        uid="RPRTMKT0000001",
        public_id="acme.reported",
        publisher="Acme",
    )
    await set_rls_context(session, Unattributed())

    response = await _report(
        client,
        scene["member"],
        target_type="marketplace_listing",
        target_id=listing.id,
        reason="spam",
        detail="Not what it says it is.",
        community_id=scene["guild"].id,
    )
    assert response.status_code == 202, response.text
    assert response.json()["venue"] == ReportVenue.platform.value

    await set_rls_context(session, SystemGuild(operations["guild"].id))
    task = (
        await session.exec(
            select(Task).where(Task.project_id == operations["project"].id)
        )
    ).one()
    assert "marketplace_listing" in task.title
    assert "acme.reported" in (task.description or "")
    assert "Acme" in (task.description or "")


async def test_a_listing_that_does_not_exist_is_not_reportable(client, session, scene):
    """A listing the catalog holds resolves, and only then does the report go
    looking for somewhere to land; one it does not hold is refused first."""
    listing = await create_marketplace_listing(
        session, uid="RPRTMKT0000002", public_id="acme.real"
    )
    await set_rls_context(session, Unattributed())

    real = await _report(
        client,
        scene["member"],
        target_type="marketplace_listing",
        target_id=listing.id,
        reason="spam",
    )
    missing = await _report(
        client,
        scene["member"],
        target_type="marketplace_listing",
        target_id=999_999,
        reason="spam",
    )
    # No operations community is bound here, so the real one reaches nobody.
    assert real.status_code == 503, real.text
    assert missing.status_code == 404, missing.text


async def test_a_reported_community_is_the_cases_subject(
    client, session, scene, operations
):
    """A community reported from the directory or by name is what its case is
    about, so the case names it the way a community's content does."""
    response = await _report(
        client,
        scene["member"],
        target_type="guild",
        target_id=scene["guild"].id,
        reason="hate",
    )
    assert response.status_code == 202, response.text

    await set_rls_context(session, SystemGuild(operations["guild"].id))
    task = (
        await session.exec(
            select(Task).where(Task.project_id == operations["project"].id)
        )
    ).one()
    subject_guild = (
        await session.exec(
            select(MetadataValue.value_number)
            .join(
                MetadataDefinition,
                MetadataDefinition.id == MetadataValue.property_id,
            )
            .where(MetadataValue.entity_type == "task")
            .where(MetadataValue.entity_id == task.id)
            .where(MetadataDefinition.name == CaseField.subject_guild.value)
        )
    ).one()
    assert int(subject_guild) == scene["guild"].id


async def test_a_community_the_reporter_cannot_see_is_not_reportable(
    client, session, scene, operations
):
    """Hidden and missing answer the same way: reporting reaches as far as looking."""
    stranger = await create_user(session)
    hidden = await create_guild(session, creator=stranger)
    await set_rls_context(session, Unattributed())

    hidden_response = await _report(
        client,
        scene["member"],
        target_type="guild",
        target_id=hidden.id,
        reason="hate",
    )
    missing_response = await _report(
        client,
        scene["member"],
        target_type="guild",
        target_id=999_999,
        reason="hate",
    )
    assert hidden_response.status_code == missing_response.status_code == 404
    assert hidden_response.json() == missing_response.json()


async def test_the_sharing_overview_is_for_moderators(client, scene):
    """Grants on every resource is a wider question than grants on one.

    ``resource_grants`` is scoped to initiative membership, which is right for
    reading the sharing on something you can already reach. The aggregate asks
    about resources the reader may not reach at all, so it takes the standing
    the moderation tables take.
    """
    url = _sharing_url(scene)
    assert (await client.get(url, headers=scene["member"].headers)).status_code == 404
    assert (await client.get(url, headers=scene["mod"].headers)).status_code == 200


async def test_the_sharing_overview_names_what_is_shared(client, scene):
    response = await client.get(_sharing_url(scene), headers=scene["mod"].headers)

    assert response.status_code == 200
    items = response.json()["items"]
    # The fixture shares its project with the whole initiative.
    project = next(i for i in items if i["resource_type"] == "project")
    assert project["all_initiative_members"] is True
    assert project["name"]


async def test_a_guild_admin_reads_it_without_being_in_the_initiative(
    client, session, scene
):
    admin = await create_user(session)
    await create_guild_membership(
        session, user=admin, guild=scene["guild"], role=CommunityRole.admin
    )
    await set_rls_context(session, Unattributed())

    response = await client.get(_sharing_url(scene), headers=get_auth_headers(admin))
    assert response.status_code == 200


async def test_a_communitys_moderation_leaves_no_trace_in_the_platform_log(
    client, session, scene, operations, capfd
):
    """A community's own moderation decisions are not the platform's record.

    The audit stream is the deployment operator's log, and what it holds is the
    population we have to show we triaged. A community deciding its own
    business is that community's, kept in its own schema and governed by its
    own retention — so filing a report and settling it must add nothing there.
    Escalation is the one crossing, and even it carries no line: what it opens
    is an intake case, which is work rather than a record.

    Asserted against the stream rather than against the event registry, so a
    moderation decision that started writing one would fail here whichever
    member it chose.
    """
    capfd.readouterr()

    report_id = await _filed_report_id(
        client, session, scene, reason="harassment", detail="This is abusive."
    )
    settle = await client.post(
        f"/api/v1/c/{scene['guild'].id}/reports/{report_id}/settle",
        json={"outcome": "content_removed", "note": "Taken down."},
        headers=scene["mod"].headers,
    )
    assert settle.status_code == 200, settle.text

    added = emitted(capfd)
    assert added == [], (
        "a community's moderation wrote to the platform audit log: "
        f"{[row['event_type'] for row in added]}"
    )
