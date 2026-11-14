"""The board's realtime signals — a notice reaches a second window on its own.

End to end, and deliberately so: a real endpoint writes, the capture trigger
logs it, the room sink reads the log, and a socket in that initiative's room
hears about it. Nothing in the endpoints announces anything, so a signal that
is missing, mis-scoped or carrying content fails here rather than in a mock.

Publication is the case worth stating twice: a draft says nothing, and the
moment it goes up — posted outright, or stamped later by the scheduler — is the
moment the room hears about it.
"""

from datetime import UTC, datetime, timedelta
from typing import Self

from httpx2 import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import cohorts
from app.models.platform.guild import CommunityRole
from app.models.tenant.post import Post
from app.services.content_sockets import sockets
from app.services.tenant import room_sink
from app.services.tenant.post_publication import publish_due_posts
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_post,
    create_user,
    lexical_body,
    route_session_to_guild,
    route_system,
)
from app.testing.sockets import FakeWebSocket, settle, watch_events_bus


async def _posts_enabled(session: AsyncSession, initiative) -> None:
    initiative.posts_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


class _Room:
    """A socket joined to one initiative's room, reading the log as it goes.

    Entering marks where the change log is, the way a freshly connected socket
    is: whoever just arrived fetched as they mounted, so nothing before that is
    theirs to hear. ``catch_up`` is the sweep the sink runs on a timer, standing
    in for the notification the capture raises on commit — both read the same
    rows, and neither is allowed to be the only one that works.
    """

    def __init__(self, guild_id: int, initiative_id: int, user_id: int = 1) -> None:
        self._guild_id = guild_id
        self._initiative_id = initiative_id
        self._user_id = user_id
        self.socket = FakeWebSocket()

    async def __aenter__(self) -> Self:
        watch_events_bus(
            self._guild_id, [self._initiative_id], self.socket, user_id=self._user_id
        )
        await room_sink.process_room_sweep()
        return self

    async def __aexit__(self, *exc) -> None:
        sockets.leave(self.socket)  # type: ignore[arg-type]
        room_sink._delivered.pop(self._guild_id, None)

    async def catch_up(self) -> None:
        await room_sink.process_room_sweep()
        await settle()

    def changes(self, resource_type: str = "posts") -> list[dict]:
        return [
            change
            for frame in self.socket.sent
            for change in frame.get("changes", [])
            if change["resource"]["type"] == resource_type
        ]

    def actions(self, resource_type: str = "posts") -> list[str]:
        return [change["action"] for change in self.changes(resource_type)]


async def test_posting_a_notice_tells_the_room(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)

    async with _Room(a.guild.id, a.initiative.id) as room:
        response = await client.post(
            a.g("/posts/"),
            headers=a.headers,
            json={
                "initiative_id": a.initiative.id,
                "name": "Session moved",
                "body": lexical_body("We are on Thursday now."),
            },
        )
        assert response.status_code == 201
        post_id = response.json()["id"]
        await room.catch_up()

        changes = room.changes()
        # The notice arriving, and the owner's share of it landing beside it —
        # both name the notice, which is all a board needs to read it again.
        assert "created" in room.actions()
        assert all(c["resource"] == {"type": "posts", "id": post_id} for c in changes)
        # A notice sits directly in its initiative, so it names no parents.
        assert all(c["parents"] == [] for c in changes)
        # Identifiers, an action and the columns it changed. The notice itself
        # is not on the bus.
        assert all(
            set(c) == {"resource", "parents", "initiative_id", "action", "changed"}
            for c in changes
        )


async def test_a_scheduled_draft_says_nothing_until_it_goes_up(
    client: AsyncClient, acting_user, session
):
    """A draft is nobody else's business, so no board is told to refetch."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    later = datetime.now(UTC) + timedelta(days=1)

    async with _Room(a.guild.id, a.initiative.id) as room:
        response = await client.post(
            a.g("/posts/"),
            headers=a.headers,
            json={
                "initiative_id": a.initiative.id,
                "name": "Not yet",
                "body": lexical_body("Draft."),
                "scheduled_for": later.isoformat(),
            },
        )
        assert response.status_code == 201
        await room.catch_up()
        assert room.changes() == []


async def test_publishing_a_draft_now_tells_the_room(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    later = datetime.now(UTC) + timedelta(days=1)
    created = await client.post(
        a.g("/posts/"),
        headers=a.headers,
        json={
            "initiative_id": a.initiative.id,
            "name": "Held back",
            "body": lexical_body("Draft."),
            "scheduled_for": later.isoformat(),
        },
    )
    post_id = created.json()["id"]

    async with _Room(a.guild.id, a.initiative.id) as room:
        # Clearing the schedule is how "post it now" is expressed.
        response = await client.patch(
            a.g(f"/posts/{post_id}"),
            headers=a.headers,
            json={"scheduled_for": None},
        )
        assert response.status_code == 200
        await room.catch_up()

        changes = room.changes()
        assert len(changes) == 1
        # Coming out of quiet is the notice arriving, as far as a board is
        # concerned: it was never told about the draft.
        assert changes[0]["action"] == "created"
        assert changes[0]["resource"] == {"type": "posts", "id": post_id}


async def test_editing_pinning_and_deleting_each_tell_the_room(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)

    async with _Room(a.guild.id, a.initiative.id) as room:
        edited = await client.patch(
            a.g(f"/posts/{post.id}"), headers=a.headers, json={"name": "Renamed"}
        )
        assert edited.status_code == 200
        await room.catch_up()

        pinned = await client.put(
            a.g(f"/posts/{post.id}/pin"), headers=a.headers, json={"pinned": True}
        )
        assert pinned.status_code == 200
        await room.catch_up()

        removed = await client.delete(a.g(f"/posts/{post.id}"), headers=a.headers)
        assert removed.status_code == 204
        await room.catch_up()

    # A soft delete reaches the board as a delete, not as an update carrying a
    # timestamp a reader would have to interpret.
    assert room.actions() == ["updated", "updated", "deleted"]


async def test_answering_a_poll_tells_the_room_the_tallies_moved(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    written = await client.put(
        a.g(f"/posts/{post.id}/poll"),
        headers=a.headers,
        json={"question": "Thursday?", "options": [{"text": "Yes"}, {"text": "No"}]},
    )
    assert written.status_code == 200
    option_id = written.json()["poll"]["options"][0]["id"]

    async with _Room(a.guild.id, a.initiative.id) as room:
        voted = await client.put(
            a.g(f"/posts/{post.id}/poll/vote"),
            headers=a.headers,
            json={"option_ids": [option_id]},
        )
        assert voted.status_code == 200
        await room.catch_up()

        retracted = await client.delete(
            a.g(f"/posts/{post.id}/poll/vote"), headers=a.headers
        )
        assert retracted.status_code == 200
        await room.catch_up()

    # Both gestures reach the board as the notice moving, which is what a
    # reader re-reads to see the tallies. Neither says who answered.
    assert room.actions() == ["updated", "updated"]


async def test_a_notice_never_reaches_another_initiatives_room(
    client: AsyncClient, acting_user, session
):
    """The room key is (guild, initiative): a board next door hears nothing.

    Watched by somebody who is in neither initiative, deliberately. A socket is
    also put into the rooms of every initiative its own user belongs to, as the
    roster moves under it (``room_sink._open_new_rooms``) — so an author
    watching their own other board is told about their own notice, correctly,
    and is the wrong person to ask this question of.
    """
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    elsewhere = await create_initiative(session, a.guild, a.user)
    outsider = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

    async with _Room(a.guild.id, elsewhere.id, user_id=outsider.user.id) as room:
        response = await client.post(
            a.g("/posts/"),
            headers=a.headers,
            json={
                "initiative_id": a.initiative.id,
                "name": "Ours only",
                "body": lexical_body("Not yours."),
            },
        )
        assert response.status_code == 201
        await room.catch_up()
        assert room.changes() == []


async def test_the_scheduler_tells_the_room_when_a_draft_comes_due(
    session: AsyncSession,
):
    """The other way a notice goes up: no request, same signal."""
    author = await create_user(session)
    guild = await create_guild(session, creator=author)
    reader = await create_user(session)
    await create_guild_membership(session, user=reader, guild=guild)
    initiative = await create_initiative(session, guild, author)
    await create_initiative_member(session, initiative, reader)
    await _posts_enabled(session, initiative)

    post = await create_post(session, initiative, author)
    post.published_at = None
    post.scheduled_for = datetime.now(UTC) - timedelta(minutes=1)
    session.add(post)
    await session.commit()
    post_id, guild_id, initiative_id = post.id, guild.id, initiative.id

    async with _Room(guild_id, initiative_id) as room:
        # As the sweep runs: a system session of its own, routed into the
        # community with nobody behind it.
        async with cohorts.system_session(guild_id) as system:
            await route_system(system, guild_id=guild_id)
            assert await publish_due_posts(system, now=datetime.now(UTC)) == [post_id]
            await system.commit()
        await room.catch_up()

        changes = room.changes()
        assert len(changes) == 1
        assert changes[0]["action"] == "created"
        assert changes[0]["resource"] == {"type": "posts", "id": post_id}

    await route_session_to_guild(session, guild_id)
    published = (await session.exec(select(Post).where(Post.id == post_id))).one()
    assert published.published_at is not None
