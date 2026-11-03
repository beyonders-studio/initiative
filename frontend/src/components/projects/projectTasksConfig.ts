import {
  Calendar,
  CalendarDays,
  ChartGantt,
  Clock,
  FileImage,
  FileText,
  Hash,
  Kanban,
  LayoutGrid,
  ListOrdered,
  type LucideIcon,
  Megaphone,
  Table,
} from "lucide-react";

import type {
  DetailLayoutRead,
  ListLayoutReadKind,
  TaskPriority,
} from "@/api/generated/initiativeAPI.schemas";
import { MasonryIcon } from "@/components/files/collections/MasonryIcon";

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

type Look = { icon: LucideIcon; labelKey: string };

/** Each list layout's icon, and its name, by a key that names its
 *  namespace: a project's lists are in `projects`, a collection's in `files`. */
export const listLayoutLooks: Record<ListLayoutReadKind, Look> = {
  table: { icon: Table, labelKey: "projects:tasks.viewTable" },
  board: { icon: Kanban, labelKey: "projects:tasks.viewBoard" },
  gantt: { icon: ChartGantt, labelKey: "projects:tasks.viewGantt" },
  calendar: { icon: Calendar, labelKey: "projects:tasks.viewCalendar" },
  masonry: { icon: MasonryIcon, labelKey: "files:collections.views.masonry" },
  grid: { icon: LayoutGrid, labelKey: "common:toolbar.viewGrid" },
  timeline: { icon: Clock, labelKey: "files:collections.views.timeline" },
};

/** Each detail layout's icon, and its name in `layouts`. */
export const detailLayoutLooks: Record<DetailLayoutRead["kind"], Look> = {
  task: { icon: FileText, labelKey: "layouts:taskLayout" },
  calendar_event: { icon: CalendarDays, labelKey: "layouts:eventDetail.name" },
  queue_item: { icon: ListOrdered, labelKey: "layouts:queueItemDetail.name" },
  counter: { icon: Hash, labelKey: "layouts:counterDetail.name" },
  post: { icon: Megaphone, labelKey: "layouts:postDetail.name" },
  file: { icon: FileImage, labelKey: "layouts:fileDetail.name" },
};

/** Any layout's icon and name. */
export const layoutLook = (kind: ListLayoutReadKind | DetailLayoutRead["kind"]): Look =>
  kind in listLayoutLooks
    ? listLayoutLooks[kind as ListLayoutReadKind]
    : detailLayoutLooks[kind as DetailLayoutRead["kind"]];
