"""The tool plug-in routes, over the Counters fixture: a tool's rows and its
items made, changed, listed, copied and acted on as its declaration says, and
reached by an installed plug-in with the tool's scope and not without it.
Who outside an initiative reaches none of it is the boundary sweep's
(``app.db.initiative_boundary_test``)."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Any

from sqlmodel import select

from app.core.messages import KindMessages, PluginMessages, ToolPluginMessages
from app.db import plugin_tools
from app.db import session as db_session
from app.db.session import require_guild_context
from app.models.platform.guild import CommunityRole
from app.models.platform.notice_outbox import NoticeOutboxItem
from app.models.platform.notification import NotificationType
from app.schemas.tenant.plugin_tool import PluginToolActionRun
from app.services.tenant import plugin_tool_rows as rows_service
from app.testing import (
    COUNTERS_UID,
    counters_tool_manifest,
    create_tag,
    guild_url,
    install_tool_plugin,
)
from app.testing.plugin_clients import install_headers, install_plugin

GROUP = f"counter_group.{COUNTERS_UID.lower()}"
COUNTER = f"counter.{COUNTERS_UID.lower()}"


def _with_more(manifest: dict[str, Any]) -> dict[str, Any]:
    """Counters, with a checkbox on each counter and an action adding one to
    a counter and to every counter in a group."""
    tool = manifest["tool"]
    (counter,) = tool["items"]
    counter["fields"].append(
        {"key": "done", "name": {"en": "Done"}, "kind": "checkbox"}
    )
    tool["actions"] += [
        {
            "id": "add_one",
            "name": {"en": "Add one"},
            "on": "counter",
            "write": '{"set": {"count": item.count + 1}}',
        },
        {
            "id": "add_all",
            "name": {"en": "Add one to each"},
            "on": "counter_group",
            "write": '{"items": {"counter": [items.counter.{"id": id, '
            '"set": {"count": count + 1}}]}}',
        },
    ]
    return manifest


async def _counters(
    client: Any, session: Any, acting_user: Any, definition: Any = None
) -> tuple[Any, Any]:
    """A community with Counters installed: a moderator of its initiative,
    and a member of it."""
    moderator = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    member = await acting_user(guild=moderator.guild, initiative=moderator.initiative)
    seat = await acting_user(guild=moderator.guild, guild_role=CommunityRole.superadmin)
    await install_tool_plugin(client, session, seat, definition=definition)
    return moderator, member


async def test_an_initiatives_creator_adds_a_row_after_the_install(
    client, session, acting_user
):
    """The member who made an initiative, who holds no share override, adds
    a row of a tool installed after it was made, and an item inside it, and
    reads them as their owner."""
    creator = await acting_user(guild_role=CommunityRole.member, initiative=True)
    seat = await acting_user(guild=creator.guild, guild_role=CommunityRole.superadmin)
    await install_tool_plugin(client, session, seat)

    async def made(path: str, body: Any) -> dict[str, Any]:
        response = await client.post(
            creator.g(f"/plugin-tools/{path}"), headers=creator.headers, json=body
        )
        assert response.status_code == 201, (path, response.text)
        return response.json()

    group = await made(
        f"{GROUP}/", {"initiative_id": creator.initiative.id, "name": "G"}
    )
    await made(f"{COUNTER}/", {"parent_id": group["id"], "name": "HP"})
    response = await client.get(
        creator.g(f"/plugin-tools/{GROUP}/{group['id']}"), headers=creator.headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["can"]["share"] is True


async def test_a_new_row_starts_as_declared_and_actions_side_by_side_both_land(
    client, session, acting_user, reading_as
):
    a, _member = await _counters(
        client, session, acting_user, _with_more(counters_tool_manifest())
    )

    async def call(path: str, body: Any = None) -> Any:
        response = await client.post(
            a.g(f"/plugin-tools/{path}"), headers=a.headers, json=body
        )
        assert response.status_code in (200, 201), (path, response.text)
        return response.json()

    group = await call(f"{GROUP}/", {"initiative_id": a.initiative.id, "name": "G"})
    counter = await call(f"{COUNTER}/", {"parent_id": group["id"], "name": "HP"})
    assert counter["fields"]["done"] is False
    assert counter["fields"]["count"] == 0

    async def run(kind: str, row_id: int, action_id: str) -> None:
        """Run an action on a connection of its own, as two requests do."""
        own = await reading_as(a.user.id, a.guild.id)
        context = require_guild_context(own)
        located = rows_service.located_kind(context.tools, kind)
        row = await rows_service.load_authorized(
            own,
            context,
            located,
            context.tools,
            row_id,
            action=rows_service.writing(located),
        )
        await rows_service.run_action(
            own,
            context,
            located,
            context.tools,
            row,
            action_id,
            PluginToolActionRun(),
            author=None,
        )
        await own.commit()

    await asyncio.gather(
        run(GROUP, group["id"], "add_all"), run(COUNTER, counter["id"], "add_one")
    )
    read = await client.get(
        a.g(f"/plugin-tools/{COUNTER}/{counter['id']}"), headers=a.headers
    )
    assert read.json()["fields"]["count"] == 2


async def test_rows_are_made_changed_listed_copied_and_acted_on(
    client, session, acting_user
):
    a, member = await _counters(client, session, acting_user)

    async def call(method: str, path: str, body: Any = None) -> Any:
        response = await client.request(
            method, a.g(f"/plugin-tools/{path}"), headers=a.headers, json=body
        )
        assert response.status_code in (200, 201), (path, response.text)
        return response.json()

    group = await call(
        "POST",
        f"{GROUP}/",
        {
            "initiative_id": a.initiative.id,
            "name": "Party",
            "fields": {"description": f"For @[Bo]({member.user.id})"},
        },
    )
    assert group["fields"] == {"description": f"For @[]({member.user.id})"}
    assert group["can"]["edit"] and group["grants"]
    notices = (
        await session.exec(
            select(NoticeOutboxItem).where(
                NoticeOutboxItem.user_id == member.user.id,
                NoticeOutboxItem.type == NotificationType.mention.value,
            )
        )
    ).all()
    assert [(n.data["entity_type"], n.data["target_path"]) for n in notices] == [
        (GROUP, f"/i/{a.initiative.id}/t/{GROUP}/{group['id']}")
    ]

    counter = await call(
        "POST",
        f"{COUNTER}/",
        {"parent_id": group["id"], "name": "HP", "fields": {"max": 5, "count": 9}},
    )
    assert counter["parent_id"] == group["id"]
    assert counter["fields"]["count"] == 5
    assert counter["fields"]["step"] == 1
    assert counter["fields"]["view_mode"] == "number"
    changed = await call("PATCH", f"{COUNTER}/{counter['id']}", {"fields": {"max": 3}})
    assert changed["fields"]["count"] == 3

    listed = await call("GET", f"{COUNTER}/?parent_id={group['id']}")
    assert [row["id"] for row in listed["items"]] == [counter["id"]]
    listed = await call("GET", f"{GROUP}/?initiative_id={a.initiative.id}")
    assert [row["id"] for row in listed["items"]] == [group["id"]]
    assert listed["items"][0]["preview"] is None
    previewed = await call(
        "GET", f"{GROUP}/?initiative_id={a.initiative.id}&include_preview=true"
    )
    (preview,) = (row["preview"] for row in previewed["items"])
    assert {kind: [row["id"] for row in rows] for kind, rows in preview.items()} == {
        COUNTER: [counter["id"]]
    }

    await call("POST", f"{GROUP}/{group['id']}/actions/reset_all")
    read = await call("GET", f"{COUNTER}/{counter['id']}")
    assert read["fields"]["count"] == 0

    copy = await call("POST", f"{GROUP}/{group['id']}/duplicate")
    assert copy["name"] == "Party (Copy)"
    copied = await call("GET", f"{COUNTER}/?parent_id={copy['id']}")
    assert [row["name"] for row in copied["items"]] == ["HP"]
    beside = await call("POST", f"{COUNTER}/{counter['id']}/duplicate")
    assert (beside["name"], beside["parent_id"]) == ("HP (Copy)", group["id"])


async def test_rows_are_tagged_and_trashed_as_a_built_in_tools_are(
    client, session, acting_user
):
    """A row and its items carry the tags they are made or changed with, and
    go to the trash: a tool's row on the delete right, an item on what
    changing it asks, with the comments others said on them. The trash lists
    both and puts them back, and the initiative goes with them in it."""
    a, member = await _counters(client, session, acting_user)
    tag = await create_tag(session, a.guild, name="Boss")

    async def call(who: Any, method: str, path: str, body: Any = None) -> Any:
        return await client.request(
            method, who.g(f"/plugin-tools/{path}"), headers=who.headers, json=body
        )

    group = (
        await call(
            a, "POST", f"{GROUP}/", {"initiative_id": a.initiative.id, "name": "G"}
        )
    ).json()
    counter = (
        await call(
            a,
            "POST",
            f"{COUNTER}/",
            {"parent_id": group["id"], "name": "HP", "tag_ids": [tag.id]},
        )
    ).json()
    assert [each["name"] for each in counter["tags"]] == ["Boss"]
    changed = await call(a, "PATCH", f"{GROUP}/{group['id']}", {"tag_ids": [tag.id]})
    assert changed.status_code == 200, changed.text
    assert [each["id"] for each in changed.json()["tags"]] == [tag.id]
    changed = await call(a, "PATCH", f"{COUNTER}/{counter['id']}", {"tag_ids": []})
    assert changed.json()["tags"] == []

    for kind, row in ((COUNTER, counter), (GROUP, group)):
        said = await client.post(
            member.g("/comments/"),
            headers=member.headers,
            json={"subject_type": kind, "subject_id": row["id"], "content": "Hi"},
        )
        assert said.status_code == 201, said.text
        refused = await call(member, "DELETE", f"{kind}/{row['id']}")
        assert refused.status_code in (403, 404), refused.text
    trashed = await call(a, "DELETE", f"{COUNTER}/{counter['id']}")
    assert trashed.status_code == 204, trashed.text
    assert (await call(a, "GET", f"{COUNTER}/{counter['id']}")).status_code == 404
    trashed = await call(a, "DELETE", f"{GROUP}/{group['id']}")
    assert trashed.status_code == 204, trashed.text

    listing = await client.get(a.g("/trash/"), headers=a.headers)
    assert {
        (item["entity_type"], item["entity_id"]) for item in listing.json()["items"]
    } == {(GROUP, group["id"]), (COUNTER, counter["id"])}
    restored = await client.post(
        a.g(f"/trash/{GROUP}/{group['id']}/restore"), headers=a.headers
    )
    assert restored.status_code == 200, restored.text
    assert (await call(a, "GET", f"{GROUP}/{group['id']}")).status_code == 200
    gone = await client.delete(
        a.g(f"/initiatives/{a.initiative.id}"), headers=a.headers
    )
    assert gone.status_code == 204, gone.text


async def test_values_and_places_are_held_to_the_declaration(
    client, session, acting_user
):
    a, member = await _counters(client, session, acting_user)
    created = await client.post(
        a.g(f"/plugin-tools/{GROUP}/"),
        headers=a.headers,
        json={"initiative_id": a.initiative.id, "name": "Party"},
    )
    group = created.json()

    async def refused(method: str, path: str, body: Any = None) -> tuple[int, Any]:
        response = await client.request(
            method, a.g(f"/plugin-tools/{path}"), headers=a.headers, json=body
        )
        return response.status_code, response.json().get("detail")

    item = {"parent_id": group["id"], "name": "HP"}
    invalid = (422, ToolPluginMessages.FIELD_INVALID)
    for fields in (
        {"view_mode": "dial"},
        {"nothing": 1},
        {"count": None},
        {"color": "red"},
        {"count": 1e12},
        # Its required fields and its checks.
        {"step": None},
        {"step": 0},
        {"min": 5, "max": 1},
    ):
        assert await refused("POST", f"{COUNTER}/", {**item, "fields": fields}) == (
            invalid
        ), fields
    assert await refused(
        "POST", f"{COUNTER}/", {**item, "people": {"count": member.user.id}}
    ) == (invalid)
    placement = (422, ToolPluginMessages.PLACEMENT_INVALID)
    assert (
        await refused("POST", f"{COUNTER}/", {"initiative_id": 1, "name": "X"})
        == placement
    )
    assert (
        await refused("POST", f"{GROUP}/", {"parent_id": group["id"], "name": "X"})
        == placement
    )
    assert await refused("GET", f"stranger.{'x' * 14}/1") == (
        404,
        KindMessages.NOT_FOUND,
    )
    assert await refused("POST", f"{GROUP}/{group['id']}/actions/nope") == (
        404,
        ToolPluginMessages.ACTION_NOT_FOUND,
    )


async def test_an_installed_plugin_reaches_the_tool_by_its_scopes(
    client, session, acting_user, role_session, monkeypatch
):
    write, read = f"{GROUP}:write", f"{GROUP}:read"
    installed = await install_plugin(
        session, acting_user, role_session, granted=[write], requested=[write]
    )
    await install_tool_plugin(client, session, installed.seat)
    # Cold: this process keeps no tool set, so the install's request builds
    # its community's.
    monkeypatch.setattr(plugin_tools, "_SETS", OrderedDict())
    monkeypatch.setattr(db_session, "_INSTALL_TOOLS", {})
    url = guild_url(installed.guild.id, f"/plugin-tools/{GROUP}/")
    body = {"initiative_id": installed.placed.id, "name": "Made by the plug-in"}

    response = await client.post(
        url, headers=install_headers(installed, ["projects:read"]), json=body
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == PluginMessages.SCOPE_REQUIRED

    response = await client.post(
        url, headers=install_headers(installed, [write]), json=body
    )
    assert response.status_code == 201, response.text
    made = response.json()
    assert made["created_by_kind"] == "plugin"
    response = await client.get(
        guild_url(installed.guild.id, f"/plugin-tools/{GROUP}/{made['id']}"),
        headers=install_headers(installed, [read]),
    )
    assert response.status_code == 200, response.text

    # Its declaration is read with its read scope, and a step needs its write.
    declared = guild_url(installed.guild.id, f"/plugin-tools/{COUNTER}")
    response = await client.get(declared, headers=install_headers(installed, [read]))
    assert response.status_code == 200, response.text
    assert response.json()["kind"] == GROUP
    response = await client.get(
        declared, headers=install_headers(installed, ["projects:read"])
    )
    assert response.status_code == 403, response.text
    counter = await client.post(
        guild_url(installed.guild.id, f"/plugin-tools/{COUNTER}/"),
        headers=install_headers(installed, [write]),
        json={"parent_id": made["id"], "name": "Laps"},
    )
    assert counter.status_code == 201, counter.text
    step = guild_url(
        installed.guild.id, f"/plugin-tools/{COUNTER}/{counter.json()['id']}/step"
    )
    response = await client.post(
        step, headers=install_headers(installed, [read]), json={"field": "count"}
    )
    assert response.status_code == 403, response.text
    response = await client.post(
        step, headers=install_headers(installed, [write]), json={"field": "count"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["fields"]["count"] == 1

    response = await client.post(
        url,
        headers=install_headers(installed, [write]),
        json={**body, "initiative_id": installed.unplaced.id},
    )
    assert response.status_code in (403, 404), response.text


async def test_a_tool_off_where_its_row_is_refuses_the_universal_routes(
    client: Any, session: Any, acting_user: Any
):
    """A universal route refuses a tool plug-in's row in an initiative its
    tool is switched off in, or not placed in, to the community's admin, as
    it refuses a switched-off built-in tool's."""
    from app.core.tools import Tool
    from app.services.tenant.initiative_tools import write_switches
    from app.testing import add_counter, create_initiative, create_project
    from app.testing.schema_harness import route_session_to_guild

    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    guild, initiative = admin.guild, admin.initiative
    elsewhere = await create_initiative(session, guild, admin.user)
    project = await create_project(session, initiative, admin.user)
    await session.commit()
    seat = await acting_user(guild=guild, guild_role=CommunityRole.superadmin)
    install = await install_tool_plugin(client, session, seat)
    tools, group, _ = await add_counter(session, guild.id, initiative.id)
    (tool,) = tools.installed

    async def refused(kind: str, row_id: int) -> None:
        response = await client.put(
            admin.g(f"/tools/{kind}/{row_id}/comments"),
            headers=admin.headers,
            json={"comments_enabled": False},
        )
        assert response.status_code == 403, (kind, response.text)
        assert response.json()["detail"] == KindMessages.TOOL_NOT_ENABLED, kind

    await route_session_to_guild(session, guild.id)
    await write_switches(session, initiative.id, {Tool.project: False})
    await write_switches(session, initiative.id, {tool: False})
    await session.commit()
    await refused(Tool.project.value, project.id)
    await refused(tool.kind, group)

    await route_session_to_guild(session, guild.id)
    await write_switches(session, initiative.id, {tool: True})
    await session.commit()
    placed = await client.patch(
        seat.g(f"/plugins/{install['id']}"),
        headers=seat.headers,
        json={"placed_initiative_ids": [elsewhere.id]},
    )
    assert placed.status_code == 200, placed.text
    await refused(tool.kind, group)


async def test_an_admin_outside_the_initiative_is_refused_an_unplaced_tools_row(
    client: Any, session: Any, acting_user: Any
):
    """A community admin who is not in the row's initiative changes a tool
    plug-in's row through a universal route while its install is placed
    there, and is refused once it is not, as for a switched-off tool."""
    from app.testing import add_counter, create_initiative

    member = await acting_user(guild_role=CommunityRole.member, initiative=True)
    guild, initiative = member.guild, member.initiative
    elsewhere = await create_initiative(session, guild, member.user)
    await session.commit()
    admin = await acting_user(guild=guild, guild_role=CommunityRole.admin)
    seat = await acting_user(guild=guild, guild_role=CommunityRole.superadmin)
    install = await install_tool_plugin(client, session, seat)
    tools, group, _ = await add_counter(session, guild.id, initiative.id)
    (tool,) = tools.installed

    def comments() -> Any:
        return client.put(
            admin.g(f"/tools/{tool.kind}/{group}/comments"),
            headers=admin.headers,
            json={"comments_enabled": False},
        )

    response = await comments()
    assert response.status_code == 200, response.text

    placed = await client.patch(
        seat.g(f"/plugins/{install['id']}"),
        headers=seat.headers,
        json={"placed_initiative_ids": [elsewhere.id]},
    )
    assert placed.status_code == 200, placed.text
    response = await comments()
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == KindMessages.TOOL_NOT_ENABLED


def _with_a_capped_count(manifest: dict[str, Any]) -> dict[str, Any]:
    """Counters, whose counts are never above 4, as a check of its table."""
    (counter,) = manifest["tool"]["items"]
    counter["checks"].append({"field": "count", "at_most": 4})
    return manifest


async def test_a_counter_field_steps_within_its_bounds_and_two_steps_both_count(
    client, session, acting_user, reading_as
):
    a, _member = await _counters(
        client, session, acting_user, _with_a_capped_count(counters_tool_manifest())
    )

    async def call(method: str, path: str, body: Any = None) -> Any:
        response = await client.request(
            method, a.g(f"/plugin-tools/{path}"), headers=a.headers, json=body
        )
        assert response.status_code in (200, 201), (path, response.text)
        return response.json()

    group = await call(
        "POST", f"{GROUP}/", {"initiative_id": a.initiative.id, "name": "G"}
    )
    hp = await call(
        "POST",
        f"{COUNTER}/",
        {
            "parent_id": group["id"],
            "name": "HP",
            "fields": {"min": 0, "max": 3, "step": 2},
        },
    )
    at = f"{COUNTER}/{hp['id']}/step"

    async def count(body: dict[str, Any]) -> Any:
        stepped = await call("POST", at, body)
        assert stepped["id"] == hp["id"]
        return stepped["fields"]["count"]

    # By its own step, held to its own max and min; by a signed amount.
    assert await count({"field": "count"}) == 2
    assert await count({"field": "count"}) == 3
    assert await count({"field": "count", "down": True}) == 1
    assert await count({"field": "count", "by": -100}) == 0
    assert await count({"field": "count", "by": 0.5}) == 0.5

    async def refused(path: str, body: dict[str, Any]) -> tuple[int, Any]:
        response = await client.post(
            a.g(f"/plugin-tools/{path}"), headers=a.headers, json=body
        )
        return response.status_code, response.json().get("detail")

    invalid = (422, ToolPluginMessages.FIELD_INVALID)
    for body in (
        {"field": "step"},
        {"field": "nothing"},
        {"field": "count", "by": 1e12},
    ):
        assert await refused(at, body) == invalid, body
    assert await refused(f"{GROUP}/{group['id']}/step", {"field": "count"}) == invalid
    status, _ = await refused(at, {"field": "count", "by": 1, "down": True})
    assert status == 422

    # A step past a check of the table is refused, and changes nothing.
    mp = await call("POST", f"{COUNTER}/", {"parent_id": group["id"], "name": "MP"})
    assert await refused(
        f"{COUNTER}/{mp['id']}/step", {"field": "count", "by": 10}
    ) == (invalid)
    read = await call("GET", f"{COUNTER}/{mp['id']}")
    assert read["fields"]["count"] == 0

    async def stepped() -> None:
        """One step, on a connection of its own, as two requests make them."""
        own = await reading_as(a.user.id, a.guild.id)
        context = require_guild_context(own)
        located = rows_service.located_kind(context.tools, COUNTER)
        await rows_service.step(own, located, mp["id"], "count")
        await own.commit()

    await asyncio.gather(stepped(), stepped())
    read = await call("GET", f"{COUNTER}/{mp['id']}")
    assert read["fields"]["count"] == 2


async def test_a_tool_is_read_as_its_plugin_declares_it(client, session, acting_user):
    a, _member = await _counters(client, session, acting_user)

    response = await client.get(a.g(f"/plugin-tools/{GROUP}"), headers=a.headers)
    assert response.status_code == 200, response.text
    tool = response.json()
    assert (tool["kind"], tool["key"], tool["icon"]) == (
        GROUP,
        "counter_group",
        "gauge",
    )
    assert (tool["name"], tool["instance_name"]) == (
        {"en": "Counters"},
        {"en": "Counter group"},
    )
    assert [field["key"] for field in tool["fields"]] == ["description"]
    (item,) = tool["items"]
    assert (item["kind"], item["key"], item["parent"]) == (COUNTER, "counter", GROUP)
    fields = {field["key"]: field for field in item["fields"]}
    assert fields["count"]["kind"] == "counter"
    assert fields["count"]["counter"] == {
        "min": "min",
        "max": "max",
        "step": "step",
        "initial": "initial_count",
    }
    look = fields["view_mode"]
    assert (look["kind"], look["default"], look["required"]) == (
        "select",
        "number",
        True,
    )
    assert [option["value"] for option in look["options"]] == ["number", "bar", "clock"]
    (action,) = tool["actions"]
    assert (action["id"], action["on"], action["params"]) == ("reset_all", GROUP, [])
    assert action["confirm"]
    # Neither its layouts nor what an action writes.
    assert "layouts" not in tool and "layouts" not in item and "write" not in action

    # By an item's kind, the tool it sits in.
    by_item = await client.get(a.g(f"/plugin-tools/{COUNTER}"), headers=a.headers)
    assert by_item.json() == tool

    # A member of no initiative reaches it in none, and an unknown kind is no tool.
    outsider = await acting_user(guild=a.guild)
    response = await client.get(
        outsider.g(f"/plugin-tools/{GROUP}"), headers=outsider.headers
    )
    assert response.status_code == 404, response.text
    response = await client.get(
        a.g(f"/plugin-tools/stranger.{'x' * 14}"), headers=a.headers
    )
    assert response.status_code == 404, response.text


async def test_leaving_an_initiative_takes_the_person_off_its_rows(
    client, session, acting_user
):
    """A person field names a member while they are in the row's initiative:
    removed from it, they are taken off its rows, and the others stay. A row
    in the trash keeps them, as archived or trashed content does."""
    definition = counters_tool_manifest()
    definition["tool"]["fields"].append(
        {"key": "keeper", "name": {"en": "Keeper"}, "kind": "user_reference"}
    )
    a, member = await _counters(client, session, acting_user, definition)

    async def group(keeper: int) -> int:
        made = await client.post(
            a.g(f"/plugin-tools/{GROUP}/"),
            headers=a.headers,
            json={
                "initiative_id": a.initiative.id,
                "name": "G",
                "people": {"keeper": keeper},
            },
        )
        assert made.status_code == 201, made.text
        return made.json()["id"]

    theirs, mine = await group(member.user.id), await group(a.user.id)
    binned = await group(member.user.id)
    trashed = await client.delete(
        a.g(f"/plugin-tools/{GROUP}/{binned}"), headers=a.headers
    )
    assert trashed.status_code == 204, trashed.text
    removed = await client.delete(
        a.g(f"/initiatives/{a.initiative.id}/members/{member.user.id}"),
        headers=a.headers,
    )
    assert removed.status_code == 204, removed.text
    restored = await client.post(
        a.g(f"/trash/{GROUP}/{binned}/restore"), headers=a.headers
    )
    assert restored.status_code == 200, restored.text
    for row, keeper in ((theirs, None), (mine, a.user.id), (binned, member.user.id)):
        read = await client.get(a.g(f"/plugin-tools/{GROUP}/{row}"), headers=a.headers)
        assert read.json()["people"].get("keeper") == keeper, read.text


def test_reading_a_tool_leaves_its_declaration_as_declared():
    """A read validates a copy, so the community's kept declaration keeps its
    text as declared for every later row."""
    import copy

    from app.db.tool_rows import locate
    from app.services.marketplace.tool_plugins import (
        normalize_tool_plugin_definition,
        tool_kinds,
    )

    manifest = counters_tool_manifest()
    manifest["tool"]["fields"][0]["default"] = "<b>Ready</b> & set"
    declared = normalize_tool_plugin_definition(manifest)
    kinds = tool_kinds(declared, listing_uid=COUNTERS_UID)
    tools = plugin_tools.community_tool_set(
        [plugin_tools.InstalledTool(COUNTERS_UID, declared)],
        {kind: 900 + i for i, kind in enumerate(kinds)},
    )
    located = locate(tools, GROUP)
    assert located is not None
    before = copy.deepcopy(dict(located.tool.declaration))
    rows_service.declaration(located)
    assert dict(located.tool.declaration) == before
