import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { TaskListRead, TaskStatusRead } from "@/api/generated/initiativeAPI.schemas";
import { statusTriggerStyle, TaskStatusOption } from "@/components/tasks/TaskStatusOption";
import { toast } from "@/lib/mascotToast";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/ui/select";

type TaskStatusSelectorProps = {
  task: TaskListRead;
  activeCommunityId: number | null;
  isUpdatingTaskStatus: boolean;
  changeTaskStatusById: (task: TaskListRead, statusId: number) => Promise<void>;
  fetchProjectStatuses: (
    projectId: number,
    communityId: number | null
  ) => Promise<TaskStatusRead[]>;
  projectStatusCache: React.MutableRefObject<
    Map<number, { statuses: TaskStatusRead[]; complete: boolean }>
  >;
  /** Whether a column is too full to take the task; a full one can't be picked. */
  isFull?: (statusId: number) => boolean;
};

const NEVER_FULL = () => false;

export const TaskStatusSelector = ({
  task,
  activeCommunityId,
  isUpdatingTaskStatus,
  changeTaskStatusById,
  fetchProjectStatuses,
  projectStatusCache,
  isFull = NEVER_FULL,
}: TaskStatusSelectorProps) => {
  const { t } = useTranslation(["tasks", "projects"]);
  const [statuses, setStatuses] = useState<TaskStatusRead[]>(() => {
    const cached = projectStatusCache.current.get(task.project_id);
    return cached?.statuses ?? [task.task_status];
  });

  // Re-sync from cache when the task's project or status changes (e.g. after refetch)
  useEffect(() => {
    const cached = projectStatusCache.current.get(task.project_id);
    if (cached) {
      // Ensure the current task_status is present in the cached list
      if (!cached.statuses.some((s) => s.id === task.task_status.id)) {
        cached.statuses.push(task.task_status);
      }
      setStatuses(cached.statuses);
    } else {
      setStatuses([task.task_status]);
    }
  }, [task.project_id, task.task_status, projectStatusCache]);

  const handleOpenChange = useCallback(
    async (open: boolean) => {
      if (open) {
        const communityId = task.community_id ?? activeCommunityId ?? null;
        const fetchedStatuses = await fetchProjectStatuses(task.project_id, communityId);
        setStatuses(fetchedStatuses);
      }
    },
    [task, activeCommunityId, fetchProjectStatuses]
  );

  const sortedStatuses = useMemo(
    () => [...statuses].sort((a, b) => a.position - b.position),
    [statuses]
  );

  return (
    <Select
      value={String(task.task_status.id)}
      onValueChange={(value) => {
        const targetId = Number(value);
        if (Number.isNaN(targetId)) {
          toast.error(t("statusSelector.invalidStatus"));
          return;
        }
        void changeTaskStatusById(task, targetId);
      }}
      onOpenChange={handleOpenChange}
      disabled={isUpdatingTaskStatus}
    >
      <SelectTrigger className="w-40 border-2" style={statusTriggerStyle(task.task_status)}>
        <TaskStatusOption status={task.task_status} />
      </SelectTrigger>
      <SelectContent>
        {sortedStatuses.map((status) => {
          const full = status.id !== task.task_status.id && isFull(status.id);
          return (
            <SelectItem key={status.id} value={String(status.id)} disabled={full}>
              <TaskStatusOption status={status} />
              {full ? (
                <span className="text-muted-foreground text-xs">{t("projects:kanban.full")}</span>
              ) : null}
            </SelectItem>
          );
        })}
      </SelectContent>
    </Select>
  );
};
