"""Tests for the post endpoints — CRUD, the board's order, pinning, scheduling,
and the authorization gates (feature gate, role create gate, DAC levels).

The post-specific concerns beyond the usual tool contract are the three things
the board owns: what order notices come back in, who may lift one above the
others, and when a notice becomes something other people can see.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import CodedError
from app.core.tools import Tool
from app.models.platform.guild import CommunityRole
from app.models.platform.notification import Notification, NotificationType
from app.models.tenant.post import Post
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.schemas.tenant.post import MAX_POST_TEXT_CHARS
from app.testing import (
    strip_non_owner_grants,
    Actor,
    create_comment,
    create_post,
    create_resource_grant,
    lexical_body,
    drain_notices,
    grant_role_permission,
)
from app.testing import route_as


async def _posts_enabled(session: AsyncSession, initiative) -> None:
    initiative.posts_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


async def _joins(acting_user, actor: Actor, **overrides: Any) -> Actor:
    """Another account in the same guild and initiative as ``actor``."""
    return await acting_user(
        **{
            "guild_role": CommunityRole.member,
            "guild": actor.guild,
            "initiative": actor.initiative,
            **overrides,
        }
    )


async def _draft(session: AsyncSession, actor: Actor, **fields: Any) -> Post:
    """A notice written but scheduled for tomorrow, so it is not up yet."""
    return await create_post(
        session,
        actor.initiative,
        actor.user,
        published_at=None,
        scheduled_for=datetime.now(timezone.utc) + timedelta(days=1),
        **{"name": "Embargoed", **fields},
    )


@pytest.fixture
async def board(acting_user, session) -> Actor:
    """A guild admin with an initiative whose board is switched on."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    return a


@dataclass
class _DraftScene:
    """A notice that is not up yet, whoever wrote it, and somebody else in the
    initiative it is not up for."""

    author: Actor
    reader: Actor
    draft: Post


@pytest.fixture
async def draft_scene(acting_user, session) -> _DraftScene:
    """An embargoed notice and the two people around it.

    The author is an ordinary member, not a guild admin, so what keeps the
    draft theirs is the notice's own grants. The reader is somebody else in
    the same initiative, so the notice's default sharing already reaches
    them — being shared with is not the same as being up.
    """
    author = await acting_user(guild_role=CommunityRole.member, initiative=True)
    reader = await _joins(acting_user, author)
    await _posts_enabled(session, author.initiative)
    return _DraftScene(
        author=author, reader=reader, draft=await _draft(session, author)
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def test_create_post(client: AsyncClient, board: Actor):
    """Posting seeds the author's owner grant plus the default all-members read
    grant — a notice nobody could read is not a notice."""
    response = await client.post(
        board.g("/posts/"),
        headers=board.headers,
        json={
            "name": "Server maintenance Sunday",
            "initiative_id": board.initiative.id,
            "body": lexical_body("We are upgrading at 9am."),
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Server maintenance Sunday"
    assert body["can"]["delete"] is True
    assert body["is_pinned"] is False
    assert body["pinned_at"] is None
    assert body["excerpt"] == "We are upgrading at 9am."


@pytest.mark.parametrize("field", ["scheduled_for", "poll"])
async def test_create_post_requires_offset_for_instants(client, board, field):
    payload = {"name": "With a deadline", "initiative_id": board.initiative.id}
    if field == "poll":
        payload[field] = {
            "options": [{"text": "Yes"}, {"text": "No"}],
            "closes_at": "2099-10-20T12:00:00",
        }
    else:
        payload[field] = "2099-10-20T12:00:00"
    response = await client.post(
        board.g("/posts/"), headers=board.headers, json=payload
    )
    assert response.status_code == 422, response.text


async def test_pin_requires_offset_for_expiry(client, session, board):
    post = await create_post(session, board.initiative, board.user)
    response = await client.put(
        board.g(f"/posts/{post.id}/pin"),
        headers=board.headers,
        json={"pinned": True, "expires_at": "2099-10-20T12:00:00"},
    )
    assert response.status_code == 422, response.text


async def test_post_schedule_update_requires_offset(client, session, board):
    post = await _draft(session, board)
    response = await client.patch(
        board.g(f"/posts/{post.id}"),
        headers=board.headers,
        json={"scheduled_for": "2099-10-20T12:00:00"},
    )
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("offset", ["Z", "+02:00"])
async def test_post_schedule_accepts_explicit_offset(client, board, offset):
    response = await client.post(
        board.g("/posts/"),
        headers=board.headers,
        json={
            "name": "Scheduled",
            "initiative_id": board.initiative.id,
            "scheduled_for": f"2099-10-20T12:00:00{offset}",
        },
    )
    assert response.status_code == 201, response.text
    assert datetime.fromisoformat(
        response.json()["scheduled_for"]
    ) == datetime.fromisoformat(f"2099-10-20T12:00:00{offset}")


async def test_create_requires_feature_enabled(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    # The factory switches every tool on, so a test about one being OFF
    # turns it off.
    a.initiative.posts_enabled = False
    session.add(a.initiative)
    await session.commit()

    response = await client.post(
        a.g("/posts/"),
        headers=a.headers,
        json={"name": "Nope", "initiative_id": a.initiative.id},
    )

    assert response.status_code == 403
    assert response.json() == Tool.post.disabled().body


async def test_create_requires_the_create_permission(
    client: AsyncClient, acting_user, board: Actor
):
    """A plain member cannot post to the board unless their role says so."""
    b = await _joins(acting_user, board, initiative_role="member")

    response = await client.post(
        b.g("/posts/"),
        headers=b.headers,
        json={"name": "Unauthorized", "initiative_id": board.initiative.id},
    )

    assert response.status_code == 403
    assert response.json() == Tool.post.create_denied().body


async def test_list_carries_bodies_and_read_matches(
    client: AsyncClient, board: Actor, session
):
    """A board renders its notices, so the list carries whole posts — unlike
    every other tool list, which omits the body."""
    post = await create_post(
        session,
        board.initiative,
        board.user,
        name="Ops",
        body=lexical_body("All clear."),
    )

    listing = await client.get(board.g("/posts/"), headers=board.headers)
    assert listing.status_code == 200
    (item,) = listing.json()["items"]
    assert item["name"] == "Ops"
    assert item["body"]["root"]["children"][0]["children"][0]["text"] == "All clear."
    assert item["excerpt"] == "All clear."

    detail = await client.get(board.g(f"/posts/{post.id}"), headers=board.headers)
    assert detail.status_code == 200
    assert detail.json()["body"] == item["body"]


async def test_board_pages_in_fives_by_default(
    client: AsyncClient, board: Actor, session
):
    """The default page is small on purpose: each row is a body the client
    mounts an editor for, and the board fetches the next page as somebody
    reaches the bottom rather than making them ask."""
    for i in range(7):
        await create_post(session, board.initiative, board.user, name=f"Notice {i}")

    listing = await client.get(board.g("/posts/"), headers=board.headers)
    assert listing.status_code == 200
    payload = listing.json()
    assert payload["page_size"] == 5
    assert len(payload["items"]) == 5
    assert payload["total_count"] == 7
    assert payload["has_next"] is True


async def test_a_page_larger_than_the_cap_is_refused(client: AsyncClient, board: Actor):
    response = await client.get(board.g("/posts/?page_size=200"), headers=board.headers)
    assert response.status_code == 422


async def test_update_post(client: AsyncClient, board: Actor, session):
    post = await create_post(session, board.initiative, board.user, name="Draft")

    response = await client.patch(
        board.g(f"/posts/{post.id}"),
        headers=board.headers,
        json={"name": "Final", "body": lexical_body("Rewritten.")},
    )

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Final"
    assert response.json()["excerpt"] == "Rewritten."


async def test_delete_post_requires_owner(
    client: AsyncClient, acting_user, board: Actor, session
):
    """A reader cannot delete somebody else's notice."""
    post = await create_post(session, board.initiative, board.user)
    b = await _joins(acting_user, board, initiative_role="member")

    denied = await client.delete(b.g(f"/posts/{post.id}"), headers=b.headers)
    assert denied.status_code == 403

    allowed = await client.delete(board.g(f"/posts/{post.id}"), headers=board.headers)
    assert allowed.status_code == 204


async def test_a_post_not_shared_is_not_listed(
    client: AsyncClient, acting_user, board: Actor, session
):
    post = await create_post(session, board.initiative, board.user, name="Private")
    await strip_non_owner_grants(session, post, board.user.id)
    b = await _joins(acting_user, board, initiative_role="member")

    listing = await client.get(b.g("/posts/"), headers=b.headers)
    assert listing.status_code == 200
    assert listing.json()["items"] == []


async def test_the_board_carries_each_post_s_comment_count(
    client: AsyncClient, board: Actor, session
):
    """A reader sees there is a conversation without opening the post."""
    talked_about = await create_post(session, board.initiative, board.user, name="Busy")
    await create_post(session, board.initiative, board.user, name="Quiet")
    await create_comment(session, board.user, post=talked_about)
    await create_comment(session, board.user, post=talked_about)

    listing = await client.get(board.g("/posts/"), headers=board.headers)
    assert listing.status_code == 200
    counts = {p["name"]: p["comment_count"] for p in listing.json()["items"]}
    assert counts == {"Busy": 2, "Quiet": 0}


async def test_a_trashed_comment_leaves_the_count(
    client: AsyncClient, board: Actor, session
):
    """A thread that was cleared out reads as empty, not as history."""
    from app.services.tenant.soft_delete import soft_delete_entity

    post = await create_post(session, board.initiative, board.user)
    comment = await create_comment(session, board.user, post=post)
    await soft_delete_entity(
        session, comment, deleted_by_user_id=board.user.id, retention_days=30
    )
    await session.commit()

    detail = await client.get(board.g(f"/posts/{post.id}"), headers=board.headers)
    assert detail.status_code == 200
    assert detail.json()["comment_count"] == 0


# ---------------------------------------------------------------------------
# The board's order
# ---------------------------------------------------------------------------


async def test_board_orders_pins_first_then_newest(
    client: AsyncClient, board: Actor, session
):
    """The default order is the board: live pins on top, then reverse
    chronological."""
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    old = await create_post(
        session, board.initiative, board.user, name="Old", created_at=base
    )
    await create_post(
        session,
        board.initiative,
        board.user,
        name="New",
        created_at=base + timedelta(days=2),
    )

    unpinned = await client.get(board.g("/posts/"), headers=board.headers)
    assert [p["name"] for p in unpinned.json()["items"]] == ["New", "Old"]

    pinned = await client.put(
        board.g(f"/posts/{old.id}/pin"), headers=board.headers, json={"pinned": True}
    )
    assert pinned.status_code == 200, pinned.text

    reordered = await client.get(board.g("/posts/"), headers=board.headers)
    assert [p["name"] for p in reordered.json()["items"]] == ["Old", "New"]


async def test_a_lapsed_pin_falls_back_into_the_feed(
    client: AsyncClient, board: Actor, session
):
    """An expiry in the past reads exactly like no pin: the post orders by its
    own age again, and nothing had to sweep the columns."""
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    old = await create_post(
        session,
        board.initiative,
        board.user,
        name="Old",
        created_at=base,
        pinned_at=base,
        pinned_by=board.user.id,
        pin_expires_at=base + timedelta(days=1),
    )
    await create_post(
        session,
        board.initiative,
        board.user,
        name="New",
        created_at=base + timedelta(days=2),
    )

    listing = await client.get(board.g("/posts/"), headers=board.headers)
    items = listing.json()["items"]
    assert [p["name"] for p in items] == ["New", "Old"]
    # The record of the pin survives; only its force has lapsed.
    lapsed = next(p for p in items if p["name"] == "Old")
    assert lapsed["is_pinned"] is False
    assert lapsed["pinned_at"] is not None
    assert lapsed["pinned_by"] == old.pinned_by


async def test_sort_by_opts_out_of_the_board_order(
    client: AsyncClient, board: Actor, session
):
    """The guild-wide table needs an ordinary tool sort, so naming one wins
    over the pinned band."""
    await create_post(session, board.initiative, board.user, name="Beta")
    alpha = await create_post(session, board.initiative, board.user, name="Alpha")
    await client.put(
        board.g(f"/posts/{alpha.id}/pin"), headers=board.headers, json={"pinned": True}
    )

    listing = await client.get(board.g("/posts/?sort_by=name"), headers=board.headers)
    assert [p["name"] for p in listing.json()["items"]] == ["Alpha", "Beta"]


# ---------------------------------------------------------------------------
# Pinning
# ---------------------------------------------------------------------------


async def test_pin_requires_manager_not_write_access(
    client: AsyncClient, acting_user, board: Actor, session
):
    """A pin puts one notice above everyone else's, so writing your own post is
    not enough — this is initiative authority."""
    b = await _joins(acting_user, board, initiative_role="member")
    # b owns the post outright and still may not pin it.
    post = await create_post(session, board.initiative, b.user)

    denied = await client.put(
        b.g(f"/posts/{post.id}/pin"), headers=b.headers, json={"pinned": True}
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "POST_PIN_MANAGER_REQUIRED"

    allowed = await client.put(
        board.g(f"/posts/{post.id}/pin"), headers=board.headers, json={"pinned": True}
    )
    assert allowed.status_code == 200
    assert allowed.json()["is_pinned"] is True
    assert allowed.json()["pinned_by"] == board.user.id


async def test_unpin_clears_the_expiry_with_it(
    client: AsyncClient, board: Actor, session
):
    """An expiry belongs to a pin; leaving one behind would silently apply to
    the next one."""
    post = await create_post(session, board.initiative, board.user)
    expires = datetime.now(timezone.utc) + timedelta(days=3)

    await client.put(
        board.g(f"/posts/{post.id}/pin"),
        headers=board.headers,
        json={"pinned": True, "expires_at": expires.isoformat()},
    )
    response = await client.put(
        board.g(f"/posts/{post.id}/pin"), headers=board.headers, json={"pinned": False}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["pinned_at"] is None
    assert body["pinned_by"] is None
    assert body["pin_expires_at"] is None
    assert body["is_pinned"] is False


async def test_pin_refuses_an_expiry_already_past(
    client: AsyncClient, board: Actor, session
):
    """A pin that is already over is a no-op that reads as a pin — refused
    rather than stored."""
    post = await create_post(session, board.initiative, board.user)
    past = datetime.now(timezone.utc) - timedelta(days=1)

    response = await client.put(
        board.g(f"/posts/{post.id}/pin"),
        headers=board.headers,
        json={"pinned": True, "expires_at": past.isoformat()},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "POST_PIN_EXPIRY_IN_PAST"


async def test_pin_requires_read_access_before_the_manager_check(
    client: AsyncClient, acting_user, board: Actor, session
):
    """The two gates run in order: read access on the post, then initiative
    authority. A caller without the first is refused at it."""
    post = await create_post(session, board.initiative, board.user)
    await strip_non_owner_grants(session, post, board.user.id)
    b = await _joins(acting_user, board, initiative_role="member")

    response = await client.put(
        b.g(f"/posts/{post.id}/pin"), headers=b.headers, json={"pinned": True}
    )
    assert response.status_code in (403, 404)
    # Refused at the read gate, so it never reaches the manager check.
    assert response.json()["detail"] != "POST_PIN_MANAGER_REQUIRED"


# ---------------------------------------------------------------------------
# Length
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("length", "status", "detail"),
    [
        (MAX_POST_TEXT_CHARS, 201, None),
        (MAX_POST_TEXT_CHARS + 1, 422, "POST_BODY_TOO_LONG"),
    ],
    ids=["at the ceiling", "one character over it"],
)
async def test_a_notice_is_taken_up_to_the_length_ceiling(
    client: AsyncClient, board: Actor, length: int, status: int, detail: str | None
):
    """A board is read, not studied — something longer than this is a file.
    The ceiling itself is inclusive."""
    response = await client.post(
        board.g("/posts/"),
        headers=board.headers,
        json={
            "name": "War and Peace",
            "initiative_id": board.initiative.id,
            "body": lexical_body("x" * length),
        },
    )

    assert response.status_code == status, response.text
    assert response.json().get("detail") == detail


async def test_an_edit_cannot_grow_a_post_past_the_limit(
    client: AsyncClient, board: Actor, session
):
    """The ceiling is on the body, not on the way it arrived."""
    post = await create_post(session, board.initiative, board.user)

    response = await client.patch(
        board.g(f"/posts/{post.id}"),
        headers=board.headers,
        json={"body": lexical_body("x" * (MAX_POST_TEXT_CHARS + 1))},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "POST_BODY_TOO_LONG"


# ---------------------------------------------------------------------------
# Reactions
# ---------------------------------------------------------------------------


async def test_a_post_carries_its_reactions(client: AsyncClient, board: Actor, session):
    """Chips ride along with the post, so a board renders them from the one
    list call rather than a request per row."""
    post = await create_post(session, board.initiative, board.user)

    toggled = await client.put(
        board.g(f"/reactions/post/{post.id}"),
        headers=board.headers,
        json={"emoji": "🎉"},
    )
    assert toggled.status_code == 200, toggled.text

    listing = await client.get(board.g("/posts/"), headers=board.headers)
    (item,) = listing.json()["items"]
    assert [(g["emoji"], g["count"], g["reacted"]) for g in item["reactions"]] == [
        ("🎉", 1, True)
    ]

    detail = await client.get(board.g(f"/posts/{post.id}"), headers=board.headers)
    assert detail.json()["reactions"] == item["reactions"]


@pytest.mark.parametrize(
    ("shared_with_them", "expected"),
    [(True, {200}), (False, {403, 404})],
    ids=["a notice they can see", "one they cannot"],
)
async def test_reacting_takes_read_access_and_nothing_more(
    client: AsyncClient,
    acting_user,
    board: Actor,
    session,
    shared_with_them: bool,
    expected: set[int],
):
    """A notice everyone on the board can see is one everyone can react to —
    reacting is a gesture, not an edit. One they cannot see is not theirs to
    react to either."""
    post = await create_post(session, board.initiative, board.user)
    if not shared_with_them:
        await strip_non_owner_grants(session, post, board.user.id)
    b = await _joins(acting_user, board, initiative_role="member")

    response = await client.put(
        b.g(f"/reactions/post/{post.id}"), headers=b.headers, json={"emoji": "👍"}
    )

    assert response.status_code in expected, response.text


# ---------------------------------------------------------------------------
# Scheduling and publication
# ---------------------------------------------------------------------------


async def _notifications_for(
    session: AsyncSession, user_id: int, ntype: NotificationType
) -> list[Notification]:
    await drain_notices()
    await session.exec(text("SET search_path TO public"))
    result = await session.exec(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.type == ntype,
        )
    )
    return list(result.all())


async def test_posting_now_notifies_the_people_it_is_shared_with(
    client: AsyncClient, acting_user, board: Actor, session
):
    """The default sharing is the whole initiative, so the whole initiative
    hears about it — everyone except the author."""
    b = await _joins(acting_user, board)

    response = await client.post(
        board.g("/posts/"),
        headers=board.headers,
        json={
            "name": "Doors open at seven",
            "initiative_id": board.initiative.id,
            "body": lexical_body("Bring a chair."),
        },
    )
    assert response.status_code == 201
    assert response.json()["is_published"] is True

    assert (
        len(
            await _notifications_for(
                session, b.user.id, NotificationType.post_published
            )
        )
        == 1
    )
    assert (
        await _notifications_for(
            session, board.user.id, NotificationType.post_published
        )
        == []
    )


async def test_a_notice_only_notifies_who_it_was_shared_with(
    client: AsyncClient, acting_user, board: Actor, session
):
    """The fan-out follows the post's own grants, not the initiative roster.

    This is the gate the whole feature hangs on: sharing a notice with one
    person must not ring the bell of everybody who happens to be in the
    initiative.
    """
    named = await _joins(acting_user, board)
    bystander = await _joins(acting_user, board)

    response = await client.post(
        board.g("/posts/"),
        headers=board.headers,
        json={
            "name": "Just for you",
            "initiative_id": board.initiative.id,
            "body": lexical_body("A word in private."),
            "grants": [{"user_id": named.user.id, "level": "read"}],
        },
    )
    assert response.status_code == 201

    assert (
        len(
            await _notifications_for(
                session, named.user.id, NotificationType.post_published
            )
        )
        == 1
    )
    assert (
        await _notifications_for(
            session, bystander.user.id, NotificationType.post_published
        )
        == []
    )


async def test_a_scheduled_notice_is_not_published_and_notifies_nobody(
    client: AsyncClient, acting_user, board: Actor, session
):
    b = await _joins(acting_user, board)
    when = datetime.now(timezone.utc) + timedelta(days=1)

    response = await client.post(
        board.g("/posts/"),
        headers=board.headers,
        json={
            "name": "Tomorrow's news",
            "initiative_id": board.initiative.id,
            "body": lexical_body("Not yet."),
            "scheduled_for": when.isoformat(),
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["is_published"] is False
    assert payload["published_at"] is None
    assert payload["scheduled_for"] is not None

    assert (
        await _notifications_for(session, b.user.id, NotificationType.post_published)
        == []
    )


async def test_a_schedule_in_the_past_posts_it_now(client: AsyncClient, board: Actor):
    """An instant that has already gone is somebody asking for it now — the
    same thing an omitted schedule means, so it takes the same branch."""
    when = datetime.now(timezone.utc) - timedelta(minutes=5)

    response = await client.post(
        board.g("/posts/"),
        headers=board.headers,
        json={
            "name": "Backdated",
            "initiative_id": board.initiative.id,
            "body": lexical_body("Now."),
            "scheduled_for": when.isoformat(),
        },
    )
    assert response.status_code == 201
    assert response.json()["is_published"] is True
    assert response.json()["scheduled_for"] is None


async def test_a_draft_is_invisible_to_a_reader_but_not_to_its_author(
    client: AsyncClient, draft_scene: _DraftScene
):
    """The draft leg is write access, not any access: the notice is already
    shared with the reader and they still do not get it early."""
    author, reader, draft = draft_scene.author, draft_scene.reader, draft_scene.draft

    mine = await client.get(author.g("/posts/"), headers=author.headers)
    theirs = await client.get(reader.g("/posts/"), headers=reader.headers)

    assert [p["id"] for p in mine.json()["items"]] == [draft.id]
    assert theirs.json()["items"] == []
    assert theirs.json()["total_count"] == 0
    assert (
        await client.get(author.g(f"/posts/{draft.id}"), headers=author.headers)
    ).status_code == 200


async def test_a_draft_is_out_of_the_sidebar_counts(
    client: AsyncClient, draft_scene: _DraftScene, session
):
    author, reader = draft_scene.author, draft_scene.reader
    await create_post(session, author.initiative, author.user, name="Live one")

    counts = await client.get(
        reader.g("/tools/counts/by-initiative"), headers=reader.headers
    )
    assert counts.json()["counts"]["post"][str(author.initiative.id)] == 1


async def test_an_editor_can_see_a_draft(
    client: AsyncClient, draft_scene: _DraftScene, session
):
    editor, draft = draft_scene.reader, draft_scene.draft
    await create_resource_grant(
        session, draft, level=ResourceAccessLevel.write, user=editor.user
    )

    listing = await client.get(editor.g("/posts/"), headers=editor.headers)
    assert [p["id"] for p in listing.json()["items"]] == [draft.id]


async def test_clearing_the_schedule_publishes_and_notifies(
    client: AsyncClient, acting_user, board: Actor, session
):
    b = await _joins(acting_user, board)
    draft = await _draft(session, board, name="Post it now")

    response = await client.patch(
        board.g(f"/posts/{draft.id}"),
        headers=board.headers,
        json={"scheduled_for": None},
    )
    assert response.status_code == 200
    assert response.json()["is_published"] is True
    assert (
        len(
            await _notifications_for(
                session, b.user.id, NotificationType.post_published
            )
        )
        == 1
    )


async def test_a_published_notice_cannot_be_rescheduled(
    client: AsyncClient, board: Actor, session
):
    """Publication is not reversible — the people it was announced to have
    already been told."""
    post = await create_post(session, board.initiative, board.user, name="Already up")

    response = await client.patch(
        board.g(f"/posts/{post.id}"),
        headers=board.headers,
        json={
            "scheduled_for": (
                datetime.now(timezone.utc) + timedelta(days=1)
            ).isoformat()
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "POST_ALREADY_PUBLISHED"


async def test_posting_an_already_posted_notice_now_is_nothing_to_do(
    client: AsyncClient, acting_user, board: Actor, session
):
    """ "Post now" twice is a double click, not a conflict — and it must not
    announce the notice a second time."""
    b = await _joins(acting_user, board)
    draft = await _draft(session, board, name="Twice")
    body = {"scheduled_for": None}

    first = await client.patch(
        board.g(f"/posts/{draft.id}"), headers=board.headers, json=body
    )
    second = await client.patch(
        board.g(f"/posts/{draft.id}"), headers=board.headers, json=body
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["is_published"] is True
    assert (
        len(
            await _notifications_for(
                session, b.user.id, NotificationType.post_published
            )
        )
        == 1
    )


async def test_the_board_dates_a_notice_by_when_it_went_up(
    client: AsyncClient, board: Actor, session
):
    """A notice written last week and published today leads a notice written
    yesterday — the board is a feed of what has been said, not of drafting."""
    now = datetime.now(timezone.utc)
    await create_post(
        session,
        board.initiative,
        board.user,
        name="Written yesterday",
        created_at=now - timedelta(days=1),
        published_at=now - timedelta(days=1),
    )
    await create_post(
        session,
        board.initiative,
        board.user,
        name="Written last week, up today",
        created_at=now - timedelta(days=7),
        published_at=now,
    )

    response = await client.get(board.g("/posts/"), headers=board.headers)
    assert [p["name"] for p in response.json()["items"]] == [
        "Written last week, up today",
        "Written yesterday",
    ]


async def test_a_draft_is_not_exported(board: Actor, session):
    """An export is a record of what a board has said, and a draft has said
    nothing yet — including to the author it belongs to."""
    from app.services.export.adapters.post import PostAdapter

    live = await create_post(session, board.initiative, board.user, name="Up")
    await _draft(session, board, name="Not up")

    ids = await PostAdapter().initiative_ids(session, board.initiative.id)
    assert ids == [live.id]


async def test_setting_an_expiry_does_not_re_pin(
    client: AsyncClient, board: Actor, session
):
    """Putting an end date on a live pin changes the end date and nothing else.

    Re-stamping ``pinned_at`` would vault a three-day-old pin over the pins
    made since it, which is the band's ordering key.
    """
    post = await create_post(
        session, board.initiative, board.user, name="Long-standing"
    )

    first = await client.put(
        board.g(f"/posts/{post.id}/pin"), headers=board.headers, json={"pinned": True}
    )
    assert first.status_code == 200
    pinned_at = first.json()["pinned_at"]

    second = await client.put(
        board.g(f"/posts/{post.id}/pin"),
        headers=board.headers,
        json={
            "pinned": True,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
        },
    )
    assert second.status_code == 200
    assert second.json()["pinned_at"] == pinned_at
    assert second.json()["pin_expires_at"] is not None


async def test_re_pinning_a_lapsed_pin_starts_a_new_one(
    client: AsyncClient, board: Actor, session
):
    """A pin whose expiry has passed reads as no pin at all, so pinning again
    is a new pin and takes today's date."""
    stale = datetime.now(timezone.utc) - timedelta(days=5)
    post = await create_post(
        session,
        board.initiative,
        board.user,
        name="Lapsed",
        pinned_at=stale,
        pinned_by=board.user.id,
        pin_expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )

    response = await client.put(
        board.g(f"/posts/{post.id}/pin"), headers=board.headers, json={"pinned": True}
    )
    assert response.status_code == 200
    assert response.json()["pinned_at"] != stale.isoformat()
    assert response.json()["is_pinned"] is True
    assert response.json()["pin_expires_at"] is None


# ---------------------------------------------------------------------------
# A draft is not reachable by any door
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("surface", "door"),
    [
        ("opening it", lambda s: ("GET", s.reader.g(f"/posts/{s.draft.id}"), {})),
        (
            "reading its comments",
            lambda s: (
                "GET",
                s.reader.g("/comments/"),
                {"params": {"post_id": s.draft.id}},
            ),
        ),
        (
            "adding a comment",
            lambda s: (
                "POST",
                s.reader.g("/comments/"),
                {"json": {"content": "Seen it", "post_id": s.draft.id}},
            ),
        ),
        (
            "reacting to it",
            lambda s: (
                "PUT",
                s.reader.g(f"/reactions/post/{s.draft.id}"),
                {"json": {"emoji": "👍"}},
            ),
        ),
    ],
    ids=lambda v: v if isinstance(v, str) else "",
)
async def test_a_draft_answers_a_reader_as_if_it_were_not_there(
    client: AsyncClient, draft_scene: _DraftScene, surface: str, door
):
    """Every door onto a notice is shut until it is up, and each says the same
    thing: there is nothing here."""
    method, url, kwargs = door(draft_scene)

    response = await client.request(
        method, url, headers=draft_scene.reader.headers, **kwargs
    )

    assert response.status_code == 404, response.text


async def test_a_draft_cannot_be_exported(draft_scene: _DraftScene, role_session):
    """The export seam resolves an id the caller chose, so it asks the same
    question the board does rather than only read access.

    On the request login, routed as the reader: what a notice is to somebody
    is the level they hold on it, and that is answered for whoever the
    session is."""
    from app.services.export.adapters import ADAPTERS

    reader, draft = draft_scene.reader, draft_scene.draft
    guild_id = draft_scene.author.guild.id

    s = await role_session("app_user")
    await route_as(s, user_id=reader.user.id, guild_id=guild_id)
    with pytest.raises(CodedError) as refusal:
        await ADAPTERS["post"].fetch(s, reader.user, guild_id, draft.id)
    assert refusal.value.status_code == 404


async def test_its_author_still_reaches_a_draft_everywhere(
    client: AsyncClient, draft_scene: _DraftScene, role_session
):
    """The gate is "not yours to read yet", not "gone" — whoever could edit it
    keeps every door."""
    from app.services.export.adapters import ADAPTERS

    author, draft = draft_scene.author, draft_scene.draft

    assert (
        await client.get(author.g(f"/posts/{draft.id}"), headers=author.headers)
    ).status_code == 200
    assert (
        await client.put(
            author.g(f"/reactions/post/{draft.id}"),
            headers=author.headers,
            json={"emoji": "👍"},
        )
    ).status_code == 200
    s = await role_session("app_user")
    await route_as(s, user_id=author.user.id, guild_id=author.guild.id)
    assert await ADAPTERS["post"].fetch(s, author.user, author.guild.id, draft.id)


# ---------------------------------------------------------------------------
# Read receipts
# ---------------------------------------------------------------------------


async def test_a_notice_starts_unread_and_stays_read(
    client: AsyncClient, acting_user, board: Actor, session
):
    reader = await _joins(acting_user, board)
    post = await create_post(session, board.initiative, board.user, name="Read me")

    before = await client.get(reader.g("/posts/"), headers=reader.headers)
    assert [p["is_read"] for p in before.json()["items"]] == [False]

    marked = await client.post(
        reader.g("/posts/read"), headers=reader.headers, json={"post_ids": [post.id]}
    )
    assert marked.status_code == 200
    assert marked.json()["marked"] == 1

    after = await client.get(reader.g("/posts/"), headers=reader.headers)
    assert [p["is_read"] for p in after.json()["items"]] == [True]


async def test_marking_the_same_page_again_changes_nothing(
    client: AsyncClient, acting_user, board: Actor, session
):
    """The board sends what is on screen, and scrolling back up sends it again.
    That has to be free."""
    reader = await _joins(acting_user, board)
    post = await create_post(session, board.initiative, board.user, name="Seen twice")
    body = {"post_ids": [post.id]}

    first = await client.post(
        reader.g("/posts/read"), headers=reader.headers, json=body
    )
    second = await client.post(
        reader.g("/posts/read"), headers=reader.headers, json=body
    )

    assert first.json()["marked"] == 1
    assert second.json()["marked"] == 0


async def test_reading_is_one_persons_business(
    client: AsyncClient, acting_user, board: Actor, session
):
    """A receipt says this reader saw it, and nothing about anybody else."""
    b = await _joins(acting_user, board)
    c = await _joins(acting_user, board)
    post = await create_post(session, board.initiative, board.user, name="Mine only")

    await client.post(
        b.g("/posts/read"), headers=b.headers, json={"post_ids": [post.id]}
    )

    theirs = await client.get(b.g("/posts/"), headers=b.headers)
    others = await client.get(c.g("/posts/"), headers=c.headers)
    assert [p["is_read"] for p in theirs.json()["items"]] == [True]
    assert [p["is_read"] for p in others.json()["items"]] == [False]


async def test_marking_unread_puts_it_back(
    client: AsyncClient, acting_user, board: Actor, session
):
    """Somebody ELSE's notice: there is no receipt on your own to take off, and
    a notice you wrote reads as read whatever you do to it."""
    reader = await _joins(acting_user, board)
    post = await create_post(session, board.initiative, board.user, name="Again please")
    await client.post(
        reader.g("/posts/read"), headers=reader.headers, json={"post_ids": [post.id]}
    )

    response = await client.delete(
        reader.g(f"/posts/{post.id}/read"), headers=reader.headers
    )
    assert response.status_code == 204

    listed = await client.get(reader.g("/posts/"), headers=reader.headers)
    assert [p["is_read"] for p in listed.json()["items"]] == [False]


async def test_marking_unread_twice_is_not_an_error(
    client: AsyncClient, board: Actor, session
):
    """Asking for a state a thing is already in is not a failure."""
    post = await create_post(session, board.initiative, board.user, name="Never read")

    response = await client.delete(
        board.g(f"/posts/{post.id}/read"), headers=board.headers
    )
    assert response.status_code == 204


async def test_the_unread_filter_shows_only_what_is_left(
    client: AsyncClient, acting_user, board: Actor, session
):
    reader = await _joins(acting_user, board)
    read = await create_post(
        session, board.initiative, board.user, name="Done with this"
    )
    await create_post(session, board.initiative, board.user, name="Still to read")
    await client.post(
        reader.g("/posts/read"), headers=reader.headers, json={"post_ids": [read.id]}
    )

    response = await client.get(
        reader.g("/posts/"), headers=reader.headers, params={"unread": "true"}
    )
    assert [p["name"] for p in response.json()["items"]] == ["Still to read"]
    assert response.json()["total_count"] == 1


async def test_a_reader_cannot_mark_a_notice_they_cannot_see(
    client: AsyncClient, acting_user, board: Actor, session
):
    """A receipt is only recorded for a notice the caller can see.

    The reader here is IN the initiative, so membership alone would admit
    them — which is the point: what may be marked read is what the board would
    have shown them, not what the schema allows them to name.
    """
    member = await _joins(acting_user, board)
    post = await create_post(session, board.initiative, board.user, name="Not theirs")
    await strip_non_owner_grants(session, post, board.user.id)

    response = await client.post(
        member.g("/posts/read"),
        headers=member.headers,
        json={"post_ids": [post.id]},
    )
    assert response.status_code == 200
    assert response.json()["marked"] == 0


async def test_a_draft_is_not_in_the_unread_list(
    client: AsyncClient, draft_scene: _DraftScene
):
    """Unread means "not read yet", not "does not exist yet" — a scheduled
    notice is nobody's to read, so it is not waiting for them either."""
    reader = draft_scene.reader

    response = await client.get(
        reader.g("/posts/"), headers=reader.headers, params={"unread": "true"}
    )
    assert response.json()["items"] == []


async def test_a_draft_cannot_be_marked_read(
    client: AsyncClient, draft_scene: _DraftScene
):
    """A notice nobody can read yet is not one anybody has read."""
    reader, draft = draft_scene.reader, draft_scene.draft

    response = await client.post(
        reader.g("/posts/read"), headers=reader.headers, json={"post_ids": [draft.id]}
    )
    assert response.json()["marked"] == 0


async def test_a_notice_counts_its_readers(
    client: AsyncClient, acting_user, board: Actor, session
):
    """Everyone who can see the notice can see whether it landed — that is the
    point of saying something out loud."""
    b = await _joins(acting_user, board)
    post = await create_post(session, board.initiative, board.user, name="Did it land")

    await client.post(
        b.g("/posts/read"), headers=b.headers, json={"post_ids": [post.id]}
    )

    listing = await client.get(board.g("/posts/"), headers=board.headers)
    assert [p["read_count"] for p in listing.json()["items"]] == [1]


async def test_the_roster_says_who_read_it_and_who_has_not(
    client: AsyncClient, acting_user, board: Actor, session
):
    reader = await _joins(acting_user, board)
    waiting = await _joins(acting_user, board)
    post = await create_post(session, board.initiative, board.user, name="Roster")
    await client.post(
        reader.g("/posts/read"), headers=reader.headers, json={"post_ids": [post.id]}
    )

    response = await client.get(
        board.g(f"/posts/{post.id}/reads"), headers=board.headers
    )
    assert response.status_code == 200
    body = response.json()

    assert [row["id"] for row in body["read"]] == [reader.user.id]
    assert body["read"][0]["read_at"] is not None
    assert [row["id"] for row in body["unread"]] == [waiting.user.id]


async def test_the_roster_waits_only_on_who_can_open_it(
    client: AsyncClient, acting_user, board: Actor, session
):
    """Somebody whose role keeps them off the board is not ignoring the
    notice."""
    await _joins(acting_user, board, initiative_role="member")
    post = await create_post(session, board.initiative, board.user, name="Roster")
    await grant_role_permission(
        session, board.initiative, Tool.post.view_permission, enabled=False
    )

    response = await client.get(
        board.g(f"/posts/{post.id}/reads"), headers=board.headers
    )

    assert response.status_code == 200
    assert response.json()["unread"] == []


async def test_the_roster_waits_only_on_who_it_was_shared_with(
    client: AsyncClient, acting_user, board: Actor
):
    """A board of a hundred where a notice went to one is not ninety-nine
    people ignoring it."""
    named = await _joins(acting_user, board)
    await _joins(acting_user, board)

    created = await client.post(
        board.g("/posts/"),
        headers=board.headers,
        json={
            "name": "Just for you",
            "initiative_id": board.initiative.id,
            "body": lexical_body("A word."),
            "grants": [{"user_id": named.user.id, "level": "read"}],
        },
    )
    post_id = created.json()["id"]

    body = (
        await client.get(board.g(f"/posts/{post_id}/reads"), headers=board.headers)
    ).json()
    assert [row["id"] for row in body["unread"]] == [named.user.id]


async def test_the_author_is_on_neither_list(
    client: AsyncClient, board: Actor, session
):
    """Writing a notice is not reading it, and they were not told about it
    either."""
    post = await create_post(session, board.initiative, board.user, name="Mine")

    body = (
        await client.get(board.g(f"/posts/{post.id}/reads"), headers=board.headers)
    ).json()
    assert body["read"] == []
    assert body["unread"] == []


async def test_a_notice_is_signed(client: AsyncClient, board: Actor, session):
    """A board shows who said it, the way a comment does — handle, picture and
    what they wear around it, carried with the row rather than fetched per
    card."""
    await create_post(session, board.initiative, board.user, name="Signed")

    listing = await client.get(board.g("/posts/"), headers=board.headers)
    author = listing.json()["items"][0]["author"]

    assert author["id"] == board.user.id
    assert author["username"] == board.user.username
    assert "profile_decorations" in author
    assert "presence" in author


async def test_writing_a_notice_is_not_reading_it(
    client: AsyncClient, board: Actor, session
):
    """An author's own notice is on their own board, so the card reports it
    read like any other. It must not count: the roster leaves them off the
    waiting side, and a count that included them would contradict it."""
    post = await create_post(
        session, board.initiative, board.user, name="Mine to write"
    )

    marked = await client.post(
        board.g("/posts/read"), headers=board.headers, json={"post_ids": [post.id]}
    )
    assert marked.json()["marked"] == 0

    listing = await client.get(board.g("/posts/"), headers=board.headers)
    assert listing.json()["items"][0]["read_count"] == 0


async def test_somebody_who_has_left_is_on_neither_side(
    client: AsyncClient, acting_user, board: Actor, session
):
    """Sharing changes after a notice goes up, and a receipt stays behind.

    Both sides of the roster answer against the audience as it is NOW, so a
    former recipient is off both — otherwise "Read 1, Unread 0" would describe
    somebody the notice is no longer for.
    """
    reader = await _joins(acting_user, board)
    post = await create_post(
        session, board.initiative, board.user, name="Shared, then not"
    )
    await client.post(
        reader.g("/posts/read"), headers=reader.headers, json={"post_ids": [post.id]}
    )

    # The sharing goes; the receipt does not.
    await strip_non_owner_grants(session, post, board.user.id)

    listing = await client.get(board.g("/posts/"), headers=board.headers)
    roster = (
        await client.get(board.g(f"/posts/{post.id}/reads"), headers=board.headers)
    ).json()

    assert listing.json()["items"][0]["read_count"] == 0
    assert roster["read"] == []
    assert roster["unread"] == []


async def test_a_guild_admin_can_mark_read_without_a_grant(
    client: AsyncClient, acting_user, session
):
    """A guild admin reaches every notice in their community without a grant
    row, so the board shows them one. Refusing the receipt would leave
    everything they read permanently unread."""
    author = await acting_user(guild_role=CommunityRole.member, initiative=True)
    admin = await _joins(acting_user, author, guild_role=CommunityRole.admin)
    await _posts_enabled(session, author.initiative)
    post = await create_post(
        session, author.initiative, author.user, name="Admin reads"
    )
    await strip_non_owner_grants(session, post, author.user.id)

    # The board shows it to them — the real request names its initiative,
    # which is the scope where a guild admin's authority answers.
    view = {"initiative_id": author.initiative.id}
    listing = await client.get(admin.g("/posts/"), headers=admin.headers, params=view)
    assert [p["id"] for p in listing.json()["items"]] == [post.id]

    # ...so marking it read has to work.
    marked = await client.post(
        admin.g("/posts/read"), headers=admin.headers, json={"post_ids": [post.id]}
    )
    assert marked.json()["marked"] == 1

    after = await client.get(admin.g("/posts/"), headers=admin.headers, params=view)
    assert [p["is_read"] for p in after.json()["items"]] == [True]
