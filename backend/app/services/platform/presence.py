"""Who has Initiative open — the person, not the place.

Presence is a fact about an account, not about a guild: someone with a tab open
is online whether that tab is a guild they share with whoever is asking, a
guild they don't, or no guild at all. So it lives here rather than inside any
one channel's connection manager, and every channel that proves a person is
present feeds the same roll.

Two do. The guild events socket (``app.services.content_sockets``) only exists
while a tab sits inside a guild. The notification stream
(``app.services.platform.notification_stream``) has no guild in its address and
is open on every page for as long as someone is signed in, which is what makes
it the signal that actually answers the question.

It takes three facts to say how someone appears, and the roll holds all three
so that "how does this person appear" is one lookup with one answer, rather
than a rule each of the several surfaces that draw a dot would have to apply
for itself:

* whether anything is open, which only the sockets know;
* what the person picked — ``users.presence``, which is a column because it
  outlives every socket. Two things carry it here: a connecting socket, which
  read the row at some point on its way in, and the endpoint that writes it.
  Neither is reliably the later one, so each says *when* it learned what it
  knows and the later knowledge wins;
* when they last did something, which is what separates someone at their
  keyboard from someone who left a tab open. That only ever narrows ``online``
  — to ``idle`` — because every other value is something a person said, and an
  inference does not talk over a statement. Picking ``idle`` outright is one of
  those statements, and holds however busy the keyboard is.

Bounded the way the other in-memory rolls are: these are one process's own
sockets. Where the API runs as more than one worker each holds a share, so this
can say "offline" about someone another worker is serving — the direction that
tells a reader less rather than more.
"""

from time import monotonic

from app.db.request_context import Unattributed
from app.models.platform.user import Presence

#: How long a person's tabs go without a sign of them before they read as idle.
#: Long enough to sit through reading a file, short enough that a tab left
#: open overnight does not claim someone is at it.
IDLE_AFTER_SECONDS = 10 * 60


class OnlineRoll:
    """Counted per user rather than per socket, so two tabs are one person."""

    def __init__(self) -> None:
        # user_id -> how many of that user's sockets are open on this process.
        self._sockets: dict[int, int] = {}
        # user_id -> (what they picked, when this roll learned it). The second
        # half is what settles a disagreement between the two things that say
        # so — see ``_learned``.
        #
        # Accounts seen since the last flush, waiting to be written down.
        # Separate from ``_last_active`` because that is cleared when the last
        # socket goes, and somebody who looked in and left is exactly whose
        # visit still has to be recorded.
        self._pending: set[int] = set()
        # Kept past the last socket, deliberately: a choice made with nothing
        # open is exactly the one a connect already in flight must not undo.
        # It is one small entry per account this process has seen.
        self._chosen: dict[int, tuple[Presence, float]] = {}
        # user_id -> monotonic time of the last sign of them. Monotonic because
        # only the gap matters, and a clock that steps must not move it.
        self._last_active: dict[int, float] = {}

    def _learned(self, user_id: int, chosen: Presence, known_at: float) -> None:
        """Record a choice, unless this roll already knows a later one.

        The two callers learn it at different points: a socket reads the column
        somewhere on its way in, and a write knows it at the commit. Either can
        reach the roll second, so what is compared is when each *learned* its
        value rather than when it got here — otherwise a connect that started
        before a change could land after it and put the old value back.
        """
        known = self._chosen.get(user_id)
        if known is not None and known[1] > known_at:
            return
        self._chosen[user_id] = (chosen, known_at)

    def arrived(
        self,
        user_id: int,
        chosen: Presence = Presence.online,
        *,
        known_at: float | None = None,
    ) -> None:
        """Register a socket, and the column value it read on the way in.

        ``known_at`` is a ``monotonic()`` reading taken *before* that read, so
        it is never later than the state the socket is carrying. Left out, the
        value is treated as read now.
        """
        self._sockets[user_id] = self._sockets.get(user_id, 0) + 1
        self._learned(user_id, chosen, monotonic() if known_at is None else known_at)
        # Opening a tab is somebody doing something.
        self._last_active[user_id] = monotonic()
        self._pending.add(user_id)

    def left(self, user_id: int) -> None:
        remaining = self._sockets.get(user_id, 0) - 1
        if remaining > 0:
            self._sockets[user_id] = remaining
        else:
            self._sockets.pop(user_id, None)
            self._last_active.pop(user_id, None)

    def chose(self, user_id: int, chosen: Presence) -> None:
        """Follow a change to the column, as the endpoint that wrote it commits.

        Recorded whether or not anything is open. Someone with no sockets
        appears offline either way, but the record is what stops a connect
        already on its way in from arriving with the value it read first.
        """
        self._learned(user_id, chosen, monotonic())

    def active(self, user_id: int) -> None:
        """Note a sign of them, from any one of their tabs.

        Per user rather than per socket: a person reading in one window is at
        their keyboard whatever the other windows are doing, and the newest
        sign of them is the one that answers that.
        """
        if user_id in self._sockets:
            self._last_active[user_id] = monotonic()
            self._pending.add(user_id)

    def drain_pending(self) -> set[int]:
        """Take the accounts seen since the last call, and start again.

        This roll is already the buffer the durable stamp needs: it is told
        every time somebody does something, and it is per-process, so draining
        it once a minute is one statement instead of one per sign of life.
        """
        pending, self._pending = self._pending, set()
        return pending

    def presence_of(self, user_id: int) -> Presence:
        """How this account appears to anyone reading it right now."""
        if user_id not in self._sockets:
            return Presence.offline
        known = self._chosen.get(user_id)
        chosen = known[0] if known is not None else Presence.online
        if chosen is not Presence.online:
            return chosen
        since = monotonic() - self._last_active.get(user_id, 0.0)
        return Presence.idle if since >= IDLE_AFTER_SECONDS else Presence.online

    def shown(self) -> dict[int, Presence]:
        """Everyone this process sees as here, and how each appears.

        Bounded by the open sockets, so a roster can ask the database who is
        here among its members without asking about every member.
        """
        appearing = {}
        for user_id in self._sockets:
            presence = self.presence_of(user_id)
            if presence is not Presence.offline:
                appearing[user_id] = presence
        return appearing


#: The one roll every channel feeds and every reader asks.
online = OnlineRoll()


#: How often what this roll has seen is written down. Well inside
#: :data:`IDLE_AFTER_SECONDS`, so a continuously busy account's stamp is never
#: stale enough to read as away.
ACTIVITY_FLUSH_SECONDS = 60

#: How long a stamp stands before it is worth rewriting. Delivery only ever
#: asks whether somebody was here within the idle window, so a finer record
#: would cost writes to answer a question nobody asks.
ACTIVITY_STAMP_MIN_GAP_SECONDS = 300


async def process_activity_flush() -> None:
    """Write down who has been at their keyboard.

    The roll above is one process's own memory, and delivery routinely decides
    in another — a background worker, a second API process. This is the part
    that crosses that gap: a single statement, throttled in its own WHERE so a
    busy client cannot turn one person into a stream of writes.

    Best effort throughout. A flush that fails costs at most one window of
    knowing somebody was here, and the rule that reads it treats not knowing as
    them being away, which is the direction that delivers rather than holds.
    """
    from sqlalchemy import text

    from app.db.session import SystemSessionLocal, set_rls_context

    user_ids = sorted(online.drain_pending())
    if not user_ids:
        return
    async with SystemSessionLocal() as session:
        await set_rls_context(session, Unattributed())
        await session.exec(
            text(
                "UPDATE users SET last_active_at = now() "
                "WHERE id = ANY(:ids) AND (last_active_at IS NULL "
                "  OR last_active_at < now() - make_interval(secs => :gap))"
            ).bindparams(ids=user_ids, gap=ACTIVITY_STAMP_MIN_GAP_SECONDS)
        )
        await session.commit()
