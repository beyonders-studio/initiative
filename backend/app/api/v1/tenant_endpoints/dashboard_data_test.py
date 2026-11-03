"""A canvas answered at once: ``GET /dashboards/{id}/data``.

The one statement the canvas compiles to has to say exactly what each widget
says on its own, to exactly the same reader. The first test holds that for the
shapes a canvas holds; the rest hold the ways a canvas load differs from one
widget's: a failing widget does not take the others with it, and a guild with
no free slot refuses the canvas as a whole.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


from app.core.messages import QueryMessages
from app.models.platform.guild import CommunityRole
from app.models.tenant.metadata import MetadataType
from app.models.tenant.task import TaskStatusCategory
from app.services.query import executor
from app.services.tenant.view_as_test import dashboard_body, dashboards_on
from app.testing import (
    create_initiative,
    create_project,
    create_property_definition,
    create_property_value,
    create_queue,
    create_task,
)


async def _canvas(client, actor, *statements: str) -> int:
    response = await client.post(
        actor.g("/dashboards/"),
        json={
            "name": "Canvas",
            "initiative_id": actor.initiative.id,
            "definition": dashboard_body(*statements),
        },
        headers=actor.headers,
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


async def _data(client, actor, dashboard_id: int) -> dict:
    response = await client.get(
        actor.g(f"/dashboards/{dashboard_id}/data"), headers=actor.headers
    )
    assert response.status_code == 200, response.text
    return response.json()["widgets"]


async def _one(client, actor, sql: str) -> dict:
    response = await client.post(
        actor.g("/query"),
        json={"sql": sql, "initiative_id": actor.initiative.id},
        headers=actor.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _author_with_tasks(session, acting_user):
    author = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await dashboards_on(session, author.initiative)
    project = await create_project(session, author.initiative, author.user)
    for offset, category in enumerate(
        (TaskStatusCategory.todo, TaskStatusCategory.todo, TaskStatusCategory.done)
    ):
        await create_task(
            session,
            project,
            title=f"Task {offset}",
            status_category=category,
            due_date=datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(days=offset),
        )
    return author, project


async def test_the_canvas_answers_what_each_widget_answers(
    client, session, acting_user, monkeypatch
):
    author, _ = await _author_with_tasks(session, acting_user)
    statements = (
        "SELECT count(*) AS n FROM tasks",
        "SELECT priority, count(*) AS n FROM tasks GROUP BY priority",
        "SELECT title, due_date, created_at FROM tasks ORDER BY due_date LIMIT 2",
        "SELECT title FROM tasks WHERE status.category = 'done'",
        "SELECT status.name AS s, count(*) AS n FROM tasks GROUP BY status.name ORDER BY s",
        "SELECT t.id, p.id FROM tasks AS t JOIN projects AS p ON p.id = t.project_id ORDER BY t.id",
        "SELECT count(*) AS n FROM projects",
        # A running total, as the builder writes one.
        "SELECT date_trunc('day', due_date) AS day, "
        "sum(count(*)) OVER (ORDER BY date_trunc('day', due_date)) AS total "
        "FROM tasks GROUP BY 1 ORDER BY 1",
        # A frame counted in days: its offset has to reach Postgres as written.
        "SELECT title, count(*) OVER (ORDER BY due_date "
        "RANGE BETWEEN '1 day' PRECEDING AND CURRENT ROW) AS near "
        "FROM tasks ORDER BY due_date",
        # A window repeating an output grouped by its alias.
        "SELECT priority = 'high' AS hot, "
        "sum(count(*)) OVER (ORDER BY priority = 'high') AS t "
        "FROM tasks GROUP BY hot",
    )
    dashboard_id = await _canvas(client, author, *statements)

    # Answered by the compiled statement, not by the widget-at-a-time fallback,
    # which would agree with the comparison below by construction.
    async def fell_back(*_args, **_kwargs):
        raise AssertionError("the canvas fell back to one widget at a time")

    with monkeypatch.context() as patched:
        patched.setattr(executor, "execute", fell_back)
        canvas = await _data(client, author, dashboard_id)

    assert set(canvas) == {f"w{index + 1}" for index in range(len(statements))}
    for index, sql in enumerate(statements):
        entry = canvas[f"w{index + 1}"]
        assert entry["error"] is None, (sql, entry)
        assert entry["result"] == await _one(client, author, sql)
    assert canvas["w1"]["result"]["rows"] == [[3]]
    assert [row[1] for row in canvas["w8"]["result"]["rows"]] == [1, 2, 3]
    assert [row[1] for row in canvas["w9"]["result"]["rows"]] == [1, 2, 2]


async def test_a_reader_sees_their_own_rows_or_the_initiatives(
    client, session, acting_user
):
    author, project = await _author_with_tasks(session, acting_user)
    reader = await acting_user(
        guild_role=CommunityRole.member,
        guild=author.guild,
        initiative=author.initiative,
        initiative_role="member",
    )
    dashboard_id = await _canvas(
        client,
        author,
        "SELECT count(*) AS n FROM tasks",
        "SELECT count(*) AS n FROM tasks WHERE status.category = 'done'",
    )

    before = await _data(client, reader, dashboard_id)
    assert [before[w]["result"]["rows"] for w in ("w1", "w2")] == [[[0]], [[0]]]

    shared = await client.put(
        author.g(f"/dashboards/{dashboard_id}/view-mode"),
        json={"mode": "initiative"},
        headers=author.headers,
    )
    assert shared.status_code == 200, shared.text

    after = await _data(client, reader, dashboard_id)
    assert [after[w]["result"]["rows"] for w in ("w1", "w2")] == [[[3]], [[1]]]


async def test_a_property_is_reported_across_the_initiative(
    client, session, acting_user
):
    """A property is the initiative's, so its values add up whatever carries
    them. Another initiative's property of the same name stays out."""
    author, project = await _author_with_tasks(session, acting_user)
    points = await create_property_definition(
        session, author.initiative, name="Points", type=MetadataType.number
    )
    task = await create_task(session, project, title="Pointed")
    queue = await create_queue(session, author.initiative, author.user)
    await create_property_value(session, task, points, value_number=5)
    await create_property_value(session, queue, points, value_number=3)

    elsewhere = await create_initiative(session, author.guild, author.user)
    elsewhere_points = await create_property_definition(
        session, elsewhere, name="Points", type=MetadataType.number
    )
    elsewhere_project = await create_project(session, elsewhere, author.user)
    elsewhere_task = await create_task(session, elsewhere_project)
    await create_property_value(
        session, elsewhere_task, elsewhere_points, value_number=100
    )

    result = await _one(
        client,
        author,
        "SELECT property.name AS p, sum(value_number) AS total "
        "FROM metadata_values GROUP BY property.name",
    )
    assert [(name, float(total)) for name, total in result["rows"]] == [("Points", 8.0)]

    releases = await create_property_definition(
        session, author.initiative, name="Releases", type=MetadataType.multi_select
    )
    await create_property_value(session, task, releases, value_json=["a", "b"])
    choices = await _one(
        client,
        author,
        "SELECT value_json AS choices FROM metadata_values "
        "WHERE property.name = 'Releases'",
    )
    assert choices["rows"] == [['["a", "b"]']]
    one_choice = await _one(
        client,
        author,
        "SELECT count(*) AS n FROM metadata_values WHERE value_json @> '[\"b\"]'",
    )
    assert one_choice["rows"] == [[1]]


async def test_a_widget_that_fails_does_not_blank_the_canvas(
    client, session, acting_user
):
    author, _ = await _author_with_tasks(session, acting_user)
    dashboard_id = await _canvas(
        client,
        author,
        "SELECT count(*) AS n FROM tasks",
        "SELECT 1 / (count(*) - count(*)) AS broken FROM tasks",
    )

    canvas = await _data(client, author, dashboard_id)

    assert canvas["w1"]["result"]["rows"] == [[3]]
    assert canvas["w2"] == {"result": None, "error": QueryMessages.EXECUTION_FAILED}


async def test_a_guild_with_no_free_slot_refuses_the_canvas(
    client, session, acting_user, monkeypatch
):
    author, _ = await _author_with_tasks(session, acting_user)
    dashboard_id = await _canvas(client, author, "SELECT count(*) AS n FROM tasks")

    async def taken(_connection, _guild_id):
        return False

    monkeypatch.setattr(executor, "_claim_a_slot", taken)
    response = await client.get(
        author.g(f"/dashboards/{dashboard_id}/data"), headers=author.headers
    )
    assert response.status_code == 429
    assert response.json()["detail"] == QueryMessages.BUSY
