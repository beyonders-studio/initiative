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

/** Each list layout's icon and name, in `layouts`. */
export const listLayoutLooks: Record<ListLayoutReadKind, LayoutLook> = {
  table: { icon: Table, labelKey: "layouts:lists.table" },
  board: { icon: Kanban, labelKey: "layouts:lists.board" },
  gantt: { icon: ChartGantt, labelKey: "layouts:lists.gantt" },
  calendar: { icon: Calendar, labelKey: "layouts:lists.calendar" },
  masonry: { icon: MasonryIcon, labelKey: "layouts:lists.masonry" },
  grid: { icon: LayoutGrid, labelKey: "layouts:lists.grid" },
  timeline: { icon: Clock, labelKey: "layouts:lists.timeline" },
};
