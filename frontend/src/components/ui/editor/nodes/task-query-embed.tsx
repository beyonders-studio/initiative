import { keepPreviousData } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import type { SortingState } from "@tanstack/react-table";
import { startOfDay } from "date-fns";
import type { NodeKey } from "lexical";
import { ListChecks } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { TaskListRead } from "@/api/generated/initiativeAPI.schemas";
import { sharedTaskColumns } from "@/components/tasks/globalTaskColumns";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { EmbedCallout, useEmbedFold } from "@/components/ui/editor/nodes/embed-callout";
import { Skeleton } from "@/components/ui/skeleton";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { NO_DEFINITIONS, useOwnedDefinitions } from "@/hooks/useProperties";
import { useLiveClockValue } from "@/hooks/useRelativeTime";
import { useKnownTagIds } from "@/hooks/useTags";
import { useTasks } from "@/hooks/useTasks";
import { communityPath } from "@/lib/communityUrl";
import { EMBED_PAGE_SIZE, type EmbedDisplay, type TaskQuery, taskQueryParams } from "@/lib/embeds";
import { taskSortFields, taskTableSorting } from "@/lib/filters/taskFilters";
import { numberFormat } from "@/lib/intl";
import { fieldColumn } from "@/lib/layouts/columns";
import { useProjectLayoutEnv } from "@/lib/layouts/fields";
import { pluginFields, usePluginsOnItems } from "@/lib/layouts/plugins";
import { TASK_COLUMNS, taskFields } from "@/lib/layouts/tasks";
import type { AppColumnDef } from "@/lib/table";
import { entityRefRoute } from "@/lib/tools";

interface TaskQueryEmbedProps {
  query: TaskQuery;
  display: EmbedDisplay;
  /** What its author called it. */
  label: string;
  collapsed: boolean;
  nodeKey: NodeKey;
}

/**
 * The tasks a filter matches, as a list, a table or a count.
 *
 * Read through the same task list every project page reads, as the person
 * looking: each reader sees the tasks they may open, `me` is them, and a due
 * window is counted from today. The list is kept current by the same signal
 * that refreshes a project's board, and it pages rather than stopping short.
 */
export function TaskQueryEmbed({ query, display, label, collapsed, nodeKey }: TaskQueryEmbedProps) {
  const { t, i18n } = useTranslation(["editor", "common"]);
  const communityId = useActiveCommunityId();
  const [page, setPage] = useState(1);
  // A reader may sort a table for themselves; the page's own order is where
  // it starts.
  const [sorting, setSorting] = useState<SortingState>(() => taskTableSorting(query.sort));
  const fold = useEmbedFold(nodeKey, collapsed);
  const counting = display.mode === "count";
  // Read so the embed renders again at local midnight, which rebuilds a due
  // window from the new day.
  useLiveClockValue((now) => startOfDay(now).getTime());
  // A tag deleted since the filter was written would match nothing.
  const tagIds = useKnownTagIds(query.filters.tag_ids);

  const { data, isLoading, isError, isPlaceholderData, refetch } = useTasks(
    taskQueryParams(
      { ...query, filters: { ...query.filters, tag_ids: tagIds }, sort: taskSortFields(sorting) },
      page,
      counting
    ),
    { placeholderData: keepPreviousData }
  );
  const tasks = data?.items ?? [];
  const total = data?.total_count ?? 0;

  // Fewer pages than the reader was on — something finished or was moved
  // while they looked — and the server answers with its last page: follow it.
  useEffect(() => {
    if (data && !isPlaceholderData && !counting && data.page !== page) setPage(data.page);
  }, [data, isPlaceholderData, counting, page]);

  const taskHref = useCallback(
    (taskId: number) => communityPath(communityId, entityRefRoute("task", taskId)),
    [communityId]
  );

  return (
    <EmbedCallout
      icon={ListChecks}
      nodeKey={nodeKey}
      title={
        <span className="min-w-0 flex-1 font-semibold">{label || t("embeds.tasks.untitled")}</span>
      }
      meta={counting ? null : t("embeds.tasks.total", { count: total })}
      fold={counting ? null : fold}
    >
      {isLoading ? (
        <Skeleton className="h-16 w-full" />
      ) : isError && !data ? (
        <div className="flex items-center gap-2 text-muted-foreground text-sm">
          <span>{t("embeds.tasks.error")}</span>
          <Button type="button" variant="ghost" size="sm" onClick={() => void refetch()}>
            {t("common:tryAgain")}
          </Button>
        </div>
      ) : counting ? (
        <p className="font-semibold text-3xl tabular-nums">
          {numberFormat(i18n.language).format(total)}
        </p>
      ) : fold.folded ? null : tasks.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("embeds.tasks.none")}</p>
      ) : display.mode === "table" ? (
        <TaskTable
          query={query}
          columns={display.columns}
          tasks={tasks}
          taskHref={taskHref}
          page={page}
          total={total}
          onPage={setPage}
          sorting={sorting}
          onSorting={(next) => {
            setSorting(next);
            setPage(1);
          }}
        />
      ) : (
        <TaskList tasks={tasks} taskHref={taskHref} page={page} total={total} onPage={setPage} />
      )}
    </EmbedCallout>
  );
}

interface PagedProps {
  page: number;
  total: number;
  onPage: (page: number) => void;
}

/** The tasks as lines: each its name, which opens it, and where it stands. */
function TaskList({
  tasks,
  taskHref,
  page,
  total,
  onPage,
}: PagedProps & { tasks: TaskListRead[]; taskHref: (taskId: number) => string }) {
  const { t } = useTranslation("editor");
  const pages = Math.max(1, Math.ceil(total / EMBED_PAGE_SIZE));
  return (
    <div className="space-y-2">
      <ul className="space-y-1">
        {tasks.map((task) => (
          <li key={task.id} className="flex items-baseline gap-2">
            <Link to={taskHref(task.id)} className="min-w-0 truncate font-medium hover:underline">
              {task.title}
            </Link>
            {task.task_status ? (
              <span className="shrink-0 text-muted-foreground text-xs">
                {task.task_status.name}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
      {pages > 1 ? (
        <div className="flex items-center gap-2 text-muted-foreground text-xs">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={page <= 1}
            onClick={() => onPage(page - 1)}
          >
            {t("embeds.tasks.previous")}
          </Button>
          <span>{t("embeds.tasks.page", { page, pages })}</span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={page >= pages}
            onClick={() => onPage(page + 1)}
          >
            {t("embeds.tasks.next")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

/** The tasks as a table, with the columns its author chose — the columns a
 *  task table draws everywhere, sorted by the server as My Tasks' are. */
function TaskTable({
  query,
  columns: chosen,
  tasks,
  taskHref,
  page,
  total,
  onPage,
  sorting,
  onSorting,
}: PagedProps & {
  query: TaskQuery;
  columns: string[] | undefined;
  tasks: TaskListRead[];
  taskHref: (taskId: number) => string;
  sorting: SortingState;
  onSorting: (sorting: SortingState) => void;
}) {
  const { i18n } = useTranslation();
  const env = useProjectLayoutEnv(taskHref);
  // A query of one project's tasks can show its metadata too.
  const { data: definitions = NO_DEFINITIONS } = useOwnedDefinitions({
    initiativeId: query.initiative_id,
    owner: query.project_id === null ? undefined : { kind: "project", id: query.project_id },
  });
  const plugins = usePluginsOnItems(query.initiative_id);
  const fields = useMemo(
    () => taskFields(definitions, pluginFields(plugins, i18n.language)),
    [definitions, plugins, i18n.language]
  );
  const columns = useMemo(() => {
    const {
      dateGroup: _dateGroup,
      priority: _priority,
      properties,
      ...builtins
    } = sharedTaskColumns<TaskListRead>({ fields, env, isPriorityDisabled: () => true });
    const shared = new Map<string, AppColumnDef<TaskListRead>>([
      ...Object.entries(builtins),
      ...properties.map((column) => [column.id as string, column] as const),
    ]);
    // Priority reads as what it is: an embed is not where it is changed.
    return (chosen ?? TASK_COLUMNS).flatMap((id) => {
      const field = fields.get(id);
      if (!field) return [];
      return [shared.get(id) ?? fieldColumn<TaskListRead>(field, env)];
    });
  }, [chosen, fields, env]);
  return (
    <DataTable
      columns={columns}
      data={tasks}
      getRowId={(task) => String(task.id)}
      enablePagination
      manualPagination
      manualSorting
      sorting={sorting}
      onSortingChange={onSorting}
      pageSizeOptions={[EMBED_PAGE_SIZE]}
      pageIndex={page - 1}
      pageCount={Math.max(1, Math.ceil(total / EMBED_PAGE_SIZE))}
      rowCount={total}
      onPaginationChange={(next) => onPage(next.pageIndex + 1)}
    />
  );
}
