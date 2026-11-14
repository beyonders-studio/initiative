import logging

from fastapi import APIRouter, WebSocket
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.content_socket import admit, hold_open
from app.api.deps import CommunityIdPath
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative
from app.services.content_sockets import (
    Authorizer,
    RoomKey,
    Subscriber,
    Wire,
    guild_room,
    initiative_room,
)
from app.services.membership import initiative_scope_clause
from app.services.tenant.room_sink import EVERYTHING, missed_while_away

router = APIRouter()
logger = logging.getLogger(__name__)


def _rooms_for(guild_id: int) -> Authorizer:
    """The events-bus rooms one reader may be in: the guild's own, and one per
    initiative whose content they could read over REST.

    ``initiative_scope_clause`` → ``initiative_access`` is the function RLS
    uses, so the rooms are member initiatives plus every initiative for a guild
    admin or a grant holder. Asked at connect and on every re-check, and the
    answer replaces the socket's rooms: somebody added to an initiative is
    given its room, and somebody removed loses it.
    """

    async def authorize(session: AsyncSession, user: User) -> frozenset[RoomKey] | None:
        rows = await session.exec(
            select(Initiative.id).where(initiative_scope_clause(user.id, Initiative.id))
        )
        return frozenset(
            {guild_room(guild_id), *(initiative_room(guild_id, i) for i in rows.all())}
        )

    return authorize


@router.websocket("/updates")
async def websocket_updates(websocket: WebSocket, guild_id: CommunityIdPath):
    """Change envelopes for one guild: ``{changes: [...]}`` frames naming what
    moved, never its content, and a heartbeat when nothing has.

    The first frame carries the credential (see ``app.api.content_socket``) and
    may say how long this tab was without a socket (``away_seconds``). A
    reconnect that names a gap is told whether anything it can see changed
    during it — one bit, since the frames that named the rows are gone.

    The socket counts its user as present in the guild.
    """
    behind = False

    async def catch_up(_session: AsyncSession, sub: Subscriber) -> None:
        # Asked of the rooms just seated, which are what the fan-out would have
        # sent to. Joined first, so a change committing in between reaches the
        # socket and this can only over-answer; a read that fails says the same
        # bit, since a gap nobody could look into is a gap.
        nonlocal behind
        away = sub.first_frame.get("away_seconds")
        if not isinstance(away, (int, float)) or away <= 0:
            return
        try:
            behind = await missed_while_away(guild_id, sub.rooms, float(away))
        except Exception:
            logger.exception("Events WS: catch-up read failed for guild %s", guild_id)
            behind = True

    sub = await admit(
        websocket,
        guild_id,
        wire=Wire.json,
        authorize=_rooms_for(guild_id),
        presence=True,
        joined=catch_up,
    )
    if sub is None:
        return
    if behind:
        sub.send_json(EVERYTHING)
    await hold_open(sub)
