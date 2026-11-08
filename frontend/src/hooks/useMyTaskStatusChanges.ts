/**
 * Changing the status of a task in a cross-community list (`/me/tasks`): the
 * tasks table's rows, the focus card's checkboxes.
 *
 * Kept apart from the table so a widget that only checks tasks off does not
 * also load the table's page of rows.
 */

import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";

import type {
  TaskListRead,
  TaskListResponse,
  TaskStatusCategory,
  TaskStatusRead,
  TaskUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { listTaskStatuses } from "@/api/generated/task-statuses/task-statuses";
import { getListMyTasksQueryKey } from "@/api/generated/tasks/tasks";
import { useCommunities } from "@/hooks/useCommunities";
import { useUpdateTaskInCommunity } from "@/hooks/useTasks";
import { toast } from "@/lib/mascotToast";

/**
 * Prefix shared by every `/me/tasks` cache entry — the table's page, the focus
 * summary's rule and pin queries. A status change patches all of them at once,
 * so the row it touched updates wherever it is on screen without waiting for
 * three cross-community aggregates to come back.
 */
const MY_TASKS_QUERY_PREFIX = getListMyTasksQueryKey();

/** Task ids repeat across communities, so an in-flight row is addressed by both. */
const taskKey = (task: Pick<TaskListRead, "id" | "community_id">) =>
  `${task.community_id ?? "none"}:${task.id}`;

/**
 * Which tasks have a status change in flight, shared by every list that can
 * change one — the tasks table and the focus card are separate widgets, and
 * the same task can sit in both. One change at a time per task, wherever it
 * was started: a second could land in either order, and a failure rolling
 * back would undo the other one's save.
 *
 * Held per query client, beside the cache those changes write to.
 */
interface InFlight {
  keys: Set<string>;
  version: number;
  listeners: Set<() => void>;
}

const inFlightByClient = new WeakMap<QueryClient, InFlight>();

const inFlightFor = (client: QueryClient): InFlight => {
  let held = inFlightByClient.get(client);
  if (!held) {
    held = { keys: new Set(), version: 0, listeners: new Set() };
    inFlightByClient.set(client, held);
  }
  return held;
};

const notify = (held: InFlight) => {
  held.version += 1;
  for (const listener of held.listeners) listener();
};

export function useMyTaskStatusChanges() {
  const { t } = useTranslation(["tasks", "common"]);
  const { activeCommunityId } = useCommunities();
  const localQueryClient = useQueryClient();
  const projectStatusCache = useRef<Map<number, { statuses: TaskStatusRead[]; complete: boolean }>>(
    new Map()
  );

  // --- Status mutation ---
  const { mutateAsync: updateTaskStatusMutate } = useUpdateTaskInCommunity({
    onSuccess: (updatedTask) => {
      const cached = projectStatusCache.current.get(updatedTask.project_id);
      if (cached && !cached.statuses.some((status) => status.id === updatedTask.task_status.id)) {
        cached.statuses.push(updatedTask.task_status);
      }
    },
  });

  // Which rows have a status change in flight. Per task rather than one flag for
  // the mutation, because the shared `isPending` disabled every row on the page
  // — and the focus summary's rows with them — while a single checkbox was
  // saving.
  // Re-rendered whenever any list starts or finishes a change; the answer is
  // read off the shared set, so every list agrees on which rows are saving.
  const inFlight = inFlightFor(localQueryClient);
  const subscribe = useCallback(
    (listener: () => void) => {
      inFlight.listeners.add(listener);
      return () => inFlight.listeners.delete(listener);
    },
    [inFlight]
  );
  const snapshot = useCallback(() => inFlight.version, [inFlight]);
  const inFlightVersion = useSyncExternalStore(subscribe, snapshot, snapshot);
  const isUpdatingTask = useCallback(
    (task: Pick<TaskListRead, "id" | "community_id">) => {
      void inFlightVersion;
      return inFlight.keys.has(taskKey(task));
    },
    [inFlight, inFlightVersion]
  );

  /**
   * Rewrite one row's status in every `/me/tasks` page the cache holds.
   *
   * Only that row is touched — not a snapshot of the whole page — so two rows
   * changed at once don't undo each other when one of them fails.
   */
  const writeStatusToCache = useCallback(
    (task: Pick<TaskListRead, "id" | "community_id">, status: TaskStatusRead) => {
      const key = taskKey(task);
      localQueryClient.setQueriesData<TaskListResponse>(
        { queryKey: MY_TASKS_QUERY_PREFIX },
        (old) => {
          if (!old?.items?.some((item) => taskKey(item) === key)) return old;
          return {
            ...old,
            items: old.items.map((item) =>
              taskKey(item) === key
                ? { ...item, task_status_id: status.id, task_status: status }
                : item
            ),
          };
        }
      );
    },
    [localQueryClient]
  );

  /**
   * Show the new status now, and hand back the undo.
   *
   * The check lands the moment it is clicked instead of after the refetch the
   * mutation's invalidation kicks off. A task that has just moved out of the
   * filtered set stays put until that refetch drops it, which reads as
   * completing work rather than as the row vanishing mid-click.
   */
  const applyStatusLocally = useCallback(
    (task: TaskListRead, status: TaskStatusRead) => {
      const previous = task.task_status;
      writeStatusToCache(task, status);
      return () => writeStatusToCache(task, previous);
    },
    [writeStatusToCache]
  );

  /** Note the statuses rows arrived in, so a change can show at once in a
   *  column the project is already known to have. */
  const rememberStatuses = useCallback((tasks: readonly TaskListRead[]) => {
    for (const task of tasks) {
      const cached = projectStatusCache.current.get(task.project_id);
      if (cached) {
        if (!cached.statuses.some((status) => status.id === task.task_status.id)) {
          cached.statuses.push(task.task_status);
        }
      } else {
        projectStatusCache.current.set(task.project_id, {
          statuses: [task.task_status],
          complete: false,
        });
      }
    }
  }, []);

  // --- Status helpers ---
  const fetchProjectStatuses = useCallback(
    async (projectId: number, communityId: number | null) => {
      const cached = projectStatusCache.current.get(projectId);
      if (cached?.complete) {
        return cached.statuses;
      }
      if (!communityId) {
        return cached?.statuses ?? [];
      }
      // Explicit community address: the project lives in the task's community, which
      // need not be the user's current context on these cross-community pages.
      const statuses = await listTaskStatuses(communityId, projectId);
      const merged = cached
        ? [
            ...cached.statuses,
            ...statuses.filter((status) => !cached.statuses.some((s) => s.id === status.id)),
          ]
        : statuses;
      projectStatusCache.current.set(projectId, { statuses: merged, complete: true });
      return merged;
    },
    []
  );

  /** Move a row: shown in its new status at once where that status is known,
   *  and written either way. */
  const moveTask = useCallback(
    async (task: TaskListRead, data: TaskUpdate, target: TaskStatusRead | undefined) => {
      const targetCommunityId = task.community_id ?? activeCommunityId ?? null;
      if (!targetCommunityId) {
        toast.error(t("errors.communityContext"));
        return;
      }
      const key = taskKey(task);
      // Another list is already saving this task: that change stands.
      if (inFlight.keys.has(key)) return;
      inFlight.keys.add(key);
      notify(inFlight);
      const rollback = target ? applyStatusLocally(task, target) : null;
      try {
        await updateTaskStatusMutate({
          taskId: task.id,
          data,
          // Cross-community update from the personal My Tasks table: per-community task
          // ids collide, so the update must name the task's own community (path).
          communityId: targetCommunityId,
        });
      } catch (error) {
        rollback?.();
        console.error(error);
      } finally {
        inFlight.keys.delete(key);
        notify(inFlight);
      }
    },
    [activeCommunityId, applyStatusLocally, inFlight, updateTaskStatusMutate, t]
  );

  const cachedStatuses = useCallback(
    (task: TaskListRead) => projectStatusCache.current.get(task.project_id)?.statuses ?? [],
    []
  );

  const changeTaskStatusById = useCallback(
    (task: TaskListRead, targetStatusId: number) =>
      moveTask(
        task,
        { task_status_id: targetStatusId },
        cachedStatuses(task).find((status) => status.id === targetStatusId)
      ),
    [moveTask, cachedStatuses]
  );

  // The project's column for the category is the server's to pick. The row
  // moves ahead of it into a known column of that category, or into its own
  // marked with the category until the answer names the column.
  const changeTaskStatus = useCallback(
    (task: TaskListRead, targetCategory: TaskStatusCategory) =>
      moveTask(
        task,
        { status_category: targetCategory },
        cachedStatuses(task).find((status) => status.category === targetCategory) ?? {
          ...task.task_status,
          category: targetCategory,
        }
      ),
    [moveTask, cachedStatuses]
  );

  return {
    changeTaskStatus,
    changeTaskStatusById,
    fetchProjectStatuses,
    projectStatusCache,
    isUpdatingTask,
    rememberStatuses,
  };
}
