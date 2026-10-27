"""Convert to edit, through the real routes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel import select

from app.models.platform.guild import CommunityRole
from app.models.tenant.file import FileVersion
from app.models.tenant.upload import Upload
from app.services.tenant import attachments, file_conversion
from app.testing import route_session_to_guild


async def _upload(client: AsyncClient, actor, filename: str, body: bytes) -> dict:
    uploaded = await client.post(
        actor.g("/files/upload"),
        headers=actor.headers,
        data={"name": "Budget", "initiative_id": str(actor.initiative.id)},
        files={"file": (filename, body, "application/octet-stream")},
    )
    assert uploaded.status_code == 201, uploaded.text
    return uploaded.json()


async def _convert(client: AsyncClient, actor, file_id: int):
    return await client.post(
        actor.g(f"/files/{file_id}/convert"), headers=actor.headers
    )


async def test_a_csv_becomes_a_spreadsheet_and_lets_its_upload_go(
    client: AsyncClient, acting_user, session
):
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    uploaded = await _upload(client, owner, "budget.csv", b"Item,Cost\nTea,3\n")
    assert uploaded["converts_to"] == "sheet"

    converted = await _convert(client, owner, uploaded["id"])

    assert converted.status_code == 200, converted.text
    body = converted.json()
    assert (body["id"], body["name"]) == (uploaded["id"], "Budget")
    assert (body["file_type"], body["kind"], body["converts_to"]) == (
        "sheet",
        "spreadsheet",
        None,
    )
    (sheet,) = body["content"]["sheets"]
    assert sheet["cells"]["1:1"] == 3
    assert body["file_url"] is None
    await route_session_to_guild(session, owner.guild.id)
    assert (await session.exec(select(FileVersion))).first() is None
    assert (await session.exec(select(Upload))).first() is None
    assert await attachments.get_guild_storage_usage(owner.guild.id) == 0


@pytest.mark.parametrize(
    ("filename", "body", "first"),
    [
        ("notes.md", b"# Minutes\n\nTea was **late**.\n", "heading"),
        ("notes.txt", b"# not a heading\nsecond line\n", "paragraph"),
    ],
    ids=["markdown", "plain-text"],
)
async def test_text_becomes_a_document(
    client: AsyncClient, acting_user, filename, body, first
):
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    uploaded = await _upload(client, owner, filename, body)

    converted = await _convert(client, owner, uploaded["id"])

    assert converted.status_code == 200, converted.text
    document = converted.json()
    assert document["file_type"] == "lexical"
    assert document["content"]["root"]["children"][0]["type"] == first


async def test_a_file_that_converts_to_nothing_is_refused(
    client: AsyncClient, acting_user
):
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    uploaded = await _upload(client, owner, "report.pdf", b"%PDF-1.4 a report")
    assert uploaded["converts_to"] is None

    refused = await _convert(client, owner, uploaded["id"])

    assert refused.status_code == 400
    assert refused.json()["detail"] == "FILE_NOT_CONVERTIBLE"


async def test_a_file_too_large_to_convert_stays_as_it_was(
    client: AsyncClient, acting_user, monkeypatch
):
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    uploaded = await _upload(client, owner, "budget.csv", b"Item,Cost\nTea,3\n")
    monkeypatch.setattr(file_conversion, "MAX_CONVERT_BYTES", 4)

    refused = await _convert(client, owner, uploaded["id"])

    assert refused.status_code == 413
    assert refused.json()["detail"] == "FILE_TOO_LARGE_TO_CONVERT"
    kept = await client.get(owner.g(f"/files/{uploaded['id']}"), headers=owner.headers)
    assert kept.json()["file_type"] == "csv"


async def test_only_somebody_who_may_edit_the_file_converts_it(
    client: AsyncClient, acting_user
):
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    reader = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    uploaded = await _upload(client, owner, "budget.csv", b"Item,Cost\nTea,3\n")

    refused = await _convert(client, reader, uploaded["id"])

    assert refused.status_code in (403, 404)
