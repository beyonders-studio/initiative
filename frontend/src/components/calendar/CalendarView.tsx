import {
  DndContext,
  type DragEndEvent,
  DragOverlay,
  type DragStartEvent,
  pointerWithin,
} from "@dnd-kit/core";
import {
  addDays,
  addMonths,
  addWeeks,
  addYears,
  differenceInCalendarDays,
  format,
  parseISO,
  startOfWeek,
} from "date-fns";
import {
  Calendar,
  CalendarDays,
  CalendarRange,
  ChevronLeft,
  ChevronRight,
  Grid3X3,
  List,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  PropertySummary,
  TagSummary,
  TaskTypeRead,
} from "@/api/generated/initiativeAPI.schemas";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";
import { dateTimeFormat } from "@/ui/lib/intl";
import { parseLocalCalendarDate, resolveLocalDateTime } from "@/ui/lib/localDateTime";
import { useDragSensors } from "@/ui/lib/useDragSensors";
import { cn } from "@/ui/lib/utils";
import { Skeleton } from "@/ui/skeleton";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/ui/tooltip";

import { DayView } from "./views/DayView";
import { ListView } from "./views/ListView";
import { MonthView } from "./views/MonthView";
import { type DropData, dateKey, type WeekStartsOn } from "./views/shared";
import { WeekView } from "./views/WeekView";
import { YearView } from "./views/YearView";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export type CalendarViewMode = "day" | "week" | "month" | "year" | "list";

/** Where an older release kept one month, week, day or list for every
 *  calendar. Each calendar's is now part of a person's view of it, which
 *  reads this once. */
export const CALENDAR_VIEW_MODE_KEY = "calendar:view-mode";

export type CalendarEntryAttendee = {
  name: string;
  /** The picture's URL; needs ``resolveUploadUrl`` to become absolute. */
  avatarUrl?: string | null;
  /** User id for the deterministic avatar tint. Optional because some
   *  entry sources (e.g. event summaries, which carry just attendee
   *  names) don't expose ids yet; those render a neutral fallback. */
  userId?: number | null;
};

/** Presentational marker for task entries: lets the calendar render a
 *  "Start"/"Due" label and a distinct dot so the two are easy to tell apart.
 *  Unset for events and same-day task spans. */
export type CalendarEntryKind = "start" | "due";

export type CalendarEntry = {
  id: number | string;
  title: string;
  description?: string | null;
  startAt: string; // ISO datetime
  endAt: string; // ISO datetime
  allDay?: boolean;
  color?: string | null;
  attendees?: CalendarEntryAttendee[];
  /** Custom property values attached to the underlying entity. Rendered as
   *  compact chips on the list view; other calendar views omit them. */
  properties?: PropertySummary[];
  /** Tags attached to the underlying entity. Rendered as badges on the list view. */
  tags?: TagSummary[];
  /** A task's type, drawn by its icon before the title. */
  taskType?: Pick<TaskTypeRead, "name" | "icon" | "color"> | null;
  /** Presentational start/due marker (see CalendarEntryKind). */
  kind?: CalendarEntryKind;
  /** When false, the entry cannot be dragged to reschedule (default true). */
  draggable?: boolean;
  /** Something about the entry is unread; the entry carries the unread mark. */
  unread?: boolean;
  /** Any extra data the consumer wants to pass through */
  meta?: Record<string, unknown>;
};

/** Payload handed to ``onEntryReschedule`` after a drag drop. CalendarView
 *  computes the resulting absolute ISO start/end (duration preserved, and
 *  time-of-day preserved on date-only moves); the consumer routes it to the
 *  right mutation using ``entry.meta``/``entry.kind``. */
export type CalendarEntryReschedule = {
  entry: CalendarEntry;
  /** New absolute start, ISO. */
  startAt: string;
  /** New absolute end, ISO. Equals ``startAt`` for instant markers. */
  endAt: string;
  /** Which axis changed: a date-only move (month/week) or a time move (day). */
  mode: "day" | "time";
};

type CalendarViewProps = {
  entries: CalendarEntry[];
  /** Current view mode */
  viewMode: CalendarViewMode;
  onViewModeChange: (mode: CalendarViewMode) => void;
  /** The currently focused date (used to determine what month/week/day to show) */
  focusDate: Date;
  onFocusDateChange: (date: Date) => void;
  /** Called when user clicks an entry */
  onEntryClick?: (entry: CalendarEntry) => void;
  /** Called when user clicks an empty day/time slot to create */
  onSlotClick?: (date: Date) => void;
  /** Called when the user drags an entry to a new day (month/week) or hour
   *  (day). When omitted, drag-to-reschedule is disabled entirely. */
  onEntryReschedule?: (change: CalendarEntryReschedule) => void;
  /** Week start day from user preferences */
  weekStartsOn?: WeekStartsOn;
  /** Loading state */
  isLoading?: boolean;
  /** Hide the list view option (e.g. for tasks where list doesn't make sense) */
  hideListView?: boolean;
  /** The page offers the views in its own toolbar, so the calendar does not. */
  hideViewSwitch?: boolean;
  /** Draws its own card. Off where something around it already is one. */
  framed?: boolean;
  /** Multi-select on the list view (opt-in — only the list view uses these, and
   *  only the entries `isEntrySelectable` accepts get a checkbox). */
  selectionActive?: boolean;
  selectedEntryIds?: Set<CalendarEntry["id"]>;
  isEntrySelectable?: (entry: CalendarEntry) => boolean;
  onToggleEntrySelection?: (entry: CalendarEntry) => void;
};

type ViewModeLabel =
  | "calendar.day"
  | "calendar.week"
  | "calendar.month"
  | "calendar.year"
  | "calendar.list";

/** The calendar's views, for a page that offers them in its own toolbar. */
export const CALENDAR_VIEW_OPTIONS: {
  mode: CalendarViewMode;
  icon: typeof Calendar;
  labelKey: ViewModeLabel;
}[] = [
  { mode: "day", icon: Calendar, labelKey: "calendar.day" },
  { mode: "week", icon: CalendarRange, labelKey: "calendar.week" },
  { mode: "month", icon: CalendarDays, labelKey: "calendar.month" },
  { mode: "year", icon: Grid3X3, labelKey: "calendar.year" },
  { mode: "list", icon: List, labelKey: "calendar.list" },
];

// ---------------------------------------------------------------------------
// Calendar Header
// ---------------------------------------------------------------------------

function CalendarHeader({
  viewMode,
  onViewModeChange,
  focusDate,
  onFocusDateChange,
  periodLabel,
  hideListView = false,
  hideViewSwitch = false,
}: {
  viewMode: CalendarViewMode;
  onViewModeChange: (mode: CalendarViewMode) => void;
  focusDate: Date;
  onFocusDateChange: (date: Date) => void;
  periodLabel: string;
  hideListView?: boolean;
  hideViewSwitch?: boolean;
}) {
  const { t } = useTranslation(["common"]);

  const navigate = useCallback(
    (direction: "prev" | "next") => {
      const delta = direction === "prev" ? -1 : 1;
      switch (viewMode) {
        case "day":
          onFocusDateChange(addDays(focusDate, delta));
          break;
        case "week":
          onFocusDateChange(addWeeks(focusDate, delta));
          break;
        case "month":
        case "list":
          onFocusDateChange(addMonths(focusDate, delta));
          break;
        case "year":
          onFocusDateChange(addYears(focusDate, delta));
          break;
      }
    },
    [viewMode, focusDate, onFocusDateChange]
  );

  const goToToday = useCallback(() => {
    onFocusDateChange(new Date());
  }, [onFocusDateChange]);

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b pb-3">
      {/* Left: navigation */}
      <div className="flex items-center gap-2">
        <Button type="button" variant="outline" size="sm" onClick={goToToday}>
          {t("common:calendar.today")}
        </Button>
        <Button type="button" variant="outline" size="icon-sm" onClick={() => navigate("prev")}>
          <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          <span className="sr-only">{t("common:previous")}</span>
        </Button>
        <Button type="button" variant="outline" size="icon-sm" onClick={() => navigate("next")}>
          <ChevronRight className="h-4 w-4" aria-hidden="true" />
          <span className="sr-only">{t("common:next")}</span>
        </Button>
        <p className="font-semibold text-lg capitalize">{periodLabel}</p>
      </div>

      {/* Right: view mode switcher */}
      {hideViewSwitch ? null : (
        <TooltipProvider delayDuration={300}>
          <fieldset
            className="flex items-center gap-0.5 rounded-lg bg-muted p-1"
            aria-label={t("common:calendar.viewMode")}
          >
            {CALENDAR_VIEW_OPTIONS.filter(({ mode }) => !(hideListView && mode === "list")).map(
              ({ mode, icon: Icon, labelKey }) => (
                <Tooltip key={mode}>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      aria-pressed={viewMode === mode}
                      className={cn(
                        "inline-flex items-center justify-center rounded-md px-2 py-1.5 font-medium text-sm transition-colors",
                        "hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                        viewMode === mode
                          ? "bg-background text-foreground shadow-sm"
                          : "text-muted-foreground hover:bg-accent/50"
                      )}
                      onClick={() => onViewModeChange(mode)}
                    >
                      <Icon className="h-4 w-4" aria-hidden="true" />
                      <span className="sr-only">{t(labelKey)}</span>
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="bottom">{t(labelKey)}</TooltipContent>
                </Tooltip>
              )
            )}
          </fieldset>
        </TooltipProvider>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Loading Skeleton
// ---------------------------------------------------------------------------

function CalendarSkeleton() {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Skeleton className="h-8 w-16" />
          <Skeleton className="h-8 w-8" />
          <Skeleton className="h-8 w-8" />
          <Skeleton className="h-6 w-40" />
        </div>
        <Skeleton className="h-8 w-48" />
      </div>
      <div className="grid grid-cols-7 gap-px">
        {Array.from({ length: 35 }).map((_, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: This is a static skeleton layout, not dynamic data
          <Skeleton key={i} className="h-28 rounded-none" />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Period Label
// ---------------------------------------------------------------------------

function usePeriodLabel(
  viewMode: CalendarViewMode,
  focusDate: Date,
  weekStartsOn: WeekStartsOn
): string {
  const { i18n } = useTranslation();

  return useMemo(() => {
    const locale = i18n.language;
    switch (viewMode) {
      case "day":
        return dateTimeFormat(locale, {
          weekday: "long",
          month: "long",
          day: "numeric",
          year: "numeric",
        }).format(focusDate);
      case "week": {
        const weekStart = startOfWeek(focusDate, { weekStartsOn });
        const weekEnd = addDays(weekStart, 6);
        const startStr = dateTimeFormat(locale, { month: "short", day: "numeric" }).format(
          weekStart
        );
        const endStr = dateTimeFormat(locale, {
          month: "short",
          day: "numeric",
          year: "numeric",
        }).format(weekEnd);
        return `${startStr} – ${endStr}`;
      }
      case "month":
      case "list":
        return dateTimeFormat(locale, { month: "long", year: "numeric" }).format(focusDate);
      case "year":
        return focusDate.getFullYear().toString();
    }
  }, [viewMode, focusDate, weekStartsOn, i18n.language]);
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export const CalendarView = ({
  entries,
  viewMode,
  onViewModeChange,
  focusDate,
  onFocusDateChange,
  onEntryClick,
  onSlotClick,
  onEntryReschedule,
  weekStartsOn = 0,
  isLoading = false,
  hideListView = false,
  hideViewSwitch = false,
  framed = true,
  selectionActive = false,
  selectedEntryIds,
  isEntrySelectable,
  onToggleEntrySelection,
}: CalendarViewProps) => {
  const { t } = useTranslation("dates");
  const periodLabel = usePeriodLabel(viewMode, focusDate, weekStartsOn);
  const dndEnabled = !!onEntryReschedule;
  const [activeEntry, setActiveEntry] = useState<CalendarEntry | null>(null);

  // A small move or a long press starts a drag; a plain click still selects
  // the entry, so navigation keeps working.
  const sensors = useDragSensors();

  const handleDragStart = useCallback((event: DragStartEvent) => {
    setActiveEntry((event.active.data.current?.entry as CalendarEntry | undefined) ?? null);
  }, []);

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      setActiveEntry(null);
      const { active, over } = event;
      if (!over) return;
      const entry = active.data.current?.entry as CalendarEntry | undefined;
      const drop = over.data.current as DropData | undefined;
      if (!entry || !drop) return;

      const start = parseISO(entry.startAt);
      if (Number.isNaN(start.getTime())) return;
      const parsedEnd = parseISO(entry.endAt);
      const end = Number.isNaN(parsedEnd.getTime()) ? start : parsedEnd;
      const time =
        drop.type === "day" || entry.allDay
          ? format(start, "HH:mm:ss.SSS")
          : `${String(drop.hour).padStart(2, "0")}:00:00.000`;
      const newStart = entry.allDay
        ? parseLocalCalendarDate(drop.dateKey)
        : resolveLocalDateTime(drop.dateKey, time, entry.startAt);
      if (newStart && entry.allDay) {
        // A calendar day remains valid when its midnight is skipped. Task
        // markers also retain their existing clock where that day has it.
        newStart.setHours(
          start.getHours(),
          start.getMinutes(),
          start.getSeconds(),
          start.getMilliseconds()
        );
      }
      if (!newStart) {
        toast.error(t("picker.invalidLocalDateTime"));
        return;
      }
      if (
        drop.type === "day"
          ? dateKey(newStart) === dateKey(start)
          : newStart.getTime() === start.getTime()
      )
        return;
      // All-day spans count calendar days; elapsed time differs across DST.
      const newEnd = entry.allDay
        ? addDays(end, differenceInCalendarDays(newStart, start))
        : new Date(newStart.getTime() + end.getTime() - start.getTime());
      onEntryReschedule?.({
        entry,
        startAt: newStart.toISOString(),
        endAt: newEnd.toISOString(),
        mode: drop.type === "day" || entry.allDay ? "day" : "time",
      });
    },
    [onEntryReschedule, t]
  );

  if (isLoading) {
    return (
      <div className={cn("space-y-4", framed && "rounded-xl border bg-card p-4 shadow-sm")}>
        <CalendarSkeleton />
      </div>
    );
  }

  const gridProps = { entries, focusDate, onEntryClick, onSlotClick, dndEnabled };
  const views = (
    <>
      {viewMode === "month" ? <MonthView {...gridProps} weekStartsOn={weekStartsOn} /> : null}
      {viewMode === "week" ? <WeekView {...gridProps} weekStartsOn={weekStartsOn} /> : null}
      {viewMode === "day" ? <DayView {...gridProps} /> : null}
      {viewMode === "year" ? (
        <YearView
          entries={entries}
          focusDate={focusDate}
          weekStartsOn={weekStartsOn}
          onFocusDateChange={onFocusDateChange}
          onViewModeChange={onViewModeChange}
        />
      ) : null}
      {viewMode === "list" ? (
        <ListView
          entries={entries}
          focusDate={focusDate}
          onEntryClick={onEntryClick}
          selectionActive={selectionActive}
          selectedEntryIds={selectedEntryIds}
          isEntrySelectable={isEntrySelectable}
          onToggleEntrySelection={onToggleEntrySelection}
        />
      ) : null}
    </>
  );

  return (
    <div className={cn("space-y-4", framed && "rounded-xl border bg-card p-4 shadow-sm")}>
      <CalendarHeader
        viewMode={viewMode}
        onViewModeChange={onViewModeChange}
        focusDate={focusDate}
        onFocusDateChange={onFocusDateChange}
        periodLabel={periodLabel}
        hideListView={hideListView}
        hideViewSwitch={hideViewSwitch}
      />

      {dndEnabled ? (
        <DndContext
          sensors={sensors}
          collisionDetection={pointerWithin}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
          onDragCancel={() => setActiveEntry(null)}
        >
          {views}
          <DragOverlay>
            {activeEntry ? (
              <div
                className="pointer-events-none flex items-center gap-1 rounded px-2 py-1 font-medium text-2xs text-white shadow-lg"
                style={{ backgroundColor: activeEntry.color || "var(--primary)" }}
              >
                <span className="truncate">{activeEntry.title}</span>
              </div>
            ) : null}
          </DragOverlay>
        </DndContext>
      ) : (
        views
      )}
    </div>
  );
};
