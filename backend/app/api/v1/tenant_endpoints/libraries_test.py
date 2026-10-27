"""Tests for the library endpoints — CRUD, the picture list and its paging,
uploads and their validation, versions, covers, tags, and the authorization
gates (feature gate, role create gate, DAC levels).

The library-specific concerns beyond the usual tool contract are the things a
collection of pictures owns: what an upload is allowed to be, that a picture
is reached only through its library, and how the list pages and anchors.
"""

import io
from datetime import date, datetime, timedelta, timezone

from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import KINDS, Tool
from app.models.platform.guild import CommunityRole
from app.models.tenant.library import LibraryItem, LibraryItemVersion
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.models.tenant.upload import Upload
from app.services.tenant import libraries as libraries_service
from app.testing import (
    strip_non_owner_grants,
    create_library,
    create_library_item,
    create_resource_grant,
    create_tag,
    png_bytes,
)


async def _libraries_enabled(session: AsyncSession, initiative) -> None:
    initiative.libraries_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


def _upload(name: str = "shot.png", data: bytes | None = None, **fields):
    """The multipart body the upload endpoints take."""
    return {
        "files": {"file": (name, io.BytesIO(data or png_bytes()), "image/png")},
        "data": fields,
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def test_create_library(client: AsyncClient, acting_user, session):
    """Creating seeds the creator's owner grant plus the default all-members
    read grant."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)

    response = await client.post(
        a.g("/libraries/"),
        headers=a.headers,
        json={
            "name": "Live screen, round 4",
            "description": "Every canvas from the fourth round.",
            "initiative_id": a.initiative.id,
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Live screen, round 4"
    assert body["description"] == "Every canvas from the fourth round."
    assert body["can"]["delete"] is True
    assert body["cover"] is None
    levels = {(g.get("all_initiative_members"), g["level"]) for g in body["grants"]}
    assert (True, "read") in levels


async def test_create_requires_feature_enabled(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    a.initiative.libraries_enabled = False
    session.add(a.initiative)
    await session.commit()

    response = await client.post(
        a.g("/libraries/"),
        headers=a.headers,
        json={"name": "Nope", "initiative_id": a.initiative.id},
    )

    assert response.status_code == 403
    assert response.json() == Tool.library.disabled().body


async def test_create_requires_the_create_permission(
    client: AsyncClient, acting_user, session
):
    """A plain member cannot open a library unless their role says so."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    response = await client.post(
        b.g("/libraries/"),
        headers=b.headers,
        json={"name": "Unauthorized", "initiative_id": a.initiative.id},
    )

    assert response.status_code == 403
    assert response.json() == Tool.library.create_denied().body


async def test_list_carries_newest_picture_as_cover(
    client: AsyncClient, acting_user, session
):
    """A list of libraries is itself visual: each row shows a picture, the
    newest unless one was chosen."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user, name="Store assets")
    older = await create_library_item(
        session,
        library,
        a.user,
        title="old",
        created_at=datetime.now(timezone.utc) - timedelta(days=1),
        write_blob=False,
    )
    newer = await create_library_item(
        session, library, a.user, title="new", write_blob=False
    )

    listing = await client.get(
        a.g("/libraries/"),
        headers=a.headers,
        params={"initiative_id": a.initiative.id, "include_preview": True},
    )
    assert listing.status_code == 200, listing.text
    (item,) = listing.json()["items"]
    # Nothing chosen: no cover, and the preview is the newest first.
    assert item["cover"] is None
    assert item["cover_item_id"] is None
    assert [p["item_id"] for p in item["preview"]] == [newer.id, older.id]

    chosen = await client.patch(
        a.g(f"/libraries/{library.id}"),
        headers=a.headers,
        json={"cover_item_id": older.id},
    )
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["cover"]["item_id"] == older.id
    assert chosen.json()["cover_item_id"] == older.id


async def test_a_description_written_over_another_is_refused(
    client: AsyncClient, acting_user, session
):
    """A description saved over one that has since changed."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user)
    item = await create_library_item(session, library, a.user, write_blob=False)
    path = a.g(f"/library-items/{item.id}")

    first = await client.patch(path, headers=a.headers, json={"description": "Dawn"})
    stale = await client.patch(
        path, headers=a.headers, json={"description": "Dusk", "description_base": None}
    )
    current = await client.patch(
        path,
        headers=a.headers,
        json={"description": "Dusk", "description_base": "Dawn"},
    )

    assert first.status_code == 200, first.text
    assert stale.status_code == 409
    assert stale.json()["detail"] == "DESCRIPTION_CHANGED"
    assert current.json()["description"] == "Dusk"
    assert current.json()["plugin_values"] == []


async def test_preview_is_capped_at_the_newest_few(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user)
    base = datetime(2026, 3, 1, tzinfo=timezone.utc)
    made = [
        await create_library_item(
            session,
            library,
            a.user,
            created_at=base + timedelta(days=d),
            write_blob=False,
        )
        for d in range(6)
    ]

    listing = await client.get(
        a.g("/libraries/"), headers=a.headers, params={"include_preview": True}
    )
    (item,) = listing.json()["items"]
    assert [p["item_id"] for p in item["preview"]] == [
        i.id for i in reversed(made[-libraries_service.PREVIEW_COUNT :])
    ]


async def test_cover_must_be_one_of_the_libraries_own(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user)
    other = await create_library(session, a.initiative, a.user)
    stranger = await create_library_item(session, other, a.user, write_blob=False)

    response = await client.patch(
        a.g(f"/libraries/{library.id}"),
        headers=a.headers,
        json={"cover_item_id": stranger.id},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "LIBRARY_COVER_NOT_IN_LIBRARY"


async def test_update_and_delete_follow_the_dac_levels(
    client: AsyncClient, acting_user, session
):
    """Write access renames; only the owner deletes."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user, name="Before")
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_resource_grant(
        session, library, level=ResourceAccessLevel.write, user=b.user
    )

    renamed = await client.patch(
        b.g(f"/libraries/{library.id}"), headers=b.headers, json={"name": "After"}
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "After"

    refused = await client.delete(b.g(f"/libraries/{library.id}"), headers=b.headers)
    assert refused.status_code == 403

    deleted = await client.delete(a.g(f"/libraries/{library.id}"), headers=a.headers)
    assert deleted.status_code == 204
    gone = await client.get(a.g(f"/libraries/{library.id}"), headers=a.headers)
    assert gone.status_code == 404


async def test_a_member_without_a_grant_cannot_see_it(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user)
    await strip_non_owner_grants(session, library, a.user.id)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    listing = await client.get(b.g("/libraries/"), headers=b.headers)
    assert listing.status_code == 200
    assert listing.json()["total_count"] == 0

    detail = await client.get(b.g(f"/libraries/{library.id}"), headers=b.headers)
    assert detail.status_code in (403, 404)

    pictures = await client.get(b.g(f"/libraries/{library.id}/items"), headers=b.headers)
    assert pictures.status_code in (403, 404)


async def test_counts_by_initiative(client: AsyncClient, acting_user, session):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    await create_library(session, a.initiative, a.user)
    await create_library(session, a.initiative, a.user)

    response = await client.get(a.g("/tools/counts/by-initiative"), headers=a.headers)

    assert response.status_code == 200
    assert response.json()["counts"]["library"] == {str(a.initiative.id): 2}


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------


async def test_upload_a_picture(client: AsyncClient, acting_user, session):
    """An upload is identified from its bytes: the size comes from the PNG
    header, not from anything the client said."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user)

    response = await client.post(
        a.g(f"/libraries/{library.id}/items"),
        headers=a.headers,
        **_upload("report-detail.png", png_bytes(12, 7), title="Report detail"),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["title"] == "Report detail"
    assert body["original_filename"] == "report-detail.png"
    assert body["file_content_type"] == "image/png"
    assert (body["width"], body["height"]) == (12, 7)
    assert body["file_url"].startswith(f"/uploads/{a.guild.id}/")
    assert body["version_count"] == 1
    # A picture no larger than the thumbnail edge gets no thumbnail: the grid
    # would only be shown a copy of what it already has.
    assert body["thumbnail_url"] is None

    # The blob is tracked for the storage quota.
    uploads = (await session.exec(select(Upload))).all()
    assert any(u.filename == body["file_url"].split("/")[-1] for u in uploads)


async def test_a_large_picture_gets_a_thumbnail(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user)

    edge = libraries_service.THUMBNAIL_EDGE + 400
    response = await client.post(
        a.g(f"/libraries/{library.id}/items"),
        headers=a.headers,
        **_upload("big.png", png_bytes(edge, edge // 2)),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["thumbnail_url"] is not None
    assert body["thumbnail_url"].endswith(".webp")
    assert (body["width"], body["height"]) == (edge, edge // 2)


async def test_upload_refuses_what_is_not_a_raster_image(
    client: AsyncClient, acting_user, session
):
    """An SVG is a document rather than a picture, and a mislabelled text file
    is nothing at all; both are refused on their bytes."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user)

    svg = await client.post(
        a.g(f"/libraries/{library.id}/items"),
        headers=a.headers,
        files={
            "file": (
                "x.svg",
                io.BytesIO(b"<svg xmlns='http://www.w3.org/2000/svg'/>"),
                "image/svg+xml",
            )
        },
    )
    assert svg.status_code == 400
    assert svg.json()["detail"] == "IMAGE_INVALID"

    fake = await client.post(
        a.g(f"/libraries/{library.id}/items"),
        headers=a.headers,
        files={
            "file": ("x.png", io.BytesIO(b"not a png at all, honestly"), "image/png")
        },
    )
    assert fake.status_code == 400
    assert fake.json()["detail"] == "IMAGE_INVALID"

    empty = await client.post(
        a.g(f"/libraries/{library.id}/items"),
        headers=a.headers,
        files={"file": ("x.png", io.BytesIO(b""), "image/png")},
    )
    assert empty.status_code == 400
    assert empty.json()["detail"] == "IMAGE_EMPTY"


def test_orphaned_blobs_are_discarded_only_when_that_is_certain(monkeypatch):
    """A failed commit strands the blobs written for it — but only some
    failures prove the rows are not there. A server that rejected a
    constraint definitely did not commit; a connection that dropped may
    have, and deleting then would break a live picture rather than tidy a
    dead one. So the ambiguous case keeps its bytes."""
    from sqlalchemy.exc import IntegrityError, OperationalError

    from app.services.tenant import file_versions

    deleted: list[tuple[int, set[str]]] = []
    monkeypatch.setattr(
        file_versions.attachments_service,
        "delete_blobs",
        lambda guild_id, names: deleted.append((guild_id, set(names))),
    )

    urls: list[str | None] = ["/uploads/1/a.png", "/uploads/1/a-thumb.webp"]
    file_versions.discard_orphans(7, urls, IntegrityError("stmt", {}, Exception()))
    assert deleted == [(7, {"a.png", "a-thumb.webp"})]

    deleted.clear()
    file_versions.discard_orphans(7, urls, OperationalError("stmt", {}, Exception()))
    assert deleted == [], "an inconclusive failure must leave the bytes alone"


async def test_upload_refuses_what_the_decoder_will_not_read(
    client: AsyncClient, acting_user, session
):
    """A header says what a file claims; the decode says whether it is one.
    A truncated PNG passes the first gate and must not pass the second — it
    would sit on the wall as a picture nothing can draw, served at full size
    to every viewer for want of a thumbnail."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user)

    whole = png_bytes(64, 64)
    truncated = whole[: len(whole) // 2]
    # The header still reads: this is exactly the case a header check passes.
    assert libraries_service.validate_image(truncated)[0].width == 64

    response = await client.post(
        a.g(f"/libraries/{library.id}/items"),
        headers=a.headers,
        **_upload("truncated.png", truncated),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "IMAGE_INVALID"
    listing = await client.get(a.g(f"/libraries/{library.id}/items"), headers=a.headers)
    assert listing.json()["total_count"] == 0


async def test_a_jump_lands_on_the_month_whichever_way_the_list_reads(
    client: AsyncClient, acting_user, session
):
    """The rail hands back both ends of a month. Newest first the page walks
    back from the last picture in it; oldest first, forward from the first."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user)
    for month, days in ((1, (5, 20)), (3, (2, 9, 27)), (5, (11,))):
        for day in days:
            await create_library_item(
                session,
                library,
                a.user,
                title=f"{month:02d}-{day:02d}",
                occurred_on=date(2026, month, day),
                write_blob=False,
            )

    rail = await client.get(
        a.g(f"/libraries/{library.id}/items/timeline"), headers=a.headers
    )
    march = next(b for b in rail.json()["buckets"] if b["period"] == "2026-03")
    assert march["count"] == 3

    backwards = await client.get(
        a.g(f"/libraries/{library.id}/items"),
        headers=a.headers,
        params={"until": march["anchor"]},
    )
    assert [i["title"] for i in backwards.json()["items"]][:3] == [
        "03-27",
        "03-09",
        "03-02",
    ]

    forwards = await client.get(
        a.g(f"/libraries/{library.id}/items"),
        headers=a.headers,
        params={"until": march["anchor_oldest"], "oldest_first": "true"},
    )
    assert [i["title"] for i in forwards.json()["items"]][:3] == [
        "03-02",
        "03-09",
        "03-27",
    ]


async def test_upload_needs_write_access_on_the_library(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    response = await client.post(
        b.g(f"/libraries/{library.id}/items"), headers=b.headers, **_upload()
    )

    assert response.status_code == 403
    assert response.json() == Tool.library.write_required().body


# ---------------------------------------------------------------------------
# The picture list
# ---------------------------------------------------------------------------


async def test_pictures_page_newest_first_and_anchor(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user)
    base = datetime(2026, 3, 1, tzinfo=timezone.utc)
    made = []
    for day in range(5):
        made.append(
            await create_library_item(
                session,
                library,
                a.user,
                title=f"day {day}",
                occurred_on=(base + timedelta(days=day)).date(),
                write_blob=False,
            )
        )

    first = await client.get(
        a.g(f"/libraries/{library.id}/items"),
        headers=a.headers,
        params={"page_size": 2},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert [i["title"] for i in body["items"]] == ["day 4", "day 3"]
    assert body["has_next"] is True
    assert body["total_count"] == 5

    last = await client.get(
        a.g(f"/libraries/{library.id}/items"),
        headers=a.headers,
        params={"page_size": 2, "page": 3},
    )
    assert [i["title"] for i in last.json()["items"]] == ["day 0"]
    assert last.json()["has_next"] is False
    assert last.json()["has_prev"] is True

    anchored = await client.get(
        a.g(f"/libraries/{library.id}/items"),
        headers=a.headers,
        params={"until": (base + timedelta(days=2)).isoformat()},
    )
    assert [i["title"] for i in anchored.json()["items"]] == ["day 2", "day 1", "day 0"]

    oldest = await client.get(
        a.g(f"/libraries/{library.id}/items"),
        headers=a.headers,
        params={"oldest_first": "true", "page_size": 2},
    )
    assert [i["title"] for i in oldest.json()["items"]] == ["day 0", "day 1"]


async def test_the_timeline_groups_items_by_the_month_of_their_date(
    client: AsyncClient, acting_user, session
):
    """By the day each item is about, not the day it was added: all three
    were added on one day."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user)
    for day in (date(2026, 1, 15), date(2026, 3, 2), date(2026, 3, 9)):
        await create_library_item(
            session,
            library,
            a.user,
            occurred_on=day,
            created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            write_blob=False,
        )

    response = await client.get(
        a.g(f"/libraries/{library.id}/items/timeline"), headers=a.headers
    )

    assert response.status_code == 200, response.text
    buckets = response.json()["buckets"]
    assert [b["period"] for b in buckets] == ["2026-03", "2026-01"]
    assert [b["count"] for b in buckets] == [2, 1]


async def test_pictures_filter_by_tag_and_search(
    client: AsyncClient, acting_user, session
):
    """Tags on a picture are ANY-of, and the search box reads title, description
    and filename."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user)
    picked = await create_tag(session, a.guild, name="picked")
    waiting = await create_tag(session, a.guild, name="awaiting decision")
    one = await create_library_item(
        session, library, a.user, title="Hero", write_blob=False
    )
    two = await create_library_item(
        session, library, a.user, title="Settings sheet", write_blob=False
    )
    await create_library_item(
        session, library, a.user, title="Untagged", write_blob=False
    )

    tagged = await client.patch(
        a.g(f"/library-items/{one.id}"),
        headers=a.headers,
        json={"tag_ids": [picked.id], "description": "The one we chose"},
    )
    assert tagged.status_code == 200, tagged.text
    assert [t["name"] for t in tagged.json()["tags"]] == ["picked"]
    assert tagged.json()["description"] == "The one we chose"
    await client.patch(
        a.g(f"/library-items/{two.id}"),
        headers=a.headers,
        json={"tag_ids": [waiting.id]},
    )

    # Retagging a picture that already carries tags replaces them — the loaded
    # links are dropped underneath the row, and the save must not try to put
    # them back.
    retagged = await client.patch(
        a.g(f"/library-items/{one.id}"),
        headers=a.headers,
        json={"tag_ids": [waiting.id]},
    )
    assert retagged.status_code == 200, retagged.text
    assert [t["name"] for t in retagged.json()["tags"]] == ["awaiting decision"]
    cleared = await client.patch(
        a.g(f"/library-items/{one.id}"),
        headers=a.headers,
        json={"tag_ids": [picked.id]},
    )
    assert cleared.status_code == 200, cleared.text
    assert [t["name"] for t in cleared.json()["tags"]] == ["picked"]

    by_tag = await client.get(
        a.g(f"/libraries/{library.id}/items"),
        headers=a.headers,
        params={"tag_ids": [picked.id, waiting.id]},
    )
    assert {i["title"] for i in by_tag.json()["items"]} == {"Hero", "Settings sheet"}

    by_word = await client.get(
        a.g(f"/libraries/{library.id}/items"),
        headers=a.headers,
        params={"search": "chose"},
    )
    assert [i["title"] for i in by_word.json()["items"]] == ["Hero"]


async def test_removing_a_picture_trashes_it_and_clears_the_cover(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user)
    item = await create_library_item(session, library, a.user, write_blob=False)
    library.cover_item_id = item.id
    session.add(library)
    await session.commit()

    response = await client.delete(a.g(f"/library-items/{item.id}"), headers=a.headers)
    assert response.status_code == 204

    detail = await client.get(a.g(f"/libraries/{library.id}"), headers=a.headers)
    assert detail.json()["cover"] is None
    assert detail.json()["cover_item_id"] is None
    assert detail.json()["preview"] == []

    trash = await client.get(a.g("/trash/"), headers=a.headers)
    assert trash.status_code == 200
    assert any(
        row["entity_type"] == "library_item" and row["entity_id"] == item.id
        for row in trash.json()["items"]
    )


async def test_bulk_delete_trashes_a_selection_or_nothing(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user)
    other = await create_library(session, a.initiative, a.user)
    mine = [
        await create_library_item(session, library, a.user, write_blob=False)
        for _ in range(3)
    ]
    stranger = await create_library_item(session, other, a.user, write_blob=False)
    library.cover_item_id = mine[0].id
    session.add(library)
    await session.commit()

    # One id from another library refuses the whole request.
    mixed = await client.post(
        a.g(f"/libraries/{library.id}/items/bulk-delete"),
        headers=a.headers,
        json={"item_ids": [mine[0].id, stranger.id]},
    )
    assert mixed.status_code == 404
    assert mixed.json() == KINDS["library_item"].not_found().body
    still = await client.get(a.g(f"/libraries/{library.id}/items"), headers=a.headers)
    assert still.json()["total_count"] == 3

    deleted = await client.post(
        a.g(f"/libraries/{library.id}/items/bulk-delete"),
        headers=a.headers,
        json={"item_ids": [mine[0].id, mine[1].id, mine[1].id]},
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_count"] == 2
    left = await client.get(a.g(f"/libraries/{library.id}/items"), headers=a.headers)
    assert [i["id"] for i in left.json()["items"]] == [mine[2].id]
    detail = await client.get(a.g(f"/libraries/{library.id}"), headers=a.headers)
    assert detail.json()["cover_item_id"] is None


async def test_bulk_delete_needs_write_access(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user)
    item = await create_library_item(session, library, a.user, write_blob=False)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    response = await client.post(
        b.g(f"/libraries/{library.id}/items/bulk-delete"),
        headers=b.headers,
        json={"item_ids": [item.id]},
    )

    assert response.status_code == 403


async def test_bulk_tags_on_pictures_go_through_the_library(
    client: AsyncClient, acting_user, session
):
    """The shared bulk-tag endpoint takes pictures, authorized by their
    library's write gate; a picture from a library the caller cannot write
    refuses the whole request."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user)
    first = await create_library_item(session, library, a.user, write_blob=False)
    second = await create_library_item(session, library, a.user, write_blob=False)
    picked = await create_tag(session, a.guild, name="picked")

    response = await client.post(
        a.g("/tags/bulk"),
        headers=a.headers,
        json={
            "target_type": "library_item",
            "target_ids": [first.id, second.id],
            "add_tag_ids": [picked.id],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["updated_count"] == 2
    listing = await client.get(a.g(f"/libraries/{library.id}/items"), headers=a.headers)
    assert all(
        [t["name"] for t in i["tags"]] == ["picked"] for i in listing.json()["items"]
    )

    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    refused = await client.post(
        b.g("/tags/bulk"),
        headers=b.headers,
        json={
            "target_type": "library_item",
            "target_ids": [first.id],
            "remove_tag_ids": [picked.id],
        },
    )
    assert refused.status_code == 403


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


async def test_versions_replace_the_picture_and_keep_history(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user)
    item = await create_library_item(session, library, a.user, width=4, height=4)
    first_url = item.current_version.file_url

    uploaded = await client.post(
        a.g(f"/library-items/{item.id}/versions"),
        headers=a.headers,
        **_upload("round-2.png", png_bytes(9, 3)),
    )
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["version_number"] == 2
    assert uploaded.json()["is_current"] is True

    current = await client.get(a.g(f"/library-items/{item.id}"), headers=a.headers)
    assert (current.json()["width"], current.json()["height"]) == (9, 3)
    assert current.json()["original_filename"] == "round-2.png"
    assert current.json()["version_count"] == 2
    assert current.json()["file_url"] != first_url

    versions = await client.get(
        a.g(f"/library-items/{item.id}/versions"), headers=a.headers
    )
    assert [v["version_number"] for v in versions.json()] == [2, 1]
    assert [v["is_current"] for v in versions.json()] == [True, False]


async def test_deleting_the_current_version_promotes_the_previous(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user)
    item = await create_library_item(session, library, a.user, width=4, height=4)
    uploaded = await client.post(
        a.g(f"/library-items/{item.id}/versions"),
        headers=a.headers,
        **_upload("round-2.png", png_bytes(9, 3)),
    )
    second_id = uploaded.json()["id"]

    deleted = await client.delete(
        a.g(f"/library-items/{item.id}/versions/{second_id}"),
        headers=a.headers,
    )
    assert deleted.status_code == 204

    current = await client.get(a.g(f"/library-items/{item.id}"), headers=a.headers)
    assert (current.json()["width"], current.json()["height"]) == (4, 4)
    remaining = (
        await session.exec(
            select(LibraryItemVersion).where(
                LibraryItemVersion.library_item_id == item.id
            )
        )
    ).all()
    assert [v.version_number for v in remaining] == [1]
    pointer = await session.exec(
        select(LibraryItem.current_version_id).where(LibraryItem.id == item.id)
    )
    assert pointer.one() == remaining[0].id

    last = await client.delete(
        a.g(f"/library-items/{item.id}/versions/{remaining[0].id}"),
        headers=a.headers,
    )
    assert last.status_code == 400
    assert last.json()["detail"] == "CANNOT_DELETE_LAST_VERSION"


async def test_deleting_a_version_is_the_owners_call(
    client: AsyncClient, acting_user, session
):
    """Write access replaces a picture; destroying its history is the owner's."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user)
    item = await create_library_item(session, library, a.user)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_resource_grant(
        session, library, level=ResourceAccessLevel.write, user=b.user
    )

    uploaded = await client.post(
        b.g(f"/library-items/{item.id}/versions"),
        headers=b.headers,
        **_upload("round-2.png", png_bytes(9, 3)),
    )
    assert uploaded.status_code == 201, uploaded.text

    refused = await client.delete(
        b.g(f"/library-items/{item.id}/versions/{uploaded.json()['id']}"),
        headers=b.headers,
    )
    assert refused.status_code == 403


# ---------------------------------------------------------------------------
# What the item row looks like after a soft delete + purge
# ---------------------------------------------------------------------------


async def test_trashing_a_library_takes_its_pictures(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user)
    item = await create_library_item(session, library, a.user, write_blob=False)

    deleted = await client.delete(a.g(f"/libraries/{library.id}"), headers=a.headers)
    assert deleted.status_code == 204

    from app.db.soft_delete_filter import select_including_deleted

    row = (
        await session.exec(
            select_including_deleted(LibraryItem).where(LibraryItem.id == item.id)
        )
    ).one()
    assert row.deleted_at is not None


async def test_a_copy_has_its_pictures_and_its_cover(
    client: AsyncClient, acting_user, session
):
    from app.testing import route_session_to_guild

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user)
    cover = await create_library_item(session, library, a.user, write_blob=False)
    await create_library_item(session, library, a.user, write_blob=False)
    library.cover_item_id = cover.id
    session.add(library)
    await session.commit()

    response = await client.post(
        a.g(f"/libraries/{library.id}/duplicate"), headers=a.headers
    )

    assert response.status_code == 201, response.text
    copy = response.json()
    assert copy["cover_item_id"] not in (None, cover.id)
    await route_session_to_guild(session, a.guild.id)
    items = (
        await session.exec(
            select(LibraryItem).where(LibraryItem.library_id == copy["id"])
        )
    ).all()
    assert [item.current_version.version_number for item in items] == [1, 1]
    versions = (
        await session.exec(
            select(LibraryItemVersion).where(
                LibraryItemVersion.library_item_id == copy["cover_item_id"]
            )
        )
    ).all()
    assert [(v.version_number, v.file_url) for v in versions] == [
        (1, cover.current_version.file_url)
    ]
    copied_cover = next(i for i in items if i.id == copy["cover_item_id"])
    assert copied_cover.current_version_id == versions[0].id
