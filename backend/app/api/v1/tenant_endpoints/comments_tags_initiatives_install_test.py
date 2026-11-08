"""Comments, tags, initiatives and property definitions, called by an
installed plug-in on the real-role client.

Each test installs a plug-in the way a community does (``install_plugin``: placed in
initiative A and not in B, granted scopes by the seat), seals an installation
token for it, and calls the routes these four routers let a plug-in reach.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlmodel import select

from app.core.messages import PluginMessages
from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.models.platform.guild import CommunityRole
from app.models.platform.notification import Notification
from app.models.tenant._mixins import ActorKind
from app.models.tenant.comment import Comment
from app.models.tenant.relationship import EntityRelationship
from app.testing import (
    create_comment,
    create_file,
    create_property_definition,
    create_tag,
    drain_notices,
    guild_url,
    route_session_to_guild,
)
from app.testing.plugin_clients import (
    assert_names_nobody,
    install_headers,
    install_plugin,
    lift_person_and_guild_ids,
    share_with_members,
)


async def _open_files(session: Any, installed: Any) -> tuple[Any, Any]:
    """A file open to A's members and one open to B's, both the seat's."""
    in_a = await create_file(
        session, installed.placed, installed.seat.user, name="Open in A"
    )
    await share_with_members(session, in_a, installed.placed.id)
    in_b = await create_file(
        session, installed.unplaced, installed.seat.user, name="Open in B"
    )
    await share_with_members(session, in_b, installed.unplaced.id)
    return in_a, in_b


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


async def test_reads_the_comments_on_what_it_can_read(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    scopes = ["comments:read", "files:read"]
    installed = await install_plugin(session, acting_user, role_session, granted=scopes)
    in_a, in_b = await _open_files(session, installed)
    on_a = await create_comment(
        session, installed.seat.user, file=in_a, content="Seen in A"
    )
    on_b = await create_comment(
        session, installed.seat.user, file=in_b, content="Seen in B"
    )
    headers = install_headers(installed, scopes)
    guild_id = installed.guild.id

    listed = await client.get(
        guild_url(guild_id, f"/comments/?file_id={in_a.id}"), headers=headers
    )
    assert listed.status_code == 200, listed.text
    [comment] = listed.json()["comments"]
    assert comment["content"] == "Seen in A"
    assert comment["reactions"] == []
    # The author is named by the install's own reference for them.
    assert isinstance(comment["created_by"], str)
    assert comment["author"]["id"] == comment["created_by"]
    assert_names_nobody(listed.text, [installed.seat.user.id, guild_id])

    read = await client.get(
        guild_url(guild_id, f"/comments/{on_a.id}"), headers=headers
    )
    assert read.status_code == 200, read.text
    assert read.json()["created_by"] == comment["created_by"]
    assert_names_nobody(read.text, [installed.seat.user.id, guild_id])

    other = await client.get(
        guild_url(guild_id, f"/comments/?file_id={in_b.id}"), headers=headers
    )
    assert other.status_code == 404, other.text
    other_one = await client.get(
        guild_url(guild_id, f"/comments/{on_b.id}"), headers=headers
    )
    assert other_one.status_code == 404, other_one.text


async def test_without_the_parents_scope_the_thread_is_not_there(
    client, session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["comments:read"]
    )
    in_a, _in_b = await _open_files(session, installed)
    await create_comment(session, installed.seat.user, file=in_a)

    listed = await client.get(
        guild_url(installed.guild.id, f"/comments/?file_id={in_a.id}"),
        headers=install_headers(installed, ["comments:read"]),
    )
    assert listed.status_code == 404, listed.text


async def test_posting_a_comment_needs_the_write_scope(
    client, session, acting_user, role_session
):
    scopes = ["comments:read", "files:read"]
    installed = await install_plugin(session, acting_user, role_session, granted=scopes)
    in_a, _in_b = await _open_files(session, installed)

    posted = await client.post(
        guild_url(installed.guild.id, "/comments/"),
        headers=install_headers(installed, scopes),
        json={"content": "Hello", "file_id": in_a.id},
    )
    assert posted.status_code == 403, posted.text
    assert posted.json()["detail"] == PluginMessages.SCOPE_REQUIRED


async def test_posts_as_itself_and_the_notices_name_the_plugin(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    scopes = ["comments:write", "files:read"]
    installed = await install_plugin(session, acting_user, role_session, granted=scopes)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=installed.guild,
        initiative=installed.placed,
        initiative_role="member",
    )
    in_a, in_b = await _open_files(session, installed)
    theirs = await create_comment(session, member.user, file=in_a, content="A question")
    headers = install_headers(installed, scopes)
    guild_id = installed.guild.id

    posted = await client.post(
        guild_url(guild_id, "/comments/"),
        headers=headers,
        json={
            "content": "An answer",
            "file_id": in_a.id,
            "parent_comment_id": theirs.id,
        },
    )
    assert posted.status_code == 201, posted.text
    body = posted.json()
    assert body["created_by"] is None
    assert body["author"] is None
    assert body["parent_comment_id"] == theirs.id
    assert_names_nobody(posted.text, [installed.seat.user.id, member.user.id, guild_id])

    await route_session_to_guild(session, guild_id)
    stored = await session.get(Comment, body["id"])
    assert stored is not None and (stored.created_by, stored.created_by_kind) == (
        installed.plugin.id,
        ActorKind.plugin,
    )

    # The member it answered hears of the reply, and the file's owner of
    # the comment: both from the plug-in, by its name.
    await drain_notices()
    notices = (
        await session.exec(
            select(Notification).where(
                Notification.user_id.in_([member.user.id, installed.seat.user.id])
            )
        )
    ).all()
    by_person = {n.user_id: n for n in notices}
    assert by_person[member.user.id].data["replier_name"] == installed.plugin.name
    assert by_person[member.user.id].data["replier_id"] is None
    owner_notice = by_person[installed.seat.user.id]
    assert owner_notice.data["commenters"] == [
        {"id": None, "name": installed.plugin.name}
    ]

    elsewhere = await client.post(
        guild_url(guild_id, "/comments/"),
        headers=headers,
        json={"content": "Not here", "file_id": in_b.id},
    )
    assert elsewhere.status_code == 404, elsewhere.text


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


async def test_lists_the_tags_naming_the_community_by_reference(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_plugin(
        session, acting_user, role_session, granted=["tags:read"]
    )
    await create_tag(session, installed.guild, name="alpha")
    await create_tag(session, installed.guild, name="beta")

    listed = await client.get(
        guild_url(installed.guild.id, "/tags/"),
        headers=install_headers(installed, ["tags:read"]),
    )
    assert listed.status_code == 200, listed.text
    assert [t["name"] for t in listed.json()] == ["alpha", "beta"]
    assert all(isinstance(t["community_id"], str) for t in listed.json())
    assert_names_nobody(listed.text, [installed.seat.user.id, installed.guild.id])


async def test_tags_what_it_may_write_in_bulk(
    client, session, acting_user, role_session
):
    scopes = ["tags:write", "files:write", "relationships:write"]
    installed = await install_plugin(session, acting_user, role_session, granted=scopes)
    tag = await create_tag(session, installed.guild, name="triaged")
    headers = install_headers(installed, scopes)
    guild_id = installed.guild.id

    created = await client.post(
        guild_url(guild_id, "/files/"),
        headers=headers,
        json={"name": "Its own", "initiative_id": installed.placed.id},
    )
    assert created.status_code == 201, created.text
    file_id = created.json()["id"]

    tagged = await client.post(
        guild_url(guild_id, "/tags/bulk"),
        headers=headers,
        json={
            "target_type": "file",
            "target_ids": [file_id],
            "add_tag_ids": [tag.id],
        },
    )
    assert tagged.status_code == 200, tagged.text
    assert tagged.json() == {"updated_count": 1}

    await route_session_to_guild(session, guild_id)
    edges = (
        await session.exec(
            select(EntityRelationship).where(
                EntityRelationship.source_type == SearchEntityType.file.value,
                EntityRelationship.source_id == file_id,
                EntityRelationship.relationship_type
                == RelationshipType.tagged_with.value,
            )
        )
    ).all()
    assert [edge.target_id for edge in edges] == [tag.id]


@pytest.mark.parametrize(
    "scopes",
    [
        ["tags:write"],
        ["tags:write", "files:write"],
        ["tags:write", "relationships:write"],
    ],
)
async def test_bulk_tagging_needs_every_scope_it_writes_under(
    client, session, acting_user, role_session, scopes
):
    installed = await install_plugin(session, acting_user, role_session, granted=scopes)
    tag = await create_tag(session, installed.guild, name="triaged")
    in_a, _in_b = await _open_files(session, installed)

    tagged = await client.post(
        guild_url(installed.guild.id, "/tags/bulk"),
        headers=install_headers(installed, scopes),
        json={
            "target_type": "file",
            "target_ids": [in_a.id],
            "add_tag_ids": [tag.id],
        },
    )
    assert tagged.status_code == 403, tagged.text
    assert tagged.json()["detail"] == PluginMessages.SCOPE_REQUIRED


async def test_bulk_tagging_with_a_read_token_is_refused(
    client, session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["tags:read"]
    )
    tag = await create_tag(session, installed.guild, name="triaged")

    tagged = await client.post(
        guild_url(installed.guild.id, "/tags/bulk"),
        headers=install_headers(installed, ["tags:read"]),
        json={"target_type": "file", "target_ids": [1], "add_tag_ids": [tag.id]},
    )
    assert tagged.status_code == 403, tagged.text
    assert tagged.json()["detail"] == PluginMessages.SCOPE_REQUIRED


async def test_bulk_tagging_what_it_cannot_write_is_refused(
    client, session, acting_user, role_session
):
    scopes = ["tags:write", "files:write", "relationships:write"]
    installed = await install_plugin(session, acting_user, role_session, granted=scopes)
    tag = await create_tag(session, installed.guild, name="triaged")
    in_a, in_b = await _open_files(session, installed)
    headers = install_headers(installed, scopes)

    # Open to A's members to read, which is not to write.
    readable = await client.post(
        guild_url(installed.guild.id, "/tags/bulk"),
        headers=headers,
        json={
            "target_type": "file",
            "target_ids": [in_a.id],
            "add_tag_ids": [tag.id],
        },
    )
    assert readable.status_code == 403, readable.text

    elsewhere = await client.post(
        guild_url(installed.guild.id, "/tags/bulk"),
        headers=headers,
        json={
            "target_type": "file",
            "target_ids": [in_b.id],
            "add_tag_ids": [tag.id],
        },
    )
    assert elsewhere.status_code == 404, elsewhere.text


# ---------------------------------------------------------------------------
# Initiatives
# ---------------------------------------------------------------------------


async def test_reads_the_initiatives_it_is_placed_in(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_plugin(
        session, acting_user, role_session, granted=["initiatives:read"]
    )
    headers = install_headers(installed, ["initiatives:read"])
    guild_id = installed.guild.id

    listed = await client.get(guild_url(guild_id, "/initiatives/"), headers=headers)
    assert listed.status_code == 200, listed.text
    [only] = listed.json()
    assert only["id"] == installed.placed.id
    assert isinstance(only["community_id"], str)
    # Neither the list nor one initiative's read names a roster.
    assert "members" not in only
    assert_names_nobody(listed.text, [installed.seat.user.id, guild_id])

    read = await client.get(
        guild_url(guild_id, f"/initiatives/{installed.placed.id}"), headers=headers
    )
    assert read.status_code == 200, read.text
    assert read.json()["name"] == installed.placed.name
    # Who is in it is the members scope's to read, the headcount included.
    assert (read.json()["member_count"], read.json()["role_display_name"]) == (
        0,
        None,
    )
    assert_names_nobody(read.text, [installed.seat.user.id, guild_id])

    other = await client.get(
        guild_url(guild_id, f"/initiatives/{installed.unplaced.id}"), headers=headers
    )
    assert other.status_code == 404, other.text

    whole_guild = await client.get(
        guild_url(guild_id, "/initiatives/?scope=community"), headers=headers
    )
    assert whole_guild.status_code == 403, whole_guild.text


async def test_with_the_members_scope_the_roster_names_people_by_reference(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    scopes = ["initiatives:read", "members:read"]
    installed = await install_plugin(session, acting_user, role_session, granted=scopes)

    headers = install_headers(installed, scopes)

    read = await client.get(
        guild_url(installed.guild.id, f"/initiatives/{installed.placed.id}"),
        headers=headers,
    )
    roster = await client.get(
        guild_url(installed.guild.id, "/users/search"),
        headers=headers,
        params={"initiative_id": installed.placed.id},
    )

    assert read.status_code == 200, read.text
    assert read.json()["member_count"] == 1
    assert roster.status_code == 200, roster.text
    [member] = roster.json()["items"]
    assert isinstance(member["id"], str)
    assert_names_nobody(roster.text, [installed.seat.user.id, installed.guild.id])


async def test_initiatives_need_the_initiatives_scope(
    client, session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["comments:read"]
    )
    listed = await client.get(
        guild_url(installed.guild.id, "/initiatives/"),
        headers=install_headers(installed, ["comments:read"]),
    )
    assert listed.status_code == 403, listed.text
    assert listed.json()["detail"] == PluginMessages.SCOPE_REQUIRED


# ---------------------------------------------------------------------------
# Property definitions
# ---------------------------------------------------------------------------


async def test_lists_the_property_definitions_of_its_initiatives(
    client, session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["properties:read"]
    )
    await create_property_definition(session, installed.placed, name="Estimate")
    await create_property_definition(session, installed.unplaced, name="Hidden")
    headers = install_headers(installed, ["properties:read"])
    guild_id = installed.guild.id

    listed = await client.get(
        guild_url(guild_id, "/property-definitions/"), headers=headers
    )
    assert listed.status_code == 200, listed.text
    assert [d["name"] for d in listed.json()] == ["Estimate"]

    narrowed = await client.get(
        guild_url(
            guild_id, f"/property-definitions/?initiative_id={installed.unplaced.id}"
        ),
        headers=headers,
    )
    assert narrowed.status_code == 200, narrowed.text
    assert narrowed.json() == []
