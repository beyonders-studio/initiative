"""Collections: seen through the files in them, changed by the initiative's
file makers, gone to the trash once their last file leaves."""

from datetime import date, datetime, timezone

from httpx import AsyncClient
from sqlmodel import select, update

from app.core.messages import CollectionMessages
from app.db import post_commit
from app.db.soft_delete_filter import select_including_deleted
from app.models.platform.guild import CommunityRole
from app.models.tenant.collection import Collection, CollectionFile
from app.models.tenant.file import FileVersion
from app.models.tenant.property import PropertyValue
from app.services.tenant import collections as collections_service
from app.testing import (
    create_collection,
    create_file,
    create_property_value,
    create_resource_grant,
    create_tag,
    route_session_to_guild,
)
from app.testing.factories import grant_role_permission


async def _scene(session, acting_user):
    """An initiative's manager, a member whose role makes files, and two files
    of the manager's: one shared with the initiative, one with nobody."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    maker = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    await grant_role_permission(session, owner.initiative, "create_files")
    shared = await create_file(session, owner.initiative, owner.user, name="Shared")
    await create_resource_grant(session, shared, all_initiative_members=True)
    private = await create_file(session, owner.initiative, owner.user, name="Private")
    return owner, maker, shared, private


async def test_a_collection_is_seen_through_the_files_its_reader_can_open(
    client: AsyncClient, session, acting_user
):
    owner, maker, shared, private = await _scene(session, acting_user)
    created = await client.post(
        owner.g("/collections/"),
        headers=owner.headers,
        json={
            "initiative_id": owner.initiative.id,
            "name": "Moodboard",
            "file_ids": [shared.id, private.id],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["file_count"] == 2
    assert body["can"]["edit"] is True
    collection_id = body["id"]

    # The cover is one the reader can open: the private file stands for it
    # for its owner, never for the maker.
    await client.patch(
        owner.g(f"/collections/{collection_id}"),
        headers=owner.headers,
        json={"cover_file_id": private.id},
    )
    seen = await client.get(
        maker.g(f"/collections/{collection_id}"), headers=maker.headers
    )
    assert seen.status_code == 200
    assert seen.json()["file_count"] == 1
    assert seen.json()["cover"]["file_id"] == shared.id

    listed = await client.get(
        maker.g("/collections/"),
        headers=maker.headers,
        params={"initiative_id": owner.initiative.id},
    )
    assert [c["id"] for c in listed.json()["items"]] == [collection_id]

    files = await client.get(
        maker.g(f"/collections/{collection_id}/files"), headers=maker.headers
    )
    assert files.status_code == 200
    assert [f["id"] for f in files.json()["items"]] == [shared.id]
    filtered = await client.get(
        owner.g("/files/"),
        headers=owner.headers,
        params={"collection_id": collection_id},
    )
    assert {f["id"] for f in filtered.json()["items"]} == {shared.id, private.id}

    file = await client.get(maker.g(f"/files/{shared.id}"), headers=maker.headers)
    assert file.json()["collection_ids"] == [collection_id]


async def test_a_collection_of_files_out_of_reach_is_absent(
    client: AsyncClient, session, acting_user
):
    owner, maker, _shared, private = await _scene(session, acting_user)
    collection = await create_collection(
        session, owner.initiative, owner.user, files=[private]
    )

    assert (
        await client.get(
            maker.g(f"/collections/{collection.id}"), headers=maker.headers
        )
    ).status_code == 404
    listed = await client.get(
        maker.g("/collections/"),
        headers=maker.headers,
        params={"initiative_id": owner.initiative.id},
    )
    assert listed.json()["items"] == []
    renamed = await client.patch(
        maker.g(f"/collections/{collection.id}"),
        headers=maker.headers,
        json={"name": "Mine now"},
    )
    assert renamed.status_code == 404


async def test_changing_a_collection_takes_the_role_that_makes_files(
    client: AsyncClient, session, acting_user
):
    owner, maker, shared, _private = await _scene(session, acting_user)
    collection = await create_collection(
        session, owner.initiative, owner.user, files=[shared]
    )

    async def tag_it() -> int:
        tag = await create_tag(session, owner.guild)
        response = await client.post(
            maker.g("/relationships/"),
            headers=maker.headers,
            json={
                "source": {"type": "collection", "id": collection.id},
                "relationship_type": "tagged_with",
                "target": {"type": "tag", "id": tag.id},
            },
        )
        return response.status_code

    renamed = await client.patch(
        maker.g(f"/collections/{collection.id}"),
        headers=maker.headers,
        json={"name": "Renamed by a file maker"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Renamed by a file maker"
    assert await tag_it() == 201

    await grant_role_permission(
        session, owner.initiative, "create_files", enabled=False
    )
    await session.commit()
    seen = await client.get(
        maker.g(f"/collections/{collection.id}"), headers=maker.headers
    )
    assert seen.json()["can"]["edit"] is False
    refused = await client.patch(
        maker.g(f"/collections/{collection.id}"),
        headers=maker.headers,
        json={"name": "Not allowed"},
    )
    assert refused.status_code == 403
    assert await tag_it() == 403
    # Seeing it is enough to talk about it.
    comment = await client.post(
        maker.g("/comments/"),
        headers=maker.headers,
        json={"content": "Nice set", "collection_id": collection.id},
    )
    assert comment.status_code == 201, comment.text


async def test_archiving_a_collection_takes_the_role_that_makes_files(
    client: AsyncClient, session, acting_user
):
    owner, maker, shared, _private = await _scene(session, acting_user)
    collection = await create_collection(
        session, owner.initiative, owner.user, files=[shared]
    )
    archive = f"/archive/collection/{collection.id}"
    unarchive = f"/unarchive/collection/{collection.id}"

    read = f"/collections/{collection.id}"

    async def can(actor) -> dict[str, bool]:
        return (await client.get(actor.g(read), headers=actor.headers)).json()["can"]

    assert (await can(maker))["unarchive"] is False
    archived = await client.post(maker.g(archive), headers=maker.headers)
    assert archived.status_code == 200, archived.text
    assert archived.json()["archived_at"] is not None
    assert await can(maker) == {"edit": False, "unarchive": True}
    restored = await client.post(maker.g(unarchive), headers=maker.headers)
    assert restored.status_code == 200, restored.text

    await grant_role_permission(
        session, owner.initiative, "create_files", enabled=False
    )
    await session.commit()
    assert (
        await client.post(maker.g(archive), headers=maker.headers)
    ).status_code == 403
    assert (
        await client.post(owner.g(archive), headers=owner.headers)
    ).status_code == 200
    assert await can(maker) == {"edit": False, "unarchive": False}
    assert await can(owner) == {"edit": False, "unarchive": True}
    assert (
        await client.post(maker.g(unarchive), headers=maker.headers)
    ).status_code == 403


async def test_adding_a_file_takes_being_able_to_open_it(
    client: AsyncClient, session, acting_user
):
    owner, maker, shared, private = await _scene(session, acting_user)
    collection = await create_collection(
        session, owner.initiative, owner.user, files=[shared]
    )
    refused = await client.post(
        maker.g(f"/collections/{collection.id}/files"),
        headers=maker.headers,
        json={"file_ids": [private.id]},
    )
    assert refused.status_code == 422
    assert refused.json()["detail"] == CollectionMessages.FILE_NOT_AVAILABLE

    own = await create_file(session, owner.initiative, maker.user, name="Maker's")
    added = await client.post(
        maker.g(f"/collections/{collection.id}/files"),
        headers=maker.headers,
        json={"file_ids": [own.id]},
    )
    assert added.status_code == 200
    assert added.json()["file_count"] == 2


async def test_an_emptied_collection_goes_to_the_trash_and_comes_back(
    client: AsyncClient, session, acting_user
):
    owner, _maker, shared, private = await _scene(session, acting_user)
    collection = await create_collection(
        session, owner.initiative, owner.user, files=[shared, private]
    )

    removed = await client.delete(
        owner.g(f"/collections/{collection.id}/files"),
        headers=owner.headers,
        params={"file_ids": [shared.id]},
    )
    assert removed.status_code == 204
    trashed = await client.delete(
        owner.g(f"/files/{private.id}"), headers=owner.headers
    )
    assert trashed.status_code in (200, 204)
    await post_commit.settle_all()

    await route_session_to_guild(session, owner.guild.id)

    async def deleted_at():
        row = (
            await session.exec(
                select_including_deleted(Collection)
                .where(Collection.id == collection.id)
                .execution_options(populate_existing=True)
            )
        ).one()
        return row.deleted_at

    assert await deleted_at() is not None

    restored = await client.post(
        owner.g(f"/trash/file/{private.id}/restore"), headers=owner.headers
    )
    assert restored.status_code == 200, restored.text
    await post_commit.settle_all()
    assert await deleted_at() is None


async def test_a_member_takes_out_the_last_file_they_can_open(
    client: AsyncClient, session, acting_user
):
    owner, maker, shared, _private = await _scene(session, acting_user)
    collection = await create_collection(
        session, owner.initiative, owner.user, files=[shared]
    )

    removed = await client.delete(
        maker.g(f"/collections/{collection.id}/files"),
        headers=maker.headers,
        params={"file_ids": [shared.id]},
    )
    assert removed.status_code == 204, removed.text
    await post_commit.settle_all()

    await route_session_to_guild(session, owner.guild.id)
    row = (
        await session.exec(
            select_including_deleted(Collection)
            .where(Collection.id == collection.id)
            .execution_options(populate_existing=True)
        )
    ).one()
    assert row.deleted_at is not None


async def test_a_collection_lays_out_its_files_in_a_grid_and_a_table(
    client: AsyncClient, session, acting_user
):
    owner, maker, shared, _private = await _scene(session, acting_user)
    collection = await create_collection(
        session, owner.initiative, owner.user, files=[shared]
    )
    params = {"tool": "collection", "tool_id": collection.id}

    layouts = await client.get(
        owner.g("/layouts/"), headers=owner.headers, params=params
    )
    assert layouts.status_code == 200, layouts.text
    shown = {
        layout["kind"]: (not layout["hidden"], layout["is_default"])
        for layout in layouts.json()["layouts"]
    }
    assert shown == {
        "masonry": (False, False),
        "grid": (True, True),
        "timeline": (False, False),
        "table": (True, False),
    }

    shown_masonry = await client.put(
        maker.g("/layouts/"),
        headers=maker.headers,
        params=params,
        json={"kind": "masonry", "definition": {"hidden": False}},
    )
    assert shown_masonry.status_code == 200, shown_masonry.text
    # A table shows a file's own fields and the collection's; a task's are
    # not a file's.
    columns = await client.put(
        maker.g("/layouts/"),
        headers=maker.headers,
        params=params,
        json={"kind": "table", "definition": {"columns": ["name", "size"]}},
    )
    assert columns.status_code == 200, columns.text
    assignees = await client.put(
        maker.g("/layouts/"),
        headers=maker.headers,
        params=params,
        json={"kind": "table", "definition": {"columns": ["assignees"]}},
    )
    assert assignees.status_code == 400


async def test_a_collection_is_an_end_of_a_link_only_for_who_sees_it(
    client: AsyncClient, session, acting_user
):
    owner, maker, shared, private = await _scene(session, acting_user)
    collection = await create_collection(
        session, owner.initiative, owner.user, files=[private]
    )
    linked = await client.post(
        owner.g("/relationships/"),
        headers=owner.headers,
        json={
            "source": {"type": "collection", "id": collection.id},
            "relationship_type": "related_to",
            "target": {"type": "file", "id": shared.id},
        },
    )
    assert linked.status_code == 201, linked.text

    async def edges(actor, entity: str) -> list:
        response = await client.get(
            actor.g("/relationships/"), headers=actor.headers, params={"entity": entity}
        )
        return response.json() if response.status_code == 200 else []

    from_collection = await edges(owner, f"collection:{collection.id}")
    assert [e["other"]["id"] for e in from_collection] == [shared.id]
    from_file = await edges(owner, f"file:{shared.id}")
    assert [(e["other"]["type"], e["other"]["id"]) for e in from_file] == [
        ("collection", collection.id)
    ]

    # The maker opens the file but no file in the collection: no edge.
    assert await edges(maker, f"file:{shared.id}") == []
    assert await edges(maker, f"collection:{collection.id}") == []

    # Once the collection holds a file the maker opens, the edge is theirs too.
    await client.post(
        owner.g(f"/collections/{collection.id}/files"),
        headers=owner.headers,
        json={"file_ids": [shared.id]},
    )
    assert [e["other"]["id"] for e in await edges(maker, f"file:{shared.id}")] == [
        collection.id
    ]


async def test_a_collection_lists_its_files_by_when_each_was_added(
    client: AsyncClient, session, acting_user
):
    owner, maker, shared, private = await _scene(session, acting_user)
    later = await create_file(session, owner.initiative, owner.user, name="Later")
    await create_resource_grant(session, later, all_initiative_members=True)
    collection = await create_collection(
        session, owner.initiative, owner.user, files=[shared, private, later]
    )
    # Added in another order than they were made in.
    await route_session_to_guild(session, owner.guild.id)
    for file, month in ((shared, 3), (private, 1), (later, 2)):
        await session.exec(
            update(CollectionFile)  # type: ignore[arg-type]
            .where(CollectionFile.file_id == file.id)
            .values(added_at=datetime(2026, month, 10, tzinfo=timezone.utc))
        )
    await session.commit()
    path = f"/collections/{collection.id}/files"

    async def ids(actor, **params) -> list[int]:
        response = await client.get(actor.g(path), headers=actor.headers, params=params)
        assert response.status_code == 200, response.text
        return [f["id"] for f in response.json()["items"]]

    newest = await client.get(owner.g(path), headers=owner.headers)
    assert [(f["id"], f["added_at"][:10]) for f in newest.json()["items"]] == [
        (shared.id, "2026-03-10"),
        (later.id, "2026-02-10"),
        (private.id, "2026-01-10"),
    ]
    assert await ids(owner, sort_by="added_at", sort_dir="asc") == [
        private.id,
        later.id,
        shared.id,
    ]
    assert await ids(owner, sort_by="created_at", sort_dir="desc") == [
        later.id,
        private.id,
        shared.id,
    ]

    # The rail counts only what its reader can open, by the month each was
    # added in, and a month's anchors start the list there either way.
    timeline = await client.get(maker.g(f"{path}/timeline"), headers=maker.headers)
    assert timeline.status_code == 200, timeline.text
    buckets = timeline.json()["buckets"]
    assert [(b["period"], b["count"]) for b in buckets] == [
        ("2026-03", 1),
        ("2026-02", 1),
    ]
    february = buckets[1]
    assert await ids(maker, until=february["anchor"]) == [later.id]
    assert await ids(owner, until=february["anchor"]) == [later.id, private.id]
    assert await ids(
        owner,
        until=february["anchor_oldest"],
        sort_by="added_at",
        sort_dir="asc",
    ) == [later.id, shared.id]


async def test_a_collection_shows_its_pictures_at_their_size(
    client: AsyncClient, session, acting_user
):
    owner, _maker, _shared, _private = await _scene(session, acting_user)
    picture = await create_file(
        session,
        owner.initiative,
        owner.user,
        file_url=f"/uploads/{owner.guild.id}/wide.png",
        file_content_type="image/png",
    )
    thumbnail = f"/uploads/{owner.guild.id}/thumb-wide.webp"
    await route_session_to_guild(session, owner.guild.id)
    await session.exec(
        update(FileVersion)  # type: ignore[arg-type]
        .where(FileVersion.file_id == picture.id)
        .values(
            thumbnail_url=thumbnail, thumbnail_state="ready", width=1600, height=900
        )
    )
    await session.commit()
    collection = await create_collection(
        session, owner.initiative, owner.user, files=[picture]
    )

    cover = (
        await client.get(
            owner.g(f"/collections/{collection.id}"), headers=owner.headers
        )
    ).json()["cover"]
    assert (cover["thumbnail_url"], cover["width"], cover["height"]) == (
        thumbnail,
        1600,
        900,
    )
    (item,) = (
        await client.get(
            owner.g(f"/collections/{collection.id}/files"), headers=owner.headers
        )
    ).json()["items"]
    assert (item["thumbnail_url"], item["width"], item["height"]) == (
        thumbnail,
        1600,
        900,
    )


async def test_a_collection_made_as_a_shape_brings_its_fields_and_lists(
    client: AsyncClient, session, acting_user
):
    _owner, maker, shared, _private = await _scene(session, acting_user)
    created = await client.post(
        maker.g("/collections/"),
        headers=maker.headers,
        json={
            "initiative_id": maker.initiative.id,
            "name": "Shop",
            "file_ids": [shared.id],
            "shape": "catalog",
        },
    )
    assert created.status_code == 201, created.text
    fields = {field["name"]: field for field in created.json()["fields"]}
    assert {name: (f["type"], f["currency"]) for name, f in fields.items()} == {
        "Price": ("currency", "USD"),
        "Rating": ("rating", None),
    }
    price, rating = (f"property:{fields[name]['id']}" for name in ("Price", "Rating"))

    layouts = await client.get(
        maker.g("/layouts/"),
        headers=maker.headers,
        params={"tool": "collection", "tool_id": created.json()["id"]},
    )
    assert layouts.status_code == 200, layouts.text
    lists = {layout["kind"]: layout for layout in layouts.json()["layouts"]}
    assert {kind for kind, layout in lists.items() if not layout["hidden"]} == {
        "grid",
        "table",
    }
    assert lists["grid"]["is_default"]
    assert [
        child["props"]["field"]
        for child in lists["grid"]["definition"]["card"]["children"]
    ] == ["name", price, rating]
    assert lists["table"]["definition"]["columns"] == ["name", price, rating, "added"]
    assert lists["grid"]["definition"]["displays"] == {rating: "stars"}


async def test_the_shapes_are_offered_in_the_readers_language(
    client: AsyncClient, session, acting_user
):
    reader = await acting_user(guild_role=CommunityRole.member, initiative=True)
    reader.user.locale = "de"
    session.add(reader.user)
    await session.commit()

    listed = await client.get(reader.g("/collections/shapes"), headers=reader.headers)
    assert listed.status_code == 200, listed.text
    entries = {e["key"]: e for group in listed.json() for e in group["entries"]}
    assert list(entries) == ["gallery", "catalog", "log"]
    assert entries["catalog"]["name"] == "Katalog"
    assert entries["catalog"]["fields"][0] == {
        "name": "Preis",
        "type": "currency",
        "display": None,
        "currency": "EUR",
    }


async def test_a_collection_can_start_with_another_collections_shape(
    client: AsyncClient, session, acting_user
):
    owner, maker, shared, _private = await _scene(session, acting_user)
    source = await create_collection(
        session, owner.initiative, owner.user, files=[shared], shape="gallery"
    )
    (caption,) = (await collections_service.fields_of(session, [source.id]))[source.id]
    await create_property_value(session, shared, caption, value_text="Dusk")

    created = await client.post(
        maker.g("/collections/"),
        headers=maker.headers,
        json={
            "initiative_id": maker.initiative.id,
            "name": "Second wall",
            "file_ids": [shared.id],
            "shape_from": source.id,
        },
    )
    assert created.status_code == 201, created.text
    (copied,) = created.json()["fields"]
    assert (copied["name"], copied["type"]) == ("Caption", "text")
    assert copied["id"] != caption.id

    layouts = await client.get(
        maker.g("/layouts/"),
        headers=maker.headers,
        params={"tool": "collection", "tool_id": created.json()["id"]},
    )
    masonry = next(
        layout for layout in layouts.json()["layouts"] if layout["kind"] == "masonry"
    )
    assert masonry["is_default"]
    assert masonry["definition"]["card"]["children"][1]["props"]["field"] == (
        f"property:{copied['id']}"
    )
    # The shape, not the values.
    listed = await client.get(
        maker.g(f"/collections/{created.json()['id']}/files"), headers=maker.headers
    )
    assert listed.json()["items"][0]["fields"] == []


async def test_a_file_maker_fills_a_collections_fields_without_editing_the_file(
    client: AsyncClient, session, acting_user
):
    owner, maker, shared, private = await _scene(session, acting_user)
    collection = await create_collection(
        session, owner.initiative, owner.user, files=[shared, private], shape="catalog"
    )
    price, rating = (await collections_service.fields_of(session, [collection.id]))[
        collection.id
    ]
    path = f"/collections/{collection.id}/files/{shared.id}/fields"

    written = await client.put(
        maker.g(path),
        headers=maker.headers,
        json={
            "values": [
                {"property_id": price.id, "value": "19.99"},
                {"property_id": rating.id, "value": 80},
            ]
        },
    )
    assert written.status_code == 200, written.text
    assert {(v["name"], v["value"], v["currency"]) for v in written.json()} == {
        ("Price", 19.99, "USD"),
        ("Rating", 80, None),
    }
    out_of_range = await client.put(
        maker.g(path),
        headers=maker.headers,
        json={"values": [{"property_id": rating.id, "value": 101}]},
    )
    assert out_of_range.status_code == 400

    # Seen with the collection's files, and not among the file's properties.
    listed = await client.get(
        maker.g(f"/collections/{collection.id}/files"), headers=maker.headers
    )
    assert {v["name"] for v in listed.json()["items"][0]["fields"]} == {
        "Price",
        "Rating",
    }
    opened = await client.get(maker.g(f"/files/{shared.id}"), headers=maker.headers)
    assert opened.json()["properties"] == []
    # Nor written as one.
    as_property = await client.put(
        owner.g(f"/properties/file/{shared.id}"),
        headers=owner.headers,
        json={"values": [{"property_id": rating.id, "value": 10}]},
    )
    assert as_property.status_code == 404

    # A file of the collection the maker cannot open is not one they fill.
    hidden = await client.put(
        maker.g(f"/collections/{collection.id}/files/{private.id}/fields"),
        headers=maker.headers,
        json={"values": [{"property_id": rating.id, "value": 50}]},
    )
    assert hidden.status_code == 422
    assert hidden.json()["detail"] == CollectionMessages.FILE_NOT_IN_COLLECTION


async def test_a_file_taken_out_of_a_collection_leaves_its_values_behind(
    client: AsyncClient, session, acting_user
):
    owner, _maker, shared, private = await _scene(session, acting_user)
    collection = await create_collection(
        session, owner.initiative, owner.user, files=[shared, private], shape="log"
    )
    (day,) = (await collections_service.fields_of(session, [collection.id]))[
        collection.id
    ]
    await create_property_value(session, shared, day, value_date=date(2026, 1, 2))

    removed = await client.delete(
        owner.g(f"/collections/{collection.id}/files"),
        headers=owner.headers,
        params={"file_ids": [shared.id]},
    )
    assert removed.status_code == 204, removed.text

    await route_session_to_guild(session, owner.guild.id)
    left = await session.exec(
        select(PropertyValue).where(PropertyValue.property_id == day.id)
    )
    assert left.all() == []
