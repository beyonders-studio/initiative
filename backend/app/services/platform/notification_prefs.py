"""Resolving "does this person want to hear about this, on this channel".

One function, one order, read by every delivery path. The settings document is
sparse, so almost every call falls through to a registry default without
touching a key.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from enum import Enum
from typing import Any, Mapping, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.notification_categories import (
    CATEGORY_SPECS,
    Channel,
    NotificationCategory,
)
from app.models.platform.user_notification_prefs import (
    DigestCadence,
    EmailCadence,
    UserNotificationPrefs,
)
from app.services.platform.presence import IDLE_AFTER_SECONDS
from app.core.user_input_validators import resolve_zone

#: An account with no row and no keys — every default, nothing overridden.
EMPTY: dict[str, Any] = {}


def _section(prefs: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = prefs.get(key)
    return value if isinstance(value, Mapping) else {}


def _guild_section(prefs: Mapping[str, Any], guild_id: int | None) -> Mapping[str, Any]:
    if guild_id is None:
        return {}
    # JSON object keys are strings, so the guild id is stringified on the way in
    # and on the way out.
    return _section(_section(prefs, "guilds"), str(guild_id))


def is_muted(prefs: Mapping[str, Any], guild_id: int | None) -> bool:
    """Whether the account muted this community. Not unless it said so, which
    is what makes a newly joined community need no write."""
    return _guild_section(prefs, guild_id).get("muted") is True


def row_is_off(
    prefs: Mapping[str, Any], guild_id: int, category: NotificationCategory
) -> bool:
    """Whether the account switched this row off in this community: every
    channel it could switch is off there."""
    spec = CATEGORY_SPECS[category]
    section = _guild_section(prefs, guild_id)
    return bool(spec.mutable_channels) and all(
        _override(section, category, channel) is False
        for channel in spec.mutable_channels
    )


def _override(
    section: Mapping[str, Any],
    category: NotificationCategory,
    channel: Channel,
) -> Optional[bool]:
    value = _section(_section(section, "categories"), category.value).get(channel.value)
    return value if isinstance(value, bool) else None


def wants(
    prefs: Mapping[str, Any] | None,
    *,
    category: NotificationCategory,
    channel: Channel,
    guild_id: int | None = None,
) -> bool:
    """Whether this account wants ``category`` on ``channel``.

    Most specific first:

    1. a category with nothing to switch, which is not a preference at all
    2. the community's mute, where the category belongs to a community
    3. a per-community override for this category and channel: a row the
       account switched off in that community
    4. the account-wide override
    5. the category's default from the registry

    The mute is checked before the rest because it is the account's
    deliberate statement about one community, and it means nothing at all —
    including a direct mention. It cannot reach a category that belongs to no
    community, so an account notice arrives however the communities are set.
    """
    prefs = prefs or EMPTY
    spec = CATEGORY_SPECS[category]

    if not spec.mutable_channels:
        return True

    if spec.guild_scoped and is_muted(prefs, guild_id):
        return False

    # A channel the account cannot switch off is on, and no override for it is
    # read — a stale key from an earlier shape must not decide anything.
    if not spec.is_mutable(channel):
        return True

    if spec.guild_scoped and guild_id is not None:
        override = _override(_guild_section(prefs, guild_id), category, channel)
        if override is not None:
            return override

    override = _override(prefs, category, channel)
    if override is not None:
        return override

    return spec.defaults[channel]


# --- Quiet hours -------------------------------------------------------------


def _parse_clock(raw: Any) -> Optional[time]:
    if not isinstance(raw, str):
        return None
    try:
        hour, minute = raw.split(":", 1)
        return time(hour=int(hour), minute=int(minute))
    except (ValueError, TypeError):
        return None


def quiet_hours(prefs: Mapping[str, Any] | None) -> Optional[tuple[time, time]]:
    """The account's nightly window, or None where it has not set one."""
    section = _section(prefs or EMPTY, "quiet_hours")
    start = _parse_clock(section.get("start"))
    end = _parse_clock(section.get("end"))
    if start is None or end is None or start == end:
        return None
    return start, end


def in_quiet_hours(
    prefs: Mapping[str, Any] | None,
    *,
    tz_name: str | None,
    now: datetime | None = None,
) -> bool:
    """Whether ``now`` falls inside the account's window, in its own timezone.

    Overnight ranges are the normal case, so a window whose end is before its
    start wraps around midnight.
    """
    window = quiet_hours(prefs)
    if window is None:
        return False
    start, end = window
    moment = (now or datetime.now(timezone.utc)).astimezone(resolve_zone(tz_name))
    current = moment.time()
    if start < end:
        return start <= current < end
    return current >= start or current < end


#: The channels a hold can hold. The bell is not one of them: it interrupts
#: nobody, it is the record, and it is what makes holding the others safe —
#: nothing is lost, it is simply waiting where it was always going to be.
HELD_CHANNELS: frozenset[Channel] = frozenset(
    {Channel.email, Channel.push, Channel.desktop}
)

#: How long after a hold lifts its summary is still worth sending. Past this
#: the news has kept until whenever the account next looks, and a "while you
#: were away" about the week before last is noise.
HOLD_SUMMARY_GRACE = timedelta(hours=6)


def last_window_close(
    prefs: Mapping[str, Any] | None,
    *,
    tz_name: str | None,
    now: datetime | None = None,
) -> Optional[tuple[datetime, datetime]]:
    """The window that most recently closed, as ``(opened_at, closed_at)``.

    Both are absolute instants, so the summary can ask for exactly what was
    held back. Returns None when there is no window, when the window has not
    closed within :data:`HOLD_SUMMARY_GRACE`, or when ``now`` is still inside
    it — a window that has not finished has nothing to summarise yet.
    """
    window = quiet_hours(prefs)
    if window is None:
        return None
    start, end = window
    tz = resolve_zone(tz_name)
    moment = (now or datetime.now(timezone.utc)).astimezone(tz)
    if in_quiet_hours(prefs, tz_name=tz_name, now=moment):
        return None

    closed = moment.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    if closed > moment:
        closed -= timedelta(days=1)
    opened = closed.replace(hour=start.hour, minute=start.minute)
    if opened >= closed:
        # An overnight window opened the day before it closed.
        opened -= timedelta(days=1)

    if moment - closed > HOLD_SUMMARY_GRACE:
        return None
    return opened.astimezone(timezone.utc), closed.astimezone(timezone.utc)


# --- Holds -------------------------------------------------------------------
#
# Three things can stand delivery down: a pause the account set, the nightly
# quiet-hours window, and the account demonstrably being at the keyboard right
# now. They are one idea with three sources, and writing them as one idea is
# what keeps a third copy of the rule from appearing the next time one is
# added.
#
# A hold names the moment it lifts. That one property answers both channels:
# email defers to the latest lift, push refuses while any hold is in force.
# The bell is never held.


class HoldKind(str, Enum):
    """Why delivery is standing down."""

    #: The account said "not until <date>".
    pause = "pause"
    #: Inside the nightly window.
    quiet_hours = "quiet_hours"
    #: They are looking at Initiative right now, so the bell has already told
    #: them. The only hold with no summary when it lifts, for that reason.
    present = "present"


@dataclass(frozen=True)
class Hold:
    kind: HoldKind
    lifts_at: datetime


@dataclass(frozen=True)
class Lift:
    """A hold that has ended, and the stretch it covered."""

    kind: HoldKind
    opened: datetime
    closed: datetime


#: How recently somebody must have done something to count as here. The same
#: constant that decides whether to draw them as idle: "are they at the
#: keyboard" is one question, whether it is asked to render a dot or to decide
#: whether to interrupt them. If the two ever need to differ, that is the
#: moment to split it.
PRESENT_WITHIN = timedelta(seconds=IDLE_AFTER_SECONDS)

#: The longest a pause may run. Permanent silence is what the category grid and
#: the community dial are for, and both are visible on the page that owns them;
#: an open-ended hold is one you forget you set and then experience as the app
#: having stopped working.
MAX_PAUSE_DAYS = 90

#: The clock a scheduled email, and the overdue digest, go out at absent a
#: choice. Carried over from the overdue reminder, so nobody's mail moved.
DEFAULT_DIGEST_CLOCK = "21:00"

#: The clock each digest goes out at absent a choice: overdue in the evening,
#: as it always has, and what is coming up first thing.
DIGEST_CLOCKS: Mapping[NotificationCategory, str] = {
    NotificationCategory.overdue: DEFAULT_DIGEST_CLOCK,
    NotificationCategory.coming_up: "07:00",
}

#: ISO weekday for a weekly digest, absent a choice.
DEFAULT_DIGEST_WEEKDAY = 1


def _parse_instant(raw: Any) -> Optional[datetime]:
    if not isinstance(raw, str):
        return None
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return None
    # A value written without an offset is read as UTC rather than rejected:
    # every writer here stamps one, and treating a stray naive value as local
    # would make the answer depend on the server's clock.
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def pause_until(prefs: Mapping[str, Any] | None) -> Optional[datetime]:
    """When the account's pause ends, whether or not it is still running."""
    return _parse_instant(_section(prefs or EMPTY, "pause").get("until"))


def pause_since(prefs: Mapping[str, Any] | None) -> Optional[datetime]:
    """When it begins — which is not always now.

    A stand-down can be booked ahead for a holiday somebody already knows
    about, so this is a real start rather than a record of when the switch was
    flipped. It is also the instant the summary at the other end reports from.
    """
    return _parse_instant(_section(prefs or EMPTY, "pause").get("since"))


def pause_window(
    prefs: Mapping[str, Any] | None,
) -> Optional[tuple[datetime, datetime]]:
    """The stand-down this account has booked, whenever it runs.

    A window rather than an end date, because a pause set for next week is not
    holding anything yet but still has to stop mail that would otherwise land
    in the middle of it.
    """
    until = pause_until(prefs)
    if until is None:
        return None
    since = pause_since(prefs)
    # An older row, or one written without a start, ran from the moment it was
    # set — and a start after its own end describes nothing.
    if since is None or since >= until:
        since = datetime.min.replace(tzinfo=timezone.utc)
    return since, until


def respects_presence(prefs: Mapping[str, Any] | None) -> bool:
    """Whether to hold off while the account is plainly already looking.

    On unless the account has said otherwise — every comparable app ships the
    behaviour, and the switch exists because a change to when a push arrives
    should not be invisible.
    """
    value = _section(prefs or EMPTY, "away").get("respect")
    return value if isinstance(value, bool) else True


def quiet_hours_close(
    prefs: Mapping[str, Any] | None,
    *,
    tz_name: str | None,
    now: datetime | None = None,
) -> Optional[datetime]:
    """When the window the account is currently inside ends, or None if it is
    not inside one."""
    window = quiet_hours(prefs)
    if window is None:
        return None
    _start, end = window
    tz = resolve_zone(tz_name)
    moment = (now or datetime.now(timezone.utc)).astimezone(tz)
    if not in_quiet_hours(prefs, tz_name=tz_name, now=moment):
        return None
    close = moment.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    if close <= moment:
        # An overnight window closes on the following day.
        close += timedelta(days=1)
    return close.astimezone(timezone.utc)


def holds_in_force(
    prefs: Mapping[str, Any] | None,
    *,
    tz_name: str | None = None,
    last_active_at: datetime | None = None,
    now: datetime | None = None,
) -> list[Hold]:
    """Every hold standing between this account and a message right now.

    Empty means nothing is holding. Order is outermost first, which is the
    order a reader would want them named; nothing depends on it.
    """
    prefs = prefs or EMPTY
    now = now or datetime.now(timezone.utc)
    found: list[Hold] = []

    window = pause_window(prefs)
    if window is not None and window[0] <= now < window[1]:
        found.append(Hold(HoldKind.pause, window[1]))

    close = quiet_hours_close(prefs, tz_name=tz_name, now=now)
    if close is not None:
        found.append(Hold(HoldKind.quiet_hours, close))

    if last_active_at is not None and respects_presence(prefs):
        seen = last_active_at
        if seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
        # A stamp from the future is a clock disagreeing with itself; treat it
        # as now so it holds for the ordinary window rather than forever.
        seen = min(seen, now)
        if now - seen < PRESENT_WITHIN:
            found.append(Hold(HoldKind.present, seen + PRESENT_WITHIN))

    return found


def reachable(
    prefs: Mapping[str, Any] | None,
    *,
    category: NotificationCategory,
    channel: Channel,
    guild_id: int | None = None,
    tz_name: str | None = None,
    last_active_at: datetime | None = None,
    now: datetime | None = None,
) -> bool:
    """Whether this notification may take this channel *at this moment*.

    :func:`wants` answers whether the account wants it at all; this adds
    whatever is holding delivery. One function, so the three places that fan
    out — notifications, direct messages, contacts — cannot drift apart on it.

    Email rarely asks this: an email is deferred rather than refused, which is
    :func:`email_due_at`'s job. Push does, because a push that arrives after
    the moment it was about is worse than none.
    """
    if not wants(
        prefs,
        category=category,
        channel=channel,
        guild_id=guild_id,
    ):
        return False
    if channel not in HELD_CHANNELS:
        return True
    return not holds_in_force(
        prefs,
        tz_name=tz_name,
        # The desktop app alerts only while its own window is not in front,
        # which says whether somebody is looking better than recent activity
        # anywhere does.
        last_active_at=None if channel is Channel.desktop else last_active_at,
        now=now,
    )


def last_lift(
    prefs: Mapping[str, Any] | None,
    *,
    tz_name: str | None,
    now: datetime | None = None,
) -> Optional[Lift]:
    """The hold that most recently ended, if one did and it is still worth
    reporting.

    A pause is the outer hold, so a quiet-hours window that closed during one
    is not reported: the pause will report the whole stretch when it ends.
    """
    now = now or datetime.now(timezone.utc)
    window = pause_window(prefs)
    if window is not None:
        since, until = window
        if since <= now < until:
            return None  # still paused — nothing has lifted
        if until <= now and now - until <= HOLD_SUMMARY_GRACE:
            return Lift(HoldKind.pause, since, until)
    window = last_window_close(prefs, tz_name=tz_name, now=now)
    if window is None:
        return None
    return Lift(HoldKind.quiet_hours, window[0], window[1])


# --- Email cadence -----------------------------------------------------------


@dataclass(frozen=True)
class EmailSchedule:
    """When this account reads its mail."""

    cadence: EmailCadence
    #: HH:MM in the account's own timezone, for the daily and weekly slots.
    at: str
    #: ISO weekday, 1–7, for the weekly slot.
    weekday: int
    #: Whether things another person addressed to this account skip the queue.
    personal_instant: bool


def email_schedule(prefs: Mapping[str, Any] | None) -> EmailSchedule:
    section = _section(prefs or EMPTY, "email")
    raw = section.get("cadence")
    try:
        cadence = EmailCadence(raw)
    except ValueError:
        cadence = EmailCadence.instant
    at = _parse_clock(section.get("at"))
    weekday = section.get("weekday")
    if not isinstance(weekday, int) or not 1 <= weekday <= 7:
        weekday = DEFAULT_DIGEST_WEEKDAY
    lane = section.get("personal_instant")
    return EmailSchedule(
        cadence=cadence,
        at=(at.strftime("%H:%M") if at else DEFAULT_DIGEST_CLOCK),
        weekday=weekday,
        personal_instant=lane if isinstance(lane, bool) else True,
    )


@dataclass(frozen=True)
class DigestSchedule:
    """When one digest goes out."""

    cadence: DigestCadence
    #: HH:MM in the account's own timezone.
    at: str
    #: ISO weekday, 1–7, for a weekly digest.
    weekday: int


def digest_schedule(
    prefs: Mapping[str, Any] | None, category: NotificationCategory
) -> DigestSchedule:
    section = _section(_section(prefs or EMPTY, "digests"), category.value)
    try:
        cadence = DigestCadence(section.get("cadence"))
    except ValueError:
        cadence = DigestCadence.daily
    at = _parse_clock(section.get("at"))
    weekday = section.get("weekday")
    if not isinstance(weekday, int) or not 1 <= weekday <= 7:
        weekday = DEFAULT_DIGEST_WEEKDAY
    return DigestSchedule(
        cadence=cadence,
        at=(at.strftime("%H:%M") if at else DIGEST_CLOCKS[category]),
        weekday=weekday,
    )


@dataclass(frozen=True)
class DigestSlot:
    """Where a digest stands at one moment, in the account's own time."""

    #: Today's time for it.
    today: datetime
    #: The one after today's: tomorrow's, or next week's on its day.
    following: datetime
    #: Whether today is one of its days at all.
    on_today: bool

    @property
    def day_start(self) -> datetime:
        """Today's midnight, before which a stamp is yesterday's."""
        return self.today.replace(hour=0, minute=0)


def digest_slot(
    schedule: DigestSchedule, *, tz_name: str | None, now: datetime
) -> DigestSlot:
    local = now.astimezone(resolve_zone(tz_name))
    hour, minute = map(int, schedule.at.split(":"))
    today = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    weekly = schedule.cadence is DigestCadence.weekly
    following = today + timedelta(days=1)
    while weekly and following.isoweekday() != schedule.weekday:
        following += timedelta(days=1)
    return DigestSlot(
        today=today,
        following=following,
        on_today=not weekly or local.isoweekday() == schedule.weekday,
    )


def _next_slot(
    schedule: EmailSchedule, *, tz_name: str | None, now: datetime
) -> datetime:
    """The next time this cadence opens, strictly after ``now``."""
    if schedule.cadence is EmailCadence.hourly:
        # Fixed boundaries rather than a rolling hour: the next one is knowable
        # without reading when the last went out.
        return now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

    tz = resolve_zone(tz_name)
    local = now.astimezone(tz)
    clock = _parse_clock(schedule.at) or time(hour=21)
    slot = local.replace(hour=clock.hour, minute=clock.minute, second=0, microsecond=0)
    if schedule.cadence is EmailCadence.weekly:
        slot += timedelta(days=(schedule.weekday - slot.isoweekday()) % 7)
        if slot <= local:
            slot += timedelta(days=7)
    elif slot <= local:
        slot += timedelta(days=1)
    return slot.astimezone(timezone.utc)


def email_due_at(
    prefs: Mapping[str, Any] | None,
    *,
    category: NotificationCategory,
    tz_name: str | None = None,
    last_active_at: datetime | None = None,
    now: datetime | None = None,
) -> datetime:
    """The earliest this email may go out.

    Computed once, when the email is written down. Two things decide it: the
    cadence the account picked, and whatever is holding them.

    The holds are applied as a floor over the cadence's own answer, so a hold
    can only ever push a message later. That also means the present-hold needs
    no special case for a scheduled cadence: it lifts within minutes, and a
    slot hours away is already past it.
    """
    prefs = prefs or EMPTY
    now = now or datetime.now(timezone.utc)
    schedule = email_schedule(prefs)
    spec = CATEGORY_SPECS[category]
    # A digest is written at the time the account chose for it, so it is not
    # gathered again into the scheduled email.
    immediate = (
        schedule.cadence is EmailCadence.instant
        or spec.digest
        or (schedule.personal_instant and spec.personal)
    )
    due = now if immediate else _next_slot(schedule, tz_name=tz_name, now=now)

    for hold in holds_in_force(
        prefs, tz_name=tz_name, last_active_at=last_active_at, now=now
    ):
        due = max(due, hold.lifts_at)

    # A stand-down booked for next week holds nothing today, so it is not among
    # the holds above — but a message already timed to land inside it would
    # arrive in the middle of somebody's holiday. It waits for the end instead.
    window = pause_window(prefs)
    if window is not None and window[0] <= due < window[1]:
        due = window[1]
    return due


# --- Loading -----------------------------------------------------------------


async def load_prefs_for_delivery(user_id: int) -> dict[str, Any]:
    """One recipient's settings, read on the system engine.

    Delivery decides what to send *somebody else*, from a session routed into
    the guild the content is in. That session is not the recipient, and their
    settings are not a guild's to read — the same reason recipients themselves
    are loaded this way (see ``accounts.load``). Reading them under the
    account's own rule would find nothing and quietly deliver every default.
    """
    from app.db.session import SystemSessionLocal

    async with SystemSessionLocal() as system_session:
        return await load_prefs(system_session, user_id)


async def load_prefs_for_delivery_many(
    user_ids: list[int],
) -> dict[int, dict[str, Any]]:
    """The settings of everybody one notice goes to, in one system-engine read
    (see :func:`load_prefs_for_delivery`). Absent accounts read as defaults."""
    from app.db.session import SystemSessionLocal

    async with SystemSessionLocal() as system_session:
        return await load_prefs_for(system_session, user_ids)


async def load_prefs(session: AsyncSession, user_id: int) -> dict[str, Any]:
    """One account's settings document, or ``{}`` where it has none."""
    row = (
        await session.exec(
            select(UserNotificationPrefs).where(
                UserNotificationPrefs.user_id == user_id
            )
        )
    ).one_or_none()
    if row is None:
        return {}
    record = row[0] if isinstance(row, tuple) else row
    return dict(record.prefs or {})


async def load_prefs_for(
    session: AsyncSession, user_ids: list[int]
) -> dict[int, dict[str, Any]]:
    """The settings documents for a set of recipients, in one query.

    Fan-out resolves a whole audience at once, so this is what keeps preference
    resolution off the per-recipient path. Accounts with no row are absent from
    the result and read as all-defaults.
    """
    if not user_ids:
        return {}
    rows = (
        await session.exec(
            select(UserNotificationPrefs).where(
                UserNotificationPrefs.user_id.in_(user_ids)
            )
        )
    ).all()
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        record = row[0] if isinstance(row, tuple) else row
        out[record.user_id] = dict(record.prefs or {})
    return out


async def save_prefs(
    session: AsyncSession, user_id: int, prefs: Mapping[str, Any]
) -> UserNotificationPrefs:
    """Write an account's whole settings document, creating the row if needed."""
    row = (
        await session.exec(
            select(UserNotificationPrefs).where(
                UserNotificationPrefs.user_id == user_id
            )
        )
    ).one_or_none()
    record = (row[0] if isinstance(row, tuple) else row) if row is not None else None
    now = datetime.now(timezone.utc)
    if record is None:
        record = UserNotificationPrefs(
            user_id=user_id, prefs=dict(prefs), created_at=now, updated_at=now
        )
    else:
        record.prefs = dict(prefs)
        record.updated_at = now
    session.add(record)
    await session.flush()
    return record
