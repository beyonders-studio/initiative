"""Asking for something you can't open or edit, and answering, end to end."""

import pytest
from sqlmodel import select

from app.models.platform.guild import CommunityRole
from app.models.platform.notification import Notification, NotificationType
from app.services.platform import app_settings as app_settings_service
from app.testing import (
    create_collection,
    create_file,
    create_guest,
    create_project,
    create_resource_grant,
    create_task,
    get_auth_headers,
)
from app.testing.notices import drain_notices


async def _told(session, user_id: int, ntype: NotificationType) -> list[Notification]:
    await drain_notices()
    return list(
        (
            await session.exec(
                select(Notification).where(
                    Notification.user_id == user_id, Notification.type == ntype
                )
            )
        ).all()
    )


@pytest.fixture
async def two(acting_user):
    """An owner, and a member of the same initiative who can't open the
    owner's files."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    reader = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    return owner, reader


async def test_a_member_asks_for_a_file_and_the_owner_shares_it(client, session, two):
    owner, reader = two
    file = await create_file(session, owner.initiative, owner.user, name="Budget")
    file_id = file.id

    assert (
        await client.get(owner.g(f"/files/{file_id}"), headers=reader.headers)
    ).status_code in (403, 404)
    standing = await client.get(
        reader.g(f"/share-requests/standing?kind=file&entity_id={file_id}"),
        headers=reader.headers,
    )
    assert standing.json() == {
        "resource_type": "file",
        "resource_id": file_id,
        "initiative_id": owner.initiative.id,
        "level": None,
        "pending": None,
    }

    asked = await client.post(
        reader.g("/share-requests/"),
        json={"resource_type": "file", "resource_id": file_id, "message": "For May"},
        headers=reader.headers,
    )
    assert asked.status_code == 201 and asked.json()["count"] == 1
    again = await client.post(
        reader.g("/share-requests/"),
        json={"resource_type": "file", "resource_id": file_id},
        headers=reader.headers,
    )
    assert again.json()["detail"] == "SHARE_REQUEST_ALREADY_PENDING"
    assert (
        len(await _told(session, owner.user.id, NotificationType.share_requested)) == 1
    )

    waiting = await client.get(
        owner.g(f"/share-requests/?batch_id={asked.json()['batch_id']}"),
        headers=owner.headers,
    )
    (request,) = waiting.json()
    assert (request["resource_name"], request["message"], request["level"]) == (
        "Budget",
        "For May",
        "read",
    )
    # The requester answers nothing of their own.
    assert (
        await client.post(
            reader.g("/share-requests/answer"),
            json={"ids": [request["id"]], "approve": True},
            headers=reader.headers,
        )
    ).json()["detail"] == "SHARE_REQUEST_CANNOT_ANSWER"

    answered = await client.post(
        owner.g("/share-requests/answer"),
        json={"ids": [request["id"]], "approve": True},
        headers=owner.headers,
    )
    assert answered.status_code == 204
    assert (
        await client.get(owner.g(f"/files/{file_id}"), headers=reader.headers)
    ).status_code == 200
    assert (
        len(await _told(session, reader.user.id, NotificationType.share_granted)) == 1
    )


async def test_nothing_outside_the_readers_initiatives_can_be_asked_about(
    client, session, acting_user, two
):
    owner, _ = two
    file = await create_file(session, owner.initiative, owner.user)
    outsider = await acting_user(
        guild_role=CommunityRole.member, guild=owner.guild, initiative=True
    )
    file_id = file.id

    standing = await client.get(
        outsider.g(f"/share-requests/standing?kind=file&entity_id={file_id}"),
        headers=outsider.headers,
    )
    asked = await client.post(
        outsider.g("/share-requests/"),
        json={"resource_type": "file", "resource_id": file_id},
        headers=outsider.headers,
    )
    missing = await client.get(
        outsider.g("/share-requests/standing?kind=file&entity_id=99999"),
        headers=outsider.headers,
    )
    # The same answer as for nothing at all.
    assert standing.status_code == asked.status_code == missing.status_code == 404
    assert standing.json() == missing.json()


async def test_a_collection_counts_what_its_reader_cannot_open_and_asks_for_it(
    client, session, two
):
    owner, reader = two
    shown = await create_file(session, owner.initiative, owner.user)
    await create_resource_grant(session, shown, all_initiative_members=True)
    hidden = [
        await create_file(session, owner.initiative, owner.user) for _ in range(2)
    ]
    collection = await create_collection(
        session, owner.initiative, owner.user, files=[shown, *hidden]
    )
    collection_id = collection.id

    read = await client.get(
        reader.g(f"/collections/{collection_id}"), headers=reader.headers
    )
    assert (read.json()["file_count"], read.json()["hidden_files"]) == (
        1,
        {"count": 2, "requested": 0},
    )

    asked = await client.post(
        reader.g("/share-requests/"),
        json={
            "resource_type": "file",
            "collection_id": collection_id,
            "level": "write",
        },
        headers=reader.headers,
    )
    assert asked.json()["count"] == 2
    read = await client.get(
        reader.g(f"/collections/{collection_id}"), headers=reader.headers
    )
    assert read.json()["hidden_files"] == {"count": 2, "requested": 2}
    # One notice for the batch, not one per file.
    assert (
        len(await _told(session, owner.user.id, NotificationType.share_requested)) == 1
    )


async def test_a_silent_no_tells_the_requester_nothing(client, session, two):
    owner, reader = two
    file = await create_file(session, owner.initiative, owner.user)
    file_id = file.id
    asked = await client.post(
        reader.g("/share-requests/"),
        json={"resource_type": "file", "resource_id": file_id},
        headers=reader.headers,
    )
    (request,) = (
        await client.get(
            owner.g(f"/share-requests/?batch_id={asked.json()['batch_id']}"),
            headers=owner.headers,
        )
    ).json()

    await client.post(
        owner.g("/share-requests/answer"),
        json={"ids": [request["id"]], "approve": False},
        headers=owner.headers,
    )

    assert await _told(session, reader.user.id, NotificationType.share_declined) == []
    standing = await client.get(
        reader.g(f"/share-requests/standing?kind=file&entity_id={file_id}"),
        headers=reader.headers,
    )
    assert standing.json()["pending"] is None


async def test_an_item_guest_asks_to_edit_and_a_share_with_everyone_reaches_them(
    client, session, acting_user
):
    row = await app_settings_service.ensure_settings_row(session)
    row.guests_enabled = True
    session.add(row)
    await session.commit()
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    given = await create_file(session, owner.initiative, owner.user)
    other = await create_file(session, owner.initiative, owner.user)
    guest = await create_guest(session, owner.guild)
    await create_resource_grant(session, given, user=guest)
    headers = get_auth_headers(guest)
    given_id, other_id = given.id, other.id

    # Nothing beyond what was given is known to them.
    assert (
        await client.post(
            owner.g("/share-requests/"),
            json={"resource_type": "file", "resource_id": other_id},
            headers=headers,
        )
    ).status_code == 404
    asked = await client.post(
        owner.g("/share-requests/"),
        json={"resource_type": "file", "resource_id": given_id, "level": "write"},
        headers=headers,
    )
    assert asked.status_code == 201
    (request,) = (
        await client.get(
            owner.g(f"/share-requests/?batch_id={asked.json()['batch_id']}"),
            headers=owner.headers,
        )
    ).json()
    assert request["guest_until"] is not None

    await client.post(
        owner.g("/share-requests/answer"),
        json={"ids": [request["id"]], "approve": True, "scope": "initiative"},
        headers=owner.headers,
    )

    standing = await client.get(
        owner.g(f"/share-requests/standing?kind=file&entity_id={given_id}"),
        headers=headers,
    )
    assert standing.json()["level"] == "write"


async def test_a_task_is_asked_for_through_its_project(client, session, two):
    owner, reader = two
    project = await create_project(session, owner.initiative, owner.user)
    task = await create_task(session, project)
    ids = (project.id, task.id)

    project_id, task_id = ids
    standing = await client.get(
        reader.g(f"/share-requests/standing?kind=task&entity_id={task_id}"),
        headers=reader.headers,
    )
    assert (standing.json()["resource_type"], standing.json()["resource_id"]) == (
        "project",
        project_id,
    )


async def test_leaving_the_initiative_takes_what_they_asked_for(client, session, two):
    owner, reader = two
    file = await create_file(session, owner.initiative, owner.user)
    file_id, initiative_id, reader_id = file.id, owner.initiative.id, reader.user.id
    asked = await client.post(
        reader.g("/share-requests/"),
        json={"resource_type": "file", "resource_id": file_id},
        headers=reader.headers,
    )
    batch = asked.json()["batch_id"]

    removed = await client.delete(
        owner.g(f"/initiatives/{initiative_id}/members/{reader_id}"),
        headers=owner.headers,
    )

    assert removed.status_code == 200
    assert (
        await client.get(
            owner.g(f"/share-requests/?batch_id={batch}"), headers=owner.headers
        )
    ).json() == []
