/**
 * One person's view of a project's tasks: which of the project's list layouts
 * they are in, and their own filters, sort and grouping on each, kept for them
 * on the project as their view of that list ({@link useListView}). A layout is
 * how the project draws its tasks; what a person narrows the list to and how
 * they order it are theirs. A layout's presets are where they can start from:
 * picking one makes its filters and sort theirs.
 *
 * The project page reads it to show the list, and the project's export card
 * reads it so an export starts from the same tasks.
 */

import type { GroupingState, SortingState } from "@tanstack/react-table";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";

import {
  type ListLayoutDefinitionInput,
  type ListLayoutRead,
  type ListLayoutReadKind,
  type SortField,
  type TaskStatusRead,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useFieldCatalog } from "@/hooks/useFieldCatalog";
import {
  type ListViewSpec,
  NO_PART_VIEW,
  partOf,
  type StoredListView,
  useListView,
  usePresetLink,
  viewKey,
} from "@/hooks/useListView";
import { useProject, useProjectTaskStatuses, useProjectTaskTypes } from "@/hooks/useProjects";
import { useKnownTagIds } from "@/hooks/useTags";
import { detailLayoutOf, listLayouts, useInstanceLayouts } from "@/hooks/useToolLayouts";
import {
  EMPTY_TASK_FILTERS,
  type StoredTaskFilters,
  specFromStored,
  type TaskFilterSpec,
  taskFilterCount,
  taskFiltersEqual,
  taskSortFields,
} from "@/lib/filters/taskFilters";
import { pageParts, type StoredRegions } from "@/lib/layouts/detailLayout";
import { columnsOf } from "@/lib/layouts/draft";
import { catalogChoices, viewGrouping } from "@/lib/layouts/grouping";
import { pluginFields, shippedPluginParts, usePluginsOnItems } from "@/lib/layouts/plugins";
import { type Preset, presetsOf, TASK_PRESETS } from "@/lib/layouts/presets";
import { BOARD_COLUMNS } from "@/lib/layouts/taskGroupings";
import { TASK_LIST_SHAPE, taskLayoutFor } from "@/lib/layouts/tasks";

const readTaskFilters = (raw: unknown) => specFromStored(raw as StoredTaskFilters);
const TASK_DEFAULTS = { filters: EMPTY_TASK_FILTERS, ...NO_PART_VIEW };

/** Where one person's view of a project's tasks is kept, and what it holds. */
export const projectViewSpec = (
  communityId: number,
  projectId: number
): ListViewSpec<TaskFilterSpec> => ({
  key: viewKey("project", projectId),
  communityId,
  read: readTaskFilters,
  defaults: TASK_DEFAULTS,
});

/** What the URL names: `?layout=` and `?preset=`, which a link means for
 *  whoever opens it. */
export type ProjectViewSearch = { layout?: string; preset?: string };

/** The lists a project's menu offers: those it has not hidden. */
const shownOf = (layouts: readonly ListLayoutRead[]) => layouts.filter((each) => !each.hidden);

/** The layout a person sees, of those the project shows: the one the URL
 *  names (a link means the same layout for whoever opens it), else the one
 *  they were last in, else the one the project opens on. */
const layoutShown = (
  search: ProjectViewSearch,
  lists: readonly ListLayoutRead[],
  view: StoredListView
) => {
  const layouts = shownOf(lists);
  return (
    layouts.find((each) => each.kind === search.layout) ??
    layouts.find((each) => each.kind === view.layout) ??
    layouts.find((each) => each.is_default) ??
    layouts[0] ??
    null
  );
};

/**
 * Which layout a person sees and their filters and sort for it. A preset the
 * URL names gives its filters and sort; otherwise they are the person's own.
 * The page and the route's prefetch both resolve it here, so the prefetch
 * lands on the key the page asks for.
 */
export const resolveProjectView = (
  search: ProjectViewSearch,
  layouts: readonly ListLayoutRead[],
  view: StoredListView
) => {
  const layout = layoutShown(search, layouts, view);
  const kind: ListLayoutReadKind = layout?.kind ?? "board";
  const presets = presetsOf(layout?.definition, TASK_PRESETS);
  const preset = presets.find((each) => each.slug === search.preset) ?? null;
  const own = partOf(view, kind, { read: readTaskFilters, defaults: TASK_DEFAULTS });
  return {
    layout,
    kind,
    presets,
    preset,
    spec: preset?.filters ?? own.filters,
    sorting: preset?.sorting ?? own.sorting,
  };
};

const sameSorting = (a: SortingState, b: SortingState) =>
  a.length === b.length &&
  a.every((each, index) => each.id === b[index].id && each.desc === b[index].desc);

export function useProjectTaskView({
  projectId,
  taskStatuses,
  search,
}: {
  projectId: number;
  /** The project's statuses, to drop a filter on one that is gone. */
  taskStatuses: TaskStatusRead[];
  search: ProjectViewSearch;
}) {
  const communityId = useActiveCommunityId();
  const spec = useMemo(() => projectViewSpec(communityId, projectId), [communityId, projectId]);

  // The project's layouts. `can_configure` is computed server-side and is what
  // gates the editor. The list waits for them, which say how it is drawn; a
  // set that cannot be read is reported, with a way to ask again, rather than
  // guessed at.
  const layoutsQuery = useInstanceLayouts(Tool.project, projectId);
  const layoutsLoaded = layoutsQuery.data !== undefined;
  const layoutsFailed = layoutsQuery.isError && !layoutsLoaded;
  const { refetch: refetchLayouts } = layoutsQuery;
  const retryLayouts = useCallback(() => void refetchLayouts(), [refetchLayouts]);
  const canConfigure = layoutsQuery.data?.can_configure ?? false;
  const lists = useMemo(() => listLayouts(layoutsQuery.data), [layoutsQuery.data]);
  const layouts = useMemo(() => shownOf(lists), [lists]);

  // What an export of the tasks shows: the table's columns, and the task
  // page's parts in its order, as the project's default type lays it out. The
  // shipped ones are the app's, so the export is told them.
  const { i18n } = useTranslation();
  const plugins = usePluginsOnItems(useProject(projectId).data?.initiative_id);
  const types = useProjectTaskTypes(projectId).data;
  const defaultType = types?.find((type) => type.is_default) ?? types?.[0];
  const exportFields = useMemo(() => {
    // Hidden or not, the table's columns are what an export lists.
    const table = lists.find((each) => each.kind === "table");
    const fields = new Map(pluginFields(plugins, i18n.language).map((field) => [field.id, field]));
    return {
      columns: columnsOf(
        (table?.definition ?? {}) as ListLayoutDefinitionInput,
        fields,
        TASK_LIST_SHAPE
      ),
      detail: pageParts(
        taskLayoutFor(defaultType?.layout_preset).tree(
          detailLayoutOf(layoutsQuery.data, "task", defaultType?.id) as StoredRegions | null,
          shippedPluginParts(plugins)
        )
      ),
    };
  }, [lists, plugins, i18n.language, layoutsQuery.data, defaultType]);

  const view = useListView(spec, (kept) => layoutShown(search, lists, kept)?.kind ?? "board");
  const kind = view.part as ListLayoutReadKind;
  const layout = layouts.find((each) => each.kind === kind) ?? null;
  const presets = useMemo(() => presetsOf(layout?.definition, TASK_PRESETS), [layout]);

  const { apply, setFilters: keepFilters, setSorting, rememberLayout } = view;
  /** Keep `next` as this person's filters for the layout on screen, or drop
   *  theirs (null) to see every task. */
  const setFilters = useCallback(
    (next: TaskFilterSpec | null) => {
      keepFilters(next);
      rememberLayout(kind);
    },
    [keepFilters, rememberLayout, kind]
  );
  const keepSorting = useCallback(
    (next: SortingState) => {
      setSorting(next);
      rememberLayout(kind);
    },
    [setSorting, rememberLayout, kind]
  );
  /** Make `next`'s filters and sort this person's own on the layout on
   *  screen. Which layout they come back to is theirs to pick: a link that
   *  names one does not change it. */
  const applyPreset = useCallback(
    (next: Preset) => apply({ filters: next.filters, sorting: next.sorting }),
    [apply]
  );
  const { preset, pick: pickPreset } = usePresetLink({
    slug: search.preset,
    presets,
    ready: layoutsLoaded && view.loaded,
    scope: `${projectId}:${kind}`,
    apply: applyPreset,
    same: useCallback(
      (each: Preset) =>
        taskFiltersEqual(view.filters, each.filters) && sameSorting(view.sorting, each.sorting),
      [view.filters, view.sorting]
    ),
  });
  const spec_ = preset?.filters ?? view.filters;
  const sorting = preset?.sorting ?? view.sorting;

  const tag_ids = useKnownTagIds(spec_.tag_ids);

  const { grouping: kept, groupingKept } = view;
  const { groupings: catalog } = useFieldCatalog("tasks");
  const grouping = useMemo(
    () =>
      viewGrouping(
        layout?.definition,
        kind,
        groupingKept ? kept : null,
        catalogChoices(catalog, BOARD_COLUMNS)
      ),
    [layout, kind, kept, groupingKept, catalog]
  );

  /**
   * The filters actually applied, with ids that no longer resolve dropped:
   * deleted tags (see {@link useKnownTagIds}) and removed statuses. Statuses
   * arrive as a prop, so an empty list means "not loaded yet" and nothing is
   * pruned.
   */
  const appliedSpec = useMemo(() => {
    const spec = spec_;
    const statusIds = new Set(taskStatuses.map((status) => status.id));
    const status_ids =
      taskStatuses.length > 0 ? spec.status_ids.filter((id) => statusIds.has(id)) : spec.status_ids;
    if (tag_ids === spec.tag_ids && status_ids.length === spec.status_ids.length) {
      return spec;
    }
    return { ...spec, tag_ids, status_ids };
  }, [spec_, tag_ids, taskStatuses]);

  return {
    filtersLoaded: view.loaded,
    layoutsLoaded,
    layoutsFailed,
    retryLayouts,
    retryingLayouts: layoutsQuery.isFetching,
    layouts,
    canConfigure,
    layout,
    kind,
    /** What the layout on screen offers to start from. */
    presets,
    /** The one the URL names, while it does. */
    preset,
    spec: spec_,
    /** This person narrows the list on screen. */
    filtered: taskFilterCount(spec_) > 0,
    appliedSpec,
    sorting,
    setFilters,
    setSorting: keepSorting,
    /** Name a preset in the URL, which applies it; or none. */
    pickPreset,
    rememberLayout,
    /** How much of the calendar the Gantt shows: a day, a week or a month. */
    mode: view.mode,
    setMode: view.setMode,
    grouping,
    setGrouping: view.setGrouping,
    exportFields,
  };
}

/** How a project's task table is shown to one person: grouped and sorted as
 *  their view keeps it. */
export type ProjectTaskTableState = [
  { grouping: GroupingState; sorting: SortingState },
  {
    setGrouping: (next: GroupingState) => void;
    setSorting: (next: SortingState) => void;
  },
];

export const useProjectTaskTableState = (
  grouping: GroupingState,
  setGrouping: (next: GroupingState) => void,
  sorting: SortingState,
  setSorting: (next: SortingState) => void
): ProjectTaskTableState =>
  useMemo(
    () => [
      { grouping, sorting },
      { setGrouping, setSorting },
    ],
    [grouping, sorting, setGrouping, setSorting]
  );

/** The order a list shows tasks in, as the endpoint's `sorting`: the table's
 *  sort while it is the layout, and the project's order in every other. */
export const taskViewSorting = (
  kind: ListLayoutReadKind,
  tableSorting: Parameters<typeof taskSortFields>[0]
): SortField[] => (kind === "table" ? taskSortFields(tableSorting) : []);

/** What an export of the project starts from for this person: the tasks and
 *  the order their view of it shows, with the statuses those filters name. */
export function useProjectTaskExportView(projectId: number) {
  const taskStatuses = useProjectTaskStatuses(projectId).data ?? EMPTY_STATUSES;
  const { appliedSpec, kind, sorting, exportFields } = useProjectTaskView({
    projectId,
    taskStatuses,
    search: NO_SEARCH,
  });
  return useMemo(
    () => ({
      tasks: appliedSpec,
      taskSorting: taskViewSorting(kind, sorting),
      taskColumns: exportFields.columns,
      taskStatuses,
    }),
    [appliedSpec, kind, sorting, exportFields, taskStatuses]
  );
}

const EMPTY_STATUSES: TaskStatusRead[] = [];
const NO_SEARCH = {};
