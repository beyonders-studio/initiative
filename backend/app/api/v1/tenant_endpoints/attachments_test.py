"""Tests for the attachment upload endpoint."""

import io

import pytest
from httpx import AsyncClient

from app.testing import guild_administration
from app.services.tenant.attachments import detect_document_image_type
from app.models.platform.guild import CommunityRole

#: A real 1x1 PNG — the header reader walks IHDR, so a stub signature is not
#: enough to be identified as one.
TINY_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
    b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00"
    b"\x00\x00\x00IEND\xaeB`\x82"
)


async def test_upload_image_too_large(client: AsyncClient, acting_user):
    """Uploading an image larger than MAX_IMAGE_BYTES returns 413."""
    a = await acting_user(guild_role=CommunityRole.admin)

    oversized = b"\x89PNG\r\n\x1a\n" + b"X" * (11 * 1024 * 1024)
    response = await client.post(
        a.g("/attachments/"),
        headers=a.headers,
        files={"file": ("big.png", io.BytesIO(oversized), "image/png")},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "ATTACHMENT_TOO_LARGE"


async def test_upload_image_within_limit(client: AsyncClient, acting_user):
    """A valid PNG under the size limit is accepted."""
    a = await acting_user(guild_role=CommunityRole.admin)

    response = await client.post(
        a.g("/attachments/"),
        headers=a.headers,
        files={"file": ("pixel.png", io.BytesIO(TINY_PNG), "image/png")},
    )

    assert response.status_code == 201
    assert response.json()["url"].startswith("/uploads/")


async def test_upload_names_the_file_after_its_bytes(client: AsyncClient, acting_user):
    """The stored name and type come from the bytes, not from what the client
    called the file — so the name a serve request reads back describes it."""
    a = await acting_user(guild_role=CommunityRole.admin)
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"></svg>'

    response = await client.post(
        a.g("/attachments/"),
        headers=a.headers,
        files={"file": ("disguised.png", io.BytesIO(svg), "image/png")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["content_type"] == "image/svg+xml"
    assert payload["url"].endswith(".svg")


async def test_upload_ignores_a_declared_svg_type(client: AsyncClient, acting_user):
    """A raster is identified as one however it is labelled."""
    a = await acting_user(guild_role=CommunityRole.admin)

    response = await client.post(
        a.g("/attachments/"),
        headers=a.headers,
        files={"file": ("pixel.svg", io.BytesIO(TINY_PNG), "image/svg+xml")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["content_type"] == "image/png"
    assert payload["url"].endswith(".png")


@pytest.mark.parametrize(
    "prolog",
    [
        b"\xef\xbb\xbf",
        b'<?xml version="1.0" encoding="UTF-8"?>\n',
        b"<!-- exported by a drawing program -->\n",
        b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
        b'"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n',
    ],
)
async def test_upload_accepts_an_svg_behind_a_prolog(
    client: AsyncClient, acting_user, prolog: bytes
):
    """Real SVGs open with a byte-order mark, a declaration, a comment or a
    doctype before the root element; all four are still SVGs."""
    a = await acting_user(guild_role=CommunityRole.admin)
    svg = prolog + b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'

    response = await client.post(
        a.g("/attachments/"),
        headers=a.headers,
        files={"file": ("image.svg", io.BytesIO(svg), "image/svg+xml")},
    )

    assert response.status_code == 201
    assert response.json()["url"].endswith(".svg")


async def test_upload_refuses_bytes_that_are_no_image(client: AsyncClient, acting_user):
    """Nothing the detector recognizes means nothing is stored, whatever the
    client called it."""
    a = await acting_user(guild_role=CommunityRole.admin)

    response = await client.post(
        a.g("/attachments/"),
        headers=a.headers,
        files={
            "file": (
                "payload.png",
                io.BytesIO(b"MZ\x90\x00this is a program, not a picture"),
                "image/png",
            )
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "ATTACHMENT_INVALID_IMAGE"


@pytest.mark.parametrize(
    "contents",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg"></svg>',
        b"<svg/>",
        b'\xef\xbb\xbf<svg xmlns="x"></svg>',
        b'<?xml version="1.0"?>\n<svg xmlns="x"/>',
        b"<!-- drawn by a program -->\n<svg xmlns='x'/>",
        b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
        b'"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n<svg xmlns="x"/>',
        b'<?xml version="1.0"?><!-- one --><!-- two --><svg/>',
    ],
)
def test_an_svg_root_is_found_behind_its_prolog(contents: bytes):
    """Whatever an SVG carries ahead of its root element, the root is what
    decides."""
    assert detect_document_image_type(contents) == "image/svg+xml"


@pytest.mark.parametrize(
    "contents",
    [
        b"<!-- <svg -->not an image",
        b"<svgfoo></svgfoo>",
        b"<html><svg/></html>",
        b"<!-- a comment that never closes <svg/>",
        b"plain text mentioning <svg",
        b"",
    ],
)
def test_markup_that_is_not_an_svg_is_not_an_image(contents: bytes):
    """Naming the element somewhere in the file is not being it — the root
    element is, so none of these are stored as pictures."""
    assert detect_document_image_type(contents) is None


def test_a_raster_is_identified_before_markup():
    """A raster signature settles it; nothing goes looking for markup in a PNG."""
    assert detect_document_image_type(TINY_PNG) == "image/png"


# ---------------------------------------------------------------------------
# Pictures pasted into a task's description or a comment
# ---------------------------------------------------------------------------


async def _paste(client: AsyncClient, a) -> str:
    response = await client.post(
        a.g("/attachments/pasted"),
        headers=a.headers,
        files={"file": ("pasted.png", io.BytesIO(TINY_PNG), "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()["url"]


async def _stored(session, guild_id: int, url: str) -> bool:
    """Whether the upload's row and its bytes are both still there."""
    from pathlib import Path

    from sqlmodel import select

    from app.models.tenant.upload import Upload
    from app.services.storage import get_guild_storage
    from app.testing.schema_harness import route_session_to_guild

    name = Path(url).name
    await route_session_to_guild(session, guild_id)
    row = (await session.exec(select(Upload).where(Upload.filename == name))).first()
    return row is not None and get_guild_storage(guild_id).exists(name)


async def _set_description(client: AsyncClient, a, task_id: int, text: str) -> None:
    response = await client.patch(
        a.g(f"/tasks/{task_id}"), headers=a.headers, json={"description": text}
    )
    assert response.status_code == 200, response.text


async def test_a_pasted_picture_is_named_as_pasted(client: AsyncClient, acting_user):
    from app.services.tenant.attachments import PASTED_IMAGE_PREFIX

    a = await acting_user(guild_role=CommunityRole.member)

    url = await _paste(client, a)

    assert url.startswith(f"/uploads/{a.guild.id}/{PASTED_IMAGE_PREFIX}")


async def test_taking_a_picture_out_of_a_description_deletes_it(
    client: AsyncClient, session, acting_user
):
    from app.testing import create_task

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, a.project)
    await session.commit()
    url = await _paste(client, a)

    await _set_description(client, a, task.id, f"Look: ![shot]({url})")
    assert await _stored(session, a.guild.id, url)

    session.expunge_all()
    await _set_description(client, a, task.id, "Never mind")
    assert not await _stored(session, a.guild.id, url)


async def test_a_picture_another_task_still_shows_stays(
    client: AsyncClient, session, acting_user
):
    """A duplicated task shares its original's pictures, and one that shows
    it counts wherever it is — in an initiative the editor is not in too."""
    from app.testing import create_task

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    other = await acting_user(
        guild_role=CommunityRole.member, guild=a.guild, initiative=True, project=True
    )
    url = await _paste(client, a)
    task = await create_task(session, a.project, description=f"![shot]({url})")
    await create_task(session, other.project, description=f"copy ![shot]({url})")
    await session.commit()

    await _set_description(client, a, task.id, "Never mind")

    assert await _stored(session, a.guild.id, url)


async def test_a_picture_that_is_not_a_description_s_is_never_deleted(
    client: AsyncClient, session, acting_user
):
    """An image pasted from a file keeps its own name, so taking it out of
    a description leaves the file's picture alone."""
    from app.testing import create_task

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    response = await client.post(
        a.g("/attachments/"),
        headers=a.headers,
        files={"file": ("doc.png", io.BytesIO(TINY_PNG), "image/png")},
    )
    doc_url = response.json()["url"]
    task = await create_task(session, a.project, description=f"![doc]({doc_url})")
    await session.commit()

    await _set_description(client, a, task.id, "Never mind")

    assert await _stored(session, a.guild.id, doc_url)


async def test_purging_a_task_deletes_its_pictures(
    client: AsyncClient, session, acting_user
):
    from app.services.tenant.soft_delete import hard_purge_entity, soft_delete_entity
    from app.testing import create_task
    from app.testing.schema_harness import route_session_to_guild

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    url = await _paste(client, a)
    task = await create_task(session, a.project, description=f"![shot]({url})")
    await session.commit()

    await route_session_to_guild(session, a.guild.id)
    await soft_delete_entity(
        session, task, deleted_by_user_id=a.user.id, retention_days=30
    )
    await session.commit()
    # In the trash it still pins its pictures — it may come back.
    assert await _stored(session, a.guild.id, url)

    await hard_purge_entity(session, task)
    await session.commit()

    assert not await _stored(session, a.guild.id, url)


def _lexical(*urls: str) -> dict:
    """A file body showing these pictures."""
    return {"root": {"children": [{"type": "image", "src": url} for url in urls]}}


async def test_a_picture_taken_out_of_a_file_goes_when_nothing_shows_it(
    client: AsyncClient, session, acting_user
):
    """Editing a file lets go of a picture it stopped showing, but only
    once nothing else shows it, and only a file this community stores — a
    body naming another community's file leaves that file alone. A duplicate
    shows its own copy, stored at the same size, so it is not what keeps the
    original."""
    from pathlib import Path

    from sqlmodel import select

    from app.models.tenant.upload import Upload
    from app.testing import create_file

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    b = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    url = await _paste(client, a)
    elsewhere = await _paste(client, b)
    first = await create_file(session, a.initiative, a.user, content=_lexical(url))
    second = await create_file(
        session, a.initiative, a.user, content=_lexical(url, elsewhere)
    )
    await session.commit()

    duplicate = await client.post(
        a.g(f"/files/{first.id}/duplicate"), headers=a.headers, json={"name": "C"}
    )
    assert duplicate.status_code == 201, duplicate.text
    copy = duplicate.json()["content"]["root"]["children"][0]["src"]
    assert copy != url and await _stored(session, a.guild.id, copy)
    sizes = await session.exec(
        select(Upload.size_bytes).where(
            Upload.filename.in_([Path(url).name, Path(copy).name])
        )
    )
    assert set(sizes.all()) == {len(TINY_PNG)}

    async def clear(file_id: int) -> None:
        response = await client.patch(
            a.g(f"/files/{file_id}"),
            headers=a.headers,
            json={"content": _lexical()},
        )
        assert response.status_code == 200, response.text

    await clear(first.id)
    assert await _stored(session, a.guild.id, url), "the second one still shows it"

    await clear(second.id)
    assert not await _stored(session, a.guild.id, url)
    assert await _stored(session, b.guild.id, elsewhere)


async def _discard(client: AsyncClient, a, url: str) -> None:
    from pathlib import Path

    response = await client.delete(
        a.g(f"/attachments/pasted/{Path(url).name}"), headers=a.headers
    )
    assert response.status_code == 204, response.text


async def test_a_picture_left_unsaved_is_discarded(
    client: AsyncClient, session, acting_user
):
    a = await acting_user(guild_role=CommunityRole.member)
    url = await _paste(client, a)

    await _discard(client, a, url)

    assert not await _stored(session, a.guild.id, url)


async def test_a_saved_picture_is_not_discarded(
    client: AsyncClient, session, acting_user
):
    """The page asks about everything it pasted; the ones a description kept
    stay."""
    from app.testing import create_task

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    url = await _paste(client, a)
    await create_task(session, a.project, description=f"![shot]({url})")
    await session.commit()

    await _discard(client, a, url)

    assert await _stored(session, a.guild.id, url)


async def test_nobody_discards_somebody_else_s_picture(
    client: AsyncClient, session, acting_user
):
    a = await acting_user(guild_role=CommunityRole.member)
    b = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    url = await _paste(client, a)

    await _discard(client, b, url)

    assert await _stored(session, a.guild.id, url)


async def test_only_a_pasted_picture_can_be_discarded(
    client: AsyncClient, session, acting_user
):
    a = await acting_user(guild_role=CommunityRole.member)
    response = await client.post(
        a.g("/attachments/"),
        headers=a.headers,
        files={"file": ("doc.png", io.BytesIO(TINY_PNG), "image/png")},
    )
    doc_url = response.json()["url"]

    await _discard(client, a, doc_url)

    assert await _stored(session, a.guild.id, doc_url)


async def test_the_sweep_takes_pictures_nobody_saved_once_their_grace_is_over(
    client: AsyncClient, session, acting_user
):
    """A tab closed rather than left never discards what it pasted. A saved
    one is claimed for the initiative that shows it and not looked at again."""
    from datetime import datetime, timedelta, timezone

    from sqlmodel import select

    from app.models.tenant.upload import Upload
    from app.services.tenant.attachments import (
        UNCLAIMED_PASTED_IMAGE_GRACE,
        release_unclaimed_pasted_images,
    )
    from app.testing import create_task
    from app.testing.schema_harness import route_session_to_guild

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    unsaved = await _paste(client, a)
    saved = await _paste(client, a)
    task = await create_task(session, a.project, description=f"![shot]({saved})")
    await session.commit()

    await route_session_to_guild(session, a.guild.id)
    now = datetime.now(timezone.utc)
    # Within the grace period, both stay: the draft may still be saved.
    assert await release_unclaimed_pasted_images(session, now=now) == set()

    later = now + UNCLAIMED_PASTED_IMAGE_GRACE + timedelta(minutes=1)
    released = await release_unclaimed_pasted_images(session, now=later)

    assert released == {unsaved.rsplit("/", 1)[1]}
    saved_name = saved.rsplit("/", 1)[1]
    claimed = (
        await session.exec(select(Upload).where(Upload.filename == saved_name))
    ).one()
    assert claimed.claimed_at is not None
    assert claimed.initiative_id == a.initiative.id

    # Once claimed, the sweep leaves it alone even when nothing shows it.
    task.description = "No picture"
    session.add(task)
    await session.commit()
    assert await release_unclaimed_pasted_images(session, now=later) == set()
    assert await _stored(session, a.guild.id, saved)


async def test_the_sweep_copies_a_picture_two_initiatives_show(
    client: AsyncClient, session, acting_user
):
    """The oldest showing row's initiative keeps the file, and the other gets
    a copy of its own that its row shows."""
    from datetime import datetime, timedelta, timezone

    from sqlmodel import select

    from app.models.tenant.task import Task
    from app.models.tenant.upload import Upload
    from app.services.tenant.attachments import (
        UNCLAIMED_PASTED_IMAGE_GRACE,
        release_unclaimed_pasted_images,
    )
    from app.testing import create_initiative, create_project, create_task
    from app.testing.schema_harness import route_session_to_guild

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    elsewhere = await create_initiative(session, a.guild, a.user)
    other = await create_project(session, elsewhere, a.user)
    url = await _paste(client, a)
    await create_task(session, a.project, description=f"![shot]({url})")
    later_task = await create_task(session, other, description=f"![shot]({url})")
    await session.commit()

    await route_session_to_guild(session, a.guild.id)
    later = datetime.now(timezone.utc) + UNCLAIMED_PASTED_IMAGE_GRACE
    assert (
        await release_unclaimed_pasted_images(session, now=later + timedelta(minutes=1))
        == set()
    )

    kept = {
        u.filename: u.initiative_id
        for u in await session.exec(
            select(Upload).execution_options(populate_existing=True)
        )
    }
    name = url.rsplit("/", 1)[1]
    [copy] = set(kept) - {name}
    assert kept == {name: a.initiative.id, copy: elsewhere.id}
    description = (
        await session.exec(
            select(Task.description)
            .where(Task.id == later_task.id)
            .execution_options(populate_existing=True)
        )
    ).one()
    assert description == f"![shot](/uploads/{a.guild.id}/{copy})"
    assert await _stored(session, a.guild.id, f"/uploads/{a.guild.id}/{copy}")


async def _edit_comment(client: AsyncClient, a, comment_id: int, text: str) -> None:
    response = await client.patch(
        a.g(f"/comments/{comment_id}"), headers=a.headers, json={"content": text}
    )
    assert response.status_code == 200, response.text


async def test_taking_a_picture_out_of_a_comment_deletes_it(
    client: AsyncClient, session, acting_user
):
    from app.testing import create_comment, create_task

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, a.project)
    url = await _paste(client, a)
    comment = await create_comment(
        session, a.user, task=task, content=f"Here: ![shot]({url})"
    )
    await session.commit()

    await _edit_comment(client, a, comment.id, "Never mind")

    assert not await _stored(session, a.guild.id, url)


async def test_a_picture_a_comment_shows_outlives_the_description(
    client: AsyncClient, session, acting_user
):
    """A picture moved between a description and a comment is the same file;
    either one showing it keeps it."""
    from app.testing import create_comment, create_task

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    url = await _paste(client, a)
    task = await create_task(session, a.project, description=f"![shot]({url})")
    await create_comment(session, a.user, task=task, content=f"again ![shot]({url})")
    await session.commit()

    await _set_description(client, a, task.id, "Never mind")

    assert await _stored(session, a.guild.id, url)


async def test_purging_a_task_takes_its_comments_pictures_too(
    client: AsyncClient, session, acting_user
):
    from app.services.tenant.soft_delete import hard_purge_entity, soft_delete_entity
    from app.testing import create_comment, create_task
    from app.testing.schema_harness import route_session_to_guild

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    url = await _paste(client, a)
    task = await create_task(session, a.project)
    await create_comment(session, a.user, task=task, content=f"![shot]({url})")
    await session.commit()

    await route_session_to_guild(session, a.guild.id)
    await soft_delete_entity(
        session, task, deleted_by_user_id=a.user.id, retention_days=30
    )
    await session.commit()
    await hard_purge_entity(session, task)
    await session.commit()

    assert not await _stored(session, a.guild.id, url)


async def _status(client: AsyncClient, a, url: str) -> int:
    return (await client.get(url, headers=a.headers)).status_code


async def _uploads(session, guild_id: int) -> list:
    from sqlmodel import select

    from app.models.tenant.upload import Upload
    from app.testing.schema_harness import route_session_to_guild

    await route_session_to_guild(session, guild_id)
    rows = await session.exec(select(Upload).execution_options(populate_existing=True))
    return list(rows.all())


async def test_a_saved_picture_reaches_its_initiative_and_nobody_else(
    client: AsyncClient, session, acting_user
):
    """Until it is saved a picture is its uploader's; once a task shows it,
    the task's initiative reads it and the rest of the guild does not."""
    from app.testing import create_task

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    peer = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    outsider = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    url = await _paste(client, a)
    task = await create_task(session, a.project)
    await session.commit()

    assert await _status(client, a, url) == 200
    assert await _status(client, peer, url) == 404

    await _set_description(client, a, task.id, f"![shot]({url})")

    assert await _status(client, peer, url) == 200
    assert await _status(client, outsider, url) == 404


async def test_one_picture_in_a_file_and_a_task_stays_one_file(
    client: AsyncClient, session, acting_user
):
    from app.testing import create_file, create_task

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    url = await _paste(client, a)
    task = await create_task(session, a.project)
    file = await create_file(session, a.initiative, a.user)
    await session.commit()

    await _set_description(client, a, task.id, f"![shot]({url})")
    response = await client.patch(
        a.g(f"/files/{file.id}"),
        headers=a.headers,
        json={"content": _lexical(url)},
    )

    assert response.status_code == 200, response.text
    assert response.json()["content"]["root"]["children"][0]["src"] == url
    [upload] = await _uploads(session, a.guild.id)
    assert upload.initiative_id == a.initiative.id


async def test_a_picture_pasted_from_another_initiative_is_copied(
    client: AsyncClient, session, acting_user
):
    """Saving a picture kept for another initiative makes one copy for this
    one, which its members read, and leaves the original where it was."""
    from app.testing import create_initiative, create_project, create_task

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    elsewhere = await create_initiative(session, a.guild, a.user)
    project = await create_project(session, elsewhere, a.user)
    there = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=elsewhere,
        initiative_role="member",
    )
    url = await _paste(client, a)
    first = await create_task(session, a.project)
    second = await create_task(session, project)
    await session.commit()
    await _set_description(client, a, first.id, f"![shot]({url})")

    await _set_description(client, a, second.id, f"![shot]({url}) and ![again]({url})")

    response = await client.get(a.g(f"/tasks/{second.id}"), headers=a.headers)
    copy = response.json()["description"].split("(")[1].split(")")[0]
    assert copy != url
    assert response.json()["description"] == f"![shot]({copy}) and ![again]({copy})"
    kept = {u.filename: u.initiative_id for u in await _uploads(session, a.guild.id)}
    assert kept == {
        url.rsplit("/", 1)[1]: a.initiative.id,
        copy.rsplit("/", 1)[1]: elsewhere.id,
    }
    assert await _status(client, there, copy) == 200
    assert await _status(client, there, url) == 404


async def test_a_picture_copied_into_a_file_reaches_its_live_state(
    client: AsyncClient, session, acting_user
):
    """The copy's address is written into the file's stored Yjs state as
    well as its content, so a live session merges it in rather than writing
    the original's back."""
    from sqlalchemy.orm import undefer
    from sqlmodel import select

    from app.models.tenant.file import File
    from app.services.tenant.body_states import LEXICAL
    from app.testing import create_file, create_initiative, lexical_body

    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    elsewhere = await create_initiative(session, a.guild, a.user)
    url = await _paste(client, a)
    body = lexical_body("A picture")
    body["root"]["children"][0]["children"].append(
        {"type": "image", "src": url, "altText": "shot", "version": 1}
    )
    first = await create_file(session, a.initiative, a.user)
    doc = await create_file(
        session,
        elsewhere,
        a.user,
        content=lexical_body("Nothing yet"),
        yjs_state=await LEXICAL.bootstrap(lexical_body("Nothing yet")),
    )
    await session.commit()
    kept = await client.patch(
        a.g(f"/files/{first.id}"), headers=a.headers, json={"content": body}
    )
    assert kept.status_code == 200, kept.text

    response = await client.patch(
        a.g(f"/files/{doc.id}"), headers=a.headers, json={"content": body}
    )

    assert response.status_code == 200, response.text
    saved = (
        await session.exec(
            select(File)
            .where(File.id == doc.id)
            .options(undefer(File.content), undefer(File.yjs_state))
            .execution_options(populate_existing=True)
        )
    ).one()
    [image] = [
        node
        for node in saved.content["root"]["children"][0]["children"]
        if node["type"] == "image"
    ]
    assert image["src"] != url
    rendered = await LEXICAL.render(saved.yjs_state or b"")
    assert rendered is not None
    assert image["src"] in str(rendered) and url not in str(rendered)


async def test_a_picture_the_saver_cannot_read_is_left_as_written(
    client: AsyncClient, session, acting_user
):
    from app.testing import create_task

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    c = await acting_user(
        guild_role=CommunityRole.member, guild=a.guild, initiative=True, project=True
    )
    url = await _paste(client, a)
    mine = await create_task(session, a.project)
    theirs = await create_task(session, c.project)
    await session.commit()
    await _set_description(client, a, mine.id, f"![shot]({url})")

    await _set_description(client, c, theirs.id, f"![shot]({url})")

    response = await client.get(c.g(f"/tasks/{theirs.id}"), headers=c.headers)
    assert response.json()["description"] == f"![shot]({url})"
    assert len(await _uploads(session, a.guild.id)) == 1
    assert await _status(client, c, url) == 404


async def test_a_plugin_copies_only_a_picture_it_reads_through_content(
    client: AsyncClient, session, acting_user, role_session
):
    """An install placed in two initiatives copies a picture into the second
    only when content it may read shows it: a file does here, and a task,
    under a scope it was not granted, does not."""
    from sqlmodel import select

    from app.models.tenant.plugin_placement import PluginPlacement
    from app.models.tenant.file import File
    from app.testing import (
        create_file,
        create_project,
        create_resource_grant,
        create_task,
        guild_url,
        route_session_to_guild,
    )
    from app.testing.plugin_clients import install_plugin, install_headers

    scopes = ["files:read", "files:write"]
    installed = await install_plugin(session, acting_user, role_session, granted=scopes)
    seat = installed.seat
    in_task, in_file = await _paste(client, seat), await _paste(client, seat)
    task = await create_task(
        session, await create_project(session, installed.placed, seat.user)
    )
    file = await create_file(session, installed.placed, seat.user)
    await create_resource_grant(session, file, all_initiative_members=True)
    await route_session_to_guild(session, installed.guild.id)
    session.add(
        PluginPlacement(
            install_id=installed.plugin.id, initiative_id=installed.unplaced.id
        )
    )
    await session.commit()
    await _set_description(client, seat, task.id, f"![shot]({in_task})")
    saved = await client.patch(
        seat.g(f"/files/{file.id}"),
        headers=seat.headers,
        json={"content": _lexical(in_file)},
    )
    assert saved.status_code == 200, saved.text

    response = await client.post(
        guild_url(installed.guild.id, "/files/"),
        headers=install_headers(installed, scopes),
        json={
            "name": "Elsewhere",
            "initiative_id": installed.unplaced.id,
            "content": _lexical(in_task, in_file),
        },
    )

    assert response.status_code == 201, response.text
    # An install reads no stored file's path back, so the saved body is read
    # where it is kept.
    saved_body = (
        await session.exec(
            select(File.content)
            .where(File.id == response.json()["id"])
            .execution_options(populate_existing=True)
        )
    ).one()
    shown = [c["src"] for c in saved_body["root"]["children"]]
    assert shown[0] == in_task
    assert shown[1] != in_file


async def test_a_plugin_moving_a_task_carries_its_picture(
    client: AsyncClient, session, acting_user, role_session
):
    """A task an install moves into another initiative it is placed in takes a
    copy of the picture only it shows: the content came with the task."""
    from app.models.tenant.plugin_placement import PluginPlacement
    from app.models.tenant.resource_grant import ResourceAccessLevel
    from app.testing import (
        create_project,
        create_resource_grant,
        create_task,
        guild_url,
        route_session_to_guild,
    )
    from app.testing.plugin_clients import install_plugin, install_headers

    scopes = ["projects:read", "projects:write"]
    installed = await install_plugin(session, acting_user, role_session, granted=scopes)
    seat = installed.seat
    here = await create_project(session, installed.placed, seat.user)
    there = await create_project(session, installed.unplaced, seat.user)
    for project in (here, there):
        await create_resource_grant(
            session,
            project,
            all_initiative_members=True,
            level=ResourceAccessLevel.write,
        )
    task = await create_task(session, here)
    await route_session_to_guild(session, installed.guild.id)
    session.add(
        PluginPlacement(
            install_id=installed.plugin.id, initiative_id=installed.unplaced.id
        )
    )
    await session.commit()
    url = await _paste(client, seat)
    await _set_description(client, seat, task.id, f"![shot]({url})")

    moved = await client.post(
        guild_url(installed.guild.id, f"/tasks/{task.id}/move"),
        headers=install_headers(installed, scopes),
        json={"target_project_id": there.id},
    )

    assert moved.status_code == 200, moved.text
    assert url not in moved.json()["description"]


async def test_a_task_moved_to_another_initiative_takes_copies_of_its_pictures(
    client: AsyncClient, session, acting_user
):
    """The task and its conversation show one copy kept for the destination;
    the original still serves the initiative it came from."""
    from app.testing import create_comment, create_initiative, create_project
    from app.testing import create_task

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    stay = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    elsewhere = await create_initiative(session, a.guild, a.user)
    destination = await create_project(session, elsewhere, a.user)
    there = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=elsewhere,
        initiative_role="member",
    )
    url = await _paste(client, a)
    task = await create_task(session, a.project)
    await session.commit()
    await _set_description(client, a, task.id, f"![shot]({url})")
    comment = await create_comment(
        session, a.user, task=task, content=f"See ![shot]({url})"
    )
    await session.commit()

    response = await client.post(
        a.g(f"/tasks/{task.id}/move"),
        headers=a.headers,
        json={"target_project_id": destination.id},
    )

    assert response.status_code == 200, response.text
    copy = response.json()["description"].removeprefix("![shot](").removesuffix(")")
    assert copy != url
    await session.refresh(comment)
    assert comment.content == f"See ![shot]({copy})"
    assert await _status(client, there, copy) == 200
    assert await _status(client, there, url) == 404
    assert await _status(client, stay, url) == 200


async def test_the_quota_counts_files_the_uploader_cannot_read(
    client: AsyncClient, session, acting_user
):

    from app.testing import create_upload

    a = await acting_user(guild_role=CommunityRole.member)
    other = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    await create_upload(session, a.guild, other.user, size_bytes=1000)
    await guild_administration(
        session, a.guild, max_storage_bytes=1000 + len(TINY_PNG) - 1
    )

    response = await client.post(
        a.g("/attachments/pasted"),
        headers=a.headers,
        files={"file": ("pasted.png", io.BytesIO(TINY_PNG), "image/png")},
    )

    assert response.status_code == 507
    assert response.json()["detail"] == "ATTACHMENT_STORAGE_QUOTA_EXCEEDED"
