import { Link } from "@tanstack/react-router";
import { CalendarDays, MapPin, Repeat } from "lucide-react";
import {
  type ComponentType,
  type ReactNode,
  type RefObject,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import {
  type CalendarEventRead,
  type RSVPStatus,
  SearchEntityType,
  Tool,
  type UserPublic,
} from "@/api/generated/initiativeAPI.schemas";
import { isRepeating, utcDateKey } from "@/components/calendar/eventCalendarEntry";
import {
  EventDateTimeFields,
  type EventTiming,
  eventRange,
} from "@/components/initiativeTools/events/EventDateTimeFields";
import { toDateKey, toTimeSlot } from "@/components/initiativeTools/events/eventDateTime";
import { MemberMultiSelect } from "@/components/members/MemberSearchSelect";
import type { OccurrenceScope } from "@/components/recurrence/OccurrenceScopeDialog";
import { RecurrenceEditor } from "@/components/recurrence/RecurrenceEditor";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DateTimePicker } from "@/components/ui/date-time-picker";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/hooks/useAuth";
import {
  type EventPatch,
  eventSaveOptions,
  eventSaves,
  useEventFieldSave,
  useOccurrenceAction,
  useUpdateEventRSVP,
} from "@/hooks/useCalendarEvents";
import { ItemDraftContext } from "@/hooks/useFieldSave";
import { useCommunityPath } from "@/lib/communityUrl";
import { formatDate, formatDateTime } from "@/lib/formatDate";
import { dateTimeFormat } from "@/lib/intl";
import { toast } from "@/lib/mascotToast";
import {
  allDayReference,
  fromStored,
  type RecurrenceRule,
  rulePayload,
  summarizeStored,
} from "@/lib/recurrence";
import { referenceRef } from "@/lib/smartChips";
import { hour12Option } from "@/lib/timeFormat";
import { eventRoute } from "@/lib/tools";
import { getUserDisplayName } from "@/lib/userDisplay";
import type { TranslateFn } from "@/types/i18n";

import { type DetailKind, useItemContext } from "./DetailLayoutView";
import { filledBy, hasAny, hasText, sentOr } from "./detailLayout";
import { FieldFrame, sameIds, sameJson, useFieldDraft } from "./editing";
import { type EVENT_FIELDS, EVENT_LAYOUT, eventFields } from "./events";
import { DescriptionField, TagsField, TitleField } from "./fieldEditors";

/** What an event's detail shares with its parts, beside the event itself. */
export interface EventLayoutContext {
  /** The server says the reader cannot change the event: they see it, and
   *  nothing to change it with. */
  readOnly: boolean;
  initiativeId: number | null;
  /** The date of a repeating event the page was opened at, when it names one. */
  occurrence: string | undefined;
  /** The date a change here is about, by its start in the series. */
  occurrenceStart: string;
  /** When the date shown starts and ends. */
  shownStart: string;
  shownEnd: string;
  askScope: (action: "edit") => Promise<OccurrenceScope | null>;
  /** Takes the page to the event a change answered with: one date of a
   *  repeating event made its own, or the new series from it. */
  onMoved: (moved: CalendarEventRead) => void;
  /** Takes the page to the date it shows, moved with every date of its series. */
  onShifted: (start: string) => void;
  /** Set when the detail is left on purpose, so an open draft does not hold it. */
  leaving: RefObject<boolean>;
  /** Reporting it, and the menu of what else can be done with it. */
  actions: ReactNode;
  /** Drawn in the layout editor, where nothing is changed: a description
   *  draft kept on the device stays there. */
  preview?: boolean;
}

const useEventLayout = useItemContext<EventLayoutContext>;

type EditorProps = { item: CalendarEventRead; label: string };

/** A field's save, for the page it is on. */
const useSave = (event: CalendarEventRead, label: string) =>
  useEventFieldSave(event, label, useEventLayout());

const RSVP_LABEL_KEYS: Record<
  string,
  "rsvpPending" | "rsvpAccepted" | "rsvpDeclined" | "rsvpTentative"
> = {
  pending: "rsvpPending",
  accepted: "rsvpAccepted",
  declined: "rsvpDeclined",
  tentative: "rsvpTentative",
};

const rsvpBadgeVariant = (
  status: RSVPStatus
): "default" | "secondary" | "destructive" | "outline" =>
  status === "accepted"
    ? "default"
    : status === "declined"
      ? "destructive"
      : status === "tentative"
        ? "outline"
        : "secondary";

const DAY = { weekday: "long", year: "numeric", month: "long", day: "numeric" } as const;

const formatDay = (value: string, allDay: boolean) =>
  // An all-day event's date is its UTC date, the same for every viewer.
  dateTimeFormat(undefined, allDay ? { ...DAY, timeZone: "UTC" } : DAY).format(new Date(value));

const formatTime = (value: string) =>
  dateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
    hour12: hour12Option(),
  }).format(new Date(value));

/** An event's dates as a reader reads them: one day with its times, or from
 *  one moment to another. */
const formatRange = (start: string, end: string, allDay: boolean): string => {
  if (allDay) {
    const [first, last] = [formatDay(start, true), formatDay(end, true)];
    return first === last ? first : `${first} - ${last}`;
  }
  const [from, to] = [new Date(start), new Date(end)];
  const sameDay = from.toDateString() === to.toDateString();
  return sameDay
    ? `${formatDay(start, false)}, ${formatTime(start)} - ${formatTime(end)}`
    : `${formatDay(start, false)}, ${formatTime(start)} - ${formatDay(end, false)}, ${formatTime(end)}`;
};

/** The event's title, which is the detail's heading. */
const TitleEditor = ({ item: event, label }: EditorProps) => {
  const { t } = useTranslation("calendars");
  const { readOnly } = useEventLayout();
  return (
    <TitleField
      id="event-title"
      label={label}
      value={event.title}
      save={useSave(event, label)}
      readOnly={readOnly}
      placeholder={t("eventPage.titlePlaceholder")}
    />
  );
};

/** The description, as a task's is ({@link DescriptionField}). */
const DescriptionEditor = ({ item: event, label }: EditorProps) => {
  const { t } = useTranslation("calendars");
  const context = useEventLayout();
  return (
    <DescriptionField
      kind={eventSaves(context.occurrence)}
      id={event.id}
      options={eventSaveOptions(event, context)}
      label={label}
      htmlId="event-description"
      value={event.description}
      readOnly={context.readOnly}
      initiativeId={event.initiative_id}
      subject={referenceRef(SearchEntityType.calendar_event, event.id)}
      leaving={context.leaving}
      preview={context.preview}
      placeholder={t("descriptionPlaceholder")}
    />
  );
};

const LocationEditor = ({ item: event, label }: EditorProps) => {
  const { t } = useTranslation("calendars");
  const { readOnly } = useEventLayout();
  const save = useSave(event, label);
  const saved = event.location ?? "";
  const edit = (text: string) => {
    const location = text.trim() || null;
    return { patch: { location }, shows: { location } };
  };
  const draft = useFieldDraft(saved, (text) =>
    save.save(edit(text), text.trim() || !saved ? undefined : edit(saved))
  );
  if (readOnly) {
    return saved ? (
      <div className="flex items-start gap-3">
        <MapPin className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
        <p className="text-sm">{saved}</p>
      </div>
    ) : null;
  }
  return (
    <FieldFrame
      label={label}
      htmlFor="event-location"
      save={save}
      changed={draft.changed}
      keys={draft.keys}
    >
      <Input
        id="event-location"
        value={draft.value}
        onChange={(change) => draft.change(change.target.value)}
        placeholder={t("locationPlaceholder")}
      />
    </FieldFrame>
  );
};

/** When the date shown starts and ends, as the pickers hold it. */
const timingOf = (start: string, end: string, allDay: boolean): EventTiming => {
  const [from, to] = [new Date(start), new Date(end)];
  return {
    allDay,
    startInstant: start,
    endInstant: end,
    // An all-day event's dates are UTC dates.
    startDate: allDay ? utcDateKey(from.toISOString()) : toDateKey(from),
    startTime: toTimeSlot(from),
    endDate: allDay ? utcDateKey(to.toISOString()) : toDateKey(to),
    endTime: toTimeSlot(to),
  };
};

/** The start, the end and whether it lasts all day, saved as one. For one
 *  date of a repeating event they are that date's, which the change asks
 *  about. */
const DatesEditor = ({ event }: { event: CalendarEventRead }) => {
  const { t } = useTranslation(["calendars", "common"]);
  const context = useEventLayout();
  const { readOnly } = context;
  // One being added shows its own dates; one opened, the date it was opened at.
  const adding = useContext(ItemDraftContext) !== null;
  const [shownStart, shownEnd] = adding
    ? [event.start_at, event.end_at]
    : [context.shownStart, context.shownEnd];
  const label = t("eventPage.when");
  const save = useSave(event, label);
  const repeating = isRepeating(event);
  const draft = useFieldDraft(
    timingOf(shownStart, shownEnd, event.all_day),
    (timing) => {
      const range = eventRange(timing);
      if (!range) return Promise.resolve(false);
      const patch = { ...range, all_day: timing.allDay };
      // A series' own times are not the date's, so nothing shows until it answers.
      return save.save({ patch, shows: repeating ? {} : patch });
    },
    sameJson,
    (timing) => eventRange(timing) !== null
  );
  if (readOnly) {
    return (
      <div className="flex items-start gap-3">
        <CalendarDays className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
        <div className="flex flex-wrap items-center gap-2">
          <p className="font-medium">{formatRange(shownStart, shownEnd, event.all_day)}</p>
          {event.all_day ? <Badge variant="secondary">{t("common:calendar.allDay")}</Badge> : null}
        </div>
      </div>
    );
  }
  return (
    <FieldFrame label={label} save={save} changed={draft.changed} keys={draft.keys}>
      <EventDateTimeFields
        value={draft.value}
        onChange={(patch) => draft.edit({ ...draft.value, ...patch })}
      />
    </FieldFrame>
  );
};

/**
 * How the event repeats, and the dates it skips or adds. One date with a row
 * of its own repeats with its series, which is where that changes; opened at
 * one date of a series, it can be made a row of its own.
 *
 * A new rule is saved with Save, not as it is picked: it can take away dates
 * that have changes and answers of their own, and some rules take more than
 * one pick to say (an end date is picked after choosing to end on one).
 */
const RepeatEditor = ({ item: event, label }: EditorProps) => {
  const { t } = useTranslation(["calendars", "common"]);
  const { readOnly, occurrence, occurrenceStart, onMoved, initiativeId } = useEventLayout();
  const gp = useCommunityPath();
  const save = useSave(event, label);
  const saved: RecurrenceRule | "custom" | null = fromStored(
    event.recurrence,
    event.start_at,
    event.recurrence_shift,
    event.all_day
  );
  // The rule picked, until it is saved or put back. One being added takes it
  // as it is picked, and keeps showing it: it has no dates of its own to lose.
  const adding = useContext(ItemDraftContext) !== null;
  const [picked, setPicked] = useState<RecurrenceRule | "custom" | null | undefined>(undefined);
  const changed = !adding && picked !== undefined && !sameJson(picked, saved);
  const commit = async (rule = picked, allDay = event.all_day) => {
    if (rule === undefined || rule === "custom") return;
    const sent = await save.save({ patch: rulePayload(rule, { allDay }), shows: {} });
    // A rule picked while this one was saving is still to be saved.
    if (sent && !adding) setPicked((current) => (current === rule ? undefined : current));
  };
  // One being added sends its rule as it is picked, and again when it turns
  // all-day or back, which writes the rule's dates another way.
  const taken = useRef(commit);
  taken.current = commit;
  useEffect(() => {
    if (adding && picked !== undefined) void taken.current(picked, event.all_day);
  }, [adding, picked, event.all_day]);
  const openAlone = useOccurrenceAction(event.id, "open", { onSuccess: onMoved });
  const restoreDate = useOccurrenceAction(event.id, "restore", {
    onSuccess: () => toast.success(t("occurrence.restored")),
  });
  const [extraDate, setExtraDate] = useState("");
  const addDate = useOccurrenceAction(event.id, "add", {
    onSuccess: () => {
      toast.success(t("occurrence.added"));
      setExtraDate("");
    },
  });

  if (event.series_id != null) {
    return (
      <div className="flex items-start gap-3">
        <Repeat className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
        <div className="space-y-1 text-sm">
          <p>{t("occurrence.partOfSeries")}</p>
          <Link
            className="text-primary underline-offset-4 hover:underline"
            to={gp(eventRoute(initiativeId, event.calendar_id, event.series_id))}
          >
            {t("occurrence.openSeries")}
          </Link>
        </div>
      </div>
    );
  }
  if (readOnly) {
    return event.recurrence ? (
      <div className="flex items-start gap-3">
        <Repeat className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
        <p className="text-sm">
          {summarizeStored(
            event.recurrence,
            event.start_at,
            { shift: event.recurrence_shift, allDay: event.all_day },
            t as TranslateFn
          )}
        </p>
      </div>
    ) : null;
  }
  return (
    <FieldFrame label={label} hideLabel save={save}>
      <RecurrenceEditor
        kind="event"
        value={picked === undefined ? saved : picked}
        onChange={setPicked}
        referenceDate={event.all_day ? allDayReference(event.start_at) : event.start_at}
        allDay={event.all_day}
        stored={event.recurrence ? { rule: event.recurrence, shift: event.recurrence_shift } : null}
      />
      {changed ? (
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            disabled={picked === "custom" || save.state === "saving"}
            onClick={() => void commit()}
          >
            {t("common:save")}
          </Button>
          <Button type="button" size="sm" variant="outline" onClick={() => setPicked(undefined)}>
            {t("common:cancel")}
          </Button>
        </div>
      ) : null}
      {event.recurrence && occurrence ? (
        <Button
          type="button"
          variant="link"
          className="h-auto p-0"
          onClick={() => openAlone.mutate(occurrenceStart)}
          disabled={openAlone.isPending}
        >
          {t("occurrence.openAlone")}
        </Button>
      ) : null}
      {event.recurrence
        ? (
            [
              ["skipped", event.skipped_starts, true],
              ["extra", event.extra_starts, false],
            ] as const
          ).map(([kind, starts, restorable]) =>
            starts.length ? (
              <div key={kind} className="space-y-2">
                <Label>{t(`occurrence.${kind}`)}</Label>
                <ul className="space-y-1 text-sm">
                  {starts.map((start) => (
                    <li key={start} className="flex items-center justify-between gap-2">
                      <span>
                        {event.all_day ? formatDate(start.slice(0, 10)) : formatDateTime(start)}
                      </span>
                      {restorable ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => restoreDate.mutate(start)}
                          disabled={restoreDate.isPending}
                        >
                          {t("occurrence.restore")}
                        </Button>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null
          )
        : null}
      {event.recurrence ? (
        <div className="flex flex-wrap items-end gap-2">
          <div className="space-y-2">
            <Label className="sr-only">{t("occurrence.addDate")}</Label>
            <DateTimePicker
              value={extraDate}
              onChange={setExtraDate}
              includeTime={!event.all_day}
            />
          </div>
          <Button
            type="button"
            variant="outline"
            disabled={!extraDate || addDate.isPending}
            onClick={() =>
              addDate.mutate(
                event.all_day
                  ? `${extraDate.slice(0, 10)}T00:00:00Z`
                  : new Date(extraDate).toISOString()
              )
            }
          >
            {t("occurrence.addDate")}
          </Button>
        </div>
      ) : null}
    </FieldFrame>
  );
};

/** Who is coming, each with their answer; who is asked, saved as they are
 *  picked; and whether anyone who can see it may answer. */
// An event being added starts its attendees over in another calendar.
const AttendeesEditor = (props: EditorProps) => (
  <Attendees key={props.item.calendar_id} {...props} />
);

const Attendees = ({ item: event }: EditorProps) => {
  const { t } = useTranslation(["calendars", "common"]);
  const { readOnly } = useEventLayout();
  const label = `${t("attendees")} (${event.attendees.length})`;
  const save = useSave(event, t("attendees"));
  const openSave = useSave(event, t("rsvpOpen"));
  const saved = event.attendees.map((attendee) => attendee.user_id);
  const draft = useFieldDraft(
    saved,
    (ids) => save.save({ patch: { attendee_ids: ids }, shows: {} }),
    sameIds
  );
  const users = useMemo(
    () => event.attendees.flatMap((attendee) => (attendee.user ? [attendee.user] : [])),
    [event.attendees]
  );
  return (
    <FieldFrame label={label} save={save} changed={draft.changed} keys={draft.keys}>
      {readOnly ? null : (
        <MemberMultiSelect
          scope={{ type: "canOpen", tool: Tool.calendar, id: event.calendar_id }}
          selectedIds={draft.value}
          selectedUsers={users}
          onChange={draft.edit}
          placeholder={t("addAttendee")}
          emptyMessage={t("noAttendees")}
        />
      )}
      {event.attendees.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("noAttendees")}</p>
      ) : (
        <ul className="space-y-2">
          {event.attendees.map((attendee) => (
            <li
              key={attendee.user_id}
              className="flex items-center justify-between rounded-md border px-3 py-2"
            >
              <span className="font-medium text-sm">
                {getUserDisplayName(attendee.user ?? { id: attendee.user_id })}
              </span>
              <Badge variant={rsvpBadgeVariant(attendee.rsvp_status)}>
                {t(RSVP_LABEL_KEYS[attendee.rsvp_status] ?? "rsvpPending")}
              </Badge>
            </li>
          ))}
        </ul>
      )}
      {readOnly ? null : (
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <Label htmlFor="event-rsvp-open" className="text-sm">
              {t("rsvpOpen")}
            </Label>
            <p className="text-muted-foreground text-xs">
              {event.series_id != null ? t("occurrence.followsSeries") : t("rsvpOpenHint")}
            </p>
          </div>
          <Switch
            id="event-rsvp-open"
            checked={event.rsvp_open}
            // One date with a row of its own answers as its series is set.
            disabled={event.series_id != null || openSave.state === "saving"}
            onCheckedChange={(next) =>
              void openSave.save({ patch: { rsvp_open: next }, shows: { rsvp_open: next } })
            }
            className="mt-0.5 shrink-0"
          />
        </div>
      )}
    </FieldFrame>
  );
};

/** The reader's own answer, where they are asked. A series' is for the date
 *  shown. */
const MyAnswer = ({ event }: { event: CalendarEventRead }) => {
  const { t } = useTranslation("calendars");
  const { occurrenceStart } = useEventLayout();
  const { user } = useAuth();
  const answer = useUpdateEventRSVP(event.id, {
    onSuccess: () => toast.success(t("rsvpUpdated")),
  });
  const mine = event.attendees.find((attendee) => attendee.user_id === user?.id);
  if (!mine) return null;
  return (
    <section className="space-y-2 rounded-lg border bg-card p-4 text-card-foreground shadow-sm">
      <Label htmlFor="event-rsvp">{t("rsvp")}</Label>
      <Select
        // Pending is no answer yet, so it shows as the placeholder rather
        // than as a choice.
        value={mine.rsvp_status === "pending" ? "" : mine.rsvp_status}
        onValueChange={(status) =>
          answer.mutate({
            rsvp_status: status as RSVPStatus,
            ...(event.recurrence ? { occurrence: occurrenceStart } : {}),
          })
        }
        disabled={answer.isPending}
      >
        <SelectTrigger id="event-rsvp" className="w-[140px]">
          <SelectValue placeholder={t("rsvpPending")} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="accepted">{t("rsvpAccepted")}</SelectItem>
          <SelectItem value="tentative">{t("rsvpTentative")}</SelectItem>
          <SelectItem value="declined">{t("rsvpDeclined")}</SelectItem>
        </SelectContent>
      </Select>
    </section>
  );
};

const TagsEditor = ({ item: event, label }: EditorProps) => {
  const { t } = useTranslation("calendars");
  const { readOnly } = useEventLayout();
  const save = useSave(event, label);
  // A reader sees the tags it has, and none where it has none.
  if (readOnly && event.tags.length === 0) return null;
  return (
    <TagsField
      label={label}
      tags={event.tags}
      save={save}
      readOnly={readOnly}
      placeholder={t("eventPage.tagsPlaceholder")}
    />
  );
};

/** An event's detail: its fields, its own parts and where it lives. */
export const EVENT_DETAIL: DetailKind<CalendarEventRead, EventLayoutContext, EventPatch> = {
  spec: EVENT_LAYOUT,
  fields: eventFields,
  namespaces: ["calendars", "common"],
  editors: {
    title: TitleEditor,
    description: DescriptionEditor,
    location: LocationEditor,
    recurrence: RepeatEditor,
    attendees: AttendeesEditor,
    tags: TagsEditor,
  } satisfies Record<keyof typeof EVENT_FIELDS, ComponentType<EditorProps>>,
  parts: {
    dates: (_node, event) => <DatesEditor event={event} />,
    rsvp: (_node, event) => <MyAnswer event={event} />,
  },
  addingParts: ["dates"],
  filled: filledBy<CalendarEventRead, EventPatch>(
    {
      description: (event, sent) => hasText(sentOr(sent, "description", event.description)),
      location: (event, sent) => hasText(sentOr(sent, "location", event.location)),
      recurrence: (event, sent) => sentOr(sent, "recurrence", event.recurrence) != null,
      attendees: (event, sent) => hasAny(sentOr(sent, "attendee_ids", event.attendees)),
      tags: (event, sent) => hasAny(sentOr(sent, "tag_ids", event.tags)),
    },
    (event) => event.properties
  ),
  home: (event, context) => ({
    saves: eventSaves(context.occurrence),
    readOnly: context.readOnly,
    initiativeId: event.initiative_id,
    canOpen: { tool: Tool.calendar, id: event.calendar_id },
    links: {
      entity: event,
      target: { type: SearchEntityType.calendar_event, id: event.id },
      title: event.title,
    },
    actions: context.actions,
  }),
};

/** An event not yet added to `calendar`, over `range`, as its detail draws it
 *  while it is: `attendee`, who adds it, attends. */
export const blankEvent = (
  calendar: { id: number; initiative_id: number | null } | undefined,
  range: { start_at: string; end_at: string },
  attendee: UserPublic | null
): CalendarEventRead => ({
  id: 0,
  title: "",
  description: null,
  location: null,
  ...range,
  all_day: false,
  rsvp_open: true,
  recurrence: null,
  recurrence_shift: 0,
  original_start: null,
  series_id: null,
  calendar_id: calendar?.id ?? 0,
  initiative_id: calendar?.initiative_id ?? null,
  community_id: 0,
  created_by: null,
  properties: [],
  tags: [],
  can: { edit: true },
  created_at: "",
  updated_at: "",
  attendees: attendee
    ? [{ user_id: attendee.id, user: attendee, rsvp_status: "pending", created_at: "" }]
    : [],
  overridden_fields: [],
  skipped_starts: [],
  extra_starts: [],
});
