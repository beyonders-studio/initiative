import type { IconName } from "lucide-react/dynamic";

import type { TaskTypeRead } from "@/api/generated/initiativeAPI.schemas";
import { Icon } from "@/ui/icon-picker";
import { cn } from "@/ui/lib/utils";

type TypeLike = Pick<TaskTypeRead, "name" | "icon" | "color">;

/** A task type's icon, in its colour, or in the text's where it sits on a
 *  colour of its own (`tinted={false}`). */
export const TaskTypeIcon = ({
  type,
  className,
  tinted = true,
}: {
  type: TypeLike;
  className?: string;
  tinted?: boolean;
}) => (
  <Icon
    name={type.icon as IconName}
    style={tinted ? { color: type.color } : undefined}
    className={cn("h-3.5 w-3.5 shrink-0", className)}
    aria-hidden
  />
);

/** A task type by its icon alone, named on hover and to a screen reader: what
 *  sits beside a task's title. */
export const TaskTypeMark = ({
  type,
  className,
  iconClassName,
  tinted,
}: {
  type: TypeLike;
  className?: string;
  iconClassName?: string;
  tinted?: boolean;
}) => (
  <span className={cn("inline-flex shrink-0 items-center", className)} title={type.name}>
    <TaskTypeIcon type={type} className={iconClassName} tinted={tinted} />
    <span className="sr-only">{type.name}</span>
  </span>
);

/** A task type as a picker lists it: its icon, then its name. */
export const TaskTypeOption = ({
  type,
  className,
  iconClassName,
}: {
  type: TypeLike;
  className?: string;
  iconClassName?: string;
}) => (
  // `flex!` overrides SelectTrigger's `[&>span]:line-clamp-1`, as on a status.
  <span className={cn("flex! min-w-0 items-center gap-2", className)}>
    <TaskTypeIcon type={type} className={iconClassName} />
    <span className="truncate">{type.name}</span>
  </span>
);
