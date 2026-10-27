"""Resumable uploads over tus, through the real routes."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlmodel import select

from app.models.platform.guild import CommunityRole
from app.models.tenant.pending_upload import PendingUpload
from app.services import resumable
from app.services.storage import get_guild_storage
from app.services.tenant import attachments
from app.testing import route_session_to_guild

TUS = {"Tus-Resumable": "1.0.0"}


@pytest.fixture(autouse=True)
def small_parts(monkeypatch):
    """Parts of four bytes, so a short file takes several."""
    monkeypatch.setattr(resumable, "PART_BYTES", 4)


def _metadata(**values: str) -> str:
    return ",".join(
        f"{key} {base64.b64encode(value.encode()).decode()}"
        for key, value in values.items()
    )


async def _create(client: AsyncClient, actor, length: int, **metadata: str):
    values = {"purpose": "file", "filename": "cut.mp4", **metadata}
    if "initiative_id" not in values:
        values["initiative_id"] = str(actor.initiative.id)
    return await client.post(
        actor.g("/resumable-uploads"),
        headers={
            **actor.headers,
            **TUS,
            "Upload-Length": str(length),
            "Upload-Metadata": _metadata(**values),
        },
    )


async def _append(client: AsyncClient, actor, location: str, offset: int, body: bytes):
    return await client.patch(
        location,
        headers={
            **actor.headers,
            **TUS,
            "Upload-Offset": str(offset),
            "Content-Type": "application/offset+octet-stream",
        },
        content=body,
    )


def _path(location: str) -> str:
    return location[location.index("/api/") :]


async def test_a_file_arrives_in_pieces_and_resumes_where_it_stopped(
    client: AsyncClient, acting_user, session
):
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    body = b"0123456789abcdef!"
    created = await _create(client, owner, len(body))
    assert created.status_code == 201, created.text
    location = _path(created.headers["location"])

    first = await _append(client, owner, location, 0, body[:10])
    assert first.status_code == 204, first.text
    assert first.headers["upload-offset"] == "10"
    # Out of step: the offset the client names must be the server's.
    stale = await _append(client, owner, location, 3, body[10:])
    assert stale.status_code == 409
    where = await client.head(location, headers={**owner.headers, **TUS})
    assert where.headers["upload-offset"] == "10"
    rest = await _append(client, owner, location, 10, body[10:])
    assert rest.headers["upload-offset"] == str(len(body))

    await route_session_to_guild(session, owner.guild.id)
    upload = (await session.exec(select(PendingUpload))).one()
    assert upload.completed_at is not None
    staged = get_guild_storage(owner.guild.id).open_readable(upload.staging_key)
    assert staged.path.read_bytes() == body


async def test_an_arriving_file_holds_its_room_and_cancelling_frees_it(
    client: AsyncClient, acting_user
):
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    before = await attachments.get_guild_storage_usage(owner.guild.id)
    created = await _create(client, owner, 1000)
    location = _path(created.headers["location"])
    assert await attachments.get_guild_storage_usage(owner.guild.id) == before + 1000

    cancelled = await client.delete(location, headers={**owner.headers, **TUS})

    assert cancelled.status_code == 204
    assert await attachments.get_guild_storage_usage(owner.guild.id) == before
    gone = await client.head(location, headers={**owner.headers, **TUS})
    assert gone.status_code == 404


@pytest.mark.parametrize(
    ("metadata", "status", "detail"),
    [
        ({"filename": "setup.exe"}, 400, "FILE_TYPE_NOT_ALLOWED"),
        ({"purpose": "nothing"}, 400, "RESUMABLE_INVALID_REQUEST"),
    ],
    ids=["program", "no-such-purpose"],
)
async def test_an_upload_is_refused_before_anything_is_stored(
    client: AsyncClient, acting_user, metadata, status, detail
):
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)

    refused = await _create(client, owner, 10, **metadata)

    assert refused.status_code == status
    assert refused.json()["detail"] == detail


async def test_only_somebody_who_may_add_a_file_may_upload_one(
    client: AsyncClient, acting_user
):
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    outsider = await acting_user(guild_role=CommunityRole.member, guild=owner.guild)

    refused = await _create(
        client, outsider, 10, initiative_id=str(owner.initiative.id)
    )

    assert refused.status_code in (403, 404)


async def test_an_expired_upload_is_thrown_away(
    client: AsyncClient, acting_user, session
):
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    created = await _create(client, owner, 8)
    await _append(client, owner, _path(created.headers["location"]), 0, b"abc")
    await route_session_to_guild(session, owner.guild.id)
    upload = (await session.exec(select(PendingUpload))).one()
    key = upload.staging_key
    upload.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    session.add(upload)
    await session.commit()

    await resumable.expire(session, owner.guild.id)

    assert (await session.exec(select(PendingUpload))).first() is None
    assert get_guild_storage(owner.guild.id).open_readable(key) is None


async def test_bytes_past_the_length_are_refused_though_no_length_was_declared(
    client: AsyncClient, acting_user
):
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    created = await _create(client, owner, 4)

    async def body():
        yield b"abcdefgh"

    refused = await _append(
        client, owner, _path(created.headers["location"]), 0, body()
    )

    assert refused.status_code == 400
    assert refused.json()["detail"] == "RESUMABLE_PAST_LENGTH"


async def test_a_size_past_what_can_be_kept_is_refused(
    client: AsyncClient, acting_user
):
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)

    refused = await _create(client, owner, 2**63)

    assert refused.status_code == 400
    assert refused.json()["detail"] == "RESUMABLE_INVALID_REQUEST"


async def test_an_upload_held_by_one_request_refuses_another(
    client: AsyncClient, acting_user, session
):
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    created = await _create(client, owner, 8)
    await route_session_to_guild(session, owner.guild.id)
    upload = (await session.exec(select(PendingUpload))).one()
    upload.lease_token = "another"
    upload.lease_until = datetime.now(timezone.utc) + timedelta(minutes=1)
    session.add(upload)
    await session.commit()

    refused = await _append(client, owner, _path(created.headers["location"]), 0, b"ab")

    assert refused.status_code == 423


async def test_an_upload_left_finishing_is_finished_when_asked_where_it_stands(
    client: AsyncClient, acting_user, session
):
    """A request whose record of completion did not land leaves it finishing."""
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    created = await _create(client, owner, 4)
    location = _path(created.headers["location"])
    await _append(client, owner, location, 0, b"abcd")
    await route_session_to_guild(session, owner.guild.id)
    upload = (await session.exec(select(PendingUpload))).one()
    upload.completed_at = None
    upload.blob_state = {**upload.blob_state, "finishing": True}
    session.add(upload)
    await session.commit()

    where = await client.head(location, headers={**owner.headers, **TUS})

    assert where.headers["upload-offset"] == "4"
    session.expunge_all()
    await route_session_to_guild(session, owner.guild.id)
    assert (await session.exec(select(PendingUpload))).one().completed_at is not None


async def test_a_held_upload_leaves_no_transaction_open_while_bytes_arrive(
    client: AsyncClient, acting_user, session
):
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    created = await _create(client, owner, 8)
    await route_session_to_guild(session, owner.guild.id)
    upload_id = _path(created.headers["location"]).rsplit("/", 1)[1]
    lease = resumable._Lease(session, upload_id, resumable._nothing)

    upload = await lease.take()

    assert upload.offset == 0
    assert not session.in_transaction()
    await lease.let_go()
