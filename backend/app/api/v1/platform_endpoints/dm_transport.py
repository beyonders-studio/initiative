"""The direct-message transport: keys in, ciphertext through, nothing kept.

All of it on ``UserSessionDep`` — a platform-tier session, RLS enforced. Every
table these routes touch is own-row for the caller, with two exceptions the
database itself gates: reading another account's public keys, and claiming one
of its prekeys, both only where an accepted message grant already exists.

There is no route that returns a conversation's history, because the server has
none to return. A collected message is deleted; the client is the archive.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    HTTPException,
    Path,
    Request,
    Response,
    status,
)

from app.api.deps import CurrentUser, UserSessionDep
from app.core import audit_context, auth_context
from app.core.messages import DirectMessageTransportMessages as Messages
from app.core.rate_limit import limiter
from app.core.user_display import handle_of
from app.schemas.platform.dm_transport import (
    MAX_GROUP_MEMBERS,
    DmConversationCreate,
    DmConversationRead,
    DmConversationsResponse,
    DmDeviceRegistration,
    DmDevicesResponse,
    DmGroupCreate,
    DmOneTimeKeyBatch,
    DmOwnSessionKeysRequest,
    DmQueueAck,
    DmQueueResponse,
    DmRosterCheckRequest,
    DmRosterCheckResponse,
    DmSendRequest,
    DmSendResponse,
    DmSessionKeysRequest,
    DmSessionKeysResponse,
    DmVerificationInbox,
    DmVerificationSend,
)
from app.services.platform import dm_notifications, dm_stream
from app.services.platform import dm_transport as service

me_router = APIRouter()
user_router = APIRouter()

TargetUserId = Annotated[int, Path(ge=1)]


def _session_id() -> uuid.UUID | None:
    """The sign-in this request is on, which a key store is linked to."""
    credential = auth_context.current().session_credential
    return credential.session_id if credential is not None else None


@me_router.post(
    "/dm/devices", response_model=DmDevicesResponse, status_code=status.HTTP_201_CREATED
)
async def register_device(
    body: DmDeviceRegistration,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> DmDevicesResponse:
    """Publish this installed client's public keys.

    The device's label comes from the request's user-agent rather than the body:
    a device list is more use when it says what actually connected.
    """
    device = await service.register_device(
        session,
        user_id=current_user.id,
        identity_key=body.identity_key,
        fingerprint_key=body.fingerprint_key,
        signature=body.signature,
        fallback_key=body.fallback_key,
        one_time_keys=body.one_time_keys,
        label=(audit_context.client_user_agent() or "")[:200] or None,
        session_id=_session_id(),
    )
    device_id = device.id
    await session.commit()
    return DmDevicesResponse(
        devices=await service.list_devices(session, user_id=current_user.id),
        device_id=device_id,
    )


@me_router.get("/dm/devices", response_model=DmDevicesResponse)
async def list_devices(
    session: UserSessionDep, current_user: CurrentUser
) -> DmDevicesResponse:
    return DmDevicesResponse(
        devices=await service.list_devices(session, user_id=current_user.id)
    )


@me_router.delete("/dm/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_device(
    device_id: uuid.UUID,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> Response:
    """Stop encrypted messaging on one device, without signing it out.

    Takes its queued messages with it, which is the one thing that removes an
    undelivered message and is a visible act by the person who owns it.
    """
    await service.remove_device(session, user_id=current_user.id, device_id=device_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@me_router.post("/dm/one-time-keys", response_model=DmDevicesResponse)
async def top_up_keys(
    body: DmOneTimeKeyBatch,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> DmDevicesResponse:
    await service.add_one_time_keys(
        session,
        user_id=current_user.id,
        device_id=body.device_id,
        keys=body.one_time_keys,
    )
    await session.commit()
    return DmDevicesResponse(
        devices=await service.list_devices(session, user_id=current_user.id)
    )


@me_router.post("/dm/session-keys", response_model=DmSessionKeysResponse)
@limiter.limit("60/minute")
async def claim_own_session_keys(
    request: Request,
    body: DmOwnSessionKeysRequest,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> DmSessionKeysResponse:
    """Keys for this account's other devices, so a message reaches its own
    outbox.

    A device of yours is a separate ratchet, not a shortcut: it needs a session
    like anybody else's. The calling device names itself so it is left out of
    its own answer.
    """
    devices = await service.own_session_keys(
        session,
        user_id=current_user.id,
        except_device=body.device_id,
        only=body.device_ids,
    )
    await session.commit()
    return DmSessionKeysResponse(user_id=current_user.id, devices=devices)


@user_router.post("/{user_id}/dm/session-keys", response_model=DmSessionKeysResponse)
@limiter.limit("60/minute")
async def claim_session_keys(
    request: Request,
    user_id: TargetUserId,
    session: UserSessionDep,
    current_user: CurrentUser,
    body: DmSessionKeysRequest | None = None,
) -> DmSessionKeysResponse:
    """Claim what is needed to open a session with each of that account's
    devices.

    A POST rather than a GET because a claim spends a prekey — this writes.
    """
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=Messages.CANNOT_MESSAGE_SELF,
        )
    devices = await service.claim_session_keys(
        session, target_id=user_id, only=body.device_ids if body else None
    )
    await session.commit()
    return DmSessionKeysResponse(user_id=user_id, devices=devices)


@user_router.get("/{user_id}/dm/devices", response_model=DmSessionKeysResponse)
@limiter.limit("120/minute")
async def read_directory(
    request: Request,
    user_id: TargetUserId,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> DmSessionKeysResponse:
    """That account's devices and their public keys, claiming nothing.

    What a recipient reads to derive the session an inbound pre-key message
    describes. Separate from the claim above because claiming spends a prekey,
    and answering a message should not cost one.
    """
    devices = await service.directory(session, target_id=user_id)
    return DmSessionKeysResponse(user_id=user_id, devices=devices)


@me_router.post(
    "/dm/conversations",
    response_model=DmConversationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    body: DmConversationCreate,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> DmConversationRead:
    conversation = await service.create_conversation(
        session, actor_id=current_user.id, other_id=body.user_id
    )
    await session.commit()
    return DmConversationRead(
        id=conversation.id,
        other_user_id=body.user_id,
        created_at=conversation.created_at,
    )


@me_router.post("/dm/roster-check", response_model=DmRosterCheckResponse)
async def check_roster(
    body: DmRosterCheckRequest,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> DmRosterCheckResponse:
    """Could this set of people be a group?

    Asked while somebody is still choosing names, so the answer arrives when
    they can still drop one, rather than as a refusal after they commit. The
    proposal enforces the same rule again — this is the question, not the gate.
    """
    members = sorted(set(body.user_ids) | {current_user.id})
    too_large = len(members) > MAX_GROUP_MEMBERS
    pair = (
        None
        if too_large
        else await service.unreachable_pair(
            session, actor_id=current_user.id, member_ids=members
        )
    )
    return DmRosterCheckResponse(
        unreachable_pair=list(pair) if pair else [],
        max_members=MAX_GROUP_MEMBERS,
        too_large=too_large,
    )


@me_router.post(
    "/dm/conversations/group",
    response_model=DmConversationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_group_conversation(
    body: DmGroupCreate,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> DmConversationRead:
    """Propose a roster. Everybody named on it is asked; nobody is added.

    Proposing the same roster again asks whoever is not on it — somebody who
    declined or left may have changed their mind, or their settings.
    """
    conversation, invited, roster = await service.create_group_conversation(
        session, actor_id=current_user.id, member_ids=body.user_ids
    )
    await session.commit()
    for recipient_id in invited:
        await dm_stream.signal_dm(recipient_id)
    return DmConversationRead(
        id=conversation.id,
        # The same shape the list answers with, so a client can put this
        # straight into the list it already has rather than re-fetching.
        other_user_id=roster[0],
        created_at=conversation.created_at,
        kind="group",
        member_ids=roster,
        # The one proposing it has answered by proposing.
        pending=False,
    )


@me_router.post(
    "/dm/conversations/{conversation_id}/accept",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def accept_invitation(
    conversation_id: uuid.UUID,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> Response:
    """Answer yes to a roster you were named on.

    Declining is :func:`leave_conversation` — the same act, because an
    invitation refused and a conversation left both come to "not on it", and
    both are answered by being asked again if anybody proposes that roster.
    """
    joined = await service.accept_invitation(
        session, user_id=current_user.id, conversation_id=conversation_id
    )
    await session.commit()
    await dm_stream.signal_dm(current_user.id)
    for member_id in joined:
        await dm_stream.signal_dm(member_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@me_router.get("/dm/conversations", response_model=DmConversationsResponse)
async def list_conversations(
    session: UserSessionDep, current_user: CurrentUser
) -> DmConversationsResponse:
    return DmConversationsResponse(
        conversations=await service.list_conversations(session, user_id=current_user.id)
    )


@me_router.delete(
    "/dm/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def leave_conversation(
    conversation_id: uuid.UUID,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> Response:
    await service.leave_conversation(
        session, user_id=current_user.id, conversation_id=conversation_id
    )
    await dm_notifications.forget_conversation(
        session, user_id=current_user.id, conversation_id=conversation_id
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@me_router.post(
    "/dm/conversations/{conversation_id}/read", status_code=status.HTTP_204_NO_CONTENT
)
async def mark_conversation_read(
    conversation_id: uuid.UUID,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> Response:
    """This account has read what was waiting in one thread.

    The client says so once it has decrypted and rendered what arrived, which is
    the only moment anybody knows. It closes the rolled-up bell line, so the
    next message announces itself instead of joining a line that is already
    there, and it clears the badge on this account's other tabs.

    It acts on this account's own notifications and nothing else, so a
    conversation id that names none of them closes nothing and still answers.
    """
    await dm_notifications.mark_conversation_read(
        session, user_id=current_user.id, conversation_id=conversation_id
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@me_router.post(
    "/dm/conversations/{conversation_id}/messages", response_model=DmSendResponse
)
async def send_messages(
    conversation_id: uuid.UUID,
    body: DmSendRequest,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> DmSendResponse:
    """Hand the server one already-encrypted copy per destination device."""
    outcome = await service.send(
        session,
        user_id=current_user.id,
        conversation_id=conversation_id,
        messages=body.messages,
    )
    await session.commit()

    # The sender's own tabs always have something to collect; a recipient only
    # where the message actually reached them, and they are never told about the
    # difference.
    await dm_stream.signal_dm(current_user.id)
    if body.wake_own_devices:
        await dm_notifications.wake_own_devices(
            user_id=current_user.id,
            except_session_id=_session_id(),
        )
    for recipient_id in outcome.reached:
        if body.silent:
            # Wake them to collect it, and write nothing down about it. A bell
            # line names a sender and counts what they said; a client saying it
            # has read something is neither.
            await dm_stream.signal_dm(recipient_id)
        else:
            await dm_notifications.notify(
                recipient_id=recipient_id,
                sender=current_user,
                sender_name=handle_of(current_user),
                conversation_id=conversation_id,
                group=outcome.group,
            )
    return DmSendResponse(
        accepted=outcome.accepted, queue_full_for=list(outcome.queue_full)
    )


@me_router.get("/dm/queue", response_model=DmQueueResponse)
async def collect_queue(
    device_id: uuid.UUID,
    session: UserSessionDep,
    current_user: CurrentUser,
    after: int | None = None,
) -> DmQueueResponse:
    """What is waiting for one device, oldest first, the page after ``after``."""
    page = await service.collect(
        session,
        user_id=current_user.id,
        device_id=device_id,
        session_id=_session_id(),
        after=after,
    )
    await session.commit()
    return page


@me_router.post("/dm/queue/ack", status_code=status.HTTP_204_NO_CONTENT)
async def acknowledge_queue(
    body: DmQueueAck,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> Response:
    """Delete what this device has taken."""
    await service.acknowledge(
        session,
        user_id=current_user.id,
        device_id=body.device_id,
        message_ids=body.message_ids,
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@me_router.post("/dm/verification", status_code=status.HTTP_204_NO_CONTENT)
async def send_verification(
    body: DmVerificationSend,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> Response:
    """Relay one message of a verification to another of this account's
    devices. The body is the client's own and is not read here."""
    await service.send_verification(
        session,
        user_id=current_user.id,
        device_id=body.device_id,
        to_device_id=body.to_device_id,
        body=body.body,
    )
    await session.commit()
    await dm_stream.signal_dm(current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@me_router.get("/dm/verification", response_model=DmVerificationInbox)
async def collect_verification(
    device_id: uuid.UUID,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> DmVerificationInbox:
    """Verification messages waiting for one device, oldest first. Collecting
    deletes them."""
    items = await service.collect_verification(
        session, user_id=current_user.id, device_id=device_id
    )
    await session.commit()
    return DmVerificationInbox(items=items)
