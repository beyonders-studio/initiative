"""
Integration tests for file-version endpoints:
upload new version, list versions, download a specific version, delete a version.
"""

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.storage import get_guild_storage
from app.services.tenant import attachments as attachments_service
from app.models.tenant.file import (
    File,
    FileVersion,
)
from app.models.platform.guild import CommunityRole
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.models.tenant.upload import Upload
from app.testing import create_resource_grant
from app.testing.plugin_clients import install_plugin, install_headers

PDF_BYTES = b"%PDF-1.4 first version body"
PDF_BYTES_V2 = b"%PDF-1.4 second version body that differs"


async def _upload_initial_file_doc(
    client: AsyncClient,
    actor,
    *,
    initiative,
    name: str = "Versioned Doc",
    content: bytes = PDF_BYTES,
    filename: str = "v1.pdf",
    content_type: str = "application/pdf",
) -> dict:
    """Create an uploaded file through the real upload endpoint (creates v1)."""
    response = await client.post(
        actor.g("/files/upload"),
        headers=actor.headers,
        data={"name": name, "initiative_id": str(initiative.id)},
        files={"file": (filename, content, content_type)},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _share(session: AsyncSession, doc: dict, actor, level) -> None:
    await create_resource_grant(
        session, await session.get(File, doc["id"]), user=actor.user, level=level
    )


async def test_upload_and_duplicate_each_start_at_version_one(
    client: AsyncClient, acting_user
) -> None:
    """Uploading an uploaded file seeds version 1, and a duplicate of it is a
    uploaded file of its own: a copy of the file, at its own version 1."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await _upload_initial_file_doc(client, owner, initiative=owner.initiative)

    duplicate = await client.post(
        owner.g(f"/files/{doc['id']}/duplicate"), headers=owner.headers
    )
    assert duplicate.status_code == 201, duplicate.text
    copy = duplicate.json()
    assert copy["file_type"] == "pdf"
    assert copy["file_url"] != doc["file_url"]

    for file in (doc, copy):
        resp = await client.get(
            owner.g(f"/files/{file['id']}/versions"), headers=owner.headers
        )
        assert resp.status_code == 200
        assert [(v["version_number"], v["is_current"]) for v in resp.json()] == [
            (1, True)
        ]
    downloaded = await client.get(
        owner.g(f"/files/{copy['id']}/download"), headers=owner.headers
    )
    assert downloaded.status_code == 200
    assert downloaded.content == PDF_BYTES


async def test_a_plugin_copies_a_uploaded_file_under_its_uploader(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
) -> None:
    """A plug-in with the file scopes copies the file an uploaded file shows, and
    the copy's version 1 names the file's uploader: a plug-in is never an
    author. The plug-in reads each stored file as an empty string and a cover from
    elsewhere as it is; a person reads the paths."""
    scopes = ["files:read", "files:write"]
    installed = await install_plugin(session, acting_user, role_session, granted=scopes)
    # Uploaded files are shared with the initiative the install is placed
    # in, and read is enough to copy a template.
    doc = await _upload_initial_file_doc(
        client,
        installed.seat,
        initiative=installed.placed,
        content=_TINY_PNG,
        filename="v1.png",
        content_type="image/png",
    )
    template = await session.get(File, doc["id"])
    assert template is not None
    template.is_template = True
    session.add(template)
    await session.commit()

    response = await client.post(
        installed.seat.g(f"/files/{doc['id']}/duplicate"),
        headers=install_headers(installed, scopes),
    )

    assert response.status_code == 201, response.text
    copy = response.json()
    assert (copy["file_url"], copy["featured_image_url"]) == ("", None)
    assert "/uploads/" not in response.text
    person = await client.get(
        installed.seat.g(f"/files/{copy['id']}"), headers=installed.seat.headers
    )
    assert person.json()["file_url"].startswith(f"/uploads/{installed.guild.id}/")
    assert person.json()["file_url"] != doc["file_url"]

    # A cover from elsewhere reaches the plug-in as it is; a PDF shows none.
    cover = "https://pictures.example/cover.png"
    updated = await client.patch(
        installed.seat.g(f"/files/{copy['id']}"),
        headers=installed.seat.headers,
        json={"featured_image_url": cover},
    )
    assert updated.status_code == 200, updated.text
    pdf = await _upload_initial_file_doc(
        client, installed.seat, initiative=installed.placed, name="Notes"
    )
    listed = await client.get(
        installed.seat.g("/files/"), headers=install_headers(installed, scopes)
    )
    assert listed.status_code == 200, listed.text
    assert "/uploads/" not in listed.text
    assert {
        item["id"]: (item["file_url"], item["featured_image_url"])
        for item in listed.json()["items"]
    } == {doc["id"]: ("", None), copy["id"]: ("", cover), pdf["id"]: ("", None)}
    read = await client.get(
        installed.seat.g(f"/files/{doc['id']}"),
        headers=install_headers(installed, scopes),
    )
    assert read.status_code == 200, read.text
    assert (read.json()["file_url"], read.json()["featured_image_url"]) == ("", None)
    version = (
        await session.exec(select(FileVersion).where(FileVersion.file_id == copy["id"]))
    ).one()
    assert version.created_by == installed.seat.user.id


async def test_upload_version_creates_v2_and_points_the_file_at_it(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """A write user uploads v2; the file points at it, and it has its
    Upload row and version row."""
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    writer = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )

    doc = await _upload_initial_file_doc(client, owner, initiative=owner.initiative)
    await _share(session, doc, writer, ResourceAccessLevel.write)

    resp = await client.post(
        writer.g(f"/files/{doc['id']}/versions"),
        headers=writer.headers,
        files={"file": ("v2.pdf", PDF_BYTES_V2, "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["version_number"] == 2
    assert body["is_current"] is True

    read = await client.get(writer.g(f"/files/{doc['id']}"), headers=writer.headers)
    assert (read.json()["file_size"], read.json()["original_filename"]) == (
        len(PDF_BYTES_V2),
        "v2.pdf",
    )
    session.expire_all()
    refreshed = await session.get(File, doc["id"])
    assert refreshed.current_version_id == body["id"]

    # Two version rows + two Upload rows exist.
    versions = (
        await session.exec(select(FileVersion).where(FileVersion.file_id == doc["id"]))
    ).all()
    assert {v.version_number for v in versions} == {1, 2}
    for v in versions:
        upload = (
            await session.exec(
                select(Upload).where(Upload.filename == v.file_url.split("/")[-1])
            )
        ).one_or_none()
        assert upload is not None


async def test_upload_version_read_user_forbidden(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """A read-only user cannot upload a new version."""
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    reader = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )

    doc = await _upload_initial_file_doc(client, owner, initiative=owner.initiative)
    await _share(session, doc, reader, ResourceAccessLevel.read)

    resp = await client.post(
        reader.g(f"/files/{doc['id']}/versions"),
        headers=reader.headers,
        files={"file": ("v2.pdf", PDF_BYTES_V2, "application/pdf")},
    )
    assert resp.status_code == 403


async def test_upload_version_type_mismatch_rejected(
    client: AsyncClient, acting_user
) -> None:
    """A new version must be the same kind of file as the one it replaces."""
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    doc = await _upload_initial_file_doc(client, owner, initiative=owner.initiative)

    resp = await client.post(
        owner.g(f"/files/{doc['id']}/versions"),
        headers=owner.headers,
        files={"file": ("notes.txt", b"plain text not a pdf", "text/plain")},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "FILE_VERSION_TYPE_MISMATCH"


async def test_a_new_version_may_change_format_within_its_kind(
    client: AsyncClient, acting_user
) -> None:
    """A picture stays a picture, though a PNG may become a JPEG. The file's
    type follows its current version, and a picture features no image."""
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    doc = await _upload_initial_file_doc(
        client,
        owner,
        initiative=owner.initiative,
        content=_TINY_PNG,
        filename="site.png",
        content_type="image/png",
    )
    assert (doc["file_type"], doc["kind"], doc["featured_image_url"]) == (
        "png",
        "image",
        None,
    )

    resp = await client.post(
        owner.g(f"/files/{doc['id']}/versions"),
        headers=owner.headers,
        files={"file": ("site.jpg", b"\xff\xd8\xff\xe0\x00\x10JFIF\x00", "image/jpeg")},
    )
    assert resp.status_code == 201, resp.text
    read = await client.get(owner.g(f"/files/{doc['id']}"), headers=owner.headers)
    assert read.json()["file_type"] == "jpeg"


async def test_upload_version_non_uploaded_file_rejected(
    client: AsyncClient, acting_user
) -> None:
    """Native files don't support versions."""
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    create = await client.post(
        owner.g("/files/"),
        headers=owner.headers,
        json={"name": "Native doc", "initiative_id": owner.initiative.id},
    )
    assert create.status_code == 201
    native_id = create.json()["id"]

    resp = await client.post(
        owner.g(f"/files/{native_id}/versions"),
        headers=owner.headers,
        files={"file": ("v2.pdf", PDF_BYTES_V2, "application/pdf")},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "FILE_NOT_AN_UPLOADED_FILE"

    # Listing versions on a non-uploaded file is rejected too.
    list_resp = await client.get(
        owner.g(f"/files/{native_id}/versions"), headers=owner.headers
    )
    assert list_resp.status_code == 400
    assert list_resp.json()["detail"] == "FILE_NOT_AN_UPLOADED_FILE"


async def test_upload_version_program_refused(client: AsyncClient, acting_user) -> None:
    """A program is refused with a coded error."""
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    doc = await _upload_initial_file_doc(client, owner, initiative=owner.initiative)

    resp = await client.post(
        owner.g(f"/files/{doc['id']}/versions"),
        headers=owner.headers,
        files={
            "file": (
                "evil.exe",
                b"MZ\x90\x00\x03 not allowed",
                "application/x-msdownload",
            )
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "FILE_TYPE_NOT_ALLOWED"


async def test_list_versions_read_user_allowed_and_ordered(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """Read users can list versions; newest first with is_current on the highest."""
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    reader = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )

    doc = await _upload_initial_file_doc(client, owner, initiative=owner.initiative)
    await _share(session, doc, reader, ResourceAccessLevel.read)

    # Owner uploads v2.
    await client.post(
        owner.g(f"/files/{doc['id']}/versions"),
        headers=owner.headers,
        files={"file": ("v2.pdf", PDF_BYTES_V2, "application/pdf")},
    )

    resp = await client.get(
        owner.g(f"/files/{doc['id']}/versions"), headers=reader.headers
    )
    assert resp.status_code == 200
    versions = resp.json()
    assert [v["version_number"] for v in versions] == [2, 1]
    assert versions[0]["is_current"] is True
    assert versions[1]["is_current"] is False


async def test_download_specific_version_returns_its_bytes(
    client: AsyncClient, acting_user
) -> None:
    """Downloading an old version returns that version's bytes, not the current one."""
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    doc = await _upload_initial_file_doc(client, owner, initiative=owner.initiative)

    await client.post(
        owner.g(f"/files/{doc['id']}/versions"),
        headers=owner.headers,
        files={"file": ("v2.pdf", PDF_BYTES_V2, "application/pdf")},
    )

    versions = (
        await client.get(
            owner.g(f"/files/{doc['id']}/versions"),
            headers=owner.headers,
        )
    ).json()
    v1 = next(v for v in versions if v["version_number"] == 1)
    v2 = next(v for v in versions if v["version_number"] == 2)

    r1 = await client.get(
        owner.g(f"/files/{doc['id']}/versions/{v1['id']}/download"),
        headers=owner.headers,
    )
    r2 = await client.get(
        owner.g(f"/files/{doc['id']}/versions/{v2['id']}/download"),
        headers=owner.headers,
    )
    assert r1.status_code == 200 and r1.content == PDF_BYTES
    assert r2.status_code == 200 and r2.content == PDF_BYTES_V2


async def test_download_version_unknown_returns_404(
    client: AsyncClient, acting_user
) -> None:
    """A version id that doesn't belong to the file 404s."""
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    doc = await _upload_initial_file_doc(client, owner, initiative=owner.initiative)

    resp = await client.get(
        owner.g(f"/files/{doc['id']}/versions/99999/download"),
        headers=owner.headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "VERSION_NOT_FOUND"


async def test_download_version_cross_guild_forbidden(
    client: AsyncClient, acting_user
) -> None:
    """A user from another guild cannot download a version."""
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    doc = await _upload_initial_file_doc(client, owner, initiative=owner.initiative)
    versions = (
        await client.get(
            owner.g(f"/files/{doc['id']}/versions"),
            headers=owner.headers,
        )
    ).json()
    v1 = versions[0]

    outsider = await acting_user("member")
    resp = await client.get(
        owner.g(f"/files/{doc['id']}/versions/{v1['id']}/download"),
        headers=outsider.headers,
    )
    assert resp.status_code == 404


async def test_delete_non_current_version_owner(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """Owner deletes an old version; current stays, blob + Upload row removed."""
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    doc = await _upload_initial_file_doc(client, owner, initiative=owner.initiative)
    await client.post(
        owner.g(f"/files/{doc['id']}/versions"),
        headers=owner.headers,
        files={"file": ("v2.pdf", PDF_BYTES_V2, "application/pdf")},
    )
    versions = (
        await client.get(
            owner.g(f"/files/{doc['id']}/versions"),
            headers=owner.headers,
        )
    ).json()
    v1 = next(v for v in versions if v["version_number"] == 1)

    # Resolve v1's blob filename before deletion.
    v1_row = (
        await session.exec(select(FileVersion).where(FileVersion.id == v1["id"]))
    ).one()
    v1_filename = v1_row.file_url.split("/")[-1]
    storage = get_guild_storage(owner.guild.id)
    assert storage.exists(v1_filename)

    resp = await client.delete(
        owner.g(f"/files/{doc['id']}/versions/{v1['id']}"),
        headers=owner.headers,
    )
    assert resp.status_code == 204

    remaining = (
        await session.exec(select(FileVersion).where(FileVersion.file_id == doc["id"]))
    ).all()
    assert [v.version_number for v in remaining] == [2]
    # Upload row + blob for v1 are gone.
    assert (
        await session.exec(select(Upload).where(Upload.filename == v1_filename))
    ).one_or_none() is None
    assert not storage.exists(v1_filename)

    # The file still points at v2.
    session.expire_all()
    refreshed = await session.get(File, doc["id"])
    assert refreshed.current_version.version_number == 2


async def test_delete_current_version_promotes_previous(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """Deleting the current version rolls the file back to the prior version."""
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    doc = await _upload_initial_file_doc(client, owner, initiative=owner.initiative)
    v2_resp = await client.post(
        owner.g(f"/files/{doc['id']}/versions"),
        headers=owner.headers,
        files={"file": ("v2.pdf", PDF_BYTES_V2, "application/pdf")},
    )
    v2_id = v2_resp.json()["id"]

    resp = await client.delete(
        owner.g(f"/files/{doc['id']}/versions/{v2_id}"),
        headers=owner.headers,
    )
    assert resp.status_code == 204

    # The file points back at v1. Capture the versions URL first —
    # expire_all() below expires owner.guild, and building owner.g(...) afterwards
    # would trigger a sync lazy-load of guild.id (greenlet error).
    versions_url = owner.g(f"/files/{doc['id']}/versions")
    session.expire_all()
    refreshed = await session.get(File, doc["id"])
    assert refreshed.current_version.version_number == 1
    assert refreshed.current_version.original_filename == "v1.pdf"

    versions = (await client.get(versions_url, headers=owner.headers)).json()
    assert [v["version_number"] for v in versions] == [1]
    assert versions[0]["is_current"] is True


async def test_delete_last_version_blocked(client: AsyncClient, acting_user) -> None:
    """The only remaining version can't be deleted."""
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    doc = await _upload_initial_file_doc(client, owner, initiative=owner.initiative)
    versions = (
        await client.get(
            owner.g(f"/files/{doc['id']}/versions"),
            headers=owner.headers,
        )
    ).json()
    v1_id = versions[0]["id"]

    resp = await client.delete(
        owner.g(f"/files/{doc['id']}/versions/{v1_id}"),
        headers=owner.headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "CANNOT_DELETE_LAST_VERSION"


async def test_delete_version_non_owner_forbidden(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """A write (non-owner) user cannot delete versions."""
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    writer = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )

    doc = await _upload_initial_file_doc(client, owner, initiative=owner.initiative)
    await _share(session, doc, writer, ResourceAccessLevel.write)
    await client.post(
        owner.g(f"/files/{doc['id']}/versions"),
        headers=owner.headers,
        files={"file": ("v2.pdf", PDF_BYTES_V2, "application/pdf")},
    )
    versions = (
        await client.get(
            owner.g(f"/files/{doc['id']}/versions"),
            headers=owner.headers,
        )
    ).json()
    v1_id = next(v for v in versions if v["version_number"] == 1)["id"]

    resp = await client.delete(
        writer.g(f"/files/{doc['id']}/versions/{v1_id}"),
        headers=writer.headers,
    )
    assert resp.status_code == 403


async def test_delete_version_non_uploaded_file_rejected(
    client: AsyncClient, acting_user
) -> None:
    """Delete is rejected on non-uploaded files with the same code as upload/list."""
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    create = await client.post(
        owner.g("/files/"),
        headers=owner.headers,
        json={"name": "Native doc", "initiative_id": owner.initiative.id},
    )
    assert create.status_code == 201
    native_id = create.json()["id"]

    # Any version_id will do — the type check fires before the version lookup.
    resp = await client.delete(
        owner.g(f"/files/{native_id}/versions/9999"),
        headers=owner.headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "FILE_NOT_AN_UPLOADED_FILE"


# ---------------------------------------------------------------------------
# Bounded upload reads: over-limit bodies are rejected with 413 before
# the whole payload is buffered into memory. The size cap is shrunk via
# monkeypatch so the test payloads stay tiny.
# ---------------------------------------------------------------------------

# A small PDF that comfortably fits under the shrunk cap below.
_TINY_PDF = b"%PDF-1.4 tiny body for size tests"


async def test_upload_file_over_limit_rejected(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /files/upload rejects a body over the cap with 413."""
    cap = 1024
    monkeypatch.setattr(attachments_service, "MAX_FILE_SIZE", cap)

    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)

    oversized = b"%PDF-1.4 " + b"A" * (cap + 1)
    resp = await client.post(
        owner.g("/files/upload"),
        headers=owner.headers,
        data={"name": "Too big", "initiative_id": str(owner.initiative.id)},
        files={"file": ("big.pdf", oversized, "application/pdf")},
    )

    assert resp.status_code == 413
    assert resp.json()["detail"] == "FILE_TOO_LARGE"

    # Nothing was persisted.
    docs = (
        await session.exec(
            select(File).where(File.initiative_id == owner.initiative.id)
        )
    ).all()
    assert all(d.name != "Too big" for d in docs)


async def test_upload_file_just_under_limit_succeeds(
    client: AsyncClient,
    acting_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /files/upload accepts a body at/under the cap."""
    cap = 4096
    monkeypatch.setattr(attachments_service, "MAX_FILE_SIZE", cap)

    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)

    under = _TINY_PDF + b" " + b"B" * (cap - len(_TINY_PDF) - 1)
    assert len(under) == cap
    resp = await client.post(
        owner.g("/files/upload"),
        headers=owner.headers,
        data={"name": "Under cap", "initiative_id": str(owner.initiative.id)},
        files={"file": ("under.pdf", under, "application/pdf")},
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["file_size"] == cap


async def test_upload_file_version_over_limit_rejected(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /files/{id}/versions rejects a body over the cap with 413."""
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    # Seed v1 while the cap is still large so the file exists.
    doc = await _upload_initial_file_doc(client, owner, initiative=owner.initiative)

    cap = 1024
    monkeypatch.setattr(attachments_service, "MAX_FILE_SIZE", cap)

    oversized = b"%PDF-1.4 " + b"A" * (cap + 1)
    resp = await client.post(
        owner.g(f"/files/{doc['id']}/versions"),
        headers=owner.headers,
        files={"file": ("big.pdf", oversized, "application/pdf")},
    )

    assert resp.status_code == 413
    assert resp.json()["detail"] == "FILE_TOO_LARGE"

    # Only the original v1 exists; the oversized upload created no version.
    versions = (
        await session.exec(select(FileVersion).where(FileVersion.file_id == doc["id"]))
    ).all()
    assert {v.version_number for v in versions} == {1}


async def test_upload_file_version_just_under_limit_succeeds(
    client: AsyncClient,
    acting_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /files/{id}/versions accepts a body at/under the cap."""
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    doc = await _upload_initial_file_doc(client, owner, initiative=owner.initiative)

    cap = 4096
    monkeypatch.setattr(attachments_service, "MAX_FILE_SIZE", cap)

    under = _TINY_PDF + b" " + b"B" * (cap - len(_TINY_PDF) - 1)
    assert len(under) == cap
    resp = await client.post(
        owner.g(f"/files/{doc['id']}/versions"),
        headers=owner.headers,
        files={"file": ("v2.pdf", under, "application/pdf")},
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["version_number"] == 2
    assert body["file_size"] == cap


#: A real 1x1 PNG — the header reader walks IHDR, so a stub signature is not
#: enough to be identified as one.
_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
    b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00"
    b"\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.mark.parametrize("uploader_role", ["guild_admin", "initiative_manager"])
@pytest.mark.parametrize(
    ("filename", "content", "content_type"),
    [
        pytest.param("floor-plan.png", _TINY_PNG, "image/png", id="image"),
        pytest.param("floor-plan.pdf", _TINY_PDF, "application/pdf", id="pdf"),
    ],
)
async def test_upload_file_as_any_author(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    uploader_role: str,
    filename: str,
    content: bytes,
    content_type: str,
) -> None:
    """Anybody who may make files can upload one, not only a guild admin.

    Everything the upload writes after the files row — its version — is
    the owner's to write, and the uploader is
    the owner only once their grant exists. A guild admin passes regardless,
    which is how the order went unnoticed. A picture features no image.
    """
    if uploader_role == "guild_admin":
        uploader = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    else:
        uploader = await acting_user(guild_role=CommunityRole.member, initiative=True)

    resp = await client.post(
        uploader.g("/files/upload"),
        headers=uploader.headers,
        data={"name": "Floor plan", "initiative_id": str(uploader.initiative.id)},
        files={"file": (filename, content, content_type)},
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["file_content_type"] == content_type
    assert body["featured_image_url"] is None

    versions = (
        await session.exec(select(FileVersion).where(FileVersion.file_id == body["id"]))
    ).all()
    assert [v.version_number for v in versions] == [1]


_MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 64


def _frame(size: tuple[int, int] = (320, 180)) -> bytes:
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", size, (20, 20, 20)).save(out, format="PNG")
    return out.getvalue()


async def _video_version(client: AsyncClient, session: AsyncSession, owner):
    doc = await _upload_initial_file_doc(
        client,
        owner,
        initiative=owner.initiative,
        content=_MP4,
        filename="clip.mp4",
        content_type="video/mp4",
    )
    assert doc["kind"] == "video", doc
    version = (
        await session.exec(select(FileVersion).where(FileVersion.file_id == doc["id"]))
    ).one()
    return doc, version.id


async def _put_frame(client, actor, doc, version_id, frame):
    return await client.put(
        actor.g(f"/files/{doc['id']}/versions/{version_id}/thumbnail"),
        headers=actor.headers,
        files={"file": ("frame.png", frame, "image/png")},
    )


async def test_a_video_takes_one_frame_as_its_thumbnail(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """Drawn again on the server, so even a small frame is stored as a WebP of
    its own; a second frame is refused."""
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    doc, version_id = await _video_version(client, session, owner)

    resp = await _put_frame(client, owner, doc, version_id, _frame())
    assert resp.status_code == 204, resp.text

    listed = await client.get(owner.g(f"/files/{doc['id']}"), headers=owner.headers)
    thumbnail = listed.json()["thumbnail_url"]
    name = thumbnail.rsplit("/", 1)[-1]
    assert name.startswith(attachments_service.THUMBNAIL_PREFIX)
    assert name.endswith(".webp")
    again = await _put_frame(client, owner, doc, version_id, _frame())
    assert again.status_code == 409
    assert again.json()["detail"] == "FILE_THUMBNAIL_NOT_WANTED"


async def test_only_a_video_takes_a_frame(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    doc = await _upload_initial_file_doc(client, owner, initiative=owner.initiative)
    version = (
        await session.exec(select(FileVersion).where(FileVersion.file_id == doc["id"]))
    ).one()

    resp = await _put_frame(client, owner, doc, version.id, _frame())
    assert resp.status_code == 409
    assert resp.json()["detail"] == "FILE_THUMBNAIL_NOT_WANTED"


async def test_a_frame_that_is_not_a_picture_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    doc, version_id = await _video_version(client, session, owner)

    resp = await _put_frame(client, owner, doc, version_id, b"<svg/>" * 10)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "FILE_INVALID_FILE"


async def test_a_reader_cannot_give_a_video_its_thumbnail(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    reader = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    doc, version_id = await _video_version(client, session, owner)
    await _share(session, doc, reader, ResourceAccessLevel.read)

    resp = await _put_frame(client, reader, doc, version_id, _frame())
    assert resp.status_code == 403
