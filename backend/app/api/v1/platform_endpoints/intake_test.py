"""The owner's intake settings, and who can read what lands through them."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlmodel import select

from app.api.v1.platform_endpoints.tickets_feedback_test import cloud  # noqa: F401
from app.core.intake import IntakeStream, offered_streams
from app.db.session import set_rls_context
from app.models.platform.app_setting import AppSetting
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative
from app.models.tenant.project import Project
from app.models.tenant.task import Task
from app.services.platform import intake as intake_service
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_user,
    get_auth_headers,
    route_session_to_guild,
)
from app.models.platform.guild import Guild, CommunityRole
from app.db.request_context import SystemGuild, Unattributed


@pytest.fixture
async def owner(session, acting_user):
    """A platform owner, and a guild they can point operations at.

    Ids rather than ORM rows: these endpoints run on the system session, which
    in tests IS this session, and routing it into a guild schema expunges the
    identity map. A detached row refreshed afterwards would read against the
    wrong search_path.
    """
    actor = await acting_user("owner")
    guild_owner = await create_user(session)
    guild = await create_guild(session, creator=guild_owner)
    initiative = await create_initiative(session, guild, guild_owner)
    ids = {
        "actor": actor,
        "guild_id": guild.id,
        "initiative_id": initiative.id,
        "guild_owner_id": guild_owner.id,
    }
    await set_rls_context(session, Unattributed())
    return ids


async def test_every_stream_is_listed_before_anything_is_configured(client, owner):
    response = await client.get(
        "/api/v1/settings/intake", headers=owner["actor"].headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["operations_community_id"] is None
    assert {b["stream"] for b in body["bindings"]} == {
        s.value for s in offered_streams()
    }
    assert all(b["enabled"] is False for b in body["bindings"])


async def test_a_member_cannot_read_or_change_the_settings(client, acting_user):
    """Not an owner, so not deployment configuration they may touch."""
    actor = await acting_user("member")
    assert (
        await client.get("/api/v1/settings/intake", headers=actor.headers)
    ).status_code == 403
    assert (
        await client.put(
            "/api/v1/settings/intake/community",
            json={"community_id": 1},
            headers=actor.headers,
        )
    ).status_code == 403


async def test_pointing_at_a_guild_that_does_not_exist_is_refused(client, owner):
    response = await client.put(
        "/api/v1/settings/intake/community",
        json={"community_id": 99_999},
        headers=owner["actor"].headers,
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "COMMUNITY_NOT_FOUND"


async def test_binding_before_a_guild_is_named_is_refused(client, owner):
    response = await client.put(
        "/api/v1/settings/intake/support",
        json={"project_id": 1},
        headers=owner["actor"].headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "INTAKE_NO_OPERATIONS_COMMUNITY"


async def test_an_unknown_stream_is_not_a_stream(client, owner):
    response = await client.put(
        "/api/v1/settings/intake/rumours",
        json={"project_id": 1},
        headers=owner["actor"].headers,
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "INTAKE_UNKNOWN_STREAM"


async def test_setting_a_stream_up_from_its_blueprint(client, session, owner):
    await client.put(
        "/api/v1/settings/intake/community",
        json={"community_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    response = await client.post(
        "/api/v1/settings/intake/security/blueprint",
        json={"initiative_id": owner["initiative_id"]},
        headers=owner["actor"].headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stream"] == "security"
    assert body["project_name"] == "Security"
    assert body["enabled"] is True
    assert body["initiative_id"] == owner["initiative_id"]

    # A case filed now lands in what the blueprint produced.
    outcome = await intake_service.open_case(
        IntakeStream.security, title="Refused sign-ins", body="Ten in fifteen minutes."
    )
    assert outcome is not None
    await set_rls_context(session, SystemGuild(owner["guild_id"]))
    task = (await session.exec(select(Task).where(Task.id == outcome.task_id))).one()
    assert task.project_id == body["project_id"]


async def test_clearing_the_pointer_stops_every_stream(client, session, owner):
    await client.put(
        "/api/v1/settings/intake/community",
        json={"community_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    await client.post(
        "/api/v1/settings/intake/support/blueprint",
        json={"initiative_id": owner["initiative_id"]},
        headers=owner["actor"].headers,
    )
    assert (
        await intake_service.open_case(IntakeStream.support, title="Help") is not None
    )

    response = await client.put(
        "/api/v1/settings/intake/community",
        json={"community_id": None},
        headers=owner["actor"].headers,
    )
    assert response.status_code == 200
    assert await intake_service.open_case(IntakeStream.support, title="Help") is None

    # The binding is untouched: pointing back restores what was there.
    await client.put(
        "/api/v1/settings/intake/community",
        json={"community_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    assert (
        await intake_service.open_case(IntakeStream.support, title="Help") is not None
    )


@pytest.mark.usefixtures("cloud")
async def test_setting_the_ideas_board_up_names_its_published_type(client, owner):
    """The type is what publishes an idea, so a board set up from its
    blueprint publishes its Published tasks and keeps every other type a
    draft."""
    await client.put(
        "/api/v1/settings/intake/community",
        json={"community_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    response = await client.post(
        "/api/v1/settings/intake/ideas/blueprint",
        json={"initiative_id": owner["initiative_id"]},
        headers=owner["actor"].headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["task_type_name"] == "Published"


@pytest.mark.usefixtures("cloud")
async def test_unbinding_keeps_the_project(client, session, owner):
    await client.put(
        "/api/v1/settings/intake/community",
        json={"community_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    created = await client.post(
        "/api/v1/settings/intake/feedback/blueprint",
        json={"initiative_id": owner["initiative_id"]},
        headers=owner["actor"].headers,
    )
    project_id = created.json()["project_id"]

    response = await client.delete(
        "/api/v1/settings/intake/feedback", headers=owner["actor"].headers
    )
    assert response.status_code == 204
    assert await intake_service.open_case(IntakeStream.feedback, title="Idea") is None

    await set_rls_context(session, SystemGuild(owner["guild_id"]))
    assert (
        await session.exec(select(Project).where(Project.id == project_id))
    ).one_or_none() is not None


async def test_a_guild_member_outside_the_initiative_cannot_read_a_case(
    client, session, owner
):
    """Gate 2, unchanged: the bound project's initiative is who reads its cases."""
    await client.put(
        "/api/v1/settings/intake/community",
        json={"community_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    await client.post(
        "/api/v1/settings/intake/security/blueprint",
        json={"initiative_id": owner["initiative_id"]},
        headers=owner["actor"].headers,
    )

    await set_rls_context(session, Unattributed())
    outsider = await create_user(session)
    guild = (
        await session.exec(select(Guild).where(Guild.id == owner["guild_id"]))
    ).one()
    await create_guild_membership(
        session, user=outsider, guild=guild, role=CommunityRole.member
    )

    outcome = await intake_service.open_case(
        IntakeStream.security, title="Refused sign-ins"
    )
    assert outcome is not None

    response = await client.get(
        f"/api/v1/c/{owner['guild_id']}/tasks/{outcome.task_id}",
        headers=get_auth_headers(outsider),
    )
    assert response.status_code == 404


async def test_a_status_from_another_project_is_refused(client, session, owner):
    await client.put(
        "/api/v1/settings/intake/community",
        json={"community_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    created = await client.post(
        "/api/v1/settings/intake/support/blueprint",
        json={"initiative_id": owner["initiative_id"]},
        headers=owner["actor"].headers,
    )
    await route_session_to_guild(session, owner["guild_id"])
    from app.models.tenant.task import TaskStatus
    from app.services.tenant import task_statuses as task_statuses_service

    initiative = (
        await session.exec(
            select(Initiative).where(Initiative.id == owner["initiative_id"])
        )
    ).one()
    guild_owner = (
        await session.exec(select(User).where(User.id == owner["guild_owner_id"]))
    ).one()
    elsewhere = await create_project(session, initiative, guild_owner)

    await task_statuses_service.ensure_default_statuses(
        session, elsewhere.id, locale="en"
    )
    await session.commit()
    foreign = (
        await session.exec(
            select(TaskStatus).where(TaskStatus.project_id == elsewhere.id)
        )
    ).first()
    await set_rls_context(session, Unattributed())

    response = await client.put(
        "/api/v1/settings/intake/support",
        json={
            "project_id": created.json()["project_id"],
            "default_status_id": foreign.id,
        },
        headers=owner["actor"].headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "INTAKE_STATUS_NOT_IN_PROJECT"


async def test_a_binding_names_one_of_its_projects_types(client, session, owner):
    await client.put(
        "/api/v1/settings/intake/community",
        json={"community_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    created = await client.post(
        "/api/v1/settings/intake/support/blueprint",
        json={"initiative_id": owner["initiative_id"]},
        headers=owner["actor"].headers,
    )
    project_id = created.json()["project_id"]
    await route_session_to_guild(session, owner["guild_id"])
    from app.services.tenant import task_types as task_types_service

    initiative = (
        await session.exec(
            select(Initiative).where(Initiative.id == owner["initiative_id"])
        )
    ).one()
    guild_owner = (
        await session.exec(select(User).where(User.id == owner["guild_owner_id"]))
    ).one()
    elsewhere = await create_project(session, initiative, guild_owner)
    foreign = (
        await task_types_service.ensure_default_types(
            session, elsewhere.id, locale="en"
        )
    )[1]
    bug = (
        await task_types_service.ensure_default_types(session, project_id, locale="en")
    )[1]
    await session.commit()
    await set_rls_context(session, Unattributed())

    refused = await client.put(
        "/api/v1/settings/intake/support",
        json={"project_id": project_id, "task_type_id": foreign.id},
        headers=owner["actor"].headers,
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == "INTAKE_TYPE_NOT_IN_PROJECT"

    bound = await client.put(
        "/api/v1/settings/intake/support",
        json={"project_id": project_id, "task_type_id": bug.id},
        headers=owner["actor"].headers,
    )
    assert bound.status_code == 200, bound.text
    assert (bound.json()["task_type_id"], bound.json()["task_type_name"]) == (
        bug.id,
        bug.name,
    )


async def test_the_pointer_is_cleared_when_the_guild_goes(client, session, owner):
    """``ON DELETE SET NULL``: nothing is left naming a guild that is gone."""
    await client.put(
        "/api/v1/settings/intake/community",
        json={"community_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    await set_rls_context(session, Unattributed())
    await session.exec(
        text("DELETE FROM public.guilds WHERE id = :gid").bindparams(
            gid=owner["guild_id"]
        )
    )
    await session.commit()

    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).one()
    assert row.operations_guild_id is None


async def test_repointing_a_stream_starts_fresh_in_the_new_project(
    client, session, owner
):
    """Cases are keyed by project, so a repeat follows the binding."""
    await client.put(
        "/api/v1/settings/intake/community",
        json={"community_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    first = await client.post(
        "/api/v1/settings/intake/support/blueprint",
        json={"initiative_id": owner["initiative_id"]},
        headers=owner["actor"].headers,
    )
    opened = await intake_service.open_case(
        IntakeStream.support, title="Refused", dedupe_key="refused:42"
    )
    assert opened is not None

    await route_session_to_guild(session, owner["guild_id"])
    initiative = (
        await session.exec(
            select(Initiative).where(Initiative.id == owner["initiative_id"])
        )
    ).one()
    guild_owner = (
        await session.exec(select(User).where(User.id == owner["guild_owner_id"]))
    ).one()
    elsewhere = await create_project(session, initiative, guild_owner)
    elsewhere_id = elsewhere.id
    await set_rls_context(session, Unattributed())

    repointed = await client.put(
        "/api/v1/settings/intake/support",
        json={"project_id": elsewhere_id},
        headers=owner["actor"].headers,
    )
    assert repointed.status_code == 200
    assert repointed.json()["project_id"] == elsewhere_id

    again = await intake_service.open_case(
        IntakeStream.support, title="Refused", dedupe_key="refused:42"
    )
    assert again is not None
    assert again.opened is True
    assert again.task_id != opened.task_id

    await set_rls_context(session, SystemGuild(owner["guild_id"]))
    landed = (await session.exec(select(Task).where(Task.id == again.task_id))).one()
    assert landed.project_id == elsewhere_id
    assert first.json()["project_id"] != elsewhere_id


async def test_rebinding_the_same_project_finds_the_open_case(client, session, owner):
    """Unbinding keeps the history, so a repeat does not open a second case."""
    await client.put(
        "/api/v1/settings/intake/community",
        json={"community_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    created = await client.post(
        "/api/v1/settings/intake/support/blueprint",
        json={"initiative_id": owner["initiative_id"]},
        headers=owner["actor"].headers,
    )
    project_id = created.json()["project_id"]
    opened = await intake_service.open_case(
        IntakeStream.support, title="Refused", dedupe_key="refused:42"
    )
    assert opened is not None

    await client.delete(
        "/api/v1/settings/intake/support", headers=owner["actor"].headers
    )
    rebound = await client.put(
        "/api/v1/settings/intake/support",
        json={"project_id": project_id},
        headers=owner["actor"].headers,
    )
    assert rebound.status_code == 200

    again = await intake_service.open_case(
        IntakeStream.support, title="Refused", dedupe_key="refused:42"
    )
    assert again is not None
    assert again.opened is False
    assert again.task_id == opened.task_id


@pytest.mark.usefixtures("cloud")
async def test_the_last_case_time_ignores_ordinary_tasks(client, owner):
    """A blueprint's seed task is not a case, and must not read as one."""
    await client.put(
        "/api/v1/settings/intake/community",
        json={"community_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    created = await client.post(
        "/api/v1/settings/intake/feedback/blueprint",
        json={"initiative_id": owner["initiative_id"]},
        headers=owner["actor"].headers,
    )
    assert created.json()["last_case_at"] is None

    await intake_service.open_case(IntakeStream.feedback, title="An idea")
    listed = await client.get("/api/v1/settings/intake", headers=owner["actor"].headers)
    feedback = next(b for b in listed.json()["bindings"] if b["stream"] == "feedback")
    assert feedback["last_case_at"] is not None


async def test_only_cloud_sets_feedback_up(client, owner):
    """Feedback goes to Initiative Cloud from every other server, which lists
    no Feedback board, binds none and keeps no address for one."""
    await client.put(
        "/api/v1/settings/intake/community",
        json={"community_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    listed = await client.get("/api/v1/settings/intake", headers=owner["actor"].headers)
    assert "feedback" not in {b["stream"] for b in listed.json()["bindings"]}
    assert listed.json()["feedback_enabled"] is True

    for method, path, body in (
        ("POST", "feedback/blueprint", {"initiative_id": owner["initiative_id"]}),
        ("PUT", "feedback", {"project_id": 1}),
        ("PUT", "feedback/contact", {"email": "ideas@example.org"}),
    ):
        response = await client.request(
            method,
            f"/api/v1/settings/intake/{path}",
            json=body,
            headers=owner["actor"].headers,
        )
        assert response.status_code == 404, path


async def test_options_are_empty_before_a_guild_is_named(client, owner):
    response = await client.get(
        "/api/v1/settings/intake/options", headers=owner["actor"].headers
    )
    assert response.status_code == 200
    assert response.json()["initiatives"] == []


async def test_options_offer_the_operations_guilds_projects(client, owner):
    await client.put(
        "/api/v1/settings/intake/community",
        json={"community_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    created = await client.post(
        "/api/v1/settings/intake/support/blueprint",
        json={"initiative_id": owner["initiative_id"]},
        headers=owner["actor"].headers,
    )
    project_id = created.json()["project_id"]

    response = await client.get(
        "/api/v1/settings/intake/options", headers=owner["actor"].headers
    )
    assert response.status_code == 200
    initiatives = response.json()["initiatives"]
    mine = next(i for i in initiatives if i["id"] == owner["initiative_id"])
    project = next(p for p in mine["projects"] if p["id"] == project_id)
    # The blueprint's four columns, so the landing-status picker has something
    # to offer.
    assert [s["name"] for s in project["statuses"]] == [
        "Triage",
        "Investigating",
        "Waiting on requester",
        "Requester replied",
        "Resolved",
    ]
    # And its types, for the type a case is.
    assert [t["name"] for t in project["task_types"]] == [
        "Task",
        "Bug",
        "Idea",
        "Milestone",
    ]


async def test_a_member_cannot_read_the_options(client, acting_user):
    actor = await acting_user("member")
    response = await client.get(
        "/api/v1/settings/intake/options", headers=actor.headers
    )
    assert response.status_code == 403


async def test_a_stream_cannot_be_bound_to_an_archived_project(client, session, owner):
    """Archived content takes no writes, so a case could never land there."""
    await client.put(
        "/api/v1/settings/intake/community",
        json={"community_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    await route_session_to_guild(session, owner["guild_id"])
    initiative = (
        await session.exec(
            select(Initiative).where(Initiative.id == owner["initiative_id"])
        )
    ).one()
    guild_owner = (
        await session.exec(select(User).where(User.id == owner["guild_owner_id"]))
    ).one()
    shelved = await create_project(
        session, initiative, guild_owner, archived_at=datetime.now(timezone.utc)
    )
    shelved_id = shelved.id
    await set_rls_context(session, Unattributed())

    response = await client.put(
        "/api/v1/settings/intake/support",
        json={"project_id": shelved_id},
        headers=owner["actor"].headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "INTAKE_PROJECT_NOT_LIVE"


async def test_a_binding_says_when_its_project_has_been_archived(
    client, session, owner
):
    """Archiving the destination later is a state the page has to show."""
    await client.put(
        "/api/v1/settings/intake/community",
        json={"community_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    created = await client.post(
        "/api/v1/settings/intake/support/blueprint",
        json={"initiative_id": owner["initiative_id"]},
        headers=owner["actor"].headers,
    )
    assert created.json()["project_archived"] is False
    project_id = created.json()["project_id"]

    await set_rls_context(session, SystemGuild(owner["guild_id"]))
    project = (
        await session.exec(select(Project).where(Project.id == project_id))
    ).one()
    project.archived_at = datetime.now(timezone.utc)
    session.add(project)
    await session.commit()
    await set_rls_context(session, Unattributed())

    listed = await client.get("/api/v1/settings/intake", headers=owner["actor"].headers)
    support = next(b for b in listed.json()["bindings"] if b["stream"] == "support")
    assert support["project_archived"] is True
    assert support["project_name"] == "Support"

    # And nothing lands there while it is archived, rather than the database
    # refusing the write.
    assert await intake_service.open_case(IntakeStream.support, title="Help") is None


# ── Who to contact ──────────────────────────────────────────────────────────


async def test_contacts_start_empty(client, owner):
    body = (
        await client.get("/api/v1/settings/intake", headers=owner["actor"].headers)
    ).json()
    assert body["general_contact_email"] is None
    assert body["contact_emails"] == {}


async def test_the_general_and_a_stream_contact_are_set_and_cleared(client, owner):
    headers = owner["actor"].headers
    response = await client.put(
        "/api/v1/settings/intake/contact",
        headers=headers,
        json={"email": "ops@example.com"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["general_contact_email"] == "ops@example.com"

    response = await client.put(
        "/api/v1/settings/intake/moderation/contact",
        headers=headers,
        json={"email": "trust@example.com"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["contact_emails"] == {"moderation": "trust@example.com"}

    response = await client.put(
        "/api/v1/settings/intake/moderation/contact",
        headers=headers,
        json={"email": None},
    )
    assert response.json()["contact_emails"] == {}
    assert response.json()["general_contact_email"] == "ops@example.com"

    response = await client.put(
        "/api/v1/settings/intake/contact", headers=headers, json={"email": None}
    )
    assert response.json()["general_contact_email"] is None


async def test_a_contact_must_be_an_address(client, owner):
    response = await client.put(
        "/api/v1/settings/intake/contact",
        headers=owner["actor"].headers,
        json={"email": "not an address"},
    )
    assert response.status_code == 422


async def test_a_contact_for_an_unknown_stream_is_refused(client, owner):
    response = await client.put(
        "/api/v1/settings/intake/billing/contact",
        headers=owner["actor"].headers,
        json={"email": "ops@example.com"},
    )
    assert response.status_code == 404


async def test_a_member_cannot_set_a_contact(client, acting_user):
    member = await acting_user("member")
    response = await client.put(
        "/api/v1/settings/intake/contact",
        headers=member.headers,
        json={"email": "ops@example.com"},
    )
    assert response.status_code == 403


async def test_a_stream_falls_back_to_the_general_contact_and_never_to_another(
    client, session, owner
):
    headers = owner["actor"].headers
    await set_rls_context(session, Unattributed())
    assert await intake_service.contact_for(session, IntakeStream.moderation) is None

    await client.put(
        "/api/v1/settings/intake/support/contact",
        headers=headers,
        json={"email": "help@example.com"},
    )
    await set_rls_context(session, Unattributed())
    session.expire_all()
    assert await intake_service.contact_for(session, IntakeStream.moderation) is None
    assert (
        await intake_service.contact_for(session, IntakeStream.support)
        == "help@example.com"
    )

    await client.put(
        "/api/v1/settings/intake/contact",
        headers=headers,
        json={"email": "ops@example.com"},
    )
    await set_rls_context(session, Unattributed())
    session.expire_all()
    assert (
        await intake_service.contact_for(session, IntakeStream.moderation)
        == "ops@example.com"
    )
    assert (
        await intake_service.contact_for(session, IntakeStream.support)
        == "help@example.com"
    )


async def _point(client, owner) -> None:
    response = await client.put(
        "/api/v1/settings/intake/community",
        json={"community_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("stream", ["support", "security"])
async def test_a_blueprint_names_which_statuses_wait_on_the_filer(
    client, session, owner, stream
):
    """Setting a stream that holds a conversation up from its blueprint creates
    a status for each role and names them on the binding, so its filers can be
    told a case is waiting on them from the start."""
    await _point(client, owner)
    bound = (
        await client.post(
            f"/api/v1/settings/intake/{stream}/blueprint",
            json={"initiative_id": owner["initiative_id"]},
            headers=owner["actor"].headers,
        )
    ).json()
    assert bound["awaiting_filer_status_id"] is not None
    assert bound["active_status_id"] is not None

    options = (
        await client.get(
            "/api/v1/settings/intake/options", headers=owner["actor"].headers
        )
    ).json()
    statuses = {
        status["id"]: status["name"]
        for initiative in options["initiatives"]
        for project in initiative["projects"]
        if project["id"] == bound["project_id"]
        for status in project["statuses"]
    }
    assert statuses[bound["awaiting_filer_status_id"]] == "Waiting on requester"
    assert statuses[bound["active_status_id"]] == "Requester replied"


async def test_a_stream_without_a_conversation_names_no_status_roles(client, owner):
    """Moderation reports open no conversation, so nobody is waited on."""
    await _point(client, owner)
    bound = (
        await client.post(
            "/api/v1/settings/intake/moderation/blueprint",
            json={"initiative_id": owner["initiative_id"]},
            headers=owner["actor"].headers,
        )
    ).json()
    assert bound["awaiting_filer_status_id"] is None
    assert bound["active_status_id"] is None


@pytest.mark.usefixtures("cloud")
async def test_a_status_role_from_another_project_is_refused(client, owner):
    await _point(client, owner)
    support = (
        await client.post(
            "/api/v1/settings/intake/support/blueprint",
            json={"initiative_id": owner["initiative_id"]},
            headers=owner["actor"].headers,
        )
    ).json()
    feedback = (
        await client.post(
            "/api/v1/settings/intake/feedback/blueprint",
            json={"initiative_id": owner["initiative_id"]},
            headers=owner["actor"].headers,
        )
    ).json()

    response = await client.put(
        "/api/v1/settings/intake/support",
        json={
            "project_id": support["project_id"],
            "awaiting_filer_status_id": feedback["awaiting_filer_status_id"],
        },
        headers=owner["actor"].headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "INTAKE_STATUS_NOT_IN_PROJECT"


async def test_a_stream_that_keeps_to_itself_will_not_share_an_initiative(
    client, owner
):
    """Security binds where no other stream works, in either order: neither
    beside support, nor support beside it."""
    await _point(client, owner)
    support = await client.post(
        "/api/v1/settings/intake/support/blueprint",
        json={"initiative_id": owner["initiative_id"]},
        headers=owner["actor"].headers,
    )
    assert support.status_code == 200, support.text

    refused = await client.post(
        "/api/v1/settings/intake/security/blueprint",
        json={"initiative_id": owner["initiative_id"]},
        headers=owner["actor"].headers,
    )
    assert refused.status_code == 409
    assert refused.json()["detail"] == "INTAKE_INITIATIVE_SHARED"

    refused = await client.put(
        "/api/v1/settings/intake/moderation",
        json={"project_id": support.json()["project_id"]},
        headers=owner["actor"].headers,
    )
    assert refused.status_code == 409
    assert refused.json()["detail"] == "INTAKE_INITIATIVE_SHARED"


@pytest.mark.usefixtures("cloud")
async def test_streams_that_do_not_keep_to_themselves_share_freely(client, owner):
    await _point(client, owner)
    for stream in ("support", "feedback"):
        response = await client.post(
            f"/api/v1/settings/intake/{stream}/blueprint",
            json={"initiative_id": owner["initiative_id"]},
            headers=owner["actor"].headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["shares_initiative"] is False


@pytest.mark.usefixtures("cloud")
async def test_a_shared_initiative_bound_before_the_rule_is_flagged(
    client, session, owner
):
    """Bindings that predate the rule are left working and shown as shared."""
    await _point(client, owner)
    support = (
        await client.post(
            "/api/v1/settings/intake/support/blueprint",
            json={"initiative_id": owner["initiative_id"]},
            headers=owner["actor"].headers,
        )
    ).json()
    from app.models.tenant.intake import IntakeBinding

    await set_rls_context(session, SystemGuild(owner["guild_id"]))
    session.add(
        IntakeBinding(stream=IntakeStream.security, project_id=support["project_id"])
    )
    await session.commit()
    await set_rls_context(session, Unattributed())

    bindings = {
        b["stream"]: b
        for b in (
            await client.get("/api/v1/settings/intake", headers=owner["actor"].headers)
        ).json()["bindings"]
    }
    assert bindings["security"]["isolated"] is True
    assert bindings["security"]["shares_initiative"] is True
    assert bindings["support"]["shares_initiative"] is True
    assert bindings["feedback"]["shares_initiative"] is False
