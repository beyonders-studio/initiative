from datetime import datetime, timedelta, timezone
from itertools import islice
from zoneinfo import ZoneInfo

import pytest
from dateutil.rrule import rrulestr

from app.core import recurrence

BERLIN = ZoneInfo("Europe/Berlin")
UTC = timezone.utc

# Monday 00:30 in Berlin is Sunday in UTC.
EAST = datetime(2026, 10, 5, 0, 30, tzinfo=BERLIN)


@pytest.mark.parametrize(
    ("text", "kind", "stored"),
    [
        ("FREQ=MONTHLY;BYDAY=2MO", "task", "RRULE:FREQ=MONTHLY;BYDAY=2MO"),
        ("RRULE:FREQ=HOURLY;BYHOUR=17,9", "event", "RRULE:FREQ=HOURLY;BYHOUR=17,9"),
        (
            "RRULE:FREQ=WEEKLY;BYDAY=MO\nRDATE;VALUE=DATE:20261224\n"
            "EXDATE:20261012T063000Z",
            "event",
            "RRULE:FREQ=WEEKLY;BYDAY=MO\nEXDATE:20261012T063000Z\n"
            "RDATE;VALUE=DATE:20261224",
        ),
    ],
)
def test_normalize_writes_canonical_lines(text, kind, stored):
    assert recurrence.normalize(text, kind=kind) == stored


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("FREQ=HOURLY", "task"),
        ("FREQ=DAILY;BYHOUR=9", "task"),
        ("FREQ=MINUTELY", "event"),
        ("FREQ=DAILY;BYMINUTE=5", "event"),
        ("FREQ=DAILY;COUNT=3;UNTIL=20261201T000000Z", "event"),
        ("FREQ=DAILY;UNTIL=20261201T000000", "event"),
        ("FREQ=DAILY;INTERVAL=0", "event"),
        ("FREQ=DAILY;COUNT=10001", "event"),
        ("FREQ=YEARLY;COUNT=102", "event"),
        ("FREQ=YEARLY;INTERVAL=366;COUNT=10000", "event"),
        ("FREQ=BOGUS", "event"),
        ("DTSTART:20261001T000000Z\nRRULE:FREQ=DAILY", "event"),
        ("", "event"),
        # Dates a day's shift would move off the calendar.
        ("FREQ=DAILY\nRDATE:99991231T230000Z", "event"),
        ("FREQ=DAILY\nEXDATE;VALUE=DATE:00010101", "event"),
        ("FREQ=DAILY;UNTIL=99991231T235959Z", "event"),
        ("FREQ=DAILY\nEXDATE:" + ",".join(["20261012T063000Z"] * 250), "event"),
        # Within the limit as written, past it as stored.
        ("FREQ=WEEKLY\nRDATE:" + ",".join(["20261012T063000Z"] * 234), "event"),
    ],
)
def test_normalize_refuses(text, kind):
    with pytest.raises(ValueError):
        recurrence.normalize(text, kind=kind)


_PICKED = [
    rule
    for interval in (1, 2)
    for rule in (
        f"FREQ=WEEKLY;INTERVAL={interval};BYDAY=MO,TH",
        f"FREQ=MONTHLY;INTERVAL={interval};BYDAY=5MO",
        f"FREQ=MONTHLY;INTERVAL={interval};BYDAY=-1MO",
        f"FREQ=MONTHLY;INTERVAL={interval};BYMONTHDAY=29",
        f"FREQ=MONTHLY;INTERVAL={interval};BYMONTHDAY=30",
        f"FREQ=MONTHLY;INTERVAL={interval};BYDAY=MO,TU,WE,TH,FR;BYSETPOS=1",
        f"FREQ=MONTHLY;INTERVAL={interval};BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1",
        f"FREQ=YEARLY;INTERVAL={interval};BYMONTH=2;BYMONTHDAY=28",
        f"FREQ=WEEKLY;INTERVAL={interval};BYDAY=MO;BYHOUR=0,12",
        f"FREQ=DAILY;INTERVAL={interval};BYHOUR=0,12",
    )
]


@pytest.mark.parametrize("picked", _PICKED)
@pytest.mark.parametrize(
    ("zone", "at"),
    [
        (BERLIN, (0, 30)),
        (ZoneInfo("America/New_York"), (20, 30)),
        (ZoneInfo("Asia/Kolkata"), (0, 15)),
        (ZoneInfo("Pacific/Auckland"), (1, 0)),
    ],
    ids=["berlin-midnight", "new-york-evening", "kolkata-midnight", "auckland"],
)
def test_a_stored_rule_starts_when_it_was_picked_to(picked, zone, at):
    """Near midnight a day moves across a month's end on some months and not
    others, which no rule in UTC terms can say. Kept as picked, with its
    shift, the rule starts exactly when it does at the start's own offset."""
    first = rrulestr(f"RRULE:{picked}", dtstart=datetime(2026, 1, 1, *at))[0].replace(
        tzinfo=zone
    )
    fixed = timezone(first.utcoffset() or timedelta(0))
    wanted = [
        value.replace(tzinfo=fixed).astimezone(UTC)
        for value in islice(
            rrulestr(f"RRULE:{picked}", dtstart=first.replace(tzinfo=None)), 24
        )
    ]
    rule, shift = recurrence.stored(picked, first, str(zone), kind="event")
    assert rule == recurrence.normalize(picked, kind="event")
    assert recurrence.first(rule, first, shift, 24) == wanted


def test_occurrences_come_from_the_stored_rule():
    rule, shift = recurrence.stored(
        "FREQ=WEEKLY;BYDAY=MO,WE", EAST, "Europe/Berlin", kind="event"
    )
    assert shift == 1440
    start = EAST.astimezone(UTC)
    assert recurrence.next_start(rule, start, shift) == datetime(
        2026, 10, 6, 22, 30, tzinfo=UTC
    )
    # A task series' own counter decides its end, so COUNT can be left out.
    assert recurrence.next_start("RRULE:FREQ=DAILY;COUNT=1", start) is None
    assert recurrence.next_start(
        "RRULE:FREQ=DAILY;COUNT=1", start, count=False
    ) == datetime(2026, 10, 5, 22, 30, tzinfo=UTC)
    assert recurrence.last_start("RRULE:FREQ=WEEKLY;COUNT=3", start) == datetime(
        2026, 10, 18, 22, 30, tzinfo=UTC
    )
    # A task series' successor counts down what its predecessors used.
    assert recurrence.last_start(
        "RRULE:FREQ=WEEKLY;COUNT=3", start, done=1
    ) == datetime(2026, 10, 11, 22, 30, tzinfo=UTC)
    assert recurrence.last_start("RRULE:FREQ=DAILY;UNTIL=20261201", start) == (
        datetime(2026, 12, 1, 23, 59, 59, tzinfo=UTC)
    )
    assert recurrence.last_start("RRULE:FREQ=DAILY", start) is None
    # An extra start after the end, given as a date, is the last one.
    assert recurrence.last_start(
        "RRULE:FREQ=DAILY;UNTIL=20261201\nRDATE;VALUE=DATE:20261224", start
    ) == datetime(2026, 12, 24, 22, 30, tzinfo=UTC)
    assert recurrence.between(
        "RRULE:FREQ=WEEKLY;BYDAY=MO\nEXDATE:20261011T223000Z\nRDATE:20261020T090000Z",
        start,
        shift,
        datetime(2026, 10, 1, tzinfo=UTC),
        datetime(2026, 10, 21, tzinfo=UTC),
    ) == [
        datetime(2026, 10, 4, 22, 30, tzinfo=UTC),
        datetime(2026, 10, 18, 22, 30, tzinfo=UTC),
        datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
    ]
    weekly = [start + timedelta(weeks=n) for n in range(5)]
    assert (
        recurrence.between("RRULE:FREQ=WEEKLY", start, 0, start, weekly[-1], at_most=2)
        == weekly[:2]
    )
    # A stored date at the calendar's end reads at a day's shift either way.
    edge = "RRULE:FREQ=WEEKLY\nRDATE:99991231T230000Z\nEXDATE;VALUE=DATE:99991231"
    for shift in (1440, -1440):
        assert recurrence.between(edge, start, shift, start, weekly[-1]) == weekly
        assert recurrence.upcoming(edge, start, shift, start) == start
        assert recurrence.exception_starts(edge, start, shift)[1]
        assert recurrence.last_start(edge, start, shift) is None


def test_a_repeat_moves_with_its_start():
    """Mondays at 00:30 in Berlin, moved to noon: still Mondays, the shift
    taken again, and a skipped Monday skipped at its new time."""
    rule = "RRULE:FREQ=WEEKLY;BYDAY=MO\nEXDATE:20261011T223000Z"
    noon = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)
    moved, shift = recurrence.restarted(rule, 1440, EAST, noon, "Europe/Berlin")
    assert (moved, shift) == (
        "RRULE:FREQ=WEEKLY;BYDAY=MO\nEXDATE:20261012T100000Z",
        0,
    )
    # Without a zone the shift stays.
    assert recurrence.restarted(rule, 1440, EAST, noon, None)[1] == 1440


@pytest.mark.parametrize(
    ("rule", "start", "days", "new_start"),
    [
        # Mondays and Wednesdays from a Monday: a Monday again, the nearest.
        (
            "FREQ=WEEKLY;BYDAY=MO,WE",
            datetime(2026, 10, 5, 9),
            10,
            datetime(2026, 10, 12, 9),
        ),
        # The second Tuesday, and the 15th: the nearest of each.
        (
            "FREQ=MONTHLY;BYDAY=2TU",
            datetime(2026, 10, 13, 9),
            20,
            datetime(2026, 11, 10, 9),
        ),
        ("FREQ=MONTHLY", datetime(2026, 10, 15, 9), 40, datetime(2026, 11, 15, 9)),
        # Every day: exactly as far.
        ("FREQ=DAILY", datetime(2026, 10, 5, 9), 3, datetime(2026, 10, 8, 9)),
    ],
)
def test_a_moved_series_keeps_its_days_and_its_exceptions(rule, start, days, new_start):
    """Its start lands on its rule nearest the move, and what it skipped, where
    it ends and an occurrence of its own stay on the occurrence they named."""
    start, new_start = start.replace(tzinfo=UTC), new_start.replace(tzinfo=UTC)
    second, third, fourth = recurrence.first(rule, start, 0, 4)[1:]
    text = recurrence.skipped(f"RRULE:{rule};UNTIL={fourth:%Y%m%dT%H%M%SZ}", 0, second)

    series = recurrence.moved(text, start, 0, timedelta(days=days), occurrences=[third])

    assert series.start == new_start
    new_second, new_third, new_fourth = recurrence.first(
        f"RRULE:{rule}", new_start, 0, 4
    )[1:]
    assert series.occurrences == {third: new_third}
    assert recurrence.between(series.text, new_start, 0, new_start, new_fourth) == [
        new_start,
        new_third,
        new_fourth,
    ]
    assert not recurrence.occurs(series.text, new_start, 0, new_second)
    assert recurrence.last_start(series.text, new_start, 0) == new_fourth


def test_imports_read_either_shape():
    """A rule string comes with its shift; the JSON shape older exports carried
    was picked in a zone, which the importer's stands in for."""
    assert recurrence.imported(
        "FREQ=WEEKLY;BYDAY=MO", kind="task", start=EAST, tz="Europe/Berlin", shift=1440
    ) == ("RRULE:FREQ=WEEKLY;BYDAY=MO", 1440)
    legacy = {"frequency": "weekly", "weekdays": ["monday"], "ends": "never"}
    assert recurrence.imported(legacy, kind="task", start=EAST, tz="Europe/Berlin") == (
        "RRULE:FREQ=WEEKLY;BYDAY=MO",
        1440,
    )
    assert recurrence.imported(
        {"frequency": "hourly"}, kind="event", start=EAST, tz=None
    ) == (None, 0)
    assert recurrence.imported(
        "FREQ=WEEKLY", kind="event", start=EAST, tz=None, shift=1441
    ) == (None, 0)


def test_a_series_splits_skips_and_takes_extra_starts():
    """Weekly on Mondays at 06:30 UTC from 5 October, three times: cut at the
    second it is one Monday and the rest; a skip, a restore and an extra start
    are lines the rule keeps when it is written again."""
    start = datetime(2026, 10, 5, 6, 30, tzinfo=UTC)
    second = start + timedelta(weeks=1)
    rule = "RRULE:FREQ=WEEKLY;COUNT=3;BYDAY=MO"
    assert recurrence.split(rule, start, 0, second) == (
        "RRULE:FREQ=WEEKLY;COUNT=1;BYDAY=MO",
        "RRULE:FREQ=WEEKLY;COUNT=2;BYDAY=MO",
    )
    assert recurrence.split(rule, start, 0, start)[0] is None
    head, tail = recurrence.split("RRULE:FREQ=WEEKLY", start, 0, second)
    assert head == "RRULE:FREQ=WEEKLY;UNTIL=20261012T062959Z"
    assert tail == "RRULE:FREQ=WEEKLY"

    skipped = recurrence.skipped(rule, 0, second)
    assert recurrence.first(skipped, start, 0, 3) == [start, start + timedelta(weeks=2)]
    assert recurrence.exception_starts(skipped, start, 0) == ([second], [])
    assert recurrence.restored(skipped, 0, second) == rule
    extra = recurrence.with_extra(rule, 0, datetime(2026, 10, 7, 9, tzinfo=UTC))
    assert recurrence.kept_exceptions("RRULE:FREQ=DAILY", extra) == (
        "RRULE:FREQ=DAILY\nRDATE:20261007T090000Z"
    )
    # An extra start taken out again is gone, not skipped.
    assert recurrence.skipped(extra, 0, datetime(2026, 10, 7, 9, tzinfo=UTC)) == rule
    assert recurrence.occurs(rule, start, 0, second)
    assert not recurrence.occurs(rule, start, 0, second + timedelta(hours=1))
    # Every four hours, moved half an hour: each start moves by as much, rather
    # than every start of a day to one time. At named hours, each keeps its
    # hour and takes the new minute.
    later = start + timedelta(minutes=30)
    assert recurrence.rehomed(
        "RRULE:FREQ=HOURLY;INTERVAL=4", start + timedelta(hours=8), 0, 0, start, later
    ) == start + timedelta(hours=8, minutes=30)
    nine = datetime(2026, 10, 5, 9, tzinfo=UTC)
    assert recurrence.rehomed(
        "RRULE:FREQ=DAILY;BYHOUR=9,17",
        nine + timedelta(hours=8),
        0,
        0,
        nine,
        nine + timedelta(hours=2, minutes=30),
    ) == nine + timedelta(hours=8, minutes=30)


def test_a_walk_starts_near_its_window_and_ends_past_it():
    """An hourly series from the year 1 lists a day of 2026 from its own
    steps; a rule with no starts has none in any window; an open lookup finds
    a start within fifty years or four hundred steps, a counted series runs to
    its count, and an extra start is a date of its own."""
    day = datetime(2026, 9, 30, tzinfo=UTC)
    assert recurrence.between(
        "RRULE:FREQ=HOURLY;INTERVAL=5",
        datetime(1, 1, 1, 2, 30, tzinfo=UTC),
        0,
        day,
        day + timedelta(hours=12),
    ) == [datetime(2026, 9, 30, h, 30, tzinfo=UTC) for h in (0, 5, 10)]
    # Every fifth month on the 31st, where a month has one, at 09:15.
    start = datetime(1950, 1, 31, 9, 15)
    assert recurrence.between(
        "RRULE:FREQ=MONTHLY;INTERVAL=5",
        start.replace(tzinfo=UTC),
        0,
        day,
        day + timedelta(days=400),
    ) == [
        value.replace(tzinfo=UTC)
        for value in rrulestr("RRULE:FREQ=MONTHLY;INTERVAL=5", dtstart=start).between(
            day.replace(tzinfo=None), day.replace(tzinfo=None) + timedelta(days=400)
        )
    ]
    never = "RRULE:FREQ=HOURLY;BYMONTH=2;BYMONTHDAY=30"
    late = datetime(9000, 1, 1, tzinfo=UTC)
    assert recurrence.between(never, day, 0, late, late + timedelta(days=400)) == []
    assert recurrence.first(never, day, 0, 5) == []
    assert recurrence.next_start(never, day) is None
    assert recurrence.upcoming(never, day, 0, day) == day
    # Leap days a century apart: 2000, then 2400.
    leap = "RRULE:FREQ=YEARLY;INTERVAL=100;BYMONTH=2;BYMONTHDAY=29"
    leap_day = datetime(2000, 2, 29, tzinfo=UTC)
    after = datetime(2400, 2, 29, tzinfo=UTC)
    assert recurrence.next_start(leap, leap_day) == after
    assert recurrence.upcoming(f"{leap};UNTIL=27000101", leap_day, 0, late) == after
    assert recurrence.last_start("RRULE:FREQ=YEARLY;COUNT=101", day) == datetime(
        2126, 9, 30, tzinfo=UTC
    )
    assert recurrence.normalize("FREQ=YEARLY;INTERVAL=366;COUNT=1", kind="event")
    # Saved from its start, a repeat has to happen, and a counted one to reach
    # its count within a hundred years: a hundred leap days take four hundred.
    new_year = datetime(2026, 1, 1, tzinfo=UTC)
    leap_days = "FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=29;COUNT="
    with pytest.raises(recurrence.OutOfReach):
        recurrence.stored(f"{leap_days}101", new_year, None, kind="event")
    with pytest.raises(recurrence.OutOfReach):
        recurrence.stored(never, day, None, kind="event")
    rule, _ = recurrence.stored(f"{leap_days}20", new_year, None, kind="event")
    assert recurrence.last_start(rule, new_year) == datetime(2108, 2, 29, tzinfo=UTC)
    extra = "RRULE:FREQ=DAILY;COUNT=3\nRDATE:20800101T000000Z"
    in_2080 = datetime(2080, 1, 1, tzinfo=UTC)
    assert recurrence.last_start(extra, day) == in_2080
    assert recurrence.between(extra, day, 0, in_2080, in_2080) == [in_2080]
