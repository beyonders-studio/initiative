"""Regression tests for the ``page_size=0`` window protocol.

"Fetch all" list requests are served in ``FETCH_ALL_WINDOW``-sized pages:
every response is bounded, ``page`` selects the window, and ``has_next``
tells the caller to keep walking — so large result sets are fully
retrievable while no single response can dump an entire table. These tests
pin both halves of that contract on every endpoint that accepts
``page_size=0``, with the window shrunk to 3 so the tests stay small.

The regression they guard against: the previous behavior silently truncated
``page_size=0`` responses at the cap, dropping rows from task boards and
file pickers with no signal to the client.
"""

import pytest

from app.models.platform.guild import CommunityRole
from app.testing import create_file, create_project, create_task

WINDOW = 3
TOTAL = 7  # 3 windows: 3 + 3 + 1


@pytest.fixture(autouse=True)
def _small_window(monkeypatch):
    monkeypatch.setattr("app.db.query.FETCH_ALL_WINDOW", WINDOW)


async def _walk(client, url: str, headers: dict, created: set[int]) -> None:
    """Walk ``url``'s ``page_size=0`` windows: each is bounded, and together
    they reassemble exactly ``created`` — no gaps, no dupes."""
    ids: list[int] = []
    pages = 0
    while True:
        pages += 1
        assert pages <= TOTAL, "window walk failed to terminate"
        response = await client.get(
            url, params={"page_size": 0, "page": pages}, headers=headers
        )
        assert response.status_code == 200
        body = response.json()
        # Bounded: one response never exceeds the window, and truncation is loud.
        assert len(body["items"]) == (WINDOW if pages < 3 else TOTAL - 2 * WINDOW)
        assert body["total_count"] == TOTAL
        ids.extend(item["id"] for item in body["items"])
        if not body["has_next"]:
            break

    assert pages == 3
    assert len(ids) == len(set(ids)) == TOTAL
    assert set(ids) == created


async def test_tasks_fetch_all_windows(client, session, acting_user):
    """Guild /tasks/ (the canonical DB-windowed path via paginated_query). A
    positive page_size is clamped to the window too, even though endpoint
    ``le=`` validation should reject it first."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    created = {(await create_task(session, a.project)).id for _ in range(TOTAL)}

    await _walk(client, a.g("/tasks/"), a.headers, created)

    # le=100 admits page_size=100; the window (3) must still bound the response.
    response = await client.get(a.g("/tasks/?page_size=100"), headers=a.headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == WINDOW
    assert body["has_next"] is True


async def test_files_fetch_all_windows(client, session, acting_user):
    """Guild /files/ (hand-rolled SQL path, now on apply_pagination)."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    created = {
        (await create_file(session, a.initiative, a.user)).id for _ in range(TOTAL)
    }

    await _walk(client, a.g("/files/"), a.headers, created)


async def test_projects_fetch_all_windows(client, session, acting_user):
    """Guild /projects/ (in-memory DAC-filtered list, now on paginate_sequence).

    page_size=0 is this endpoint's DEFAULT, so the window protocol is what
    every project picker/board exercises.
    """
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    created = {a.project.id}
    while len(created) < TOTAL:
        created.add((await create_project(session, a.initiative, a.user)).id)

    await _walk(client, a.g("/projects/"), a.headers, created)


async def test_me_tasks_fetch_all_windows(client, session, acting_user):
    """/me/tasks (cross-guild in-memory merge path, now on paginate_sequence)."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    created = {
        (await create_task(session, a.project, assignees=[a.user])).id
        for _ in range(TOTAL)
    }

    await _walk(client, "/api/v1/me/tasks", a.headers, created)
