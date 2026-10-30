import { useParams, useRouter, useSearch } from "@tanstack/react-router";
import { format } from "date-fns";
import { FileDown, Loader2, Plus, Rss, Upload } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  CalendarSummary,
  ExportEventsParams,
  FilterCondition,
  FilterGroup,
  ListCalendarEntriesParams,
  TaskPriority,
  TaskStatusCategory,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  allDayRange,
  buildEventCalendarEntry,
  buildTaskCalendarEntries,
  buildTaskOccurrenceEntries,
  CALENDAR_VIEW_MODE_KEY,
  CALENDAR_VIEW_OPTIONS,
  type CalendarEntry,
  type CalendarEntryReschedule,
  CalendarView,
  type CalendarViewMode,
  calendarVisibleRange,
  type EventEntryMeta,
  occurrenceTarget,
  rescheduledDates,
  type TaskEntryMeta,
  useCalendarVisibility,
} from "@/components/calendar";
import { ToolCommentsPanel } from "@/components/comments/ToolCommentsPanel";
import { ToolRelationsPanel } from "@/components/entities/ToolRelationsPanel";
import { useToolImportAction } from "@/components/imports/ToolImportAction";
import {
  CalendarPicker,
  type ProjectTaskCalendar,
  ProjectTaskToggles,
} from "@/components/initiativeTools/events/CalendarListPanel";
import { CalendarSubscribeDialog } from "@/components/initiativeTools/events/CalendarSubscribeDialog";
import { CreateCalendarDialog } from "@/components/initiativeTools/events/CreateCalendarDialog";
import {
  CreateEventDialog,
  isWritableCalendar,
} from "@/components/initiativeTools/events/CreateEventDialog";
import { ICalImportDialog } from "@/components/initiativeTools/events/ICalImportDialog";
import { ToolFilterPanel } from "@/components/initiativeTools/shared/ToolFilterPanel";
import { ToolListToolbar } from "@/components/initiativeTools/shared/ToolListToolbar";
import { ToolPresetSelect } from "@/components/initiativeTools/shared/ToolPresetSelect";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import {
  PropertyFilter,
  type PropertyFilterCondition,
} from "@/components/properties/PropertyFilter";
import { useScopePrompt } from "@/components/recurrence/OccurrenceScopeDialog";
import {
  CalendarPageSkeleton,
  CardGridSkeleton,
  SkeletonRegion,
} from "@/components/skeletons/PageSkeletons";
import { ToolAccessStatus } from "@/components/ToolAccessStatus";
import { TaskStatusPriorityFilters } from "@/components/tasks/TaskStatusPriorityFilters";
import { ToolPageHeader } from "@/components/tools/ToolPageHeader";
import { Button } from "@/components/ui/button";
import {
  DateRangeField,
  dateRangeBounds,
  dateRangeParams,
  isDateRangeSet,
  type LocalDateRange,
} from "@/components/ui/date-range-field";
import { DropdownMenuItem } from "@/components/ui/dropdown-menu";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAuth } from "@/hooks/useAuth";
import { useCalendarEntries } from "@/hooks/useCalendarEntries";
import { useUpdateCalendarEvent } from "@/hooks/useCalendarEvents";
import { useCalendar, useCalendarsList } from "@/hooks/useCalendars";
import { useCanonicalInitiativeId } from "@/hooks/useCanonicalInitiativeId";
import { useCommunities } from "@/hooks/useCommunities";
import { useCreateFromSearchParam } from "@/hooks/useCreateFromSearchParam";
import { useHeldSurfaces } from "@/hooks/useCustomRoles";
import { useExportJob } from "@/hooks/useExportJob";
import { useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { useInitiative } from "@/hooks/useInitiatives";
import {
  deviceJSON,
  LIST,
  type ListViewSpec,
  NO_PART_VIEW,
  useListView,
  usePresetLink,
  viewKey,
} from "@/hooks/useListView";
import { useReadOnOpen } from "@/hooks/useNotifications";
import { useRecordOpen } from "@/hooks/usePersonalItems";
import { useUpdateTask } from "@/hooks/useTasks";
import { listLayouts, sharedTarget, useToolLayouts } from "@/hooks/useToolLayouts";
import { useUnreadTree } from "@/hooks/useUnreadTree";
import { useCommunityPath } from "@/lib/communityUrl";
import { getErrorMessage } from "@/lib/errorMessage";
import {
  type CalendarFilters,
  type CalendarViewFilters,
  type CalendarVisibility,
  calendarViewFiltersFromStored,
  carriedCalendarView,
  EMPTY_CALENDAR_VIEW_FILTERS,
} from "@/lib/filters/calendarFilters";
import { CALENDAR_PRESETS, type Preset, presetName, presetsOf } from "@/lib/layouts/presets";
import { getProjectColor } from "@/lib/projectColor";
import { browserTimezone } from "@/lib/timezones";
import { eventRoute, taskRoute, toolListRoute, toolSettingsRoute } from "@/lib/tools";

/** Where a calendar page keeps one person's view: the initiative's calendar,
 *  one community calendar, or the community's calendars together. What an
 *  older release kept (the filters every calendar shared, what was switched
 *  off in the community, and the month or week every calendar shared) is
 *  carried over. */
const calendarsViewSpec = (
  communityId: number,
  ...names: (string | number)[]
): ListViewSpec<CalendarViewFilters> => ({
  key: viewKey(communityId, ...names),
  read: calendarViewFiltersFromStored,
  defaults: CALENDAR_VIEW_DEFAULTS,
  carryOver: (items) => {
    const carried = carriedCalendarView({
      prefs: deviceJSON("initiative-calendars-prefs"),
      visibility: deviceJSON(`initiative-calendar-visibility:${communityId}`),
      mode: items[CALENDAR_VIEW_MODE_KEY],
    });
    return carried && { mode: carried.mode, parts: { [LIST]: { filters: carried.filters } } };
  },
});

const CALENDAR_VIEW_DEFAULTS = { filters: EMPTY_CALENDAR_VIEW_FILTERS, ...NO_PART_VIEW };

type CalendarsViewProps = {
  fixedInitiativeId?: number;
  canCreate?: boolean;
  /** Focus a single calendar (the /calendars/$calendarId route): it is forced
   * visible so the deep link always shows its events. */
  focusCalendarId?: number;
  /** A community calendar rendered as its own whole surface — a deep link to one
   * of them. Community plug-ins show community-level content only, so this mode shows
   * exactly this calendar's events: no tasks, no projects, no other calendars,
   * no initiative-flavored filters. */
  soloCalendar?: CalendarSummary;
  /** The calendar plug-in's own surface: every community calendar this reader may see,
   * overlaid. Community-level content only, like {@link soloCalendar} — but the
   * plug-in holds many calendars, so this one keeps the calendar list panel and
   * the create seam. */
  communityScope?: boolean;
};

export const CalendarsView = ({
  fixedInitiativeId,
  canCreate,
  focusCalendarId,
  soloCalendar,
  communityScope = false,
}: CalendarsViewProps) => {
  const { t } = useTranslation(["calendars", "tasks", "common", "access", "exports", "projects"]);
  const router = useRouter();
  const { user } = useAuth();
  const gp = useCommunityPath();
  const communityId = useActiveCommunityId();
  const searchParams = useSearch({ strict: false }) as {
    create?: string;
    preset?: string;
  };
  // The focus route addresses its calendar inside an initiative, so the path
  // is the fallback when this view isn't mounted as an initiative tab.
  const { initiativeId: initiativeIdParam } = useParams({ strict: false }) as {
    initiativeId?: string;
  };

  const weekStartsOn = (user?.week_starts_on ?? 0) as 0 | 1 | 2 | 3 | 4 | 5 | 6;

  const solo = soloCalendar != null;
  // Both community surfaces show community-level content only. What separates them is
  // how many calendars are in view, not what kind of thing is.
  const communityOnly = solo || communityScope;
  // Set only by the initiative page's tool tabs — the deep-link surfaces
  // resolve their initiative from the URL instead.
  const isInitiativeTab = fixedInitiativeId != null;

  // Resolve initiative from prop or URL param. A community calendar belongs to no
  // initiative, so none applies.
  const initiativeId = communityOnly
    ? null
    : (fixedInitiativeId ?? (initiativeIdParam ? Number(initiativeIdParam) : null));
  // Nothing is exported from an initiative that keeps its content in.
  const keepsContentIn = Boolean(useInitiative(initiativeId).data?.keep_content_in);

  const searchParamsRef = useRef(searchParams);
  searchParamsRef.current = searchParams;

  // This person's view of the calendar: its mode (month, week, …), its
  // filters, and what is switched off, kept for them on this calendar page.
  const viewSpec = useMemo(
    () =>
      solo
        ? calendarsViewSpec(communityId, "calendar", soloCalendar.id)
        : communityScope || initiativeId == null
          ? calendarsViewSpec(communityId, "calendars")
          : calendarsViewSpec(communityId, "initiative", initiativeId, "calendar"),
    [solo, soloCalendar?.id, communityScope, communityId, initiativeId]
  );
  const view = useListView(viewSpec);
  const viewMode = (view.mode ?? "month") as CalendarViewMode;
  const { setMode: setViewMode, setFilters } = view;
  const [focusDate, setFocusDate] = useState(() => new Date());

  const {
    status_categories: statusFilters,
    priorities: priorityFilters,
    properties: propertyFilters,
  } = view.filters;
  const setStatusFilters = useCallback(
    (status_categories: TaskStatusCategory[]) =>
      setFilters((prev) => ({ ...prev, status_categories })),
    [setFilters]
  );
  const setPriorityFilters = useCallback(
    (priorities: TaskPriority[]) => setFilters((prev) => ({ ...prev, priorities })),
    [setFilters]
  );
  const setPropertyFilters = useCallback(
    (properties: PropertyFilterCondition[]) => setFilters((prev) => ({ ...prev, properties })),
    [setFilters]
  );
  // Which days to show and export. Kept for this visit only, like a search:
  // a saved range would leave the grid empty on a later month with no
  // obvious cause.
  const [dateRange, setDateRange] = useState<LocalDateRange>({});
  // Closed until asked for. The filter button carries a count of what's set, so
  // a narrowed list still says so with the panel shut — and the fields no
  // longer take the top of the page before the list itself.
  const [filtersOpen, setFiltersOpen] = useState(false);

  // Per-calendar / per-project visibility, part of their filters.
  const visibility = useCalendarVisibility(
    view.filters,
    useCallback(
      (next: (prev: CalendarVisibility) => CalendarVisibility) =>
        setFilters((prev) => ({ ...prev, ...next(prev) })),
      [setFilters]
    )
  );
  const { showCalendar, tasksHidden } = visibility;

  // A deep-linked calendar is always shown, whatever the stored toggles say,
  // once they are in.
  useEffect(() => {
    if (view.loaded && focusCalendarId !== undefined) showCalendar(communityId, focusCalendarId);
  }, [view.loaded, focusCalendarId, communityId, showCalendar]);

  // The initiative calendar's layout, and the presets its list offers. The
  // community surfaces belong to no initiative, so they have none.
  const layoutsQuery = useToolLayouts(
    initiativeId != null && !communityOnly ? sharedTarget(Tool.calendar, initiativeId) : null
  );
  const presets = useMemo(
    () => presetsOf(listLayouts(layoutsQuery.data)[0]?.definition, CALENDAR_PRESETS),
    [layoutsQuery.data]
  );
  const { preset, pick: namePreset } = usePresetLink<CalendarFilters>({
    slug: searchParams.preset,
    presets,
    ready: layoutsQuery.data !== undefined && view.loaded,
    scope: `${initiativeId}`,
    apply: useCallback(
      ({ filters }: Preset<CalendarFilters>) => setFilters((prev) => ({ ...prev, ...filters })),
      [setFilters]
    ),
    same: useCallback(
      ({ filters }: Preset<CalendarFilters>) =>
        JSON.stringify(filters) ===
        JSON.stringify({
          status_categories: statusFilters,
          priorities: priorityFilters,
          properties: propertyFilters,
        }),
      [statusFilters, priorityFilters, propertyFilters]
    ),
  });

  // The span the current view renders — the window events + tasks fetch over.
  const visibleRange = useMemo(
    () => calendarVisibleRange(focusDate, viewMode, weekStartsOn),
    [focusDate, viewMode, weekStartsOn]
  );

  // What the grid fetches: the span it renders, narrowed to the date range.
  // Null when the two don't overlap — there is nothing to fetch, the grid is
  // empty, and the lit filter badge says why.
  const entriesWindow = useMemo(() => {
    const { start: from, end: until } = dateRangeBounds(dateRange);
    const start = from && from > visibleRange.start ? from : visibleRange.start;
    const end = until && until < visibleRange.end ? until : visibleRange.end;
    return start < end ? { start, end } : null;
  }, [dateRange, visibleRange]);

  // Serialize property filters into the query-param shape the backend
  // expects. Empty list drops the param entirely so the URL stays clean.
  const propertyFiltersParam = useMemo(() => {
    if (propertyFilters.length === 0) return undefined;
    return JSON.stringify(propertyFilters);
  }, [propertyFilters]);

  const userTimezone = useMemo(browserTimezone, []);

  // Task filter conditions (same JSON shape GET /tasks accepts). The date
  // window travels as start_after/start_before on the request (see
  // entriesParams) — the endpoint bounds the task leg by those.
  const taskConditions = useMemo((): (FilterCondition | FilterGroup)[] => {
    const conditions: (FilterCondition | FilterGroup)[] = [];

    // Only add filters if explicitly selected by user
    if (statusFilters.length > 0) {
      conditions.push({ field: "status_category", op: "in_", value: statusFilters });
    }
    if (priorityFilters.length > 0) {
      conditions.push({ field: "priority", op: "in_", value: priorityFilters });
    }
    // Translate the shared PropertyFilter conditions into the tasks endpoint's
    // ``property_values`` virtual-field shape so the same filter row narrows
    // both events and tasks on the calendar. PropertyFilterCondition.op is
    // typed as string (runtime value matches FilterOp); cast here rather
    // than re-enumerate.
    for (const cond of propertyFilters) {
      conditions.push({
        field: "property_values",
        op: cond.op as FilterCondition["op"],
        value: { property_id: cond.property_id, value: cond.value },
      });
    }
    return conditions;
  }, [statusFilters, priorityFilters, propertyFilters]);

  // The real calendars backing the list panel, colors, and the create seams.
  // Asked for before the entries, because on a community surface they are what
  // names the entries to fetch.
  const calendarsQuery = useCalendarsList(
    communityScope
      ? { page_size: 200, scope: "community" }
      : { page_size: 200, ...(initiativeId ? { initiative_id: initiativeId } : {}) },
    { enabled: !solo }
  );
  const calendars = useMemo(
    () => (solo ? [soloCalendar] : (calendarsQuery.data?.items ?? [])),
    [solo, soloCalendar, calendarsQuery.data]
  );
  const calendarsById = useMemo(() => {
    const map = new Map<number, (typeof calendars)[number]>();
    for (const calendar of calendars) map.set(calendar.id, calendar);
    return map;
  }, [calendars]);

  // --- One request: events + task markers over the visible window. ---
  const entriesParams = useMemo((): ListCalendarEntriesParams => {
    const span = entriesWindow ?? visibleRange;
    // A community surface: community-level events, and nothing task- or
    // initiative-shaped at all. The plug-in asks by scope rather than by naming its
    // calendars — the calendars below arrive one page at a time, and an event
    // on one that fell off the end would simply not be drawn.
    if (communityOnly) {
      return {
        ...(solo ? { calendar_ids: [soloCalendar.id] } : { scope: "community" as const }),
        start_after: span.start.toISOString(),
        start_before: span.end.toISOString(),
        tz: userTimezone,
        include_events: true,
        include_tasks: false,
      };
    }
    return {
      ...(initiativeId ? { initiative_id: initiativeId } : {}),
      start_after: span.start.toISOString(),
      start_before: span.end.toISOString(),
      ...(propertyFiltersParam ? { property_filters: propertyFiltersParam } : {}),
      conditions: taskConditions,
      tz: userTimezone,
      include_events: true,
      // Tasks switched off in the filters are not asked for at all.
      include_tasks: !tasksHidden,
    };
  }, [
    communityOnly,
    solo,
    soloCalendar?.id,
    initiativeId,
    entriesWindow,
    visibleRange,
    propertyFiltersParam,
    taskConditions,
    tasksHidden,
    userTimezone,
  ]);

  const entriesQuery = useCalendarEntries(entriesParams, { enabled: entriesWindow != null });
  // Kept-previous data belongs to a window the grid no longer shows.
  const entriesData = entriesWindow ? entriesQuery.data : undefined;

  // Export the calendars on screen, through the same scope and filters as the
  // grid: the date range when one is set, and every date when not. Hidden
  // calendars are left out by their saved ids, so one past the loaded page of
  // calendars stays out too.
  const eventsExport = useExportJob({ resumePending: true });
  const exportParams = useMemo((): ExportEventsParams | null => {
    if (keepsContentIn) {
      return null;
    }
    const allHidden = calendars.every((calendar) =>
      visibility.isCalendarHidden(communityId, calendar.id)
    );
    if (!solo && allHidden && !calendarsQuery.data?.has_next) {
      return null;
    }
    const hidden = visibility.hiddenCalendarIds(communityId);
    return {
      ...(solo
        ? { calendar_ids: [soloCalendar.id] }
        : communityScope
          ? { scope: "community" as const }
          : initiativeId
            ? { initiative_id: initiativeId }
            : {}),
      ...(!solo && hidden.length > 0 ? { exclude_calendar_ids: hidden } : {}),
      ...(!communityOnly && propertyFiltersParam ? { property_filters: propertyFiltersParam } : {}),
      ...dateRangeParams(dateRange),
    };
  }, [
    calendars,
    calendarsQuery.data?.has_next,
    visibility,
    communityId,
    solo,
    soloCalendar?.id,
    communityScope,
    communityOnly,
    initiativeId,
    keepsContentIn,
    propertyFiltersParam,
    dateRange,
  ]);

  // One read-only virtual calendar per project with a task in the window —
  // fully derived from the entries payload, never stored.
  const projectCalendars = useMemo<ProjectTaskCalendar[]>(() => {
    const seen = new Map<number, ProjectTaskCalendar>();
    const data = entriesData;
    for (const task of [...(data?.tasks ?? []), ...(data?.task_occurrences ?? [])]) {
      if (task.project_id == null || seen.has(task.project_id)) continue;
      seen.set(task.project_id, {
        projectId: task.project_id,
        communityId: task.community_id ?? communityId,
        name: task.project_name ?? `#${task.project_id}`,
        color: getProjectColor(task.project_id),
      });
    }
    return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [entriesData, communityId]);

  // Creating a CALENDAR is the role-permission gate; creating an EVENT is
  // write access on at least one calendar (the project→task pattern). An
  // explicit canCreate prop (e.g. from InitiativeDetailPage) wins.
  const { activeCommunity } = useCommunities();
  const { canCreate: canCreateCalendarsDerived } = useToolCreateAccess(Tool.calendar, {
    initiativeId,
    enabled: !communityOnly,
  });
  // At community scope there is no initiative role to consult: the community's
  // calendars are added by whoever holds them. The solo deep link is one
  // calendar's surface, so it offers no list to add to.
  const holdsCommunityCalendars = useHeldSurfaces().holds("community_calendars");
  const canCreateCalendars = communityScope
    ? holdsCommunityCalendars
    : solo
      ? false
      : (canCreate ?? canCreateCalendarsDerived);
  const writableCalendars = useMemo(() => calendars.filter(isWritableCalendar), [calendars]);
  const canCreateEvents = writableCalendars.length > 0;

  // --- Merge events + tasks into calendar entries (visibility-filtered) ---
  const unread = useUnreadTree();
  const calendarEntries = useMemo<CalendarEntry[]>(() => {
    const entries: CalendarEntry[] = [];

    for (const event of entriesData?.events ?? []) {
      if (visibility.isCalendarHidden(communityId, event.calendar_id)) continue;
      entries.push(
        buildEventCalendarEntry(
          event,
          calendarsById.get(event.calendar_id)?.color,
          unread.hasSubject(event.community_id, "calendar_event", event.id)
        )
      );
    }

    for (const task of tasksHidden ? [] : (entriesData?.tasks ?? [])) {
      if (task.project_id != null && visibility.isProjectHidden(communityId, task.project_id)) {
        continue;
      }
      // Task chips stay non-draggable here: per-project edit rights vary
      // across the visible projects; the task page is the editing surface.
      entries.push(...buildTaskCalendarEntries(task, getProjectColor(task.project_id), false));
    }
    for (const task of tasksHidden ? [] : (entriesData?.task_occurrences ?? [])) {
      if (task.project_id != null && visibility.isProjectHidden(communityId, task.project_id)) {
        continue;
      }
      entries.push(...buildTaskOccurrenceEntries(task, getProjectColor(task.project_id)));
    }

    return entries;
  }, [entriesData, tasksHidden, visibility, communityId, calendarsById, unread]);

  // Create dialog state
  const {
    open: createDialogOpen,
    setOpen: setCreateDialogOpen,
    onOpenChange: handleCreateDialogOpenChange,
  } = useCreateFromSearchParam({
    onClose: () => setCreateDefaultDate(null),
  });
  const [createCalendarOpen, setCreateCalendarOpen] = useState(false);
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const [subscribeOpen, setSubscribeOpen] = useState(false);
  // What can be subscribed to, a link per calendar: the calendars this page
  // lists, an initiative's or the community's own. Not while the initiative
  // keeps its content in, nor where the community does not take this member's
  // API keys.
  const subscribeCalendars = communityOnly || initiativeId ? calendars : [];
  const subscribable =
    subscribeCalendars.length > 0 && !keepsContentIn && Boolean(activeCommunity?.can.use_api);
  const [createDefaultDate, setCreateDefaultDate] = useState<Date | null>(null);

  // Drive the app-wide bottom-nav add button for this route. Creating an
  // event needs a writable calendar; with none, offer calendar creation.
  useRegisterPrimaryCreateAction(
    canCreateEvents
      ? {
          run: () => {
            setCreateDefaultDate(null);
            setCreateDialogOpen(true);
          },
          label: t("createEvent"),
        }
      : canCreateCalendars
        ? {
            run: () => setCreateCalendarOpen(true),
            label: t("createCalendar"),
          }
        : null
  );

  const calendarImport = useToolImportAction({
    tool: Tool.calendar,
    canImport: !communityOnly && canCreateCalendars,
    fixedInitiativeId,
  });

  // Hidden tasks count too: the reader has narrowed what the grid shows, and
  // nothing else on screen says so once the panel is closed. Hidden calendars
  // don't — the title says which calendars are showing.
  const activeFilterCount =
    visibility.hiddenTaskCount +
    statusFilters.length +
    priorityFilters.length +
    propertyFilters.length +
    (isDateRangeSet(dateRange) ? 1 : 0);

  const clearFilters = () => {
    visibility.showTasks();
    setStatusFilters([]);
    setPriorityFilters([]);
    setPropertyFilters([]);
    setDateRange({});
  };

  const handleEventCreated = (event: { id: number; calendar_id: number }) => {
    void router.navigate({
      to: gp(eventRoute(initiativeId, event.calendar_id, event.id)),
    });
  };

  const handleSlotClick = (date: Date) => {
    if (!canCreateEvents) return;
    setCreateDefaultDate(date);
    setCreateDialogOpen(true);
  };

  const handleEntryClick = (entry: CalendarEntry) => {
    const meta = entry.meta as TaskEntryMeta | EventEntryMeta | undefined;
    if (meta?.type === "event") {
      void router.navigate({
        to: gp(eventRoute(initiativeId, meta.calendarId, meta.eventId)),
        search: meta.occurrence ? { occurrence: meta.occurrence } : {},
      });
    } else if (meta?.type === "task") {
      void router.navigate({ to: gp(taskRoute(initiativeId, meta.projectId, meta.taskId)) });
    }
  };

  // Drag-to-reschedule for events (the backend enforces calendar write).
  const updateTask = useUpdateTask();
  const rescheduleEvent = useUpdateCalendarEvent();
  const scopePrompt = useScopePrompt();

  const handleEntryReschedule = useCallback(
    async ({ entry, startAt, endAt }: CalendarEntryReschedule) => {
      const meta = entry.meta as TaskEntryMeta | EventEntryMeta | undefined;
      if (meta?.type === "event") {
        // An occurrence of a repeating event moves alone, from here on, or
        // with every other one, as the person picks.
        const { occurrence } = meta;
        const scope = occurrence ? await scopePrompt.ask("edit") : undefined;
        if (scope === null) return;
        rescheduleEvent.mutate({
          eventId: meta.eventId,
          data: {
            ...(entry.allDay ? allDayRange(startAt, endAt) : { start_at: startAt, end_at: endAt }),
            ...(scope && occurrence
              ? occurrenceTarget({ series_id: meta.seriesId }, scope, occurrence)
              : {}),
          },
        });
        return;
      }
      if (meta?.type === "task") {
        // Dates are each task's own, so moving one asks only whether the
        // tasks after it move too.
        const scope = meta.repeating
          ? await scopePrompt.ask("edit", { tool: "tasks", scopes: ["this", "following"] })
          : undefined;
        if (scope === null) return;
        updateTask.mutate({
          taskId: meta.taskId,
          data: { ...rescheduledDates(meta.kind, startAt, endAt), ...(scope ? { scope } : {}) },
        });
      }
    },
    [updateTask, rescheduleEvent, scopePrompt.ask]
  );

  const defaultStartDate = createDefaultDate ? format(createDefaultDate, "yyyy-MM-dd") : undefined;

  // Which calendars are drawn. The picker is the page's title: it names what
  // is showing and opens the checklist that changes it.
  const shownCalendars = solo
    ? [soloCalendar]
    : calendars.filter((calendar) => !visibility.isCalendarHidden(communityId, calendar.id));
  const onlyCalendar = shownCalendars.length === 1 ? shownCalendars[0] : null;
  const settingsPathFor = (calendar: CalendarSummary) =>
    gp(toolSettingsRoute(Tool.calendar, calendar.initiative_id, calendar.id));
  const calendarPicker = (
    <CalendarPicker
      calendars={calendars}
      isCalendarHidden={(calendar) => visibility.isCalendarHidden(communityId, calendar.id)}
      onToggleCalendar={(calendar) => visibility.toggleCalendar(communityId, calendar.id)}
      onShowAll={() => visibility.showAllCalendars(communityId)}
      settingsPathFor={settingsPathFor}
      canCreate={canCreateCalendars}
      onCreate={() => setCreateCalendarOpen(true)}
    />
  );

  const isLoading =
    (entriesQuery.isLoading && !entriesQuery.data) ||
    (calendarsQuery.isLoading && !calendarsQuery.data);

  return (
    <div className="space-y-6">
      {/* A tab sits under the initiative's own heading, which already says
          where you are; the standalone surfaces head themselves. */}
      {isInitiativeTab ? null : (
        <ToolPageHeader
          tool={Tool.calendar}
          initiativeId={initiativeId}
          // The calendar in view, when there is one: its mark, its star and
          // its settings.
          starId={onlyCalendar?.id}
          mark={
            onlyCalendar ? (
              <span
                aria-hidden
                className="h-4 w-4 shrink-0 rounded-full"
                style={{ backgroundColor: onlyCalendar.color }}
              />
            ) : null
          }
          settingsTo={
            onlyCalendar?.can.edit
              ? toolSettingsRoute(Tool.calendar, onlyCalendar.initiative_id, onlyCalendar.id)
              : undefined
          }
          // The solo deep link is one calendar's surface: nothing to pick.
          title={solo ? soloCalendar.name : calendarPicker}
        />
      )}

      <ToolListToolbar
        // As a tab, the picker heads the row instead, at a title's size.
        heading={
          isInitiativeTab ? (
            <h2 className="font-semibold text-xl tracking-tight">{calendarPicker}</h2>
          ) : undefined
        }
        filters={
          /* Every filter is task- or initiative-shaped, and neither community
             surface holds tasks or an initiative. */
          communityOnly
            ? undefined
            : { open: filtersOpen, onOpenChange: setFiltersOpen, activeCount: activeFilterCount }
        }
        view={{
          value: viewMode,
          onChange: setViewMode,
          options: CALENDAR_VIEW_OPTIONS.map(({ mode, icon, labelKey }) => ({
            value: mode,
            label: t(`common:${labelKey}`),
            icon,
          })),
          label: t("common:calendar.viewMode"),
        }}
        actions={
          communityScope && canCreateCalendars ? (
            <Button size="sm" className="h-9" onClick={() => setCreateCalendarOpen(true)}>
              <Plus className="h-4 w-4" />
              {t("createCalendar")}
            </Button>
          ) : null
        }
        menuItems={
          <>
            {/* One format, so one entry: the job reports itself in a toast. */}
            {exportParams ? (
              <DropdownMenuItem
                disabled={eventsExport.busy}
                onSelect={() =>
                  void eventsExport.start({
                    endpoint: "/exports/events",
                    params: { ...exportParams, format: "ics" },
                    fallbackFilename: "events.ics",
                  })
                }
              >
                {eventsExport.busy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <FileDown className="h-4 w-4" />
                )}
                {eventsExport.busy
                  ? t("exports:export.preparing")
                  : `${t("exports:export.button")} · ${t("exports:export.formatIcs")}`}
              </DropdownMenuItem>
            ) : null}
            {subscribable ? (
              <DropdownMenuItem onSelect={() => setSubscribeOpen(true)}>
                <Rss className="h-4 w-4" />
                {t("subscribe.menu")}
              </DropdownMenuItem>
            ) : null}
            {canCreateEvents ? (
              <DropdownMenuItem onSelect={() => setImportDialogOpen(true)}>
                <Upload className="h-4 w-4" />
                {t("import.importIcs")}
              </DropdownMenuItem>
            ) : null}
            {calendarImport.menuItem}
          </>
        }
      />
      {calendarImport.dialog}

      {/* Filters — task- and initiative-shaped, every one of them. Neither
          community surface holds tasks or an initiative, so they are absent there
          rather than empty. Which calendars are showing is the title's. */}
      {!communityOnly && (
        <ToolFilterPanel
          open={filtersOpen}
          onOpenChange={setFiltersOpen}
          onClear={clearFilters}
          activeCount={activeFilterCount}
          // The presets the calendar's layout offers, once it offers any.
          leading={
            presets.length > 0 ? (
              <ToolPresetSelect
                presets={presets.map((each) => ({
                  slug: each.slug,
                  name: presetName(each, t as never),
                }))}
                activeSlug={preset?.slug ?? null}
                onSelect={namePreset}
                label={t("projects:presets.label")}
                placeholder={t("projects:presets.placeholder")}
              />
            ) : undefined
          }
        >
          <div className="flex flex-wrap items-end gap-4">
            {/* Tasks on the grid: all of them, and each project's. */}
            <div className="w-full space-y-2">
              <div className="flex items-center gap-2">
                <Switch
                  id="calendar-show-tasks"
                  checked={!tasksHidden}
                  onCheckedChange={visibility.toggleTasks}
                />
                <Label htmlFor="calendar-show-tasks" className="cursor-pointer font-medium text-sm">
                  {t("filters.tasks")}
                </Label>
              </div>
              {!tasksHidden && projectCalendars.length > 0 ? (
                <fieldset className="space-y-1">
                  <legend className="mb-1 font-medium text-muted-foreground text-xs">
                    {t("panel.projectTasks")}
                  </legend>
                  <ProjectTaskToggles
                    projects={projectCalendars}
                    isProjectHidden={(project) =>
                      visibility.isProjectHidden(communityId, project.projectId)
                    }
                    onToggleProject={(project) =>
                      visibility.toggleProject(communityId, project.projectId)
                    }
                    className="flex flex-wrap gap-x-4 gap-y-1"
                  />
                </fieldset>
              ) : null}
            </div>

            <div className="w-full sm:w-64">
              <Label
                htmlFor="calendar-date-range"
                className="mb-2 block font-medium text-muted-foreground text-xs"
              >
                {t("filters.dates")}
              </Label>
              <DateRangeField id="calendar-date-range" value={dateRange} onChange={setDateRange} />
            </div>

            <TaskStatusPriorityFilters
              statusFilters={statusFilters}
              onStatusChange={setStatusFilters}
              priorityFilters={priorityFilters}
              onPriorityChange={setPriorityFilters}
            />

            {/* Custom property filters — applied to both events and tasks
                rendered on the calendar. Scoped to the active initiative
                when one is selected, union across accessible initiatives
                otherwise. Nested inside the same bordered filter container
                so it lines up with the other controls. */}
            <div className="w-full">
              <PropertyFilter
                value={propertyFilters}
                onChange={setPropertyFilters}
                {...(initiativeId != null ? { initiativeId } : {})}
              />
            </div>
          </div>
        </ToolFilterPanel>
      )}

      {entriesQuery.isError ? (
        <p className="text-destructive text-sm" role="alert">
          {getErrorMessage(entriesQuery.error, "calendars:loadError")}
        </p>
      ) : null}

      {isLoading ? (
        <SkeletonRegion label={t("loading")}>
          <CardGridSkeleton />
        </SkeletonRegion>
      ) : communityScope && calendars.length === 0 ? (
        /* An empty grid would read as "nothing is happening" rather than
           "there is nothing to happen in yet". */
        <div className="rounded-lg border border-dashed p-8 text-center">
          <p className="font-medium">{t("communityScope.empty")}</p>
          <p className="mt-1 text-muted-foreground text-sm">{t("communityScope.emptyHint")}</p>
          {canCreateCalendars ? (
            <Button className="mt-4" onClick={() => setCreateCalendarOpen(true)}>
              {t("createCalendar")}
            </Button>
          ) : null}
        </div>
      ) : (
        <CalendarView
          entries={calendarEntries}
          viewMode={viewMode}
          onViewModeChange={setViewMode}
          // Offered in the toolbar, where other tools keep their views.
          hideViewSwitch
          focusDate={focusDate}
          onFocusDateChange={setFocusDate}
          onEntryClick={handleEntryClick}
          onSlotClick={canCreateEvents ? handleSlotClick : undefined}
          onEntryReschedule={(change) => void handleEntryReschedule(change)}
          weekStartsOn={weekStartsOn}
        />
      )}

      {scopePrompt.dialog}

      <CreateEventDialog
        open={createDialogOpen}
        onOpenChange={handleCreateDialogOpenChange}
        {...(solo ? { calendarId: soloCalendar.id } : {})}
        defaultCalendarId={focusCalendarId}
        {...(fixedInitiativeId !== undefined ? { initiativeId: fixedInitiativeId } : {})}
        defaultStartDate={defaultStartDate}
        defaultStartTime={createDefaultDate ? format(createDefaultDate, "HH:mm") : undefined}
        onSuccess={handleEventCreated}
      />

      <CreateCalendarDialog
        open={createCalendarOpen}
        onOpenChange={setCreateCalendarOpen}
        communityScope={communityScope}
        initiativeId={fixedInitiativeId}
        defaultInitiativeId={initiativeId ?? undefined}
      />

      <ICalImportDialog open={importDialogOpen} onOpenChange={setImportDialogOpen} />
      {subscribable ? (
        <CalendarSubscribeDialog
          open={subscribeOpen}
          onOpenChange={setSubscribeOpen}
          communityId={communityId}
          calendars={subscribeCalendars}
        />
      ) : null}
    </div>
  );
};

/**
 * The /calendars route — the calendar plug-in's own surface.
 *
 * Every community calendar this reader may see, overlaid in one view: the community's
 * own events and nothing else. Which calendars are showing is the reader's to
 * narrow, and any member may add one.
 */
export function CommunityCalendarsPage() {
  return <CalendarsView communityScope />;
}

/** The /calendars/$calendarId deep link (recents tabs, command palette):
 * the same calendar page with that calendar forced visible, recorded as a
 * recent open. */
export function CalendarFocusPage() {
  const { calendarId: calendarIdParam } = useParams({ strict: false });
  const calendarId = Number(calendarIdParam);
  const calendarQuery = useCalendar(Number.isFinite(calendarId) ? calendarId : null);
  const calendar = calendarQuery.data;
  const { t } = useTranslation("calendars");
  const gp = useCommunityPath();
  const initiativeId = useCanonicalInitiativeId(calendar?.initiative_id);

  // Track recently viewed calendars for the layout header tabs bar — only
  // once the read succeeds (access checks passed).
  const viewedCalendarId = calendar?.id;
  useReadOnOpen(Tool.calendar, viewedCalendarId);
  useRecordOpen(Tool.calendar, viewedCalendarId);

  // Which kind of calendar decides which surface renders, so nothing renders
  // until the read resolves: a community calendar (the plug-in) must never flash the
  // community-wide view, whose fetches reach into initiative content.
  if (calendarQuery.isLoading) {
    return <CalendarPageSkeleton />;
  }
  if (calendarQuery.isError || !calendar) {
    return (
      <ToolAccessStatus
        error={calendarQuery.error}
        keys="calendars:"
        backTo={gp(toolListRoute(Tool.calendar, initiativeId))}
        backLabel={t("backToEvents")}
        entity={{ kind: "calendar", id: calendarId }}
      />
    );
  }

  const isCommunityCalendar = calendar.initiative_id == null;
  return (
    <div className="space-y-6">
      <CalendarsView
        focusCalendarId={calendar.id}
        soloCalendar={isCommunityCalendar ? calendar : undefined}
      />
      {/* A community calendar belongs to no initiative, and a link is only ever
          made inside one — the panel takes itself out of the way there. */}
      <ToolRelationsPanel
        tool={Tool.calendar}
        entity={calendar}
        canEdit={calendar.can.edit}
        entityTitle={calendar.name}
      />

      <ToolCommentsPanel tool={Tool.calendar} entity={calendar} />
    </div>
  );
}
