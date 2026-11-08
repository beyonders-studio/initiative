import type { IconName } from "lucide-react/dynamic";
import type { CSSProperties } from "react";

import type { TaskStatusRead } from "@/api/generated/initiativeAPI.schemas";
import { Icon } from "@/ui/icon-picker";
import { cn } from "@/ui/lib/utils";

type StatusLike = Pick<TaskStatusRead, "name" | "icon" | "color">;

interface TaskStatusOptionProps {
  status: StatusLike;
  className?: string;
  iconClassName?: string;
}

export const TaskStatusOption = ({ status, className, iconClassName }: TaskStatusOptionProps) => (
  // `flex!` overrides the `[&>span]:line-clamp-1` rule that shadcn's SelectTrigger
  // applies to direct span children, which would otherwise set `display: -webkit-box`
  // and stack the icon on top of the name.
  <span className={cn("flex! min-w-0 items-center gap-2", className)}>
    <Icon
      name={status.icon as IconName}
      style={{ color: status.color }}
      className={cn("h-3.5 w-3.5 shrink-0", iconClassName)}
    />
    <span className="truncate">{status.name}</span>
  </span>
);

export const statusTriggerStyle = (status: Pick<StatusLike, "color">): CSSProperties => ({
  borderColor: status.color,
});
