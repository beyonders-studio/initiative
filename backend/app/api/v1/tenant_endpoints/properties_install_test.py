"""The custom property routes an installed plug-in calls.

``PUT /properties/{target}/{id}`` answers to the write scope of the tool that
governs the item, and a person-valued property names the person by the
install's own reference for them, on the way in and on the way out. The
definitions answer to ``properties``, and are read with any tool's scope too.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.core.messages import InitiativeMessages, PluginMessages, QueryMessages
from app.models.tenant.property import PropertyType
from app.services.marketplace import plugin_refs
from app.testing import (
    guild_url,
    create_guild_plugin,
    create_property_definition,
    guild_of,
    route_session_to_guild,
)
from app.testing.plugin_clients import (
    assert_names_nobody,
    install_plugin,
    install_headers,
    lift_person_and_guild_ids,
)


async def _file(client: Any, session: Any, installed: Any, headers: dict) -> int:
    created = await client.post(
        guild_url(installed.guild.id, "/files/"),
        headers=headers,
        json={"name": "The plug-in's", "initiative_id": installed.placed.id},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def _task(client: Any, session: Any, installed: Any, headers: dict) -> int:
    project = await client.post(
        guild_url(installed.guild.id, "/projects/"),
        headers=headers,
        json={"name": "The plug-in's", "initiative_id": installed.placed.id},
    )
    assert project.status_code == 201, project.text
    task = await client.post(
        guild_url(installed.guild.id, "/tasks/"),
        headers=headers,
        json={"project_id": project.json()["id"], "title": "The plug-in's"},
    )
    assert task.status_code == 201, task.text
    return task.json()["id"]


async def _event(client: Any, session: Any, installed: Any, headers: dict) -> int:
    await route_session_to_guild(session, guild_of(installed.placed))
    installed.placed.calendars_enabled = True
    session.add(installed.placed)
    await session.commit()
    calendar = await client.post(
        guild_url(installed.guild.id, "/calendars/"),
        headers=headers,
        json={"name": "The plug-in's", "initiative_id": installed.placed.id},
    )
    assert calendar.status_code == 201, calendar.text
    start = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=1)
    event = await client.post(
        guild_url(installed.guild.id, "/calendar-events/"),
        headers=headers,
        json={
            "calendar_id": calendar.json()["id"],
            "title": "The plug-in's",
            "start_at": start.isoformat(),
            "end_at": (start + timedelta(hours=1)).isoformat(),
        },
    )
    assert event.status_code == 201, event.text
    return event.json()["id"]


#: Per target: the tool's scopes, how to make an item the install may write,
#: and the route it is read from.
_KINDS = {
    "file": ("files", _file, "/files"),
    "task": ("projects", _task, "/tasks"),
    "calendar_event": ("calendars", _event, "/calendar-events"),
}


async def _seat_reference(client: Any, installed: Any, headers: dict) -> str:
    """What the install calls the seat, a member of the initiative it is
    placed in."""
    members = await client.get(
        guild_url(installed.guild.id, "/users/search"), headers=headers
    )
    assert members.status_code == 200, members.text
    [seat] = members.json()["items"]
    assert isinstance(seat["id"], str)
    return seat["id"]


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", list(_KINDS))
async def test_setting_values_needs_the_tools_write(
    kind, client, session, acting_user, role_session
):
    tool = _KINDS[kind][0]
    scopes = [f"{tool}:read", f"{tool}:write"]
    installed = await install_plugin(session, acting_user, role_session, granted=scopes)
    guild_id = installed.guild.id
    item_id = await _KINDS[kind][1](
        client, session, installed, install_headers(installed, scopes)
    )
    note = await create_property_definition(
        session, installed.placed, name="Note", type=PropertyType.text
    )
    url = guild_url(guild_id, f"/properties/{kind}/{item_id}")
    body = {"values": [{"property_id": note.id, "value": "Set by the plug-in"}]}

    read_only = await client.put(
        url, headers=install_headers(installed, [f"{tool}:read"]), json=body
    )
    assert read_only.status_code == 403, read_only.text
    assert read_only.json()["detail"] == PluginMessages.SCOPE_REQUIRED

    written = await client.put(
        url, headers=install_headers(installed, scopes), json=body
    )
    assert written.status_code == 200, written.text
    [value] = written.json()
    assert value["property_id"] == note.id
    assert value["value"] == "Set by the plug-in"


async def test_definitions_are_read_with_any_tool_and_written_with_properties(
    client, session, acting_user, role_session
):
    scopes = ["projects:write", "properties:write"]
    installed = await install_plugin(session, acting_user, role_session, granted=scopes)
    url = guild_url(installed.guild.id, "/property-definitions/")
    stage = await create_property_definition(
        session,
        installed.placed,
        name="Stage",
        type=PropertyType.select,
        options=[{"value": "draft", "label": "Draft"}],
    )

    by_tool = await client.get(
        url, headers=install_headers(installed, ["projects:read"])
    )
    assert by_tool.status_code == 200, by_tool.text
    [listed] = by_tool.json()
    assert listed["id"] == stage.id
    assert [option["value"] for option in listed["options"]] == ["draft"]

    unrelated = await client.get(
        url, headers=install_headers(installed, ["members:read"])
    )
    assert unrelated.status_code == 403, unrelated.text

    body = {
        "initiative_id": installed.placed.id,
        "name": "Client",
        "type": "select",
        "options": [{"value": "acme", "label": "Acme"}],
    }
    refused = await client.post(
        url, headers=install_headers(installed, ["properties:read"]), json=body
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == PluginMessages.SCOPE_REQUIRED

    # Placed in the initiative, it creates and adds options as a member does;
    # reshaping or removing one is a manager's.
    headers = install_headers(installed, ["properties:write"])
    created = await client.post(url, headers=headers, json=body)
    assert created.status_code == 201, created.text
    definition_url = f"{url}{created.json()['id']}"
    added = await client.patch(
        definition_url,
        headers=headers,
        json={"options": [{"value": "globex", "label": "Globex"}]},
    )
    assert added.status_code == 200, added.text
    assert [o["value"] for o in added.json()["definition"]["options"]] == [
        "acme",
        "globex",
    ]
    renamed = await client.patch(
        definition_url, headers=headers, json={"name": "Customer"}
    )
    assert renamed.status_code == 403, renamed.text
    assert renamed.json()["detail"] == InitiativeMessages.MANAGER_REQUIRED


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", list(_KINDS))
async def test_a_person_valued_property_is_set_and_read_by_reference(
    kind, client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    tool = _KINDS[kind][0]
    # The person has to be a member of the item's initiative, which the
    # service reads from the roster.
    scopes = [f"{tool}:read", f"{tool}:write", "initiatives:read", "members:read"]
    installed = await install_plugin(session, acting_user, role_session, granted=scopes)
    headers = install_headers(installed, scopes)
    guild_id = installed.guild.id
    item_id = await _KINDS[kind][1](client, session, installed, headers)
    owner = await create_property_definition(
        session, installed.placed, name="Owner", type=PropertyType.user_reference
    )
    seat_ref = await _seat_reference(client, installed, headers)
    path = f"{_KINDS[kind][2]}/{item_id}"

    written = await client.put(
        guild_url(guild_id, f"/properties/{kind}/{item_id}"),
        headers=headers,
        json={"values": [{"property_id": owner.id, "value": seat_ref}]},
    )
    assert written.status_code == 200, written.text
    [value] = written.json()
    assert value["value"]["id"] == seat_ref
    assert_names_nobody(written.text, [installed.seat.user.id, guild_id])

    read = await client.get(guild_url(guild_id, path), headers=headers)
    assert read.status_code == 200, read.text
    [value] = read.json()["properties"]
    assert value["value"]["id"] == seat_ref
    assert_names_nobody(read.text, [installed.seat.user.id, guild_id])

    # A person reads the same value as the row id it is stored as.
    as_person = await client.get(
        guild_url(guild_id, path), headers=installed.seat.headers
    )
    assert as_person.status_code == 200, as_person.text
    [value] = as_person.json()["properties"]
    assert value["value"]["id"] == installed.seat.user.id


async def test_a_person_named_any_other_way_is_a_422(
    client, session, acting_user, role_session
):
    scopes = ["files:read", "files:write", "initiatives:read", "members:read"]
    installed = await install_plugin(session, acting_user, role_session, granted=scopes)
    headers = install_headers(installed, scopes)
    guild_id = installed.guild.id
    file_id = await _file(client, session, installed, headers)
    owner = await create_property_definition(
        session, installed.placed, name="Owner", type=PropertyType.user_reference
    )
    other = await create_guild_plugin(
        session,
        installed.guild,
        installed.seat.user,
        definition={
            "plugin_kind": "service",
            "service": {"public_id": "tests.token-client-two", "protocol": 1},
        },
        listing_uid="TOKENCLIENT002",
    )
    # The seat, as another install knows them.
    foreign = await plugin_refs.ensure_plugin_ref(
        guild_id=guild_id,
        public_id=other.definition["service"]["public_id"],
        user_id=installed.seat.user.id,
    )

    for named in (foreign, installed.seat.user.id, "uplu_" + "x" * 32):
        response = await client.put(
            guild_url(guild_id, f"/properties/file/{file_id}"),
            headers=headers,
            json={"values": [{"property_id": owner.id, "value": named}]},
        )
        assert response.status_code == 422, (named, response.text)
        assert response.json()["detail"] == PluginMessages.REFERENCE_UNKNOWN


async def test_a_file_list_filter_that_names_a_person_is_refused(
    client, session, acting_user, role_session
):
    scopes = ["files:read", "files:write", "initiatives:read", "members:read"]
    installed = await install_plugin(session, acting_user, role_session, granted=scopes)
    headers = install_headers(installed, scopes)
    guild_id = installed.guild.id
    await _file(client, session, installed, headers)
    owner = await create_property_definition(
        session, installed.placed, name="Owner", type=PropertyType.user_reference
    )

    def _filters(op: str, value: Any) -> dict:
        return {
            "property_filters": json.dumps(
                [{"property_id": owner.id, "op": op, "value": value}]
            )
        }

    named = await client.get(
        guild_url(guild_id, "/files/"),
        headers=headers,
        params=_filters("eq", installed.seat.user.id),
    )
    assert named.status_code == 400, named.text
    assert named.json()["detail"] == QueryMessages.INVALID_CONDITIONS

    # Asking whether anyone is set names nobody.
    unset = await client.get(
        guild_url(guild_id, "/files/"),
        headers=headers,
        params=_filters("is_null", True),
    )
    assert unset.status_code == 200, unset.text

    # A person filters by the row id as before.
    as_person = await client.get(
        guild_url(guild_id, "/files/"),
        headers=installed.seat.headers,
        params=_filters("eq", installed.seat.user.id),
    )
    assert as_person.status_code == 200, as_person.text


async def test_a_collections_fields_are_written_with_the_files_scope(
    client, session, acting_user, role_session
):
    scopes = ["files:write", "properties:write"]
    installed = await install_plugin(session, acting_user, role_session, granted=scopes)
    files = install_headers(installed, ["files:write"])
    file_id = await _file(client, session, installed, files)
    collection = await client.post(
        guild_url(installed.guild.id, "/collections/"),
        headers=files,
        json={
            "initiative_id": installed.placed.id,
            "name": "The plug-in's",
            "file_ids": [file_id],
        },
    )
    assert collection.status_code == 201, collection.text
    collection_id = collection.json()["id"]
    url = guild_url(installed.guild.id, "/property-definitions/")
    body = {
        "initiative_id": installed.placed.id,
        "collection_id": collection_id,
        "name": "Score",
        "type": "scale",
    }

    refused = await client.post(
        url, headers=install_headers(installed, ["properties:write"]), json=body
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == PluginMessages.SCOPE_REQUIRED

    created = await client.post(url, headers=files, json=body)
    assert created.status_code == 201, created.text
    written = await client.put(
        guild_url(
            installed.guild.id,
            f"/collections/{collection_id}/files/{file_id}/fields",
        ),
        headers=files,
        json={"values": [{"property_id": created.json()["id"], "value": 42}]},
    )
    assert written.status_code == 200, written.text
    assert [v["value"] for v in written.json()] == [42]
