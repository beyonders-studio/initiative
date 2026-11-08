"""Sharing, called by an installed plug-in on the real-role client.

An install changes a resource's sharing through the same route a person
does, under ``sharing:write``, with the tool's write scope and the roster
reads a share makes, and only where its rung on the resource would let a
person share. ``sharing:read`` is what shows it a resource's grants.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlmodel import select

from app.core.messages import PluginMessages
from app.core.tools import Tool
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.testing import (
    create_project,
    create_resource_grant,
    guild_url,
    route_session_to_guild,
)
from app.testing.plugin_clients import (
    assert_names_nobody,
    install_headers,
    install_plugin,
    lift_person_and_guild_ids,
)

SHARE = ["projects:write", "sharing:write", "members:read", "initiatives:read"]


async def _open_project(session: Any, installed: Any, level: str = "read") -> Any:
    """A project of the seat's, shared with every member of the install's
    initiative at ``level``."""
    project = await create_project(
        session, installed.placed, installed.seat.user, name="The seat's"
    )
    await create_resource_grant(
        session, project, all_initiative_members=True, level=ResourceAccessLevel(level)
    )
    return project


async def _seat_ref(client: Any, session: Any, installed: Any, headers: dict) -> str:
    """What the install calls the seat, from the owner of a project it reads."""
    project = await _open_project(session, installed)
    read = await client.get(
        guild_url(installed.guild.id, f"/projects/{project.id}"), headers=headers
    )
    assert read.status_code == 200, read.text
    return read.json()["owner_id"]


async def _own_project(client: Any, installed: Any, headers: dict, **extra) -> Any:
    return await client.post(
        guild_url(installed.guild.id, "/projects/"),
        headers=headers,
        json={"name": "The plug-in's", "initiative_id": installed.placed.id, **extra},
    )


async def _grant_rows(session: Any, guild_id: int, project_id: int) -> set[tuple]:
    await route_session_to_guild(session, guild_id)
    rows = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == Tool.project.value,
                ResourceGrant.resource_id == project_id,
            )
        )
    ).all()
    return {
        (g.level, g.user_id, g.plugin_install_id, g.all_initiative_members)
        for g in rows
    }


async def test_an_install_shares_what_it_owns(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_plugin(session, acting_user, role_session, granted=SHARE)
    headers = install_headers(installed, SHARE)
    gid = installed.guild.id
    seat_ref = await _seat_ref(client, session, installed, headers)
    created = await _own_project(client, installed, headers)
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]

    shared = await client.put(
        guild_url(gid, f"/projects/{project_id}/grants"),
        headers=headers,
        json=[
            {"all_initiative_members": True, "level": "write"},
            {"user_id": seat_ref, "level": "read"},
        ],
    )
    assert shared.status_code == 200, shared.text
    reported = {
        (g["level"], g["user_id"], g["plugin_install_id"], g["all_initiative_members"])
        for g in shared.json()["grants"]
    }
    assert reported == {
        ("owner", None, installed.plugin.id, False),
        ("write", None, None, True),
        ("read", seat_ref, None, False),
    }
    assert_names_nobody(shared.text, [installed.seat.user.id, gid])

    assert await _grant_rows(session, gid, project_id) == {
        (ResourceAccessLevel.owner, None, installed.plugin.id, False),
        (ResourceAccessLevel.write, None, None, True),
        (ResourceAccessLevel.read, installed.seat.user.id, None, False),
    }


async def test_without_sharing_write_the_route_refuses(
    client, session, acting_user, role_session
):
    scopes = ["projects:write", "members:read", "initiatives:read"]
    installed = await install_plugin(session, acting_user, role_session, granted=scopes)
    headers = install_headers(installed, scopes)
    created = await _own_project(client, installed, headers)
    project_id = created.json()["id"]

    refused = await client.put(
        guild_url(installed.guild.id, f"/projects/{project_id}/grants"),
        headers=headers,
        json=[{"all_initiative_members": True, "level": "read"}],
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == PluginMessages.SCOPE_REQUIRED


@pytest.mark.parametrize("missing", ["members:read", "projects:write"])
async def test_sharing_asks_the_tool_and_the_roster_too(
    client, session, acting_user, role_session, missing
):
    installed = await install_plugin(session, acting_user, role_session, granted=SHARE)
    created = await _own_project(client, installed, install_headers(installed, SHARE))
    project_id = created.json()["id"]
    scopes = [s for s in SHARE if s != missing]
    if missing == "projects:write":
        scopes.append("projects:read")

    refused = await client.put(
        guild_url(installed.guild.id, f"/projects/{project_id}/grants"),
        headers=install_headers(installed, scopes),
        json=[{"all_initiative_members": True, "level": "read"}],
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == PluginMessages.SCOPE_REQUIRED


async def test_writing_a_project_is_not_the_rung_to_share_it(
    client, session, acting_user, role_session
):
    """Sharing is the owner's, as deleting is."""
    installed = await install_plugin(session, acting_user, role_session, granted=SHARE)
    project = await _open_project(session, installed, level="write")
    before = await _grant_rows(session, installed.guild.id, project.id)

    refused = await client.put(
        guild_url(installed.guild.id, f"/projects/{project.id}/grants"),
        headers=install_headers(installed, SHARE),
        json=[{"all_initiative_members": True, "level": "write"}],
    )
    assert refused.status_code == 403, refused.text
    assert refused.json() == Tool.project.owner_required().body
    assert await _grant_rows(session, installed.guild.id, project.id) == before


async def test_an_install_shares_what_it_creates_as_it_creates_it(
    client, session, acting_user, role_session
):
    installed = await install_plugin(session, acting_user, role_session, granted=SHARE)
    created = await _own_project(
        client,
        installed,
        install_headers(installed, SHARE),
        grants=[{"all_initiative_members": True, "level": "read"}],
    )
    assert created.status_code == 201, created.text
    assert await _grant_rows(session, installed.guild.id, created.json()["id"]) == {
        (ResourceAccessLevel.owner, None, installed.plugin.id, False),
        (ResourceAccessLevel.read, None, None, True),
    }


async def test_without_sharing_write_a_create_shares_nothing(
    client, session, acting_user, role_session
):
    scopes = ["projects:write"]
    installed = await install_plugin(session, acting_user, role_session, granted=scopes)
    refused = await _own_project(
        client,
        installed,
        install_headers(installed, scopes),
        grants=[{"all_initiative_members": True, "level": "read"}],
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == PluginMessages.SHARING_NOT_AVAILABLE


@pytest.mark.parametrize("sees", [False, True])
async def test_sharing_read_shows_an_install_the_grants(
    client, session, acting_user, role_session, sees
):
    scopes = ["projects:read", *(["sharing:read"] if sees else [])]
    installed = await install_plugin(session, acting_user, role_session, granted=scopes)
    project = await _open_project(session, installed)

    read = await client.get(
        guild_url(installed.guild.id, f"/projects/{project.id}"),
        headers=install_headers(installed, scopes),
    )
    assert read.status_code == 200, read.text
    body = read.json()
    assert bool(body["grants"]) is sees
    # Who owns it is reported either way.
    assert isinstance(body["owner_id"], str)
