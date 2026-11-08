import { useNavigate } from "@tanstack/react-router";
import { type ReactNode, useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type FilterCondition,
  type FilterGroup,
  type ListMyCalendarEntriesParams,
  type TaskPriority,
  type TaskStatusCategory,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import {
  buildEventCalendarEntry,
  buildTaskCalendarEntries,
  buildTaskOccurrenceEntries,
  type CalendarEntry,
  CalendarView,
  type CalendarViewMode,
  calendarVisibleRange,
  type EventEntryMeta,
  type TaskEntryMeta,
  useCalendarVisibility,
} from "@/components/calendar";
import {
  CalendarPanelDropdown,
  type ProjectTaskCalendar,
} from "@/components/initiativeTools/events/CalendarListPanel";
import { ToolFilterPanel } from "@/components/initiativeTools/shared/ToolFilterPanel";
import { TaskStatusPriorityFilters } from "@/components/tasks/TaskStatusPriorityFilters";
import { useMyCalendarEntries } from "@/hooks/useCalendarEntries";
import { useMyCalendars } from "@/hooks/useCalendars";
import { useCommunities } from "@/hooks/useCommunities";
import {
  deviceJSON,
  LIST,
  type ListViewSpec,
  NO_PART_VIEW,
  useListView,
  viewKey,
} from "@/hooks/useListView";
import { useUnreadTree } from "@/hooks/useUnreadTree";
import { communityPath, useCommunityPath } from "@/lib/communityUrl";
import { getErrorMessage } from "@/lib/errorMessage";
import {
  type CalendarViewFilters,
  type CalendarVisibility,
  calendarViewFiltersFromStored,
  carriedCalendarView,
  EMPTY_CALENDAR_VIEW_FILTERS,
} from "@/lib/filters/calendarFilters";
import { getProjectColor } from "@/lib/projectColor";
import { browserTimezone } from "@/lib/timezones";
import { entityRefRoute, toolSettingsRoute } from "@/lib/tools";
import { useWeekStart } from "@/ui/host";
import { Label } from "@/ui/label";
import { MultiSelect } from "@/ui/multi-select";
import { CalendarGridSkeleton, SkeletonRegion } from "@/ui/page-skeletons";

/** Where one person's view of their calendar is kept. What an older release
 *  kept (its filters and month or week as one preference, what was switched
 *  off on the device) is carried over. */
/** Match My Tasks: hide done tasks unless the person opts in. */
const MY_CALENDAR_FILTERS: CalendarViewFilters = {
  ...EMPTY_CALENDAR_VIEW_FILTERS,
  status_categories: ["backlog", "todo", "in_progress"],
};

const MY_CALENDAR_VIEW: ListViewSpec<CalendarViewFilters> = {
  key: viewKey("me", "calendar"),
  read: calendarViewFiltersFromStored,
  defaults: { filters: MY_CALENDAR_FILTERS, ...NO_PART_VIEW },
  carryOver: (items) => {
    const carried = carriedCalendarView({
      prefs: items["initiative-my-calendar-prefs"],
      visibility: deviceJSON("initiative-my-calendar-visibility"),
    });
    // What was never kept reads as the default, as it did then.
    return (
      carried && {
        mode: carried.mode,
        parts: { [LIST]: { filters: { ...MY_CALENDAR_FILTERS, ...carried.filters } } },
      }
    );
  },
};

/** The filter button's state, for whoever places the button. */
export interface MyCalendarFilters {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  activeCount: number;
}

export interface MyCalendarProps {
  /**
   * Puts the calendar in its surroundings — the page's heading and toolbar,
   * or a home widget's card — with the filter button wherever they keep one.
   * `body` is the filter panel and the calendar itself.
   */
  frame: (parts: { filters: MyCalendarFilters; body: ReactNode }) => ReactNode;
  /** Whether the calendar draws its own card: not inside a widget's. */
  framed?: boolean;
}

/**
 * The reader's events and dated tasks from every community, on one calendar:
 * the My Calendar page, and the home page's calendar widget. Both are the
 * same view of the same calendar, kept in one place of the reader's own, so
 * a filter set on one is set on the other.
 */
export const MyCalendar = ({ frame, framed = true }: MyCalendarProps) => {
  const { t } = useTranslation(["tasks", "calendars", "common"]);
  const { communities } = useCommunities();
  const gp = useCommunityPath();
  const navigate = useNavigate();

  const weekStartsOn = useWeekStart();

  // This person's view of their calendar: its mode, its filters, and what is
  // switched off.
  const view = useListView(MY_CALENDAR_VIEW);
  const calendarViewMode = (view.mode ?? "month") as CalendarViewMode;
  const { setFilters } = view;
  const setCalendarViewMode = view.setMode as (next: CalendarViewMode) => void;
  const {
    status_categories: statusFilters,
    priorities: priorityFilters,
    community_ids: communityFilters,
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
  const setCommunityFilters = useCallback(
    (community_ids: number[]) => setFilters((prev) => ({ ...prev, community_ids })),
    [setFilters]
  );
  // Closed until asked for. The filter button carries a count of what's set, so
  // a narrowed list still says so with the panel shut — and the fields no
  // longer take the top of the page before the list itself.
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [focusDate, setFocusDate] = useState(() => new Date());

  // Per-calendar / per-project visibility, across every community: part of
  // their filters.
  const visibility = useCalendarVisibility(
    view.filters,
    useCallback(
      (next: (prev: CalendarVisibility) => CalendarVisibility) =>
        setFilters((prev) => ({ ...prev, ...next(prev) })),
      [setFilters]
    )
  );

  // Badges the filter button while the panel is closed. Hidden calendars count:
  // the reader has narrowed the grid, and nothing else on screen says so.
  const activeFilterCount =
    visibility.hiddenCount +
    statusFilters.length +
    priorityFilters.length +
    communityFilters.length;

  const clearFilters = () => {
    visibility.clear();
    setStatusFilters([]);
    setPriorityFilters([]);
    setCommunityFilters([]);
  };

  const userTimezone = useMemo(browserTimezone, []);

  // The span the current view renders — the window events + tasks fetch over.
  const visibleRange = useMemo(
    () => calendarVisibleRange(focusDate, calendarViewMode, weekStartsOn),
    [focusDate, calendarViewMode, weekStartsOn]
  );

  // Task filter conditions (same JSON shape GET /me/tasks accepts). The date
  // window travels as start_after/start_before on the request (see
  // entriesParams) — the cross-community task path can only be windowed by those
  // params, not by conditions — so it isn't repeated here.
  const taskConditions = useMemo((): (FilterCondition | FilterGroup)[] => {
    const conditions: (FilterCondition | FilterGroup)[] = [];
    if (statusFilters.length > 0) {
      conditions.push({ field: "status_category", op: "in_", value: statusFilters });
    }
    if (priorityFilters.length > 0) {
      conditions.push({ field: "priority", op: "in_", value: priorityFilters });
    }
    if (communityFilters.length > 0) {
      conditions.push({ field: "community_ids", op: "in_", value: communityFilters });
    }
    return conditions;
  }, [statusFilters, priorityFilters, communityFilters]);

  // --- One request: cross-community events + assigned-task markers over the window. ---
  const entriesParams = useMemo((): ListMyCalendarEntriesParams => {
    const params: ListMyCalendarEntriesParams = {
      start_after: visibleRange.start.toISOString(),
      start_before: visibleRange.end.toISOString(),
      conditions: taskConditions,
      tz: userTimezone,
      include_events: true,
      include_tasks: true,
    };
    if (communityFilters.length > 0) {
      params.community_ids = communityFilters;
    }
    return params;
  }, [visibleRange, taskConditions, userTimezone, communityFilters]);

  const entriesQuery = useMyCalendarEntries(entriesParams);

  // The user's visible calendars across communities — the grouping panel's rows and
  // the color source for events without their own color.
  const calendarsQuery = useMyCalendars(
    communityFilters.length > 0 ? { community_ids: communityFilters } : undefined
  );
  const calendars = useMemo(() => calendarsQuery.data?.items ?? [], [calendarsQuery.data]);
  const calendarColors = useMemo(() => {
    const map = new Map<string, string>();
    for (const calendar of calendars)
      map.set(`${calendar.community_id}:${calendar.id}`, calendar.color);
    return map;
  }, [calendars]);

  const communityNamesById = useMemo(() => {
    const map = new Map<number, string>();
    for (const community of communities) map.set(community.id, community.name);
    return map;
  }, [communities]);
  const multiCommunity = communities.length > 1;

  // One read-only virtual calendar per project with a task in the window.
  const projectCalendars = useMemo<ProjectTaskCalendar[]>(() => {
    const seen = new Map<string, ProjectTaskCalendar>();
    const data = entriesQuery.data;
    for (const task of [...(data?.tasks ?? []), ...(data?.task_occurrences ?? [])]) {
      if (task.project_id == null) continue;
      const key = `${task.community_id ?? 0}:${task.project_id}`;
      if (seen.has(key)) continue;
      const communityName =
        multiCommunity && task.community_id != null
          ? communityNamesById.get(task.community_id)
          : undefined;
      const baseName = task.project_name ?? `#${task.project_id}`;
      seen.set(key, {
        projectId: task.project_id,
        communityId: task.community_id ?? 0,
        name: communityName ? `${baseName} · ${communityName}` : baseName,
        color: getProjectColor(task.project_id),
      });
    }
    return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [entriesQuery.data, communityNamesById, multiCommunity]);

  // --- Merge tasks + events into calendar entries (visibility-filtered) ---
  const unread = useUnreadTree();
  const calendarEntries = useMemo<CalendarEntry[]>(() => {
    const entries: CalendarEntry[] = [];

    // Task entries. Reuse the shared builder so the start/due markers get the
    // same visual treatment as the other calendars, injecting communityId into
    // meta for cross-community navigation. Not draggable here (My Calendar has no
    // reschedule handler).
    const data = entriesQuery.data;
    const occurrences = new Set(data?.task_occurrences);
    for (const task of [...(data?.tasks ?? []), ...occurrences]) {
      if (
        task.project_id != null &&
        visibility.isProjectHidden(task.community_id, task.project_id)
      ) {
        continue;
      }
      const color = getProjectColor(task.project_id);
      for (const entry of occurrences.has(task)
        ? buildTaskOccurrenceEntries(task, color)
        : buildTaskCalendarEntries(task, color, false)) {
        entries.push({
          ...entry,
          meta: { ...(entry.meta as Record<string, unknown>), communityId: task.community_id },
        });
      }
    }

    for (const event of entriesQuery.data?.events ?? []) {
      if (visibility.isCalendarHidden(event.community_id, event.calendar_id)) continue;
      entries.push(
        buildEventCalendarEntry(
          event,
          calendarColors.get(`${event.community_id}:${event.calendar_id}`),
          unread.hasSubject(event.community_id, "calendar_event", event.id)
        )
      );
    }

    return entries;
  }, [entriesQuery.data, visibility, calendarColors, unread]);

  const handleEntryClick = (entry: CalendarEntry) => {
    const meta = entry.meta as
      | (TaskEntryMeta & { communityId?: number })
      | EventEntryMeta
      | undefined;
    if (!meta) return;
    const scopedPath = (path: string) =>
      meta.communityId ? communityPath(meta.communityId, path) : gp(path);
    // Cross-community rows carry no initiative, so the resolver works out where
    // the entity lives on the way in.
    if (meta.type === "task") {
      void navigate({ to: scopedPath(entityRefRoute("task", meta.taskId)) });
    } else if (meta.type === "event") {
      void navigate({
        to: scopedPath(entityRefRoute("calendar-event", meta.eventId)),
        search: meta.occurrence ? { occurrence: meta.occurrence } : {},
      });
    }
  };

  // Wait for the calendars metadata too (same gate as the community page):
  // entries rendered before it resolves would flash the generic event color
  // until each calendar's own color arrives.
  const isLoading =
    (entriesQuery.isLoading && !entriesQuery.data) ||
    (calendarsQuery.isLoading && !calendarsQuery.data);

  const body = (
    <div className="space-y-6">
      <ToolFilterPanel
        open={filtersOpen}
        onOpenChange={setFiltersOpen}
        onClear={clearFilters}
        activeCount={activeFilterCount}
      >
        <div className="flex flex-wrap items-end gap-4">
          {/* Calendar visibility — the user's calendars across communities +
                  per-project task calendars behind one dropdown. */}
          <div className="flex items-end">
            <CalendarPanelDropdown
              calendars={calendars}
              projectCalendars={projectCalendars}
              isCalendarHidden={(calendar) =>
                visibility.isCalendarHidden(calendar.community_id, calendar.id)
              }
              isProjectHidden={(project) =>
                visibility.isProjectHidden(project.communityId, project.projectId)
              }
              onToggleCalendar={(calendar) =>
                visibility.toggleCalendar(calendar.community_id, calendar.id)
              }
              onToggleProject={(project) =>
                visibility.toggleProject(project.communityId, project.projectId)
              }
              calendarLabel={(calendar) => {
                const communityName = multiCommunity
                  ? communityNamesById.get(calendar.community_id)
                  : undefined;
                return communityName ? `${calendar.name} · ${communityName}` : calendar.name;
              }}
              settingsPathFor={(calendar) =>
                communityPath(
                  calendar.community_id,
                  toolSettingsRoute(Tool.calendar, calendar.initiative_id, calendar.id)
                )
              }
            />
          </div>
          <TaskStatusPriorityFilters
            statusFilters={statusFilters}
            onStatusChange={setStatusFilters}
            priorityFilters={priorityFilters}
            onPriorityChange={setPriorityFilters}
          />
          <div className="w-full sm:w-48 md:flex-1">
            <Label className="mb-2 block font-medium text-muted-foreground text-xs">
              {t("tasks:filters.filterByCommunity")}
            </Label>
            <MultiSelect
              selectedValues={communityFilters.map(String)}
              options={communities.map((community) => ({
                value: String(community.id),
                label: community.name,
              }))}
              onChange={(values) => {
                const numericValues = values.map(Number).filter(Number.isFinite);
                setCommunityFilters(numericValues);
              }}
              placeholder={t("tasks:filters.allCommunities")}
              emptyMessage={t("tasks:filters.noCommunities")}
            />
          </div>
        </div>
      </ToolFilterPanel>

      {entriesQuery.isError ? (
        <p className="text-destructive text-sm" role="alert">
          {getErrorMessage(entriesQuery.error, "calendars:loadError")}
        </p>
      ) : null}

      {isLoading ? (
        <SkeletonRegion>
          <CalendarGridSkeleton />
        </SkeletonRegion>
      ) : (
        <CalendarView
          entries={calendarEntries}
          viewMode={calendarViewMode}
          onViewModeChange={setCalendarViewMode}
          focusDate={focusDate}
          onFocusDateChange={setFocusDate}
          onEntryClick={handleEntryClick}
          weekStartsOn={weekStartsOn}
          framed={framed}
        />
      )}
    </div>
  );

  return frame({
    filters: { open: filtersOpen, onOpenChange: setFiltersOpen, activeCount: activeFilterCount },
    body,
  });
};
