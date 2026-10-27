"""Posts, wikis and collections as an installed plug-in calls them.

Each test installs a plug-in the way a community does (``install_plugin``: placed in
initiative A and not in B, granted scopes by the seat), seals an installation
token for it, and calls the routes that name a scope: the list, read, create
and update of posts and wikis, a post's pin, a wiki's pages, and a
collection's files under the files scopes.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import pytest
from sqlmodel import select

from app.core.messages import PluginMessages
from app.main import plugin_openapi
from app.models.tenant.post import Post
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.testing import (
    create_resource_grant,
    guild_url,
    create_post,
    create_post_poll,
    create_wiki,
    create_wiki_page,
    guild_of,
    lexical_body,
    png_bytes,
    route_session_to_guild,
)
from app.testing.plugin_clients import (
    assert_names_nobody,
    install_plugin,
    install_headers,
    lift_person_and_guild_ids,
)


@dataclass(frozen=True)
class _Tool:
    """What the tests below vary per tool."""

    plural: str
    #: What a grant on one calls it.
    resource_type: str
    #: The initiative's switch for the tool.
    switch: str
    #: Makes one open to its initiative's members, as its seat.
    make: Callable[..., Awaitable[Any]]
    #: A change the tool's PATCH takes, and the field it shows up in.
    patch: dict[str, Any]


TOOLS = [
    _Tool("posts", "post", "posts_enabled", create_post, {"name": "Renamed"}),
    _Tool("wikis", "wiki", "wikis_enabled", create_wiki, {"name": "Renamed"}),
]


async def _switch_on(session: Any, tool: _Tool, *initiatives: Any) -> None:
    """Turn ``tool`` on in each of ``initiatives``."""
    await route_session_to_guild(session, guild_of(initiatives[0]))
    for initiative in initiatives:
        setattr(initiative, tool.switch, True)
        session.add(initiative)
    await session.commit()


# ---------------------------------------------------------------------------
# Reach
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool", TOOLS, ids=[t.plural for t in TOOLS])
async def test_reads_what_is_open_to_its_initiative(
    tool, client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_plugin(
        session, acting_user, role_session, granted=[f"{tool.plural}:read"]
    )
    seat = installed.seat
    guild_id = installed.guild.id
    await _switch_on(session, tool, installed.placed, installed.unplaced)
    # Both are open to their initiative's members (the factory's default).
    in_a = await tool.make(session, installed.placed, seat.user, name="In A")
    in_b = await tool.make(session, installed.unplaced, seat.user, name="In B")
    headers = install_headers(installed, [f"{tool.plural}:read"])

    listed = await client.get(guild_url(guild_id, f"/{tool.plural}/"), headers=headers)
    assert listed.status_code == 200, listed.text
    assert [row["name"] for row in listed.json()["items"]] == ["In A"]
    assert_names_nobody(listed.text, [seat.user.id, guild_id])

    read = await client.get(
        guild_url(guild_id, f"/{tool.plural}/{in_a.id}"), headers=headers
    )
    assert read.status_code == 200, read.text
    body = read.json()
    assert body["name"] == "In A"
    assert body["can"]["edit"] is False
    # The seat is named by this install's reference, and the community by its
    # own.
    assert isinstance(body["created_by"], str)
    assert isinstance(body["community_id"], str)
    assert listed.json()["items"][0]["created_by"] == body["created_by"]
    assert_names_nobody(read.text, [seat.user.id, guild_id])

    other = await client.get(
        guild_url(guild_id, f"/{tool.plural}/{in_b.id}"), headers=headers
    )
    assert other.status_code == 404, other.text

    # A person reading the same row is served row ids, as always.
    person = await client.get(
        guild_url(guild_id, f"/{tool.plural}/{in_a.id}"), headers=seat.headers
    )
    assert person.status_code == 200, person.text
    assert person.json()["created_by"] == seat.user.id
    assert person.json()["community_id"] == guild_id


async def test_a_post_it_reads_carries_no_one_s_own_state(
    client, session, acting_user, role_session
):
    """Reactions, read markers and ballots are people's own rows, so a post an
    installed plug-in reads carries the empty form of each."""
    await lift_person_and_guild_ids(session)
    installed = await install_plugin(
        session, acting_user, role_session, granted=["posts:read"]
    )
    seat = installed.seat
    guild_id = installed.guild.id
    await _switch_on(session, TOOLS[0], installed.placed)
    post = await create_post(session, installed.placed, seat.user, name="Asks")
    await create_post_poll(session, post)
    headers = install_headers(installed, ["posts:read"])

    for path in ("/posts/", f"/posts/{post.id}", "/posts/?unread=true"):
        response = await client.get(guild_url(guild_id, path), headers=headers)
        assert response.status_code == 200, (path, response.text)
        body = response.json()
        row = body["items"][0] if "items" in body else body
        assert row["name"] == "Asks"
        assert row["is_read"] is False
        assert row["read_count"] == 0
        assert row["reactions"] == []
        assert row["poll"]["options"][0]["text"] == "Tuesday"
        assert_names_nobody(response.text, [seat.user.id, guild_id])


async def test_lists_a_wiki_s_pages_with_the_read_scope(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_plugin(
        session, acting_user, role_session, granted=["wikis:read"]
    )
    seat = installed.seat
    guild_id = installed.guild.id
    await _switch_on(session, TOOLS[1], installed.placed)
    wiki = await create_wiki(session, installed.placed, seat.user)
    await create_wiki_page(session, wiki, seat.user, title="Start here")
    path = guild_url(guild_id, f"/wikis/{wiki.id}/pages")

    listed = await client.get(path, headers=install_headers(installed, ["wikis:read"]))
    assert listed.status_code == 200, listed.text
    (page,) = listed.json()["items"]
    assert page["title"] == "Start here"
    assert isinstance(page["created_by"], str)
    assert_names_nobody(listed.text, [seat.user.id, guild_id])

    refused = await client.get(path, headers=install_headers(installed, ["posts:read"]))
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == PluginMessages.SCOPE_REQUIRED


async def test_reads_a_wiki_page_with_the_read_scope(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_plugin(
        session, acting_user, role_session, granted=["wikis:read"]
    )
    seat = installed.seat
    guild_id = installed.guild.id
    await _switch_on(session, TOOLS[1], installed.placed)
    wiki = await create_wiki(session, installed.placed, seat.user)
    content = lexical_body("Over to ", mentioning=seat.user.id, name="The Seat")
    content["root"]["children"].append(
        {"type": "image", "src": f"/uploads/{guild_id}/shot.png", "altText": "shot"}
    )
    page = await create_wiki_page(
        session, wiki, seat.user, title="Start here", content=content
    )
    path = guild_url(guild_id, f"/wiki-pages/{page.id}")

    read = await client.get(path, headers=install_headers(installed, ["wikis:read"]))
    assert read.status_code == 200, read.text
    body = read.json()
    assert body["title"] == "Start here"
    assert isinstance(body["created_by"], str)
    assert isinstance(body["community_id"], str)
    # The mention names the seat by this install's reference, and the stored
    # picture comes without its path.
    [_, node] = body["content"]["root"]["children"][0]["children"]
    assert (node["mentionUserId"], node["mentionName"], node["text"]) == (
        body["created_by"],
        "",
        "",
    )
    assert body["content"]["root"]["children"][1]["src"] == ""
    assert "/uploads/" not in read.text
    assert "The Seat" not in read.text
    assert_names_nobody(read.text, [seat.user.id, guild_id])

    refused = await client.get(path, headers=install_headers(installed, ["posts:read"]))
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == PluginMessages.SCOPE_REQUIRED


def test_the_plugin_file_lists_wiki_pages_collections_and_uploads():
    operations = {
        operation["operationId"]: operation
        for item in plugin_openapi()["paths"].values()
        for operation in item.values()
    }
    assert operations["list_wiki_pages"]["x-plugin-scope"] == "wikis:read"
    assert operations["read_wiki_page"]["x-plugin-scope"] == "wikis:read"
    assert operations["create_wiki_page"]["x-plugin-scope"] == "wikis:write"
    assert operations["list_collections"]["x-plugin-scope"] == "files:read"
    assert operations["list_collection_files"]["x-plugin-scope"] == "files:read"
    assert operations["create_collection"]["x-plugin-scope"] == "files:write"
    assert operations["upload_file"]["x-plugin-scope"] == "files:write"
    assert operations["upload_file_version"]["x-plugin-scope"] == "files:write"


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool", TOOLS, ids=[t.plural for t in TOOLS])
async def test_changing_anything_needs_the_write_scope(
    tool, client, session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=[f"{tool.plural}:read"]
    )
    seat = installed.seat
    guild_id = installed.guild.id
    await _switch_on(session, tool, installed.placed)
    row = await tool.make(session, installed.placed, seat.user, name="Theirs")
    headers = install_headers(installed, [f"{tool.plural}:read"])

    attempts = [
        (
            "POST",
            f"/{tool.plural}/",
            {"name": "New", "initiative_id": seat.initiative.id},
        ),
        ("PATCH", f"/{tool.plural}/{row.id}", tool.patch),
    ]
    if tool.plural == "posts":
        attempts.append(("PUT", f"/posts/{row.id}/pin", {"pinned": True}))
    if tool.plural == "wikis":
        attempts.append(("POST", f"/wikis/{row.id}/pages", {}))
    for method, path, payload in attempts:
        response = await client.request(
            method, guild_url(guild_id, path), headers=headers, json=payload
        )
        assert response.status_code == 403, (method, path, response.text)
        assert response.json()["detail"] == PluginMessages.SCOPE_REQUIRED


@pytest.mark.parametrize("tool", TOOLS, ids=[t.plural for t in TOOLS])
async def test_what_it_creates_is_its_own(
    tool, client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_plugin(
        session, acting_user, role_session, granted=[f"{tool.plural}:write"]
    )
    seat = installed.seat
    guild_id = installed.guild.id
    await _switch_on(session, tool, installed.placed)
    headers = install_headers(installed, [f"{tool.plural}:write"])
    create = {"name": "Made by the plug-in", "initiative_id": installed.placed.id}

    # It shares nothing: an explicit grant list is refused.
    shared = await client.post(
        guild_url(guild_id, f"/{tool.plural}/"),
        headers=headers,
        json={**create, "grants": [{"all_initiative_members": True, "level": "read"}]},
    )
    assert shared.status_code == 403, shared.text
    assert shared.json()["detail"] == PluginMessages.SHARING_NOT_AVAILABLE

    created = await client.post(
        guild_url(guild_id, f"/{tool.plural}/"), headers=headers, json=create
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["created_by"] is None
    assert isinstance(body["community_id"], str)
    assert body["can"]["delete"] is True
    assert_names_nobody(created.text, [seat.user.id, guild_id])

    await route_session_to_guild(session, guild_id)
    grants = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == tool.resource_type,
                ResourceGrant.resource_id == body["id"],
            )
        )
    ).all()
    assert [(g.level, g.plugin_install_id, g.user_id) for g in grants] == [
        (ResourceAccessLevel.owner, installed.plugin.id, None)
    ]

    updated = await client.patch(
        guild_url(guild_id, f"/{tool.plural}/{body['id']}"),
        headers=headers,
        json=tool.patch,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Renamed"
    assert_names_nobody(updated.text, [seat.user.id, guild_id])


async def test_writes_the_pages_of_a_wiki_it_may_write(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_plugin(
        session, acting_user, role_session, granted=["wikis:write"]
    )
    seat = installed.seat
    guild_id = installed.guild.id
    await _switch_on(session, TOOLS[1], installed.placed)
    headers = install_headers(installed, ["wikis:write"])
    wiki = await client.post(
        guild_url(guild_id, "/wikis/"),
        headers=headers,
        json={"name": "Runbook", "initiative_id": installed.placed.id},
    )
    assert wiki.status_code == 201, wiki.text
    pages = guild_url(guild_id, f"/wikis/{wiki.json()['id']}/pages")

    created = await client.post(pages, headers=headers, json={"title": "Start"})
    assert created.status_code == 201, created.text
    assert created.json()["created_by"] is None
    page_path = guild_url(guild_id, f"/wiki-pages/{created.json()['id']}")
    under = await client.post(pages, headers=headers, json={"title": "Under"})
    assert under.status_code == 201, under.text

    updated = await client.patch(page_path, headers=headers, json={"title": "Begin"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "Begin"
    moved = await client.post(
        guild_url(guild_id, f"/wiki-pages/{under.json()['id']}/move"),
        headers=headers,
        json={"parent_page_id": created.json()["id"]},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["parent_page_id"] == created.json()["id"]
    for response in (created, updated, moved):
        assert_names_nobody(response.text, [seat.user.id, guild_id])


async def test_uploads_pictures_into_a_collection_with_the_files_scopes(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    scopes = ["files:read", "files:write"]
    installed = await install_plugin(session, acting_user, role_session, granted=scopes)
    seat = installed.seat
    guild_id = installed.guild.id
    headers = install_headers(installed, scopes)

    def picture() -> dict:
        return {"file": ("shot.png", io.BytesIO(png_bytes()), "image/png")}

    uploaded = await client.post(
        guild_url(guild_id, "/files/upload"),
        headers=headers,
        files=picture(),
        data={"name": "Harbour", "initiative_id": str(installed.placed.id)},
    )
    assert uploaded.status_code == 201, uploaded.text
    file_id = uploaded.json()["id"]
    version = await client.post(
        guild_url(guild_id, f"/files/{file_id}/versions"),
        headers=headers,
        files=picture(),
    )
    assert version.status_code == 201, version.text
    assert version.json()["version_number"] == 2

    made = await client.post(
        guild_url(guild_id, "/collections/"),
        headers=headers,
        json={
            "name": "Shots",
            "initiative_id": installed.placed.id,
            "file_ids": [file_id],
        },
    )
    assert made.status_code == 201, made.text
    collection_id = made.json()["id"]
    listed = await client.get(
        guild_url(guild_id, f"/collections/{collection_id}/files"),
        headers=install_headers(installed, ["files:read"]),
    )
    assert listed.status_code == 200, listed.text
    assert [row["id"] for row in listed.json()["items"]] == [file_id]
    for response in (uploaded, version, made, listed):
        assert "/uploads/" not in response.text
        assert_names_nobody(response.text, [seat.user.id, guild_id])

    refused = await client.get(
        guild_url(guild_id, f"/collections/{collection_id}"),
        headers=install_headers(installed, ["wikis:read"]),
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == PluginMessages.SCOPE_REQUIRED


async def test_pins_the_posts_it_may_write(client, session, acting_user, role_session):
    await lift_person_and_guild_ids(session)
    installed = await install_plugin(
        session, acting_user, role_session, granted=["posts:write"]
    )
    seat = installed.seat
    guild_id = installed.guild.id
    await _switch_on(session, TOOLS[0], installed.placed)
    headers = install_headers(installed, ["posts:write"])

    created = await client.post(
        guild_url(guild_id, "/posts/"),
        headers=headers,
        json={"name": "Notice", "initiative_id": installed.placed.id},
    )
    assert created.status_code == 201, created.text
    own_id = created.json()["id"]

    pinned = await client.put(
        guild_url(guild_id, f"/posts/{own_id}/pin"),
        headers=headers,
        json={"pinned": True},
    )
    assert pinned.status_code == 200, pinned.text
    assert pinned.json()["is_pinned"] is True
    assert pinned.json()["pinned_by"] is None
    assert_names_nobody(pinned.text, [seat.user.id, guild_id])

    # One of the seat's, open to A's members at read: it reads it, and does
    # not pin it.
    theirs = await create_post(session, installed.placed, seat.user, name="Theirs")
    refused = await client.put(
        guild_url(guild_id, f"/posts/{theirs.id}/pin"),
        headers=headers,
        json={"pinned": True},
    )
    assert refused.status_code == 403, refused.text

    # Shared with the plug-in at write, it does.
    await create_resource_grant(
        session,
        theirs,
        plugin_install_id=installed.plugin.id,
        level=ResourceAccessLevel.write,
    )
    allowed = await client.put(
        guild_url(guild_id, f"/posts/{theirs.id}/pin"),
        headers=headers,
        json={"pinned": True},
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["is_pinned"] is True
    assert isinstance(allowed.json()["created_by"], str)
    assert_names_nobody(allowed.text, [seat.user.id, guild_id])

    await route_session_to_guild(session, guild_id)
    row = await session.get(Post, theirs.id, populate_existing=True)
    assert row is not None and row.pinned_at is not None and row.pinned_by is None
