import { useTranslation } from "react-i18next";

import type { ChecklistProgress } from "@/api/generated/initiativeAPI.schemas";
import { cn } from "@/ui/lib/utils";
import { Progress } from "@/ui/progress";

type TaskChecklistProgressProps = {
  progress?: ChecklistProgress | null;
  /** What is counted: a task's checklist lines, or the tasks part of it. */
  of?: "checklist" | "subtasks";
  className?: string;
};

export const TaskChecklistProgress = ({
  progress,
  of = "checklist",
  className,
}: TaskChecklistProgressProps) => {
  const { t } = useTranslation("tasks");

  if (!progress || progress.total === 0) {
    return null;
  }

  const ratio = progress.total === 0 ? 0 : Math.round((progress.completed / progress.total) * 100);

  return (
    <div className={cn("space-y-1", className)}>
      <Progress value={ratio} className="h-1.5" aria-label={t(`${of}.progressLabel`)} />
      <p className="font-medium text-2xs text-muted-foreground">
        {t(`${of}.progress`, {
          completed: progress.completed,
          total: progress.total,
          count: progress.total,
        })}
      </p>
    </div>
  );
};
