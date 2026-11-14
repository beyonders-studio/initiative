import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  SearchEntityType,
  type TaskListRead,
  type TaskRead,
} from "@/api/generated/initiativeAPI.schemas";
import { EntityCard } from "@/components/entities/EntityCard";
import { useRelationshipsFor } from "@/hooks/useRelationships";
import { groupOf, RELATION_GROUPS } from "@/lib/relationships";
import { Button } from "@/ui/button";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/ui/hover-card";
import { cn } from "@/ui/lib/utils";

interface TaskSubtasksHoverCardProps {
  task: Pick<TaskListRead | TaskRead, "id" | "subtask_progress">;
  className?: string;
}

const Parts = RELATION_GROUPS.parts.icon;

/**
 * A task's subtasks, where the task is a row in a list: the mark its links
 * give its parts, and how many are done, and on hover what they are.
 *
 * As the blocker mark beside it: nothing is drawn for a task with none, and
 * the list is fetched only once somebody asks for it.
 */
export const TaskSubtasksHoverCard = ({ task, className }: TaskSubtasksHoverCardProps) => {
  const { t } = useTranslation("tasks");
  const [open, setOpen] = useState(false);
  const progress = task.subtask_progress;

  const { data: rows = [] } = useRelationshipsFor(
    { type: SearchEntityType.task, id: task.id },
    { enabled: open }
  );
  const parts = rows.filter(
    (row) =>
      row.other.type === SearchEntityType.task && groupOf(row, [RELATION_GROUPS.parts]) !== null
  );

  if (!progress?.total) return null;
  const label = t("subtasks.progress", {
    completed: progress.completed,
    total: progress.total,
    count: progress.total,
  });

  return (
    <HoverCard open={open} onOpenChange={setOpen}>
      <HoverCardTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={label}>
          <Parts
            className={cn(
              "h-4 w-4 text-muted-foreground",
              progress.completed === progress.total && "text-success",
              className
            )}
          />
        </Button>
      </HoverCardTrigger>
      <HoverCardContent className="w-72" align="start">
        <p className="font-medium text-sm">{label}</p>
        <ul className="mt-2 flex flex-col gap-1.5">
          {parts.map((edge) => (
            <li key={edge.id}>
              <EntityCard variant="compact" end={edge.other} isOpen={edge.other.is_open} />
            </li>
          ))}
        </ul>
      </HoverCardContent>
    </HoverCard>
  );
};
