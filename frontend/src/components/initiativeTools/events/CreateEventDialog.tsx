import { useContext, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";

import type {
  CalendarEventCreate,
  CalendarEventRead,
  CalendarSummary,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { AddItemDialog } from "@/components/layouts/AddItemDialog";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAuth } from "@/hooks/useAuth";
import { useCreateCalendarEvent } from "@/hooks/useCalendarEvents";
import { useCalendar, useCalendarsList } from "@/hooks/useCalendars";
import { ItemDraftContext } from "@/hooks/useFieldSave";
import { sharedTarget } from "@/hooks/useToolLayouts";
import { blankEvent, EVENT_DETAIL } from "@/lib/layouts/eventLayout";
import { getItem, setItem } from "@/lib/storage";
import type { DialogProps } from "@/types/dialog";
import { Button } from "@/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Label } from "@/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

import { eventRange } from "./EventDateTimeFields";
import { shiftEndPreservingDuration, toDateKey } from "./eventDateTime";

/** A calendar the user may author events in — `can.contribute` on the
 * calendar is the event-create gate (like task creation via project write). */
export const isWritableCalendar = (calendar: CalendarSummary): boolean => calendar.can.contribute;

const LAST_CALENDAR_KEY = "initiative-last-event-calendar";

type CreateEventDialogProps = DialogProps & {
  /** If provided, the calendar is locked and the picker is hidden. */
  calendarId?: number;
  /** If provided, pre-selects this calendar (but the user can change it). */
  defaultCalendarId?: number;
  /** Restrict the picker to this initiative's calendars (initiative tab). */
  initiativeId?: number;
  defaultStartDate?: string;
  defaultStartTime?: string;
  onSuccess?: (event: CalendarEventRead) => void;
};

/** Which calendar an event being added goes in. Attendees and properties are
 *  its initiative's, so another calendar starts over with neither, but for
 *  whoever adds it. */
const CalendarPick = ({
  calendars,
  event,
}: {
  calendars: CalendarSummary[];
  event: CalendarEventRead;
}) => {
  const { t } = useTranslation("calendars");
  const { user } = useAuth();
  const draft = useContext(ItemDraftContext);
  return (
    <div className="space-y-2">
      <Label htmlFor="create-event-calendar">{t("calendar")}</Label>
      <Select
        value={event.calendar_id ? String(event.calendar_id) : ""}
        onValueChange={(value) => {
          const calendar = calendars.find((each) => String(each.id) === value);
          if (!calendar || !draft) return;
          draft.edit({
            patch: { calendar_id: calendar.id, attendee_ids: user ? [user.id] : [] },
            shows: {
              calendar_id: calendar.id,
              initiative_id: calendar.initiative_id,
              attendees: event.attendees.filter((attendee) => attendee.user_id === user?.id),
            },
          });
          draft.edit({
            properties: { values: [], removed: event.properties.map((each) => each.property_id) },
            shows: {},
          });
        }}
      >
        <SelectTrigger id="create-event-calendar">
          <SelectValue placeholder={t("selectCalendar")} />
        </SelectTrigger>
        <SelectContent>
          {calendars.map((calendar) => (
            <SelectItem key={calendar.id} value={String(calendar.id)}>
              <span className="inline-flex items-center gap-2">
                <span
                  className="inline-block h-2.5 w-2.5 rounded-full"
                  style={{ backgroundColor: calendar.color }}
                />
                {calendar.name}
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
};

/** Adding an event, drawn as its calendar's initiative lays events out. */
export const CreateEventDialog = ({
  open,
  onOpenChange,
  calendarId,
  defaultCalendarId,
  initiativeId,
  defaultStartDate,
  defaultStartTime,
  onSuccess,
}: CreateEventDialogProps) => {
  const { t } = useTranslation(["calendars", "dates", "common"]);
  const { user } = useAuth();
  const communityId = useActiveCommunityId();
  const leaving = useRef(false);

  // Calendars the current user may author events in (write on the calendar).
  // Locked to one calendar the picker is hidden, so there is no list to fill:
  // that calendar is read on its own instead. A community calendar's surface shows
  // community-level content only, and this is the one read on it that would
  // otherwise span the community's initiatives.
  const calendarsQuery = useCalendarsList(
    { page_size: 200, ...(initiativeId ? { initiative_id: initiativeId } : {}) },
    { enabled: open && calendarId === undefined }
  );
  const writableCalendars = useMemo(
    () => (calendarsQuery.data?.items ?? []).filter(isWritableCalendar),
    [calendarsQuery.data]
  );
  const locked = useCalendar(calendarId ?? null, { enabled: open }).data;
  const createEvent = useCreateCalendarEvent();

  // It starts in the calendar given, the one last added to, or the only one.
  const lastUsed = Number(getItem(`${LAST_CALENDAR_KEY}:${communityId}`) ?? "");
  const calendar =
    locked ??
    writableCalendars.find((each) => each.id === defaultCalendarId) ??
    writableCalendars.find((each) => each.id === lastUsed) ??
    (writableCalendars.length === 1 ? writableCalendars[0] : undefined);
  const startDate = defaultStartDate ?? toDateKey(new Date());
  const startTime = defaultStartTime ?? "09:00";
  const initialEnd = shiftEndPreservingDuration("", "", "", "", startDate, startTime);
  const range = eventRange({
    allDay: false,
    startDate,
    startTime,
    endDate: initialEnd?.endDate ?? startDate,
    endTime: initialEnd?.endTime ?? startTime,
    endInstant: initialEnd?.endInstant,
  });

  // Drawn once the calendars it may go in are known, so it starts in one.
  const known = calendarId !== undefined ? locked !== undefined : calendarsQuery.isSuccess;
  if (!known) return null;
  if (!range) {
    return (
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>{t("createEvent")}</DialogTitle>
            <DialogDescription role="alert">
              {t("dates:picker.invalidLocalDateTime")}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" onClick={() => onOpenChange(false)}>
              {t("common:close")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }
  return (
    <AddItemDialog
      open={open}
      onOpenChange={onOpenChange}
      detail={EVENT_DETAIL}
      blank={blankEvent(
        calendar,
        range,
        user
          ? {
              id: user.id,
              username: user.username,
              discriminator: user.discriminator,
              avatar_url: user.avatar_url,
              status: user.status,
              display_name: null,
            }
          : null
      )}
      context={{
        readOnly: false,
        initiativeId: calendar?.initiative_id ?? null,
        occurrence: undefined,
        occurrenceStart: range.start_at,
        shownStart: range.start_at,
        shownEnd: range.end_at,
        askScope: async () => null,
        onMoved: () => {},
        onShifted: () => {},
        leaving,
        actions: null,
      }}
      layouts={(event) =>
        event.initiative_id === null ? null : sharedTarget(Tool.calendar, event.initiative_id)
      }
      before={
        calendarId === undefined
          ? (event) => <CalendarPick calendars={writableCalendars} event={event} />
          : undefined
      }
      title={t("createEvent")}
      ready={(event) => event.title.trim() !== "" && event.calendar_id !== 0}
      create={({ item, fields, properties }) =>
        createEvent.mutateAsync({
          calendar_id: item.calendar_id,
          start_at: item.start_at,
          end_at: item.end_at,
          all_day: item.all_day,
          // Whoever adds it attends, unless they say otherwise.
          attendee_ids: user ? [user.id] : [],
          ...fields,
          properties,
        } as CalendarEventCreate)
      }
      onAdded={(event) => {
        setItem(`${LAST_CALENDAR_KEY}:${communityId}`, String(event.calendar_id));
        onOpenChange(false);
        onSuccess?.(event);
      }}
    />
  );
};
