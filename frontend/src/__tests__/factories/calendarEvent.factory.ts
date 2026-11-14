import {
  ActorKind,
  type CalendarEventRead,
  type CalendarEventSummary,
} from "@/api/generated/initiativeAPI.schemas";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

/** An event on a calendar of initiative 1, an hour long, that the reader may change. */
export function buildCalendarEvent(overrides: Partial<CalendarEventRead> = {}): CalendarEventRead {
  counter++;
  return {
    id: counter,
    title: `Event ${counter}`,
    description: null,
    location: null,
    start_at: "2026-10-20T15:00:00.000Z",
    end_at: "2026-10-20T16:00:00.000Z",
    all_day: false,
    rsvp_open: false,
    recurrence: null,
    recurrence_shift: 0,
    original_start: null,
    series_id: null,
    calendar_id: 1,
    initiative_id: 1,
    community_id: 1,
    created_by: 1,
    created_by_kind: ActorKind.member,
    created_by_install: null,
    properties: [],
    tags: [],
    can: { edit: true },
    created_at: "2026-10-01T00:00:00.000Z",
    updated_at: "2026-10-01T00:00:00.000Z",
    attendees: [],
    overridden_fields: [],
    skipped_starts: [],
    extra_starts: [],
    next_start: null,
    next_occurrence: null,
    ...overrides,
  };
}

/** The list/calendar shape, with the attendee previews its endpoint supplies. */
export function buildCalendarEventSummary(
  overrides: Partial<CalendarEventSummary> = {}
): CalendarEventSummary {
  return { ...buildCalendarEvent(), attendee_previews: [], ...overrides };
}
