import { keepPreviousData, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearch } from "@tanstack/react-router";
import type { SortingState } from "@tanstack/react-table";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ListMyTasksParams, SortField } from "@/api/generated/initiativeAPI.schemas";
import { getListMyTasksQueryOptions, useListMyTasks } from "@/api/generated/tasks/tasks";
import { useTaskColumnLimits } from "@/hooks/useColumnLimits";
import { useCommunities } from "@/hooks/useCommunities";
import { deviceJSON, LIST, type ListViewSpec, useListView, viewKey } from "@/hooks/useListView";
import { useMyTaskStatusChanges } from "@/hooks/useMyTaskStatusChanges";
import {
  EMPTY_TASK_FILTERS,
  type StoredTaskFilters,
  specFromStored,
  type TaskFilterSpec,
  taskFilterCount,
  taskSortFields,
  taskSpecConditions,
  taskTableSorting,
} from "@/lib/filters/taskFilters";
import { browserTimezone } from "@/lib/timezones";

const SORT_DEFAULTS: SortField[] = [
  { field: "date_group", dir: "asc" },
  { field: "due_date", dir: "asc" },
];

/** What someone who has narrowed nothing sees: their tasks that are not
 *  done. */
const FILTER_DEFAULTS: TaskFilterSpec = {
  ...EMPTY_TASK_FILTERS,
  status_categories: ["backlog", "todo", "in_progress"],
};

const readMyTasksFilters = (raw: unknown) => specFromStored(raw as StoredTaskFilters);

/** What an older release kept: My Tasks' own filter names. */
const fromOldNames = (old: Record<string, unknown>): StoredTaskFilters => ({
  ...(old.statusFilters !== undefined ? { status_categories: old.statusFilters } : {}),
  ...(old.priorityFilters !== undefined ? { priorities: old.priorityFilters } : {}),
  ...(old.communityFilters !== undefined ? { community_ids: old.communityFilters } : {}),
  ...(old.propertyFilters !== undefined ? { properties: old.propertyFilters } : {}),
});

/** Order-insensitive comparison of two selections. */
const sameMembers = <T>(a: T[], b: T[]): boolean =>
  a.length === b.length && new Set(a).size === new Set([...a, ...b]).size;

/**
 * Where one person's view of My Tasks is kept: their filters, and the table's
 * sort, grouping and columns (date window and community hidden, grouped by
 * date window, until they change them). What an older release kept (filters
 * and sort as one preference, grouping and columns on the device) is carried
 * over.
 */
export const MY_TASKS_VIEW: ListViewSpec<TaskFilterSpec> = {
  key: viewKey("me", "tasks"),
  read: readMyTasksFilters,
  defaults: {
    filters: FILTER_DEFAULTS,
    sorting: taskTableSorting(SORT_DEFAULTS),
    grouping: ["date group"],
    columns: { "date group": false, guild: false },
  },
  carryOver: (items) => {
    const old = items["initiative-my-tasks-filters"] as
      | (Record<string, unknown> & { sorting?: SortField[] })
      | undefined;
    const table = deviceJSON("initiative-my-tasks-table") as { grouping?: unknown } | null;
    const columns = deviceJSON("initiative-my-tasks-columns");
    if (!old && !table && !columns) return null;
    const sorting = old?.sorting;
    // What was never kept reads as the default, as it did then.
    const filters = old ? { ...FILTER_DEFAULTS, ...fromOldNames(old) } : {};
    return {
      parts: {
        [LIST]: {
          ...(old ? { filters } : {}),
          ...(Array.isArray(sorting) ? { sorting: taskTableSorting(sorting) } : {}),
          ...(Array.isArray(table?.grouping) ? { grouping: table.grouping } : {}),
          ...(columns && typeof columns === "object" ? { columns } : {}),
        },
      },
    };
  },
};

const PAGE_SIZE = 20;

/** Filters kept somewhere of the caller's own (a home widget's options) in
 *  place of the reader's view. */
export interface OwnTaskFilters {
  /** What was kept, or `undefined` while nothing has been: the reader's view
   *  shows until then. */
  stored: unknown;
  onChange: (next: TaskFilterSpec) => void;
}

export function useGlobalTasksTable(own?: OwnTaskFilters) {
  const { t } = useTranslation(["tasks", "dates", "common"]);
  const { activeCommunityId } = useCommunities();
  const localQueryClient = useQueryClient();
  const router = useRouter();
  const searchParams = useSearch({ strict: false }) as { page?: number };
  const searchParamsRef = useRef(searchParams);
  searchParamsRef.current = searchParams;

  // --- This person's view of My Tasks: their filters and the table's sort ---
  const view = useListView(MY_TASKS_VIEW);
  const preferencesLoaded = view.loaded;
  const ownStored = own?.stored;
  const ownFilters = useMemo(
    () => (ownStored !== undefined ? readMyTasksFilters(ownStored) : null),
    [ownStored]
  );
  const filters = ownFilters ?? view.filters;
  const sorting = useMemo(() => taskSortFields(view.sorting), [view.sorting]);
  const { setFilters: keepFilters, setSorting: keepSorting } = view;
  const keepOwn = own?.onChange;
  const setFilters = useCallback(
    (next: TaskFilterSpec) => (keepOwn ? keepOwn(next) : keepFilters(next)),
    [keepOwn, keepFilters]
  );

  // Closed until asked for. The filter button carries a count of what's set, so
  // a narrowed list still says so with the panel shut.
  const [filtersOpen, setFiltersOpen] = useState(false);

  // This page starts on a status selection rather than an empty one, so status
  // counts as "set" only once it differs from that baseline — otherwise the
  // button would badge a list nobody has touched.
  const activeFilterCount = taskFilterCount({
    ...filters,
    status_categories: sameMembers(filters.status_categories, FILTER_DEFAULTS.status_categories)
      ? []
      : filters.status_categories,
  });

  /** Back to what someone who narrowed nothing sees. Kept filters of the
   *  caller's own say so outright, rather than falling back to the view's. */
  const clearFilters = useCallback(
    () => (keepOwn ? keepOwn(FILTER_DEFAULTS) : keepFilters(null)),
    [keepOwn, keepFilters]
  );

  // --- Pagination state ---
  const [page, setPageState] = useState(() => searchParams.page ?? 1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);

  const setPage = useCallback(
    (updater: number | ((prev: number) => number)) => {
      setPageState((prev) => {
        const next = typeof updater === "function" ? updater(prev) : updater;
        void router.navigate({
          to: ".",
          search: {
            ...searchParamsRef.current,
            page: next <= 1 ? undefined : next,
          },
          replace: true,
        });
        return next;
      });
    },
    [router]
  );

  // The table captures its seed at mount, which is why the caller holds the
  // table back until `preferencesLoaded` — mounting first would freeze the
  // headers on the default sort while the rows came back in the saved one.
  const initialSorting = view.sorting;

  const handleSortingChange = useCallback(
    (tableSorting: SortingState) => {
      keepSorting(tableSorting);
      setPage(1);
    },
    [setPage, keepSorting]
  );

  // Reset to page 1 when filters change
  const filtersKey = JSON.stringify(filters);
  useEffect(() => {
    void filtersKey;
    setPage(1);
  }, [filtersKey, setPage]);

  // --- User timezone for server-side date_group calculation ---
  const userTimezone = useMemo(browserTimezone, []);

  // --- Tasks query ---
  const tasksParams = useMemo((): ListMyTasksParams => {
    const conditions = taskSpecConditions(filters);
    return {
      conditions: conditions.length > 0 ? conditions : undefined,
      page,
      page_size: pageSize,
      sorting: sorting.length > 0 ? sorting : undefined,
      tz: userTimezone,
    };
  }, [filters, page, pageSize, sorting, userTimezone]);

  const tasksQuery = useListMyTasks(tasksParams, {
    query: {
      placeholderData: keepPreviousData,
      // Nothing is worth asking for until the saved filters and sort are in
      // hand: a request built on the defaults would be thrown away the moment
      // they arrive, and its rows would sit under the saved sort's headers in
      // the meantime.
      enabled: preferencesLoaded,
    },
  });

  const prefetchPage = useCallback(
    (targetPage: number) => {
      if (targetPage < 1) return;
      const prefetchParams: ListMyTasksParams = {
        ...tasksParams,
        page: targetPage,
      };

      void localQueryClient.prefetchQuery(getListMyTasksQueryOptions(prefetchParams));
    },
    [tasksParams, localQueryClient]
  );

  // --- Status changes, and what each row's project offers ---
  const status = useMyTaskStatusChanges();
  const { rememberStatuses } = status;
  const tasks = useMemo(() => tasksQuery.data?.items ?? [], [tasksQuery.data]);
  useEffect(() => rememberStatuses(tasks), [tasks, rememberStatuses]);
  const columnLimits = useTaskColumnLimits(tasks);

  // --- Display tasks ---
  // Archived/template projects are excluded server-side, so the rows come
  // back ready to render.
  const displayTasks = tasks;

  // --- Derived loading / error states ---
  const isInitialLoad = tasksQuery.isLoading && !tasksQuery.data;

  const isRefetching = tasksQuery.isFetching && !isInitialLoad;

  const hasError = tasksQuery.isError;

  const totalCount = tasksQuery.data?.total_count ?? 0;
  const totalPages = pageSize > 0 ? Math.ceil(totalCount / pageSize) : 1;

  return {
    // Filter state
    filters,
    setFilters,
    filtersOpen,
    setFiltersOpen,
    activeFilterCount,
    clearFilters,

    // Query results
    tasksQuery,

    // Pagination
    page,
    setPage,
    pageSize,
    setPageSize,
    totalPages,
    totalCount,

    // Sorting
    initialSorting,
    handleSortingChange,

    // False until the saved filters and sort have resolved.
    preferencesLoaded,

    // Prefetching
    prefetchPage,

    // Status mutations
    changeTaskStatus: status.changeTaskStatus,
    changeTaskStatusById: status.changeTaskStatusById,
    fetchProjectStatuses: status.fetchProjectStatuses,
    projectStatusCache: status.projectStatusCache,
    isUpdatingTask: status.isUpdatingTask,
    // Which of the rows' projects' columns are full
    columnLimits,

    // Display data
    displayTasks,

    // Loading states
    isInitialLoad,
    isRefetching,
    hasError,

    // Context
    activeCommunityId,
    localQueryClient,
    t,
  };
}
