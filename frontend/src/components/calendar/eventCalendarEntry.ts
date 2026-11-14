import type {
  CalendarEventSummary,
  CalendarEventUpdateScope,
} from "@/api/generated/initiativeAPI.schemas";
import { DEFAULT_COLOR } from "@/lib/initiativeColors";

import type { CalendarEntry } from "./CalendarView";

/** The UTC date of an instant, as `YYYY-MM-DD`: an all-day event's day. */
export const utcDateKey = (iso: string) => new Date(iso).toISOString().slice(0, 10);

/** The stored range for an all-day event dropped onto local days: those days as UTC dates. */
export const allDayRange = (startAt: string, endAt: string) => {
  const day = (iso: string) => {
    const d = new Date(iso);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  };
  return { start_at: `${day(startAt)}T00:00:00Z`, end_at: `${day(endAt)}T23:59:59Z` };
};

/** Whether a change to an event asks which of its dates it is for: it repeats,
 *  or it is one date of a series made its own. */
export const isRepeating = (event: Pick<CalendarEventSummary, "recurrence" | "series_id">) =>
  Boolean(event.recurrence) || event.series_id != null;

/** What a change to `event` at the date starting `occurrenceStart` names: an
 *  event that is one date's own names only the scope, and a series the date
 *  too. */
export const occurrenceTarget = (
  event: Pick<CalendarEventSummary, "series_id">,
  scope: NonNullable<CalendarEventUpdateScope>,
  occurrenceStart: string
): { scope: NonNullable<CalendarEventUpdateScope>; occurrence?: string } =>
  event.series_id != null ? { scope } : { scope, occurrence: occurrenceStart };

/** What an event's calendar entry carries for opening and rescheduling it. */
export type EventEntryMeta = {
  type: "event";
  eventId: number;
  calendarId: number;
  communityId: number;
  /** The date's start in its series, for every event that repeats
   *  ({@link isRepeating}): a change to it asks which dates it is for. */
  occurrence?: string;
  /** The series an event that is one date's own belongs to. */
  seriesId: number | null;
};

/**
 * The calendar entry for one event, drawn in its calendar's color.
 *
 * The id carries the community because the cross-community calendar holds events whose
 * per-community ids collide, and a repeating event's occurrence because the series
 * is there once for each; `meta` carries everything either calendar navigates
 * or reschedules by: an occurrence names its start in the series.
 */
export const buildEventCalendarEntry = (
  event: CalendarEventSummary,
  calendarColor: string | undefined,
  unread: boolean
): CalendarEntry => ({
  id: `event-${event.community_id}-${event.id}${event.original_start ? `@${event.original_start}` : ""}`,
  title: event.title,
  description: event.description,
  // An all-day event's dates are UTC dates; drawn as the same dates here.
  startAt: event.all_day ? `${utcDateKey(event.start_at)}T00:00:00` : event.start_at,
  endAt: event.all_day ? `${utcDateKey(event.end_at)}T23:59:59` : event.end_at,
  allDay: event.all_day,
  color: calendarColor ?? DEFAULT_COLOR,
  attendees: (event.attendee_previews ?? []).map((att) => ({
    name: att.name,
    avatarUrl: att.avatar_url,
    userId: att.user_id,
  })),
  properties: event.properties,
  tags: event.tags,
  draggable: event.can.edit,
  unread,
  meta: {
    type: "event",
    eventId: event.id,
    calendarId: event.calendar_id,
    communityId: event.community_id,
    // A series drawn once (its rule unread) still repeats, from its start.
    occurrence: isRepeating(event) ? (event.original_start ?? event.start_at) : undefined,
    seriesId: event.series_id,
  } satisfies EventEntryMeta,
});
