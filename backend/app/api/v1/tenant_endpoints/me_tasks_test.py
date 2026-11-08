"""
Integration tests for the assigned-tasks /me view.

Tests GET /api/v1/me/tasks, which returns tasks ASSIGNED to the current user
across all guilds they belong to, or with ``created=true`` the tasks they
created.
"""

import json

from httpx import AsyncClient
from sqlalchemy import update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.tenant.task_types import get_default_type
from app.testing import guild_of
from app.models.platform.guild import CommunityRole
from app.models.tenant.task import Task, TaskAssignee, TaskPriority
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_project,
    create_resource_grant,
    create_user,
    get_auth_headers,
)
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.testing import route_as


async def _create_task(
    session,
    project,
    title="Test Task",
    *,
    created_by=None,
    due_date=None,
    start_date=None,
    priority=TaskPriority.medium,
):
    """Create a task in ``project``'s guild schema."""
    from app.services.tenant import task_statuses as task_statuses_service

    # Route status setup + the task into the project's guild schema; a prior
    # setup may have left the search_path on a different guild.
    await route_as(session, user_id=created_by, guild_id=guild_of(project))
    await task_statuses_service.ensure_default_statuses(
        session, project.id, locale="en"
    )
    status = await task_statuses_service.get_default_status(session, project.id)

    task = Task(
        title=title,
        project_id=project.id,
        task_status_id=status.id,
        task_type_id=(await get_default_type(session, project.id)).id,
        created_by=created_by,
        due_date=due_date,
        start_date=start_date,
        priority=priority,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def _assign(session, task, user_id):
    """Assign ``task`` to ``user_id``. Route the write as the task's creator (a
    member with initiative write access) — the task_assignees RLS checks the
    ACTOR's access, and the assignee need not be an initiative member."""

    await route_as(session, user_id=task.created_by, guild_id=guild_of(task))
    session.add(TaskAssignee(task_id=task.id, user_id=user_id))
    await session.commit()


async def _setup_guild_with_project(session, user, *, guild_name="Test Guild"):
    """Create a guild, membership, initiative, and project for the user."""
    guild = await create_guild(session, creator=user, name=guild_name)
    await create_guild_membership(
        session, user=user, guild=guild, role=CommunityRole.admin
    )
    initiative = await create_initiative(session, guild, user, name="Initiative")
    project = await create_project(session, initiative, user, name="Project")
    return guild, initiative, project


async def test_list_my_tasks_returns_assigned(
    client: AsyncClient, session: AsyncSession
):
    """GET /me/tasks returns tasks assigned to the current user."""
    user = await create_user(session, email="user@example.com")
    guild, _, project = await _setup_guild_with_project(session, user)

    task1 = await _create_task(session, project, "Assigned 1", created_by=user.id)
    task2 = await _create_task(session, project, "Assigned 2", created_by=user.id)
    await _assign(session, task1, user.id)
    await _assign(session, task2, user.id)

    headers = get_auth_headers(user)
    response = await client.get("/api/v1/me/tasks", headers=headers)

    assert response.status_code == 200, response.text
    task_ids = {t["id"] for t in response.json()["items"]}
    assert task1.id in task_ids
    assert task2.id in task_ids


async def test_list_my_tasks_assigned_or_created(
    client: AsyncClient, session: AsyncSession
):
    """GET /me/tasks lists the caller's assigned tasks; ``created=true`` lists
    the ones they created instead, whoever they are assigned to."""
    user = await create_user(session, email="user@example.com")
    other = await create_user(session, email="other@example.com")
    guild, initiative, project = await _setup_guild_with_project(session, user)
    await create_guild_membership(session, user=other, guild=guild)
    await create_initiative_member(session, initiative, other)
    await create_resource_grant(
        session, project, level=ResourceAccessLevel.write, user=other
    )

    mine = await _create_task(session, project, "Mine", created_by=user.id)
    await _assign(session, mine, user.id)
    created_not_assigned = await _create_task(
        session, project, "Created not assigned", created_by=user.id
    )
    assigned_to_other = await _create_task(
        session, project, "Assigned to other", created_by=user.id
    )
    await _assign(session, assigned_to_other, other.id)
    from_other = await _create_task(session, project, "From other", created_by=other.id)
    await _assign(session, from_other, user.id)
    # A row from before ``created_by`` existed belongs to nobody's created view.
    legacy = await _create_task(session, project, "Legacy", created_by=user.id)
    await session.exec(update(Task).where(Task.id == legacy.id).values(created_by=None))
    await session.commit()

    headers = get_auth_headers(user)
    assigned = await client.get("/api/v1/me/tasks", headers=headers)
    assert assigned.status_code == 200, assigned.text
    assert {t["id"] for t in assigned.json()["items"]} == {mine.id, from_other.id}

    created = await client.get("/api/v1/me/tasks?created=true", headers=headers)
    assert created.status_code == 200, created.text
    assert {t["id"] for t in created.json()["items"]} == {
        mine.id,
        created_not_assigned.id,
        assigned_to_other.id,
    }


async def test_admin_sees_assigned_task_in_non_member_initiative(
    client: AsyncClient, session: AsyncSession
):
    """A guild ADMIN has default access to all guild content, so /me/tasks shows
    a task assigned to them even in an initiative they were never added to as a
    member. Regression: ``gather_across_guilds`` must route each guild with the
    user's role so ``initiative_access``'s admin leg fires (without it the admin
    only got the member leg and the task was hidden)."""
    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session, creator=admin, name="Guild")
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )
    await create_guild_membership(
        session, user=member, guild=guild, role=CommunityRole.member
    )

    # Initiative + project owned by the member; the admin is NOT a member of it.
    initiative = await create_initiative(
        session, guild, member, name="Member Initiative"
    )
    project = await create_project(session, initiative, member, name="Member Project")

    task = await _create_task(
        session, project, "Assigned to admin", created_by=member.id
    )
    await _assign(session, task, admin.id)

    headers = get_auth_headers(admin)
    response = await client.get("/api/v1/me/tasks", headers=headers)

    assert response.status_code == 200, response.text
    task_ids = {t["id"] for t in response.json()["items"]}
    assert task.id in task_ids, (
        "Guild admin should see a task assigned to them even in an initiative "
        "they aren't a member of (initiative_access admin leg)."
    )


async def test_list_my_tasks_priority_filter(
    client: AsyncClient, session: AsyncSession
):
    """GET /me/tasks respects priority filters."""
    user = await create_user(session, email="user@example.com")
    guild, _, project = await _setup_guild_with_project(session, user)

    high = await _create_task(session, project, "High", created_by=user.id)
    high.priority = TaskPriority.high
    session.add(high)
    low = await _create_task(session, project, "Low", created_by=user.id)
    low.priority = TaskPriority.low
    session.add(low)
    await session.commit()
    await _assign(session, high, user.id)
    await _assign(session, low, user.id)

    headers = get_auth_headers(user)
    conditions = json.dumps([{"field": "priority", "op": "in_", "value": ["high"]}])
    response = await client.get(
        f"/api/v1/me/tasks?conditions={conditions}", headers=headers
    )

    assert response.status_code == 200, response.text
    task_ids = {t["id"] for t in response.json()["items"]}
    assert high.id in task_ids
    assert low.id not in task_ids


async def test_list_my_tasks_due_date_filter_across_guilds(
    client: AsyncClient, session: AsyncSession
):
    """GET /me/tasks honors a due_date condition across every guild.

    Regression: the cross-guild aggregate only applied a fixed whitelist of
    extracted scalars and silently dropped every other field, so a ``due_date``
    filter returned the caller's entire assigned set. The aggregate now applies
    the full condition set per guild via apply_filters, matching the
    guild-scoped list.
    """
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    overdue = now - timedelta(days=2)
    upcoming = now + timedelta(days=10)

    user = await create_user(session, email="user@example.com")
    guild1, _, project1 = await _setup_guild_with_project(
        session, user, guild_name="Guild 1"
    )
    _guild2, _, project2 = await _setup_guild_with_project(
        session, user, guild_name="Guild 2"
    )

    # One overdue + one upcoming in each guild, so a working filter must reach
    # across guilds and cannot pass by only matching one guild's rows.
    g1_overdue = await _create_task(
        session, project1, "g1 overdue", created_by=user.id, due_date=overdue
    )
    g1_upcoming = await _create_task(
        session, project1, "g1 upcoming", created_by=user.id, due_date=upcoming
    )
    g2_overdue = await _create_task(
        session, project2, "g2 overdue", created_by=user.id, due_date=overdue
    )
    g2_upcoming = await _create_task(
        session, project2, "g2 upcoming", created_by=user.id, due_date=upcoming
    )
    for task in (g1_overdue, g1_upcoming, g2_overdue, g2_upcoming):
        await _assign(session, task, user.id)

    headers = get_auth_headers(user)
    conditions = json.dumps(
        [{"field": "due_date", "op": "lt", "value": now.isoformat()}]
    )
    # Pass via params so httpx URL-encodes the "+" in the ISO offset.
    response = await client.get(
        "/api/v1/me/tasks", params={"conditions": conditions}, headers=headers
    )

    assert response.status_code == 200, response.text
    task_ids = {t["id"] for t in response.json()["items"]}
    assert task_ids == {g1_overdue.id, g2_overdue.id}


async def test_list_my_tasks_guild_ids_filter(
    client: AsyncClient, session: AsyncSession
):
    """GET /me/tasks with the community_ids filter restricts to the named guilds.

    Regression: the frontend previously sent ``field: "guild_id"`` (singular)
    but the endpoint extracts ``community_ids`` (plural, mirroring initiative_ids);
    the singular silently no-op'd and tasks from every guild leaked in.
    """
    user = await create_user(session, email="user@example.com")
    guild1, _, project1 = await _setup_guild_with_project(
        session, user, guild_name="Guild 1"
    )
    guild2, _, project2 = await _setup_guild_with_project(
        session, user, guild_name="Guild 2"
    )

    task1 = await _create_task(session, project1, "Task in Guild 1", created_by=user.id)
    task2 = await _create_task(session, project2, "Task in Guild 2", created_by=user.id)
    await _assign(session, task1, user.id)
    await _assign(session, task2, user.id)

    headers = get_auth_headers(user)

    def keyed(resp):
        # Task ids are per-guild (per-schema); key by (guild_id, id).
        return {(t["community_id"], t["id"]) for t in resp.json()["items"]}

    # No filter: assigned tasks from BOTH guilds are aggregated.
    response = await client.get("/api/v1/me/tasks", headers=headers)
    assert response.status_code == 200, response.text
    found = keyed(response)
    assert (guild1.id, task1.id) in found
    assert (guild2.id, task2.id) in found

    # Filtered to guild1: only guild1's task.
    conditions = json.dumps(
        [{"field": "community_ids", "op": "in_", "value": [guild1.id]}]
    )
    response = await client.get(
        f"/api/v1/me/tasks?conditions={conditions}", headers=headers
    )
    assert response.status_code == 200, response.text
    found = keyed(response)
    assert (guild1.id, task1.id) in found
    assert (guild2.id, task2.id) not in found


async def test_list_my_tasks_pagination(client: AsyncClient, session: AsyncSession):
    """GET /me/tasks supports pagination."""
    user = await create_user(session, email="user@example.com")
    guild, _, project = await _setup_guild_with_project(session, user)

    for i in range(3):
        task = await _create_task(session, project, f"Task {i}", created_by=user.id)
        await _assign(session, task, user.id)

    headers = get_auth_headers(user)

    # Page 1 with page_size=2
    response = await client.get("/api/v1/me/tasks?page=1&page_size=2", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["items"]) == 2
    assert data["total_count"] == 3
    assert data["has_next"] is True

    # Page 2
    response = await client.get("/api/v1/me/tasks?page=2&page_size=2", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["items"]) == 1
    assert data["has_next"] is False


async def test_list_my_tasks_counts_comments_per_row(
    client: AsyncClient, session: AsyncSession
):
    """Each row carries its own comment count.

    The count is selected alongside the task rather than fetched for the page as
    a group, so it is worth pinning that it lands on the right row — including
    the zero for a task nobody has commented on.
    """
    from app.testing.factories import create_comment

    user = await create_user(session, email="user@example.com")
    _guild, _, project = await _setup_guild_with_project(session, user)

    talked_about = await _create_task(
        session, project, "talked about", created_by=user.id
    )
    quiet = await _create_task(session, project, "quiet", created_by=user.id)
    for task in (talked_about, quiet):
        await _assign(session, task, user.id)
    for _ in range(3):
        await create_comment(session, user, task=talked_about)

    response = await client.get("/api/v1/me/tasks", headers=get_auth_headers(user))
    assert response.status_code == 200, response.text
    counts = {t["title"]: t["comment_count"] for t in response.json()["items"]}
    assert counts == {"talked about": 3, "quiet": 0}


async def test_list_my_tasks_paged_page_interleaves_guilds(
    client: AsyncClient, session: AsyncSession
):
    """A page drawn from several guilds comes back in the sort's order.

    The endpoint orders the whole matching set from lightweight per-guild rows
    and then loads only the ids on the requested page — so the rows are fetched
    guild by guild and have to be put back into the global order, and a guild
    that contributes nothing to this page must still count toward
    ``total_count``. Interleaving the due dates across two guilds means guild
    order and sort order disagree on every page.
    """
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)

    user = await create_user(session, email="user@example.com")
    _guild1, _, project1 = await _setup_guild_with_project(
        session, user, guild_name="Guild 1"
    )
    _guild2, _, project2 = await _setup_guild_with_project(
        session, user, guild_name="Guild 2"
    )

    # The soonest task is in the LATER guild, so concatenating each guild's rows
    # in guild order gets every page wrong: guild 2 holds days 1 and 3, guild 1
    # days 2 and 4.
    plan = [
        (project2, "first", 1),
        (project1, "second", 2),
        (project2, "third", 3),
        (project1, "fourth", 4),
    ]
    for project, title, days in plan:
        task = await _create_task(
            session,
            project,
            title,
            created_by=user.id,
            due_date=now + timedelta(days=days),
        )
        await _assign(session, task, user.id)

    headers = get_auth_headers(user)
    sorting = json.dumps([{"field": "due_date", "dir": "asc"}])

    response = await client.get(
        f"/api/v1/me/tasks?sorting={sorting}&page=1&page_size=2&tz=UTC", headers=headers
    )
    assert response.status_code == 200, response.text
    first = response.json()
    assert [t["title"] for t in first["items"]] == ["first", "second"]
    assert first["total_count"] == 4
    assert first["has_next"] is True

    response = await client.get(
        f"/api/v1/me/tasks?sorting={sorting}&page=2&page_size=2&tz=UTC", headers=headers
    )
    assert response.status_code == 200, response.text
    second = response.json()
    assert [t["title"] for t in second["items"]] == ["third", "fourth"]
    assert second["total_count"] == 4
    assert second["has_next"] is False

    # The hydrated rows carry everything the list shape promises, including the
    # relationship-backed fields the second pass is responsible for loading.
    row = second["items"][0]
    assert row["project_id"] == project2.id
    assert row["task_status"]["id"] is not None
    assert row["community_name"] == "Guild 2"


async def test_list_my_tasks_page_from_one_guild_only(
    client: AsyncClient, session: AsyncSession
):
    """Guilds off the requested page are skipped, and still counted.

    The hydration pass visits only the guilds holding ids on this page. A guild
    whose tasks all sort onto a later page must contribute to ``total_count``
    without appearing in ``items``.
    """
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)

    user = await create_user(session, email="user@example.com")
    _guild1, _, project1 = await _setup_guild_with_project(
        session, user, guild_name="Guild 1"
    )
    _guild2, _, project2 = await _setup_guild_with_project(
        session, user, guild_name="Guild 2"
    )

    for title, days in (("g1 soon", 1), ("g1 next", 2)):
        task = await _create_task(
            session,
            project1,
            title,
            created_by=user.id,
            due_date=now + timedelta(days=days),
        )
        await _assign(session, task, user.id)
    for title, days in (("g2 late", 30), ("g2 latest", 60)):
        task = await _create_task(
            session,
            project2,
            title,
            created_by=user.id,
            due_date=now + timedelta(days=days),
        )
        await _assign(session, task, user.id)

    headers = get_auth_headers(user)
    sorting = json.dumps([{"field": "due_date", "dir": "asc"}])
    response = await client.get(
        f"/api/v1/me/tasks?sorting={sorting}&page=1&page_size=2&tz=UTC", headers=headers
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert [t["title"] for t in data["items"]] == ["g1 soon", "g1 next"]
    assert {t["community_name"] for t in data["items"]} == {"Guild 1"}
    assert data["total_count"] == 4
    assert data["has_next"] is True


async def test_list_my_tasks_date_group_sorted_across_guilds(
    client: AsyncClient, session: AsyncSession
):
    """GET /me/tasks sorts by date_group then due_date across ALL guilds.

    Regression: per-guild SQL ordering was concatenated in guild-id order, so a
    later guild's "today" task could appear after an earlier guild's "later"
    task. The merged set must be globally re-sorted before pagination.
    """
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    overdue = now - timedelta(days=2)
    this_week = now + timedelta(days=3)
    later = now + timedelta(days=60)

    user = await create_user(session, email="user@example.com")
    guild1, _, project1 = await _setup_guild_with_project(
        session, user, guild_name="Guild 1"
    )
    guild2, _, project2 = await _setup_guild_with_project(
        session, user, guild_name="Guild 2"
    )

    # Interleave date groups so any per-guild-only ordering is detectably wrong:
    # guild1 holds overdue + later; guild2 holds today + this-week.
    g1_overdue = await _create_task(
        session, project1, "g1 overdue", created_by=user.id, due_date=overdue
    )
    g1_later = await _create_task(
        session, project1, "g1 later", created_by=user.id, due_date=later
    )
    # "Today" via start_date (start <= today → group 1) rather than a narrow
    # future due_date, so the classification is stable at any time of day —
    # including right around midnight UTC.
    g2_today = await _create_task(
        session, project2, "g2 today", created_by=user.id, start_date=now
    )
    g2_week = await _create_task(
        session, project2, "g2 this week", created_by=user.id, due_date=this_week
    )
    for task in (g1_overdue, g1_later, g2_today, g2_week):
        await _assign(session, task, user.id)

    headers = get_auth_headers(user)
    sorting = json.dumps(
        [{"field": "date_group", "dir": "asc"}, {"field": "due_date", "dir": "asc"}]
    )
    response = await client.get(
        f"/api/v1/me/tasks?sorting={sorting}&tz=UTC", headers=headers
    )
    assert response.status_code == 200, response.text
    titles = [t["title"] for t in response.json()["items"]]
    # Overdue → today → this week → later, regardless of which guild owns each.
    assert titles == ["g1 overdue", "g2 today", "g2 this week", "g1 later"]


async def test_list_my_tasks_priority_sorted_desc_across_guilds(
    client: AsyncClient, session: AsyncSession
):
    """GET /me/tasks sorts by priority across guilds in PG enum order (low→urgent),
    not alphabetically — descending therefore yields urgent → high → medium → low.
    """
    user = await create_user(session, email="user@example.com")
    guild1, _, project1 = await _setup_guild_with_project(
        session, user, guild_name="Guild 1"
    )
    guild2, _, project2 = await _setup_guild_with_project(
        session, user, guild_name="Guild 2"
    )

    # Split priorities across both guilds so per-guild-only ordering is wrong.
    g1_low = await _create_task(
        session, project1, "low", created_by=user.id, priority=TaskPriority.low
    )
    g1_high = await _create_task(
        session, project1, "high", created_by=user.id, priority=TaskPriority.high
    )
    g2_medium = await _create_task(
        session, project2, "medium", created_by=user.id, priority=TaskPriority.medium
    )
    g2_urgent = await _create_task(
        session, project2, "urgent", created_by=user.id, priority=TaskPriority.urgent
    )
    for task in (g1_low, g1_high, g2_medium, g2_urgent):
        await _assign(session, task, user.id)

    headers = get_auth_headers(user)
    sorting = json.dumps([{"field": "priority", "dir": "desc"}])
    response = await client.get(f"/api/v1/me/tasks?sorting={sorting}", headers=headers)
    assert response.status_code == 200, response.text
    titles = [t["title"] for t in response.json()["items"]]
    assert titles == ["urgent", "high", "medium", "low"]


async def test_list_my_tasks_property_value_is_null_filter(
    client: AsyncClient, session: AsyncSession
):
    """GET /me/tasks filters by a custom property value.

    Regression: the property definition needed to compile the filter lives in
    the guild schema, but the /me session runs in the ``public`` search_path.
    Loading definitions off that un-routed session raised
    ``UndefinedTableError: relation "property_definitions" does not exist`` and
    the endpoint 500'd; definitions must be loaded per-guild.
    """
    from app.models.tenant.metadata import MetadataType
    from app.testing.factories import (
        create_property_definition,
        create_property_value,
    )

    user = await create_user(session, email="user@example.com")
    guild, initiative, project = await _setup_guild_with_project(session, user)

    definition = await create_property_definition(
        session, initiative, name="Owner note", type=MetadataType.text
    )

    with_value = await _create_task(session, project, "Has value", created_by=user.id)
    without_value = await _create_task(session, project, "No value", created_by=user.id)
    await _assign(session, with_value, user.id)
    await _assign(session, without_value, user.id)
    await create_property_value(session, with_value, definition, value_text="something")

    headers = get_auth_headers(user)
    conditions = json.dumps(
        [
            {
                "field": "property_values",
                "op": "is_null",
                "value": {"property_id": definition.id, "value": True},
            }
        ]
    )
    response = await client.get(
        f"/api/v1/me/tasks?conditions={conditions}", headers=headers
    )

    assert response.status_code == 200, response.text
    task_ids = {t["id"] for t in response.json()["items"]}
    assert without_value.id in task_ids
    assert with_value.id not in task_ids


async def test_list_my_tasks_property_filter_spans_guilds(
    client: AsyncClient, session: AsyncSession
):
    """GET /me/tasks applies a property_values filter across EVERY guild.

    ``_load_property_definitions_across_guilds`` routes into each guild's schema
    to resolve the definition, then the compiled ``property_id`` predicate runs
    per-guild. A definition id is unique only within a schema, so two guilds
    typically both assign the same id to their first definition; the loader
    merges first-id-wins and the filter must still resolve correctly in both.
    """
    from app.models.tenant.metadata import MetadataType
    from app.testing.factories import (
        create_property_definition,
        create_property_value,
    )

    user = await create_user(session, email="user@example.com")
    guild1, initiative1, project1 = await _setup_guild_with_project(
        session, user, guild_name="Guild 1"
    )
    guild2, initiative2, project2 = await _setup_guild_with_project(
        session, user, guild_name="Guild 2"
    )

    def1 = await create_property_definition(
        session, initiative1, name="Note", type=MetadataType.text
    )
    def2 = await create_property_definition(
        session, initiative2, name="Note", type=MetadataType.text
    )
    # Per-schema sequences: the first definition in each guild shares an id. The
    # filter carries one property_id, so this collision is what makes a single
    # cross-guild filter meaningful (and exercises the first-id-wins merge).
    assert def1.id == def2.id

    # Build each guild's rows fully before moving on: the assign/value writes
    # route the session's ROLE into that guild, so interleaving would leave a
    # write pointed at the wrong guild's schema.
    g1_has = await _create_task(session, project1, "g1 has", created_by=user.id)
    g1_empty = await _create_task(session, project1, "g1 empty", created_by=user.id)
    await _assign(session, g1_has, user.id)
    await _assign(session, g1_empty, user.id)
    await create_property_value(session, g1_has, def1, value_text="x")

    g2_has = await _create_task(session, project2, "g2 has", created_by=user.id)
    g2_empty = await _create_task(session, project2, "g2 empty", created_by=user.id)
    await _assign(session, g2_has, user.id)
    await _assign(session, g2_empty, user.id)
    await create_property_value(session, g2_has, def2, value_text="y")

    headers = get_auth_headers(user)
    conditions = json.dumps(
        [
            {
                "field": "property_values",
                "op": "is_null",
                "value": {"property_id": def1.id, "value": True},
            }
        ]
    )
    response = await client.get(
        f"/api/v1/me/tasks?conditions={conditions}", headers=headers
    )

    assert response.status_code == 200, response.text
    # Key by (guild_id, id): ids collide across schemas.
    found = {(t["community_id"], t["id"]) for t in response.json()["items"]}
    assert (guild1.id, g1_empty.id) in found
    assert (guild2.id, g2_empty.id) in found
    assert (guild1.id, g1_has.id) not in found
    assert (guild2.id, g2_has.id) not in found


# --- Focus summary query -----------------------------------------------------
# The My Tasks "Focus" section sends one nested OR group. These lock the wire
# format in: a silent 400 (or a silently-dropped leg) would empty the section
# with no visible cause.


async def test_my_tasks_accepts_nested_or_conditions(
    client: AsyncClient, session: AsyncSession, acting_user
):
    from datetime import datetime, timedelta, timezone

    from app.models.tenant.task import TaskStatusCategory
    from app.testing.factories import create_task

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    now = datetime.now(timezone.utc)

    due_soon = await create_task(
        session,
        a.project,
        title="Due soon",
        assignees=[a.user],
        due_date=now + timedelta(hours=6),
    )
    urgent_undated = await create_task(
        session,
        a.project,
        title="Urgent but undated",
        assignees=[a.user],
        priority=TaskPriority.urgent,
    )
    finished_today = await create_task(
        session,
        a.project,
        title="Finished today",
        assignees=[a.user],
        status_category=TaskStatusCategory.done,
    )
    # Neither urgent nor due soon: must not be swept in.
    await create_task(
        session,
        a.project,
        title="Someday",
        assignees=[a.user],
        due_date=now + timedelta(days=90),
    )

    still_open = {
        "field": "status_category",
        "op": "in_",
        "value": ["todo", "in_progress"],
    }
    # Two group levels, not three: the parser caps nesting at
    # ``_MAX_GROUP_DEPTH``, so "open AND (due OR urgent)" is distributed into
    # separate AND legs rather than nesting an OR inside the AND.
    conditions = [
        {
            "logic": "or",
            "conditions": [
                {
                    "logic": "and",
                    "conditions": [
                        still_open,
                        {
                            "field": "due_date",
                            "op": "lte",
                            "value": (now + timedelta(days=2)).isoformat(),
                        },
                    ],
                },
                {
                    "logic": "and",
                    "conditions": [
                        still_open,
                        {"field": "priority", "op": "in_", "value": ["urgent", "high"]},
                    ],
                },
                {
                    "logic": "and",
                    "conditions": [
                        {"field": "status_category", "op": "in_", "value": ["done"]},
                        {
                            "field": "completed_at",
                            "op": "gte",
                            "value": (now - timedelta(hours=12)).isoformat(),
                        },
                    ],
                },
            ],
        }
    ]

    response = await client.get(
        "/api/v1/me/tasks",
        params={"conditions": json.dumps(conditions), "page_size": 100},
        headers=a.headers,
    )

    assert response.status_code == 200, response.text
    titles = {item["title"] for item in response.json()["items"]}
    assert titles == {"Due soon", "Urgent but undated", "Finished today"}
    assert {due_soon.id, urgent_undated.id, finished_today.id}


async def test_my_tasks_exposes_completed_at(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The section reads completed_at off the list payload to decide what
    counts as finished today."""
    from app.models.tenant.task import TaskStatusCategory
    from app.testing.factories import create_task

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await create_task(
        session,
        a.project,
        title="Finished",
        assignees=[a.user],
        status_category=TaskStatusCategory.done,
    )

    response = await client.get("/api/v1/me/tasks", headers=a.headers)

    assert response.status_code == 200, response.text
    item = next(i for i in response.json()["items"] if i["title"] == "Finished")
    assert item["completed_at"] is not None
