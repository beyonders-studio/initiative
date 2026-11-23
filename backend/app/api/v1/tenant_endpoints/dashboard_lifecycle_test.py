"""What a dashboard counts: never the trash, and archived work and templates
only when asked.

Deleted rows are left out of every statement a reader runs, whoever asks and
however the statement was written. Archived work and templates are left out by
the builder's starting filters, which an author can flip to include them or to
count only them.
"""

from __future__ import annotations

from app.models.platform.guild import CommunityRole
from app.services.tenant.view_as_test import (
    dashboards_on,
    make_dashboard,
    widget_rows,
)
from app.testing import create_project, create_task

NOT_ARCHIVED = {"field": "archived_at", "op": "is_null", "value": True}
NOT_TEMPLATE = {"field": "project.is_template", "op": "eq", "value": False}


async def count_tasks(client, actor, where: list) -> list:
    built = await client.post(
        actor.g("/query/build"),
        json={
            "dataset": "tasks",
            "columns": [{"field": "*", "aggregate": "count"}],
            "where": where,
        },
        headers=actor.headers,
    )
    assert built.status_code == 200, built.text
    dashboard_id = await make_dashboard(client, actor, built.json()["sql"])
    return await widget_rows(client, actor, dashboard_id)


async def an_initiative(session, acting_user):
    """One live project with two tasks, a template with one, and a project
    that will be archived with one."""
    actor = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await dashboards_on(session, actor.initiative)
    live = await create_project(session, actor.initiative, actor.user)
    first = await create_task(session, live)
    await create_task(session, live)
    template = await create_project(
        session, actor.initiative, actor.user, is_template=True
    )
    await create_task(session, template)
    shelved = await create_project(session, actor.initiative, actor.user)
    await create_task(session, shelved)
    return actor, live, first, shelved


async def test_deleted_work_is_never_counted(client, session, acting_user):
    actor, live, first, _ = await an_initiative(session, acting_user)
    assert await count_tasks(client, actor, []) == [[4]]

    assert (
        await client.delete(actor.g(f"/tasks/{first.id}"), headers=actor.headers)
    ).status_code == 204
    assert await count_tasks(client, actor, []) == [[3]]

    # A trashed project takes its tasks with it.
    assert (
        await client.delete(actor.g(f"/projects/{live.id}"), headers=actor.headers)
    ).status_code == 204
    assert await count_tasks(client, actor, []) == [[2]]


async def test_archived_work_and_templates_are_left_out_included_or_all_there_is(
    client, session, acting_user
):
    actor, _, _, shelved = await an_initiative(session, acting_user)
    # A second shelved task, so the archived and template groups differ in size.
    await create_task(session, shelved)
    archived = await client.post(
        actor.g(f"/archive/project/{shelved.id}"), headers=actor.headers
    )
    assert archived.status_code == 200, archived.text

    assert await count_tasks(client, actor, []) == [[5]]
    for condition, only, kept, left_out in (
        (NOT_ARCHIVED, False, 3, 2),
        (NOT_TEMPLATE, True, 4, 1),
    ):
        assert await count_tasks(client, actor, [condition]) == [[kept]]
        flipped = {**condition, "value": only}
        assert await count_tasks(client, actor, [flipped]) == [[left_out]]
