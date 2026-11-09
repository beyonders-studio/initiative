"""Todoist's CSV export → this app's project envelope.

Pure: it takes the text of an export and returns the document an ordinary
import already applies. Nothing here talks to Todoist, and nothing on the
apply path knows Todoist exists.

**How the file is shaped.** One row per thing, discriminated by ``TYPE``:

``meta``
    The project's own settings (``view_style=board`` and the like). Skipped.
``section``
    A column. Everything after it belongs to it until the next one, so
    sections become the project's statuses and the rows between them are
    placed by position in the file rather than by any field.
``task``
    A task at ``INDENT`` 1. Deeper indents are that task's checklist —
    Todoist nests tasks arbitrarily, this app nests them once, so every
    descendant lands on the nearest top-level task's list.
``note``
    A comment on the row above it. Todoist writes no id anywhere in this
    file, so "the row above" is the only association there is.

**One thing the file cannot give us.** Todoist omits completed tasks from a
CSV export, so an imported project is the work still outstanding. Nothing
here can recover the rest, and the wizard says so before the upload.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import UTC, date, datetime, time
from typing import Any

from app.core import recurrence
from app.core.user_input_validators import resolve_zone
from app.models.tenant.task import TaskPriority
from app.services.import_engine.mapping import (
    DEFAULT_TAG_COLOR,
    POSITION_STEP,
    MappedProject,
    SourceOption,
    build_envelope,
    iso_from_date,
    repeat_fields,
    statuses_from_names,
)

#: Todoist counts down — 1 is the urgent one — which is the opposite of how
#: it reads, and the reason this is a table rather than arithmetic.
PRIORITY_BY_TODOIST: dict[int, TaskPriority] = {
    1: TaskPriority.urgent,
    2: TaskPriority.high,
    3: TaskPriority.medium,
    4: TaskPriority.low,
}

#: What a section-less file calls its one column.
UNSECTIONED = "Tasks"

#: A Todoist export names one project and does not say which, so the whole
#: file is the only selection there is.
SINGLE_KEY = "todoist"


def _rows(content: str) -> list[dict[str, str]]:
    """Every row of the export, however the file was written out.

    A BOM survives a round trip through a spreadsheet, and so does a
    semicolon delimiter in the locales where that is what a spreadsheet
    writes; both are read here rather than refused.
    """
    text = content.lstrip("﻿")
    if not text.strip():
        return []
    sample = text[:4096]
    delimiter = ","
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        pass
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    return [
        {(key or "").strip().upper(): (value or "") for key, value in row.items()}
        for row in reader
    ]


def _cell(row: dict[str, str], name: str) -> str:
    return (row.get(name) or "").strip()


def _int(value: str, default: int) -> int:
    try:
        return int(value)
    except TypeError, ValueError:
        return default


# A repeating Todoist task's DATE is the phrase it was typed as ("every
# monday at 9am", "every! 2 weeks"), and the export drops when the repeat
# started. What follows reads the phrases Todoist documents in English; any
# other phrase, or language, leaves the task without its repeat.

_WEEKDAYS = {
    **dict.fromkeys(("monday", "mon"), "MO"),
    **dict.fromkeys(("tuesday", "tue", "tues"), "TU"),
    **dict.fromkeys(("wednesday", "wed"), "WE"),
    **dict.fromkeys(("thursday", "thu", "thur", "thurs"), "TH"),
    **dict.fromkeys(("friday", "fri"), "FR"),
    **dict.fromkeys(("saturday", "sat"), "SA"),
    **dict.fromkeys(("sunday", "sun"), "SU"),
}
_WORKDAYS = "MO,TU,WE,TH,FR"
_MONTHS = {
    name: number
    for number, names in enumerate(
        (
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ),
        start=1,
    )
    for name in names
}
_ORDINALS = {
    **dict.fromkeys(("first", "1st"), 1),
    **dict.fromkeys(("second", "2nd"), 2),
    **dict.fromkeys(("third", "3rd"), 3),
    **dict.fromkeys(("fourth", "4th"), 4),
    **dict.fromkeys(("fifth", "5th"), 5),
    "last": -1,
}
_UNITS = {"day": "DAILY", "week": "WEEKLY", "month": "MONTHLY", "year": "YEARLY"}
_SHORTHAND = {
    "daily": "every day",
    "everyday": "every day",
    "weekly": "every week",
    "monthly": "every month",
    "yearly": "every year",
}
#: ``every!``, ``ev!`` and ``after`` count from when the task is done.
_PREFIX = re.compile(r"(every!|ev!|every|ev|after)\s+(.+)")
_AT = re.compile(r"\s+at\s+(.+)$")
_CLOCK = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?")
_DAY_OF_MONTH = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?")


def _clock(text: str) -> time | None:
    if text in ("noon", "midnight"):
        return time(12 if text == "noon" else 0)
    match = _CLOCK.fullmatch(text)
    if match is None:
        return None
    hour, minute, half = int(match[1]), int(match[2] or 0), match[3]
    if half:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if half == "pm" else 0)
    return time(hour, minute) if hour < 24 and minute < 60 else None


def _month_day(text: str) -> int | None:
    if text == "last day":
        return -1
    match = _DAY_OF_MONTH.fullmatch(text)
    return int(match[1]) if match and 1 <= int(match[1]) <= 31 else None


def _rule(body: str) -> str | None:
    """What follows "every" as an RRULE."""
    if body in ("weekday", "workday"):
        return f"FREQ=WEEKLY;BYDAY={_WORKDAYS}"
    if body in _UNITS:
        return f"FREQ={_UNITS[body]}"
    if match := re.fullmatch(r"(\d+|other)\s+(day|week|month|year)s?", body):
        interval = 2 if match[1] == "other" else int(match[1])
        return f"FREQ={_UNITS[match[2]]};INTERVAL={interval}"
    words = body.split()
    if len(words) == 2 and words[0] == "other" and words[1] in _WEEKDAYS:
        return f"FREQ=WEEKLY;INTERVAL=2;BYDAY={_WEEKDAYS[words[1]]}"
    if len(words) == 2 and words[0] in _ORDINALS:
        nth = _ORDINALS[words[0]]
        if words[1] in _WEEKDAYS:
            return f"FREQ=MONTHLY;BYDAY={nth}{_WEEKDAYS[words[1]]}"
        if words[1] == "workday" and nth in (1, -1):
            return f"FREQ=MONTHLY;BYDAY={_WORKDAYS};BYSETPOS={nth}"
    if len(words) == 2 and (words[0] in _MONTHS or words[1] in _MONTHS):
        month, day = words if words[0] in _MONTHS else words[::-1]
        if (number := _month_day(day)) is not None and number > 0:
            return f"FREQ=YEARLY;BYMONTH={_MONTHS[month]};BYMONTHDAY={number}"
    items = [item.strip() for item in re.split(r",|\s+and\s+", body) if item.strip()]
    if items and all(item in _WEEKDAYS for item in items):
        days = dict.fromkeys(_WEEKDAYS[item] for item in items)
        return f"FREQ=WEEKLY;BYDAY={','.join(days)}"
    month_days = [_month_day(item) for item in items]
    if items and None not in month_days:
        days = dict.fromkeys(str(day) for day in month_days)
        return f"FREQ=MONTHLY;BYMONTHDAY={','.join(days)}"
    return None


def _repeat(phrase: str) -> tuple[str, bool, time | None] | None:
    """A Todoist repeat phrase as an RRULE, whether it counts from completion,
    and the time of day it names."""
    text = " ".join(phrase.lower().split())
    at = None
    if match := _AT.search(text):
        at = _clock(match[1])
        if at is None:
            return None
        text = text[: match.start()]
    text = _SHORTHAND.get(text, text)
    match = _PREFIX.fullmatch(text)
    if match is None:
        return None
    prefix, body = match.groups()
    if prefix == "after" and not re.fullmatch(r"\d+\s+(day|week|month|year)s?", body):
        return None
    rule = _rule(body)
    rolling = prefix in ("every!", "ev!", "after")
    return (f"RRULE:{rule}", rolling, at) if rule else None


def _repeating(
    phrase: str, zone: str | None, now: datetime, deadline: str | None
) -> dict[str, Any]:
    """A repeating task's due date and repeat fields. The export drops when
    the repeat started, so it is due on its first date from ``now``: today's
    date, or a time of day still to come. A time of day is in the task's zone;
    without one the task is a day, which the app reads at midnight UTC, as it
    does a plain Todoist date. A deadline beside a repeat is when it stops."""
    found = _repeat(phrase)
    if found is None:
        return {}
    rule, rolling, at = found
    tz = zone if at else None
    if deadline:
        # The end of the deadline's day where the repeat's times are read.
        end = datetime.combine(
            date.fromisoformat(deadline[:10]), time(23, 59, 59), resolve_zone(tz)
        )
        rule += f";UNTIL={end.astimezone(UTC):%Y%m%dT%H%M%SZ}"
    anchor = datetime.combine(
        now.astimezone(resolve_zone(tz)).date(), at or time(), resolve_zone(tz)
    )
    fields = repeat_fields(rule, anchor.isoformat(), tz, rolling=rolling)
    if not fields:
        return {}
    starts = recurrence.first(
        fields["recurrence"], anchor, fields["recurrence_shift"], 2
    )
    due = next((start for start in starts if at is None or start >= now), None)
    return {"due_date": due.isoformat(), **fields} if due else {}


def _person(raw: str) -> str:
    """Todoist writes a person as ``name (12345)``; the name is the part that
    means anything anywhere else."""
    name = raw.strip()
    if name.endswith(")") and "(" in name:
        name = name[: name.rindex("(")].strip()
    return name


def preview(content: str) -> list[SourceOption]:
    """What the file holds: one project, and how much of it.

    Todoist exports a project at a time and writes its name nowhere in the
    file, so there is nothing to choose between — the count is the whole
    point of showing this step at all.
    """
    tasks = sum(
        1
        for row in _rows(content)
        if _cell(row, "TYPE").lower() == "task"
        and _cell(row, "CONTENT")
        and _int(_cell(row, "INDENT"), 1) == 1
    )
    return [SourceOption(key=SINGLE_KEY, name="Todoist project", task_count=tasks)]


def build_project_envelope(
    content: str,
    *,
    selection: str,
    app_version: str,
    now: datetime | None = None,
) -> MappedProject:
    """The whole export as the envelope an ordinary import applies.

    ``selection`` is the name to give the project. Todoist writes the
    project's own name nowhere in the file, so unlike the other sources there
    is nothing to pick between — what the wizard collects is a name. ``now``
    is when a repeating task's next date is counted from.
    """
    now = now or datetime.now(UTC)
    rows = _rows(content)
    section_names: list[str] = []
    current_section: str | None = None
    tasks: list[dict[str, Any]] = []
    last_task: dict[str, Any] | None = None
    skipped = 0

    for row in rows:
        kind = _cell(row, "TYPE").lower()
        if kind == "meta" or not kind:
            continue
        if kind == "section":
            heading = _cell(row, "CONTENT")
            if heading:
                current_section = heading
                if heading not in section_names:
                    section_names.append(heading)
            continue
        if kind == "note":
            body = _cell(row, "CONTENT")
            if body and last_task is not None:
                last_task["comments"].append(
                    {
                        "author_name": _person(_cell(row, "AUTHOR")) or None,
                        "body": body,
                    }
                )
            elif body:
                skipped += 1
            continue
        if kind != "task":
            continue

        title = _cell(row, "CONTENT")
        if not title:
            skipped += 1
            continue

        if _int(_cell(row, "INDENT"), 1) > 1:
            if last_task is None:
                skipped += 1
                continue
            last_task["checklist"].append({"text": title, "done": False})
            continue

        # Todoist's two dates mean different things: DATE is when the work is
        # scheduled, DEADLINE is when it is actually due. With both, they map
        # to the two fields they describe; with only one, it is the due date,
        # because that is what a lone Todoist date means to the person who
        # set it.
        scheduled = iso_from_date(_cell(row, "DATE"))
        deadline = iso_from_date(_cell(row, "DEADLINE"))
        due = deadline or scheduled
        start = scheduled if deadline else None

        task: dict[str, Any] = {
            "title": title,
            "description": _cell(row, "DESCRIPTION") or None,
            "status_name": current_section or UNSECTIONED,
            "priority": PRIORITY_BY_TODOIST.get(
                _int(_cell(row, "PRIORITY"), 4), TaskPriority.low
            ).value,
            "position": (len(tasks) + 1) * POSITION_STEP,
            "tags": [],
            "assignee_handles": [],
            "checklist": [],
            "properties": [],
            "links": [],
            "comments": [],
        }
        if due:
            task["due_date"] = due
        if start:
            task["start_date"] = start
        # A repeating DATE is a phrase rather than a date. It says when the
        # task is due and how it repeats, until any deadline beside it.
        if _cell(row, "DATE_LANG") in ("", "en"):
            task.update(
                _repeating(
                    _cell(row, "DATE"), _cell(row, "TIMEZONE") or None, now, deadline
                )
            )
        assignee = _person(_cell(row, "RESPONSIBLE"))
        if assignee:
            task["assignee_handles"] = [assignee]
        tasks.append(task)
        last_task = task

    # Tasks that appeared before any section need a column of their own, and
    # it has to come first because that is where they are in the file.
    if any(task["status_name"] == UNSECTIONED for task in tasks):
        section_names.insert(0, UNSECTIONED)

    statuses = statuses_from_names(section_names)
    known = {status["name"] for status in statuses}
    default_name = next(
        (status["name"] for status in statuses if status["is_default"]),
        statuses[0]["name"],
    )
    for task in tasks:
        if task["status_name"] not in known:
            task["status_name"] = default_name

    warnings: list[str] = []
    if tasks:
        warnings.append("TODOIST_EXPORT_OMITS_COMPLETED")

    return MappedProject(
        envelope=build_envelope(
            name=selection or "Todoist import",
            description=None,
            statuses=statuses,
            tasks=tasks,
            app_version=app_version,
            source_url="https://todoist.com",
        ),
        skipped_rows=skipped,
        warnings=warnings,
    )


__all__ = [
    "DEFAULT_TAG_COLOR",
    "SINGLE_KEY",
    "build_project_envelope",
    "preview",
]
