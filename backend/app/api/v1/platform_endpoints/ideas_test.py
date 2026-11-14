"""The published ideas: what anybody reads, voting, publishing by type, the
team's case panel, telling voters when an idea moves, the ideas like what
somebody is writing, and joining feedback and ideas to ideas."""

from __future__ import annotations

import json

import pytest
from sqlmodel import select

from app.api.v1.platform_endpoints import tickets_test
from app.api.v1.platform_endpoints.tickets_feedback_test import cloud  # noqa: F401
from app.core.intake import IntakeStream
from app.core.messages import IdeaMessages, TaskMessages
from app.core.version import __version__
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.models.platform.guild import CommunityRole
from app.models.platform.notice_outbox import NoticeOutboxItem
from app.models.platform.notification import NotificationType
from app.models.tenant.intake import IdeaVote, IntakeBinding, IntakeCase
from app.models.tenant.task import Task, TaskStatus, TaskStatusCategory, TaskType
from app.services.platform import ticket_notices
from app.services.platform import users as user_service
from app.testing import (
    create_guild,
    create_initiative,
    create_project,
    create_task,
    create_user,
    get_auth_headers,
)

IDEAS = "/api/v1/ideas"

operations = tickets_test.operations


@pytest.fixture
async def board(session, operations, cloud):  # noqa: F811
    """Initiative Cloud's operations community, its Ideas board bound to the
    board's Idea type, with a published idea, a draft, and a feedback case
    moved onto the board."""
    project = operations["project"]
    draft = await create_task(
        session, project, title="Holiday calendars to subscribe to"
    )
    draft_type_id = draft.task_type_id
    case = await create_task(session, project, title="Idea: my own words")
    await set_rls_context(session, SystemGuild(operations["guild"].id))
    idea_type = (
        await session.exec(
            select(TaskType)
            .where(TaskType.project_id == project.id)
            .where(TaskType.name == "Idea")
        )
    ).one()
    await set_rls_context(session, Unattributed())
    published = await create_task(
        session,
        project,
        title="Recurring events skip holidays",
        task_type_id=idea_type.id,
        description="Pick a holiday calendar for a recurring event.",
    )
    await set_rls_context(session, SystemGuild(operations["guild"].id))
    session.add(
        IntakeBinding(
            stream=IntakeStream.ideas,
            project_id=project.id,
            task_type_id=idea_type.id,
        )
    )
    session.add(
        IntakeCase(
            stream=IntakeStream.feedback.value,
            task_id=case.id,
            opened_at=case.created_at,
            last_seen_at=case.created_at,
            noted_at=case.created_at,
        )
    )
    await session.commit()
    await set_rls_context(session, Unattributed())
    return {
        **operations,
        "staff": get_auth_headers(operations["staff"]),
        "staff_user": operations["staff"],
        "idea_type": idea_type,
        "published": published,
        "draft": draft,
        "draft_type_id": draft_type_id,
        "case": case,
    }


async def _move(session, board, task: Task, category: TaskStatusCategory) -> None:
    await set_rls_context(session, SystemGuild(board["guild"].id))
    status_id = (
        await session.exec(
            select(TaskStatus.id)
            .where(TaskStatus.project_id == board["project"].id)
            .where(TaskStatus.category == category)
        )
    ).first()
    task = (await session.exec(select(Task).where(Task.id == task.id))).one()
    task.task_status_id = status_id
    session.add(task)
    await session.commit()
    await set_rls_context(session, Unattributed())


async def test_only_cloud_has_an_ideas_board(client, operations):
    response = await client.get(IDEAS)
    assert response.status_code == 404
    assert response.json()["detail"] == IdeaMessages.NOT_FOUND


async def test_anybody_reads_the_published_ideas_and_nothing_else(client, board):
    """Signed out, the list is the published idea alone: not the team's draft,
    and not a feedback case moved onto the board, whose words are its
    sender's."""
    listed = await client.get(IDEAS)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert [idea["title"] for idea in body["items"]] == [
        "Recurring events skip holidays"
    ]
    assert body["items"][0]["votes"] == 0
    assert body["items"][0]["voted"] is False
    # The statuses the published ideas read as, for filtering by.
    assert [s["category"] for s in body["statuses"]] == ["todo"]
    assert "icon" in body["statuses"][0]

    one = await client.get(f"{IDEAS}/{board['published'].id}")
    assert one.json()["description"] == "Pick a holiday calendar for a recurring event."
    for hidden in (board["draft"], board["case"]):
        response = await client.get(f"{IDEAS}/{hidden.id}")
        assert response.status_code == 404, hidden.title

    searched = await client.get(IDEAS, params={"search": "HOLIDAY"})
    assert [i["task_id"] for i in searched.json()["items"]] == [board["published"].id]
    assert (await client.get(IDEAS, params={"search": "holidy"})).json()["items"] == []


async def test_a_vote_counts_once_and_can_be_taken_back(client, acting_user, board):
    voter = await acting_user()
    other = await acting_user()
    path = f"{IDEAS}/{board['published'].id}/vote"

    assert (await client.put(path)).status_code == 401
    for _ in range(2):
        voted = await client.put(path, headers=voter.headers)
        assert voted.status_code == 200, voted.text
    assert (voted.json()["votes"], voted.json()["voted"]) == (1, True)

    seen = (await client.get(IDEAS, headers=other.headers)).json()["items"][0]
    assert (seen["votes"], seen["voted"]) == (1, False)
    mine = await client.get(IDEAS, params={"voted": True}, headers=other.headers)
    assert mine.json()["items"] == []

    taken = await client.delete(path, headers=voter.headers)
    assert (taken.json()["votes"], taken.json()["voted"]) == (0, False)


async def test_a_closed_idea_keeps_its_votes(client, session, acting_user, board):
    voter = await acting_user()
    path = f"{IDEAS}/{board['published'].id}/vote"
    await client.put(path, headers=voter.headers)
    await _move(session, board, board["published"], TaskStatusCategory.done)

    for method in ("PUT", "DELETE"):
        response = await client.request(method, path, headers=voter.headers)
        assert response.status_code == 409
        assert response.json()["detail"] == IdeaMessages.CLOSED
    assert (await client.get(f"{IDEAS}/{board['published'].id}")).json()["votes"] == 1


async def test_the_team_publishes_an_idea_by_its_type(client, board):
    """Giving a task on the board the Idea type publishes it, and any other
    type takes it back; its case panel counts its votes."""
    headers = board["staff"]
    base = f"/api/v1/c/{board['guild'].id}/tasks"
    draft = board["draft"]

    unpublished = await client.get(f"{base}/{draft.id}/case", headers=headers)
    assert unpublished.status_code == 404

    changed = await client.patch(
        f"{base}/{draft.id}",
        json={"task_type_id": board["idea_type"].id},
        headers=headers,
    )
    assert changed.status_code == 200, changed.text
    titles = {i["title"] for i in (await client.get(IDEAS)).json()["items"]}
    assert "Holiday calendars to subscribe to" in titles
    panel = await client.get(f"{base}/{draft.id}/case", headers=headers)
    assert panel.status_code == 200, panel.text
    assert (panel.json()["stream"], panel.json()["votes"]) == ("ideas", 0)
    assert panel.json()["filer"] is None

    await client.patch(
        f"{base}/{draft.id}",
        json={"task_type_id": board["draft_type_id"]},
        headers=headers,
    )
    titles = {i["title"] for i in (await client.get(IDEAS)).json()["items"]}
    assert "Holiday calendars to subscribe to" not in titles


async def test_a_feedback_case_keeps_its_own_panel(client, board):
    """A feedback case moved onto the board is its sender's words, and its
    panel is the feedback case's, without votes."""
    response = await client.get(
        f"/api/v1/c/{board['guild'].id}/tasks/{board['case'].id}/case",
        headers=board["staff"],
    )
    assert response.status_code == 200, response.text
    assert (response.json()["stream"], response.json()["votes"]) == ("feedback", None)


async def test_unbinding_the_board_publishes_nothing(client, session, board):
    await set_rls_context(session, SystemGuild(board["guild"].id))
    binding = (
        await session.exec(
            select(IntakeBinding).where(
                IntakeBinding.stream == IntakeStream.ideas.value
            )
        )
    ).one()
    await session.delete(binding)
    await session.commit()
    await set_rls_context(session, Unattributed())

    assert (await client.get(IDEAS)).json()["items"] == []
    response = await client.get(
        f"/api/v1/c/{board['guild'].id}/tasks/{board['published'].id}/case",
        headers=board["staff"],
    )
    assert response.status_code == 404
    assert response.json()["detail"] == TaskMessages.NOT_A_CASE


async def test_voters_hear_when_an_idea_moves(client, session, acting_user, board):
    """A vote starts at the status it was cast on, so the first pass tells
    nobody; a move tells each voter once."""
    voter = await acting_user()
    await client.put(f"{IDEAS}/{board['published'].id}/vote", headers=voter.headers)
    assert await ticket_notices.notify_filers() == 0

    await _move(session, board, board["published"], TaskStatusCategory.in_progress)
    assert await ticket_notices.notify_filers() == 1
    assert await ticket_notices.notify_filers() == 0

    await set_rls_context(session, Unattributed())
    notice = (
        await session.exec(
            select(NoticeOutboxItem)
            .where(NoticeOutboxItem.user_id == voter.user.id)
            .where(NoticeOutboxItem.type == NotificationType.idea_updated.value)
        )
    ).one()
    assert notice.data["task_id"] == board["published"].id
    assert notice.data["target_path"] == f"/suggestions/{board['published'].id}"


async def test_a_task_moved_off_the_board_is_nobodys_to_read(
    client, session, acting_user, board
):
    """An idea's task moved to another project keeps its row and its votes,
    but nobody reads it and nobody is told about it."""
    voter = await acting_user()
    await client.put(f"{IDEAS}/{board['published'].id}/vote", headers=voter.headers)
    elsewhere = await create_project(session, board["initiative"], board["staff_user"])
    moved = await create_task(
        session, elsewhere, status_category=TaskStatusCategory.done
    )
    await set_rls_context(session, SystemGuild(board["guild"].id))
    task = (
        await session.exec(select(Task).where(Task.id == board["published"].id))
    ).one()
    task.project_id = elsewhere.id
    task.task_status_id = moved.task_status_id
    session.add(task)
    await session.commit()
    await set_rls_context(session, Unattributed())

    response = await client.get(f"{IDEAS}/{board['published'].id}")
    assert response.status_code == 404
    assert await ticket_notices.notify_filers() == 0


async def test_erasing_a_voter_takes_their_vote(client, session, acting_user, board):
    """Even from an idea the team archived, which freezes what is under it."""
    voter = await acting_user()
    await client.put(f"{IDEAS}/{board['published'].id}/vote", headers=voter.headers)
    await set_rls_context(session, SystemGuild(board["guild"].id))
    task = (
        await session.exec(select(Task).where(Task.id == board["published"].id))
    ).one()
    task.archived_at = task.created_at
    session.add(task)
    await session.commit()
    await set_rls_context(session, Unattributed())

    await user_service.hard_delete_user(session, voter.user.id)

    await set_rls_context(session, SystemGuild(board["guild"].id))
    assert (await session.exec(select(IdeaVote))).all() == []
    await set_rls_context(session, Unattributed())


@pytest.fixture
async def desk(client, session, acting_user, cloud):  # noqa: F811
    """Initiative Cloud, its Feedback and Ideas boards set up from their
    blueprints in one initiative, with two published ideas, and the
    community's owner to work them. Ids rather than rows: the settings routes
    run on this session and route it."""
    platform_owner = await acting_user("owner")
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    initiative = await create_initiative(session, guild, owner)
    team = get_auth_headers(owner)
    guild_id, initiative_id = guild.id, initiative.id
    await set_rls_context(session, Unattributed())
    await client.put(
        "/api/v1/settings/intake/community",
        json={"community_id": guild_id},
        headers=platform_owner.headers,
    )
    boards = {}
    for stream in ("feedback", "ideas"):
        made = await client.post(
            f"/api/v1/settings/intake/{stream}/blueprint",
            json={"initiative_id": initiative_id},
            headers=platform_owner.headers,
        )
        assert made.status_code == 200, made.text
        boards[stream] = made.json()
    tasks = f"/api/v1/c/{guild_id}/tasks"
    ideas = []
    for title in (
        "Recurring events skip holidays",
        "Holiday calendars to subscribe to",
    ):
        made = await client.post(
            f"{tasks}/",
            json={
                "project_id": boards["ideas"]["project_id"],
                "title": title,
                "task_type_id": boards["ideas"]["task_type_id"],
            },
            headers=team,
        )
        assert made.status_code in (200, 201), made.text
        ideas.append(made.json()["id"])
    await set_rls_context(session, SystemGuild(guild_id))
    binding = (
        await session.exec(
            select(IntakeBinding).where(
                IntakeBinding.stream == IntakeStream.ideas.value
            )
        )
    ).one()
    statuses = {
        status.name: status.id
        for status in await session.exec(
            select(TaskStatus).where(TaskStatus.project_id == binding.project_id)
        )
    }
    roles = {
        "category": binding.category_field_id,
        "release": binding.release_field_id,
        "shipped": binding.shipped_status_id,
    }
    await set_rls_context(session, Unattributed())
    # Setting the board up from its blueprint names its fields and its
    # shipped status on the binding.
    assert None not in roles.values()
    assert roles["shipped"] == statuses["Shipped"]
    return {
        "guild_id": guild_id,
        "team": team,
        "tasks": tasks,
        "boards": boards,
        "ideas": ideas,
        "roles": roles,
        "statuses": statuses,
    }


async def _send(client, actor, **body) -> None:
    payload = {"stream": "feedback", "type": "idea", "body": "Skip holidays, please."}
    payload.update(body)
    sent = await client.post(
        tickets_test.TICKETS,
        data={"payload": json.dumps(payload)},
        headers=actor.headers,
    )
    assert sent.status_code == 202, sent.text


async def _last_case(session, desk) -> int:
    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    task_id = (
        await session.exec(
            select(IntakeCase.task_id).order_by(IntakeCase.id.desc())  # type: ignore[union-attr]
        )
    ).first()
    await set_rls_context(session, Unattributed())
    assert task_id is not None
    return task_id


async def _case(client, desk, task_id: int) -> dict:
    read = await client.get(f"{desk['tasks']}/{task_id}/case", headers=desk["team"])
    assert read.status_code == 200, read.text
    return read.json()


async def test_writing_feedback_finds_the_ideas_like_it(client, desk):
    """Close either way round: a long draft finds a short title, and a few
    words find a longer one. A closed idea is not offered."""
    recurring, calendars = desk["ideas"]

    async def similar(text: str) -> list[int]:
        found = await client.get(f"{IDEAS}/similar", params={"text": text})
        assert found.status_code == 200, found.text
        return [idea["task_id"] for idea in found.json()]

    assert (await similar("Could recurring events skip the public holidays?"))[0] == (
        recurring
    )
    assert calendars in await similar("holiday calendars")
    assert await similar("Dark mode for printing") == []

    await _edit(client, desk, calendars, task_status_id=desk["statuses"]["Not planned"])
    assert calendars not in await similar("holiday calendars")


async def test_feedback_sent_for_an_idea_joins_it(client, session, acting_user, desk):
    """Its sender's vote counts once, whether or not they offered to be
    contacted, and the team sees the idea on the case."""
    recurring, _ = desk["ideas"]
    sender = await acting_user()
    voted = await client.put(f"{IDEAS}/{recurring}/vote", headers=sender.headers)
    assert voted.status_code == 200, voted.text
    await _send(client, sender, idea_task_id=recurring)

    case = await _case(client, desk, await _last_case(session, desk))
    assert case["joined_idea"]["task_id"] == recurring
    assert case["ideas_board_id"] == desk["boards"]["ideas"]["project_id"]
    idea = (await client.get(f"{IDEAS}/{recurring}", headers=sender.headers)).json()
    assert (idea["votes"], idea["voted"]) == (1, True)


async def test_the_team_joins_feedback_to_an_idea_and_takes_it_off(
    client, session, acting_user, desk
):
    """Joining gives its sender a vote; taking it off leaves the vote, which
    is theirs to take back. Only feedback joins, and only to the board."""
    recurring, calendars = desk["ideas"]
    sender = await acting_user()
    await _send(client, sender)
    case_id = await _last_case(session, desk)
    path = f"{desk['tasks']}/{case_id}/idea"

    joined = await client.put(
        path, json={"idea_task_id": calendars}, headers=desk["team"]
    )
    assert joined.status_code == 204, joined.text
    assert (await _case(client, desk, case_id))["joined_idea"] == {
        "task_id": calendars,
        "title": "Holiday calendars to subscribe to",
    }
    moved = await client.put(
        path, json={"idea_task_id": recurring}, headers=desk["team"]
    )
    assert moved.status_code == 204, moved.text
    assert (await _case(client, desk, case_id))["joined_idea"]["task_id"] == recurring
    for idea_id in (calendars, recurring):
        idea = (await client.get(f"{IDEAS}/{idea_id}", headers=sender.headers)).json()
        assert idea["voted"] is True, idea_id

    assert (await client.delete(path, headers=desk["team"])).status_code == 204
    assert (await _case(client, desk, case_id))["joined_idea"] is None
    idea = (await client.get(f"{IDEAS}/{recurring}", headers=sender.headers)).json()
    assert idea["voted"] is True

    for refused in (
        # An idea is not feedback.
        (f"{desk['tasks']}/{recurring}/idea", calendars),
        # Feedback is not an idea.
        (path, case_id),
    ):
        response = await client.put(
            refused[0], json={"idea_task_id": refused[1]}, headers=desk["team"]
        )
        assert response.status_code == 404, refused
        assert response.json()["detail"] == IdeaMessages.NOT_FOUND


async def test_an_idea_joins_another(client, session, acting_user, desk):
    """Its votes move, each voter's once, and so does the feedback joined to
    it. It leaves the Ideas page, and its page opens the other."""
    recurring, calendars = desk["ideas"]
    both, one = await acting_user(), await acting_user()
    for voter, idea_ids in ((both, (recurring, calendars)), (one, (recurring,))):
        for idea_id in idea_ids:
            await client.put(f"{IDEAS}/{idea_id}/vote", headers=voter.headers)
    await _send(client, one, idea_task_id=recurring)
    case_id = await _last_case(session, desk)

    response = await client.post(
        f"{desk['tasks']}/{recurring}/idea/join-into",
        json={"idea_task_id": calendars},
        headers=desk["team"],
    )
    assert response.status_code == 204, response.text

    listed = (await client.get(IDEAS)).json()["items"]
    assert [(i["task_id"], i["votes"]) for i in listed] == [(calendars, 2)]
    opened = await client.get(f"{IDEAS}/{recurring}")
    assert opened.status_code == 200, opened.text
    assert opened.json()["task_id"] == calendars
    assert (await _case(client, desk, case_id))["joined_idea"]["task_id"] == calendars

    # Joined again, the first page follows both joins.
    made = await client.post(
        f"{desk['tasks']}/",
        json={
            "project_id": desk["boards"]["ideas"]["project_id"],
            "title": "Holidays everywhere",
            "task_type_id": desk["boards"]["ideas"]["task_type_id"],
        },
        headers=desk["team"],
    )
    holidays = made.json()["id"]
    again = await client.post(
        f"{desk['tasks']}/{calendars}/idea/join-into",
        json={"idea_task_id": holidays},
        headers=desk["team"],
    )
    assert again.status_code == 204, again.text
    assert (await client.get(f"{IDEAS}/{recurring}")).json()["task_id"] == holidays
    # Nothing joins an idea that was joined into another.
    refused = await client.post(
        f"{desk['tasks']}/{holidays}/idea/join-into",
        json={"idea_task_id": recurring},
        headers=desk["team"],
    )
    assert refused.status_code == 404


async def _idea(client, desk, title: str, **body) -> int:
    made = await client.post(
        f"{desk['tasks']}/",
        json={
            "project_id": desk["boards"]["ideas"]["project_id"],
            "title": title,
            "task_type_id": desk["boards"]["ideas"]["task_type_id"],
            **body,
        },
        headers=desk["team"],
    )
    assert made.status_code == 201, made.text
    return made.json()["id"]


async def _edit(client, desk, task_id: int, **body) -> None:
    edited = await client.patch(
        f"{desk['tasks']}/{task_id}", json=body, headers=desk["team"]
    )
    assert edited.status_code == 200, edited.text


async def _release(client, desk, task_id: int, release: str | None) -> None:
    await _edit(
        client,
        desk,
        task_id,
        properties=[{"property_id": desk["roles"]["release"], "value": release}],
        merge_properties=True,
    )


async def _public(client, task_id: int) -> dict:
    read = await client.get(f"{IDEAS}/{task_id}")
    assert read.status_code == 200, read.text
    return read.json()


async def test_the_board_files_an_idea_under_the_category_its_words_name(client, desk):
    """Made or reworded while its category is empty, an idea takes the one its
    title names, else its description; one the team set stands."""
    recurring, calendars = desk["ideas"]
    # Made before its words named one: the blueprint's own seed task is not.
    assert (await _public(client, recurring))["category"] is None
    assert (await _public(client, calendars))["category"] == "Calendars"

    worded = await _idea(
        client,
        desk,
        "Dark mode everywhere",
        description="Starting with **wiki** pages and the files they show.",
    )
    assert (await _public(client, worded))["category"] == "Wikis"

    # Reworded: the category it has stands.
    await _edit(client, desk, worded, title="Dark mode for plug-ins")
    assert (await _public(client, worded))["category"] == "Wikis"

    # Empty, and reworded to name one.
    await _edit(client, desk, recurring, title="Recurring events in a project")
    assert (await _public(client, recurring))["category"] == "Projects"

    # Set by the team as it is made: theirs stands.
    chosen = await _idea(
        client,
        desk,
        "Notifications for a project",
        properties=[{"property_id": desk["roles"]["category"], "value": "account"}],
    )
    assert (await _public(client, chosen))["category"] == "Account"


async def test_the_list_counts_and_filters_by_category(client, acting_user, desk):
    recurring, calendars = desk["ideas"]
    projects = await _idea(
        client,
        desk,
        "Archive a project",
        description="Keep it out of the way.\n\nBut **find** it again later.",
    )
    voter = await acting_user()
    await client.put(f"{IDEAS}/{projects}/vote", headers=voter.headers)

    listed = (await client.get(IDEAS)).json()
    assert listed["categories"] == [
        {"name": "Projects", "count": 1},
        {"name": "Calendars", "count": 1},
    ]
    summaries = {idea["task_id"]: idea["summary"] for idea in listed["items"]}
    assert summaries[projects] == "Keep it out of the way."
    assert summaries[recurring] is None

    only = (await client.get(IDEAS, params={"category": "Projects"})).json()
    assert [idea["task_id"] for idea in only["items"]] == [projects]
    # The counts are of what the other filters show, whichever category.
    assert only["categories"] == listed["categories"]
    mine = (
        await client.get(
            IDEAS,
            params={"category": "Calendars", "voted": True},
            headers=voter.headers,
        )
    ).json()
    assert (mine["items"], mine["categories"]) == (
        [],
        [{"name": "Projects", "count": 1}],
    )
    unknown = (await client.get(IDEAS, params={"category": "Nothing"})).json()
    assert unknown["items"] == []
    assert calendars in {i["task_id"] for i in listed["items"]}


async def test_a_shipped_idea_reads_as_shipped_only_in_its_release(client, desk):
    """Before its release is out it reads as the board's last in-progress
    status; once a later one is out it leaves the list and the roadmap, and its
    own page still reads it as shipped in its release."""
    idea, _ = desk["ideas"]
    statuses, shipped = desk["statuses"], desk["roles"]["shipped"]
    await _edit(client, desk, idea, task_status_id=shipped)

    def listed(body: dict) -> dict:
        return {i["task_id"]: i for i in body["items"]}

    def column(roadmap: dict, name: str) -> list[int]:
        return next(
            [i["task_id"] for i in c["items"]]
            for c in roadmap["columns"]
            if c["status"]["name"] == name
        )

    for release in (None, "99.0.0"):
        await _release(client, desk, idea, release)
        read = await _public(client, idea)
        assert (read["status"]["id"], read["release"]) == (statuses["Building"], None)
        assert read["closed"] is False
        roadmap = (await client.get(f"{IDEAS}/roadmap")).json()
        assert column(roadmap, "Building") == [idea], release
        assert column(roadmap, "Shipped") == []

    await _release(client, desk, idea, __version__)
    read = await _public(client, idea)
    assert (read["status"]["id"], read["release"]) == (shipped, __version__)
    assert listed((await client.get(IDEAS)).json())[idea]["release"] == __version__
    roadmap = (await client.get(f"{IDEAS}/roadmap")).json()
    assert [c["status"]["name"] for c in roadmap["columns"]] == [
        "Planned",
        "Building",
        "Shipped",
    ]
    assert column(roadmap, "Shipped") == [idea]
    feed = await client.get(f"{IDEAS}/shipped", params={"release": __version__})
    assert [i["task_id"] for i in feed.json()] == [idea]
    # Written with a "v", it reads as the version, which What's new is named by.
    await _release(client, desk, idea, f"v{__version__}")
    assert (await _public(client, idea))["release"] == __version__

    await _release(client, desk, idea, "0.0.1")
    assert idea not in listed((await client.get(IDEAS)).json())
    roadmap = (await client.get(f"{IDEAS}/roadmap")).json()
    assert idea not in column(roadmap, "Shipped") + column(roadmap, "Building")
    read = await _public(client, idea)
    assert (read["status"]["id"], read["release"]) == (shipped, "0.0.1")
    feed = await client.get(f"{IDEAS}/shipped", params={"release": "v0.0.1"})
    assert [i["task_id"] for i in feed.json()] == [idea]
    # Nothing for a release this server is not yet on.
    feed = await client.get(f"{IDEAS}/shipped", params={"release": "99.0.0"})
    assert feed.json() == []


async def test_a_shipped_idea_stays_readable_on_a_board_with_nothing_in_progress(
    client, desk
):
    """With no in-progress status left, a shipped idea whose release is not out
    reads as the board's first waiting status, on the list and its own page."""
    idea, _ = desk["ideas"]
    statuses = desk["statuses"]
    project_id = desk["boards"]["ideas"]["project_id"]
    for name in ("Planned", "Building"):
        moved = await client.patch(
            f"/api/v1/c/{desk['guild_id']}/projects/{project_id}"
            f"/task-statuses/{statuses[name]}",
            json={"category": "todo"},
            headers=desk["team"],
        )
        assert moved.status_code == 200, moved.text
    await _edit(client, desk, idea, task_status_id=desk["roles"]["shipped"])

    read = await _public(client, idea)
    assert (read["status"]["id"], read["closed"]) == (
        statuses["Under consideration"],
        False,
    )
    assert idea in {i["task_id"] for i in (await client.get(IDEAS)).json()["items"]}


async def test_voters_hear_an_idea_shipped_once_its_release_is_out(
    client, session, acting_user, desk
):
    idea, _ = desk["ideas"]
    await _edit(client, desk, idea, task_status_id=desk["statuses"]["Building"])
    voter = await acting_user()
    await client.put(f"{IDEAS}/{idea}/vote", headers=voter.headers)

    await _edit(client, desk, idea, task_status_id=desk["roles"]["shipped"])
    assert await ticket_notices.notify_filers() == 0

    await _release(client, desk, idea, __version__)
    assert await ticket_notices.notify_filers() == 1
    await set_rls_context(session, Unattributed())
    notice = (
        await session.exec(
            select(NoticeOutboxItem)
            .where(NoticeOutboxItem.user_id == voter.user.id)
            .where(NoticeOutboxItem.type == NotificationType.idea_updated.value)
        )
    ).one()
    assert notice.data["status"] == "Shipped"


async def test_a_task_in_another_community_takes_no_category(client, acting_user, desk):
    """On Initiative Cloud, every other community's tasks are written as
    before: only the operations community binds a board."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    made = await client.post(
        a.g("/tasks/"),
        json={"project_id": a.project.id, "title": "A project for files"},
        headers=a.headers,
    )
    assert made.status_code == 201, made.text
    assert made.json()["properties"] == []
