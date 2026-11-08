"""The published ideas: what anybody reads, voting, publishing by type, the
team's case panel, and telling voters when an idea moves."""

from __future__ import annotations

import pytest
from sqlmodel import select

from app.api.v1.platform_endpoints import tickets_test
from app.api.v1.platform_endpoints.tickets_feedback_test import cloud  # noqa: F401
from app.core.intake import IntakeStream
from app.core.messages import IdeaMessages, TaskMessages
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.models.platform.notice_outbox import NoticeOutboxItem
from app.models.platform.notification import NotificationType
from app.models.tenant.intake import IdeaVote, IntakeBinding, IntakeCase
from app.models.tenant.task import Task, TaskStatus, TaskStatusCategory, TaskType
from app.services.platform import ticket_notices
from app.services.platform import users as user_service
from app.testing import create_project, create_task, get_auth_headers

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
    assert {s["category"] for s in body["statuses"]} >= {"todo", "done"}

    one = await client.get(f"{IDEAS}/{board['published'].id}")
    assert one.json()["description"] == "Pick a holiday calendar for a recurring event."
    for hidden in (board["draft"], board["case"]):
        response = await client.get(f"{IDEAS}/{hidden.id}")
        assert response.status_code == 404, hidden.title

    searched = await client.get(IDEAS, params={"q": "HOLIDAY"})
    assert [i["task_id"] for i in searched.json()["items"]] == [board["published"].id]
    assert (await client.get(IDEAS, params={"q": "holidy"})).json()["items"] == []


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
    assert notice.data["target_path"] == f"/ideas/{board['published'].id}"


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
