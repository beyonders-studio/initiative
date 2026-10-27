"""Collections: seen through the files in them, changed by the initiative's
file makers, gone to the trash once their last file leaves."""

from httpx import AsyncClient
from app.core.messages import CollectionMessages
from app.db import post_commit
from app.db.soft_delete_filter import select_including_deleted
from app.models.platform.guild import CommunityRole
from app.models.tenant.collection import Collection
from app.testing import (
    create_collection,
    create_file,
    create_resource_grant,
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

    renamed = await client.patch(
        maker.g(f"/collections/{collection.id}"),
        headers=maker.headers,
        json={"name": "Renamed by a file maker"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Renamed by a file maker"

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
    # Seeing it is enough to talk about it.
    comment = await client.post(
        maker.g("/comments/"),
        headers=maker.headers,
        json={"content": "Nice set", "collection_id": collection.id},
    )
    assert comment.status_code == 201, comment.text


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
    columns = await client.put(
        maker.g("/layouts/"),
        headers=maker.headers,
        params=params,
        json={"kind": "table", "definition": {"columns": []}},
    )
    assert columns.status_code == 400


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
