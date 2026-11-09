"""
Live editing of a collaborative body (a file, a wiki page).

The socket carries the Yjs sync protocol, updates and awareness; entry and
continuous re-authorization are ``app.api.content_socket``'s. The POST beside
each socket hands over edits a tab made while its socket was closed.
"""

# NOT ``from __future__ import annotations``: the handlers are built per kind
# with ``Annotated[int, Path(alias=...)]`` closing over a local, and stringized
# annotations re-evaluate it where that local is out of scope.

import json
import logging
from typing import Annotated

from fastapi import (
    APIRouter,
    HTTPException,
    Path,
    WebSocket,
    status,
)
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import resource_access
from app.api.content_socket import admit, hold_open
from app.api.deps import (
    CommunityIdPath,
    CurrentUser,
    GuildAccessError,
    SessionDep,
    establish_guild_access,
    raise_for_guild_access,
)
from app.core.body_limit import max_document_body
from app.core.errors import CodedError
from app.core.messages import FileMessages
from app.core.request_audit import record_privileged_edit
from app.core.user_display import display_name, handle_of
from app.db.session import require_guild_context
from app.models.platform.user import User
from app.models.platform.user_profile_view import MemberProfile
from app.schemas.tenant.collaboration import CollaborationHandover
from app.services import permissions as permissions_service
from app.services.content_sockets import RoomKey, Wire, resource_room, sockets
from app.services.tenant.collaboration import (
    MSG_UPDATE,
    broadcast_awareness,
    collaboration_manager,
    room_roster,
    user_has_connection,
)
from app.services.tenant.collaborative_resources import (
    Collaborating,
    CollaborativeResource,
    registered_types,
    resource_for,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Message types for the collaboration protocol
MSG_SYNC_STEP1 = 0  # Client requests current state
MSG_SYNC_STEP2 = 1  # Server sends current state
# MSG_UPDATE = 2, an incremental Yjs update, is the service's: it sends them too.
MSG_AWARENESS = 3  # Join / leave / roster, server to client (JSON)
MSG_AWARENESS_BINARY = 4  # y-protocols awareness (binary, relayed as-is)
# 6 carried a tab's rendering of the body. The server renders every body now,
# so a frame of it from an older tab falls through unread.


class _Editing:
    """Who may be in one body's room, asked at join and at every re-check.

    The body and the row whose sharing governs it are loaded under RLS (the
    initiative boundary), then ``resource_access.authorize`` asks what every
    REST read asks: the tool's switch on its initiative, and the sharing. The
    write level found at join is kept, and a writer who has lost it is closed
    rather than quietly downgraded — they reconnect as the reader they now are.
    A community turning read-only caps the level the same way.
    """

    def __init__(
        self,
        guild_id: int,
        spec: CollaborativeResource,
        resource_id: int,
    ) -> None:
        self.guild_id = guild_id
        self.spec = spec
        self.resource_id = resource_id
        self.resolved: Collaborating | None = None
        self.can_write: bool | None = None

    async def __call__(
        self, session: AsyncSession, user: User
    ) -> frozenset[RoomKey] | None:
        resolved = await self.spec.load(session, self.resource_id, self.guild_id)
        if resolved is None:
            return None
        context = require_guild_context(session)
        try:
            resource_access.authorize(
                self.spec.tool, resolved.governing, user, context=context
            )
        except HTTPException, CodedError:
            return None
        writes = permissions_service.allows(
            resolved.governing, permissions_service.Action.edit
        )
        if self.can_write is None:
            self.resolved = resolved
            self.can_write = writes
        elif self.can_write and not writes:
            return None
        # The body's room, and the room of the row whose sharing governs it —
        # the same room for a file, the wiki's for a page — so a change
        # to that sharing re-checks this socket at once.
        return frozenset(
            {
                resource_room(self.guild_id, self.spec.resource_type, self.resource_id),
                resource_room(
                    self.guild_id, self.spec.tool.value, resolved.governing.id
                ),
            }
        )


async def _collaborate(
    websocket: WebSocket,
    guild_id: int,
    spec: CollaborativeResource,
    resource_id: int,
):
    """Live editing of one body over Yjs.

    Entry is ``app.api.content_socket.admit``: the first frame is ``MSG_AUTH``
    with ``{token}``, and the guild comes from the ``/c/{community_id}`` path. Then:
    the server asks for what the client has (``SYNC_STEP1``) and sends the
    roster; the client answers and sends its own ``SYNC_STEP1``; after that,
    ``UPDATE`` frames are applied and relayed, and binary awareness is relayed
    as-is. Each frame is one type byte and its payload.

    Database sessions are opened only for the join and the final write, never
    held for the socket's life.
    """
    room_key = resource_room(guild_id, spec.resource_type, resource_id)
    editing = _Editing(guild_id, spec, resource_id)
    room = None
    # Filled before the socket is registered, so a roster read in between
    # never shows this connection without its name.
    meta: dict = {}

    async def open_room(session: AsyncSession, user: User) -> None:
        nonlocal room
        # Named as the rest of this guild names them, not from the account.
        member = await session.get(MemberProfile, user.id)
        meta.update(
            {
                "name": display_name(member, fallback=handle_of(user)),
                "can_write": bool(editing.can_write),
                "avatar_url": user.avatar_url,
            }
        )
        room = await collaboration_manager.get_or_create_room(
            guild_id, spec.resource_type, resource_id, session
        )
        # Held until the socket is registered, so the room is not read as idle
        # and retired in the gap between the two.
        room.hold()

    try:
        sub = await admit(
            websocket,
            guild_id,
            wire=Wire.bytes,
            authorize=editing,
            prepare=open_room,
            meta=meta,
        )
    finally:
        if room is not None:
            room.release()
    if sub is None or room is None or editing.resolved is None:
        return

    user = sub.user
    can_write = bool(editing.can_write)
    collaborator_name = meta["name"]
    # One line per session says they edited it; the rest is keystrokes.
    edit_recorded = False

    try:
        # Ask what this connection has that the room does not. A client that
        # reconnects holding work the room never saw — because the room was
        # rebuilt from the row while it was away — can only hand it over if it
        # is asked. It answers with SYNC_STEP2, and sends its own SYNC_STEP1
        # for the other direction, so one connect settles both ways.
        sub.send_bytes(bytes([MSG_SYNC_STEP1]) + room.state_vector())
        sub.send_bytes(
            bytes([MSG_AWARENESS])
            + json.dumps(
                {
                    "type": "collaborators",
                    "data": room_roster(guild_id, spec.resource_type, resource_id),
                }
            ).encode()
        )
        broadcast_awareness(
            guild_id,
            spec.resource_type,
            resource_id,
            {
                "type": "join",
                "user": {
                    "user_id": user.id,
                    "name": collaborator_name,
                    "avatar_url": user.avatar_url,
                },
            },
            exclude=websocket,
        )

        def on_bytes(data: bytes) -> None:
            nonlocal edit_recorded
            msg_type = data[0]
            payload = data[1:]

            if msg_type == MSG_SYNC_STEP1:
                # The client's state vector: send only what it is missing.
                state = room.get_state_diff(payload) if payload else room.get_state()
                sub.send_bytes(bytes([MSG_SYNC_STEP2]) + state)

            elif msg_type in (MSG_UPDATE, MSG_SYNC_STEP2):
                # An edit, or the answer to the room's opening SYNC_STEP1 —
                # both are Yjs updates and both are writes, so both need the
                # write level. A reader answering the handshake is still a
                # reader.
                if not can_write:
                    logger.warning(
                        "Collaboration: read-only user %s tried to send an update "
                        "to %s %s in guild %s",
                        user.id,
                        spec.resource_type,
                        resource_id,
                        guild_id,
                    )
                    return
                if not payload:
                    return

                try:
                    room.apply_update(payload, user_id=user.id)
                    if msg_type == MSG_UPDATE and not edit_recorded:
                        # Once per session, and only for an update: a
                        # SYNC_STEP2 is the client answering the room's
                        # opening handshake, which is not somebody typing.
                        edit_recorded = record_privileged_edit(
                            guild_id=guild_id,
                            resource_type=spec.resource_type,
                            resource_id=resource_id,
                            actor_user_id=user.id,
                        )
                    # Relayed under MSG_UPDATE whichever it arrived as: to every
                    # other connection this is simply state they do not have.
                    sockets.emit_bytes(
                        room_key, bytes([MSG_UPDATE]) + payload, exclude=websocket
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to apply Yjs update to %s %s in guild %s (%s)",
                        spec.resource_type,
                        resource_id,
                        guild_id,
                        type(e).__name__,
                    )

            elif msg_type == MSG_AWARENESS_BINARY:
                # y-protocols awareness update - relay as-is to other clients
                sockets.emit_bytes(
                    room_key, bytes([MSG_AWARENESS_BINARY]) + payload, exclude=websocket
                )

        await hold_open(sub, on_bytes=on_bytes)
    except Exception as e:
        logger.error(
            "Collaboration error for user %s on %s %s in guild %s (%s)",
            user.id,
            spec.resource_type,
            resource_id,
            guild_id,
            type(e).__name__,
        )
    finally:
        # Idempotent if a re-check already closed it.
        sockets.leave(websocket)

        # Tell the rest of the room only when this was the account's last
        # connection: the others keep a roster of people, and one of somebody's
        # two tabs closing does not take them out of the file.
        if not user_has_connection(guild_id, spec.resource_type, resource_id, user.id):
            broadcast_awareness(
                guild_id,
                spec.resource_type,
                resource_id,
                {"type": "leave", "user_id": user.id},
                exclude=websocket,
            )

        # Save what this session added and retire the room, once nothing is
        # connected to it — another tab of the same account is another
        # connection, and keeps it.
        await collaboration_manager.leave(guild_id, spec.resource_type, resource_id)


async def _hand_over(
    session: AsyncSession,
    user: User,
    guild_id: int,
    spec: CollaborativeResource,
    resource_id: int,
    handover: CollaborationHandover,
) -> None:
    """Hand a leaving tab's unsent edits to the body's room.

    Called as a page unloads with its socket already gone, so what the tab did
    offline is not lost with it. The edits go through the room — merged into
    whatever the room holds, live or loaded for the purpose — and are saved the
    way the room always saves, with the content rendered from the merged state.

    Authenticates as every other write does (the session cookie on web, the
    Authorization header on native), and is admitted exactly as the socket is,
    at the write level.
    """
    try:
        await establish_guild_access(session, user, guild_id)
    except GuildAccessError as exc:
        raise_for_guild_access(exc)
    editing = _Editing(guild_id, spec, resource_id)
    if not await editing(session, user) or editing.resolved is None:
        raise spec.tool.not_found()
    if not editing.can_write:
        raise spec.tool.write_required()

    room = await collaboration_manager.get_or_create_room(
        guild_id, spec.resource_type, resource_id, session
    )
    room.hold()
    try:
        try:
            room.apply_update(handover.update, user_id=user.id)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=FileMessages.COLLABORATION_UPDATE_INVALID,
            ) from None
        sockets.emit_bytes(
            resource_room(guild_id, spec.resource_type, resource_id),
            bytes([MSG_UPDATE]) + handover.update,
        )
        record_privileged_edit(
            guild_id=guild_id,
            resource_type=spec.resource_type,
            resource_id=resource_id,
            actor_user_id=user.id,
        )
    finally:
        room.release()
        if room.is_empty():
            await collaboration_manager.leave(guild_id, spec.resource_type, resource_id)


def _mount(spec: CollaborativeResource) -> None:
    """Mount one kind's socket and its handover at
    ``/<kind plural>/{<id param>}/collaborate``."""
    id_param = spec.path_param
    resource_id_param = Annotated[
        int, Path(alias=id_param, title=id_param.replace("_", " ").title())
    ]
    path = f"/{spec.route_segment}/{{{id_param}}}/collaborate"
    # What the body is called: ``file_id`` names a file, ``page_id`` a page.
    name = id_param.removesuffix("_id").replace("_", " ")

    async def collaborate(
        websocket: WebSocket,
        guild_id: CommunityIdPath,
        resource_id: resource_id_param,
    ):
        await _collaborate(websocket, guild_id, spec, resource_id)

    @max_document_body
    async def hand_over(
        guild_id: CommunityIdPath,
        resource_id: resource_id_param,
        handover: CollaborationHandover,
        session: SessionDep,
        user: CurrentUser,
    ) -> None:
        await _hand_over(session, user, guild_id, spec, resource_id, handover)

    router.add_api_websocket_route(
        path, collaborate, name=f"websocket_collaborate_{spec.resource_type}"
    )
    router.add_api_route(
        path,
        hand_over,
        methods=["POST"],
        status_code=status.HTTP_204_NO_CONTENT,
        name=f"hand_over_{spec.resource_type}_edits",
        description=(
            f"Merge edits a tab made while its socket was closed into the {name}."
        ),
    )


for _kind in registered_types():
    _mount(resource_for(_kind))
