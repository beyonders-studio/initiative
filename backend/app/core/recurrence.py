"""Repeat rules: RFC 5545 recurrence lines, as they were picked, and a shift.

A stored repeat is one ``RRULE`` line and any ``EXDATE`` / ``RDATE`` lines:

    RRULE:FREQ=MONTHLY;BYDAY=2MO;UNTIL=20261214T225959Z
    EXDATE:20261109T083000Z

The series start is the row's own (an event's ``start_at``, a task's due date),
never a ``DTSTART`` line. The rule's days are the ones somebody picked, in their
zone; ``UNTIL``, ``EXDATE`` and ``RDATE`` are UTC. Beside it the row keeps
``recurrence_shift``, the minutes from the start's UTC time to where it was
picked: whole days (``-1440``, ``0``, ``1440``) for a rule of days, the exact
offset for a rule of hours. It is neither a zone nor its daylight-saving rules,
so every occurrence is a fixed instant, the same for every viewer.

dateutil is the one engine that turns a rule into dates: it runs the rule from
the start moved by the shift, where the picked days are, and moves every
occurrence back. Every walk is bounded (``_walk``): it begins near the dates it
is asked for, and looks a set distance past them.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import MAXYEAR, date, datetime, time, timedelta, timezone, tzinfo
from functools import lru_cache
from heapq import merge
from itertools import groupby, islice, takewhile
from typing import Iterable, Iterator, Literal

import icalendar
from dateutil.rrule import rrulestr

from app.core.errors import CodedError
from app.core.messages import CalendarEventMessages
from app.core.user_input_validators import resolve_zone

RecurrenceKind = Literal["task", "event"]

_WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")

#: The frequencies each kind may repeat at. Every task occurrence is a new row,
#: so tasks repeat daily at the most.
_FREQUENCIES: dict[RecurrenceKind, frozenset[str]] = {
    "task": frozenset({"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}),
    "event": frozenset({"HOURLY", "DAILY", "WEEKLY", "MONTHLY", "YEARLY"}),
}

#: The rule parts each kind may name: an event may also repeat at set hours.
_TASK_PARTS = frozenset(
    {
        "FREQ",
        "INTERVAL",
        "COUNT",
        "UNTIL",
        "WKST",
        "BYDAY",
        "BYMONTHDAY",
        "BYMONTH",
        "BYYEARDAY",
        "BYWEEKNO",
        "BYSETPOS",
    }
)
_PARTS: dict[RecurrenceKind, frozenset[str]] = {
    "task": _TASK_PARTS,
    "event": _TASK_PARTS | {"BYHOUR"},
}

# The last second of a day: the instant an all-day series' UNTIL date ends
_END_OF_DAY = time(23, 59, 59)

# Input bounds: the text a repeat is written in, a year of daily steps, and
# ten thousand occurrences, which saving a rule walks once to find its last
# start.
MAX_LENGTH = 4000
_MAX_INTERVAL = 366
_MAX_COUNT = 10_000
#: The furthest a shift moves a date: a day, either way.
_MAX_SHIFT = 1440
#: The days a repeat's dates fall on: a day inside each end of the calendar,
#: so moving one by its shift keeps it on the calendar.
_FIRST_DAY = date(1, 1, 2)
_LAST_DAY = date(MAXYEAR, 12, 30)

#: The most occurrences one read of a calendar expands its repeats into.
MAX_EXPANDED = 20_000

#: The longest one step of each frequency takes.
_STEP = {
    "YEARLY": timedelta(days=366),
    "MONTHLY": timedelta(days=31),
    "WEEKLY": timedelta(weeks=1),
    "DAILY": timedelta(days=1),
    "HOURLY": timedelta(hours=1),
}
#: The frequencies whose steps are all one length, so a walk can begin any
#: whole number of them along.
_EVEN_STEPS = frozenset({"WEEKLY", "DAILY", "HOURLY"})
#: How far a walk looks past where it begins for a series' next start, at
#: the least (``_reach``).
_REACH = timedelta(days=50 * 365)
#: How long a counted series may run from its start.
_MAX_COUNTED = 100 * _STEP["YEARLY"]
#: The last second a walk holds, and how long the calendar is.
_LAST = datetime.combine(_LAST_DAY, _END_OF_DAY)
_CALENDAR = _LAST - datetime(1, 1, 1)


class OutOfReach(CodedError, ValueError):
    """A repeat that, from its start, never happens, or doesn't reach its
    count within a hundred years."""

    status_code = 422


@dataclass(frozen=True)
class Recurrence:
    """One parsed repeat: its rule parts, skipped starts and extra starts."""

    rule: dict[str, list]
    exdates: tuple[date | datetime, ...] = field(default=())
    rdates: tuple[date | datetime, ...] = field(default=())

    def to_lines(self) -> str:
        """The canonical text: equal repeats are equal strings."""
        lines = [f"RRULE:{icalendar.vRecur(self.rule).to_ical().decode()}"]
        for name, values in (("EXDATE", self.exdates), ("RDATE", self.rdates)):
            days = sorted(v for v in values if not isinstance(v, datetime))
            instants = sorted(v for v in values if isinstance(v, datetime))
            if days:
                lines.append(
                    f"{name};VALUE=DATE:" + ",".join(d.strftime("%Y%m%d") for d in days)
                )
            if instants:
                lines.append(
                    f"{name}:"
                    + ",".join(
                        d.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                        for d in instants
                    )
                )
        return "\n".join(lines)


def parse(text: str, *, strict: bool = False) -> Recurrence:
    """Read recurrence lines. Raises ``ValueError`` for anything that is not one
    ``RRULE`` with optional ``EXDATE`` / ``RDATE`` lines.

    A date before ``_FIRST_DAY`` or after ``_LAST_DAY`` is held there, or with
    ``strict`` refused."""
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        raise ValueError("A repeat needs an RRULE line.")
    if ":" not in lines[0]:
        # A bare rule value is accepted as its RRULE line.
        lines = [f"RRULE:{lines[0]}", *lines[1:]]
    try:
        component = icalendar.Event.from_ical(
            "BEGIN:VEVENT\r\n" + "\r\n".join(lines) + "\r\nEND:VEVENT\r\n"
        )
    except ValueError as exc:
        raise ValueError(f"Not a valid repeat: {exc}") from exc
    names = {name.upper() for name in component}
    if names - {"RRULE", "EXDATE", "RDATE"}:
        raise ValueError("A repeat holds only RRULE, EXDATE and RDATE lines.")
    rule = component.get("RRULE")
    if rule is None or isinstance(rule, list):
        raise ValueError("A repeat needs exactly one RRULE line.")
    parts = {key.upper(): list(values) for key, values in rule.items()}
    if until := parts.get("UNTIL"):
        parts["UNTIL"] = [_held(until[0], strict)]
    return Recurrence(
        rule=parts,
        exdates=tuple(_held(v, strict) for v in _dates(component.get("EXDATE"))),
        rdates=tuple(_held(v, strict) for v in _dates(component.get("RDATE"))),
    )


def _dates(prop) -> Iterable[date | datetime]:
    for dates in prop if isinstance(prop, list) else [prop] if prop else []:
        for value in dates.dts:
            yield value.dt


def _held(value: date | datetime, strict: bool) -> date | datetime:
    """``value``, or the nearest of ``_FIRST_DAY`` and ``_LAST_DAY`` at its
    time when it falls outside them."""
    day = value.date() if isinstance(value, datetime) else value
    if _FIRST_DAY <= day <= _LAST_DAY:
        return value
    if strict:
        raise ValueError("A repeat's dates fall from 2 January 1 to 30 December 9999.")
    day = min(max(day, _FIRST_DAY), _LAST_DAY)
    return datetime.combine(day, value.timetz()) if isinstance(value, datetime) else day


def normalize(text: str, *, kind: RecurrenceKind) -> str:
    """Validate a repeat for ``kind`` and return its canonical lines."""
    if len(text) > MAX_LENGTH:
        raise ValueError(f"A repeat is at most {MAX_LENGTH} characters.")
    recurrence = parse(text, strict=True)
    rule = recurrence.rule
    freq = rule.get("FREQ", [""])[0]
    if freq not in _FREQUENCIES[kind]:
        raise ValueError(f"This repeat can't be {str(freq).lower() or 'empty'}.")
    if extra := set(rule) - _PARTS[kind]:
        raise ValueError(f"This repeat can't use {', '.join(sorted(extra))}.")
    if "COUNT" in rule and "UNTIL" in rule:
        raise ValueError("A repeat ends after a count or on a date, not both.")
    if not 1 <= rule.get("INTERVAL", [1])[0] <= _MAX_INTERVAL:
        raise ValueError(f"A repeat's interval is 1 to {_MAX_INTERVAL}.")
    if not 1 <= rule.get("COUNT", [1])[0] <= _MAX_COUNT:
        raise ValueError(f"A repeat happens 1 to {_MAX_COUNT} times.")
    if "COUNT" in rule and _steps(rule, rule["COUNT"][0] - 1) > _MAX_COUNTED:
        raise ValueError("A counted repeat ends within a hundred years.")
    for value in [*rule.get("UNTIL", []), *recurrence.exdates, *recurrence.rdates]:
        if isinstance(value, datetime) and value.utcoffset() != timedelta(0):
            raise ValueError("A repeat's dates and times are UTC.")
    # dateutil is the engine every date comes from, so it has to read the rule.
    reference = datetime(2000, 1, 1, tzinfo=timezone.utc)
    next(_walk(recurrence, reference, 0, reference, reference), None)
    lines = recurrence.to_lines()
    if len(lines) > MAX_LENGTH:
        raise ValueError(f"A repeat is at most {MAX_LENGTH} characters.")
    return lines


def shift_for(text: str, start: datetime, zone: tzinfo) -> int:
    """The shift of a rule picked in ``zone`` for a series starting at
    ``start``: whole days for a rule of days, the offset for a rule of hours."""
    rule = parse(text).rule
    local = start.astimezone(zone)
    if rule["FREQ"][0] == "HOURLY" or "BYHOUR" in rule:
        return int((local.utcoffset() or timedelta(0)).total_seconds() // 60)
    return (local.date() - start.astimezone(timezone.utc).date()).days * 1440


def stored(
    text: str, start: datetime | None, tz: str | None, *, kind: RecurrenceKind
) -> tuple[str, int]:
    """A written rule and its shift: picked in ``tz``, or in UTC without one.
    From its start, the rule has to happen, and a counted one to reach its
    count within a hundred years."""
    rule = normalize(text, kind=kind)
    if start is None:
        return rule, 0
    shift = shift_for(rule, start, resolve_zone(tz)) if tz else 0
    repeat = parse(rule).rule
    wanted = repeat.get("COUNT", [1])[0]
    starts = _walk(Recurrence(repeat), start, shift, start)
    if sum(1 for _ in islice(starts, wanted)) < wanted:
        raise OutOfReach(CalendarEventMessages.RECURRENCE_INVALID)
    return rule, shift


def _steps(rule: dict[str, list], n: int) -> timedelta:
    """The longest ``n`` of the rule's steps take, or the calendar's length."""
    step = _STEP[rule["FREQ"][0]] * rule.get("INTERVAL", [1])[0]
    return step * min(n, _CALENDAR // step)


def _reach(rule: dict[str, list]) -> timedelta:
    """How far past where it begins a walk looks for a series' starts:
    ``_REACH``, or four hundred of its steps, in which a year's rule runs
    through every pattern it has."""
    return max(_REACH, _steps(rule, 400))


def _past(value: datetime, span: timedelta) -> datetime:
    """``span`` after ``value``, or the end of dateutil's calendar first."""
    return value + min(span, _LAST - value)


@lru_cache(maxsize=1024)
def _years_on(first: int, last: int) -> int:
    """How many years later the years ``first`` to ``last`` can run, as near
    the end of dateutil's calendar as they go, with each of them and the years
    either side starting on the same weekday, and a leap year staying one."""

    def kind(year: int) -> tuple[bool, int]:
        return calendar.isleap(year), date(year, 1, 1).weekday()

    years = range(max(first - 1, 1), last + 2)
    top = MAXYEAR - 1 - last
    # Four hundred years on, every year matches.
    return next(
        (
            shift
            for shift in range(top, max(top - 400, -1), -1)
            if all(kind(year) == kind(year + shift) for year in years)
        ),
        0,
    )


def _walk(
    recurrence: Recurrence,
    start: datetime,
    shift: int,
    since: datetime,
    through: datetime | None = None,
    *,
    count: bool = True,
) -> Iterator[datetime]:
    """The series' starts from ``since`` through ``through``, in order. The
    rule's own starts go as far as ``_reach`` from ``since``, or for a counted
    series a hundred years from its start, which ``stored`` holds its count
    to; extra starts are dates of their own, with no reach.

    dateutil runs the rule from the start moved by ``shift``, where the picked
    days are, and every start is moved back. A series without a count runs
    from its last step at or before ``since``. The years the walk covers run
    where dateutil's calendar ends, on years with the same weekdays and leap
    days, so it ends there."""
    offset = timedelta(minutes=shift)

    def here(value: date | datetime, at: time) -> datetime:
        if isinstance(value, datetime):
            moment = value.astimezone(timezone.utc).replace(tzinfo=None)
            # Held where its shift keeps it on the calendar.
            held = min(
                max(moment, datetime.min + abs(offset)), datetime.max - abs(offset)
            )
            return held + offset
        return datetime.combine(value, at)

    parts = dict(recurrence.rule)
    if not count:
        parts.pop("COUNT", None)
    origin = here(start, time())
    at = origin.time()
    lower = here(since, at)
    upper = _LAST if through is None else here(through, at)
    if counted := parts.get("COUNT"):
        limit = min(upper, _past(origin, _MAX_COUNTED))
    else:
        limit = min(upper, _past(lower, _reach(parts)))
    first = origin
    freq = parts["FREQ"][0]
    if not counted and lower > first and freq in _EVEN_STEPS:
        step = _steps(parts, 1)
        first += (lower - first) // step * step
    elif not counted and lower > first:
        # Whole steps of a month's or a year's rule from the start's month,
        # begun on the first of a month with the days and time dateutil
        # otherwise takes from the start.
        step = parts.get("INTERVAL", [1])[0] * (12 if freq == "YEARLY" else 1)
        month = first.year * 12 + first.month - 1
        if ahead := (lower.year * 12 + lower.month - 1 - month) // step * step:
            parts = _pinned(parts, first)
            parts.setdefault("BYHOUR", [first.hour])
            parts["BYMINUTE"], parts["BYSECOND"] = [first.minute], [first.second]
            first = datetime((month + ahead) // 12, (month + ahead) % 12 + 1, 1)

    def own() -> Iterator[datetime]:
        if limit < max(lower, first):
            return
        years = _years_on(min(first, lower).year, limit.year)

        def on(value: datetime, years: int = years) -> datetime:
            return value.replace(year=value.year + years)

        until = parts.pop("UNTIL", None)
        end = here(until[0], _END_OF_DAY) if until else limit
        if until and end >= first:
            parts["UNTIL"] = [on(min(end, limit))]
        rule = rrulestr(icalendar.vRecur(parts).to_ical().decode(), dtstart=on(first))
        if end < first:
            return
        last = on(limit)
        for value in takewhile(
            lambda value: value <= last, rule.xafter(on(lower), inc=True)
        ):
            yield on(value, -years)

    skipped = {here(value, at) for value in recurrence.exdates}
    extra = sorted(
        {
            moved
            for value in recurrence.rdates
            if lower <= (moved := here(value, at)) <= upper
        }
    )
    for value, _ in groupby(merge(own(), extra)):
        if value not in skipped:
            yield (value - offset).replace(tzinfo=timezone.utc)


def _pinned(parts: dict[str, list], at: datetime) -> dict[str, list]:
    """``parts`` with the days the rule otherwise takes from its start written
    in, from ``at``, the start where its days were picked: a week's weekday, a
    month's day, a year's day and month."""
    parts = dict(parts)
    freq = parts["FREQ"][0]
    if freq == "WEEKLY":
        parts.setdefault("BYDAY", [_WEEKDAYS[at.weekday()]])
    elif freq in ("MONTHLY", "YEARLY") and not parts.keys() & {
        "BYWEEKNO",
        "BYYEARDAY",
        "BYMONTHDAY",
        "BYDAY",
    }:
        parts["BYMONTHDAY"] = [at.day]
        if freq == "YEARLY":
            parts.setdefault("BYMONTH", [at.month])
    return parts


def first(text: str, start: datetime, shift: int, n: int) -> list[datetime]:
    """The series' first ``n`` starts."""
    return list(islice(_walk(parse(text), start, shift, start), n))


def next_start(
    text: str, start: datetime, shift: int = 0, *, count: bool = True
) -> datetime | None:
    """The first occurrence after ``start`` of a series starting there."""
    return next(
        (
            value
            for value in _walk(parse(text), start, shift, start, count=count)
            if value > start
        ),
        None,
    )


def last_start(
    text: str, start: datetime, shift: int = 0, *, done: int = 0
) -> datetime | None:
    """No occurrence of the series starts after this, or None when it never
    ends: UNTIL itself (or a later extra date), or a COUNT series' last start.
    ``done`` is how many of a COUNT series came before ``start``: a task series
    counts its successors itself."""
    recurrence = parse(text)
    offset = timedelta(minutes=shift)
    # An extra start given as a date is at the series' time on that date.
    at = (start.astimezone(timezone.utc) + offset).time()
    extra = [
        value.astimezone(timezone.utc)
        if isinstance(value, datetime)
        else datetime.combine(value, at, timezone.utc) - offset
        for value in recurrence.rdates
    ]
    if until := recurrence.rule.get("UNTIL"):
        end = until[0]
        if not isinstance(end, datetime):
            end = datetime.combine(end, _END_OF_DAY, timezone.utc) - offset
        return max([end.astimezone(timezone.utc), *extra])
    if count := recurrence.rule.get("COUNT"):
        left = Recurrence(
            {**recurrence.rule, "COUNT": [max(count[0] - done, 1)]},
            recurrence.exdates,
            recurrence.rdates,
        )
        return max(_walk(left, start, shift, start), default=None)
    return None


def between(
    text: str,
    start: datetime,
    shift: int,
    lower: datetime,
    upper: datetime,
    *,
    count: bool = True,
    at_most: int | None = None,
) -> list[datetime]:
    """The occurrences starting in ``[lower, upper]``: the first ``at_most``
    of them, with one."""
    starts = _walk(parse(text), start, shift, lower, upper, count=count)
    return list(islice(starts, at_most))


def starting(
    text: str, start: datetime, shift: int, at: datetime, n: int
) -> list[datetime]:
    """The series' first ``n`` starts at or after ``at``."""
    return list(islice(_walk(parse(text), start, shift, at), n))


def upcoming(text: str, start: datetime, shift: int, now: datetime) -> datetime:
    """The first occurrence starting at or after ``now``, or, once the series
    has ended, its last: looked for within a year or two steps of its end,
    then within ``_reach``."""
    repeat = parse(text)
    following = next(_walk(repeat, start, shift, now), None)
    if following is not None:
        return following
    end = min(now, last_start(text, start, shift) or now)
    last = start
    for back in (max(_steps(repeat.rule, 2), timedelta(days=366)), _reach(repeat.rule)):
        if last == start:
            since = end - min(back, end - start)
            *_, last = start, *_walk(repeat, start, shift, since, end)
    return last


def restarted(
    text: str, shift: int, old_start: datetime, new_start: datetime, tz: str | None
) -> tuple[str, int]:
    """A series whose start moved, and its shift: the days stay as picked, the
    shift is taken again in ``tz`` (kept without one), and a skipped or extra
    start keeps its picked day at the new time of day."""
    new_shift = shift_for(text, new_start, resolve_zone(tz)) if tz else shift
    repeat = parse(text)

    def move(value: date | datetime) -> date | datetime:
        if not isinstance(value, datetime):
            return value
        return rehomed(text, value, shift, new_shift, old_start, new_start)

    lines = Recurrence(
        repeat.rule,
        tuple(move(value) for value in repeat.exdates),
        tuple(move(value) for value in repeat.rdates),
    ).to_lines()
    return lines, new_shift


def rehomed(
    text: str,
    value: datetime,
    old_shift: int,
    new_shift: int,
    old_start: datetime,
    new_start: datetime,
) -> datetime:
    """An occurrence of a series whose start moved: the same picked day, at
    the new start's time of day. A rule of named hours keeps its hour and takes
    the new start's minute; a rule of every so many hours moves each start by
    as much as the first moved."""
    rule = parse(text).rule
    if "BYHOUR" in rule:
        local = value.astimezone(timezone.utc) + timedelta(minutes=old_shift)
        anchor = new_start.astimezone(timezone.utc) + timedelta(minutes=new_shift)
        return local.replace(
            minute=anchor.minute, second=anchor.second, microsecond=0
        ) - timedelta(minutes=new_shift)
    if rule["FREQ"][0] == "HOURLY":
        return value.astimezone(timezone.utc) + (new_start - old_start)
    day = (value.astimezone(timezone.utc) + timedelta(minutes=old_shift)).date()
    new = timedelta(minutes=new_shift)
    at = (new_start.astimezone(timezone.utc) + new).time()
    return datetime.combine(day, at, timezone.utc) - new


def _names(value: date | datetime, at: datetime, shift: int) -> bool:
    """Whether a skipped or extra start is the occurrence starting at ``at``:
    an instant by itself, a date by the day it was picked on."""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) == at.astimezone(timezone.utc)
    return (at.astimezone(timezone.utc) + timedelta(minutes=shift)).date() == value


def occurs(text: str, start: datetime, shift: int, at: datetime) -> bool:
    """Whether the series has an occurrence starting at ``at``."""
    return bool(between(text, start, shift, at, at))


def skipped(text: str, shift: int, at: datetime) -> str:
    """The repeat without its occurrence at ``at``: an extra start is taken
    out again, any other is skipped."""
    repeat = parse(text)
    rdates = tuple(value for value in repeat.rdates if not _names(value, at, shift))
    if len(rdates) != len(repeat.rdates):
        return Recurrence(repeat.rule, repeat.exdates, rdates).to_lines()
    return Recurrence(
        repeat.rule, (*repeat.exdates, at.astimezone(timezone.utc)), repeat.rdates
    ).to_lines()


def restored(text: str, shift: int, at: datetime) -> str:
    """The repeat with its skipped occurrence at ``at`` back."""
    repeat = parse(text)
    return Recurrence(
        repeat.rule,
        tuple(value for value in repeat.exdates if not _names(value, at, shift)),
        repeat.rdates,
    ).to_lines()


def with_extra(text: str, shift: int, at: datetime) -> str:
    """The repeat with an extra start at ``at``."""
    repeat = parse(text)
    return Recurrence(
        repeat.rule,
        tuple(value for value in repeat.exdates if not _names(value, at, shift)),
        (*repeat.rdates, at.astimezone(timezone.utc)),
    ).to_lines()


def exception_starts(
    text: str, start: datetime, shift: int
) -> tuple[list[datetime], list[datetime]]:
    """The series' skipped starts and extra starts, as instants: a date is
    at the series' time on the day it was picked."""
    repeat = parse(text)
    offset = timedelta(minutes=shift)
    at = (start.astimezone(timezone.utc) + offset).time()

    def instant(value: date | datetime) -> datetime:
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc)
        return datetime.combine(value, at, timezone.utc) - offset

    return (
        sorted(instant(v) for v in repeat.exdates),
        sorted(instant(v) for v in repeat.rdates),
    )


def kept_exceptions(new: str, old: str | None) -> str:
    """A rule written without skipped or extra starts keeps the ones the
    series had: the form edits the rule, and they are not the rule."""
    fresh = parse(new)
    if not old or fresh.exdates or fresh.rdates:
        return new
    before = parse(old)
    return Recurrence(fresh.rule, before.exdates, before.rdates).to_lines()


def split(
    text: str, start: datetime, shift: int, at: datetime
) -> tuple[str | None, str]:
    """The series cut at its occurrence ``at``: the part before it (None when
    ``at`` is its first), and the rest, a series starting at ``at``.

    A COUNT is shared between them by the rule's own starts before ``at``;
    otherwise the first part ends the second before ``at``. Each part keeps
    the skipped and extra starts on its side."""
    repeat = parse(text)
    at = at.astimezone(timezone.utc)
    offset = timedelta(minutes=shift)

    def early(value: date | datetime) -> bool:
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc) < at
        return value < (at + offset).date()

    starts = _walk(Recurrence(repeat.rule), start, shift, start, at)
    count = repeat.rule.get("COUNT")
    # The rule's own starts before ``at``: counted only for a COUNT, which
    # bounds them; otherwise all that matters is whether there is one.
    done = (
        sum(1 for value in starts if value < at)
        if count
        else int(next(starts, at) < at)
    )
    head_rule, tail_rule = dict(repeat.rule), dict(repeat.rule)
    if count:
        if count[0] <= done:
            raise ValueError("The series has ended before this occurrence.")
        head_rule["COUNT"], tail_rule["COUNT"] = [done], [count[0] - done]
    else:
        head_rule.pop("UNTIL", None)
        head_rule["UNTIL"] = [at - timedelta(seconds=1)]
    head = (
        Recurrence(
            head_rule,
            tuple(v for v in repeat.exdates if early(v)),
            tuple(v for v in repeat.rdates if early(v)),
        ).to_lines()
        if done
        else None
    )
    tail = Recurrence(
        tail_rule,
        tuple(v for v in repeat.exdates if not early(v)),
        tuple(v for v in repeat.rdates if not early(v)),
    ).to_lines()
    return head, tail


def _slot(parts: dict[str, list], at: datetime) -> tuple[int, ...]:
    """Which of the days and hours ``parts`` name ``at`` falls on."""
    slot: list[int] = []
    if "BYMONTH" in parts:
        slot.append(at.month)
    if "BYMONTHDAY" in parts:
        slot.append(at.day)
    if "BYDAY" in parts:
        slot.append(at.weekday())
        if any(day[:-2] for day in map(str, parts["BYDAY"])):
            slot.append((at.day - 1) // 7)
    if "BYHOUR" in parts:
        slot.append(at.hour)
    return tuple(slot)


@dataclass(frozen=True)
class Moved:
    """A series moved along the calendar: its repeat, its new start, and the
    new start of each old occurrence it was asked about."""

    text: str
    start: datetime
    occurrences: dict[datetime, datetime]


def moved(
    text: str,
    start: datetime,
    shift: int,
    delta: timedelta,
    *,
    occurrences: Iterable[datetime] = (),
) -> Moved:
    """The series starting at ``start``, moved by about ``delta`` without
    leaving its days: it starts on the occurrence of its rule nearest
    ``start + delta``, so a series of Mondays stays on Mondays and one on the
    second Tuesday of the month stays there.

    Its skipped starts, its end and each of ``occurrences`` go to the new
    occurrence of the same number, so they name the same occurrence as
    before. An extra start, or a value the rule never made, moves as far as
    the series start did."""
    start = start.astimezone(timezone.utc)
    asked = tuple(value.astimezone(timezone.utc) for value in occurrences)
    if not delta:
        return Moved(text, start, {value: value for value in asked})
    repeat = parse(text)
    offset = timedelta(minutes=shift)
    at = (start + offset).time()
    own = {key: v for key, v in repeat.rule.items() if key not in ("COUNT", "UNTIL")}
    pinned = _pinned(own, (start + offset).replace(tzinfo=None))
    days = Recurrence({key: v for key, v in pinned.items() if key != "INTERVAL"})

    target = start + delta
    span = _steps(days.rule, 1)
    near = list(_walk(days, start, shift, target - span, target + span))
    near = near or list(islice(_walk(days, start, shift, target), 1))
    # Among them, the ones on the start's own day of the rule's, so a series
    # of Mondays and Wednesdays that began on a Monday begins on one again.
    here = _slot(pinned, (start + offset).replace(tzinfo=None))
    alike = [
        v for v in near if _slot(pinned, (v + offset).replace(tzinfo=None)) == here
    ]
    new_start = min(alike or near, key=lambda v: (abs(v - target), v), default=target)
    along = new_start - start

    def instant(value: date | datetime) -> datetime:
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc)
        return datetime.combine(value, at, timezone.utc) - offset

    until = repeat.rule.get("UNTIL")
    end = instant(until[0]) if until else None
    skipped = [instant(value) for value in repeat.exdates]
    through = max([*skipped, *asked, *([end] if end else [])], default=start)
    old = list(
        islice(_walk(Recurrence(own), start, shift, start, through), MAX_EXPANDED)
    )
    number = {value: n for n, value in enumerate(old)}
    last = max((v for v in old if v <= end), default=None) if end else None
    named = [*skipped, *asked, *([last] if last else [])]
    wanted = max((number[v] for v in named if v in number), default=-1)
    new = list(islice(_walk(Recurrence(own), new_start, shift, new_start), wanted + 1))

    def going(value: datetime) -> datetime:
        n = number.get(value)
        return new[n] if n is not None and n < len(new) else value + along

    def by_days(value: date, by: timedelta) -> date:
        return value + timedelta(days=round(by / timedelta(days=1)))

    rule = dict(repeat.rule)
    if until:
        # The end keeps its distance past the last occurrence before it.
        by = going(last) - last if last else along
        rule["UNTIL"] = [
            until[0] + by if isinstance(until[0], datetime) else by_days(until[0], by)
        ]
    return Moved(
        Recurrence(
            rule,
            tuple(
                going(instant(v))
                if isinstance(v, datetime)
                else (going(instant(v)) + offset).date()
                for v in repeat.exdates
            ),
            tuple(
                v + along if isinstance(v, datetime) else by_days(v, along)
                for v in repeat.rdates
            ),
        ).to_lines(),
        new_start,
        {value: going(value) for value in asked},
    )


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

_LEGACY_POSITIONS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "last": -1}


def from_legacy(data: dict, *, zone: tzinfo, all_day: bool = False) -> str | None:
    """A repeat in the JSON shape exports carried before RRULE, as the rule its
    days were picked in (``zone``). None when it names no frequency."""
    freq = str(data.get("frequency") or "").upper()
    if freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
        return None

    def code(day: object) -> str:
        return str(day)[:2].upper()  # "monday" and the older "MO" alike

    rule: dict[str, list] = {"FREQ": [freq]}
    if (interval := int(data.get("interval") or 1)) > 1:
        rule["INTERVAL"] = [interval]
    if freq == "WEEKLY" and data.get("weekdays"):
        rule["BYDAY"] = [code(d) for d in data["weekdays"] if code(d) in _WEEKDAYS]
    if freq in ("MONTHLY", "YEARLY"):
        if data.get("monthly_mode") == "weekday" and data.get("weekday"):
            position = _LEGACY_POSITIONS.get(data.get("weekday_position") or "first", 1)
            rule["BYDAY"] = [f"{position}{code(data['weekday'])}"]
        elif day := data.get("day_of_month"):
            # A day a short month lacks fell on that month's last day.
            rule["BYMONTHDAY"] = [day] if day <= 28 else list(range(28, day + 1))
            if day > 28:
                rule["BYSETPOS"] = [-1]
        if freq == "YEARLY" and data.get("month"):
            rule["BYMONTH"] = [int(data["month"])]
    if data.get("ends") == "after_occurrences" and data.get("end_after_occurrences"):
        rule["COUNT"] = [int(data["end_after_occurrences"])]
    elif data.get("ends") == "on_date" and data.get("end_date"):
        # The last day as the form showed it: the date the value is written with.
        last = datetime.fromisoformat(str(data["end_date"])).date()
        rule["UNTIL"] = [
            last
            if all_day
            else datetime.combine(last, _END_OF_DAY, zone).astimezone(timezone.utc)
        ]
    return Recurrence(rule).to_lines()


def imported(
    value: str | dict | None,
    *,
    kind: RecurrenceKind,
    start: datetime | None,
    tz: str | None,
    shift: int = 0,
    all_day: bool = False,
) -> tuple[str | None, int]:
    """A repeat read from an import and its shift: a rule string comes with
    its ``shift``, and the JSON shape exports carried before RRULE was picked in
    a zone the export doesn't name, which ``tz`` (the importer's) stands in
    for. A repeat that doesn't hold up imports as none."""
    try:
        if not -_MAX_SHIFT <= shift <= _MAX_SHIFT:
            raise ValueError("A shift is at most a day.")
        if isinstance(value, dict):
            zone = resolve_zone(None if all_day else tz)
            legacy = from_legacy(value, zone=zone, all_day=all_day)
            if legacy is None:
                return None, 0
            return stored(legacy, start, None if all_day else tz, kind=kind)
        return (normalize(value, kind=kind), shift) if value else (None, 0)
    except (ValueError, TypeError):
        return None, 0
