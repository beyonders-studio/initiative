"""The calendar-event dataset.

Read off ``CalendarEvent``: its columns, the calendar picker its foreign key
implies, and its tags. Events carry no grants of their own — access derives from
the parent calendar — so nothing here says anything about permission; the
policies on the table answer that.
"""

from __future__ import annotations

from app.core.tools import Tool
from app.models.tenant.calendar_event import CalendarEvent
from app.services.fields.derive import derive_fields
from app.services.fields.spec import Dataset, Hop, Relation

#: A recurrence rule and its end are instructions to the calendar, not values
#: anybody narrows a list by.
_INTERNAL = frozenset(
    {
        "recurrence",
        "recurrence_until",
        "recurrence_shift",
        "series_id",
        "original_start",
        "overridden_fields",
    }
)


def build() -> Dataset:
    return Dataset(
        model=CalendarEvent,
        # Sharing is the calendar's: an event is reached by whoever reaches the
        # calendar it is on, which is the answer the gates already give.
        tool=Tool.calendar,
        name_override="calendar_events",
        fields=derive_fields(CalendarEvent, internal=_INTERNAL),
        relations=(
            Relation(
                name="calendar",
                hops=(Hop(dataset="calendars", left="calendar_id", right="id"),),
            ),
        ),
    )
