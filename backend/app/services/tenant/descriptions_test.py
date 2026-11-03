"""Saving a description: the edges it makes and the people it tells.

Driven through the task endpoints, because that is where a description is
saved — create, edit, duplicate — and each has its own answer to "who hears
about it".
"""

from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.models.platform.guild import CommunityRole
from app.models.platform.notification import Notification, NotificationType
from app.models.tenant.relationship import EntityRelationship
from app.services.tenant.relationships import Endpoint
from app.services.tenant.descriptions import newly_mentioned
from app.testing import (
    create_file,
    create_resource_grant,
    create_task,
    create_user,
    drain_notices,
)
from app.testing.schema_harness import route_session_to_guild


def test_only_a_name_the_last_save_did_not_have_is_new():
    assert newly_mentioned("@[Ada](4) and @[Bo](5)", "@[Ada](4)") == {5}
    assert newly_mentioned("@[Ada](4)", "@[Ada](4) and @[Bo](5)") == set()
    assert newly_mentioned("@[Ada](4)", None) == {4}
    assert newly_mentioned(None, "@[Ada](4)") == set()


async def _mentions_for(session: AsyncSession, user_id: int) -> list[dict]:
    await drain_notices()
    rows = (
        await session.exec(
            select(Notification).where(
                Notification.user_id == user_id,
                Notification.type == NotificationType.mention,
            )
        )
    ).all()
    return [row.data for row in rows]


async def _references(session: AsyncSession, guild_id: int, source: Endpoint) -> set:
    await route_session_to_guild(session, guild_id)
    rows = await session.exec(
        select(EntityRelationship.target_type, EntityRelationship.target_id).where(
            EntityRelationship.source_node == source.node,
            EntityRelationship.relationship_type == RelationshipType.references.value,
            EntityRelationship.removed_at.is_(None),  # type: ignore[union-attr]
        )
    )
    return set(rows.all())


async def _workspace(acting_user, session: AsyncSession):
    """A writer, and a teammate in the same initiative for them to name, in a
    project every member of it can read."""
    writer = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    teammate = await acting_user(
        guild_role=CommunityRole.member,
        guild=writer.guild,
        initiative=writer.initiative,
        initiative_role="member",
    )
    await create_resource_grant(session, writer.project, all_initiative_members=True)
    return writer, teammate


async def test_creating_a_task_tells_whoever_its_description_names(
    client: AsyncClient, session: AsyncSession, acting_user
):
    writer, teammate = await _workspace(acting_user, session)

    response = await client.post(
        writer.g("/tasks/"),
        headers=writer.headers,
        json={
            "title": "Ship it",
            "project_id": writer.project.id,
            "description": f"Pair with @[Tea M]({teammate.user.id})",
        },
    )
    assert response.status_code == 201, response.text
    task_id = response.json()["id"]

    [notice] = await _mentions_for(session, teammate.user.id)
    assert (notice["entity_type"], notice["entity_id"]) == ("task", task_id)
    # The title is guild content: the bell reads it back by kind and id.
    assert "entity_name" not in notice
    assert notice["target_path"] == f"/go/task/{task_id}"


async def test_an_edit_tells_only_the_people_it_adds(
    client: AsyncClient, session: AsyncSession, acting_user
):
    writer, teammate = await _workspace(acting_user, session)
    newcomer = await acting_user(
        guild_role=CommunityRole.member,
        guild=writer.guild,
        initiative=writer.initiative,
        initiative_role="member",
    )
    task = await create_task(
        session,
        writer.project,
        description=f"Pair with @[Tea M]({teammate.user.id})",
    )
    await session.commit()

    response = await client.patch(
        writer.g(f"/tasks/{task.id}"),
        headers=writer.headers,
        json={
            "description": (
                f"Pair with @[Tea M]({teammate.user.id}) and @[]({newcomer.user.id})"
            )
        },
    )
    assert response.status_code == 200, response.text
    # Stored by id alone, whoever's mention it is and however it was written.
    assert response.json()["description"] == (
        f"Pair with @[]({teammate.user.id}) and @[]({newcomer.user.id})"
    )

    assert await _mentions_for(session, teammate.user.id) == []
    assert len(await _mentions_for(session, newcomer.user.id)) == 1


async def test_nobody_outside_the_initiative_is_told(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The picker offers nobody else, and the notice would name the task."""
    writer = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    outsider = await create_user(session, email="outsider@example.com")
    await session.commit()

    response = await client.post(
        writer.g("/tasks/"),
        headers=writer.headers,
        json={
            "title": "Private",
            "project_id": writer.project.id,
            "description": f"cc @[Out Sider]({outsider.id})",
        },
    )
    assert response.status_code == 201, response.text

    assert await _mentions_for(session, outsider.id) == []


async def test_naming_yourself_tells_nobody(
    client: AsyncClient, session: AsyncSession, acting_user
):
    writer = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )

    response = await client.post(
        writer.g("/tasks/"),
        headers=writer.headers,
        json={
            "title": "Note to self",
            "project_id": writer.project.id,
            "description": f"me: @[Me]({writer.user.id})",
        },
    )
    assert response.status_code == 201, response.text

    assert await _mentions_for(session, writer.user.id) == []


async def test_a_description_s_hash_becomes_the_task_s_reference(
    client: AsyncClient, session: AsyncSession, acting_user
):
    writer = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    doc = await create_file(session, writer.initiative, writer.user)
    task = await create_task(session, writer.project)
    await session.commit()

    response = await client.patch(
        writer.g(f"/tasks/{task.id}"),
        headers=writer.headers,
        json={"description": f"Spec: #file[Spec]({doc.id})"},
    )
    assert response.status_code == 200, response.text
    assert await _references(
        session, writer.guild.id, Endpoint(SearchEntityType.task, task.id)
    ) == {("file", doc.id)}

    # Writing the sentence out takes the edge with it.
    session.expunge_all()
    response = await client.patch(
        writer.g(f"/tasks/{task.id}"),
        headers=writer.headers,
        json={"description": "No spec after all"},
    )
    assert response.status_code == 200, response.text
    assert (
        await _references(
            session, writer.guild.id, Endpoint(SearchEntityType.task, task.id)
        )
        == set()
    )


async def test_a_duplicate_points_where_its_original_does_and_tells_nobody(
    client: AsyncClient, session: AsyncSession, acting_user
):
    writer, teammate = await _workspace(acting_user, session)
    doc = await create_file(session, writer.initiative, writer.user)
    task = await create_task(
        session,
        writer.project,
        description=f"@[Tea M]({teammate.user.id}) see #file[Spec]({doc.id})",
    )
    await session.commit()

    response = await client.post(
        writer.g(f"/tasks/{task.id}/duplicate"), headers=writer.headers
    )
    assert response.status_code in (200, 201), response.text
    copy_id = response.json()["id"]

    assert await _references(
        session, writer.guild.id, Endpoint(SearchEntityType.task, copy_id)
    ) == {("file", doc.id)}
    assert await _mentions_for(session, teammate.user.id) == []
