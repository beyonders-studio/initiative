import {
  addOccurrence,
  createCalendarEvent,
  deleteCalendarEvent,
  detachOccurrence,
  duplicateCalendarEvent,
  getReadCalendarEventQueryKey,
  importIcalEvents,
  openOccurrence,
  parseIcalFile,
  restoreOccurrence,
  setAttendees,
  updateCalendarEvent,
  updateRsvp,
  useReadCalendarEvent,
} from "@/api/generated/calendar-events/calendar-events";
import {
  type CalendarEventCreate,
  type CalendarEventRead,
  type CalendarEventRSVPUpdate,
  type CalendarEventUpdate,
  type CalendarEventUpdateScope,
  type ICalImportRequest,
  type ICalImportResult,
  type ICalParseRequest,
  type ICalParseResult,
  PropertyTarget,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { isRepeating, occurrenceTarget } from "@/components/calendar/eventCalendarEntry";
import type { OccurrenceScope } from "@/components/recurrence/OccurrenceScopeDialog";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import {
  type FieldSaveKind,
  type FieldSaveOptions,
  useItemFieldSave,
  useShownWithPending,
} from "@/hooks/useFieldSave";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";
import { withZone } from "@/ui/recurrence/recurrence";

/**
 * One event. `occurrence` names one occurrence of a repeating event, whose
 * attendees' answers are shown in place of the series'.
 */
export const useCalendarEvent = (
  eventId: number | null,
  options?: QueryOpts<CalendarEventRead>,
  occurrence?: string | null
) => {
  const communityId = useActiveCommunityId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  const params = occurrence ? { occurrence } : undefined;
  const query = useReadCalendarEvent(communityId, eventId!, params, {
    query: { enabled: eventId !== null && Number.isFinite(eventId) && userEnabled, ...rest },
  });
  return useShownWithPending(eventSaves(occurrence), eventId, query);
};

/** A change to some of an event's fields. Its attendees are set as a whole,
 *  on a route of their own. */
export type EventPatch = CalendarEventUpdate & { attendee_ids?: number[] };

/** How an event is saved field by field, read at `occurrence` when it names
 *  one date of a repeating event. */
export const eventSaves = (
  occurrence?: string | null
): FieldSaveKind<CalendarEventRead, EventPatch> => ({
  name: "event",
  readKey: (communityId, id) =>
    getReadCalendarEventQueryKey(communityId, id, occurrence ? { occurrence } : undefined),
  patch: (communityId, id, { attendee_ids, ...patch }) =>
    attendee_ids
      ? setAttendees(communityId, id, attendee_ids, {
          scope: patch.scope ?? undefined,
          occurrence: patch.occurrence ?? undefined,
        })
      : updateCalendarEvent(communityId, id, withZone(patch)),
  properties: PropertyTarget.calendar_event,
  lists: (edit) =>
    "patch" in edit ? q.allCalendarEvents() : q.propertyHolder(PropertyTarget.calendar_event),
  itself: (id) => q.calendarEvent(id),
});

// The fields a change to one date of a repeating event may keep from the
// rest of it, so changing one asks which dates it is for.
const SERIES_FIELDS: (keyof EventPatch)[] = [
  "title",
  "description",
  "location",
  "start_at",
  "end_at",
  "all_day",
  "attendee_ids",
];

/** Where an event's page is: the date it shows, and how it asks and moves. */
export type EventSaveTarget = {
  /** The date the page was opened at, when it names one. */
  occurrence?: string | null;
  /** The date a change is about, by its start in the series. */
  occurrenceStart: string;
  askScope: (action: "edit") => Promise<OccurrenceScope | null>;
  onMoved: (moved: CalendarEventRead) => void;
  /** Takes the page to the date it shows, moved to `start` with every date of
   *  its series. */
  onShifted: (start: string) => void;
};

/**
 * What an event's page adds to a field's save: a change to a repeating event,
 * or to one date of it, asks which dates it is for, and its Undo is for the
 * same ones; "just this" and "from here on" answer with another event (the
 * date's own, or the new series), which `onMoved` takes the page to.
 */
export const eventSaveOptions = (
  event: CalendarEventRead,
  { occurrence, occurrenceStart, askScope, onMoved, onShifted }: EventSaveTarget
): FieldSaveOptions<CalendarEventRead, EventPatch> => {
  const repeating = isRepeating(event);
  return {
    prepare: async (edit) => {
      if (!repeating || !("patch" in edit)) return edit;
      if (!SERIES_FIELDS.some((name) => name in edit.patch)) return edit;
      const scope = await askScope("edit");
      if (scope === null) return null;
      return {
        ...edit,
        patch: { ...edit.patch, ...occurrenceTarget(event, scope, occurrenceStart) },
      };
    },
    // Undone for the dates the change was for.
    undoWith: (undo, edit) =>
      "patch" in undo && "patch" in edit
        ? {
            ...undo,
            patch: { ...undo.patch, scope: edit.patch.scope, occurrence: edit.patch.occurrence },
          }
        : undo,
    movedTo: (written) => {
      const moved = written.id !== undefined && written.id !== event.id;
      if (moved) onMoved(written as CalendarEventRead);
      return moved;
    },
    // Every date moved as the one shown did, so the page follows it there:
    // the date it named is no longer one of the series'.
    onSaved: (edit) => {
      if ("patch" in edit && occurrence && edit.patch.scope === "all" && edit.patch.start_at) {
        onShifted(edit.patch.start_at);
      }
    },
  };
};

/** The one way an event's page saves a field ({@link useItemFieldSave}), with
 *  what its page adds ({@link eventSaveOptions}). */
export const useEventFieldSave = (
  event: CalendarEventRead,
  label: string,
  target: EventSaveTarget
) =>
  useItemFieldSave(eventSaves(target.occurrence), event.id, label, eventSaveOptions(event, target));

// ── Mutations ───────────────────────────────────────────────────────────────

export const useCreateCalendarEvent = (
  options?: MutationOpts<CalendarEventRead, CalendarEventCreate>
) =>
  useCommunityMutation<CalendarEventRead, CalendarEventCreate>(
    {
      mutationFn: (communityId, data) => createCalendarEvent(communityId, data),
      invalidate: () => invalidate(q.allCalendarEvents()),
      errorKey: "calendars:error",
    },
    options
  );

/** Update an event, named per call so one hook serves any event on a page —
 *  the calendar's drag-to-reschedule does not know it until the drop. */
export const useUpdateCalendarEvent = (
  options?: MutationOpts<CalendarEventRead, { eventId: number; data: CalendarEventUpdate }>
) =>
  useCommunityMutation<CalendarEventRead, { eventId: number; data: CalendarEventUpdate }>(
    {
      mutationFn: (communityId, { eventId, data }) =>
        updateCalendarEvent(communityId, eventId, withZone(data)),
      invalidate: () => invalidate(q.allCalendarEvents()),
      errorKey: "calendars:error",
    },
    options
  );

/** Which occurrences of a repeating event a change is for, and the one named. */
export type OccurrenceTarget = {
  scope?: NonNullable<CalendarEventUpdateScope>;
  occurrence?: string;
};

export const useDeleteCalendarEvent = (
  options?: MutationOpts<void, { eventId: number } & OccurrenceTarget>
) =>
  useCommunityMutation<void, { eventId: number } & OccurrenceTarget>(
    {
      mutationFn: (communityId, { eventId, ...target }) =>
        deleteCalendarEvent(communityId, eventId, target),
      invalidate: () => invalidate(q.allCalendarEvents()),
      errorKey: "calendars:error",
    },
    options
  );

/** Copies the event, or with `occurrence` that one date of a repeating event. */
export const useDuplicateCalendarEvent = (
  options?: MutationOpts<CalendarEventRead, { eventId: number; occurrence?: string }>
) =>
  useCommunityMutation<CalendarEventRead, { eventId: number; occurrence?: string }>(
    {
      mutationFn: (communityId, { eventId, occurrence }) =>
        duplicateCalendarEvent(communityId, eventId, {
          occurrence,
        }),
      invalidate: () => invalidate(q.allCalendarEvents()),
      errorKey: "calendars:error",
    },
    options
  );

// ── iCal Import ─────────────────────────────────────────────────────────────

/** Read an .ics file and report what is in it. Writes nothing. */
export const useParseIcalFile = (options?: MutationOpts<ICalParseResult, ICalParseRequest>) =>
  useCommunityMutation<ICalParseResult, ICalParseRequest>(
    {
      mutationFn: (communityId, data) => parseIcalFile(communityId, data),
      errorKey: "calendars:import.parseFailed",
    },
    options
  );

/** Create the file's events in one calendar. */
export const useImportIcalEvents = (options?: MutationOpts<ICalImportResult, ICalImportRequest>) =>
  useCommunityMutation<ICalImportResult, ICalImportRequest>(
    {
      mutationFn: (communityId, data) => importIcalEvents(communityId, data),
      invalidate: () => invalidate(q.allCalendarEvents()),
      errorKey: "calendars:import.importError",
    },
    options
  );

// ── Association Mutations ───────────────────────────────────────────────────

export const useUpdateEventRSVP = (
  eventId: number,
  options?: MutationOpts<CalendarEventRead, CalendarEventRSVPUpdate>
) =>
  useCommunityMutation<CalendarEventRead, CalendarEventRSVPUpdate>(
    {
      mutationFn: (communityId, data) => updateRsvp(communityId, eventId, data),
      invalidate: () => invalidate(q.allCalendarEvents()),
      errorKey: "calendars:error",
    },
    options
  );

const OCCURRENCE_ACTIONS = {
  open: openOccurrence,
  detach: detachOccurrence,
  restore: restoreOccurrence,
  add: addOccurrence,
};

/**
 * One occurrence of a repeating event, by its start: `open` it as a row of
 * its own, `detach` it into an event of its own, `restore` it when skipped,
 * or `add` it as an extra start.
 */
export const useOccurrenceAction = (
  eventId: number,
  action: keyof typeof OCCURRENCE_ACTIONS,
  options?: MutationOpts<CalendarEventRead, string>
) =>
  useCommunityMutation<CalendarEventRead, string>(
    {
      mutationFn: (communityId, start) =>
        OCCURRENCE_ACTIONS[action](communityId, eventId, { start }),
      invalidate: () => invalidate(q.allCalendarEvents()),
      errorKey: "calendars:error",
    },
    options
  );
