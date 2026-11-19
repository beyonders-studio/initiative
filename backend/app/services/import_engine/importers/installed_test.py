"""The tool plug-in importer, over the Counters fixture: a group exported from
its declaration comes back in another initiative with its counters, fields,
tags, property values and links, and is refused where the tool is not
installed, not placed, or not the importer's to create. A backup restored
into an initiative it makes places the tool there, or leaves its content out
where the restorer may not place it. Who outside an
initiative imports nothing into it is the boundary sweep's
(``app.db.initiative_boundary_test``)."""

from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa

from app.core.messages import ImportEngineMessages
from app.core.relationships import node_of
from app.core.rules import SURFACE_PLUGINS, SetBy
from app.db.plugin_tools import provisioned_tools
from app.models.platform.guild import CommunityRole
from app.models.tenant.data_job import DataJobStatus
from app.models.tenant.relationship import EntityRelationship
from app.services.platform import rules
from app.services.tenant import metadata as metadata_service
from app.services.tenant import tags as tags_service
from app.testing import COUNTERS_UID, install_tool_plugin
from app.testing.factories import (
    create_initiative,
    create_property_definition,
    create_tag,
    route_session_to_guild,
)

GROUP = f"counter_group.{COUNTERS_UID.lower()}"
COUNTER = f"counter.{COUNTERS_UID.lower()}"


async def _counters(client: Any, session: Any, acting_user: Any) -> tuple[Any, ...]:
    """Counters installed in a community and placed in two of its
    initiatives, the first's manager's and a target they also manage: the
    manager, the seat, the install and the target."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    target = await create_initiative(session, a.guild, a.user, name="Import Target")
    seat = await acting_user(guild=a.guild, guild_role=CommunityRole.superadmin)
    install = await install_tool_plugin(client, session, seat)
    await _place(client, seat, install, [a.initiative.id, target.id])
    return a, seat, install, target


async def _place(client: Any, seat: Any, install: Any, initiatives: list[int]) -> None:
    response = await client.patch(
        seat.g(f"/plugins/{install['id']}"),
        headers=seat.headers,
        json={"placed_initiative_ids": initiatives},
    )
    assert response.status_code == 200, response.text


async def _import(client: Any, actor: Any, envelope: Any, initiative_id: int) -> Any:
    return await client.post(
        actor.g("/imports/envelope"),
        headers=actor.headers,
        json={"initiative_id": initiative_id, "envelope": envelope},
    )


async def test_a_tool_plugins_row_round_trips_into_another_initiative(
    client, session, acting_user
):
    a, _seat, _install, target = await _counters(client, session, acting_user)

    async def call(method: str, path: str, body: Any) -> Any:
        response = await client.request(method, a.g(path), headers=a.headers, json=body)
        assert response.status_code in (200, 201), (path, response.text)
        return response.json()

    group = await call(
        "POST",
        f"/plugin-tools/{GROUP}/",
        {
            "initiative_id": a.initiative.id,
            "name": "Party",
            "fields": {"description": f"Kept by @[]({a.user.id})"},
        },
    )
    gold, silver = [
        await call(
            "POST",
            f"/plugin-tools/{COUNTER}/",
            {"parent_id": group["id"], "name": name, "fields": fields},
        )
        for name, fields in (
            ("Gold", {"max": 100, "count": 12}),
            ("Silver", {"count": 3.5}),
        )
    ]
    loot = await create_tag(session, a.guild, name="Loot")
    note = await create_property_definition(session, a.initiative, name="Note")
    await session.commit()
    await call("PUT", f"/tools/{GROUP}/{group['id']}/tags", {"tag_ids": [loot.id]})
    await call(
        "POST",
        "/tags/bulk",
        {"target_type": COUNTER, "target_ids": [gold["id"]], "add_tag_ids": [loot.id]},
    )
    await call(
        "PUT",
        f"/properties/{GROUP}/{group['id']}",
        {"values": [{"property_id": note.id, "value": "Shared"}]},
    )
    await call(
        "POST",
        "/relationships/",
        {
            "source": {"type": COUNTER, "id": gold["id"]},
            "relationship_type": "depends_on",
            "target": {"type": COUNTER, "id": silver["id"]},
        },
    )

    response = await client.get(
        a.g(f"/exports/{GROUP}"),
        headers=a.headers,
        params={"ids": [group["id"]], "format": "json"},
    )
    assert response.status_code == 200, response.text
    envelope = response.json()
    assert envelope["fields"]["description"].startswith("Kept by @")
    assert envelope["mention_handles"]

    response = await _import(client, a, envelope, target.id)
    assert response.status_code == 201, response.text
    result = response.json()["result"]
    assert result["created"]["counter_group"] == 1
    assert result["created"]["counter"] == 2
    assert result["links_created"] == 1
    # The tag is the community's; the property is made in the target, as
    # properties are each initiative's.
    assert result["matched"] == {"tags": 1, "properties": 0}
    assert result["created"]["properties"] == 1

    tools = await provisioned_tools(a.guild.id)
    (tool,) = tools.installed
    (counters,) = tool.items
    await route_session_to_guild(session, a.guild.id)
    made = (
        await session.exec(
            sa.select(tool.table).where(tool.table.c.initiative_id == target.id)
        )
    ).one()
    assert (made.name, made.description) == ("Party", f"Kept by @[]({a.user.id})")
    items = (
        await session.exec(
            sa.select(counters)
            .where(counters.c.counter_group_id == made.id)
            .order_by(counters.c.position)
        )
    ).all()
    assert [(i.name, float(i.count), i.max) for i in items] == [
        ("Gold", 12, 100),
        ("Silver", 3.5, None),
    ]
    links = tags_service.tag_links(tools)
    assert [
        t.name
        for t in (await tags_service.tags_for(session, links[GROUP], [made.id]))[
            made.id
        ]
    ] == ["Loot"]
    assert [
        t.name
        for t in (await tags_service.tags_for(session, links[COUNTER], [items[0].id]))[
            items[0].id
        ]
    ] == ["Loot"]
    (value,) = (await metadata_service.summaries_by_id(session, GROUP, [made.id]))[
        made.id
    ]
    assert (value.name, value.value) == ("Note", "Shared")
    code = tools.kind_codes[COUNTER]
    edge = (
        await session.exec(
            sa.select(EntityRelationship).where(
                EntityRelationship.source_node == node_of(code, items[0].id),
                EntityRelationship.removed_at.is_(None),
                EntityRelationship.relationship_type == "depends_on",
            )
        )
    ).scalar_one()
    assert edge.target_node == node_of(code, items[1].id)


async def test_a_tool_plugins_envelope_is_refused_where_it_cannot_be_made(
    client, session, acting_user
):
    a, seat, install, target = await _counters(client, session, acting_user)
    group = await client.post(
        a.g(f"/plugin-tools/{GROUP}/"),
        headers=a.headers,
        json={"initiative_id": a.initiative.id, "name": "Party"},
    )
    response = await client.get(
        a.g(f"/exports/{GROUP}"),
        headers=a.headers,
        params={"ids": [group.json()["id"]], "format": "json"},
    )
    envelope = response.json()

    async def refusal(actor: Any, body: Any, initiative_id: int) -> tuple:
        response = await _import(client, actor, body, initiative_id)
        return response.status_code, response.json()["detail"]

    # A kind the community has not installed.
    stranger = {**envelope, "type": f"initiative-counter_group.{'x' * 14}"}
    assert await refusal(a, stranger, target.id) == (
        400,
        ImportEngineMessages.IMPORT_UNKNOWN_TYPE,
    )
    # An initiative the tool is not placed in.
    await _place(client, seat, install, [a.initiative.id])
    assert await refusal(a, envelope, target.id) == (
        400,
        ImportEngineMessages.IMPORT_TOOL_DISABLED,
    )
    # A member whose role does not create the tool.
    member = await acting_user(
        guild=a.guild, initiative=a.initiative, initiative_role="member"
    )
    assert await refusal(member, envelope, a.initiative.id) == (
        403,
        ImportEngineMessages.IMPORT_PERMISSION_REQUIRED,
    )
    assert (await _import(client, a, envelope, a.initiative.id)).status_code == 201


async def _restore(
    client: Any, seat: Any, monkeypatch: Any, role_session: Any
) -> dict[str, Any]:
    """A backup holding one Counters group, restored by ``seat`` into the new
    initiative the restore makes: the finished job."""
    from app.api.v1.tenant_endpoints.imports_test import (
        _apply_backup,
        _make_backup_zip,
        _minimal_manifest,
    )

    envelope = {
        "type": f"initiative-{GROUP}",
        "schema_version": 1,
        "name": "Party",
        "items": {"counter": [{"name": "Gold", "fields": {"count": 12}}]},
    }
    entry = {
        "path": f"initiatives/1-restored/{GROUP}/1-party.json",
        "tool": GROUP,
        "type": envelope["type"],
        "schema_version": 1,
        "entity_id": 1,
        "title": "Party",
        "initiative_id": 1,
    }
    archive = _make_backup_zip(
        _minimal_manifest(entries=[entry]),
        {entry["path"]: json.dumps(envelope).encode()},
    )
    job = await _apply_backup(client, seat, archive, monkeypatch, role_session)
    assert job["status"] == DataJobStatus.done.value, job.get("error")
    return job


async def test_a_restore_places_a_tool_plugin_in_the_initiative_it_makes(
    client, session, acting_user, monkeypatch, role_session
):
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    install = await install_tool_plugin(
        client, session, seat, placements=[seat.initiative.id]
    )

    job = await _restore(client, seat, monkeypatch, role_session)
    (made,) = job["result"]["initiatives"]
    (entry,) = job["result"]["entries"]
    assert entry["status"] == "created", entry

    response = await client.get(
        seat.g(f"/plugins/{install['id']}"), headers=seat.headers
    )
    assert response.json()["placed_initiative_ids"] == sorted(
        [seat.initiative.id, made["initiative_id"]]
    )
    (tool,) = (await provisioned_tools(seat.guild.id)).installed
    await route_session_to_guild(session, seat.guild.id)
    (group,) = (
        await session.exec(
            sa.select(tool.table).where(
                tool.table.c.initiative_id == made["initiative_id"]
            )
        )
    ).all()
    assert group.name == "Party"


async def test_a_restore_leaves_out_a_tool_plugin_it_may_not_place(
    client, session, acting_user, monkeypatch, role_session
):
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    install = await install_tool_plugin(
        client, session, seat, placements=[seat.initiative.id]
    )
    await rules.put(
        session, SURFACE_PLUGINS, False, guild_id=seat.guild.id, set_by=SetBy.deployment
    )
    await session.commit()

    job = await _restore(client, seat, monkeypatch, role_session)
    (entry,) = job["result"]["entries"]
    assert (entry["status"], entry["error"]) == (
        "skipped",
        ImportEngineMessages.IMPORT_TOOL_NOT_PLACED,
    )
    response = await client.get(
        seat.g(f"/plugins/{install['id']}"), headers=seat.headers
    )
    assert response.json()["placed_initiative_ids"] == [seat.initiative.id]
