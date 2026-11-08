import { Link } from "@tanstack/react-router";
import { Pin } from "lucide-react";

import {
  type TaskListRead,
  type TaskStatusCategory,
  type TaskStatusRead,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { TaskBlockersHoverCard } from "@/components/projects/TaskBlockersHoverCard";
import { TaskDescriptionHoverCard } from "@/components/projects/TaskDescriptionHoverCard";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";
import { TaskPrioritySelector } from "@/components/tasks/TaskPrioritySelector";
import { TaskStatusSelector } from "@/components/tasks/TaskStatusSelector";
import { NO_TASK_COLUMN_LIMITS, type TaskColumnLimits } from "@/hooks/useColumnLimits";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import { taskColumnId } from "@/lib/layouts/tasks";
import { summarizeStored } from "@/lib/recurrence";
import {
  dateSortingFn,
  firstName,
  firstTagName,
  prioritySortingFn,
  textSortingFn,
} from "@/lib/sorting";
import { getTaskDateStatus, getTaskDateStatusLabel } from "@/lib/taskDateStatus";
import { entityRefRoute, initiativeRoute, toolDetailRoute } from "@/lib/tools";
import { getUserDisplayName } from "@/lib/userDisplay";
import type { TranslateFn } from "@/types/i18n";
import { Button } from "@/ui/button";
import { Checkbox } from "@/ui/checkbox";
import { type FieldColumnOptions, fieldColumn } from "@/ui/layouts/columns";
import type { FieldDef, LayoutEnv } from "@/ui/layouts/fields";
import type { AppColumnDef } from "@/ui/lib/table";
import { SortHeader } from "@/ui/sort-icon";

interface GlobalTaskColumnsOptions {
  activeCommunityId: number | null;
  /** Whether THIS row has a status change in flight — one row saving must not
   *  disable the rest of the table. */
  isUpdatingTask: (task: TaskListRead) => boolean;
  changeTaskStatus: (task: TaskListRead, category: TaskStatusCategory) => Promise<void>;
  changeTaskStatusById: (task: TaskListRead, statusId: number) => Promise<void>;
  fetchProjectStatuses: (
    projectId: number,
    communityId: number | null
  ) => Promise<TaskStatusRead[]>;
  projectStatusCache: React.MutableRefObject<
    Map<number, { statuses: TaskStatusRead[]; complete: boolean }>
  >;
  /** Which of the rows' projects' columns are full. */
  columnLimits?: TaskColumnLimits;
  t: TranslateFn;
  /**
   * Focus-summary pinning. Both are omitted on views that have no focus
   * section, which drops the column entirely rather than showing a dead one.
   */
  isPinned?: (task: TaskListRead) => boolean;
  togglePin?: (task: TaskListRead) => void;
  /** The page's fields, from `taskFields`. */
  fields: ReadonlyMap<string, FieldDef<TaskListRead>>;
  env: LayoutEnv<TaskListRead>;
}

interface SharedTaskColumnsOptions<T extends TaskListRead> {
  /** The table's fields, from `taskFields`. */
  fields: ReadonlyMap<string, FieldDef<TaskListRead>>;
  env: LayoutEnv<TaskListRead>;
  isPriorityDisabled: (task: T) => boolean;
}

/**
 * The columns every task table renders alike, keyed so each table places them
 * in its own order. Each but the date window draws a field, as the board's
 * card does; the properties and the plug-ins' fields follow the tags.
 */
export function sharedTaskColumns<T extends TaskListRead>({
  fields,
  env,
  isPriorityDisabled,
}: SharedTaskColumnsOptions<T>) {
  // `taskFields` holds every built-in.
  const column = (id: string, options: FieldColumnOptions<T>) =>
    fieldColumn<T>(fields.get(id)!, env, { id: taskColumnId(id), ...options });
  const dateGroup: AppColumnDef<T> = {
    id: "date group",
    accessorFn: (task) => getTaskDateStatus(task.start_date, task.due_date),
    header: ({ column }) => (
      <SortHeader column={column} label={env.t("tasks:columns.dateWindow")} />
    ),
    cell: ({ getValue }) => (
      <span className="font-medium text-base">
        {getTaskDateStatusLabel(getValue<string>(), env.t)}
      </span>
    ),
    sortFn: "alphanumeric",
  };
  return {
    dateGroup,
    title: column("title", { sortFn: "alphanumeric" }),
    assignees: column("assignees", {
      sortBy: (task) => firstName(task.assignees.map((assignee) => getUserDisplayName(assignee))),
      sortFn: textSortingFn,
      sortUndefined: "last",
      size: 180,
    }),
    startDate: column("startDate", { sortFn: dateSortingFn }),
    dueDate: column("dueDate", { sortFn: dateSortingFn }),
    // Picking a priority here is the table's own, until fields edit.
    priority: column("priority", {
      sortFn: prioritySortingFn,
      size: 140,
      cell: ({ row }) => (
        <TaskPrioritySelector task={row.original} disabled={isPriorityDisabled(row.original)} />
      ),
    }),
    tags: column("tags", {
      sortBy: (task) => firstTagName(task.tags),
      sortFn: textSortingFn,
      sortUndefined: "last",
    }),
    comments: column("comments", { size: 90 }),
    properties: [...fields.values()]
      .filter((field) => field.source !== "builtin")
      .map((field) => fieldColumn<T>(field, env, { size: 160 })),
  };
}

export function globalTaskColumns({
  activeCommunityId,
  isUpdatingTask,
  changeTaskStatus,
  changeTaskStatusById,
  fetchProjectStatuses,
  projectStatusCache,
  columnLimits = NO_TASK_COLUMN_LIMITS,
  t,
  isPinned,
  togglePin,
  fields,
  env,
}: GlobalTaskColumnsOptions): AppColumnDef<TaskListRead>[] {
  const communityDefaultLabel = t("myTasks.noCommunity");
  const getCommunityGroupLabel = (task: TaskListRead) =>
    task.community_name ?? communityDefaultLabel;

  const shared = sharedTaskColumns<TaskListRead>({
    fields,
    env,
    isPriorityDisabled: isUpdatingTask,
  });

  return [
    shared.dateGroup,
    {
      // The id is kept in device-stored column and grouping state.
      id: "guild",
      accessorFn: (task) => getCommunityGroupLabel(task),
      header: ({ column }) => <SortHeader column={column} label={t("columns.community")} />,
      cell: ({ getValue }) => <span className="font-medium text-base">{getValue<string>()}</span>,
      sortFn: "alphanumeric",
    },
    {
      id: "completed",
      header: () => <span className="font-medium">{t("columns.done")}</span>,
      cell: ({ row }) => {
        const task = row.original;
        const full = columnLimits.fullFor(
          task,
          task.task_status.category === "done" ? "in_progress" : "done"
        );
        return (
          <Checkbox
            checked={task.task_status.category === "done"}
            onCheckedChange={(value) => {
              if (isUpdatingTask(task)) {
                return;
              }
              const targetCategory: TaskStatusCategory = value ? "done" : "in_progress";
              void changeTaskStatus(task, targetCategory);
            }}
            className="h-6 w-6"
            disabled={isUpdatingTask(task) || full !== undefined}
            title={full ? t("projects:kanban.statusFull", { name: full.name }) : undefined}
            aria-label={
              task.task_status.category === "done"
                ? t("checkbox.markInProgress")
                : t("checkbox.markDone")
            }
          />
        );
      },
      enableSorting: false,
      size: 64,
      enableHiding: false,
    },
    ...(isPinned && togglePin
      ? [
          {
            id: "focus",
            header: () => <span className="sr-only">{t("focus.title")}</span>,
            cell: ({ row }) => {
              const task = row.original;
              const pinned = isPinned(task);
              return (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 w-7 p-0"
                  onClick={() => togglePin(task)}
                  aria-label={pinned ? t("focus.unpin") : t("focus.pin")}
                  title={pinned ? t("focus.unpin") : t("focus.pin")}
                >
                  {pinned ? (
                    <Pin className="h-3.5 w-3.5 fill-current text-primary" />
                  ) : (
                    <Pin className="h-3.5 w-3.5 text-muted-foreground" />
                  )}
                </Button>
              );
            },
            enableSorting: false,
            size: 48,
          } satisfies AppColumnDef<TaskListRead>,
        ]
      : []),
    {
      ...shared.title,
      // Its own cell: these rows come from every community, and are all yours.
      cell: ({ row }) => {
        const task = row.original;
        const recurrenceSummary = task.recurrence
          ? summarizeStored(
              task.recurrence,
              task.due_date || task.start_date,
              {
                strategy: task.recurrence_strategy,
                shift: task.recurrence_shift,
                limit: task.recurrence_limit,
              },
              t
            )
          : null;
        return (
          <div className="flex min-w-60 flex-col text-left">
            <div className="flex">
              <Link
                to={env.itemHref(task)}
                className="flex w-full items-center gap-2 font-medium text-foreground hover:underline"
              >
                {task.title}
              </Link>
              <TaskBlockersHoverCard task={task} />
              <TaskDescriptionHoverCard task={task} />
            </div>
            <div className="space-y-1 text-muted-foreground text-xs">
              {recurrenceSummary ? <p>{recurrenceSummary}</p> : null}
            </div>
            <TaskChecklistProgress
              progress={task.checklist_progress}
              className="mt-2 max-w-[200px]"
            />
          </div>
        );
      },
    },
    shared.startDate,
    shared.dueDate,
    {
      id: "path",
      header: () => <span className="font-medium">{t("columns.projectPath")}</span>,
      cell: ({ row }) => {
        const task = row.original;
        const projectLabel = task.project_name ?? t("projectFallback", { id: task.project_id });
        const projectIdentifier = task.project_id;
        const communityName = task.community_name;
        const initiativeId = task.initiative_id;
        const initiativeName = task.initiative_name;
        const initiativeColor = task.initiative_color;
        return (
          <div className="min-w-72">
            <div className="flex flex-wrap items-center gap-2">
              {communityName ? (
                <>
                  <span className="text-muted-foreground text-xs sm:text-sm">{communityName}</span>
                  <span className="text-muted-foreground text-sm" aria-hidden>
                    &gt;
                  </span>
                </>
              ) : null}
              {initiativeId && initiativeName ? (
                <>
                  <Link
                    to={env.communityPath(initiativeRoute(initiativeId), task)}
                    className="flex items-center gap-2 text-muted-foreground text-sm"
                  >
                    <InitiativeColorDot color={initiativeColor ?? undefined} />
                    {initiativeName}
                  </Link>

                  <span className="text-muted-foreground text-sm" aria-hidden>
                    &gt;
                  </span>
                </>
              ) : null}
              <Link
                to={env.communityPath(
                  initiativeId != null
                    ? toolDetailRoute(Tool.project, initiativeId, projectIdentifier)
                    : entityRefRoute(Tool.project, projectIdentifier),
                  task
                )}
                className="font-medium text-primary text-sm hover:underline"
              >
                {projectLabel}
              </Link>
            </div>
          </div>
        );
      },
    },
    shared.priority,
    shared.tags,
    ...shared.properties,
    {
      id: "status",
      // Board order: a status's position in its project.
      accessorFn: (task) => task.task_status?.position,
      header: ({ column }) => <SortHeader column={column} label={t("columns.status")} />,
      cell: ({ row }) => {
        const task = row.original;
        return (
          <div className="space-y-1">
            <TaskStatusSelector
              task={task}
              activeCommunityId={activeCommunityId}
              isUpdatingTaskStatus={isUpdatingTask(task)}
              changeTaskStatusById={changeTaskStatusById}
              fetchProjectStatuses={fetchProjectStatuses}
              projectStatusCache={projectStatusCache}
              isFull={(statusId) => columnLimits.isFull(task, statusId)}
            />
          </div>
        );
      },
    },
  ];
}
