import type { ColumnVisibilityState } from "@tanstack/react-table";
import { Inbox, SquareCheckBig } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { type TaskListRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { HomeWidgetCard, HomeWidgetNotice } from "@/components/home/HomeWidgetCard";
import {
  ToolFilterButton,
  ToolFilterPanel,
} from "@/components/initiativeTools/shared/ToolFilterPanel";
import { globalTaskColumns } from "@/components/tasks/globalTaskColumns";
import { TaskFilters } from "@/components/tasks/TaskFilters";
import { useCommunities } from "@/hooks/useCommunities";
import { useFocusPreferences } from "@/hooks/useFocusSummary";
import { MY_TASKS_VIEW, useGlobalTasksTable } from "@/hooks/useGlobalTasksTable";
import { useListView } from "@/hooks/useListView";
import { useMyToolRows } from "@/hooks/useMyTools";
import { useProperties } from "@/hooks/useProperties";
import { useTaskListName } from "@/hooks/useTaskListName";
import { communityPath } from "@/lib/communityUrl";
import type { HomeTaskList } from "@/lib/home/firstHome";
import { LAYOUT_NAMESPACES, type LayoutEnv } from "@/lib/layouts/fields";
import { taskFields } from "@/lib/layouts/tasks";
import { entityRefRoute, taskRoute } from "@/lib/tools";
import type { TranslateFn } from "@/types/i18n";
import { Button } from "@/ui/button";
import { Combobox } from "@/ui/combobox";
import { DataTable } from "@/ui/data-table";
import { Label } from "@/ui/label";
import { SkeletonRegion, TableSkeleton } from "@/ui/page-skeletons";
import { StatusMessage } from "@/ui/status-message";

import { QuickAddTask } from "./QuickAddTask";
import type { HomeWidgetProps, HomeWidgetSettingsProps } from "./types";

/**
 * The reader's tasks from every community, as a table: what the My Tasks page
 * was, now one widget of the home page. Its view — sort, grouping — is the
 * reader's own and kept where My Tasks kept it, so
 * nobody's table changed when the page became a widget. Its filters and
 * columns are the widget's own, so two of them can show different tasks, or
 * the same ones two ways; one that has never had them changed shows the ones
 * My Tasks kept.
 *
 * Its own options name a list to add to, which puts a line for a new task at
 * the top; a reader with nothing assigned yet is told what lands here, and
 * offered that line, rather than shown an empty table.
 */
export const TasksWidget = ({ options, onOptionsChange, onConfigure }: HomeWidgetProps) => {
  const { t } = useTranslation(["tasks", "dates", "common", "projects", "home"]);

  const { communities } = useCommunities();

  // This person's view of My Tasks: the table's grouping and columns.
  const view = useListView(MY_TASKS_VIEW);

  const table = useGlobalTasksTable({
    stored: options.filters,
    onChange: (filters) => onOptionsChange({ ...options, filters }),
  });
  const focus = useFocusPreferences();
  const list = listOf(options);
  // Offered only while the list is there to add to.
  const listName = useTaskListName(list).data;
  const addTo = list && listName ? { list, name: listName } : null;
  // Nothing at all to show, not a narrowed list with nothing in it: that one
  // is said by the table, under the filters that narrowed it.
  const nothingYet =
    !table.isInitialLoad &&
    !table.hasError &&
    table.totalCount === 0 &&
    table.activeFilterCount === 0;

  const { data: allPropertyDefinitions = [] } = useProperties();
  const fields = useMemo(() => taskFields(allPropertyDefinitions), [allPropertyDefinitions]);
  // Rows come from every community: each one's links go to its own.
  const { t: viewT } = useTranslation(LAYOUT_NAMESPACES);
  const env = useMemo<LayoutEnv>(() => {
    const path = (to: string, task: TaskListRead) => {
      const communityId = task.community_id ?? table.activeCommunityId;
      return communityId ? communityPath(communityId, to) : to;
    };
    return {
      t: viewT as TranslateFn,
      communityPath: path,
      // A row without an initiative resolves through /go.
      itemHref: (task) =>
        path(
          task.initiative_id != null
            ? taskRoute(task.initiative_id, task.project_id, task.id)
            : entityRefRoute("task", task.id),
          task
        ),
    };
  }, [viewT, table.activeCommunityId]);
  // Property columns start hidden.
  const propertyHiddenIds = useMemo(
    () => [...fields.values()].filter((field) => field.source === "property").map(({ id }) => id),
    [fields]
  );
  const { setGrouping } = view;
  const keptColumns = columnsOf(options) ?? view.columns;
  // A column they never chose about is shown, but for the date window, the
  // community ("guild", the id the stored state is keyed by) and properties.
  const effectiveColumnVisibility = useMemo(() => {
    const next = { ...keptColumns };
    for (const id of ["date group", "guild", ...propertyHiddenIds]) {
      if (!(id in next)) next[id] = false;
    }
    return next;
  }, [keptColumns, propertyHiddenIds]);
  const setColumnVisibility = useCallback(
    (next: ColumnVisibilityState | ((prev: ColumnVisibilityState) => ColumnVisibilityState)) =>
      onOptionsChange({
        ...options,
        columns: typeof next === "function" ? next(effectiveColumnVisibility) : next,
      }),
    [onOptionsChange, options, effectiveColumnVisibility]
  );

  const columns = useMemo(
    () =>
      globalTaskColumns({
        activeCommunityId: table.activeCommunityId,
        isUpdatingTask: table.isUpdatingTask,
        changeTaskStatus: table.changeTaskStatus,
        changeTaskStatusById: table.changeTaskStatusById,
        fetchProjectStatuses: table.fetchProjectStatuses,
        projectStatusCache: table.projectStatusCache,
        columnLimits: table.columnLimits,
        t: t as TranslateFn,
        isPinned: focus.isPinned,
        togglePin: focus.togglePin,
        fields,
        env,
      }),
    [
      table.activeCommunityId,
      table.isUpdatingTask,
      table.changeTaskStatus,
      table.changeTaskStatusById,
      table.fetchProjectStatuses,
      table.projectStatusCache,
      table.columnLimits,
      t,
      fields,
      env,
      focus.isPinned,
      focus.togglePin,
    ]
  );

  const groupingOptions = useMemo(
    () => [
      { id: "date group", label: t("myTasks.groupByDate") },
      { id: "guild", label: t("myTasks.groupByCommunity") },
    ],
    [t]
  );

  return (
    <HomeWidgetCard
      icon={SquareCheckBig}
      title={t("myTasks.title")}
      actions={
        <ToolFilterButton
          open={table.filtersOpen}
          onOpenChange={table.setFiltersOpen}
          activeCount={table.activeFilterCount}
        />
      }
    >
      <div className="space-y-4">
        {addTo && !nothingYet ? <QuickAddTask list={addTo.list} name={addTo.name} /> : null}
        <ToolFilterPanel
          open={table.filtersOpen}
          onOpenChange={table.setFiltersOpen}
          onClear={table.clearFilters}
          activeCount={table.activeFilterCount}
        >
          <TaskFilters
            scope={{ kind: "mine", communities }}
            value={table.filters}
            onChange={table.setFilters}
          />
        </ToolFilterPanel>

        <div className="relative">
          {/* A refetch is a background event: a status change has already
                been applied to the rows optimistically, and the reader can go
                on sorting, paging and checking things off while the
                cross-community aggregate catches up. So this says a refresh is
                running and takes nothing away — no cover, no pointer events,
                no dimming of rows that are already correct. */}
          {table.isRefetching ? (
            <div
              aria-hidden
              className="pointer-events-none absolute inset-x-0 top-0 z-10 h-0.5 overflow-hidden rounded-full bg-primary/15"
            >
              <div className="h-full w-1/3 animate-indeterminate-sweep rounded-full bg-primary/60" />
            </div>
          ) : null}
          <span aria-live="polite" className="sr-only">
            {table.isRefetching ? t("updating") : ""}
          </span>
          {/* The saved sort has to be in hand before the table mounts: it
                seeds its headers once, so a table built on the defaults would
                keep claiming them while the rows came back in the saved order.
                The filters resolve from the same request. */}
          {table.isInitialLoad || !table.preferencesLoaded ? (
            <SkeletonRegion>
              <TableSkeleton rows={8} columns={6} pagination />
            </SkeletonRegion>
          ) : table.hasError ? (
            <StatusMessage />
          ) : nothingYet ? (
            <HomeWidgetNotice
              icon={Inbox}
              action={
                addTo ? (
                  <div className="w-full max-w-md">
                    <QuickAddTask list={addTo.list} name={addTo.name} />
                  </div>
                ) : (
                  <Button type="button" variant="outline" size="sm" onClick={onConfigure}>
                    {t("home:widgets.tasks.chooseList")}
                  </Button>
                )
              }
            >
              {t("home:widgets.tasks.empty")}
            </HomeWidgetNotice>
          ) : (
            <DataTable
              columns={columns}
              data={table.displayTasks}
              groupingOptions={groupingOptions}
              columnVisibility={effectiveColumnVisibility}
              onColumnVisibilityChange={setColumnVisibility}
              // Sort and grouping are shared by every tasks widget on the
              // page, so each table follows them rather than its own copy.
              grouping={view.grouping}
              onGroupingChange={setGrouping}
              initialState={{ expanded: true }}
              sorting={table.initialSorting}
              enableFilterInput
              filterInputColumnKey="title"
              filterInputPlaceholder={t("filters.filterPlaceholder")}
              enablePagination
              manualPagination
              pageCount={table.totalPages}
              rowCount={table.totalCount}
              pageIndex={table.page - 1}
              onPaginationChange={(pag) => {
                if (pag.pageSize !== table.pageSize) {
                  table.setPageSize(pag.pageSize);
                  table.setPage(1);
                } else {
                  table.setPage(pag.pageIndex + 1);
                }
              }}
              onPrefetchPage={table.prefetchPage}
              manualSorting
              onSortingChange={table.handleSortingChange}
              enableResetSorting
              enableColumnVisibilityDropdown
            />
          )}
        </div>
      </div>
    </HomeWidgetCard>
  );
};

const listOf = (options: Record<string, unknown>): HomeTaskList | null => {
  const list = options.addTo as Partial<HomeTaskList> | undefined;
  return list &&
    typeof list.communityId === "number" &&
    typeof list.initiativeId === "number" &&
    typeof list.projectId === "number"
    ? { communityId: list.communityId, initiativeId: list.initiativeId, projectId: list.projectId }
    : null;
};

/** The columns this widget shows and hides, once its reader has chosen any. */
const columnsOf = (options: Record<string, unknown>): ColumnVisibilityState | null => {
  const columns = options.columns;
  if (!columns || typeof columns !== "object" || Array.isArray(columns)) return null;
  return Object.fromEntries(
    Object.entries(columns).filter(([, shown]) => typeof shown === "boolean")
  ) as ColumnVisibilityState;
};

/** How many lists the picker asks for at a time; typing narrows on the server. */
const LIST_PAGE = 20;

/** Which list the line for a new task adds to, out of the reader's projects. */
export const TasksSettings = ({ options, onChange }: HomeWidgetSettingsProps) => {
  const { t } = useTranslation("home");
  const { communities } = useCommunities();
  const [search, setSearch] = useState("");
  const { rows, isLoading } = useMyToolRows(Tool.project, 1, LIST_PAGE, {
    search: search || undefined,
    sortBy: "name",
    sortDir: "asc",
  });
  const current = listOf(options);
  const currentName = useTaskListName(current).data;
  const communityNames = new Map(communities.map((community) => [community.id, community.name]));
  const key = (communityId: number, projectId: number) => `${communityId}:${projectId}`;
  const lists = rows.filter((row) => row.initiativeId != null);
  const { addTo: _dropped, ...withoutList } = options;

  return (
    <div className="space-y-2">
      <Label>{t("widgets.tasks.addTo")}</Label>
      <Combobox
        aria-label={t("widgets.tasks.addTo")}
        items={lists.map((row) => ({
          value: key(row.communityId, row.id),
          label:
            communities.length > 1
              ? `${row.name} · ${communityNames.get(row.communityId) ?? ""}`
              : row.name,
        }))}
        value={current ? key(current.communityId, current.projectId) : null}
        selectedLabel={currentName ?? null}
        onSearchChange={setSearch}
        loading={isLoading}
        placeholder={t("widgets.tasks.chooseList")}
        onValueChange={(value) => {
          const row = lists.find((each) => key(each.communityId, each.id) === value);
          if (!row || row.initiativeId == null) return;
          onChange({
            ...withoutList,
            addTo: {
              communityId: row.communityId,
              initiativeId: row.initiativeId,
              projectId: row.id,
            },
          });
        }}
      />
      <p className="text-muted-foreground text-xs">{t("widgets.tasks.addToHint")}</p>
      {current ? (
        <Button
          type="button"
          variant="link"
          className="h-auto p-0"
          onClick={() => onChange(withoutList)}
        >
          {t("widgets.tasks.noList")}
        </Button>
      ) : null}
    </div>
  );
};
