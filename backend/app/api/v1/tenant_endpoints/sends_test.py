"""Sending somebody something, end to end: who hears, and what the line names."""

import pytest
from sqlmodel import select

from app.models.platform.guild import CommunityRole
from app.models.platform.notification import Notification, NotificationType
from app.models.tenant.share_request import ShareRequest
from app.testing import create_file, create_resource_grant
from app.testing.notices import drain_notices


async def _lines(client, actor) -> list[dict]:
    """The recipient's sent lines, as their bell reads them."""
    await drain_notices()
    response = await client.get("/api/v1/notifications/", headers=actor.headers)
    assert response.status_code == 200, response.text
    return [
        n
        for n in response.json()["notifications"]
        if n["type"] == NotificationType.item_sent.value
    ]


@pytest.fixture
async def three(acting_user):
    """The owner of a file, a member of its initiative, and a member of the
    community in another initiative."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    elsewhere = await acting_user(
        guild_role=CommunityRole.member, guild=owner.guild, initiative=True
    )
    return owner, member, elsewhere


async def test_somebody_who_can_open_it_is_sent_it_with_the_note(
    client, session, three
):
    owner, member, _ = three
    file = await create_file(session, owner.initiative, owner.user, name="Budget")
    await create_resource_grant(session, file, user=member.user)

    sent = await client.post(
        owner.g("/sends/"),
        json={
            "kind": "file",
            "entity_id": file.id,
            "user_ids": [member.user.id, owner.user.id],
            "note": "For Thursday",
        },
        headers=owner.headers,
    )

    assert sent.status_code == 200, sent.text
    assert sent.json() == {"sent": [member.user.id], "let_in": [], "may_ask": []}
    (line,) = await _lines(client, member)
    assert line["data"]["note"] == "For Thursday"
    assert line["data"]["entity_name"] == "Budget"


async def test_somebody_in_its_initiative_who_cannot_open_it_may_ask(
    client, session, three
):
    owner, member, _ = three
    file = await create_file(session, owner.initiative, owner.user, name="Budget")

    sent = await client.post(
        owner.g("/sends/"),
        json={"kind": "file", "entity_id": file.id, "user_ids": [member.user.id]},
        headers=owner.headers,
    )

    assert sent.json() == {"sent": [], "let_in": [], "may_ask": [member.user.id]}
    (line,) = await _lines(client, member)
    # The kind and the sender, never the name.
    assert line["data"]["entity_type"] == "file"
    assert not line["data"].get("entity_name")
    assert (
        await client.get(owner.g(f"/files/{file.id}"), headers=member.headers)
    ).status_code in (403, 404)


async def test_the_sender_lets_them_in_and_answers_what_they_asked(
    client, session, three
):
    owner, member, _ = three
    file = await create_file(session, owner.initiative, owner.user, name="Budget")
    file_id = file.id
    await client.post(
        member.g("/share-requests/"),
        json={"resource_type": "file", "resource_id": file_id},
        headers=member.headers,
    )

    sent = await client.post(
        owner.g("/sends/"),
        json={
            "kind": "file",
            "entity_id": file_id,
            "user_ids": [member.user.id],
            "level": "read",
        },
        headers=owner.headers,
    )

    assert sent.json() == {
        "sent": [member.user.id],
        "let_in": [member.user.id],
        "may_ask": [],
    }
    assert (
        await client.get(owner.g(f"/files/{file_id}"), headers=member.headers)
    ).status_code == 200
    (request,) = (
        await session.exec(
            select(ShareRequest).where(ShareRequest.resource_id == file_id)
        )
    ).all()
    assert request.status == "approved"
    # One line: the send's, not a grant's beside it.
    (line,) = await _lines(client, member)
    assert line["data"]["entity_name"] == "Budget"
    await drain_notices()
    assert not (
        await session.exec(
            select(Notification).where(
                Notification.user_id == member.user.id,
                Notification.type == NotificationType.share_granted,
            )
        )
    ).all()


async def test_only_somebody_who_may_share_it_lets_anyone_in(
    client, session, acting_user, three
):
    owner, member, _ = three
    other = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    file = await create_file(session, owner.initiative, owner.user)
    await create_resource_grant(session, file, user=member.user)

    sent = await client.post(
        member.g("/sends/"),
        json={
            "kind": "file",
            "entity_id": file.id,
            "user_ids": [other.user.id],
            "level": "write",
        },
        headers=member.headers,
    )

    assert sent.status_code == 403
    assert not await _lines(client, other)


async def test_nobody_outside_its_initiative_is_sent_it(client, session, three):
    owner, _, elsewhere = three
    file = await create_file(session, owner.initiative, owner.user)

    sent = await client.post(
        owner.g("/sends/"),
        json={
            "kind": "file",
            "entity_id": file.id,
            "user_ids": [elsewhere.user.id],
            "level": "read",
        },
        headers=owner.headers,
    )

    assert sent.status_code == 404
    assert sent.json()["detail"] == "SEND_NOT_IN_INITIATIVE"
    assert not await _lines(client, elsewhere)
