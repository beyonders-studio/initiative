import {
  Calendar,
  ChartGantt,
  Clock,
  Kanban,
  LayoutGrid,
  type LucideIcon,
  Table,
} from "lucide-react";

import type { ListLayoutReadKind } from "@/api/generated/initiativeAPI.schemas";

import { MasonryIcon } from "./MasonryIcon";

/** A layout's icon, and its name, by a key that names its namespace. */
export type LayoutLook = { icon: LucideIcon; labelKey: string };

/** Each list layout's icon and name. */
export const listLayoutLooks: Record<ListLayoutReadKind, LayoutLook> = {
  table: { icon: Table, labelKey: "projects:tasks.viewTable" },
  board: { icon: Kanban, labelKey: "projects:tasks.viewBoard" },
  gantt: { icon: ChartGantt, labelKey: "projects:tasks.viewGantt" },
  calendar: { icon: Calendar, labelKey: "projects:tasks.viewCalendar" },
  masonry: { icon: MasonryIcon, labelKey: "files:collections.views.masonry" },
  grid: { icon: LayoutGrid, labelKey: "common:toolbar.viewGrid" },
  timeline: { icon: Clock, labelKey: "files:collections.views.timeline" },
};
