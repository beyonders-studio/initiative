"""The one surface for links, in place of the five per-tool attach routes.

What it owes: the same gate the tables apply, the same refusal when a picker
reaches across initiatives, and an answer rendered from the side that asked —
so a caller never has to know that a symmetric edge is stored in node-id order.
"""

from datetime import datetime, timezone
from httpx import AsyncClient

from app.core.messages import RelationshipMessages
from app.models.platform.guild import CommunityRole
from app.testing.schema_harness import route_session_to_guild
from app.testing import (
    create_resource_grant,
    create_calendar_event,
    create_file,
    create_guild_calendar,
    create_catalog,
    create_catalog_item,
    create_initiative,
    create_project,
    create_tag,
    create_task,
)


def _url(a) -> str:
    return a.g("/relationships/")


async def _catalogs_enabled(session, initiative) -> None:
    """A catalog only exists in an initiative that has catalogs turned on."""
    initiative.catalogs_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


def _wikilink_body(file_id: int) -> dict:
    """A file body holding one ``[[ ]]`` link."""
    return {
        "root": {
            "children": [
                {
                    "type": "paragraph",
                    "children": [{"type": "wikilink", "documentId": file_id}],
                }
            ]
        }
    }


async def test_a_link_is_made_and_read_back_from_either_side(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    doc = await create_file(session, a.initiative, a.user)

    created = await client.post(
        _url(a),
        headers=a.headers,
        json={
            "source": {"type": "project", "id": a.project.id},
            "relationship_type": "attached",
            "target": {"type": "file", "id": doc.id},
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["other"]["type"] == "file"
    assert body["other"]["id"] == doc.id
    assert body["other"]["title"] == doc.name
    assert body["other"]["initiative_id"] == a.initiative.id

    # The same edge, asked for from the file. ``attached`` is symmetric and
    # stored once in node-id order, which the caller never has to know.
    from_doc = await client.get(
        _url(a), headers=a.headers, params={"entity": f"file:{doc.id}"}
    )
    assert from_doc.status_code == 200, from_doc.text
    (edge,) = from_doc.json()
    assert edge["other"]["type"] == "project"
    assert edge["other"]["id"] == a.project.id


async def test_the_same_pair_is_refused_twice(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    doc = await create_file(session, a.initiative, a.user)
    payload = {
        "source": {"type": "project", "id": a.project.id},
        "relationship_type": "attached",
        "target": {"type": "file", "id": doc.id},
    }
    assert (
        await client.post(_url(a), headers=a.headers, json=payload)
    ).status_code == 201
    again = await client.post(_url(a), headers=a.headers, json=payload)
    assert again.status_code == 409
    assert again.json()["detail"] == RelationshipMessages.EXISTS


async def test_a_thing_cannot_be_linked_to_itself(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    response = await client.post(
        _url(a),
        headers=a.headers,
        json={
            "source": {"type": "project", "id": a.project.id},
            "relationship_type": "related_to",
            "target": {"type": "project", "id": a.project.id},
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == RelationshipMessages.SELF


async def test_a_picker_does_not_reach_across_initiatives(
    client: AsyncClient, acting_user, session
):
    """The table permits a cross-initiative edge — that is where the graph gets
    its reach — but choosing one in a picker is not how they should arrive."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    elsewhere = await create_initiative(session, a.guild, a.user)
    doc = await create_file(session, elsewhere, a.user)

    response = await client.post(
        _url(a),
        headers=a.headers,
        json={
            "source": {"type": "project", "id": a.project.id},
            "relationship_type": "attached",
            "target": {"type": "file", "id": doc.id},
        },
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == RelationshipMessages.CROSS_INITIATIVE


async def test_an_end_the_caller_cannot_open_is_absent(
    client: AsyncClient, acting_user, session
):
    """Not forbidden — absent, which is what every other read here does with
    something out of reach."""
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    hidden = await create_initiative(session, owner.guild, owner.user)
    doc = await create_file(session, hidden, owner.user)

    reader = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    response = await client.post(
        _url(reader),
        headers=reader.headers,
        json={
            "source": {"type": "project", "id": owner.project.id},
            "relationship_type": "attached",
            "target": {"type": "file", "id": doc.id},
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"] == RelationshipMessages.ENDPOINT_NOT_FOUND


async def test_a_slice_is_replaced_wholesale(client: AsyncClient, acting_user, session):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    first = await create_file(session, a.initiative, a.user, name="First")
    second = await create_file(session, a.initiative, a.user, name="Second")

    params = {
        "entity": f"project:{a.project.id}",
        "relationship_type": "attached",
        "other_type": "file",
    }
    set_one = await client.put(
        _url(a), headers=a.headers, params=params, json=[first.id]
    )
    assert set_one.status_code == 200, set_one.text
    assert [e["other"]["id"] for e in set_one.json()] == [first.id]

    set_other = await client.put(
        _url(a), headers=a.headers, params=params, json=[second.id]
    )
    assert set_other.status_code == 200, set_other.text
    assert [e["other"]["id"] for e in set_other.json()] == [second.id]


async def test_a_link_you_made_is_yours_to_remove(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    doc = await create_file(session, a.initiative, a.user)
    created = await client.post(
        _url(a),
        headers=a.headers,
        json={
            "source": {"type": "project", "id": a.project.id},
            "relationship_type": "attached",
            "target": {"type": "file", "id": doc.id},
        },
    )
    edge_id = created.json()["id"]

    removed = await client.delete(a.g(f"/relationships/{edge_id}"), headers=a.headers)
    assert removed.status_code == 204, removed.text

    listing = await client.get(
        _url(a), headers=a.headers, params={"entity": f"project:{a.project.id}"}
    )
    assert listing.json() == []


async def test_a_task_link_is_addressed_by_the_same_surface(
    client: AsyncClient, acting_user, session
):
    """The point of one router: a queue item's tasks and a project's files
    are the same request with different kinds in it."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, a.project)
    doc = await create_file(session, a.initiative, a.user)

    response = await client.post(
        _url(a),
        headers=a.headers,
        json={
            "source": {"type": "task", "id": task.id},
            "relationship_type": "attached",
            "target": {"type": "file", "id": doc.id},
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["other"]["type"] == "file"


async def test_a_kind_no_edge_may_name_is_refused(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    response = await client.get(
        _url(a), headers=a.headers, params={"entity": "comment:1"}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == RelationshipMessages.BAD_ENDPOINT


async def test_a_guild_calendars_event_holds_no_initiative_content(
    client: AsyncClient, acting_user, session
):
    """An event takes its initiative from its calendar, and a guild calendar
    has none — so its events are guild-level content and a file is not
    theirs to link."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    file = await create_file(session, a.initiative, a.user)
    calendar = await create_guild_calendar(session, a.guild, a.user)
    event = await create_calendar_event(session, calendar, a.user)

    response = await client.post(
        _url(a),
        headers=a.headers,
        json={
            "source": {"type": "calendar_event", "id": event.id},
            "relationship_type": "attached",
            "target": {"type": "file", "id": file.id},
        },
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == RelationshipMessages.CROSS_INITIATIVE


async def test_the_guilds_vocabulary_pairs_with_anything(
    client: AsyncClient, acting_user, session
):
    """A tag belongs to no initiative by its nature rather than by where it
    sits, so it is not the same case as the event above."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    tag = await create_tag(session, a.guild)
    task = await create_task(session, a.project)

    response = await client.post(
        _url(a),
        headers=a.headers,
        json={
            "source": {"type": "task", "id": task.id},
            "relationship_type": "tagged_with",
            "target": {"type": "tag", "id": tag.id},
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["other"]["type"] == "tag"


async def test_a_replace_cannot_drop_a_link_a_delete_would_refuse(
    client: AsyncClient, acting_user, session
):
    """A replace is a bulk removal, so it answers the same question a DELETE
    does. ``attached`` is symmetric, which means anyone who can read both ends
    may write the row — the right rule for making one and the wrong rule for
    undoing somebody else's."""
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    doc = await create_file(session, owner.initiative, owner.user)
    made = await client.post(
        _url(owner),
        headers=owner.headers,
        json={
            "source": {"type": "project", "id": owner.project.id},
            "relationship_type": "attached",
            "target": {"type": "file", "id": doc.id},
        },
    )
    assert made.status_code == 201, made.text

    # A co-member who can read both ends but edit neither.
    for resource in (owner.project, doc):
        await create_resource_grant(session, resource, all_initiative_members=True)

    reader = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    wipe = await client.put(
        _url(reader),
        headers=reader.headers,
        params={
            "entity": f"project:{owner.project.id}",
            "relationship_type": "attached",
            "other_type": "file",
        },
        json=[],
    )
    assert wipe.status_code == 403, wipe.text
    assert wipe.json()["detail"] == RelationshipMessages.REMOVE_DENIED

    # And it is still there.
    still = await client.get(
        _url(owner),
        headers=owner.headers,
        params={"entity": f"project:{owner.project.id}"},
    )
    assert [e["other"]["id"] for e in still.json()] == [doc.id]


async def test_a_kind_no_edge_may_name_is_refused_as_a_filter(
    client: AsyncClient, acting_user, session
):
    """``other_type`` takes any search kind, and the ones no edge can name have
    to be refused here rather than at the node encoder."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    response = await client.put(
        _url(a),
        headers=a.headers,
        params={
            "entity": f"project:{a.project.id}",
            "relationship_type": "attached",
            "other_type": "comment",
        },
        json=[],
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == RelationshipMessages.BAD_ENDPOINT


async def test_an_archived_project_takes_no_new_links(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    doc = await create_file(session, a.initiative, a.user)
    await route_session_to_guild(session, a.guild.id)
    a.project.archived_at = datetime.now(timezone.utc)
    session.add(a.project)
    await session.commit()

    response = await client.post(
        _url(a),
        headers=a.headers,
        json={
            "source": {"type": "project", "id": a.project.id},
            "relationship_type": "attached",
            "target": {"type": "file", "id": doc.id},
        },
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == RelationshipMessages.ENDPOINT_ARCHIVED


async def test_a_link_read_out_of_a_body_is_not_one_to_assert_by_hand(
    client: AsyncClient, acting_user, session
):
    """Writing the sentence is how you make one."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    doc = await create_file(session, a.initiative, a.user)
    other = await create_file(session, a.initiative, a.user)

    refused = await client.post(
        _url(a),
        headers=a.headers,
        json={
            "source": {"type": "file", "id": doc.id},
            "relationship_type": "references",
            "target": {"type": "file", "id": other.id},
        },
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == RelationshipMessages.DERIVED


async def test_a_slice_of_derived_links_is_not_one_to_restate(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    doc = await create_file(session, a.initiative, a.user)

    refused = await client.put(
        _url(a),
        headers=a.headers,
        params={
            "entity": f"file:{doc.id}",
            "relationship_type": "references",
            "other_type": "file",
        },
        json=[],
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == RelationshipMessages.DERIVED


async def test_a_link_read_out_of_a_body_is_not_one_to_unlink_by_hand(
    client: AsyncClient, acting_user, session
):
    """Editing the body is how it goes away, so the button does not offer to."""
    from app.core.search import SearchEntityType
    from app.services.tenant import content_references
    from app.services.tenant.relationships import Endpoint

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    doc = await create_file(session, a.initiative, a.user)
    other = await create_file(session, a.initiative, a.user)

    await route_session_to_guild(session, a.guild.id)
    await content_references.sync_for_entity(
        session,
        Endpoint(SearchEntityType.file, doc.id),
        body=_wikilink_body(other.id),
        author_id=a.user.id,
    )
    await session.commit()

    listed = await client.get(
        _url(a),
        headers=a.headers,
        params={"entity": f"file:{doc.id}", "relationship_type": "references"},
    )
    assert listed.status_code == 200, listed.text
    (edge,) = listed.json()
    assert edge["provenance"] == "content"

    refused = await client.delete(
        a.g(f"/relationships/{edge['id']}"), headers=a.headers
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == RelationshipMessages.DERIVED


async def test_inbound_asks_what_links_here(client: AsyncClient, acting_user, session):
    """The two sides of a reference are different questions, and the backlinks
    panel asks only one of them."""
    from app.core.search import SearchEntityType
    from app.services.tenant import content_references
    from app.services.tenant.relationships import Endpoint

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    doc = await create_file(session, a.initiative, a.user)
    other = await create_file(session, a.initiative, a.user)

    await route_session_to_guild(session, a.guild.id)
    await content_references.sync_for_entity(
        session,
        Endpoint(SearchEntityType.file, doc.id),
        body=_wikilink_body(other.id),
        author_id=a.user.id,
    )
    await session.commit()

    def ask(entity: int, direction: str):
        return client.get(
            _url(a),
            headers=a.headers,
            params={
                "entity": f"file:{entity}",
                "relationship_type": "references",
                "direction": direction,
            },
        )

    into = await ask(other.id, "inbound")
    assert [row["other"]["id"] for row in into.json()] == [doc.id]
    assert into.json()[0]["other"]["updated_at"] is not None, (
        "a list ordered by recency needs the far end's own moment"
    )

    out_of = await ask(other.id, "outbound")
    assert out_of.json() == [], "the target names nothing; it is named"


# ---------------------------------------------------------------------------
# What a far end says about itself
#
# A list of edges is a list of mixed kinds. Each end has to carry enough to be
# drawn and linked to, or a reader would have to fetch every one of them to find
# out what it is called, what it looks like and where it lives.
# ---------------------------------------------------------------------------


async def _attach(client: AsyncClient, a, target_type: str, target_id: int) -> dict:
    """Attach one thing to the acting user's project, and return the edge."""
    created = await client.post(
        _url(a),
        headers=a.headers,
        json={
            "source": {"type": "project", "id": a.project.id},
            "relationship_type": "attached",
            "target": {"type": target_type, "id": target_id},
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["other"]


async def test_a_far_end_inside_a_tool_carries_the_address_of_that_tool(
    client: AsyncClient, acting_user, session
):
    """A task has no id-addressable page of its own: it lives at its project.

    So the pair naming the project comes back with it, the same pair a search hit
    carries. Without it a caller holds `task:12` and cannot build a link at all.
    """
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    other_project = await create_project(session, a.initiative, a.user)
    task = await create_task(session, other_project)

    end = await _attach(client, a, "task", task.id)

    assert end["tool"] == "project"
    assert end["tool_id"] == other_project.id


async def test_a_far_end_that_is_a_tool_names_itself(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    doc = await create_file(session, a.initiative, a.user)

    end = await _attach(client, a, "file", doc.id)

    assert end["tool"] == "file"
    assert end["tool_id"] == doc.id


async def test_the_guilds_vocabulary_is_addressed_by_nothing_else(
    client: AsyncClient, acting_user, session
):
    """A tag is not inside a tool — it is the guild's own vocabulary — so it
    reports no governing tool rather than being fitted to one."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    tag = await create_tag(session, a.guild)

    end = await _attach(client, a, "tag", tag.id)

    assert end["tool"] is None
    assert end["tool_id"] is None


async def test_a_file_brings_its_featured_image(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    doc = await create_file(
        session, a.initiative, a.user, featured_image_url="/uploads/3/cover.png"
    )

    end = await _attach(client, a, "file", doc.id)

    assert end["image_urls"] == ["/uploads/3/cover.png"]
    assert end["icon"] is None
    assert end["color"] is None


async def test_a_picture_brings_its_thumbnail_and_falls_back_to_itself(
    client: AsyncClient, acting_user, session
):
    """A thumbnail is absent whenever the source was already small enough not to
    need one, so the full picture is the fallback — decided here rather than by
    every surface that draws one."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await _catalogs_enabled(session, a.initiative)
    catalog = await create_catalog(session, a.initiative, a.user)
    small = await create_catalog_item(session, catalog, a.user)
    large = await create_catalog_item(
        session, catalog, a.user, thumbnail_url="/uploads/3/thumb.webp"
    )

    assert (await _attach(client, a, "catalog_item", small.id))["image_urls"] == [
        small.current_version.file_url
    ]
    assert (await _attach(client, a, "catalog_item", large.id))["image_urls"] == [
        "/uploads/3/thumb.webp"
    ]


async def test_a_catalog_brings_the_cover_somebody_chose(
    client: AsyncClient, acting_user, session
):
    """A catalog's picture lives on another row, so it is one hop away."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await _catalogs_enabled(session, a.initiative)
    catalog = await create_catalog(session, a.initiative, a.user)
    cover = await create_catalog_item(
        session, catalog, a.user, thumbnail_url="/uploads/3/cover-thumb.webp"
    )
    catalog.cover_item_id = cover.id
    session.add(catalog)
    await session.commit()

    end = await _attach(client, a, "catalog", catalog.id)

    # The chosen one stands alone, even though the catalog holds others.
    assert end["image_urls"] == ["/uploads/3/cover-thumb.webp"]


async def test_a_kind_that_carries_a_colour_reports_it(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    tag = await create_tag(session, a.guild, color="#112233")

    end = await _attach(client, a, "tag", tag.id)

    assert end["color"] == "#112233"
    assert end["image_urls"] == []
    assert end["icon"] is None


async def test_a_project_reports_its_emoji(client: AsyncClient, acting_user, session):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    other_project = await create_project(session, a.initiative, a.user, icon="🎲")

    end = await _attach(client, a, "project", other_project.id)

    assert end["icon"] == "🎲"
    assert end["image_urls"] == []


async def test_a_kind_with_no_look_of_its_own_says_so(
    client: AsyncClient, acting_user, session
):
    """A task has no picture, emoji or colour. Reporting three nulls is the
    honest answer, and lets the reader draw the kind's own icon instead."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, a.project)

    end = await _attach(client, a, "task", task.id)

    assert end["image_urls"] == []
    assert end["icon"] is None
    assert end["color"] is None


async def test_a_file_says_what_sort_of_file_it_is(
    client: AsyncClient, acting_user, session
):
    """A spreadsheet, a whiteboard and a PDF are all files and none of them
    should be drawn as a scroll, so the far end carries what picks the icon."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    sheet = await create_file(session, a.initiative, a.user, file_type="spreadsheet")

    end = await _attach(client, a, "file", sheet.id)

    assert end["file_type"] == "spreadsheet"


async def test_a_kind_with_one_fixed_icon_says_nothing_about_its_sort(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, a.project)

    end = await _attach(client, a, "task", task.id)

    assert end["file_type"] is None
    assert end["mime_type"] is None
    assert end["original_filename"] is None
    assert end["smart_link_url"] is None


async def test_a_catalog_nobody_chose_a_cover_for_shows_its_newest(
    client: AsyncClient, acting_user, session
):
    """A catalog with no chosen cover is the usual kind, and it is not blank —
    it stands for itself with the newest few pictures, which is what it shows
    everywhere else."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await _catalogs_enabled(session, a.initiative)
    catalog = await create_catalog(session, a.initiative, a.user)
    for n in range(5):
        await create_catalog_item(
            session, catalog, a.user, thumbnail_url=f"/uploads/3/pic-{n}.webp"
        )

    end = await _attach(client, a, "catalog", catalog.id)

    assert len(end["image_urls"]) == 4, end["image_urls"]
    # Newest first, so the four it shows are the four most recently added.
    assert end["image_urls"][0] == "/uploads/3/pic-4.webp"


async def test_an_empty_catalog_shows_no_pictures_rather_than_a_blank_one(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await _catalogs_enabled(session, a.initiative)
    catalog = await create_catalog(session, a.initiative, a.user)

    end = await _attach(client, a, "catalog", catalog.id)

    assert end["image_urls"] == []


async def test_asserting_a_link_from_something_you_may_read_but_not_edit(
    client: AsyncClient, acting_user, session
):
    """ "This blocks that" is stored as *that* depending on this, so the far end
    is the source — and a directional edge asks write on its source.

    So a reader who may open the far end but not change it cannot assert one, and
    has to be told so rather than the refusal arriving as a server error.
    """
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    mine = await create_task(session, a.project)
    theirs = await create_project(session, a.initiative, b.user)
    # Readable by everyone in the initiative, writable only by its owner.
    await create_resource_grant(session, theirs, all_initiative_members=True)

    readable = await client.get(a.g(f"/projects/{theirs.id}"), headers=a.headers)
    assert readable.status_code == 200, "the case needs a readable far end"

    response = await client.post(
        _url(a),
        headers=a.headers,
        json={
            "source": {"type": "project", "id": theirs.id},
            "relationship_type": "depends_on",
            "target": {"type": "task", "id": mine.id},
        },
    )
    # Refused by name, so the client can say which end the problem is at —
    # rather than as a bare privilege error with nothing to show for it.
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == RelationshipMessages.SOURCE_NOT_WRITABLE


async def test_a_symmetric_link_asks_only_that_both_ends_be_readable(
    client: AsyncClient, acting_user, session
):
    """`attached` describes the pair rather than either end, so it modifies
    neither — and being able to open both is the whole of what it asks."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    theirs = await create_file(session, a.initiative, b.user)
    await create_resource_grant(session, theirs, all_initiative_members=True)

    response = await client.post(
        _url(a),
        headers=a.headers,
        json={
            "source": {"type": "file", "id": theirs.id},
            "relationship_type": "attached",
            "target": {"type": "project", "id": a.project.id},
        },
    )
    assert response.status_code == 201, response.text


async def test_a_far_end_says_what_it_lives_in(
    client: AsyncClient, acting_user, session
):
    """A card reading "Do a thing" says nothing when six of them are linked.
    The far end carries its project so the card can say which one."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, a.project, title="Do a thing")

    created = await client.post(
        _url(a),
        headers=a.headers,
        json={
            "source": {"type": "project", "id": a.project.id},
            "relationship_type": "attached",
            "target": {"type": "task", "id": task.id},
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["other"]["tool_title"] == a.project.name

    # Read from the task's side, the far end is the project itself — which
    # lives in no tool, so there is nothing to name.
    from_task = await client.get(
        _url(a), headers=a.headers, params={"entity": f"task:{task.id}"}
    )
    (edge,) = from_task.json()
    assert edge["other"]["tool_title"] is None


# ---------------------------------------------------------------------------
# A neighbourhood
#
# What the graph draws: everything within a few hops of one thing, in one
# request rather than one per neighbour.
# ---------------------------------------------------------------------------


async def _seed(session, guild_id: int, *pairs) -> None:
    """Record ``(source, type, target)`` edges as they are, past the picker."""
    from app.core.relationships import RelationshipType
    from app.core.search import SearchEntityType
    from app.services.tenant import relationships as relationships_service
    from app.services.tenant.relationships import Endpoint

    await route_session_to_guild(session, guild_id)
    for (source_kind, source_id), rtype, (target_kind, target_id) in pairs:
        await relationships_service.create(
            session,
            source=Endpoint(SearchEntityType(source_kind), source_id),
            relationship_type=RelationshipType(rtype),
            target=Endpoint(SearchEntityType(target_kind), target_id),
        )
    await session.commit()


async def _neighbourhood(client: AsyncClient, a, entity: str, **params):
    response = await client.get(
        a.g("/relationships/neighbourhood"),
        headers=a.headers,
        params={"entity": entity, **params},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return {
        (node["end"]["type"], node["end"]["id"]): node["depth"]
        for node in body["nodes"]
    }, body["edges"]


async def test_a_neighbourhood_walks_as_far_as_it_is_asked(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    near = await create_file(session, a.initiative, a.user)
    middle = await create_file(session, a.initiative, a.user)
    far = await create_file(session, a.initiative, a.user)
    await _seed(
        session,
        a.guild.id,
        (("project", a.project.id), "attached", ("file", near.id)),
        (("file", near.id), "related_to", ("file", middle.id)),
        (("file", middle.id), "related_to", ("file", far.id)),
    )
    centre = f"project:{a.project.id}"

    one, _ = await _neighbourhood(client, a, centre)
    assert one == {("file", near.id): 1}

    two, _ = await _neighbourhood(client, a, centre, hops=2)
    assert two == {("file", near.id): 1, ("file", middle.id): 2}

    three, edges = await _neighbourhood(client, a, centre, hops=3)
    assert three == {
        ("file", near.id): 1,
        ("file", middle.id): 2,
        ("file", far.id): 3,
    }
    # Each edge once, from the side the walk reached it on, so the centre is
    # never named as a far end.
    assert len(edges) == 3
    assert {(e["anchor"]["type"], e["anchor"]["id"]) for e in edges} == {
        ("project", a.project.id),
        ("file", near.id),
        ("file", middle.id),
    }
    assert all(e["other"] != {"type": "project", "id": a.project.id} for e in edges)


async def test_a_neighbourhood_keeps_the_shortest_way_round(
    client: AsyncClient, acting_user, session
):
    """Two hops out one way and one hop out another is one hop out."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    first = await create_file(session, a.initiative, a.user)
    second = await create_file(session, a.initiative, a.user)
    await _seed(
        session,
        a.guild.id,
        (("project", a.project.id), "attached", ("file", first.id)),
        (("project", a.project.id), "attached", ("file", second.id)),
        (("file", first.id), "related_to", ("file", second.id)),
    )

    nodes, edges = await _neighbourhood(client, a, f"project:{a.project.id}", hops=3)
    assert nodes == {("file", first.id): 1, ("file", second.id): 1}
    # The link between the two is still drawn, though it reached nothing new.
    assert len(edges) == 3


async def test_a_neighbourhood_walks_through_labels_only_when_asked(
    client: AsyncClient, acting_user, session
):
    """A tag is carried by everything that carries it, so walking through one
    reaches most of the community in a hop."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    tag = await create_tag(session, a.guild)
    elsewhere = await create_project(session, a.initiative, a.user)
    await _seed(
        session,
        a.guild.id,
        (("project", a.project.id), "tagged_with", ("tag", tag.id)),
        (("project", elsewhere.id), "tagged_with", ("tag", tag.id)),
    )
    centre = f"project:{a.project.id}"

    without, edges = await _neighbourhood(client, a, centre, hops=2)
    assert without == {}
    assert edges == []

    with_tags, _ = await _neighbourhood(client, a, centre, hops=2, include_tags="true")
    assert with_tags == {("tag", tag.id): 1, ("project", elsewhere.id): 2}


async def test_a_neighbourhood_does_not_walk_past_what_the_reader_cannot_open(
    client: AsyncClient, acting_user, session
):
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    shared = await create_file(session, owner.initiative, owner.user)
    hidden_initiative = await create_initiative(session, owner.guild, owner.user)
    hidden = await create_file(session, hidden_initiative, owner.user)
    beyond = await create_file(session, owner.initiative, owner.user)
    await _seed(
        session,
        owner.guild.id,
        (("project", owner.project.id), "attached", ("file", shared.id)),
        (("file", shared.id), "related_to", ("file", hidden.id)),
        (("file", hidden.id), "related_to", ("file", beyond.id)),
    )
    # Everything but the one in the other initiative is open to its members, so
    # what stops the walk is that one thing alone.
    for resource in (owner.project, shared, beyond):
        await create_resource_grant(session, resource, all_initiative_members=True)

    reader = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    nodes, edges = await _neighbourhood(
        client, reader, f"project:{owner.project.id}", hops=3
    )
    assert nodes == {("file", shared.id): 1}
    assert len(edges) == 1


async def test_a_neighbourhood_walks_on_from_the_earliest_links_first(
    client: AsyncClient, acting_user, session, monkeypatch
):
    from app.services.tenant import relationships as relationships_service

    monkeypatch.setattr(relationships_service, "HOP_BUDGET", 1)
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    earlier, later, past_earlier, past_later = [
        await create_file(session, a.initiative, a.user) for _ in range(4)
    ]
    await _seed(
        session,
        a.guild.id,
        (("project", a.project.id), "attached", ("file", earlier.id)),
        (("project", a.project.id), "attached", ("file", later.id)),
        (("file", earlier.id), "related_to", ("file", past_earlier.id)),
        (("file", later.id), "related_to", ("file", past_later.id)),
    )

    nodes, _ = await _neighbourhood(client, a, f"project:{a.project.id}", hops=2)
    assert nodes == {
        ("file", earlier.id): 1,
        ("file", later.id): 1,
        ("file", past_earlier.id): 2,
    }


async def test_a_busy_hop_is_looked_up_in_pieces(
    client: AsyncClient, acting_user, session, monkeypatch
):
    """A hop can name more far ends than one statement takes ids for, so they
    are looked up in pieces, and the answer is the same as in one."""
    from app.services.tenant import relationships as relationships_service

    monkeypatch.setattr(relationships_service, "RESOLVE_CHUNK", 1)
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    files = [await create_file(session, a.initiative, a.user) for _ in range(3)]
    await _seed(
        session,
        a.guild.id,
        *[(("project", a.project.id), "attached", ("file", f.id)) for f in files],
    )

    nodes, edges = await _neighbourhood(client, a, f"project:{a.project.id}", hops=2)
    assert nodes == {("file", f.id): 1 for f in files}
    assert len(edges) == 3


async def test_a_neighbourhood_is_refused_past_its_reach(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    response = await client.get(
        a.g("/relationships/neighbourhood"),
        headers=a.headers,
        params={"entity": f"project:{a.project.id}", "hops": 4},
    )
    assert response.status_code == 422


async def test_a_neighbourhood_of_something_out_of_reach_is_absent(
    client: AsyncClient, acting_user, session
):
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    hidden_initiative = await create_initiative(session, owner.guild, owner.user)
    hidden = await create_file(session, hidden_initiative, owner.user)
    reader = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    response = await client.get(
        reader.g("/relationships/neighbourhood"),
        headers=reader.headers,
        params={"entity": f"file:{hidden.id}"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == RelationshipMessages.ENDPOINT_NOT_FOUND


async def test_a_projects_task_edges_are_read_at_once(
    client: AsyncClient, acting_user, session
):
    """The edges from or to the project's tasks, with the other projects'
    tasks they reach; none to a task the reader cannot open."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    first, second, part = [await create_task(session, a.project) for _ in range(3)]
    other_project = await create_project(session, a.initiative, a.user, name="Other")
    elsewhere = await create_task(session, other_project, title="Elsewhere")
    # Shared with the initiative, where the reader is; the closed initiative's
    # project is not, whatever its sharing says.
    for project in (a.project, other_project):
        await create_resource_grant(session, project, all_initiative_members=True)
    closed = await create_initiative(session, a.guild, a.user, name="Closed")
    unseen = await create_task(
        session, await create_project(session, closed, a.user, name="Unseen")
    )
    doc = await create_file(session, a.initiative, a.user)
    await _seed(
        session,
        a.guild.id,
        (("task", first.id), "depends_on", ("task", second.id)),
        (("task", part.id), "part_of", ("task", first.id)),
        (("task", first.id), "depends_on", ("task", elsewhere.id)),
        (("task", second.id), "depends_on", ("task", unseen.id)),
        (("task", second.id), "attached", ("file", doc.id)),
    )
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    response = await client.get(
        b.g("/relationships/tasks"),
        headers=b.headers,
        params={"project_id": a.project.id},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert sorted(
        (edge["source_id"], edge["relationship_type"], edge["target_id"])
        for edge in body["edges"]
    ) == sorted(
        [
            (first.id, "depends_on", second.id),
            (part.id, "part_of", first.id),
            (first.id, "depends_on", elsewhere.id),
        ]
    )
    assert all(isinstance(edge["id"], int) for edge in body["edges"])
    assert [
        (task["id"], task["project_name"], task["done"]) for task in body["others"]
    ] == [(elsewhere.id, "Other", False)]
