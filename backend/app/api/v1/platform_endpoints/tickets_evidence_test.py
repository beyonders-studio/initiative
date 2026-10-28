"""Files attached to tickets and reports: sealed where they land, opened only
through their own row, carried sealed when a report is escalated, and gone
once their case has been closed long enough."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError
from sqlmodel import select

from app.core import blob_crypto
from app.core.messages import EvidenceMessages
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.models.platform.guild import CommunityRole
from app.models.tenant.comment import Comment, CommentAudience
from app.core.intake import IntakeStream, meta
from app.models.tenant.evidence import Evidence
from app.models.tenant.task import Task
from app.models.tenant.intake import IntakeCase
from app.services import storage as storage_service
from app.services.platform import evidence as evidence_service
from app.services.platform.evidence_test import picture
from app.api.v1.platform_endpoints import tickets_following_test as following
from app.api.v1.platform_endpoints.tickets_following_test import TICKETS, _file
from app.api.v1.platform_endpoints.tickets_test import _set_support
from app.api.v1.tenant_endpoints import moderation_test as moderation

# The neighbouring suites' fixtures, by name.
desk = following.desk
scene = moderation.scene
operations = moderation.operations


def _jpeg(name: str = "photo.jpg", *, located: bool = False):
    return ("files", (name, picture(located=located), "image/jpeg"))


async def _ask(client, actor, community_id: int, files):
    return await client.post(
        TICKETS,
        data={
            "payload": json.dumps(
                {
                    "stream": "support",
                    "community_id": community_id,
                    "subject": "Lost my phone",
                    "body": "Here is the screen.",
                }
            )
        },
        files=files,
        headers=actor.headers,
    )


async def _evidence(session, guild_id: int) -> list[Evidence]:
    await set_rls_context(session, SystemGuild(guild_id))
    rows = (await session.exec(select(Evidence).order_by(Evidence.id))).all()
    # Ids restart in every community: keep one community's rows from standing
    # in for another's in the identity map.
    session.expunge_all()
    await set_rls_context(session, Unattributed())
    return list(rows)


@pytest.fixture
async def asker(session, acting_user, desk):
    """A member of a community whose members may ask for help."""
    member = await acting_user(guild_role=CommunityRole.member)
    await _set_support(session, member.guild.id, True)
    return member


# -- Filing -------------------------------------------------------------------


async def test_a_filing_stores_its_files_sealed_beside_the_opening_words(
    client,
    session,
    desk,
    asker,
):
    response = await _ask(client, asker, asker.guild.id, [_jpeg(located=True)])
    assert response.status_code == 202, response.text

    (row,) = await _evidence(session, desk["guild_id"])
    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    case = (await session.exec(select(IntakeCase))).one()
    opening = (
        await session.exec(
            select(Comment).where(Comment.audience == CommentAudience.filer)
        )
    ).one()
    await set_rls_context(session, Unattributed())
    assert row.case_id == case.id
    assert row.comment_id == opening.id
    assert row.created_by == asker.user.id
    assert row.content_type == "image/jpeg"
    assert row.display_name == "photo.jpg"

    stored = storage_service.get_guild_storage(desk["guild_id"]).open_readable(
        row.storage_key
    )
    sealed = stored.path.read_bytes()
    assert sealed.startswith(b"IEV1")
    assert b"JFIF" not in sealed


async def _opened(session, guild_id: int, row: Evidence) -> bytes:
    await set_rls_context(session, SystemGuild(guild_id))
    obj = await evidence_service.sealed(session, row.id)
    await set_rls_context(session, Unattributed())
    assert obj is not None
    return b"".join(evidence_service.plaintext(guild_id, obj))


async def test_with_storage_encrypted_evidence_goes_with_the_community_key(
    client, session, desk, asker
):
    from app.db import session as db_session
    from app.services import storage_keys
    from app.services.storage_keys import DatabaseKeyStore, Keyring, LocalRoot

    storage_keys.use_keyring(Keyring(DatabaseKeyStore(), LocalRoot()))
    try:
        response = await _ask(client, asker, asker.guild.id, [_jpeg()])
        assert response.status_code == 202, response.text
        (row,) = await _evidence(session, desk["guild_id"])
        assert row.kek_version == blob_crypto.COMMUNITY_KEK_VERSION
        assert (await _opened(session, desk["guild_id"], row)).startswith(b"\xff\xd8")

        async with db_session.SystemSessionLocal() as system:
            await storage_keys.destroy(system, desk["guild_id"])
            await system.commit()
        with pytest.raises(blob_crypto.BlobCryptoError):
            await _opened(session, desk["guild_id"], row)
    finally:
        storage_keys.use_keyring(None)


async def test_evidence_sealed_before_encryption_moves_onto_the_community_key(
    client, session, desk, asker
):
    from app.services import storage_keys
    from app.services.storage_keys import DatabaseKeyStore, Keyring, LocalRoot

    response = await _ask(client, asker, asker.guild.id, [_jpeg()])
    assert response.status_code == 202, response.text
    (row,) = await _evidence(session, desk["guild_id"])
    assert row.kek_version == blob_crypto.KEK_VERSION

    storage_keys.use_keyring(Keyring(DatabaseKeyStore(), LocalRoot()))
    try:
        await set_rls_context(session, SystemGuild(desk["guild_id"]))
        assert (
            await evidence_service.adopt_community_key(session, desk["guild_id"]) == 1
        )
        await session.commit()
        await set_rls_context(session, Unattributed())
        (moved,) = await _evidence(session, desk["guild_id"])
        assert moved.kek_version == blob_crypto.COMMUNITY_KEK_VERSION
        assert (await _opened(session, desk["guild_id"], moved)).startswith(b"\xff\xd8")
    finally:
        storage_keys.use_keyring(None)


async def test_a_file_the_stream_does_not_take_files_nothing(
    client,
    session,
    desk,
    asker,
):
    response = await _ask(
        client,
        asker,
        asker.guild.id,
        [("files", ("photo.png", b"PK\x03\x04" + b"\x00" * 60, "image/png"))],
    )
    assert response.status_code == 400
    assert response.json()["detail"] == EvidenceMessages.TYPE_NOT_ALLOWED
    assert await _evidence(session, desk["guild_id"]) == []
    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    assert (await session.exec(select(IntakeCase))).all() == []


async def test_more_files_than_the_stream_takes_are_refused(
    client,
    desk,
    asker,
):
    response = await _ask(
        client, asker, asker.guild.id, [_jpeg(f"{n}.jpg") for n in range(6)]
    )
    assert response.status_code == 400
    assert response.json()["detail"] == EvidenceMessages.TOO_MANY


# -- Reading it back ----------------------------------------------------------


async def test_the_filer_opens_their_own_file_and_nobody_else_can_there(
    client,
    session,
    acting_user,
    desk,
    asker,
):
    assert (
        await _ask(client, asker, asker.guild.id, [_jpeg(located=True)])
    ).status_code == 202
    (row,) = await _evidence(session, desk["guild_id"])
    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    case = (await session.exec(select(IntakeCase))).one()
    await set_rls_context(session, Unattributed())

    detail = (
        await client.get(f"{TICKETS}/{case.task_id}", headers=asker.headers)
    ).json()
    (attachment,) = detail["messages"][0]["attachments"]
    assert attachment["id"] == row.id

    url = f"{TICKETS}/{case.task_id}/evidence/{row.id}"
    response = await client.get(url, headers=asker.headers)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-type"] == "image/jpeg"
    assert len(response.content) == row.size_bytes

    stranger = await acting_user("member")
    response = await client.get(url, headers=stranger.headers)
    assert response.status_code == 404
    assert response.json()["detail"] == EvidenceMessages.NOT_FOUND


async def test_the_team_opens_a_case_file_and_others_in_the_community_cannot(
    client,
    session,
    acting_user,
    desk,
    asker,
):
    assert (await _ask(client, asker, asker.guild.id, [_jpeg()])).status_code == 202
    (row,) = await _evidence(session, desk["guild_id"])
    staff = desk["staff"]

    response = await client.get(staff.g(f"/evidence/{row.id}"), headers=staff.headers)
    assert response.status_code == 200
    assert response.content.startswith(b"\xff\xd8")

    # In the community, but not in the initiative the case is worked in.
    outsider = await acting_user(guild_role=CommunityRole.member, guild=staff.guild)
    response = await client.get(
        outsider.g(f"/evidence/{row.id}"), headers=outsider.headers
    )
    assert response.status_code == 404


async def test_an_answer_carries_its_files(
    client,
    session,
    acting_user,
    desk,
):
    filer = await acting_user("member")
    task_id = await _file(filer.user)

    response = await client.post(
        f"{TICKETS}/{task_id}/replies",
        data={"body": "The screen again."},
        files=[_jpeg("again.jpg")],
        headers=filer.headers,
    )
    assert response.status_code == 201, response.text
    answer = response.json()["messages"][-1]
    assert [a["display_name"] for a in answer["attachments"]] == ["again.jpg"]

    staff = desk["staff"]
    case = (
        await client.get(staff.g(f"/tasks/{task_id}/case"), headers=staff.headers)
    ).json()
    (item,) = case["evidence"]
    assert item["from_requester"] is True
    assert item["comment_id"] == answer["id"]


async def test_an_answer_with_a_refused_file_is_not_taken(
    client,
    session,
    acting_user,
    desk,
):
    filer = await acting_user("member")
    task_id = await _file(filer.user)
    response = await client.post(
        f"{TICKETS}/{task_id}/replies",
        data={"body": "Look."},
        files=[("files", ("x.exe", b"MZ\x90\x00" + b"\x00" * 60, "image/png"))],
        headers=filer.headers,
    )
    assert response.status_code == 400
    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    said = (
        await session.exec(select(Comment.content).where(Comment.task_id == task_id))
    ).all()
    assert "Look." not in said


async def test_a_file_on_someone_elses_case_does_not_open_through_mine(
    client,
    session,
    acting_user,
    desk,
):
    filer = await acting_user("member")
    other = await acting_user("member")
    mine = await _file(filer.user)
    theirs = await _file(other.user, subject="Theirs")
    response = await client.post(
        f"{TICKETS}/{theirs}/replies",
        data={"body": "Mine."},
        files=[_jpeg()],
        headers=other.headers,
    )
    assert response.status_code == 201
    (row,) = await _evidence(session, desk["guild_id"])

    response = await client.get(
        f"{TICKETS}/{mine}/evidence/{row.id}", headers=filer.headers
    )
    assert response.status_code == 404


# -- Reports, and escalating one ----------------------------------------------


async def test_a_reports_files_are_read_by_its_moderators_and_carried_on_escalation(
    client,
    session,
    scene,
    operations,
):
    community = scene["guild"].id
    response = await client.post(
        "/api/v1/me/tickets",
        data={
            "payload": json.dumps(
                {
                    "stream": "moderation",
                    "target_type": "comment",
                    "target_id": scene["comment"].id,
                    "reason": "harassment",
                    "community_id": community,
                }
            )
        },
        files=[_jpeg("screenshot.jpg")],
        headers=scene["member"].headers,
    )
    assert response.status_code == 202, response.text
    (row,) = await _evidence(session, community)
    assert row.report_id is not None

    mod = scene["mod"]
    reports = (
        await client.get(
            f"/api/v1/c/{community}/initiatives/{scene['initiative'].id}/reports",
            headers=mod.headers,
        )
    ).json()
    assert [e["id"] for e in reports["items"][0]["evidence"]] == [row.id]
    opened = await client.get(mod.g(f"/evidence/{row.id}"), headers=mod.headers)
    assert opened.status_code == 200, opened.text
    original = opened.content

    settled = await client.post(
        f"/api/v1/c/{community}/reports/{row.report_id}/settle",
        json={"outcome": "escalated"},
        headers=mod.headers,
    )
    assert settled.status_code == 200, settled.text

    (carried,) = await _evidence(session, operations["guild"].id)
    # The same object, keyed for the operations community.
    assert carried.origin_id == row.origin_id
    assert carried.origin_guild_id == community
    assert carried.sha256 == row.sha256
    assert carried.wrapped_dek != row.wrapped_dek
    with pytest.raises(blob_crypto.BlobCryptoError):
        blob_crypto.unwrap(
            carried.wrapped_dek, holding_guild_id=community, origin_id=row.origin_id
        )
    copied = storage_service.get_guild_storage(operations["guild"].id).open_readable(
        carried.storage_key
    )
    kept = storage_service.get_guild_storage(community).open_readable(row.storage_key)
    # Copied as it was stored: never opened on the way.
    assert copied.path.read_bytes() == kept.path.read_bytes()

    await set_rls_context(session, SystemGuild(operations["guild"].id))
    obj = await evidence_service.sealed(session, carried.id)
    await set_rls_context(session, Unattributed())
    assert b"".join(evidence_service.plaintext(operations["guild"].id, obj)) == original


# -- Keeping and rotating -----------------------------------------------------


async def _with_file(client, acting_user) -> int:
    filer = await acting_user("member")
    task_id = await _file(filer.user)
    response = await client.post(
        f"{TICKETS}/{task_id}/replies",
        data={"body": "Here."},
        files=[_jpeg()],
        headers=filer.headers,
    )
    assert response.status_code == 201, response.text
    return task_id


async def _set_state(session, desk, task_id: int, *, done_days_ago: float | None):
    """Done since ``done_days_ago`` days, or open again for ``None``: the
    status and the completion time move together, as the task routes keep
    them."""
    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    task = (await session.exec(select(Task).where(Task.id == task_id))).one()
    if done_days_ago is None:
        task.task_status_id = desk["active"]
        task.completed_at = None
    else:
        task.task_status_id = desk["done"]
        task.completed_at = datetime.now(timezone.utc) - timedelta(days=done_days_ago)
    session.add(task)
    await session.commit()


async def _sweep(session, desk) -> int:
    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    return await evidence_service.purge_due(session, desk["guild_id"])


async def test_a_closed_cases_files_are_kept_for_the_stream_then_go(
    client, session, acting_user, desk
):
    task_id = await _with_file(client, acting_user)
    (row,) = await _evidence(session, desk["guild_id"])
    storage = storage_service.get_guild_storage(desk["guild_id"])

    # Support keeps them 90 days from the close.
    await _set_state(session, desk, task_id, done_days_ago=89)
    assert await _sweep(session, desk) == 0
    assert storage.exists(row.storage_key)

    await _set_state(session, desk, task_id, done_days_ago=91)
    assert await _sweep(session, desk) == 1
    assert await _evidence(session, desk["guild_id"]) == []
    assert not storage.exists(row.storage_key)


async def test_a_case_a_hold_names_keeps_its_files_until_the_hold_is_released(
    client, session, acting_user, desk
):
    from app.models.tenant.content_hold import ContentHold
    from app.services.platform.intake import claim_subject_guild
    from app.testing import create_guild

    task_id = await _with_file(client, acting_user)
    held_in = await create_guild(session)
    held_in_id = held_in.id
    # The case is about that community, and a hold there is worked on it.
    assert await claim_subject_guild(task_id, held_in_id) == "named"
    await set_rls_context(session, SystemGuild(held_in_id))
    hold = ContentHold(
        target_type="comment",
        target_id=1,
        case_task_id=task_id,
        placed_via="platform",
        reason="legal_request",
    )
    session.add(hold)
    await session.commit()
    hold_id = hold.id

    await _set_state(session, desk, task_id, done_days_ago=400)
    assert await _sweep(session, desk) == 0
    assert len(await _evidence(session, desk["guild_id"])) == 1

    await set_rls_context(session, SystemGuild(held_in_id))
    released = (
        await session.exec(select(ContentHold).where(ContentHold.id == hold_id))
    ).one()
    released.released_at = datetime.now(timezone.utc)
    released.release_outcome = "restore"
    session.add(released)
    await session.commit()
    assert await _sweep(session, desk) == 1


async def test_the_sweep_waits_while_a_hold_naming_the_case_is_placed(
    client, session, acting_user, desk
):
    """A hold placed on a long-closed case holds the case's task as the sweep
    locks it, so the sweep finishes first or finds the hold committed."""
    from sqlalchemy import text

    from app.services.platform.intake import case_locked

    task_id = await _with_file(client, acting_user)
    await _set_state(session, desk, task_id, done_days_ago=400)
    async with case_locked(task_id):
        await set_rls_context(session, SystemGuild(desk["guild_id"]))
        await session.exec(text("SET LOCAL lock_timeout = '200ms'"))
        with pytest.raises(DBAPIError):
            await evidence_service.purge_due(session, desk["guild_id"])
        await session.rollback()
    assert len(await _evidence(session, desk["guild_id"])) == 1
    assert await _sweep(session, desk) == 1


async def test_a_reopened_case_keeps_its_files(client, session, acting_user, desk):
    task_id = await _with_file(client, acting_user)
    await _set_state(session, desk, task_id, done_days_ago=200)
    await _set_state(session, desk, task_id, done_days_ago=None)
    assert await _sweep(session, desk) == 0
    assert len(await _evidence(session, desk["guild_id"])) == 1


async def test_a_case_closed_again_counts_from_the_new_close(
    client, session, acting_user, desk
):
    task_id = await _with_file(client, acting_user)
    await _set_state(session, desk, task_id, done_days_ago=200)
    # Reopened and closed again between two sweeps.
    await _set_state(session, desk, task_id, done_days_ago=None)
    await _set_state(session, desk, task_id, done_days_ago=1)
    assert await _sweep(session, desk) == 0
    assert len(await _evidence(session, desk["guild_id"])) == 1


async def test_a_long_trashed_cases_files_go(client, session, acting_user, desk):
    task_id = await _with_file(client, acting_user)
    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    task = (await session.exec(select(Task).where(Task.id == task_id))).one()
    task.deleted_at = datetime.now(timezone.utc) - timedelta(days=91)
    session.add(task)
    await session.commit()
    assert await _sweep(session, desk) == 1


async def test_purging_a_case_for_good_releases_its_files(
    client, session, acting_user, desk
):
    from app.services.tenant.attachments import delete_blobs
    from app.services.tenant.soft_delete import hard_purge_entity, soft_delete_entity
    from app.testing.schema_harness import route_session_to_guild

    task_id = await _with_file(client, acting_user)
    (row,) = await _evidence(session, desk["guild_id"])
    storage = storage_service.get_guild_storage(desk["guild_id"])

    await route_session_to_guild(session, desk["guild_id"])
    task = (await session.exec(select(Task).where(Task.id == task_id))).one()
    await soft_delete_entity(
        session, task, deleted_by_user_id=desk["staff"].user.id, retention_days=30
    )
    await session.commit()
    released = await hard_purge_entity(session, task)
    await session.commit()
    delete_blobs(desk["guild_id"], released)

    assert row.storage_key in released
    assert await _evidence(session, desk["guild_id"]) == []
    assert not storage.exists(row.storage_key)


async def test_an_object_another_row_still_names_is_not_released(
    client, session, acting_user, desk
):
    task_id = await _with_file(client, acting_user)
    other_task = await _with_file(client, acting_user)
    (row, other) = await _evidence(session, desk["guild_id"])
    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    # As a report's file carried into a case in the same community is.
    await session.exec(
        update(Evidence)
        .where(Evidence.id == other.id)
        .values(storage_key=row.storage_key)
    )
    await session.commit()
    released = await evidence_service.released_by_purge(session, task_ids=[task_id])
    assert released == set()
    released = await evidence_service.released_by_purge(
        session, task_ids=[task_id, other_task]
    )
    assert released == {row.storage_key}


# -- Writing fails part way ---------------------------------------------------


async def test_what_was_written_before_a_failed_write_is_removed(
    session, desk, monkeypatch
):
    gid = desk["guild_id"]
    storage = storage_service.get_guild_storage(gid)
    written: list[str] = []
    real = type(storage).write

    def flaky(self, key, data, **kwargs):
        written.append(key)
        if len(written) == 2:
            raise OSError("no space left")
        return real(self, key, data, **kwargs)

    monkeypatch.setattr(type(storage), "write", flaky)
    files = evidence_service.prepare(
        [
            evidence_service.IncomingFile("a.jpg", picture()),
            evidence_service.IncomingFile("b.jpg", picture()),
        ],
        meta(IntakeStream.support).evidence,
    )
    with pytest.raises(OSError):
        with evidence_service.Sealing(gid) as sealing:
            sealing.store(session, prepared=files, created_by=None, case_id=1)
    assert len(written) == 2
    assert not storage.exists(written[0])


async def test_what_was_written_for_rows_that_never_landed_is_removed(session, desk):
    gid = desk["guild_id"]
    storage = storage_service.get_guild_storage(gid)
    files = evidence_service.prepare(
        [evidence_service.IncomingFile("a.jpg", picture())],
        meta(IntakeStream.support).evidence,
    )
    await set_rls_context(session, SystemGuild(gid))
    with pytest.raises(DBAPIError):
        with evidence_service.Sealing(gid) as sealing:
            # No such case: the commit is refused.
            sealing.store(session, prepared=files, created_by=None, case_id=999_999)
            await session.commit()
            sealing.keep()
    await session.rollback()
    (key,) = sealing.written
    assert not storage.exists(key)


async def test_rotation_rewraps_the_keys_and_leaves_the_objects(
    client,
    session,
    desk,
    asker,
):
    from app.core.config import settings

    asked = await _ask(client, asker, asker.guild.id, [_jpeg()])
    assert asked.status_code == 202, asked.text
    (row,) = await _evidence(session, desk["guild_id"])
    storage = storage_service.get_guild_storage(desk["guild_id"])
    before = storage.open_readable(row.storage_key).path.read_bytes()

    new_key = "rotated-" + "z" * 40
    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    rotated = await evidence_service.rewrap_guild(
        session,
        desk["guild_id"],
        old_secret_key=settings.SECRET_KEY,
        new_secret_key=new_key,
    )
    await session.commit()
    assert rotated == (1, 0, 0)
    # Again: already under the new key.
    assert await evidence_service.rewrap_guild(
        session,
        desk["guild_id"],
        old_secret_key=settings.SECRET_KEY,
        new_secret_key=new_key,
        dry_run=True,
    ) == (0, 1, 0)

    (after,) = (await session.exec(select(Evidence))).all()
    assert storage.open_readable(row.storage_key).path.read_bytes() == before
    dek = blob_crypto.unwrap(
        after.wrapped_dek,
        holding_guild_id=desk["guild_id"],
        origin_id=after.origin_id,
        secret_key=new_key,
    )
    assert blob_crypto.decrypt(
        before, dek, origin_guild_id=after.origin_guild_id, origin_id=after.origin_id
    ).startswith(b"\xff\xd8")
