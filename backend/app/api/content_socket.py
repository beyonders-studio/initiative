"""How a guild content socket is opened, held and closed.

Every guild socket — the events bus, a tool's change signal, a collaboration
room — enters the same way, here:

1. accept, then wait at most ``AUTH_TIMEOUT_SECONDS`` for the first frame, which
   carries the credential (``MSG_AUTH`` + JSON, or JSON text; a web session may
   send no token and be read from its cookie);
2. authenticate it (``authenticate_ws_token``) on a short-lived session;
3. enter the guild through ``establish_guild_access``, as REST does;
4. ask the channel's authorizer which rooms the socket may be in — the same
   function every re-check calls (:mod:`app.services.content_sockets`);
5. register it, and release the session before the socket's long life begins.

Any refusal closes with ``WS_1008_POLICY_VIOLATION``. What a channel adds sits
in the two hooks: ``prepare`` runs on the admitting session before the socket
is registered, ``joined`` right after.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from time import monotonic
from typing import Any

from fastapi import HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import selectinload, undefer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import resource_access
from app.api.deps import GuildAccessError, establish_guild_access
from app.core.errors import CodedError
from app.core.identify import presented_credential
from app.core.tools import Tool
from app.db.cohorts import request_sessionmaker
from app.db.session import require_guild_context
from app.models.platform.user import User
from app.models.tenant._mixins import tool_models
from app.services.content_sockets import (
    Authorizer,
    Credential,
    RoomKey,
    Subscriber,
    Wire,
    resource_room,
    sockets,
)
from app.services.platform.ws_auth import authenticate_ws_token

logger = logging.getLogger(__name__)

#: The first binary frame's type byte. The token rides in a frame rather than
#: the URL so it never lands in an access log.
MSG_AUTH = 5

#: How long an accepted socket may wait before it says who it is.
AUTH_TIMEOUT_SECONDS = 10.0

#: How long a socket may go without the server saying anything before it says
#: that. The client reads silence past a couple of these as the socket being
#: gone, which is how a half-open connection is noticed. Measured from what the
#: server last sent, not what it last received: a client typing alone in a
#: document sends constantly and is sent nothing back.
HEARTBEAT_SECONDS = 30.0

#: The beat. It carries no change, and a client does nothing with it.
HEARTBEAT_FRAME = {"heartbeat": True}


async def read_auth_frame(
    websocket: WebSocket,
) -> tuple[str, Mapping[str, Any]] | None:
    """The credential in an accepted socket's first frame, and the rest of it.

    ``None`` once the socket has been closed: no frame in time, a frame that
    is not a credential, or no token and no session cookie.
    """
    try:
        frame = await asyncio.wait_for(websocket.receive(), AUTH_TIMEOUT_SECONDS)
    except TimeoutError:
        await _refuse(websocket)
        return None
    except WebSocketDisconnect:
        return None
    if frame.get("type") == "websocket.disconnect":
        return None
    raw: bytes | str | None
    data = frame.get("bytes")
    if data is not None:
        raw = data[1:] if len(data) > 1 and data[0] == MSG_AUTH else None
    else:
        raw = frame.get("text")
    try:
        payload = json.loads(raw) if raw else None
    except json.JSONDecodeError, UnicodeDecodeError:
        payload = None
    if not isinstance(payload, dict):
        await _refuse(websocket)
        return None
    token = payload.get("token")
    if not token:
        # The session cookie, where it is what the handshake presents.
        presented = presented_credential(websocket)
        if presented is not None and not presented.bearer:
            token = presented.token
    if not token or not isinstance(token, str):
        await _refuse(websocket)
        return None
    return token, payload


async def admit(
    websocket: WebSocket,
    guild_id: int,
    *,
    wire: Wire,
    authorize: Authorizer,
    presence: bool = False,
    meta: dict[str, Any] | None = None,
    prepare: Callable[[AsyncSession, User], Awaitable[None]] | None = None,
    joined: Callable[[AsyncSession, Subscriber], Awaitable[None]] | None = None,
) -> Subscriber | None:
    """Accept, authenticate, enter the guild, authorize and register a socket.

    Returns the registered socket, or ``None`` once it has been refused.
    """
    await websocket.accept()
    first = await read_auth_frame(websocket)
    if first is None:
        return None
    token, payload = first
    async with request_sessionmaker(guild_id)() as session:
        # Taken before the account is read, so it is never later than the
        # presence that read comes back with.
        known_at = monotonic()
        user = await authenticate_ws_token(token, session)
        if user is None:
            await _refuse(websocket)
            return None
        try:
            await establish_guild_access(session, user, guild_id)
        except GuildAccessError:
            await _refuse(websocket)
            return None
        rooms = await authorize(session, user)
        if not rooms:
            await _refuse(websocket)
            return None
        if prepare is not None:
            await prepare(session, user)
        sub = Subscriber(
            websocket=websocket,
            user=user,
            guild_id=guild_id,
            wire=wire,
            authorize=authorize,
            credential=Credential.captured(),
            rooms=rooms,
            presence=presence,
            meta=meta if meta is not None else {},
            # Everything the first frame said but the credential itself.
            first_frame={k: v for k, v in payload.items() if k != "token"},
        )
        sockets.join(sub, chosen_presence=user.presence, presence_known_at=known_at)
        if joined is not None:
            try:
                await joined(session, sub)
            except BaseException:
                sockets.leave(websocket)
                raise
    return sub


async def hold_open(
    sub: Subscriber, on_bytes: Callable[[bytes], None] | None = None
) -> None:
    """Keep a socket open until it closes, beating when the server is quiet.

    Every socket beats the same way — a JSON ``HEARTBEAT_FRAME`` — so one
    client-side check notices a connection that has stopped carrying. Binary
    frames the client sends go to ``on_bytes``; a channel that takes none
    passes nothing, and awaiting the client is then only what surfaces the
    close.
    """
    try:
        while True:
            quiet_for = monotonic() - sub.last_sent_at
            if quiet_for >= HEARTBEAT_SECONDS:
                sub.send_json(HEARTBEAT_FRAME)
                # Set here too: a socket already dropped from the register
                # queues nothing, and must still wait out the next beat.
                sub.last_sent_at = monotonic()
                continue
            try:
                frame = await asyncio.wait_for(
                    sub.websocket.receive(), HEARTBEAT_SECONDS - quiet_for
                )
            except TimeoutError:
                continue
            if frame.get("type") == "websocket.disconnect":
                break
            data = frame.get("bytes")
            if on_bytes is not None and data:
                on_bytes(data)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception(
            "content socket failed for user %s in guild %s", sub.user_id, sub.guild_id
        )
        with contextlib.suppress(Exception):
            await sub.websocket.close(code=status.WS_1011_INTERNAL_ERROR)
    finally:
        # Unconditional, cancellation included: a register entry left behind
        # would keep a writer and a room seat for a socket nobody holds.
        (sub.register or sockets).leave(sub.websocket)


def tool_room(guild_id: int, tool: Tool, resource_id: int) -> RoomKey:
    return resource_room(guild_id, tool.value, resource_id)


def tool_authorizer(guild_id: int, tool: Tool, resource_id: int) -> Authorizer:
    """May this reader watch one tool row: the row under RLS, the tool's switch
    on its initiative, and the sharing — ``resource_access.authorize``, the
    check every REST read of the row makes."""
    model = tool_models()[tool.plural]

    async def authorize(session: AsyncSession, user: User) -> frozenset[RoomKey] | None:
        row = (
            await session.exec(
                select(model)
                .where(model.id == resource_id)  # type: ignore[attr-defined]
                .options(
                    selectinload(model.initiative),  # type: ignore[attr-defined]
                    undefer(model.actions),  # type: ignore[attr-defined]
                )
            )
        ).one_or_none()
        if row is None:
            return None
        try:
            resource_access.authorize(
                tool, row, user, context=require_guild_context(session)
            )
        except HTTPException, CodedError:
            return None
        return frozenset({tool_room(guild_id, tool, resource_id)})

    return authorize


async def serve_tool_stream(
    websocket: WebSocket, guild_id: int, tool: Tool, resource_id: int
) -> None:
    """A tool row's change signal: ``{type, id, timestamp}`` frames, and a beat.

    The frames never carry the row. The client refetches it through REST.
    """
    sub = await admit(
        websocket,
        guild_id,
        wire=Wire.json,
        authorize=tool_authorizer(guild_id, tool, resource_id),
    )
    if sub is not None:
        await hold_open(sub)


async def _refuse(websocket: WebSocket) -> None:
    with contextlib.suppress(Exception):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
