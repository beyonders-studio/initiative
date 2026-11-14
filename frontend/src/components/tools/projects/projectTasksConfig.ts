import { CalendarDays, FileImage, FileText, Hash, Megaphone } from "lucide-react";

import type { DetailLayoutRead, TaskPriority } from "@/api/generated/initiativeAPI.schemas";
import type { LayoutLook } from "@/ui/layouts/looks";

export type DueFilterOption = "all" | "today" | "7_days" | "30_days" | "overdue";

export type PriorityBadgeVariant = "default" | "secondary" | "warning" | "destructive";

export const priorityVariant: Record<TaskPriority, PriorityBadgeVariant> = {
  low: "secondary",
  medium: "default",
  high: "warning",
  urgent: "destructive",
};

/** The dot beside a priority in a dropdown, in the colour of its badge.
 *  `low`'s badge is a near-background surface, so its dot takes the muted
 *  text colour to stay visible. */
export const priorityDotClass: Record<TaskPriority, string> = {
  low: "bg-muted-foreground",
  medium: "bg-primary",
  high: "bg-warning",
  urgent: "bg-destructive",
};

/** Each detail layout's icon, and its name in `layouts`. */
export const detailLayoutLooks: Record<DetailLayoutRead["kind"], LayoutLook> = {
  task: { icon: FileText, labelKey: "layouts:taskLayout" },
  calendar_event: { icon: CalendarDays, labelKey: "layouts:eventDetail.name" },
  counter: { icon: Hash, labelKey: "layouts:counterDetail.name" },
  post: { icon: Megaphone, labelKey: "layouts:postDetail.name" },
  file: { icon: FileImage, labelKey: "layouts:fileDetail.name" },
};
