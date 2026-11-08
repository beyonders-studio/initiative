import logging
from time import monotonic

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    status,
)

from app.api.content_socket import hold_open, read_auth_frame
from app.api.deps import (
    AccountHolder,
    AccountHolderSessionDep,
    UserSessionDep,
    get_current_active_user,
)
from app.core.messages import NotificationMessages
from app.core.notification_categories import category_of
from app.db.cohorts import request_sessionmaker
from app.models.platform.user import User
from app.schemas.platform.notification import (
    NotificationAlertRead,
    NotificationCountResponse,
    NotificationListResponse,
    NotificationPlace,
    NotificationRead,
    RedactedAlert,
    SubjectReadRequest,
    SubjectReadResponse,
    UnreadPlacesResponse,
)
from app.services.content_sockets import (
    Credential,
    Subscriber,
    Wire,
    account_authorizer,
    account_room,
    sockets,
)
from app.services.platform import (
    notification_policy,
    notification_subjects,
    presence,
)
from app.services.platform import user_notifications as notifications_service
from app.services.platform.ws_auth import authenticate_ws_token

router = APIRouter()
logger = logging.getLogger(__name__)

# "Somebody just did something in this tab." One byte, no payload: it says only
# that the person is at their keyboard, which is the whole of what idle needs
# to know. The client throttles it hard, so this is a frame a minute at most.
MSG_ACTIVE = 6


@router.get("/", response_model=NotificationListResponse)
async def list_notifications(
    session: AccountHolderSessionDep,
    current_user: AccountHolder,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
    unread_only: bool = Query(default=False),
    guild_id: int | None = Query(default=None, alias="community_id"),
    personal_only: bool = Query(default=False),
) -> NotificationListResponse:
    """One page of the inbox, newest first.

    The popover asks with ``unread_only`` and follows the cursor to the end:
    it shows everything still unread, which is what makes a number on the bell
    unnecessary. The page takes the same list without the filter, as the
    record.
    """
    (
        notifications,
        unread_count,
        next_cursor,
    ) = await notifications_service.list_notifications(
        session,
        user_id=current_user.id,
        limit=limit,
        cursor=cursor,
        unread_only=unread_only,
        guild_id=guild_id,
        personal_only=personal_only,
    )
    return NotificationListResponse(
        notifications=await _with_subjects(session, current_user.id, notifications),
        unread_count=unread_count,
        next_cursor=next_cursor,
    )


async def _with_subjects(
    session: UserSessionDep,
    user_id: int,
    notifications: list,
) -> list[NotificationRead]:
    """Fill each line's titles from the communities they live in.

    Read here rather than stored on the row, so a line says what its subject is
    called now and says nothing about one the reader can no longer reach. The
    bell renders its plain form for a line whose subject came back empty.

    Runs last: gathering routes this session into each community in turn, so
    nothing on the shared path may follow it.
    """
    lines = [NotificationRead.model_validate(line) for line in notifications]
    resolved = await notification_subjects.resolve_subjects(
        session, user_id, notifications
    )
    if not resolved:
        return lines
    return [
        line.model_copy(update={"data": {**line.data, **resolved[line.id]}})
        if line.id in resolved
        else line
        for line in lines
    ]


@router.get("/unread", response_model=UnreadPlacesResponse)
async def unread_notification_places(
    session: UserSessionDep,
    current_user: User = Depends(get_current_active_user),
) -> UnreadPlacesResponse:
    """Where this account has unread activity, for the dots.

    One distinct scan over the unread index. Nothing is counted: a dot says
    "look here" and the popover says what.
    """
    places = await notifications_service.unread_places(session, user_id=current_user.id)
    return UnreadPlacesResponse(places=[NotificationPlace(**place) for place in places])


@router.post("/read-subject", response_model=SubjectReadResponse)
async def read_notification_subject(
    payload: SubjectReadRequest,
    session: UserSessionDep,
    current_user: User = Depends(get_current_active_user),
) -> SubjectReadResponse:
    """Mark every unread notification about one item read — its page calls
    this when it opens — and say what was unread on it."""
    comment_ids, since = await notifications_service.read_subject(
        session,
        user_id=current_user.id,
        guild_id=payload.community_id,
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
    )
    return SubjectReadResponse(comment_ids=comment_ids, since=since)


@router.get("/{notification_id}/alert", response_model=NotificationAlertRead)
async def read_notification_alert(
    notification_id: int,
    session: AccountHolderSessionDep,
    current_user: AccountHolder,
) -> NotificationAlertRead:
    """One line as the desktop app announces it, after an ``alert`` frame.

    The switches are read as they stand now: a community that has started
    redacting since the frame went gets the kind of thing that happened, and
    one that has switched push off gets no more than that.
    """
    notification = await notifications_service.get_notification(
        session, user_id=current_user.id, notification_id=notification_id
    )
    if notification is None:
        raise HTTPException(status_code=404, detail=NotificationMessages.NOT_FOUND)
    policy = await notification_policy.for_send(session, notification.guild_id)
    redacted = None
    if policy.redact or not policy.push:
        title, body = notification_policy.redacted_line(
            category_of(notification.type), current_user.locale or "en"
        )
        redacted = RedactedAlert(title=title, body=body)
    (line,) = await _with_subjects(session, current_user.id, [notification])
    return NotificationAlertRead(notification=line, redacted=redacted)


@router.post("/{notification_id}/read", response_model=NotificationRead)
async def mark_notification_read(
    notification_id: int,
    session: UserSessionDep,
    current_user: User = Depends(get_current_active_user),
) -> NotificationRead:
    notification = await notifications_service.mark_notification_read(
        session,
        user_id=current_user.id,
        notification_id=notification_id,
    )
    if not notification:
        raise HTTPException(status_code=404, detail=NotificationMessages.NOT_FOUND)
    return NotificationRead.model_validate(notification)


@router.post("/{notification_id}/unread", response_model=NotificationRead)
async def mark_notification_unread(
    notification_id: int,
    session: UserSessionDep,
    current_user: User = Depends(get_current_active_user),
) -> NotificationRead:
    notification = await notifications_service.mark_notification_unread(
        session,
        user_id=current_user.id,
        notification_id=notification_id,
    )
    if not notification:
        raise HTTPException(status_code=404, detail=NotificationMessages.NOT_FOUND)
    return NotificationRead.model_validate(notification)


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_notification(
    notification_id: int,
    session: UserSessionDep,
    current_user: User = Depends(get_current_active_user),
) -> None:
    dismissed = await notifications_service.dismiss_notification(
        session,
        user_id=current_user.id,
        notification_id=notification_id,
    )
    if not dismissed:
        raise HTTPException(status_code=404, detail=NotificationMessages.NOT_FOUND)


@router.post("/read-all", response_model=NotificationCountResponse)
async def mark_all_notifications_read(
    session: UserSessionDep,
    current_user: User = Depends(get_current_active_user),
    guild_id: int | None = Query(default=None, alias="community_id"),
) -> NotificationCountResponse:
    """Clear the unread set, or just one community's part of it."""
    await notifications_service.mark_all_notifications_read(
        session, user_id=current_user.id, guild_id=guild_id
    )
    count = await notifications_service.unread_count(session, user_id=current_user.id)
    return NotificationCountResponse(unread_count=count)


@router.websocket("/stream")
async def websocket_notifications(websocket: WebSocket):
    """Push channel for the notification bell, scoped to one user.

    Replaces the bell's 30s poll of ``GET /notifications/``. There is no guild
    in the address because the inbox has none: it gathers a user's
    notifications from every guild they are in, and some from no guild at all.

    Protocol: the client sends ``MSG_AUTH`` with ``{"token": "..."}`` as its
    first (binary) frame, read by ``app.api.content_socket.read_auth_frame``
    exactly as on the guild sockets; web sessions
    may send ``{"token": null}`` and be authenticated from the session cookie.
    After that the server sends id envelopes, and the only thing the client
    sends back is ``MSG_ACTIVE`` — a sign that its person is at the keyboard,
    which is what keeps them from reading as idle. It names nobody: the socket
    already knows whose it is.

    The stream says "your inbox changed" and never what changed, so the
    decision about content is made by the refetch it provokes: the REST
    endpoints above resolve the inbox from ``current_user`` on a freshly
    validated credential. The socket itself is held to the credential it was
    opened with: it is registered in ``app.services.content_sockets`` as its
    account's socket, re-checked with every other socket, and closed with
    ``WS_CREDENTIAL_ENDED`` once that sign-in ends or the account is no longer
    active.

    A socket that never sends its first frame is closed at
    ``content_socket.AUTH_TIMEOUT_SECONDS`` rather than held open indefinitely.
    """
    await websocket.accept()
    first = await read_auth_frame(websocket)
    if first is None:
        return
    token, _payload = first

    # Validate in a SHORT-LIVED session and release it before the keepalive
    # loop — holding one for the socket's lifetime parks a connection
    # idle-in-transaction, whose locks block DDL like guild deletion's DROP
    # SCHEMA.
    async with request_sessionmaker(None)() as session:
        # Taken before the row is read, so it is never later than the value
        # that read comes back with.
        presence_known_at = monotonic()
        user = await authenticate_ws_token(token, session)
        if user is None:
            logger.warning("Notifications WS: auth failed")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        user_id = user.id
        chosen_presence = user.presence
        watched = Subscriber(
            websocket=websocket,
            user=user,
            guild_id=None,
            wire=Wire.json,
            authorize=account_authorizer,
            credential=Credential.captured(),
            rooms=frozenset({account_room(user_id)}),
            presence=True,
        )

    sockets.join(
        watched, chosen_presence=chosen_presence, presence_known_at=presence_known_at
    )

    def on_bytes(data: bytes) -> None:
        # The one frame the client sends is its person's activity.
        if data[0] == MSG_ACTIVE:
            presence.online.active(user_id)

    await hold_open(watched, on_bytes=on_bytes)
