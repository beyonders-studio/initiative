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
from app.models.platform.guild import CommunityRole
from app.models.platform.notice_outbox import NoticeOutboxItem
from app.models.platform.notification import NotificationType
from app.testing import (
    COUNTERS_UID,
    counters_tool_manifest,
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


async def test_a_new_row_starts_as_declared_and_actions_side_by_side_both_land(
    client, session, acting_user
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

    await asyncio.gather(
        call(f"{GROUP}/{group['id']}/actions/add_all"),
        call(f"{COUNTER}/{counter['id']}/actions/add_one"),
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

    await call("POST", f"{GROUP}/{group['id']}/actions/reset_all")
    read = await call("GET", f"{COUNTER}/{counter['id']}")
    assert read["fields"]["count"] == 0

    copy = await call("POST", f"{GROUP}/{group['id']}/duplicate")
    assert copy["name"] == "Party (Copy)"
    copied = await call("GET", f"{COUNTER}/?parent_id={copy['id']}")
    assert [row["name"] for row in copied["items"]] == ["HP"]
    beside = await call("POST", f"{COUNTER}/{counter['id']}/duplicate")
    assert (beside["name"], beside["parent_id"]) == ("HP (Copy)", group["id"])


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

    response = await client.post(
        url,
        headers=install_headers(installed, [write]),
        json={**body, "initiative_id": installed.unplaced.id},
    )
    assert response.status_code in (403, 404), response.text
