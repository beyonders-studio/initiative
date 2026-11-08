"""The published ideas: what anybody reads, voting, the team's Idea panel, and
telling voters when an idea moves."""

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
from app.models.tenant.intake import Idea, IntakeBinding, IntakeCase
from app.models.tenant.task import Task, TaskStatus, TaskStatusCategory
from app.services.platform import ideas as ideas_service
from app.services.platform import users as user_service
from app.testing import create_project, create_task, get_auth_headers

IDEAS = "/api/v1/ideas"

operations = tickets_test.operations


@pytest.fixture
async def board(session, operations, cloud):  # noqa: F811
    """Initiative Cloud's operations community, its Ideas board bound, with a
    published idea, a draft, and a feedback case moved onto the board."""
    project = operations["project"]
    published = await create_task(
        session, project, title="Recurring events skip holidays"
    )
    published.description = "Pick a holiday calendar for a recurring event."
    draft = await create_task(
        session, project, title="Holiday calendars to subscribe to"
    )
    case = await create_task(session, project, title="Idea: my own words")
    await set_rls_context(session, SystemGuild(operations["guild"].id))
    session.add(published)
    session.add(IntakeBinding(stream=IntakeStream.ideas, project_id=project.id))
    session.add(Idea(task_id=published.id, published_at=published.created_at))
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
        "published": published,
        "draft": draft,
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


async def test_the_team_publishes_an_idea_from_its_panel(client, board):
    headers = board["staff"]
    base = f"/api/v1/c/{board['guild'].id}/tasks"

    panel = await client.get(f"{base}/{board['draft'].id}/idea", headers=headers)
    assert panel.status_code == 200, panel.text
    assert panel.json() == {"published_at": None, "votes": 0}

    published = await client.put(
        f"{base}/{board['draft'].id}/idea/published", headers=headers
    )
    assert published.json()["published_at"] is not None
    titles = {i["title"] for i in (await client.get(IDEAS)).json()["items"]}
    assert "Holiday calendars to subscribe to" in titles

    await client.delete(f"{base}/{board['draft'].id}/idea/published", headers=headers)
    titles = {i["title"] for i in (await client.get(IDEAS)).json()["items"]}
    assert "Holiday calendars to subscribe to" not in titles


async def test_a_task_off_the_board_has_no_idea_panel(client, session, board):
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

    response = await client.get(
        f"/api/v1/c/{board['guild'].id}/tasks/{board['draft'].id}/idea",
        headers=board["staff"],
    )
    assert response.status_code == 404
    assert response.json()["detail"] == TaskMessages.NOT_AN_IDEA


async def test_voters_hear_when_an_idea_moves(client, session, acting_user, board):
    """A vote starts at the status it was cast on, so the first pass tells
    nobody; a move tells each voter once."""
    voter = await acting_user()
    await client.put(f"{IDEAS}/{board['published'].id}/vote", headers=voter.headers)
    assert await ideas_service.notify_voters() == 0

    await _move(session, board, board["published"], TaskStatusCategory.in_progress)
    assert await ideas_service.notify_voters() == 1
    assert await ideas_service.notify_voters() == 0

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
    assert await ideas_service.notify_voters() == 0


async def test_erasing_a_voter_takes_their_vote(client, session, acting_user, board):
    voter = await acting_user()
    await client.put(f"{IDEAS}/{board['published'].id}/vote", headers=voter.headers)
    await user_service.hard_delete_user(session, voter.user.id)

    await _move(session, board, board["published"], TaskStatusCategory.in_progress)
    assert await ideas_service.notify_voters() == 0
    assert (await client.get(f"{IDEAS}/{board['published'].id}")).json()["votes"] == 0
