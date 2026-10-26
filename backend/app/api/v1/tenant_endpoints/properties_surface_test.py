"""The custom-property surface, proved once for every entity that carries it.

Every tool and sub-tool is written through ``PUT /properties/{target}/{id}``
with replace-all semantics, holds a value to its definition's type, keeps a
definition inside its initiative, and carries its values in its read's
``properties``. Tasks, files and calendar events also filter their list by
a value. The rules are the property engine's
(``services/tenant/properties_test.py``); what this file pins is that each
entity surfaces them the same way. Another entity gets the same proof by adding
a ``Surface``.

What only one entity does — a task moving between initiatives, a file
being copied, an event outliving its initiative — sits at the bottom under
that entity's name.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import KINDS
from app.core.tools import Tool
from app.models.platform.guild import CommunityRole
from app.models.tenant.initiative import Initiative
from app.models.tenant.property import PropertyType, PropertyValue
from app.models.tenant.task import Task
from app.services.tenant.properties import PROPERTY_LINKS
from app.testing import (
    Actor,
    create_calendar,
    create_calendar_event,
    create_file,
    create_catalog,
    create_catalog_item,
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_property_definition,
    create_property_value,
    create_queue,
    create_queue_item,
    create_resource_grant,
    create_task,
    create_tool_entity,
    create_user,
    create_wiki,
    create_wiki_page,
    enable_all_tools,
    route_session_to_guild,
)

# ---------------------------------------------------------------------------
# The surfaces
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Surface:
    """One entity's property surface, and how a test gets an entity to hit."""

    #: The target the write route names: ``/properties/{kind}/{id}``.
    kind: str
    #: Path segment under ``/c/{guild}/`` the entity is listed from.
    path: str
    #: Whatever ``make`` needs in place inside an initiative.
    parent: Callable[[AsyncSession, Actor, Initiative], Awaitable[Any]]
    #: One entity under that parent, by id.
    make: Callable[[AsyncSession, Actor, Any, str], Awaitable[int]]
    #: The list query keeping only entities whose value equals ``value``.
    filter_query: Callable[[Actor, Any, int, Any], str]
    #: The list that query is read from, when it is not ``path``, and the key
    #: its items come back under.
    list_path: str = ""
    list_key: str = "items"


async def _project_in(session, a, initiative):
    return await create_project(session, initiative, a.user, name="P")


async def _make_task(session, a, project, title):
    return (await create_task(session, project, title=title)).id


def _conditions_filter(a, project, property_id, value):
    conditions = json.dumps(
        [
            {"field": "project_id", "op": "eq", "value": project.id},
            {
                "field": "property_values",
                "op": "eq",
                "value": {"property_id": property_id, "value": value},
            },
        ]
    )
    return f"conditions={conditions}"


async def _initiative_itself(session, a, initiative):
    return initiative


async def _make_file(session, a, initiative, title):
    return (await create_file(session, initiative, a.user, name=title)).id


def _property_filters(a, _parent, property_id, value):
    filters = json.dumps([{"property_id": property_id, "op": "eq", "value": value}])
    return f"initiative_id={a.initiative.id}&property_filters={filters}"


def _around_now() -> str:
    """The calendar-entries window around now, where the factory puts events,
    with no task markers."""
    now = datetime.now(timezone.utc)
    return "&".join(
        (
            f"start_after={(now - timedelta(days=1)):%Y-%m-%dT%H:%M:%SZ}",
            f"start_before={(now + timedelta(days=1)):%Y-%m-%dT%H:%M:%SZ}",
            "include_tasks=false",
        )
    )


def _event_filters(a, parent, property_id, value):
    return f"{_property_filters(a, parent, property_id, value)}&{_around_now()}"


async def _calendar_in(session, a, initiative):
    initiative.calendars_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)
    return await create_calendar(session, initiative, a.user)


async def _make_event(session, a, calendar, title):
    return (await create_calendar_event(session, calendar, a.user, title=title)).id


TASKS = Surface(
    kind="task",
    path="tasks",
    parent=_project_in,
    make=_make_task,
    filter_query=_conditions_filter,
)
FILES = Surface(
    kind="file",
    path="files",
    parent=_initiative_itself,
    make=_make_file,
    filter_query=_property_filters,
)
EVENTS = Surface(
    kind="calendar_event",
    path="calendar-events",
    parent=_calendar_in,
    make=_make_event,
    filter_query=_event_filters,
    list_path="calendar-entries",
    list_key="events",
)

SURFACES = [TASKS, FILES, EVENTS]
surfaces = pytest.mark.parametrize("surface", SURFACES, ids=[s.kind for s in SURFACES])


async def _scene(surface: Surface, session, acting_user) -> tuple[Actor, Any]:
    """An initiative admin and the parent the surface's entities hang off."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    return a, await surface.parent(session, a, a.initiative)


async def _write(
    client, a: Actor, surface: Surface, entity_id: int, values: list, **merge: Any
):
    return await client.put(
        a.g(f"/properties/{surface.kind}/{entity_id}"),
        headers=a.headers,
        json={"values": values, **merge},
    )


def _values(summaries: list) -> dict[int, Any]:
    return {p["property_id"]: p["value"] for p in summaries}


async def _stored(session, surface: Surface, entity_id: int) -> list:
    return (
        await session.exec(
            select(PropertyValue).where(
                PropertyValue.entity_type == surface.kind,
                PropertyValue.entity_id == entity_id,
            )
        )
    ).all()


async def _listed(client, a: Actor, surface: Surface, parent, defn_id, value) -> set:
    query = surface.filter_query(a, parent, defn_id, value)
    path = surface.list_path or surface.path
    response = await client.get(a.g(f"/{path}/?{query}"), headers=a.headers)
    assert response.status_code == 200, response.text
    return {item["id"] for item in response.json()[surface.list_key]}


# ---------------------------------------------------------------------------
# Replace-all
# ---------------------------------------------------------------------------


@surfaces
async def test_put_sets_values(
    client: AsyncClient, session: AsyncSession, acting_user, surface: Surface
):
    a, parent = await _scene(surface, session, acting_user)
    entity = await surface.make(session, a, parent, "E")
    text = await create_property_definition(
        session, a.initiative, name="Note", type=PropertyType.text
    )
    number = await create_property_definition(
        session, a.initiative, name="Score", type=PropertyType.number
    )

    response = await _write(
        client,
        a,
        surface,
        entity,
        [
            {"property_id": text.id, "value": "alpha"},
            {"property_id": number.id, "value": 7.5},
        ],
    )

    assert response.status_code == 200
    values = _values(response.json())
    assert values[text.id] == "alpha"
    assert float(values[number.id]) == 7.5


@surfaces
async def test_put_of_nothing_clears_what_was_there(
    client: AsyncClient, session: AsyncSession, acting_user, surface: Surface
):
    a, parent = await _scene(surface, session, acting_user)
    entity = await surface.make(session, a, parent, "E")
    defn = await create_property_definition(
        session, a.initiative, name="Tag", type=PropertyType.text
    )
    await _write(
        client, a, surface, entity, [{"property_id": defn.id, "value": "seed"}]
    )

    response = await _write(client, a, surface, entity, [])

    assert response.status_code == 200
    assert response.json() == []
    assert await _stored(session, surface, entity) == []


async def test_merged_writes_of_different_properties_both_stand(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Two people each save one property of what they read. A merged write
    names only its own, so neither takes back the other's, and one it takes
    off goes alone. The seam is every surface's, so one stands for them."""
    surface = next(s for s in SURFACES if s.kind == "task")
    a, parent = await _scene(surface, session, acting_user)
    entity = await surface.make(session, a, parent, "E")
    note, owner, phase = [
        await create_property_definition(
            session, a.initiative, name=name, type=PropertyType.text
        )
        for name in ("Note", "Owner", "Phase")
    ]
    await _write(
        client,
        a,
        surface,
        entity,
        [
            {"property_id": note.id, "value": "seed"},
            {"property_id": phase.id, "value": "beta"},
        ],
    )

    await _write(
        client,
        a,
        surface,
        entity,
        [{"property_id": note.id, "value": "mine"}],
        merge=True,
    )
    response = await _write(
        client,
        a,
        surface,
        entity,
        [{"property_id": owner.id, "value": "theirs"}],
        merge=True,
        removed=[phase.id],
    )

    assert response.status_code == 200
    assert _values(response.json()) == {note.id: "mine", owner.id: "theirs"}


async def test_option_changes_apply_to_what_the_value_holds(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Two people each move a task between options of one multi-select. A
    change names only the options it puts on and takes off, so the later one
    keeps the earlier one's."""
    a, parent = await _scene(TASKS, session, acting_user)
    entity = await TASKS.make(session, a, parent, "E")
    sprint = await create_property_definition(
        session,
        a.initiative,
        name="Sprint",
        type=PropertyType.multi_select,
        options=[{"value": slug, "label": slug} for slug in ("a", "b", "c")],
    )
    await _write(client, a, TASKS, entity, [{"property_id": sprint.id, "value": ["a"]}])

    await _write(
        client,
        a,
        TASKS,
        entity,
        [],
        merge=True,
        options=[{"property_id": sprint.id, "add": ["b"]}],
    )
    response = await _write(
        client,
        a,
        TASKS,
        entity,
        [],
        merge=True,
        options=[{"property_id": sprint.id, "add": ["c"], "remove": ["a"]}],
    )

    assert response.status_code == 200
    assert _values(response.json()) == {sprint.id: ["b", "c"]}


@pytest.mark.parametrize(
    ("type_", "add", "detail"),
    [
        (PropertyType.select, ["a"], "PROPERTY_INVALID_VALUE_FOR_TYPE"),
        (PropertyType.multi_select, ["ghost"], "PROPERTY_OPTION_NOT_IN_DEFINITION"),
    ],
    ids=["not-multi_select", "unknown-option"],
)
async def test_an_option_change_is_held_to_its_definition(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    type_: PropertyType,
    add: list[str],
    detail: str,
):
    a, parent = await _scene(TASKS, session, acting_user)
    entity = await TASKS.make(session, a, parent, "E")
    defn = await create_property_definition(
        session,
        a.initiative,
        name="Choice",
        type=type_,
        options=[{"value": "a", "label": "A"}],
    )

    response = await _write(
        client,
        a,
        TASKS,
        entity,
        [],
        merge=True,
        options=[{"property_id": defn.id, "add": add}],
    )

    assert response.status_code == 400
    assert response.json()["detail"] == detail


# ---------------------------------------------------------------------------
# Values are held to their definition
# ---------------------------------------------------------------------------


@surfaces
async def test_put_refuses_a_value_the_type_cannot_read(
    client: AsyncClient, session: AsyncSession, acting_user, surface: Surface
):
    a, parent = await _scene(surface, session, acting_user)
    entity = await surface.make(session, a, parent, "E")
    defn = await create_property_definition(
        session, a.initiative, name="Count", type=PropertyType.number
    )

    response = await _write(
        client, a, surface, entity, [{"property_id": defn.id, "value": "not a number"}]
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "PROPERTY_INVALID_VALUE_FOR_TYPE"


@pytest.mark.parametrize(
    ("type_", "value", "accepted"),
    [
        (PropertyType.text, 12345, None),
        (PropertyType.number, "3.14", 3.14),
        (PropertyType.date, "2026-04-22", "2026-04-22"),
        (PropertyType.date, "not-a-date", None),
        (PropertyType.url, "https://example.com", "https://example.com"),
        (PropertyType.url, "not a url", None),
    ],
    ids=["text-number", "number-string", "date", "date-garbage", "url", "url-garbage"],
)
async def test_put_holds_a_value_to_its_type(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    type_: PropertyType,
    value: Any,
    accepted: Any,
):
    """One surface stands for all here: the reading is the engine's."""
    a, parent = await _scene(FILES, session, acting_user)
    entity = await FILES.make(session, a, parent, "E")
    defn = await create_property_definition(session, a.initiative, name="V", type=type_)

    response = await _write(
        client, a, FILES, entity, [{"property_id": defn.id, "value": value}]
    )

    if accepted is None:
        assert response.status_code == 400
        assert response.json()["detail"] == "PROPERTY_INVALID_VALUE_FOR_TYPE"
        return
    assert response.status_code == 200
    stored = _values(response.json())[defn.id]
    if type_ is PropertyType.number:
        stored = float(stored)
    assert stored == accepted


@pytest.mark.parametrize(
    ("surface", "type_", "value"),
    [
        (TASKS, PropertyType.multi_select, ["a", "ghost"]),
        (FILES, PropertyType.multi_select, ["a", "ghost"]),
        (EVENTS, PropertyType.multi_select, ["a", "ghost"]),
        (FILES, PropertyType.select, "ghost"),
    ],
    ids=["task-multi_select", "file-multi_select", "event-multi_select", "select"],
)
async def test_put_refuses_an_option_the_definition_lacks(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    surface: Surface,
    type_: PropertyType,
    value: Any,
):
    a, parent = await _scene(surface, session, acting_user)
    entity = await surface.make(session, a, parent, "E")
    defn = await create_property_definition(
        session,
        a.initiative,
        name="Choice",
        type=type_,
        options=[{"value": "a", "label": "A"}, {"value": "b", "label": "B"}],
    )

    response = await _write(
        client, a, surface, entity, [{"property_id": defn.id, "value": value}]
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "PROPERTY_OPTION_NOT_IN_DEFINITION"


@surfaces
async def test_put_refuses_a_person_who_cannot_open_it(
    client: AsyncClient, session: AsyncSession, acting_user, surface: Surface
):
    a, parent = await _scene(surface, session, acting_user)
    entity = await surface.make(session, a, parent, "E")
    # In the community, not in the initiative.
    outsider = await create_user(session)
    await create_guild_membership(
        session, user=outsider, guild=a.guild, role=CommunityRole.member
    )
    defn = await create_property_definition(
        session, a.initiative, name="Owner", type=PropertyType.user_reference
    )

    response = await _write(
        client, a, surface, entity, [{"property_id": defn.id, "value": outsider.id}]
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "PERSON_CANNOT_READ"


# ---------------------------------------------------------------------------
# A definition stays in its initiative; an entity stays in its community
# ---------------------------------------------------------------------------


@surfaces
async def test_put_refuses_a_definition_from_another_initiative(
    client: AsyncClient, session: AsyncSession, acting_user, surface: Surface
):
    a, parent = await _scene(surface, session, acting_user)
    entity = await surface.make(session, a, parent, "E")
    elsewhere = await create_initiative(session, a.guild, a.user, name="B")
    foreign = await create_property_definition(session, elsewhere, name="Foreign")

    response = await _write(
        client, a, surface, entity, [{"property_id": foreign.id, "value": "x"}]
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "PROPERTY_DEFINITION_NOT_FOUND"


@surfaces
async def test_put_on_an_entity_of_another_community_is_not_found(
    client: AsyncClient, session: AsyncSession, acting_user, surface: Surface
):
    """Addressed through community A, an entity that lives in B is nobody's."""
    a, _parent = await _scene(surface, session, acting_user)
    guild_b = await create_guild(session, name="B")
    await create_guild_membership(
        session, user=a.user, guild=guild_b, role=CommunityRole.admin
    )
    initiative_b = await create_initiative(session, guild_b, a.user, name="Init B")
    parent_b = await surface.parent(session, a, initiative_b)
    entity_b = await surface.make(session, a, parent_b, "B")

    response = await _write(client, a, surface, entity_b, [])

    assert response.status_code == 404
    assert response.json() == KINDS[surface.kind].not_found().body


@surfaces
async def test_put_needs_write_on_the_tool_that_governs_it(
    client: AsyncClient, session: AsyncSession, acting_user, surface: Surface
):
    """Outside the initiative the entity is not there to write; inside it,
    reading the tool that governs it is not enough."""
    a, parent = await _scene(surface, session, acting_user)
    entity = await surface.make(session, a, parent, "E")
    defn = await create_property_definition(session, a.initiative, name="Tag")
    outsider = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    reader = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    spec = PROPERTY_LINKS[surface.kind]
    await route_session_to_guild(session, a.guild.id)
    row = await session.get(spec.model, entity)
    governing = (
        row
        if spec.via is None
        else await session.get(
            PROPERTY_LINKS[spec.tool.value].model, spec.governing_id(row)
        )
    )
    await create_resource_grant(session, governing, user=reader.user)
    values = [{"property_id": defn.id, "value": "x"}]

    hidden = await _write(client, outsider, surface, entity, values)
    assert hidden.status_code == 404
    assert hidden.json() == KINDS[surface.kind].not_found().body

    refused = await _write(client, reader, surface, entity, values)
    assert refused.status_code == 403
    assert await _stored(session, surface, entity) == []


# ---------------------------------------------------------------------------
# The list filters by a value
# ---------------------------------------------------------------------------


@surfaces
async def test_list_filters_by_a_text_value(
    client: AsyncClient, session: AsyncSession, acting_user, surface: Surface
):
    a, parent = await _scene(surface, session, acting_user)
    match = await surface.make(session, a, parent, "Match")
    other = await surface.make(session, a, parent, "Other")
    defn = await create_property_definition(
        session, a.initiative, name="Tag", type=PropertyType.text
    )
    await _write(
        client, a, surface, match, [{"property_id": defn.id, "value": "findme"}]
    )
    await _write(client, a, surface, other, [{"property_id": defn.id, "value": "skip"}])

    listed = await _listed(client, a, surface, parent, defn.id, "findme")

    assert match in listed
    assert other not in listed


@surfaces
async def test_list_filters_by_a_selected_option(
    client: AsyncClient, session: AsyncSession, acting_user, surface: Surface
):
    """A multi-select filter is containment: the option named is among those set."""
    a, parent = await _scene(surface, session, acting_user)
    with_alpha = await surface.make(session, a, parent, "A")
    without = await surface.make(session, a, parent, "N")
    defn = await create_property_definition(
        session,
        a.initiative,
        name="Labels",
        type=PropertyType.multi_select,
        options=[
            {"value": "alpha", "label": "Alpha"},
            {"value": "beta", "label": "Beta"},
            {"value": "gamma", "label": "Gamma"},
        ],
    )
    await _write(
        client,
        a,
        surface,
        with_alpha,
        [{"property_id": defn.id, "value": ["alpha", "beta"]}],
    )
    await _write(
        client, a, surface, without, [{"property_id": defn.id, "value": ["gamma"]}]
    )

    listed = await _listed(client, a, surface, parent, defn.id, ["alpha"])

    assert with_alpha in listed
    assert without not in listed


# ---------------------------------------------------------------------------
# Every tool and sub-tool carries them
# ---------------------------------------------------------------------------


async def test_every_tool_and_its_sub_tools_read_back_what_they_carry(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Every tool, a queue's items and a wiki's pages are written like any
    other target, and each one's own read returns its values."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await enable_all_tools(session, a.initiative)
    defn = await create_property_definition(session, a.initiative, name="Note")

    async def write(target: str, row_id: int) -> None:
        written = await client.put(
            a.g(f"/properties/{target}/{row_id}"),
            headers=a.headers,
            json={"values": [{"property_id": defn.id, "value": target}]},
        )
        assert written.status_code == 200, (target, written.text)
        assert _values(written.json()) == {defn.id: target}

    for tool in Tool:
        row = await create_tool_entity(session, tool, a.initiative, a.user)
        await write(tool.value, row.id)
        read = await client.get(
            a.g(f"/{tool.route_segment}/{row.id}"), headers=a.headers
        )
        assert read.status_code == 200, (tool, read.text)
        assert _values(read.json()["properties"]) == {defn.id: tool.value}, tool

    queue = await create_queue(session, a.initiative, a.user)
    item = await create_queue_item(session, queue)
    page = await create_wiki_page(
        session, await create_wiki(session, a.initiative, a.user), a.user
    )
    await write("queue_item", item.id)
    await write("wiki_page", page.id)
    queue_read = await client.get(a.g(f"/queues/{queue.id}"), headers=a.headers)
    [item_read] = queue_read.json()["items"]
    assert _values(item_read["properties"]) == {defn.id: "queue_item"}
    page_read = await client.get(a.g(f"/wiki-pages/{page.id}"), headers=a.headers)
    assert page_read.status_code == 200, page_read.text
    assert _values(page_read.json()["properties"]) == {defn.id: "wiki_page"}

    # A picture's own update carries them, and its read returns them.
    catalog = await create_catalog(session, a.initiative, a.user)
    image = await create_catalog_item(session, catalog, a.user)
    edited = await client.patch(
        a.g(f"/catalog-items/{image.id}"),
        headers=a.headers,
        json={"properties": [{"property_id": defn.id, "value": "catalog_item"}]},
    )
    assert edited.status_code == 200, edited.text
    assert _values(edited.json()["properties"]) == {defn.id: "catalog_item"}
    image_read = await client.get(a.g(f"/catalog-items/{image.id}"), headers=a.headers)
    assert _values(image_read.json()["properties"]) == {defn.id: "catalog_item"}


async def test_a_create_writes_its_values_with_the_row(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A create carries its values in its own transaction: a queue and an item
    in it come back holding them, and a task naming a person who cannot open
    its project is refused whole — no task is left without its values. A
    task's update does the same."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await enable_all_tools(session, a.initiative)
    note = await create_property_definition(session, a.initiative, name="Note")
    owner = await create_property_definition(
        session, a.initiative, name="Owner", type=PropertyType.user_reference
    )

    queue = await client.post(
        a.g("/queues/"),
        headers=a.headers,
        json={
            "initiative_id": a.initiative.id,
            "name": "Rota",
            "properties": [{"property_id": note.id, "value": "queue"}],
        },
    )
    assert queue.status_code == 201, queue.text
    assert _values(queue.json()["properties"]) == {note.id: "queue"}
    item = await client.post(
        a.g(f"/queues/{queue.json()['id']}/items"),
        headers=a.headers,
        json={
            "label": "First",
            "properties": [{"property_id": note.id, "value": "item"}],
        },
    )
    assert item.status_code == 201, item.text
    assert _values(item.json()["properties"]) == {note.id: "item"}

    outsider = await create_user(session)
    await create_guild_membership(
        session, user=outsider, guild=a.guild, role=CommunityRole.member
    )
    refused = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={
            "project_id": a.project.id,
            "title": "Named",
            "properties": [{"property_id": owner.id, "value": outsider.id}],
        },
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"] == "PERSON_CANNOT_READ"
    left = (await session.exec(select(Task).where(Task.title == "Named"))).all()
    assert left == []

    # An update carries them the same way: refused whole, the title unchanged.
    task = await create_task(session, a.project, title="Kept")
    edited = await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={
            "title": "Renamed",
            "properties": [{"property_id": owner.id, "value": outsider.id}],
        },
    )
    assert edited.status_code == 422, edited.text
    kept = await client.get(a.g(f"/tasks/{task.id}"), headers=a.headers)
    assert kept.json()["title"] == "Kept"
    edited = await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={
            "title": "Renamed",
            "properties": [{"property_id": note.id, "value": "task"}],
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["title"] == "Renamed"
    assert _values(edited.json()["properties"]) == {note.id: "task"}


# ---------------------------------------------------------------------------
# Tasks: values follow a task only within its initiative
# ---------------------------------------------------------------------------


async def test_moving_a_task_to_another_initiative_drops_its_values(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, project_a = await _scene(TASKS, session, acting_user)
    init_b = await create_initiative(session, a.guild, a.user, name="B")
    project_b = await create_project(session, init_b, a.user, name="PB")
    task = await _make_task(session, a, project_a, "Mover")
    defn = await create_property_definition(
        session, a.initiative, name="Tag", type=PropertyType.text
    )
    await _write(
        client, a, TASKS, task, [{"property_id": defn.id, "value": "beforeMove"}]
    )

    moved = await client.post(
        a.g(f"/tasks/{task}/move"),
        headers=a.headers,
        json={"target_project_id": project_b.id},
    )

    assert moved.status_code == 200
    assert await _stored(session, TASKS, task) == []


async def test_duplicating_a_task_in_its_project_carries_its_values(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, project = await _scene(TASKS, session, acting_user)
    task = await _make_task(session, a, project, "Orig")
    defn = await create_property_definition(
        session, a.initiative, name="Tag", type=PropertyType.text
    )
    await _write(client, a, TASKS, task, [{"property_id": defn.id, "value": "carry"}])

    duplicated = await client.post(a.g(f"/tasks/{task}/duplicate"), headers=a.headers)

    assert duplicated.status_code == 201
    assert _values(duplicated.json()["properties"]).get(defn.id) == "carry"
    assert len(await _stored(session, TASKS, duplicated.json()["id"])) == 1


# ---------------------------------------------------------------------------
# Files: the ``property_filters`` parameter, and copies
# ---------------------------------------------------------------------------


async def test_list_files_filters_by_a_number(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, initiative = await _scene(FILES, session, acting_user)
    defn = await create_property_definition(
        session, initiative, name="Score", type=PropertyType.number
    )
    docs = [await _make_file(session, a, initiative, f"D{n}") for n in range(3)]
    for doc, score in zip(docs, [10, 20, 30]):
        await _write(client, a, FILES, doc, [{"property_id": defn.id, "value": score}])

    listed = await _listed(client, a, FILES, initiative, defn.id, 20)

    assert listed & set(docs) == {docs[1]}


@pytest.mark.parametrize(
    "property_filters",
    [
        "not-json",
        json.dumps([{"property_id": i, "op": "eq", "value": "x"} for i in range(1, 7)]),
    ],
    ids=["not-json", "six-predicates"],
)
async def test_list_files_refuses_a_filter_it_cannot_take(
    client: AsyncClient, acting_user, property_filters: str
):
    """Malformed, or past the five-predicate cap; the ids need not exist."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)

    response = await client.get(
        a.g(
            f"/files/?initiative_id={a.initiative.id}"
            f"&property_filters={property_filters}"
        ),
        headers=a.headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "QUERY_INVALID_CONDITIONS"


async def test_duplicating_a_file_in_place_carries_its_values(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, initiative = await _scene(FILES, session, acting_user)
    doc = await _make_file(session, a, initiative, "Src")
    defn = await create_property_definition(
        session, initiative, name="Tag", type=PropertyType.text
    )
    await _write(
        client, a, FILES, doc, [{"property_id": defn.id, "value": "carryover"}]
    )

    duplicated = await client.post(
        a.g(f"/files/{doc}/duplicate"), headers=a.headers, json={"name": "Dup"}
    )

    assert duplicated.status_code == 201
    assert _values(duplicated.json()["properties"]).get(defn.id) == "carryover"
    rows = await _stored(session, FILES, duplicated.json()["id"])
    assert [row.property_id for row in rows] == [defn.id]


async def test_copying_a_file_to_another_initiative_drops_its_values(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, initiative = await _scene(FILES, session, acting_user)
    init_b = await create_initiative(session, a.guild, a.user, name="B")
    doc = await _make_file(session, a, initiative, "Src")
    defn = await create_property_definition(
        session, initiative, name="Tag", type=PropertyType.text
    )
    await _write(client, a, FILES, doc, [{"property_id": defn.id, "value": "onlyA"}])

    copied = await client.post(
        a.g(f"/files/{doc}/duplicate"),
        headers=a.headers,
        json={"name": "Copied", "target_initiative_id": init_b.id},
    )

    assert copied.status_code == 201
    assert copied.json()["properties"] == []
    assert await _stored(session, FILES, copied.json()["id"]) == []
    # The original is untouched.
    assert len(await _stored(session, FILES, doc)) == 1


# ---------------------------------------------------------------------------
# Events: an attached-empty row, the read, ``is_null``, and the purge
# ---------------------------------------------------------------------------


async def test_attaching_a_property_to_an_event_without_a_value_keeps_a_row(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, calendar = await _scene(EVENTS, session, acting_user)
    event = await _make_event(session, a, calendar, "E")
    defn = await create_property_definition(
        session, a.initiative, name="Empty", type=PropertyType.text
    )

    response = await _write(
        client, a, EVENTS, event, [{"property_id": defn.id, "value": None}]
    )

    assert response.status_code == 200
    assert len(await _stored(session, EVENTS, event)) == 1


async def test_reading_an_event_embeds_its_values(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, calendar = await _scene(EVENTS, session, acting_user)
    event = await _make_event(session, a, calendar, "E")
    defn = await create_property_definition(
        session, a.initiative, name="Topic", type=PropertyType.text
    )
    await _write(
        client, a, EVENTS, event, [{"property_id": defn.id, "value": "onboarding"}]
    )

    read = await client.get(a.g(f"/calendar-events/{event}"), headers=a.headers)

    assert read.status_code == 200
    assert read.json()["properties"][0]["value"] == "onboarding"


async def test_calendar_entries_is_null_matches_the_unset(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, calendar = await _scene(EVENTS, session, acting_user)
    with_value = await _make_event(session, a, calendar, "WithVal")
    without = await _make_event(session, a, calendar, "Blank")
    defn = await create_property_definition(
        session, a.initiative, name="Topic", type=PropertyType.text
    )
    await _write(
        client, a, EVENTS, with_value, [{"property_id": defn.id, "value": "yes"}]
    )

    filters = json.dumps([{"property_id": defn.id, "op": "is_null", "value": True}])
    response = await client.get(
        a.g(
            f"/calendar-entries/?initiative_id={a.initiative.id}"
            f"&property_filters={filters}&{_around_now()}"
        ),
        headers=a.headers,
    )

    assert response.status_code == 200, response.text
    listed = {item["id"] for item in response.json()["events"]}
    assert without in listed
    assert with_value not in listed


async def test_purging_an_initiative_takes_every_value_in_it_with_it(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A soft-deleted initiative keeps its rows, so a restore brings everything
    back; the purge is what takes the values on its tools and sub-tools."""
    a, calendar = await _scene(EVENTS, session, acting_user)
    event = await _make_event(session, a, calendar, "E")
    defn = await create_property_definition(
        session, a.initiative, name="Topic", type=PropertyType.text
    )
    await _write(client, a, EVENTS, event, [{"property_id": defn.id, "value": "hold"}])
    queue = await create_queue(session, a.initiative, a.user)
    for row in (queue, await create_queue_item(session, queue)):
        await create_property_value(session, row, defn, value_text="hold")

    deleted = await client.delete(
        a.g(f"/initiatives/{a.initiative.id}"), headers=a.headers
    )
    assert deleted.status_code in (200, 204)
    assert len(await _stored(session, EVENTS, event)) == 1

    purged = await client.delete(
        a.g(f"/trash/initiative/{a.initiative.id}/purge"), headers=a.headers
    )
    assert purged.status_code == 204
    assert (await session.exec(select(PropertyValue))).all() == []
