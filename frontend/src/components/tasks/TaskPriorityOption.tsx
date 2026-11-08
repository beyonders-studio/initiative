import type { TaskPriority } from "@/api/generated/initiativeAPI.schemas";
import { priorityDotClass } from "@/components/projects/projectTasksConfig";
import { cn } from "@/ui/lib/utils";

interface TaskPriorityOptionProps {
  priority: TaskPriority;
  label: string;
  className?: string;
}

export const TaskPriorityOption = ({ priority, label, className }: TaskPriorityOptionProps) => (
  // `flex!` overrides the `[&>span]:line-clamp-1` rule that shadcn's SelectTrigger
  // applies to direct span children, as in `TaskStatusOption`.
  <span className={cn("flex! min-w-0 items-center gap-2", className)}>
    <span
      aria-hidden="true"
      className={cn("size-2 shrink-0 rounded-full", priorityDotClass[priority])}
    />
    <span className="truncate">{label}</span>
  </span>
);
