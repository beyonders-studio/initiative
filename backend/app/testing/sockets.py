"""Stand-ins for a socket held open on the register.

A test that watches what the events bus or an account's own socket is sent
seats a fake socket in the process's register
(``app.services.content_sockets.sockets``) exactly as the handshake would, and
reads the frames its writer delivered.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from types import SimpleNamespace

from app.models.platform.user import Presence
from app.services.content_sockets import (
    Credential,
    Subscriber,
    Wire,
    account_authorizer,
    account_room,
    guild_room,
    initiative_room,
    sockets,
)


class FakeWebSocket:
    """Records the frames it was sent and the close code it received."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.sent_bytes: list[bytes] = []
        self.closed: int | None = None

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)

    async def send_bytes(self, payload: bytes) -> None:
        self.sent_bytes.append(payload)

    async def close(self, code: int | None = None) -> None:
        self.closed = code


async def settle() -> None:
    """Let the register's writer tasks deliver what was queued."""
    for _ in range(10):
        await asyncio.sleep(0)


def watch_events_bus(
    guild_id: int,
    initiative_ids: Iterable[int],
    websocket: FakeWebSocket,
    *,
    user_id: int,
) -> Subscriber:
    """Seat ``websocket`` on one guild's events bus, in its guild room and the
    given initiative rooms, counting ``user_id`` present.

    A re-check recomputes the rooms the way the endpoint's own authorizer does.
    """
    from app.api.v1.tenant_endpoints.events import _rooms_for

    sub = Subscriber(
        websocket=websocket,  # type: ignore[arg-type]
        user=SimpleNamespace(id=user_id),  # type: ignore[arg-type]
        guild_id=guild_id,
        wire=Wire.json,
        authorize=_rooms_for(guild_id),
        credential=Credential(),
        rooms=frozenset(
            {
                guild_room(guild_id),
                *(initiative_room(guild_id, i) for i in initiative_ids),
            }
        ),
        presence=True,
    )
    sockets.join(sub)
    return sub


def open_account_socket(
    user_id: int,
    websocket: FakeWebSocket | None = None,
    *,
    chosen_presence: Presence = Presence.online,
) -> FakeWebSocket:
    """Seat a notification-stream socket for ``user_id`` in its account room,
    counting the account online, as the stream's handshake does."""
    websocket = websocket or FakeWebSocket()
    sockets.join(
        Subscriber(
            websocket=websocket,  # type: ignore[arg-type]
            user=SimpleNamespace(id=user_id),  # type: ignore[arg-type]
            guild_id=None,
            wire=Wire.json,
            authorize=account_authorizer,
            credential=Credential(),
            rooms=frozenset({account_room(user_id)}),
            presence=True,
        ),
        chosen_presence=chosen_presence,
    )
    return websocket
