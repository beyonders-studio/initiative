"""A library's realtime signals — a picture reaches a second window on its own.

End to end, like the board's: a real endpoint writes, the capture trigger logs
it, the room sink reads the log, and a socket in that initiative's room hears
about it. An item is read at its own address, so every change to one — adding,
retitling, retagging, removing — reports as the item, naming the library it is
in as its parent, which is what a wall re-reads.
"""

import io

from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import CommunityRole
from app.services.content_sockets import sockets
from app.testing.sockets import FakeWebSocket, settle, watch_events_bus
from app.services.tenant import room_sink
from app.testing import create_library, create_library_item, create_tag, png_bytes


async def _libraries_enabled(session: AsyncSession, initiative) -> None:
    initiative.libraries_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


class _Room:
    def __init__(self, guild_id: int, initiative_id: int, user_id: int = 1) -> None:
        self._guild_id = guild_id
        self._initiative_id = initiative_id
        self._user_id = user_id
        self.socket = FakeWebSocket()

    async def __aenter__(self) -> "_Room":
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

    def changes(self, resource_type: str = "libraries") -> list[dict]:
        return [
            change
            for frame in self.socket.sent
            for change in frame.get("changes", [])
            if change["resource"]["type"] == resource_type
        ]


async def test_a_picture_arriving_tells_the_room_about_itself_and_its_library(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user)

    async with _Room(a.guild.id, a.initiative.id) as room:
        response = await client.post(
            a.g(f"/libraries/{library.id}/items"),
            headers=a.headers,
            files={"file": ("shot.png", io.BytesIO(png_bytes()), "image/png")},
        )
        assert response.status_code == 201, response.text
        await room.catch_up()

        changes = room.changes("library_items")
        assert changes, "the room heard nothing"
        item_id = response.json()["id"]
        # The item reports as itself, and names its library as the parent a
        # wall re-reads.
        assert all(
            c["resource"] == {"type": "library_items", "id": item_id} for c in changes
        )
        assert all(
            {"type": "libraries", "id": library.id} in c["parents"] for c in changes
        )


async def test_retagging_and_removing_a_picture_each_tell_the_room(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user)
    item = await create_library_item(session, library, a.user, write_blob=False)
    tag = await create_tag(session, a.guild, name="picked")

    async with _Room(a.guild.id, a.initiative.id) as room:
        retagged = await client.patch(
            a.g(f"/library-items/{item.id}"),
            headers=a.headers,
            json={"tag_ids": [tag.id], "title": "Hero"},
        )
        assert retagged.status_code == 200, retagged.text
        await room.catch_up()
        assert room.changes("library_items"), "retagging said nothing"
        heard = len(room.changes("library_items"))

        removed = await client.delete(
            a.g(f"/library-items/{item.id}"), headers=a.headers
        )
        assert removed.status_code == 204
        await room.catch_up()
        assert len(room.changes("library_items")) > heard, "removing said nothing"
        assert all(
            c["resource"] == {"type": "library_items", "id": item.id}
            and {"type": "libraries", "id": library.id} in c["parents"]
            for c in room.changes("library_items")
        )


async def test_a_comment_on_a_library_names_it_as_the_parent(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _libraries_enabled(session, a.initiative)
    library = await create_library(session, a.initiative, a.user)

    async with _Room(a.guild.id, a.initiative.id) as room:
        response = await client.post(
            a.g("/comments/"),
            headers=a.headers,
            json={"library_id": library.id, "content": "The blue one."},
        )
        assert response.status_code == 201, response.text
        await room.catch_up()

        comments = room.changes("comments")
        assert comments, "the room heard no comment"
        assert all(
            {"type": "libraries", "id": library.id} in c["parents"] for c in comments
        )
