from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import icalendar
import pytest
from dateutil.rrule import rrulestr

from app.core import recurrence
from app.services.tenant import ical_service


@pytest.mark.parametrize(
    "zone_name",
    ["Asia/Kolkata", "Asia/Kathmandu", "America/St_Johns", "Pacific/Chatham"],
)
def test_fractional_offset_repeat_survives_ical_export_and_import(zone_name):
    start = datetime(2026, 10, 20, 9, tzinfo=ZoneInfo(zone_name))
    rule, shift = recurrence.stored(
        "FREQ=DAILY;BYHOUR=9", start, zone_name, kind="event"
    )
    exported = ical_service.ical_from_export_dicts(
        [
            {
                "id": 1,
                "title": "Morning meeting",
                "start_at": start.isoformat(),
                "end_at": (start + timedelta(hours=1)).isoformat(),
                "all_day": False,
                "recurrence": rule,
                "recurrence_shift": shift,
            }
        ]
    )
    calendar = icalendar.Calendar.from_ical(exported)
    parsed = calendar.walk("VEVENT")[0]
    # A subscriber must resolve the same instant without knowing our importer.
    assert parsed.decoded("dtstart").astimezone(UTC) == start.astimezone(UTC)
    assert calendar.walk("VTIMEZONE")
    imported, errors, skipped = ical_service.build_calendar_events(
        exported.decode(), 1, 1
    )
    assert (errors, skipped) == ([], 0)
    event = imported[0]
    assert event.start_at == start
    assert event.end_at == start + timedelta(hours=1)
    assert recurrence.first(
        event.recurrence, event.start_at, event.recurrence_shift, 3
    ) == [(start + timedelta(days=days)).astimezone(UTC) for days in (0, 1, 2)]


@pytest.mark.parametrize(
    ("start", "shift"),
    [
        (datetime(2026, 10, 4, 22, 30, tzinfo=UTC), 1440),
        (datetime(2026, 10, 6, 2, 30, tzinfo=UTC), -1440),
    ],
)
def test_picked_date_exceptions_survive_ical_round_trip(start, shift):
    rule = (
        "RRULE:FREQ=WEEKLY;BYDAY=MO\nEXDATE;VALUE=DATE:20261012\n"
        "RDATE;VALUE=DATE:20261020"
    )
    exported = ical_service.ical_from_export_dicts(
        [
            {
                "id": 1,
                "start_at": start.isoformat(),
                "end_at": (start + timedelta(hours=1)).isoformat(),
                "recurrence": rule,
                "recurrence_shift": shift,
            }
        ]
    )
    imported, errors, skipped = ical_service.build_calendar_events(
        exported.decode(), 1, 1
    )
    assert (errors, skipped) == ([], 0)
    event = imported[0]
    assert recurrence.first(
        event.recurrence, event.start_at, event.recurrence_shift, 5
    ) == (recurrence.first(rule, start, shift, 5))


@pytest.mark.parametrize(
    ("properties", "expected_start", "expected_end"),
    [
        (
            "DTSTART:20261020T090000Z\r\nDURATION:PT2H",
            "2026-10-20T09:00:00+00:00",
            "2026-10-20T11:00:00+00:00",
        ),
        (
            "DTSTART;VALUE=DATE:20261020\r\nDURATION:P3D",
            "2026-10-20T00:00:00+00:00",
            "2026-10-22T23:59:59+00:00",
        ),
        # Nominal days retain local time across DST; exact hours retain elapsed time.
        (
            "DTSTART;TZID=Europe/Amsterdam:20260328T120000\r\nDURATION:P1D",
            "2026-03-28T11:00:00+00:00",
            "2026-03-29T10:00:00+00:00",
        ),
        (
            "DTSTART;TZID=Europe/Amsterdam:20260328T120000\r\nDURATION:PT24H",
            "2026-03-28T11:00:00+00:00",
            "2026-03-29T11:00:00+00:00",
        ),
    ],
)
def test_ical_duration_sets_the_imported_event_end(
    properties, expected_start, expected_end
):
    content = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:duration\r\n"
        f"SUMMARY:Duration\r\n{properties}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    imported, errors, skipped = ical_service.build_calendar_events(content, 1, 1)
    assert (errors, skipped) == ([], 0)
    assert imported[0].start_at.astimezone(UTC).isoformat() == expected_start
    assert imported[0].end_at.astimezone(UTC).isoformat() == expected_end


def test_duration_preserves_case_insensitive_components_and_ignores_alarm_duration():
    content = (
        "begin:vcalendar\r\nversion:2.0\r\nbegin:vevent\r\nuid:duration\r\n"
        "dtstart:20261020T090000Z\r\nduration:PT2H\r\n"
        "begin:valarm\r\naction:DISPLAY\r\ntrigger:-PT5M\r\n"
        "duration:PT1M\r\nrepeat:1\r\nend:valarm\r\n"
        "end:vevent\r\nend:vcalendar\r\n"
    )
    imported, errors, skipped = ical_service.build_calendar_events(content, 1, 1)
    assert (errors, skipped) == ([], 0)
    assert imported[0].end_at == datetime(2026, 10, 20, 11, tzinfo=UTC)


def _feed(rule: str, start: datetime, *, tz: str | None = "Europe/London"):
    """One repeat, picked in UTC, as a subscription (``tz``) or a download."""
    return icalendar.Calendar.from_ical(
        ical_service.ical_from_export_dicts(
            [
                {
                    "id": 1,
                    "title": "Rehearsal",
                    "start_at": start.isoformat(),
                    "end_at": (start + timedelta(hours=1)).isoformat(),
                    "all_day": False,
                    "recurrence": rule,
                    "recurrence_shift": 0,
                }
            ],
            tz=tz,
        )
    )


@pytest.mark.parametrize("hour", [18, 23])
def test_a_subscription_anchors_a_days_repeat_off_utc(hour):
    """With ``X-WR-TIMEZONE`` an app may read a UTC start in that zone, so a
    repeat of days is written an hour off UTC, on its own date. Read strictly,
    it still lands where Initiative puts it, across the October clock change."""
    start = datetime(2026, 10, 19, hour, 30, tzinfo=UTC)
    rule = "RRULE:FREQ=WEEKLY;BYDAY=MO"
    feed = _feed(rule, start)
    event = feed.walk("VEVENT")[0]
    anchor = event.decoded("dtstart")

    assert feed["X-WR-TIMEZONE"] == "Europe/London"
    assert not icalendar.is_utc(anchor)
    assert anchor.date() == start.date()
    read = rrulestr(event["RRULE"].to_ical().decode(), dtstart=anchor)
    assert [moment.astimezone(UTC) for moment in read[:4]] == (
        recurrence.first(rule, start, 0, 4)
    )
    # A download names no zone, so its starts stay as stored.
    download = _feed(rule, start, tz=None)
    assert "X-WR-TIMEZONE" not in download
    assert download.walk("VEVENT")[0].decoded("dtstart") == start


def test_a_subscription_with_a_repeat_of_hours_in_utc_names_no_zone():
    """A rule of hours keeps its exact offset, UTC here, so the feed leaves the
    header out rather than have it move the repeat."""
    start = datetime(2026, 10, 19, 9, tzinfo=UTC)
    feed = _feed("RRULE:FREQ=DAILY;BYHOUR=9,17", start)

    assert "X-WR-TIMEZONE" not in feed
    assert feed.walk("VEVENT")[0].decoded("dtstart") == start
