"""The delivery service: a key directory, a roster, and a queue.

Everything here treats a message as bytes. Nothing in this module branches on
what a payload contains: no key to it exists on the server, which is also why
there is nothing to configure about retention, moderation or search.

Four things it does, and nothing else: publish public keys, hand a sender the
keys it needs, write ciphertext to the recipients' queues, and delete a row once
its recipient has collected it.

Authorisation is the rule the permission layer already shipped. This module
calls ``dm_apparent_permission`` for what the caller may be *told*, and
``dm_deliverable`` for what actually reaches somebody — the difference is the
recipient's ignore list, which the sender's own session cannot read and is never
told about.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import status
from sqlalchemy import delete, func, insert, text, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import CodedError
from app.core.messages import DirectMessageTransportMessages as Messages
from app.core.user_agents import describe as describe_client
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.models.platform.dm_conversation import (
    DmConversation,
    DmConversationKind,
    DmConversationMember,
    roster_key,
)
from app.models.platform.dm_device import DmDevice
from app.models.platform.dm_one_time_key import DmOneTimeKey
from app.models.platform.dm_queue import DmQueueItem
from app.models.platform.dm_verification import DmVerificationItem
from app.schemas.platform.dm_transport import (
    MAX_GROUP_MEMBERS,
    MAX_ONE_TIME_KEYS,
    MAX_PAYLOAD_BYTES,
    DmConversationRead,
    DmDeviceRead,
    DmOneTimeKeyUpload,
    DmOutboundMessage,
    DmQueueItemRead,
    DmQueueResponse,
    DmRosterMember,
    DmSessionKey,
    DmVerificationMessage,
)
from app.services.platform import presence as presence_service

#: A public key is 32 bytes on both curves.
KEY_BYTES = 32

#: How much undelivered ciphertext one account may be holding. Generous by
#: design: a padded text message is about a kilobyte, so this is on the order of
#: seventeen thousand messages nobody has collected on any device.
QUEUE_CEILING_BYTES = 50 * 1024 * 1024

#: How many messages one collection returns.
QUEUE_PAGE = 200

#: How long a verification message waits for its recipient. An emoji
#: verification is two people looking at two screens at once, so a message
#: older than this belongs to an attempt that is already over.
VERIFICATION_TTL = timedelta(minutes=10)
#: How many verification messages one account may have waiting at once. One
#: verification is a handful of messages; this leaves room for several running
#: side by side.
VERIFICATION_OUTSTANDING = 32


@dataclass(frozen=True)
class DmSendOutcome:
    """What a send did, in the terms the sender may be told."""

    #: How many messages the server took. All of them, or the send failed.
    accepted: int
    #: Members something was actually written for, so they can be woken. Never
    #: reported to the sender: it is the answer an ignore is meant to withhold.
    reached: tuple[int, ...]
    #: Members whose mailbox was too full to take it. A fact about capacity
    #: rather than about permission, so this one is theirs to see.
    queue_full: tuple[int, ...]
    #: Whether this went to a group, so the bell and the push can name the
    #: thread by who is on it rather than by the one other party.
    group: bool = False


#: Every refusal that is about the pair answers the same way, so the endpoint is
#: not a way to learn which of them it was.
_STATUS: dict[str, int] = {
    Messages.DEVICE_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    Messages.CONVERSATION_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    Messages.MALFORMED_KEY: status.HTTP_422_UNPROCESSABLE_CONTENT,
    Messages.INVALID_SIGNATURE: status.HTTP_400_BAD_REQUEST,
    Messages.DUPLICATE_KEY_ID: status.HTTP_409_CONFLICT,
    Messages.TOO_MANY_KEYS: status.HTTP_409_CONFLICT,
    Messages.NOT_REACHABLE: status.HTTP_409_CONFLICT,
    Messages.CANNOT_MESSAGE_SELF: status.HTTP_409_CONFLICT,
    Messages.ROSTER_NOT_REACHABLE: status.HTTP_409_CONFLICT,
    Messages.ROSTER_TOO_LARGE: status.HTTP_409_CONFLICT,
    Messages.ROSTER_TOO_SMALL: status.HTTP_409_CONFLICT,
    Messages.NO_INVITATION: status.HTTP_404_NOT_FOUND,
    Messages.MESSAGE_TOO_LARGE: status.HTTP_413_CONTENT_TOO_LARGE,
    Messages.RECIPIENT_QUEUE_FULL: status.HTTP_507_INSUFFICIENT_STORAGE,
    Messages.VERIFY_SAME_DEVICE: status.HTTP_409_CONFLICT,
    Messages.TOO_MANY_VERIFICATIONS: status.HTTP_429_TOO_MANY_REQUESTS,
}


class DmTransportError(CodedError):
    """A refused transport call, answered at its code's status (409 unless
    :data:`_STATUS` names another)."""

    def __init__(self, code: str) -> None:
        super().__init__(code, _STATUS.get(code, status.HTTP_409_CONFLICT))


def _decode(value: str, *, expect: int | None = None) -> bytes:
    """Read one base64 value the client published.

    The ratchet writes base64 without the trailing ``=``, which is what Olm has
    always put on the wire. Python's decoder requires it, so it is restored
    here rather than asked of every client.
    """
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DmTransportError(Messages.MALFORMED_KEY) from exc
    if expect is not None and len(raw) != expect:
        raise DmTransportError(Messages.MALFORMED_KEY)
    if not raw:
        raise DmTransportError(Messages.MALFORMED_KEY)
    return raw


def _encode_key(raw: bytes) -> str:
    """Write a key or a signature back the way the ratchet wrote it: no padding.

    Clients compare keys as text -- the identity a pre-key message names
    against the one the directory lists -- so a key has one spelling on the
    wire, and it is the ratchet's.
    """
    return base64.b64encode(raw).decode("ascii").rstrip("=")


def _encode_ciphertext(raw: bytes) -> str:
    """Write a queued message back padded, which the ratchet's ciphertext
    reader requires."""
    return base64.b64encode(raw).decode("ascii")


async def _permission(session: AsyncSession, target_id: int) -> str:
    """What the caller may do about that account, as the caller sees it."""
    return (
        await session.exec(
            text("SELECT public.dm_apparent_permission(:t)").bindparams(t=target_id)
        )
    ).scalar_one()


async def _deliverable(session: AsyncSession, target_id: int) -> bool:
    """Whether anything the caller sends that account actually arrives.

    The answer is never returned to the caller. Where it is false the write
    still succeeds and simply reaches nobody, so an account that has stopped
    hearing from somebody does not announce it by behaving differently.
    """
    return (
        await session.exec(
            text("SELECT public.dm_deliverable(:t)").bindparams(t=target_id)
        )
    ).scalar_one()


async def _queue_bytes(session: AsyncSession, user_id: int) -> int:
    return (
        await session.exec(
            text("SELECT public.dm_queue_bytes(:u)").bindparams(u=user_id)
        )
    ).scalar_one()


async def _own_device(
    session: AsyncSession, *, user_id: int, device_id: uuid.UUID
) -> DmDevice:
    device = await session.get(DmDevice, device_id)
    if device is None or device.user_id != user_id:
        raise DmTransportError(Messages.DEVICE_NOT_FOUND)
    return device


# --------------------------------------------------------------------------
# Devices and keys
# --------------------------------------------------------------------------


#: The byte strings a device signs, as the ratchet builds them
#: (``crypto/src/lib.rs``): its keys and account, and each key it publishes.
_DEVICE_TAG = b"initiative-dm-device-v1\0"
_ONE_TIME_KEY_TAG = b"initiative-dm-otk-v1\0"
_FALLBACK_KEY_TAG = b"initiative-dm-fallback-v1\0"
SIGNATURE_BYTES = 64


def _device_bytes(user_id: int, identity_key: bytes, fingerprint_key: bytes) -> bytes:
    return _DEVICE_TAG + user_id.to_bytes(8, "big") + identity_key + fingerprint_key


def _signature(fingerprint_key: bytes, message: bytes, signature: str | None) -> bytes:
    """The raw signature, once it verifies against the device's fingerprint key."""
    if signature is None:
        raise DmTransportError(Messages.INVALID_SIGNATURE)
    raw = _decode(signature, expect=SIGNATURE_BYTES)
    try:
        Ed25519PublicKey.from_public_bytes(fingerprint_key).verify(raw, message)
    except (InvalidSignature, ValueError) as exc:
        raise DmTransportError(Messages.INVALID_SIGNATURE) from exc
    return raw


def _key_row(
    device: DmDevice, key: DmOneTimeKeyUpload, *, fallback: bool
) -> DmOneTimeKey:
    """A published key, its signature checked when the device signs."""
    public_key = _decode(key.public_key, expect=KEY_BYTES)
    signature = (
        _signature(
            device.fingerprint_key,
            (_FALLBACK_KEY_TAG if fallback else _ONE_TIME_KEY_TAG) + public_key,
            key.signature,
        )
        if device.signature is not None
        else None
    )
    return DmOneTimeKey(
        device_id=device.id,
        key_id=key.key_id,
        public_key=public_key,
        fallback=fallback,
        signature=signature,
    )


def _add_keys(
    session: AsyncSession,
    device: DmDevice,
    *,
    fallback_key: DmOneTimeKeyUpload | None,
    one_time_keys: list[DmOneTimeKeyUpload],
) -> None:
    if len({key.key_id for key in one_time_keys}) != len(one_time_keys):
        raise DmTransportError(Messages.DUPLICATE_KEY_ID)
    if fallback_key is not None:
        session.add(_key_row(device, fallback_key, fallback=True))
    session.add_all(_key_row(device, key, fallback=False) for key in one_time_keys)


async def register_device(
    session: AsyncSession,
    *,
    user_id: int,
    identity_key: str,
    fingerprint_key: str,
    signature: str | None,
    fallback_key: DmOneTimeKeyUpload,
    one_time_keys: list[DmOneTimeKeyUpload],
    label: str | None,
    session_id: uuid.UUID | None = None,
) -> DmDevice:
    """Publish a new installed client's public keys, signed by the device.

    An unsigned registration is refused, and a signed device's keys must be
    signed too.

    A fallback key is required rather than optional: without one, a device whose
    prekeys run out becomes unreachable to anyone starting a new conversation,
    and the failure would land on the sender.

    ``session_id`` names the sign-in this key store is collected under, taken
    from the session that authenticated the call rather than from the body. Its
    push registration names the same sign-in, which is what lets a message wake
    this device and no other; it is not something a caller may assert about
    itself.
    """
    identity = _decode(identity_key, expect=KEY_BYTES)
    fingerprint = _decode(fingerprint_key, expect=KEY_BYTES)
    if signature is None:
        raise DmTransportError(Messages.INVALID_SIGNATURE)
    device = DmDevice(
        user_id=user_id,
        identity_key=identity,
        fingerprint_key=fingerprint,
        signature=(
            _signature(
                fingerprint, _device_bytes(user_id, identity, fingerprint), signature
            )
            if signature is not None
            else None
        ),
        label=label,
        session_id=session_id,
    )
    session.add(device)
    await session.flush()
    if session_id is not None:
        # A re-registering installation brings its key store with it. The row it
        # replaces must not go on naming the sign-in, or a push would be aimed
        # at a store whose private half this device no longer has.
        await _claim_session(
            session, user_id=user_id, device_id=device.id, session_id=session_id
        )
    _add_keys(session, device, fallback_key=fallback_key, one_time_keys=one_time_keys)
    await session.flush()
    return device


async def sign_device(
    session: AsyncSession,
    *,
    user_id: int,
    device_id: uuid.UUID,
    signature: str,
    fallback_key: DmOneTimeKeyUpload,
    one_time_keys: list[DmOneTimeKeyUpload],
) -> None:
    """Sign a device registered before signing, once, and replace the keys it
    published unsigned with signed ones."""
    device = await _own_device(session, user_id=user_id, device_id=device_id)
    if device.signature is not None:
        raise DmTransportError(Messages.INVALID_SIGNATURE)
    device.signature = _signature(
        device.fingerprint_key,
        _device_bytes(user_id, device.identity_key, device.fingerprint_key),
        signature,
    )
    await session.exec(delete(DmOneTimeKey).where(DmOneTimeKey.device_id == device.id))
    _add_keys(session, device, fallback_key=fallback_key, one_time_keys=one_time_keys)
    await session.flush()


async def add_one_time_keys(
    session: AsyncSession,
    *,
    user_id: int,
    device_id: uuid.UUID,
    keys: list[DmOneTimeKeyUpload],
) -> int:
    """Top a device's pool back up. Returns how many it now holds."""
    device = await _own_device(session, user_id=user_id, device_id=device_id)
    held = (await _unclaimed_counts(session, [device.id])).get(device.id, 0)
    if held + len(keys) > MAX_ONE_TIME_KEYS:
        raise DmTransportError(Messages.TOO_MANY_KEYS)
    _add_keys(session, device, fallback_key=None, one_time_keys=keys)
    await session.flush()
    return held + len(keys)


async def _unclaimed_counts(
    session: AsyncSession, device_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    rows = await session.exec(
        select(DmOneTimeKey.device_id, func.count())
        .where(
            DmOneTimeKey.device_id.in_(device_ids),
            DmOneTimeKey.fallback.is_(False),
        )
        .group_by(DmOneTimeKey.device_id)
    )
    return {device_id: count for device_id, count in rows.all()}


async def list_devices(session: AsyncSession, *, user_id: int) -> list[DmDeviceRead]:
    devices = list(
        (
            await session.exec(
                select(DmDevice)
                .where(DmDevice.user_id == user_id)
                .order_by(DmDevice.created_at)
            )
        ).all()
    )
    counts = await _unclaimed_counts(session, [device.id for device in devices])
    return [
        DmDeviceRead(
            id=device.id,
            identity_key=_encode_key(device.identity_key),
            fingerprint_key=_encode_key(device.fingerprint_key),
            signature=_encode_key(device.signature) if device.signature else None,
            # Stored as the user agent that registered it, which is no name a
            # person would recognise their own laptop by.
            label=describe_client(device.label),
            created_at=device.created_at,
            last_seen_at=device.last_seen_at,
            one_time_key_count=counts.get(device.id, 0),
        )
        for device in devices
    ]


async def remove_device(
    session: AsyncSession, *, user_id: int, device_id: uuid.UUID
) -> None:
    """Drop a device's keys and everything queued for it.

    This is the one thing that removes an undelivered message, and it is a
    visible act by the person who owns the mailbox.
    """
    device = await _own_device(session, user_id=user_id, device_id=device_id)
    await session.delete(device)
    await session.flush()


async def withdraw_signed_in(
    session: AsyncSession, *, user_id: int, session_ids: Collection[uuid.UUID]
) -> None:
    """Drop the key stores these sign-ins name, and everything queued for them.

    What ending a sign-in from the account's own list does: nothing more is
    encrypted to a device somebody has cut off, or to a browser whose keys go
    with its session. Scoped to the account's own rows.
    """
    if not session_ids:
        return
    await session.exec(
        delete(DmDevice).where(
            DmDevice.user_id == user_id, col(DmDevice.session_id).in_(list(session_ids))
        )
    )


#: How long after a browser's sign-in ends its key store is kept. A renewal
#: that read the session just before it ran out still moves the store to the
#: session it opens, and finishes well inside this.
ENDED_BROWSER_GRACE = timedelta(hours=1)


async def withdraw_ended_browsers(session: AsyncSession, *, now: datetime) -> None:
    """Drop the key stores of browsers whose sign-in has ended.

    A browser's keys go with its session, and one that lapsed has already wiped
    them, without the credential to withdraw its row itself. A device's store
    names a session that has an install and outlasts it on purpose. Does not
    commit.
    """
    await session.exec(
        text(
            "DELETE FROM dm_devices d USING auth_sessions s "
            "WHERE d.session_id = s.id AND s.install_id IS NULL "
            "AND (s.revoked_at <= :ended OR s.expires_at <= :ended)"
        ),
        params={"ended": now - ENDED_BROWSER_GRACE},
    )


def _session_key(
    device: DmDevice, one_time_key: DmOneTimeKeyUpload | None
) -> DmSessionKey:
    return DmSessionKey(
        device_id=device.id,
        identity_key=_encode_key(device.identity_key),
        fingerprint_key=_encode_key(device.fingerprint_key),
        signature=_encode_key(device.signature) if device.signature else None,
        one_time_key=one_time_key,
    )


async def devices_of(
    session: AsyncSession,
    user_id: int,
    *,
    except_device: uuid.UUID | None = None,
    only: list[uuid.UUID] | None = None,
) -> list[DmDevice]:
    """The account's key stores, oldest first (all of them, or ``only`` those)."""
    query = select(DmDevice).where(DmDevice.user_id == user_id)
    if except_device is not None:
        query = query.where(DmDevice.id != except_device)
    if only is not None:
        query = query.where(DmDevice.id.in_(only))
    return list((await session.exec(query.order_by(DmDevice.created_at))).all())


async def claim_session_keys(
    session: AsyncSession, *, target_id: int, only: list[uuid.UUID] | None = None
) -> list[DmSessionKey]:
    """The keys the caller needs to open a session with that account's devices
    (``only`` those, when named), spending one prekey per device.

    A claim is a delete: a prekey that cannot be handed out twice needs no state
    to say so. The reusable fallback key is the exception, and is what a device
    whose pool is drained answers with.
    """
    if await _permission(session, target_id) != "open":
        raise DmTransportError(Messages.NOT_REACHABLE)
    # One statement, one key per device. The request path holds no DELETE on
    # another account's pool, and two callers racing take different rows rather
    # than the same one.
    claimed = [
        _session_key(device, await _claim_for(session, device.id))
        for device in await devices_of(session, target_id, only=only)
    ]
    await session.flush()
    return claimed


async def _claim_for(
    session: AsyncSession, device_id: uuid.UUID
) -> DmOneTimeKeyUpload | None:
    """Spend one prekey from a device, or take its reusable fallback."""
    row = (
        await session.exec(
            text(
                "SELECT key_id, public_key, fallback, signature "
                "FROM public.dm_claim_one_time_key(:d)"
            ).bindparams(d=device_id)
        )
    ).first()
    if row is None:
        return None
    return DmOneTimeKeyUpload(
        key_id=row[0],
        public_key=_encode_key(bytes(row[1])),
        fallback=row[2],
        signature=_encode_key(bytes(row[3])) if row[3] is not None else None,
    )


async def directory(session: AsyncSession, *, target_id: int) -> list[DmSessionKey]:
    """That account's devices and their public keys, claiming nothing.

    A recipient needs the sender's identity key to derive the session a pre-key
    message describes, and the queue row carries no sender -- so it reads the
    directory for the one other account its conversation has. Spending a prekey
    to answer an inbound message would drain the pool for no reason.
    """
    if await _permission(session, target_id) != "open":
        raise DmTransportError(Messages.NOT_REACHABLE)
    return [
        _session_key(device, None) for device in await devices_of(session, target_id)
    ]


async def own_session_keys(
    session: AsyncSession,
    *,
    user_id: int,
    except_device: uuid.UUID,
    only: list[uuid.UUID] | None = None,
) -> list[DmSessionKey]:
    """Keys for this account's *other* devices.

    A message has to reach the sender's own clients as well as the recipient's,
    or their phone never shows what they wrote on their laptop. A device of
    yours is as much a separate ratchet as anybody else's, so it needs the same
    keys, claimed the same way -- ``dm_claim_one_time_key`` already lets an
    owner spend from their own pool, and this is the route to it.
    """
    return [
        _session_key(device, await _claim_for(session, device.id))
        for device in await devices_of(
            session, user_id, except_device=except_device, only=only
        )
    ]


# --------------------------------------------------------------------------
# Conversations
# --------------------------------------------------------------------------


async def _conversation_with_roster(
    session: AsyncSession, *, kind: DmConversationKind, member_ids: Iterable[int]
) -> DmConversation | None:
    """The one conversation made with exactly these people, if it exists.

    Asked of the key rather than by joining the roster back together: the key is
    what the unique index is on, so this reads the same thing the index enforces
    instead of a second expression of it that could disagree.
    """
    return (
        await session.exec(
            select(DmConversation).where(
                DmConversation.kind == kind,
                DmConversation.roster_key == roster_key(member_ids),
            )
        )
    ).first()


async def _open_conversation(
    session: AsyncSession, *, kind: DmConversationKind, member_ids: Iterable[int]
) -> tuple[DmConversation, bool]:
    """Insert the conversation for this roster, or return the one that beat us.

    Two requests for the same roster can both look, both find nothing and both
    insert; the unique index refuses the second. Losing that race means the
    conversation the caller asked for exists, which is the answer they wanted,
    so it is read back rather than returned as an error. The savepoint is what
    keeps the refused insert from taking the surrounding transaction with it.

    The flag says whether this call is the one that made it, so only the winner
    writes the roster.
    """
    try:
        async with session.begin_nested():
            conversation = DmConversation(kind=kind, roster_key=roster_key(member_ids))
            session.add(conversation)
            await session.flush()
        return conversation, True
    except IntegrityError:
        pass
    winner = await _conversation_with_roster(session, kind=kind, member_ids=member_ids)
    if winner is None:
        raise DmTransportError(Messages.CONVERSATION_NOT_FOUND)
    return winner, False


async def create_conversation(
    session: AsyncSession, *, actor_id: int, other_id: int
) -> DmConversation:
    """Open the channel an accepted message request earned.

    Idempotent: asking twice returns the conversation that already exists rather
    than a second one, because a roster has one channel — for a pair, which is
    all this opens, that is the rule the pairwise design already stated.

    A conversation somebody has left is not found here, because a conversation
    down to one member releases its roster name — see :func:`leave_conversation`.
    Asking again after somebody left therefore opens a fresh channel, which is
    what it did before a roster was an identity.

    Both members are accepted the moment it is made. An invitation somebody has
    to answer belongs to a roster they did not already agree to, and a pair got
    here by an accepted message request.
    """
    if actor_id == other_id:
        raise DmTransportError(Messages.CANNOT_MESSAGE_SELF)
    members = (actor_id, other_id)
    existing = await _conversation_with_roster(
        session, kind=DmConversationKind.direct, member_ids=members
    )
    if existing is not None:
        return existing
    if await _permission(session, other_id) != "open":
        raise DmTransportError(Messages.NOT_REACHABLE)

    conversation, opened = await _open_conversation(
        session, kind=DmConversationKind.direct, member_ids=members
    )
    if not opened:
        # Somebody else's request got there first and wrote the roster with it.
        return conversation
    now = datetime.now(UTC)
    for member_id in members:
        session.add(
            DmConversationMember(
                conversation_id=conversation.id,
                user_id=member_id,
                accepted_at=now,
            )
        )
    await session.flush()
    return conversation


async def unreachable_pair(
    session: AsyncSession, *, actor_id: int, member_ids: Iterable[int]
) -> tuple[int, int] | None:
    """The first two on this roster who cannot message each other, if any.

    Everybody on a group has to be able to reach everybody else — that is what
    makes it a conversation rather than a room where two people can read each
    other and neither can start. The rule is ``can_ask`` both ways, the same
    table a pair passes, asked across the roster.

    The proposer's own pairs are asked first, and the rest of the roster only
    once the proposer can reach everybody on it: the answer is about people
    the proposer already has a way to message.

    Deliberately ``can_ask`` and not "already open": requiring an accepted
    request between every pair would mean nobody could ever be introduced to
    anybody.
    """
    others = sorted(set(member_ids) - {actor_id})
    if not others:
        return None
    own = (
        await session.exec(
            text(
                "SELECT id FROM unnest(CAST(:ids AS int[])) AS t(id) "
                "WHERE public.dm_roster_unreachable_pair(ARRAY[:actor, id]) "
                "IS NOT NULL ORDER BY id LIMIT 1"
            ).bindparams(ids=others, actor=actor_id)
        )
    ).first()
    if own is not None:
        low, high = sorted((actor_id, own[0]))
        return (low, high)
    if len(others) < 2:
        return None
    row = (
        await session.exec(
            text("SELECT public.dm_roster_unreachable_pair(:ids)").bindparams(
                ids=others
            )
        )
    ).scalar_one()
    if row is None:
        return None
    return (row[0], row[1])


async def create_group_conversation(
    session: AsyncSession, *, actor_id: int, member_ids: Iterable[int]
) -> tuple[DmConversation, list[int], list[int]]:
    """Propose a roster, and ask everybody on it who is not already.

    Returns the conversation, the members newly invited — an empty list when the
    roster was already assembled and everybody had answered, which is what
    proposing the same roster twice does — and the roster itself, without the
    caller.

    **Proposing a roster again asks the people who are not on it.** People
    change their minds, and they change their settings, so somebody who declined
    in March may accept in June. It is an invitation rather than a
    re-admission: they answer it the way they answered the first one. Somebody
    still deciding is left alone — they already have it, and a second copy is
    pestering.

    The whole roster is re-checked each time, against settings as they are now.
    That is what lets "they have widened their settings" work at all, and it
    equally means a roster that has since become unreachable is refused.
    """
    members = sorted(set(member_ids) | {actor_id})
    if actor_id in set(member_ids):
        raise DmTransportError(Messages.CANNOT_MESSAGE_SELF)
    if len(members) < 3:
        raise DmTransportError(Messages.ROSTER_TOO_SMALL)
    if len(members) > MAX_GROUP_MEMBERS:
        raise DmTransportError(Messages.ROSTER_TOO_LARGE)
    if (
        await unreachable_pair(session, actor_id=actor_id, member_ids=members)
        is not None
    ):
        raise DmTransportError(Messages.ROSTER_NOT_REACHABLE)

    conversation = await _conversation_with_roster(
        session, kind=DmConversationKind.group, member_ids=members
    )
    if conversation is None:
        conversation, _ = await _open_conversation(
            session, kind=DmConversationKind.group, member_ids=members
        )

    present = set(
        (
            await session.exec(
                select(DmConversationMember.user_id).where(
                    DmConversationMember.conversation_id == conversation.id
                )
            )
        ).all()
    )
    now = datetime.now(UTC)
    invited: list[int] = []
    for member_id in members:
        if member_id in present:
            continue
        # The one proposing has answered by proposing.
        session.add(
            DmConversationMember(
                conversation_id=conversation.id,
                user_id=member_id,
                accepted_at=now if member_id == actor_id else None,
            )
        )
        if member_id != actor_id:
            invited.append(member_id)
    await session.flush()
    others = [member_id for member_id in members if member_id != actor_id]
    return conversation, invited, others


async def accept_invitation(
    session: AsyncSession, *, user_id: int, conversation_id: uuid.UUID
) -> list[int]:
    """Answer yes, and join the roster. Returns who else is already on it."""
    updated = await session.exec(
        update(DmConversationMember)
        .where(
            DmConversationMember.conversation_id == conversation_id,
            DmConversationMember.user_id == user_id,
            DmConversationMember.accepted_at.is_(None),
        )
        .values(accepted_at=datetime.now(UTC))
    )
    if not updated.rowcount:
        raise DmTransportError(Messages.NO_INVITATION)
    await session.flush()
    return await _other_members(
        session, conversation_id=conversation_id, user_id=user_id
    )


async def _people_on(
    session: AsyncSession, member_ids: Iterable[int]
) -> dict[int, DmRosterMember]:
    """Everybody on these conversations, as a client has to draw them.

    Read from ``public.user_profiles`` -- the view that publishes the public
    columns of an account to every signed-in session. ``public.users`` itself is
    own-row for the request path below moderator, so a query there answers for
    nobody; the projection is what that view is for, and it is the same one the
    people roster and every other surface that draws a person reads.

    All of them in one question. The list is not paginated and nothing bounds
    how many conversations an account has, so a query each is a round trip each.
    """
    wanted = sorted(set(member_ids))
    if not wanted:
        return {}
    rows = (
        await session.exec(
            text(
                "SELECT id, username, discriminator, avatar_url, profile_decorations "
                "FROM public.user_profiles WHERE id = ANY(:ids)"
            ).bindparams(ids=wanted)
        )
    ).all()
    return {
        row[0]: DmRosterMember(
            user_id=row[0],
            username=row[1],
            discriminator=row[2],
            avatar_url=row[3],
            profile_decorations=row[4] or {},
            presence=presence_service.online.presence_of(row[0]),
        )
        for row in rows
    }


async def list_conversations(
    session: AsyncSession, *, user_id: int
) -> list[DmConversationRead]:
    """Every conversation this account is named on, newest first.

    Named on, not only on: an invitation waiting to be answered is in the list,
    because somewhere to answer it is the point. It is marked ``pending`` so a
    client can tell the two apart.
    """
    mine = select(DmConversationMember.conversation_id).where(
        DmConversationMember.user_id == user_id
    )
    rows = list(
        (
            await session.exec(
                select(
                    DmConversation,
                    DmConversationMember.user_id,
                    DmConversationMember.accepted_at,
                )
                .join(
                    DmConversationMember,
                    DmConversationMember.conversation_id == DmConversation.id,
                )
                .where(DmConversation.id.in_(mine))
                .order_by(DmConversation.created_at.desc())
            )
        ).all()
    )

    # One row per member came back; fold them into one entry per conversation,
    # in the order the query already put them.
    conversations: dict[uuid.UUID, DmConversation] = {}
    others: dict[uuid.UUID, list[int]] = {}
    pending: dict[uuid.UUID, bool] = {}
    for conversation, member_id, accepted_at in rows:
        conversations.setdefault(conversation.id, conversation)
        if member_id == user_id:
            pending[conversation.id] = accepted_at is None
        else:
            others.setdefault(conversation.id, []).append(member_id)

    people = await _people_on(
        session, [member_id for roster in others.values() for member_id in roster]
    )

    listed = []
    for conversation_id, conversation in conversations.items():
        roster = sorted(others.get(conversation_id, []))
        if not roster:
            # Everybody else has gone. There is nobody to send to, so it is not
            # a conversation any more.
            continue
        listed.append(
            DmConversationRead(
                id=conversation.id,
                other_user_id=roster[0],
                created_at=conversation.created_at,
                kind=str(conversation.kind),
                member_ids=roster,
                members=[
                    people[member_id] for member_id in roster if member_id in people
                ],
                pending=pending.get(conversation_id, False),
            )
        )
    return listed


async def _has_accepted(
    session: AsyncSession, *, conversation_id: uuid.UUID, user_id: int
) -> bool:
    """Whether this account has answered its own invitation to this thread."""
    return (
        await session.exec(
            select(DmConversationMember.user_id).where(
                DmConversationMember.conversation_id == conversation_id,
                DmConversationMember.user_id == user_id,
                DmConversationMember.accepted_at.is_not(None),
            )
        )
    ).first() is not None


async def _other_members(
    session: AsyncSession, *, conversation_id: uuid.UUID, user_id: int
) -> list[int]:
    """Everybody on the conversation except the caller, oldest membership first.

    Accepted members only: somebody who has been asked and has not answered is
    on no roster yet, and nothing is written for them.
    """
    return list(
        (
            await session.exec(
                select(DmConversationMember.user_id)
                .where(
                    DmConversationMember.conversation_id == conversation_id,
                    DmConversationMember.user_id != user_id,
                    DmConversationMember.accepted_at.is_not(None),
                )
                .order_by(DmConversationMember.joined_at, DmConversationMember.user_id)
            )
        ).all()
    )


async def leave_conversation(
    session: AsyncSession, *, user_id: int, conversation_id: uuid.UUID
) -> None:
    """Take this account off a conversation.

    **A conversation down to one member releases its roster name.** One person
    left on it has nobody to send to, so the thread is over — and holding its
    name would mean the two of them could never open a channel again, because
    the name is what a new one would be filed under. Releasing it leaves them
    free to start afresh, which is what leaving and asking again did before a
    roster was an identity.

    A roster with two or more still on it keeps its name. The thread is alive
    for them and the name is how they find it.

    Released before the membership row goes, because it is an act by somebody
    who is still on the conversation.
    """
    conversation = await session.get(DmConversation, conversation_id)
    if conversation is None:
        raise DmTransportError(Messages.CONVERSATION_NOT_FOUND)
    remaining = await _other_members(
        session, conversation_id=conversation_id, user_id=user_id
    )
    if len(remaining) < 2:
        await session.exec(
            update(DmConversation)
            .where(DmConversation.id == conversation_id)
            .values(roster_key=None)
        )
    await session.exec(
        delete(DmConversationMember).where(
            DmConversationMember.conversation_id == conversation_id,
            DmConversationMember.user_id == user_id,
        )
    )
    await session.flush()


# --------------------------------------------------------------------------
# The queue
# --------------------------------------------------------------------------


async def _device_owners(
    session: AsyncSession, device_ids: set[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Which account each destination device belongs to.

    Only the devices the caller may see — their own, and those of accounts they
    may message. One that does not come back is a device they have no business
    encrypting to, and its copy is dropped rather than refused, so it is not
    tellable apart from a copy an ignore dropped.
    """
    if not device_ids:
        return {}
    rows = (
        await session.exec(
            select(DmDevice.id, DmDevice.user_id).where(DmDevice.id.in_(device_ids))
        )
    ).all()
    return {device_id: owner for device_id, owner in rows}


async def send(
    session: AsyncSession,
    *,
    user_id: int,
    conversation_id: uuid.UUID,
    messages: list[DmOutboundMessage],
) -> DmSendOutcome:
    """Write one already-encrypted copy to every device that should get it.

    The sender's own devices are always written to, so their other clients
    render their own outbox. Everybody else's are written to only where
    ``dm_deliverable`` says so, and the sender is told the same thing either
    way — the count answered is what they handed over, and it does not move
    when a copy is dropped.

    **A send is refused only where it can reach nobody.** One member of a roster
    being out of reach, or holding a full mailbox, does not stop the rest
    hearing it; a pair is the case where the one recipient is everybody, so the
    refusals that were right for a pair are still exactly what a pair gets.

    The two refusals say different things and are kept apart. Being out of reach
    is read from the *apparent* permission, which the sender can ask for
    directly, so refusing on it tells them nothing new. A full mailbox is a fact
    about capacity, and the recipients it happened to are named in the outcome.
    Neither is ever read from ``dm_deliverable``, because that is the one that
    knows about ignores.
    """
    conversation = await session.get(DmConversation, conversation_id)
    if conversation is None:
        raise DmTransportError(Messages.CONVERSATION_NOT_FOUND)
    # The sender has to be on it themselves. Somebody who has been asked and has
    # not answered can see the conversation — that is how they decide — and
    # refusing here is what keeps "seeing it" and "being on it" different
    # things. Answered the way a conversation they are not on is answered.
    if not await _has_accepted(
        session, conversation_id=conversation_id, user_id=user_id
    ):
        raise DmTransportError(Messages.CONVERSATION_NOT_FOUND)

    # Everybody else on it who has answered, which may be nobody — a roster
    # whose invitations are all outstanding, or a pair the other side has left.
    # Not a refusal: the sender's own copies still land in their own outbox, and
    # anything addressed to somebody not on it is dropped the way every other
    # undeliverable copy is.
    roster = set(
        await _other_members(session, conversation_id=conversation_id, user_id=user_id)
    )

    owners = await _device_owners(
        session, {message.recipient_device_id for message in messages}
    )

    # Decode and attribute the whole bundle before anything is written: an
    # oversized copy fails the send, and who is addressed decides which
    # mailboxes are locked.
    decoded: list[tuple[DmOutboundMessage, bytes, int | None]] = []
    for message in messages:
        raw = _decode(message.payload)
        if len(raw) > MAX_PAYLOAD_BYTES:
            raise DmTransportError(Messages.MESSAGE_TOO_LARGE)
        decoded.append((message, raw, owners.get(message.recipient_device_id)))

    addressed = {owner for _m, _raw, owner in decoded if owner in roster}
    reachable = False
    for recipient in addressed:
        if await _permission(session, recipient) == "open":
            reachable = True
            break
    if addressed and not reachable:
        raise DmTransportError(Messages.NOT_REACHABLE)

    deliverable = {
        recipient for recipient in addressed if await _deliverable(session, recipient)
    }

    incoming: dict[int, int] = {}
    for _message, raw, owner in decoded:
        if owner in deliverable:
            incoming[owner] = incoming.get(owner, 0) + len(raw)

    # Two sends to the same near-full mailbox would otherwise both read the old
    # total and both pass. Taken in a fixed order because two sends into
    # overlapping rosters take the same mailboxes, and taking them in different
    # orders is how each ends up waiting on the other.
    for recipient in sorted(incoming):
        await advisory_lock(session, LockNamespace.DM_QUEUE, recipient)
    full = {
        recipient
        for recipient in sorted(incoming)
        if await _queue_bytes(session, recipient) + incoming[recipient]
        > QUEUE_CEILING_BYTES
    }
    if incoming and full == set(incoming):
        # Nobody addressed could take it. Refusing is honest; accepting a
        # message we mean to drop later is not.
        raise DmTransportError(Messages.RECIPIENT_QUEUE_FULL)

    rows = []
    reached: set[int] = set()
    for message, raw, owner in decoded:
        if owner == user_id:
            pass  # An account's own copies always land; they are its outbox.
        elif owner in deliverable and owner not in full:
            reached.add(owner)
        else:
            continue
        rows.append(
            {
                "conversation_id": conversation_id,
                "recipient_device_id": message.recipient_device_id,
                "message_type": message.message_type,
                "payload": raw,
            }
        )

    if rows:
        # A Core insert, deliberately: the ORM would ask for the new id back,
        # and nothing here needs it.
        now = datetime.now(UTC)
        await session.exec(
            insert(DmQueueItem).values([{**row, "created_at": now} for row in rows])
        )
    await session.flush()
    return DmSendOutcome(
        accepted=len(messages),
        reached=tuple(sorted(reached)),
        queue_full=tuple(sorted(full)),
        group=conversation.kind == DmConversationKind.group,
    )


async def _claim_session(
    session: AsyncSession,
    *,
    user_id: int,
    device_id: uuid.UUID,
    session_id: uuid.UUID,
) -> None:
    """Leave this sign-in named by exactly one of the account's key stores.

    Scoped to the account's own rows: a sign-in belongs to one account, and the
    one being claimed is the one that authenticated the call.
    """
    await session.exec(
        update(DmDevice)
        .where(
            DmDevice.user_id == user_id,
            DmDevice.id != device_id,
            DmDevice.session_id == session_id,
        )
        .values(session_id=None)
    )


async def follow_session(
    session: AsyncSession, *, from_id: uuid.UUID, to_id: uuid.UUID
) -> None:
    """Move the key store one session named to the session taking its place.

    Called wherever a session is succeeded, beside the push registrations, so a
    key store and its device's push row go on naming the same live sign-in.
    Does not commit: it lands with the session change.
    """
    await session.exec(
        update(DmDevice).where(DmDevice.session_id == from_id).values(session_id=to_id)
    )


async def collect(
    session: AsyncSession,
    *,
    user_id: int,
    device_id: uuid.UUID,
    session_id: uuid.UUID | None = None,
    after: int | None = None,
) -> DmQueueResponse:
    """What is waiting for one device, oldest first, a page at a time.

    The order is not a nicety. A ratchet keeps a bounded number of skipped
    message keys, so handing them over in the order they were written is what
    keeps a client able to read them.

    ``after`` is the last id of the page before, and ``more`` says another page
    follows. A device may leave a message here that it cannot read yet -- one
    from a device of its account's that is waiting to be verified -- so a
    collection pages past those rather than reading the same first page again.

    Collecting is also where the key store learns which sign-in it is under. A
    device registers once and never again, so the link cannot only be written
    at registration: a device signed in again since would stay unwakeable for
    the rest of its life. Every poll re-states it instead.

    One sign-in holds one key store, and taking the link moves it rather than
    copying it. Two key stores naming the same sign-in cannot both be woken --
    a push would go to the one device either way -- so the one that is no
    longer collecting under it would look linked while silently receiving
    nothing.
    """
    device = await _own_device(session, user_id=user_id, device_id=device_id)
    if session_id is not None and device.session_id != session_id:
        await _claim_session(
            session, user_id=user_id, device_id=device_id, session_id=session_id
        )
        device.session_id = session_id
    rows = list(
        (
            await session.exec(
                select(DmQueueItem)
                .where(
                    DmQueueItem.recipient_device_id == device_id,
                    DmQueueItem.id > (after or 0),
                )
                .order_by(DmQueueItem.id)
                .limit(QUEUE_PAGE + 1)
            )
        ).all()
    )
    device.last_seen_at = datetime.now(UTC)
    session.add(device)
    await session.flush()
    return DmQueueResponse(
        items=[
            DmQueueItemRead(
                id=row.id,
                conversation_id=row.conversation_id,
                message_type=row.message_type,
                payload=_encode_ciphertext(row.payload),
                created_at=row.created_at,
            )
            for row in rows[:QUEUE_PAGE]
        ],
        more=len(rows) > QUEUE_PAGE,
    )


async def acknowledge(
    session: AsyncSession,
    *,
    user_id: int,
    device_id: uuid.UUID,
    message_ids: list[int],
) -> int:
    """Delete what this device has taken. Collection is what empties the queue."""
    await _own_device(session, user_id=user_id, device_id=device_id)
    result = await session.exec(
        delete(DmQueueItem).where(
            DmQueueItem.recipient_device_id == device_id,
            DmQueueItem.id.in_(message_ids),
        )
    )
    await session.flush()
    return result.rowcount or 0


# --------------------------------------------------------------------------
# Verification between one account's own devices
# --------------------------------------------------------------------------


async def _clear_expired_verifications(
    session: AsyncSession, *, user_id: int, cutoff: datetime
) -> None:
    await session.exec(
        delete(DmVerificationItem).where(
            DmVerificationItem.user_id == user_id,
            DmVerificationItem.created_at < cutoff,
        )
    )


async def send_verification(
    session: AsyncSession,
    *,
    user_id: int,
    device_id: uuid.UUID,
    to_device_id: uuid.UUID,
    body: str,
) -> None:
    """Relay one verification message from one of the caller's devices to
    another of them. ``body`` is stored as the client wrote it."""
    if device_id == to_device_id:
        raise DmTransportError(Messages.VERIFY_SAME_DEVICE)
    await _own_device(session, user_id=user_id, device_id=device_id)
    await _own_device(session, user_id=user_id, device_id=to_device_id)
    # Held to the end of the transaction, so two sends from one account count
    # and insert one after the other.
    await advisory_lock(session, LockNamespace.DM_VERIFICATION, user_id)
    await _clear_expired_verifications(
        session,
        user_id=user_id,
        cutoff=datetime.now(UTC) - VERIFICATION_TTL,
    )
    waiting = (
        await session.exec(
            select(func.count())
            .select_from(DmVerificationItem)
            .where(DmVerificationItem.user_id == user_id)
        )
    ).one()
    if waiting >= VERIFICATION_OUTSTANDING:
        raise DmTransportError(Messages.TOO_MANY_VERIFICATIONS)
    await session.exec(
        insert(DmVerificationItem).values(
            user_id=user_id,
            sender_device_id=device_id,
            recipient_device_id=to_device_id,
            body=body,
        )
    )
    await session.flush()


async def collect_verification(
    session: AsyncSession, *, user_id: int, device_id: uuid.UUID
) -> list[DmVerificationMessage]:
    """Everything waiting for one device, oldest first.

    Collecting consumes: what is returned is deleted in the same statement, so
    there is nothing to acknowledge afterwards.
    """
    await _own_device(session, user_id=user_id, device_id=device_id)
    cutoff = datetime.now(UTC) - VERIFICATION_TTL
    rows = (
        await session.exec(
            delete(DmVerificationItem)
            .where(DmVerificationItem.recipient_device_id == device_id)
            .returning(
                DmVerificationItem.id,
                DmVerificationItem.sender_device_id,
                DmVerificationItem.body,
                DmVerificationItem.created_at,
            )
        )
    ).all()
    await _clear_expired_verifications(session, user_id=user_id, cutoff=cutoff)
    await session.flush()
    return [
        DmVerificationMessage(
            id=row.id,
            sender_device_id=row.sender_device_id,
            body=row.body,
            created_at=row.created_at,
        )
        for row in sorted(rows, key=lambda row: row.id)
        if row.created_at >= cutoff
    ]
