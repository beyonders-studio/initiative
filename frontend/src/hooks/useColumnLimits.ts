import { useQueries } from "@tanstack/react-query";
import { useMemo } from "react";

import {
  type ColumnFillRead,
  type TaskListRead,
  type TaskStatusCategory,
  type TaskStatusRead,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { getListTaskStatusesQueryOptions } from "@/api/generated/task-statuses/task-statuses";
import { getListColumnLimitsQueryOptions, useListColumnLimits } from "@/api/generated/tasks/tasks";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useInstanceLayouts } from "@/hooks/useToolLayouts";
import { listLayouts } from "@/ui/layouts/layoutSet";

/** The most a column may be limited to, as the server holds a layout to. */
export const MAX_COLUMN_LIMIT = 10_000;

/** The most projects one ask for their column limits names, as the server takes. */
const PROJECTS_PER_ASK = 100;

/** A project's board column limits, and how full each limited column is. */
export type ColumnLimits = {
  /** The most open tasks the column takes, where it is limited. */
  limitOf: (statusId: number) => number | undefined;
  /** How many open tasks it holds, whatever the reader's filters show. */
  countOf: (statusId: number) => number;
  /** Whether the column is too full to take `entering` more tasks (one by
   *  default). */
  isFull: (statusId: number, entering?: number) => boolean;
  /** The counts are in, where a column is limited: until then no column
   *  reads as full. */
  ready: boolean;
};

/** A project whose board limits no column. */
export const NO_COLUMN_LIMITS: ColumnLimits = {
  limitOf: () => undefined,
  countOf: () => 0,
  isFull: () => false,
  ready: true,
};

type Fill = Pick<ColumnFillRead, "status_id" | "limit" | "count">;

const overflows = (fill: Fill | undefined, entering = 1) =>
  fill !== undefined && fill.count + entering > fill.limit;

/** A board's limits, from each limited column's limit and count; none are
 *  full until the counts are in. */
export const columnLimitsOf = (fills: readonly Fill[] | undefined): ColumnLimits => {
  const held = new Map((fills ?? []).map((fill) => [fill.status_id, fill]));
  return {
    limitOf: (statusId) => held.get(statusId)?.limit,
    countOf: (statusId) => held.get(statusId)?.count ?? 0,
    isFull: (statusId, entering) => overflows(held.get(statusId), entering),
    ready: fills !== undefined,
  };
};

/**
 * The project's board column limits, and how many open tasks each limited
 * column holds, as the server counts them. Asked only where the board's
 * layout limits a column, and refetched with the project's tasks and
 * layouts.
 */
export const useColumnLimits = (projectId: number | null): ColumnLimits => {
  const communityId = useActiveCommunityId();
  const layouts = useInstanceLayouts(Tool.project, projectId).data;
  const limited = listLayouts(layouts).some(
    (layout) => layout.kind === "board" && (layout.definition.limits?.length ?? 0) > 0
  );
  const fills = useListColumnLimits(
    communityId,
    { project_id: [projectId ?? 0] },
    { query: { enabled: projectId !== null && limited } }
  ).data;
  return useMemo(() => (limited ? columnLimitsOf(fills) : NO_COLUMN_LIMITS), [limited, fills]);
};

/** Which board columns are full, for a list whose tasks come from many
 *  projects and communities. */
export type TaskColumnLimits = {
  /** Whether the column `statusId` of the task's project is too full to
   *  take it. */
  isFull: (task: TaskListRead, statusId: number) => boolean;
  /** The column the server would put the task in, told only `category`,
   *  where that column is full. */
  fullFor: (task: TaskListRead, category: TaskStatusCategory) => TaskStatusRead | undefined;
};

/** No column is full. */
export const NO_TASK_COLUMN_LIMITS: TaskColumnLimits = {
  isFull: () => false,
  fullFor: () => undefined,
};

/** The categories the server tries in turn for a task told only one
 *  (`CATEGORY_FALLBACK` in `task_statuses.py`). */
const CATEGORY_FALLBACK: Record<TaskStatusCategory, readonly TaskStatusCategory[]> = {
  backlog: ["backlog"],
  todo: ["todo", "backlog"],
  in_progress: ["in_progress", "todo", "backlog"],
  done: ["done", "in_progress", "todo", "backlog"],
};

/** The column the server puts a task in when told only `category`: the
 *  project's first of it, or of the next category back. */
const landingStatus = (statuses: readonly TaskStatusRead[], category: TaskStatusCategory) => {
  const ordered = [...statuses].sort((a, b) => a.position - b.position || a.id - b.id);
  for (const each of CATEGORY_FALLBACK[category]) {
    const found = ordered.find((status) => status.category === each);
    if (found) return found;
  }
  return undefined;
};

/** Ids repeat across communities, so one is named with its community. */
const scoped = (communityId: number | null | undefined, id: number) => `${communityId}:${id}`;

const dataOf = <T>(results: { data: T | undefined }[]) => results.map((result) => result.data);

/**
 * How full the board columns of `tasks`' projects are: one ask per
 * community, and the statuses of only the projects that limit a column, for
 * where a task told only a category lands.
 */
export const useTaskColumnLimits = (tasks: readonly TaskListRead[]): TaskColumnLimits => {
  const asks = useMemo(() => {
    const projects = new Map<number, Set<number>>();
    for (const task of tasks) {
      if (task.community_id == null) continue;
      const held = projects.get(task.community_id) ?? new Set<number>();
      projects.set(task.community_id, held.add(task.project_id));
    }
    return [...projects].flatMap(([communityId, held]) => {
      const ids = [...held].sort((a, b) => a - b);
      return Array.from({ length: Math.ceil(ids.length / PROJECTS_PER_ASK) }, (_, at) => ({
        communityId,
        projectIds: ids.slice(at * PROJECTS_PER_ASK, (at + 1) * PROJECTS_PER_ASK),
      }));
    });
  }, [tasks]);
  const fills = useQueries({
    queries: asks.map(({ communityId, projectIds }) =>
      getListColumnLimitsQueryOptions(communityId, { project_id: projectIds })
    ),
    combine: dataOf,
  });
  const limited = useMemo(() => {
    const held = new Map<string, ColumnFillRead & { communityId: number }>();
    asks.forEach(({ communityId }, at) => {
      for (const fill of fills[at] ?? []) {
        held.set(scoped(communityId, fill.status_id), { ...fill, communityId });
      }
    });
    const projects = new Map(
      [...held.values()].map(({ communityId, project_id }) => [
        scoped(communityId, project_id),
        { communityId, projectId: project_id },
      ])
    );
    return { fills: held, projects: [...projects.values()] };
  }, [asks, fills]);
  const statuses = useQueries({
    queries: limited.projects.map(({ communityId, projectId }) =>
      getListTaskStatusesQueryOptions(communityId, projectId)
    ),
    combine: dataOf,
  });
  return useMemo(() => {
    const statusesOf = new Map(
      limited.projects.map(({ communityId, projectId }, at) => [
        scoped(communityId, projectId),
        statuses[at] ?? [],
      ])
    );
    const isFull = (task: TaskListRead, statusId: number) =>
      statusId !== task.task_status_id &&
      overflows(limited.fills.get(scoped(task.community_id, statusId)));
    return {
      isFull,
      fullFor: (task, category) => {
        if (task.task_status.category === category) return undefined;
        const landing = landingStatus(
          statusesOf.get(scoped(task.community_id, task.project_id)) ?? [],
          category
        );
        return landing && isFull(task, landing.id) ? landing : undefined;
      },
    };
  }, [limited, statuses]);
};
