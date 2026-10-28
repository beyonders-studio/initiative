"""The routes an installed plug-in calls, end to end on the real-role client.

Each test installs a plug-in the way a community does (``install_plugin``: placed in
initiative A and not in B, granted scopes by the seat, registered by the
operator), seals an installation token for it, and calls ordinary
``/c/{community_id}/…`` routes with that token. Postgres decides what the install
reaches; these tests hold the routes' side of it: reach, narrowing, live
revocation, authorship, the identity boundary, route opt-in and round trips.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlmodel import select

from app.api import actor_route
from app.api.actor_route import ActorRoute
from app.api.deps import route_plugin_scopes
from app.core.identity_boundary import BoundaryPhase
from app.core.plugin_scopes import ALL_SCOPES
from app.core.messages import PluginMessages
from app.db.search_index import COMMENT_PREVIEW_CHARS
from app.main import app
from app.models.platform.guild import Guild, CommunityRole, CommunityStatus
from app.models.platform.notification import Notification, NotificationType
from app.models.tenant.plugin_placement import PluginPlacement
from app.models.tenant.comment import Comment
from app.models.tenant.file import File
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.metadata import MetadataType
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.services.marketplace import plugin_refs
from app.core.image_headers import validate_image
from app.models.platform.user_avatar import AVATAR_SPEC
from app.services.platform import user_avatars
from app.services.platform.user_avatars_test import png
from app.testing import (
    create_resource_grant,
    guild_url,
    create_comment,
    create_file,
    create_post,
    create_guild_calendar,
    create_project,
    create_property_definition,
    create_property_value,
    create_task,
    drain_notices,
    lexical_body,
    route_as,
    route_as_install,
    route_session_to_guild,
)
from app.testing.plugin_clients import (
    CLIENT,
    assert_names_nobody,
    install_plugin,
    install_headers,
    lift_person_and_guild_ids,
    share_with_members,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seat_session(installed: Any, role_session: Any) -> Any:
    """A request-path session routed as the community's seat holder."""
    s = await role_session("app_user")
    await route_as(s, user_id=installed.seat.user.id, guild_id=installed.guild.id)
    return s


@contextmanager
def _counting() -> Iterator[list[str]]:
    """Every statement any engine runs meanwhile, in order."""
    statements: list[str] = []

    def count(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", count)
    try:
        yield statements
    finally:
        event.remove(Engine, "before_cursor_execute", count)


# ---------------------------------------------------------------------------
# Reach
# ---------------------------------------------------------------------------


async def test_reads_the_files_open_to_its_initiative(
    client, session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    shared = await create_file(
        session, installed.placed, installed.seat.user, name="Open in A"
    )
    await share_with_members(session, shared, installed.placed.id)
    await create_file(
        session, installed.placed, installed.seat.user, name="Private in A"
    )
    in_b = await create_file(
        session, installed.unplaced, installed.seat.user, name="Open in B"
    )
    await share_with_members(session, in_b, installed.unplaced.id)
    headers = install_headers(installed, ["files:read"])

    listed = await client.get(guild_url(installed.guild.id, "/files/"), headers=headers)
    assert listed.status_code == 200, listed.text
    assert [d["name"] for d in listed.json()["items"]] == ["Open in A"]

    # The plug-in API's document serves from /c/0: the token names the community.
    advertised = await client.get(guild_url(0, "/files/"), headers=headers)
    assert advertised.status_code == 200, advertised.text
    assert advertised.json() == listed.json()

    read = await client.get(
        guild_url(installed.guild.id, f"/files/{shared.id}"), headers=headers
    )
    assert read.status_code == 200, read.text
    assert read.json()["name"] == "Open in A"
    assert read.json()["can"]["edit"] is False

    other = await client.get(
        guild_url(installed.guild.id, f"/files/{in_b.id}"), headers=headers
    )
    assert other.status_code == 404, other.text


# ---------------------------------------------------------------------------
# Authorship and the boundary (files)
# ---------------------------------------------------------------------------


async def test_what_it_creates_is_its_own_and_names_nobody(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:write"]
    )
    headers = install_headers(installed, ["files:write"])

    created = await client.post(
        guild_url(installed.guild.id, "/files/"),
        headers=headers,
        json={"name": "Made by the plug-in", "initiative_id": installed.placed.id},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["created_by"] is None
    assert isinstance(body["community_id"], str)
    assert body["can"]["delete"] is True
    assert_names_nobody(created.text, [installed.seat.user.id, installed.guild.id])

    await route_session_to_guild(session, installed.guild.id)
    grants = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == "file",
                ResourceGrant.resource_id == body["id"],
            )
        )
    ).all()
    assert [(g.level, g.plugin_install_id, g.user_id) for g in grants] == [
        (ResourceAccessLevel.owner, installed.plugin.id, None)
    ]
    file = await session.get(File, body["id"])
    assert file is not None and file.created_by is None


async def test_a_file_a_person_made_names_them_by_reference(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    shared = await create_file(
        session, installed.placed, installed.seat.user, name="Theirs"
    )
    await share_with_members(session, shared, installed.placed.id)
    headers = install_headers(installed, ["files:read"])

    read = await client.get(
        guild_url(installed.guild.id, f"/files/{shared.id}"), headers=headers
    )
    assert read.status_code == 200, read.text
    body = read.json()
    assert isinstance(body["created_by"], str)
    assert body["owner"]["id"] == body["created_by"]
    # Without sharing:read the install is shown who owns it, not the grants.
    assert body["grants"] == []
    assert_names_nobody(read.text, [installed.seat.user.id, installed.guild.id])

    listed = await client.get(guild_url(installed.guild.id, "/files/"), headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["created_by"] == body["created_by"]
    assert_names_nobody(listed.text, [installed.seat.user.id, installed.guild.id])

    # A person reading the same file is served row ids, as always.
    person = await client.get(
        guild_url(installed.guild.id, f"/files/{shared.id}"),
        headers=installed.seat.headers,
    )
    assert person.status_code == 200, person.text
    assert person.json()["created_by"] == installed.seat.user.id
    assert person.json()["community_id"] == installed.guild.id


# ---------------------------------------------------------------------------
# Reach, continued
# ---------------------------------------------------------------------------


async def test_a_private_file_is_read_only_once_shared_with_the_plugin(
    client, session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    private = await create_file(
        session, installed.placed, installed.seat.user, name="Private in A"
    )
    headers = install_headers(installed, ["files:read"])
    url = guild_url(installed.guild.id, f"/files/{private.id}")

    assert (await client.get(url, headers=headers)).status_code == 404

    await create_resource_grant(
        session,
        private,
        plugin_install_id=installed.plugin.id,
        level=ResourceAccessLevel.read,
    )
    read = await client.get(url, headers=headers)
    assert read.status_code == 200, read.text
    assert read.json()["can"]["edit"] is False


async def test_it_cannot_write_even_what_is_shared_with_it_at_write(
    client, session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    file = await create_file(
        session, installed.placed, installed.seat.user, name="Shared at write"
    )
    await create_resource_grant(
        session,
        file,
        plugin_install_id=installed.plugin.id,
        level=ResourceAccessLevel.write,
    )
    url = guild_url(installed.guild.id, f"/files/{file.id}")

    # A token that asks for the read scope only.
    refused = await client.patch(
        url,
        headers=install_headers(installed, ["files:read"]),
        json={"name": "Renamed"},
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == PluginMessages.SCOPE_REQUIRED

    # A token claiming a write scope the seat never granted is held to the
    # grant: the standing holds no write.
    claimed = await client.patch(
        url,
        headers=install_headers(installed, ["files:write"]),
        json={"name": "Renamed"},
    )
    assert claimed.status_code == 403, claimed.text

    await route_session_to_guild(session, installed.guild.id)
    await session.refresh(file)
    assert file.name == "Shared at write"


async def test_it_cannot_create_a_project(client, session, acting_user, role_session):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    response = await client.post(
        guild_url(installed.guild.id, "/projects/"),
        headers=install_headers(installed, ["files:read"]),
        json={"name": "Nope", "initiative_id": installed.placed.id},
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == PluginMessages.SCOPE_REQUIRED


async def test_the_role_refuses_guild_settings_outright(
    session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    s = await role_session("app_user")
    await route_as_install(
        s,
        guild_id=installed.guild.id,
        install_id=installed.plugin.id,
        client_id=CLIENT,
        scopes=["files:read"],
    )
    with pytest.raises(DBAPIError, match="permission denied"):
        await s.exec(text("SELECT count(*) FROM guild_settings"))


# ---------------------------------------------------------------------------
# Narrowing
# ---------------------------------------------------------------------------


async def test_a_narrowed_token_reads_only_its_initiative(
    client, session, acting_user, role_session
):
    installed = await install_plugin(
        session,
        acting_user,
        role_session,
        granted=["files:read", "calendars:read"],
    )
    # Placed in B too, so only the narrowing keeps B out.
    await route_session_to_guild(session, installed.guild.id)
    session.add(
        PluginPlacement(
            install_id=installed.plugin.id, initiative_id=installed.unplaced.id
        )
    )
    await session.commit()
    in_a = await create_file(
        session, installed.placed, installed.seat.user, name="In A"
    )
    await share_with_members(session, in_a, installed.placed.id)
    in_b = await create_file(
        session, installed.unplaced, installed.seat.user, name="In B"
    )
    await share_with_members(session, in_b, installed.unplaced.id)
    await create_guild_calendar(
        session, installed.guild, installed.seat.user, name="Community"
    )
    scopes = ["files:read", "calendars:read"]
    wide = install_headers(installed, scopes)
    narrow = install_headers(installed, scopes, initiative_id=installed.placed.id)
    guild = installed.guild.id

    everything = await client.get(guild_url(guild, "/files/"), headers=wide)
    assert sorted(d["name"] for d in everything.json()["items"]) == ["In A", "In B"]

    only_a = await client.get(guild_url(guild, "/files/"), headers=narrow)
    assert [d["name"] for d in only_a.json()["items"]] == ["In A"]
    assert (
        await client.get(guild_url(guild, f"/files/{in_b.id}"), headers=narrow)
    ).status_code == 404

    community = await client.get(guild_url(guild, "/calendars/"), headers=wide)
    assert "Community" in [c["name"] for c in community.json()["items"]]
    narrowed = await client.get(guild_url(guild, "/calendars/"), headers=narrow)
    assert "Community" not in [c["name"] for c in narrowed.json()["items"]]


# ---------------------------------------------------------------------------
# Live revocation
# ---------------------------------------------------------------------------


async def _open_file(session: Any, installed: Any) -> File:
    file = await create_file(
        session, installed.placed, installed.seat.user, name="Open in A"
    )
    await share_with_members(session, file, installed.placed.id)
    return file


async def _names(client: Any, installed: Any, headers: dict[str, str]) -> Any:
    response = await client.get(
        guild_url(installed.guild.id, "/files/"), headers=headers
    )
    if response.status_code != 200:
        return response.status_code
    return [d["name"] for d in response.json()["items"]]


async def test_removing_the_placement_takes_effect_on_the_next_request(
    client, session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    await _open_file(session, installed)
    headers = install_headers(installed, ["files:read"])
    assert await _names(client, installed, headers) == ["Open in A"]

    await route_session_to_guild(session, installed.guild.id)
    placement = await session.get(
        PluginPlacement, (installed.plugin.id, installed.placed.id)
    )
    await session.delete(placement)
    await session.commit()

    assert await _names(client, installed, headers) == []


async def test_removing_the_scope_takes_effect_on_the_next_request(
    client, session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    await _open_file(session, installed)
    headers = install_headers(installed, ["files:read"])
    assert await _names(client, installed, headers) == ["Open in A"]

    s = await _seat_session(installed, role_session)
    row = (
        await s.exec(select(GuildPlugin).where(GuildPlugin.id == installed.plugin.id))
    ).one()
    row.granted_scopes = []
    s.add(row)
    await s.commit()

    assert await _names(client, installed, headers) == 403


@pytest.mark.parametrize("switch", ["registration", "install", "guild"])
async def test_switching_off_takes_effect_on_the_next_request(
    client, session, acting_user, role_session, switch
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    await _open_file(session, installed)
    headers = install_headers(installed, ["files:read"])
    assert await _names(client, installed, headers) == ["Open in A"]

    if switch == "registration":
        await session.exec(
            text(
                "UPDATE public.plugin_service_registrations SET enabled = false "
                "WHERE public_id = :c"
            ),
            params={"c": CLIENT},
        )
    elif switch == "install":
        await route_session_to_guild(session, installed.guild.id)
        await session.exec(
            text("UPDATE guild_plugins SET enabled = false WHERE id = :i"),
            params={"i": installed.plugin.id},
        )
    else:
        guild = await session.get(Guild, installed.guild.id)
        assert guild is not None
        guild.status = CommunityStatus.suspended
        session.add(guild)
    await session.commit()

    assert await _names(client, installed, headers) == 401


# ---------------------------------------------------------------------------
# Route opt-in
# ---------------------------------------------------------------------------


async def test_an_unmarked_route_refuses_an_installation_token(
    client, session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    response = await client.get(
        guild_url(installed.guild.id, "/tools/file/counts"),
        headers=install_headers(installed, ["files:read"]),
    )
    assert response.status_code == 401, response.text


def test_every_marked_route_names_scopes_in_the_vocabulary():
    marked = [route for route in app.routes if route_plugin_scopes(route)]
    assert marked, "no route names a plug-in scope"
    unknown = {
        (getattr(route, "path", "?"), scope)
        for route in marked
        for scope in route_plugin_scopes(route)
        if scope not in ALL_SCOPES
    }
    assert not unknown, unknown
    assert all(isinstance(route, ActorRoute) for route in marked)


# ---------------------------------------------------------------------------
# Round trips
# ---------------------------------------------------------------------------


@contextmanager
def _handler_start(monkeypatch: Any, statements: list[str]) -> Iterator[list[int]]:
    """Record how many statements had run when the route's own code began."""
    seen: list[int] = []
    original = actor_route._enter

    def enter(phase: Any) -> Any:
        if phase is BoundaryPhase.handler:
            seen.append(len(statements))
        return original(phase)

    monkeypatch.setattr(actor_route, "_enter", enter)
    yield seen


async def test_a_list_costs_two_statements_before_its_handler(
    client, session, acting_user, role_session, monkeypatch
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    await _open_file(session, installed)
    headers = install_headers(installed, ["files:read"])

    with _counting() as statements, _handler_start(monkeypatch, statements) as seen:
        response = await client.get(
            guild_url(installed.guild.id, "/files/"), headers=headers
        )
    assert response.status_code == 200, response.text
    assert seen == [2], statements[:4]


async def test_a_response_naming_people_costs_one_statement_cold_and_none_warm(
    client, session, acting_user, role_session, monkeypatch
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    file = await _open_file(session, installed)
    headers = install_headers(installed, ["files:read"])
    url = guild_url(installed.guild.id, f"/files/{file.id}")

    # Mint the references once, then measure a warm read against a cold one.
    first = await client.get(url, headers=headers)
    assert first.status_code == 200, first.text
    with _counting() as warm:
        again = await client.get(url, headers=headers)
    assert again.json() == first.json()

    plugin_refs.forget_cached_install_refs()
    with _counting() as cold:
        third = await client.get(url, headers=headers)
    assert third.json() == first.json()
    assert len(cold) == len(warm) + 1, (cold, warm)


# ---------------------------------------------------------------------------
# People (members:read)
# ---------------------------------------------------------------------------


async def test_member_search_names_members_by_reference_and_carries_no_address(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_plugin(
        session, acting_user, role_session, granted=["members:read"]
    )
    elsewhere = await acting_user(guild_role=CommunityRole.member)
    headers = install_headers(installed, ["members:read"])

    response = await client.get(
        guild_url(installed.guild.id, "/users/search"), headers=headers
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["username"] for item in items] == [installed.seat.user.username]
    assert all(isinstance(item["id"], str) for item in items)
    assert "email" not in response.text
    assert_names_nobody(
        response.text,
        [installed.seat.user.id, elsewhere.user.id, installed.guild.id],
    )

    # The reference resolves a known selection, as a row id does for a person.
    ref = items[0]["id"]
    picked = await client.get(
        guild_url(installed.guild.id, "/users/search"),
        headers=headers,
        params={"user_id": ref},
    )
    assert [item["id"] for item in picked.json()["items"]] == [ref]

    # A row id, or somebody outside its sector, names nobody.
    unknown = await client.get(
        guild_url(installed.guild.id, "/users/search"),
        headers=headers,
        params={"user_id": str(elsewhere.user.id)},
    )
    assert unknown.status_code == 422, unknown.text


async def test_member_search_narrows_to_an_initiative_the_install_is_placed_in(
    client, session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["members:read"]
    )
    inside = await acting_user(
        guild_role=CommunityRole.member,
        guild=installed.guild,
        initiative=installed.placed,
        initiative_role="member",
    )
    outside = await acting_user(guild_role=CommunityRole.member, guild=installed.guild)
    headers = install_headers(installed, ["members:read"])
    url = guild_url(installed.guild.id, "/users/search")

    narrowed = await client.get(
        url, headers=headers, params={"initiative_id": installed.placed.id}
    )
    assert narrowed.status_code == 200, narrowed.text
    names = {item["username"] for item in narrowed.json()["items"]}
    assert inside.user.username in names
    assert outside.user.username not in names

    unplaced = await client.get(
        url, headers=headers, params={"initiative_id": installed.unplaced.id}
    )
    assert unplaced.status_code == 403, unplaced.text


async def test_member_search_needs_members_read(
    client, session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    response = await client.get(
        guild_url(installed.guild.id, "/users/search"),
        headers=install_headers(installed, ["files:read"]),
    )
    assert response.status_code == 403, response.text


@pytest.mark.parametrize("reads_names", [True, False])
async def test_a_person_is_named_to_a_plugin_only_under_members_read(
    reads_names, client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    # A property's definition is read under initiatives:read.
    reads = ["projects:read", "comments:read", "initiatives:read"]
    installed = await install_plugin(
        session, acting_user, role_session, granted=[*reads, "members:read"]
    )
    seat = installed.seat
    seat.user.avatar_url = "https://pictures.example/seat.png"
    seat.membership.display_name = "The Seat"
    session.add_all([seat.user, seat.membership])
    await session.commit()
    project = await _open_project(session, installed, installed.placed, "Open A")
    task = await create_task(session, project, assignees=[seat.user])
    await create_comment(session, seat.user, task=task)
    owner = await create_property_definition(
        session, installed.placed, name="Owner", type=MetadataType.user_reference
    )
    await create_property_value(session, task, owner, value_user_id=seat.user.id)
    headers = install_headers(
        installed, [*reads, "members:read"] if reads_names else reads
    )
    guild_id = installed.guild.id

    responses = [
        await client.get(guild_url(guild_id, path), headers=headers)
        for path in (
            f"/tasks/{task.id}",
            "/tasks/",
            f"/comments/?task_id={task.id}",
        )
    ]
    for response in responses:
        assert response.status_code == 200, response.text
        assert "pictures.example" not in response.text
        assert_names_nobody(response.text, [seat.user.id, guild_id])
    read, listed, comments = (response.json() for response in responses)
    [property_value] = read["properties"]
    [on_task] = comments["comments"]
    people = [
        read["assignees"][0],
        listed["items"][0]["assignees"][0],
        on_task["author"],
        property_value["value"],
    ]
    ref = people[0]["id"]
    assert isinstance(ref, str)
    names = {
        "username": seat.user.username,
        "discriminator": seat.user.discriminator,
        "display_name": "The Seat",
    }
    assert people == [{"id": ref, **(names if reads_names else {})}] * len(people)


async def test_an_uploaded_picture_reaches_a_plugin_by_reference_under_members_read(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    reads = ["projects:read", "members:read"]
    installed = await install_plugin(session, acting_user, role_session, granted=reads)
    seat = installed.seat
    elsewhere = await acting_user(guild_role=CommunityRole.member)
    picture = png(64, 64)
    for person in (seat.user, elsewhere.user):
        await user_avatars.store_avatar(
            session, user=person, avatar=validate_image(AVATAR_SPEC, picture)
        )
    await session.commit()
    digest = validate_image(AVATAR_SPEC, picture).sha256
    project = await _open_project(session, installed, installed.placed, "Open A")
    task = await create_task(session, project, assignees=[seat.user])
    guild_id = installed.guild.id
    task_url = guild_url(guild_id, f"/tasks/{task.id}")
    headers = install_headers(installed, reads)

    plugin_refs.forget_cached_install_refs()
    with _counting() as cold:
        read = await client.get(task_url, headers=headers)
    with _counting() as warm:
        await client.get(task_url, headers=headers)
    assert read.status_code == 200, read.text
    assert len(cold) == len(warm) + 1, (cold, warm)
    assert_names_nobody(read.text, [seat.user.id, guild_id])
    [assignee] = read.json()["assignees"]
    picture_url = f"/api/v1/c/0/members/{assignee['id']}/avatar/{digest}"
    assert assignee["avatar_url"] == picture_url

    served = await client.get(picture_url, headers=headers)
    assert served.status_code == 200, served.text
    assert served.content == picture
    assert served.headers["content-type"] == "image/png"
    assert served.headers["cache-control"] == "public, max-age=31536000, immutable"
    stale = await client.get(picture_url.replace(digest, "0" * 64), headers=headers)
    assert stale.status_code == 404, stale.text

    # Somebody the install has a reference for who is not a member here.
    outsider = await plugin_refs.ensure_plugin_ref(
        guild_id=guild_id,
        public_id=installed.public_id,
        user_id=elsewhere.user.id,
    )
    away = await client.get(
        f"/api/v1/c/0/members/{outsider}/avatar/{digest}", headers=headers
    )
    assert away.status_code == 404, away.text

    # A person reads the same picture by row id, under the community's seam.
    by_id = guild_url(guild_id, f"/members/{seat.user.id}/avatar/{digest}")
    mine = await client.get(by_id, headers=seat.headers)
    assert mine.status_code == 200, mine.text
    assert mine.content == picture

    # Without members:read: the person is their reference alone, and the
    # picture route refuses.
    tools_only = install_headers(installed, ["projects:read"])
    bare = await client.get(task_url, headers=tools_only)
    assert bare.json()["assignees"] == [{"id": assignee["id"]}]
    refused = await client.get(picture_url, headers=tools_only)
    assert refused.status_code == 403, refused.text


async def test_a_write_naming_three_people_costs_the_same_two(
    client, session, acting_user, role_session, monkeypatch
):
    scopes = ["projects:write", "members:read"]
    installed = await install_plugin(session, acting_user, role_session, granted=scopes)
    for _ in range(3):
        await acting_user(
            guild_role=CommunityRole.member,
            guild=installed.guild,
            initiative=installed.placed,
            initiative_role="member",
        )
    headers = install_headers(installed, scopes)
    guild = installed.guild.id

    # Open to the initiative for writing, so every member can be named on it.
    project = await create_project(session, installed.placed, installed.seat.user)
    await create_resource_grant(
        session,
        project,
        all_initiative_members=True,
        level=ResourceAccessLevel.write,
    )
    members = await client.get(guild_url(guild, "/users/search"), headers=headers)
    refs = [item["id"] for item in members.json()["items"]]
    others = [ref for ref in refs][:3]
    assert len(others) == 3

    with _counting() as statements, _handler_start(monkeypatch, statements) as seen:
        created = await client.post(
            guild_url(guild, "/tasks/"),
            headers=headers,
            json={
                "project_id": project.id,
                "title": "Three of them",
                "assignee_ids": others,
            },
        )
    assert created.status_code == 201, created.text
    assert seen == [2], statements[:4]
    assert sorted(a["id"] for a in created.json()["assignees"]) == sorted(others)


# ---------------------------------------------------------------------------
# Mentions
# ---------------------------------------------------------------------------


def _with_picture(body: dict[str, Any], src: str) -> dict[str, Any]:
    """``body`` with an image node after its paragraph."""
    picture = {"type": "image", "src": src, "altText": "shot", "width": 0}
    body["root"]["children"].append(picture)
    return body


@pytest.mark.parametrize("reads_names", [True, False])
async def test_a_mention_names_a_person_by_reference_and_never_by_name(
    reads_names, client, session, acting_user, role_session
):
    """Content written before names were left out still carries one, and it
    reaches no plug-in, nor does anything derived from the text."""
    await lift_person_and_guild_ids(session)
    reads = ["projects:read", "comments:read", "files:read", "posts:read"]
    installed = await install_plugin(
        session, acting_user, role_session, granted=[*reads, "members:read"]
    )
    seat = installed.seat
    picture = f"/uploads/{installed.guild.id}/pasted-shot.png"
    mention = f"Over to @[The Seat]({seat.user.id}) ![shot]({picture})"
    post = await create_post(
        session,
        installed.placed,
        seat.user,
        body=_with_picture(
            lexical_body("Over to ", mentioning=seat.user.id, name="The Seat"),
            picture,
        ),
    )
    project = await _open_project(session, installed, installed.placed, "Open A")
    task = await create_task(
        session, project, assignees=[seat.user], description=mention
    )
    await create_comment(session, seat.user, task=task, content=mention)
    file = await create_file(
        session,
        installed.placed,
        seat.user,
        content=_with_picture(
            lexical_body("Over to ", mentioning=seat.user.id, name="The Seat"),
            picture,
        ),
    )
    await share_with_members(session, file, installed.placed.id)
    headers = install_headers(
        installed, [*reads, "members:read"] if reads_names else reads
    )
    guild_id = installed.guild.id

    responses = [
        await client.get(guild_url(guild_id, path), headers=headers)
        for path in (
            f"/tasks/{task.id}",
            f"/comments/?task_id={task.id}",
            f"/files/{file.id}",
            f"/posts/{post.id}",
            f"/tasks/?project_id={project.id}",
        )
    ]
    for response in responses:
        assert response.status_code == 200, response.text
        assert_names_nobody(response.text, [seat.user.id, guild_id])
        assert "The Seat" not in response.text
        assert "/uploads/" not in response.text
    read, comments, opened, posted, listed = (r.json() for r in responses)
    ref = read["assignees"][0]["id"]
    # A stored picture is there, without its path.
    assert read["description"] == f"Over to @[]({ref}) ![shot]()"
    assert comments["comments"][0]["content"] == read["description"]
    [_, node] = opened["content"]["root"]["children"][0]["children"]
    assert (node["mentionUserId"], node["mentionName"], node["text"]) == (ref, "", "")
    assert opened["content"]["root"]["children"][1]["src"] == ""
    assert posted["body"]["root"]["children"][1]["src"] == ""
    assert posted["excerpt"] == f"Over to @[]({ref})"
    assert listed["items"][0]["description_excerpt"] == f"Over to @[]({ref})"
    # The person's handle finds what mentions them only for a plug-in that may
    # read names.
    found = await client.get(
        guild_url(guild_id, "/files/"),
        headers=headers,
        params={"search": seat.user.username},
    )
    assert found.status_code == 200, found.text
    assert len(found.json()["items"]) == int(reads_names)
    # A person reads the same with its paths.
    for path in (f"/tasks/{task.id}", f"/files/{file.id}", f"/posts/{post.id}"):
        as_person = await client.get(guild_url(guild_id, path), headers=seat.headers)
        assert as_person.status_code == 200, as_person.text
        assert picture in as_person.text


async def test_a_response_mentioning_three_people_costs_one_statement_cold(
    client, session, acting_user, role_session
):
    scopes = ["projects:read", "comments:read"]
    installed = await install_plugin(session, acting_user, role_session, granted=scopes)
    people = [
        await acting_user(guild_role=CommunityRole.member, guild=installed.guild)
        for _ in range(3)
    ]
    project = await _open_project(session, installed, installed.placed, "Open A")
    task = await create_task(session, project)
    await create_comment(
        session,
        installed.seat.user,
        task=task,
        content=" ".join(f"@[Them]({person.user.id})" for person in people),
    )
    headers = install_headers(installed, scopes)
    url = guild_url(installed.guild.id, f"/comments/?task_id={task.id}")

    first = await client.get(url, headers=headers)
    assert first.status_code == 200, first.text
    with _counting() as warm:
        again = await client.get(url, headers=headers)
    assert again.json() == first.json()

    plugin_refs.forget_cached_install_refs()
    with _counting() as cold:
        third = await client.get(url, headers=headers)
    assert third.json() == first.json()
    assert len(cold) == len(warm) + 1, (cold, warm)


async def test_a_mention_it_writes_is_stored_by_row_id(
    client, session, acting_user, role_session
):
    scopes = ["comments:write", "files:write", "members:read"]
    installed = await install_plugin(session, acting_user, role_session, granted=scopes)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=installed.guild,
        initiative=installed.placed,
        initiative_role="member",
    )
    file = await _open_file(session, installed)
    headers = install_headers(installed, scopes)
    guild_id = installed.guild.id
    members = await client.get(guild_url(guild_id, "/users/search"), headers=headers)
    [ref] = [
        item["id"]
        for item in members.json()["items"]
        if item["username"] == member.user.username
    ]

    posted = await client.post(
        guild_url(guild_id, "/comments/"),
        headers=headers,
        json={"content": f"Over to @[]({ref})", "file_id": file.id},
    )
    assert posted.status_code == 201, posted.text
    assert posted.json()["content"] == f"Over to @[]({ref})"
    created = await client.post(
        guild_url(guild_id, "/files/"),
        headers=headers,
        json={
            "name": "Mentions Sam",
            "initiative_id": installed.placed.id,
            "content": lexical_body("Over to ", mentioning=ref, name="Whoever"),
        },
    )
    assert created.status_code == 201, created.text

    await route_session_to_guild(session, guild_id)
    comment = await session.get(Comment, posted.json()["id"])
    assert comment is not None
    assert comment.content == f"Over to @[]({member.user.id})"
    stored = await session.exec(
        select(File.content).where(File.id == created.json()["id"])
    )
    assert stored.one() == lexical_body("Over to ", mentioning=member.user.id)

    # The person it mentioned hears of it, as from anybody.
    await drain_notices()
    notices = (
        await session.exec(
            select(Notification).where(
                Notification.user_id == member.user.id,
                Notification.type == NotificationType.mention,
            )
        )
    ).all()
    assert [n.data["comment_id"] for n in notices] == [comment.id]

    for content in (f"@[Sam]({member.user.id})", "@[Sam](uplu_nobody-at-all)"):
        refused = await client.post(
            guild_url(guild_id, "/comments/"),
            headers=headers,
            json={"content": content, "file_id": file.id},
        )
        assert refused.status_code == 422, refused.text
        assert PluginMessages.REFERENCE_UNKNOWN in refused.text


# ---------------------------------------------------------------------------
# Search suggestions
# ---------------------------------------------------------------------------


async def _open_project(session: Any, installed: Any, initiative: Any, name: str):
    """A project in ``initiative`` shared with every member of it, which an
    install placed there counts as."""
    project = await create_project(session, initiative, installed.seat.user, name=name)
    await create_resource_grant(session, project, all_initiative_members=True)
    return project


async def _suggest(client: Any, installed: Any, headers: dict[str, str], **params):
    return await client.get(
        guild_url(installed.guild.id, "/search/suggest"), headers=headers, params=params
    )


async def test_suggests_only_the_tasks_it_could_read(
    client, session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["projects:read"]
    )
    open_a = await _open_project(session, installed, installed.placed, "Open A")
    private_a = await create_project(
        session, installed.placed, installed.seat.user, name="Private A"
    )
    open_b = await _open_project(session, installed, installed.unplaced, "Open B")
    readable = await create_task(session, open_a, title="harbor open")
    await create_task(session, private_a, title="harbor private")
    await create_task(session, open_b, title="harbor elsewhere")
    headers = install_headers(installed, ["projects:read"])

    response = await _suggest(
        client, installed, headers, search="harbor", types=["task"]
    )
    assert response.status_code == 200, response.text
    rows = response.json()
    assert [r["entity_id"] for r in rows] == [readable.id]
    assert rows[0]["tool_id"] == open_a.id
    assert rows[0]["initiative_id"] == installed.placed.id
    assert rows[0]["can_write"] is False

    # No types: the default scope, narrowed to what it may read.
    unnamed = await _suggest(client, installed, headers, search="harbor")
    assert unnamed.status_code == 200, unnamed.text
    assert [r["entity_id"] for r in unnamed.json()] == [readable.id]


async def test_suggest_leaves_out_the_kinds_it_holds_no_scope_for(
    client, session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["projects:read"]
    )
    project = await _open_project(session, installed, installed.placed, "Open A")
    task = await create_task(session, project, title="lantern task")
    file = await create_file(
        session, installed.placed, installed.seat.user, name="lantern doc"
    )
    await share_with_members(session, file, installed.placed.id)
    headers = install_headers(installed, ["projects:read"])

    both = await _suggest(
        client, installed, headers, search="lantern", types=["task", "file"]
    )
    assert both.status_code == 200, both.text
    assert [r["entity_id"] for r in both.json()] == [task.id]

    refused = await _suggest(
        client, installed, headers, search="lantern", types=["file"]
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == PluginMessages.SCOPE_REQUIRED


async def test_suggest_asks_the_scope_of_the_tool_a_comment_is_on(
    client, session, acting_user, role_session
):
    """A comment on a task is read through the task's project, so finding one
    needs ``projects:read`` beside ``comments:read``. Its title is the start of
    what was written, and mentions and shows files as the comment does."""
    await lift_person_and_guild_ids(session)
    installed = await install_plugin(
        session,
        acting_user,
        role_session,
        granted=["projects:read", "comments:read"],
    )
    project = await _open_project(session, installed, installed.placed, "Open A")
    task = await create_task(session, project, title="stage build")
    seat = installed.seat.user
    picture = f"/uploads/{installed.guild.id}/pasted-shot.png?size=small"
    comment = await create_comment(
        session,
        seat,
        task=task,
        content=f"beacon confirmed @[The Seat]({seat.id}) ![shot]({picture})",
    )

    comments_only = await _suggest(
        client,
        installed,
        install_headers(installed, ["comments:read"]),
        search="beacon",
        types=["comment"],
    )
    assert comments_only.status_code == 200, comments_only.text
    assert comments_only.json() == []

    with_projects = await _suggest(
        client,
        installed,
        install_headers(installed, ["comments:read", "projects:read"]),
        search="beacon",
        types=["comment"],
    )
    assert with_projects.status_code == 200, with_projects.text
    [found] = with_projects.json()
    assert found["entity_id"] == comment.id
    assert found["title"].startswith("beacon confirmed @[](")
    assert found["title"].endswith(") ![shot]()")
    assert_names_nobody(found["title"], [seat.id, installed.guild.id])


@pytest.mark.parametrize(
    "written", ["@[The Seat]({seat})", "![shot](/uploads/{guild}/pasted-shot.png)"]
)
async def test_a_cut_comment_title_ends_before_what_the_cut_goes_through(
    written, client, session, acting_user, role_session
):
    """A comment's title is its first characters. When they end inside a
    mention or a stored file's address, the title ends before it."""
    scopes = ["projects:read", "comments:read"]
    await lift_person_and_guild_ids(session)
    installed = await install_plugin(session, acting_user, role_session, granted=scopes)
    seat = installed.seat.user
    project = await _open_project(session, installed, installed.placed, "Open A")
    task = await create_task(session, project, title="stage build")
    written = written.format(seat=seat.id, guild=installed.guild.id)
    row_id = str(seat.id) if "@" in written else str(installed.guild.id)
    # The cut goes through the row id's first digit.
    lead = "beacon " + "x" * (COMMENT_PREVIEW_CHARS - written.index(row_id) - 9)
    await create_comment(session, seat, task=task, content=f"{lead} {written} end")

    response = await _suggest(
        client,
        installed,
        install_headers(installed, scopes),
        search="beacon",
        types=["comment"],
    )
    assert response.status_code == 200, response.text
    assert [found["title"] for found in response.json()] == [f"{lead} "]


async def test_a_narrowed_token_suggests_only_its_initiative(
    client, session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["projects:read"]
    )
    # Placed in B too, so only the narrowing keeps B out.
    await route_session_to_guild(session, installed.guild.id)
    session.add(
        PluginPlacement(
            install_id=installed.plugin.id, initiative_id=installed.unplaced.id
        )
    )
    await session.commit()
    in_a = await create_task(
        session,
        await _open_project(session, installed, installed.placed, "Open A"),
        title="orchard in a",
    )
    in_b = await create_task(
        session,
        await _open_project(session, installed, installed.unplaced, "Open B"),
        title="orchard in b",
    )
    scopes = ["projects:read"]

    wide = await _suggest(
        client, installed, install_headers(installed, scopes), search="orchard"
    )
    assert wide.status_code == 200, wide.text
    assert sorted(r["entity_id"] for r in wide.json()) == sorted([in_a.id, in_b.id])

    narrow = await _suggest(
        client,
        installed,
        install_headers(installed, scopes, initiative_id=installed.placed.id),
        search="orchard",
    )
    assert narrow.status_code == 200, narrow.text
    assert [r["entity_id"] for r in narrow.json()] == [in_a.id]

    # Asking for the other initiative by name finds nothing either.
    asked_b = await _suggest(
        client,
        installed,
        install_headers(installed, scopes, initiative_id=installed.placed.id),
        search="orchard",
        initiative_id=installed.unplaced.id,
    )
    assert asked_b.status_code == 200, asked_b.text
    assert asked_b.json() == []
