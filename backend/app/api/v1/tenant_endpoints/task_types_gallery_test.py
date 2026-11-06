"""Ready-made task types, what a type starts a task with, and copying types
between projects."""

from typing import Any, Optional

from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import CommunityRole
from app.models.platform.user import User
from app.models.tenant.metadata import MetadataDefinition, MetadataType
from app.models.tenant.tool_layout import ToolLayout
from app.services.tenant import task_types as task_types_service
from app.testing import Actor, guild_of, route_session_to_guild
from app.testing.factories import (
    create_initiative,
    create_project,
    create_property_definition,
)


def _types_url(a: Actor, project_id: int) -> str:
    return a.g(f"/projects/{project_id}/task-types/")


def _set(values: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Starting values as read, without the fields they leave empty."""
    return {k: v for k, v in (values or {}).items() if v not in (None, [])}


async def _speaks(session: AsyncSession, user: User, locale: str) -> None:
    user.locale = locale
    session.add(user)
    await session.commit()


async def test_the_gallery_speaks_the_readers_language(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await _speaks(session, a.user, "de")

    response = await client.get(
        _types_url(a, a.project.id) + "gallery", headers=a.headers
    )

    assert response.status_code == 200, response.text
    groups = {group["key"]: group for group in response.json()}
    assert list(groups) == ["planning", "home", "groups", "making", "learning"]
    assert groups["home"]["name"] == "Rund ums Haus"
    bill = next(e for e in groups["home"]["entries"] if e["key"] == "bill")
    assert bill["name"] == "Rechnung"
    assert bill["layout_preset"] == "repeat"
    assert bill["fields"] == [{"name": "Betrag", "type": "number"}]
    assert bill["starting_values"]["recurrence"] == "RRULE:FREQ=MONTHLY"
    bug = next(e for e in groups["making"]["entries"] if e["key"] == "bug")
    assert bug["starting_values"]["description"].startswith("**Was ist passiert?**")


async def test_a_gallery_type_brings_its_look_its_start_and_its_fields(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    # One the initiative already has, one it has under another kind, and one
    # it lacks.
    cost = await create_property_definition(
        session, a.initiative, name="cost", type=MetadataType.number
    )
    await create_property_definition(
        session, a.initiative, name="Link", type=MetadataType.text
    )
    await session.commit()

    created = await client.post(
        _types_url(a, a.project.id),
        json={"name": "Buy", "gallery_key": "purchase"},
        headers=a.headers,
    )

    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["icon"], body["color"], body["layout_preset"]) == (
        "shopping-bag",
        "#10B981",
        "plain",
    )
    # The Cost it had is used; the Link of another kind is left alone.
    assert body["field_ids"] == [cost.id]

    chore = await client.post(
        _types_url(a, a.project.id),
        json={"name": "Chore", "gallery_key": "chore"},
        headers=a.headers,
    )
    assert _set(chore.json()["starting_values"]) == {"recurrence": "RRULE:FREQ=WEEKLY"}

    event = await client.post(
        _types_url(a, a.project.id),
        json={"name": "Gig", "gallery_key": "event"},
        headers=a.headers,
    )
    await route_session_to_guild(session, guild_of(a.project))
    [location] = (
        await session.exec(
            select(MetadataDefinition).where(
                MetadataDefinition.initiative_id == a.initiative.id,
                MetadataDefinition.name == "Location",
            )
        )
    ).all()
    assert location.type == MetadataType.text
    assert event.json()["field_ids"] == [location.id]


async def test_a_type_starts_from_one_place_only(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await route_session_to_guild(session, guild_of(a.project))
    task_type = (
        await task_types_service.ensure_default_types(
            session, a.project.id, locale="en"
        )
    )[0]
    await session.commit()

    response = await client.post(
        _types_url(a, a.project.id),
        json={
            "name": "Both",
            "gallery_key": "chore",
            "start_from_type_id": task_type.id,
        },
        headers=a.headers,
    )

    assert response.status_code == 422


async def test_starting_values_are_set_and_cleared(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    created = await client.post(
        _types_url(a, a.project.id),
        json={
            "name": "Packing list",
            "starting_values": {"checklist": ["Tent", "Stove"], "priority": "high"},
        },
        headers=a.headers,
    )
    assert _set(created.json()["starting_values"]) == {
        "checklist": ["Tent", "Stove"],
        "priority": "high",
    }
    type_id = created.json()["id"]

    # Started from it, another starts a task the same way.
    copied = await client.post(
        _types_url(a, a.project.id),
        json={"name": "Camping", "start_from_type_id": type_id},
        headers=a.headers,
    )
    assert copied.json()["starting_values"] == created.json()["starting_values"]

    cleared = await client.patch(
        _types_url(a, a.project.id) + str(type_id),
        json={"starting_values": None},
        headers=a.headers,
    )
    assert cleared.json()["starting_values"] is None
    # Nothing in them is nothing to start.
    emptied = await client.patch(
        _types_url(a, a.project.id) + str(copied.json()["id"]),
        json={"starting_values": {"checklist": []}},
        headers=a.headers,
    )
    assert emptied.json()["starting_values"] is None


async def test_a_new_projects_bug_starts_with_an_outline_in_its_makers_language(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _speaks(session, a.user, "fr")

    created = await client.post(
        a.g("/projects/"),
        json={"name": "Jeu", "initiative_id": a.initiative.id},
        headers=a.headers,
    )

    starts = [t["starting_values"] for t in created.json()["task_types"]]
    assert starts[0] is None
    assert starts[1]["description"].startswith("**Ce qui s’est passé**")
    assert starts[2:] == [None, None]


async def test_types_copy_from_another_project_with_their_pages(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    source = await create_project(session, a.initiative, a.user, name="Source")
    other_initiative = await create_initiative(
        session, a.guild, a.user, name="Elsewhere"
    )
    far = await create_project(session, other_initiative, a.user, name="Far")
    await route_session_to_guild(session, guild_of(source))
    effort = await create_property_definition(
        session, a.initiative, name="Effort", type=MetadataType.number
    )
    chore = (
        await client.post(
            _types_url(a, source.id),
            json={"name": "Chore", "gallery_key": "chore"},
            headers=a.headers,
        )
    ).json()
    page = {
        "side": [
            {"type": "field", "props": {"field": "title"}},
            {"type": "field", "props": {"field": f"property:{effort.id}"}},
        ]
    }
    await route_session_to_guild(session, guild_of(source))
    session.add(
        ToolLayout(
            initiative_id=a.initiative.id,
            tool="project",
            tool_id=source.id,
            kind="task",
            task_type_id=chore["id"],
            definition=page,
        )
    )
    await session.commit()

    # Into a project of the same initiative: Bug and the rest are already
    # there by name, so only Chore comes, with its page as it was.
    copied = await client.post(
        _types_url(a, a.project.id) + "copy",
        json={"source_project_id": source.id},
        headers=a.headers,
    )
    assert copied.status_code == 200, copied.text
    [copy] = copied.json()
    assert (copy["name"], copy["is_default"], _set(copy["starting_values"])) == (
        "Chore",
        False,
        {"recurrence": "RRULE:FREQ=WEEKLY"},
    )
    await route_session_to_guild(session, guild_of(source))
    near_page = (
        await session.exec(
            select(ToolLayout).where(ToolLayout.task_type_id == copy["id"])
        )
    ).one()
    assert near_page.definition == page

    # Into another initiative's: its properties stay where they are.
    far_copy = await client.post(
        _types_url(a, far.id) + "copy",
        json={"source_project_id": source.id, "type_ids": [chore["id"]]},
        headers=a.headers,
    )
    [far_type] = far_copy.json()
    await route_session_to_guild(session, guild_of(source))
    far_page = (
        await session.exec(
            select(ToolLayout).where(ToolLayout.task_type_id == far_type["id"])
        )
    ).one()
    assert (far_page.tool_id, far_page.initiative_id) == (far.id, other_initiative.id)
    assert far_page.definition == {"side": [page["side"][0]]}

    # A type that is not the source's is not found.
    missing = await client.post(
        _types_url(a, far.id) + "copy",
        json={"source_project_id": source.id, "type_ids": [999_999]},
        headers=a.headers,
    )
    assert missing.status_code == 404
