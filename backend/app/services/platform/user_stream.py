"""The per-user channel, and the bus behind it.

How a frame reaches every tab one person has open, wherever they are —
including from a worker that is not the one holding the socket. The sockets
themselves are the account sockets in :mod:`app.services.content_sockets`,
each in its account's room with its own outbox, so a send here is an enqueue
and never waits on a reader.

Four channels sit on this: :mod:`~app.services.platform.notification_stream`
(the inbox moved), :mod:`~app.services.platform.account_stream` (your standing
changed), :mod:`~app.services.platform.contacts_stream` and
:mod:`~app.services.platform.dm_stream`. They send the same shape and none owns
the machinery, so there is one place to look when a frame does not arrive.

Every frame is a **content-free invalidation signal**: it says something you can
already read has changed, never what it now says. The client refetches through
the ordinary authorized endpoint, and that request is the only decision point.
So the worst a routing mistake here can do is cost somebody a wasted refetch.

Delivery is two paths, and the split is deliberate:

* **Local** — this worker's own sockets, always, straight from the hook that
  runs once the writing transaction commits.
* **Cross-process** — ``pg_notify`` on a dedicated connection, picked up by
  every other worker's listener. One notice names every reader a frame is for
  (up to ``IDS_PER_NOTICE``), so a transaction that signals a whole
  community's members costs a few notices, not one per member.

The local path is what makes this fail-soft. Where the bus cannot be reached the
cross-process half is simply absent and everything behaves as it did before it
existed; nothing waits on it and nothing breaks when it is missing. Each process
stamps frames with its own ``origin`` and skips its own on the way back in, so
the two paths never deliver twice.

**A bus that was down is a gap in both directions**, and coming back up is the
only notice of it. So ``on_bus_connected`` does two things: it sends the frames
whose cross-process half was refused while the bus was away — content-free, so
a user with fifty missed frames is one frame — and it tells this process's own
sockets to re-read everything, because what they missed while nothing was
listening here is not knowable. That is what lets the client hold no timer of
its own for the connected case.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional

from app.db import post_commit

logger = logging.getLogger(__name__)

#: The key a transaction's frames are registered under, as one step that sends
#: each kind of frame to all its readers at once.
_FRAMES_KEY = "user_stream_frames"

#: Readers named in one notice. ``pg_notify`` refuses a payload of 8000 bytes
#: or more; this many ids and a frame stay well under it.
IDS_PER_NOTICE = 500

#: The Postgres channel every worker listens on. One channel for both callers:
#: the frames are tiny and each names its own resource, so splitting them would
#: buy a second listener and no clarity.
CHANNEL = "user_stream"

#: Who this process is. Stamped on every frame we publish so our own listener
#: can tell our echo from somebody else's news and drop it.
ORIGIN = uuid.uuid4().hex

#: A frame that names no channel: everything this socket follows may have moved.
#: Sent where the gap is real but its contents are not knowable — the client
#: answers it with the same catch-up it does on its own reconnect.
RESOURCE_RESYNC = "resync"

#: Frames whose cross-process half was refused, keyed so that repeats collapse:
#: the frames carry no content, so "your inbox changed" twice is once. Bounded,
#: because a bus that stays down must not grow this without limit — past the
#: bound the far side is brought up to date by its own reconnect instead.
_pending_remote: Dict[tuple[int, str], Dict[str, Any]] = {}
MAX_PENDING_REMOTE = 2048

#: Whether the bound above was reached, which is the one case where what was
#: refused cannot be replayed: the frames past it were never kept, so who to
#: tell is not knowable. Answered by telling everyone.
_dropped_remote = False


def build_frame(
    resource: str, action: str, ids: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    """The shape both channels send.

    ``ids`` names what to refetch and nothing about it; for a channel addressed
    by *who is asking* it is empty, because there is nothing to name.
    """
    return {
        "resource": resource,
        "action": action,
        "ids": ids or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def publish(user_ids: Iterable[int], frame: Dict[str, Any]) -> None:
    """Deliver one frame to these users, wherever their tabs are.

    Local sockets first and unconditionally, then the bus for everybody else's
    worker. The order matters only in that the local half must not be able to
    fail because of the remote one.
    """
    user_ids = list(user_ids)
    _deliver_local(user_ids, frame)
    await _publish_remote(user_ids, frame)


def _deliver_local(user_ids: Optional[Iterable[int]], frame: Dict[str, Any]) -> None:
    """Queue the frame on this process's sockets for these users, or for every
    account socket here when ``user_ids`` is ``None``."""
    from app.services.content_sockets import account_room, sockets

    for user_id in sockets.account_ids() if user_ids is None else user_ids:
        sockets.emit_json(account_room(user_id), frame)


async def _publish_remote(user_ids: list[int], frame: Dict[str, Any]) -> None:
    """Hand the frame to the other workers, if we can reach them.

    A bus we cannot reach is not an error anybody can act on — the frame was
    already delivered to every socket this process holds, and the client keeps
    a backstop refetch for exactly this. So it is logged once at debug and the
    request carries on.
    """
    from app.services.platform import notify_bus

    global _dropped_remote
    for start in range(0, len(user_ids), IDS_PER_NOTICE):
        chunk = user_ids[start : start + IDS_PER_NOTICE]
        try:
            await notify_bus.notify(
                CHANNEL,
                json.dumps({"origin": ORIGIN, "user_ids": chunk, "frame": frame}),
            )
        except Exception:
            logger.debug(
                "user_stream: cross-process publish unavailable", exc_info=True
            )
            for user_id in chunk:
                if len(_pending_remote) < MAX_PENDING_REMOTE:
                    _pending_remote[(user_id, frame.get("resource", ""))] = frame
                else:
                    _dropped_remote = True


async def deliver_remote(payload: str) -> None:
    """Take a frame off the bus and give it to this worker's sockets.

    Skips our own echo: we already delivered it locally before publishing, and
    delivering it again would double every frame on a single-worker install.
    """
    try:
        message = json.loads(payload)
        origin = message["origin"]
        raw_user_ids = message["user_ids"]
        frame = message["frame"]
        # ``None`` is addressed to nobody in particular, which means everybody:
        # a frame was owed and whose it was could not be said.
        user_ids = None if raw_user_ids is None else [int(u) for u in raw_user_ids]
    except Exception:
        logger.warning("user_stream: unreadable frame on %s", CHANNEL)
        return
    if origin == ORIGIN:
        return
    _deliver_local(user_ids, frame)


async def _publish_to_everyone(frame: Dict[str, Any]) -> bool:
    """One frame for every socket on every other worker, and whether it went.

    For the case where a frame is owed and whose it was cannot be said. Costs
    each connected reader one refetch, which is why nothing routine uses it —
    and why the caller has to know whether it landed.
    """
    from app.services.platform import notify_bus

    try:
        await notify_bus.notify(
            CHANNEL, json.dumps({"origin": ORIGIN, "user_ids": None, "frame": frame})
        )
        return True
    except Exception:
        logger.debug("user_stream: cross-process publish unavailable", exc_info=True)
        return False


async def publish_to_everyone(frame: Dict[str, Any]) -> None:
    """``frame`` for every connected reader, on this worker and the others.

    For a change every account's answer is read from, such as a deployment
    rule. Each reader refetches once, so it is for rare writes only. Where the
    bus refuses it, everybody is told again once it is back.
    """
    global _dropped_remote

    _deliver_local(None, frame)
    if not await _publish_to_everyone(frame):
        _dropped_remote = True


async def on_bus_connected() -> None:
    """The bus is up, so it was down, and both directions of it were.

    Outward: the frames it refused go now, so a tab on another worker is not
    left waiting on a signal that was dropped rather than delayed. Where more
    was refused than could be held, the frames past the bound were never kept —
    so who is owed one cannot be said, and everybody is told instead.

    Inward: this process heard nothing while it was away and cannot know what,
    so its own sockets are told to re-read. One frame each — the same catch-up
    they run when their own socket reconnects.
    """
    global _dropped_remote

    pending = dict(_pending_remote)
    _pending_remote.clear()
    for user_ids, frame in _grouped(pending):
        # Through the ordinary path, so one that is refused again is simply
        # pending again rather than lost on the way to being recovered.
        await _publish_remote(user_ids, frame)

    resync = build_frame(RESOURCE_RESYNC, "changed")
    # Cleared only once it has gone. A bus that fails again while this is
    # recovering leaves the mark standing for the next time it comes up —
    # the same rule the refused frames above follow by re-queueing.
    if _dropped_remote and await _publish_to_everyone(resync):
        _dropped_remote = False
    _deliver_local(None, resync)


def queue_frame(
    session: Any, user_id: int | None, frame: Dict[str, Any]
) -> Dict[str, Any] | None:
    """Note a frame this session has earned but not yet committed.

    Nothing is sent here — the frames go once the transaction commits, so a
    rollback pokes nobody, and a savepoint's rollback drops the frames queued
    inside it. A frame that arrived before the COMMIT would hand the client
    the state it is replacing, and nothing polls behind it closely enough to
    correct that.

    One frame per user **per channel** per transaction: a transaction writing
    three notifications pokes the inbox once, because every frame means the
    same thing ("refetch") and three would buy three identical requests. The
    first recorded wins, so a read-state change queued behind a creation does
    not downgrade it. Keyed by channel as well as by user, since an inbox frame
    and an account frame say different things and both are owed.

    ``session`` may be an ``AsyncSession`` or a sync session.

    Returns the frame that will be sent, so a channel whose frames name things
    can add to it.
    """
    if user_id is None:
        return None
    frames = post_commit.after_commit(session, _Frames(), key=_FRAMES_KEY)
    return frames.setdefault((user_id, frame["resource"]), frame)


def queue_signals(
    session: Any, user_ids: Iterable[int], resource: str, action: str = "changed"
) -> None:
    """Note one channel's signal for each of a set of accounts.

    Deliberately not narrowed to this process's own sockets. That narrowing
    would have to happen before ``publish``, which is also what puts a frame
    on the cross-worker bus — so an account connected only to another worker
    would never be published for at all. Callers pass the whole set they mean.
    """
    for user_id in user_ids:
        queue_frame(session, user_id, build_frame(resource, action))


class _Frames(dict[tuple[int, str], Dict[str, Any]]):
    """One transaction's frames, keyed by ``(user_id, resource)``."""

    def join(self, released: Mapping[tuple[int, str], Dict[str, Any]]) -> None:
        """Take a released savepoint's frames: each one this lacks, and for one
        it holds already, what the savepoint's names beside its own."""
        for key, frame in released.items():
            held = self.setdefault(key, frame)
            if held is frame:
                continue
            for kind, named in frame["ids"].items():
                kept = held["ids"].setdefault(kind, [])
                kept.extend(item for item in named if item not in kept)

    async def __call__(self) -> None:
        await asyncio.gather(
            *(publish(user_ids, frame) for user_ids, frame in _grouped(self))
        )


def _grouped(
    frames: Mapping[tuple[int, str], Dict[str, Any]],
) -> list[tuple[list[int], Dict[str, Any]]]:
    """Frames that say the same thing, each with every reader it is for."""
    groups: Dict[str, tuple[list[int], Dict[str, Any]]] = {}
    for (user_id, _resource), frame in frames.items():
        said = json.dumps(
            [frame.get("resource"), frame.get("action"), frame.get("ids")],
            sort_keys=True,
        )
        groups.setdefault(said, ([], frame))[0].append(user_id)
    return list(groups.values())
