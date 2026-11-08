/**
 * A project's tasks on a time axis: where each one's bar sits, the window the
 * axis covers, the rows (a task's parts nested under it), and the dates a drag
 * writes. The Gantt view draws from these; none of them reads the DOM.
 *
 * Days are local days, as the calendar arithmetic in `timelineAxis` counts
 * them: a task due on the 3rd fills the 3rd.
 */

import type {
  LinkedTaskRead,
  TaskEdgeRead,
  TaskListRead,
  TaskUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { addUnits, floorToUnit, type TimelineRange } from "@/lib/widgets/timelineAxis";

export const DAY = 86_400_000;

/** How much of the calendar one screen of the Gantt shows. */
export type GanttScale = "day" | "week" | "month";
export const GANTT_SCALES: readonly GanttScale[] = ["day", "week", "month"];
export const isGanttScale = (value: unknown): value is GanttScale =>
  GANTT_SCALES.includes(value as GanttScale);

/** How wide a day is at each scale. */
export const PX_PER_DAY: Record<GanttScale, number> = { day: 36, week: 14, month: 4 };

/** What the window keeps beyond the first and last dates, and the least it
 *  covers, so a project with one task still scrolls. */
const PADDING: Record<GanttScale, { before: number; after: number; least: number }> = {
  day: { before: 7, after: 21, least: 42 },
  week: { before: 14, after: 56, least: 120 },
  month: { before: 31, after: 92, least: 540 },
};

/** A task on the axis: from its first day to the day after its last. A task
 *  with one date is that day, a `start` or a `due` marker. */
export type GanttSpan = { start: number; end: number; kind: "bar" | "start" | "due" };

const dayOf = (iso: string) => floorToUnit(Date.parse(iso), "day");

export const spanOf = (task: Pick<TaskListRead, "start_date" | "due_date">): GanttSpan | null => {
  const start = task.start_date ? dayOf(task.start_date) : null;
  const due = task.due_date ? dayOf(task.due_date) : null;
  if (start !== null && due !== null) {
    const [first, last] = start <= due ? [start, due] : [due, start];
    return { start: first, end: addUnits(last, "day", 1), kind: "bar" };
  }
  const only = due ?? start;
  if (only === null) return null;
  return { start: only, end: addUnits(only, "day", 1), kind: due !== null ? "due" : "start" };
};

/** How many whole days a span covers. */
export const daysIn = (span: Pick<GanttSpan, "start" | "end">) =>
  Math.round((span.end - span.start) / DAY);

/** The window the axis covers: every span and today, with room either side,
 *  from a day's start. */
export const ganttWindow = (
  spans: readonly Pick<GanttSpan, "start" | "end">[],
  scale: GanttScale,
  now: number
): TimelineRange => {
  const today = floorToUnit(now, "day");
  let low = today;
  let high = addUnits(today, "day", 1);
  for (const span of spans) {
    low = Math.min(low, span.start);
    high = Math.max(high, span.end);
  }
  const { before, after, least } = PADDING[scale];
  const start = addUnits(low, "day", -before);
  const end = addUnits(high, "day", after);
  return { start, end: Math.max(end, addUnits(start, "day", least)) };
};

/** One row of the Gantt: a group's heading, a task, or another project's
 *  task one of them is linked to. */
export type GanttRow =
  | { type: "group"; key: string; count: number; label?: string }
  | { type: "outside"; key: string; task: LinkedTaskRead }
  | {
      type: "task";
      /** Unique across the rows: a task in two groups has a row in each. */
      key: string;
      task: TaskListRead;
      depth: number;
      /** Whether its parts are listed under it, and they are showing. */
      hasParts: boolean;
      open: boolean;
      /** What its parts cover, together; null where none is dated. */
      parts: Pick<GanttSpan, "start" | "end"> | null;
    };

/** The task each task is part of, among `tasks`: its first `part_of` edge to
 *  one of them that does not lead back to itself. */
export const wholesOf = (
  tasks: readonly TaskListRead[],
  edges: readonly TaskEdgeRead[]
): Map<number, number> => {
  const ids = new Set(tasks.map((task) => task.id));
  const wholes = new Map<number, number>();
  for (const edge of edges) {
    if (edge.relationship_type !== "part_of") continue;
    if (!ids.has(edge.source_id) || !ids.has(edge.target_id) || wholes.has(edge.source_id)) {
      continue;
    }
    let up: number | undefined = edge.target_id;
    while (up !== undefined && up !== edge.source_id) up = wholes.get(up);
    if (up === undefined) wholes.set(edge.source_id, edge.target_id);
  }
  return wholes;
};

/** `tasks` as rows, in their order, each task's parts under it unless it is
 *  folded (`folded` holds row keys). `prefix` keeps the keys of one group's
 *  rows apart from another's. */
export const taskRows = (
  tasks: readonly TaskListRead[],
  wholes: ReadonlyMap<number, number>,
  folded: ReadonlySet<string>,
  prefix = ""
): GanttRow[] => {
  const shown = new Set(tasks.map((task) => task.id));
  const parts = new Map<number, TaskListRead[]>();
  for (const task of tasks) {
    const whole = wholes.get(task.id);
    if (whole === undefined || !shown.has(whole)) continue;
    parts.set(whole, [...(parts.get(whole) ?? []), task]);
  }
  const extent = (task: TaskListRead): Pick<GanttSpan, "start" | "end"> | null => {
    let found: Pick<GanttSpan, "start" | "end"> | null = null;
    for (const part of parts.get(task.id) ?? []) {
      for (const span of [spanOf(part), extent(part)]) {
        if (!span) continue;
        found = found
          ? { start: Math.min(found.start, span.start), end: Math.max(found.end, span.end) }
          : { start: span.start, end: span.end };
      }
    }
    return found;
  };
  const rows: GanttRow[] = [];
  const visit = (task: TaskListRead, depth: number) => {
    const key = `${prefix}${task.id}`;
    const own = parts.get(task.id) ?? [];
    const open = !folded.has(key);
    rows.push({
      type: "task",
      key,
      task,
      depth,
      hasParts: own.length > 0,
      open,
      parts: own.length > 0 ? extent(task) : null,
    });
    if (open) for (const part of own) visit(part, depth + 1);
  };
  for (const task of tasks) {
    const whole = wholes.get(task.id);
    if (whole === undefined || !shown.has(whole)) visit(task, 0);
  }
  return rows;
};

/** Which end of a bar a drag holds: the whole bar, its start or its end. */
export type DragHold = "move" | "start" | "end";

const shifted = (iso: string, days: number) => {
  const date = new Date(iso);
  date.setDate(date.getDate() + days);
  return date.toISOString();
};

/** How far a drag of `days` may go: an end does not pass the other end. */
export const heldDays = (span: GanttSpan, hold: DragHold, days: number) => {
  const room = daysIn(span) - 1;
  if (hold === "start") return Math.min(days, room);
  if (hold === "end") return Math.max(days, -room);
  return days;
};

/** What a drag `days` along writes: each date it holds moved by as many days,
 *  at the time of day it had. */
export const draggedDates = (
  task: Pick<TaskListRead, "start_date" | "due_date">,
  hold: DragHold,
  days: number
): Pick<TaskUpdate, "start_date" | "due_date"> => {
  const dates: Pick<TaskUpdate, "start_date" | "due_date"> = {};
  if (task.start_date && hold !== "end") dates.start_date = shifted(task.start_date, days);
  if (task.due_date && hold !== "start") dates.due_date = shifted(task.due_date, days);
  return dates;
};

/** The days a drag across an empty track covers, from the day it began on
 *  (a day's start) and `days` along, counted in calendar days. */
export const draggedAcross = (from: number, days: number): Pick<GanttSpan, "start" | "end"> => {
  const to = addUnits(from, "day", days);
  return { start: Math.min(from, to), end: addUnits(Math.max(from, to), "day", 1) };
};

/** The dates a task with none gets from such a drag: it starts on the first
 *  day and is due on the last. */
export const scheduledDates = (from: number, days: number) => {
  const { start, end } = draggedAcross(from, days);
  return {
    start_date: new Date(start).toISOString(),
    due_date: new Date(addUnits(end, "day", -1)).toISOString(),
  };
};

/** The tasks waiting on `taskId`, directly or through others, of `ids`:
 *  each that depends on it, and each that depends on one of those. */
export const waitingOn = (
  taskId: number,
  edges: readonly TaskEdgeRead[],
  ids: ReadonlySet<number>
): number[] => {
  const waits = new Map<number, number[]>();
  for (const edge of edges) {
    if (edge.relationship_type !== "depends_on" || !ids.has(edge.source_id)) continue;
    waits.set(edge.target_id, [...(waits.get(edge.target_id) ?? []), edge.source_id]);
  }
  const found = new Set<number>();
  const visit = (id: number) => {
    for (const next of waits.get(id) ?? []) {
      if (next === taskId || found.has(next)) continue;
      found.add(next);
      visit(next);
    }
  };
  visit(taskId);
  return [...found];
};

/** The chain that decides when the work ends: the task that ends last, the
 *  blocker of it that ends last, and so on back, of those drawn with dates. */
export const criticalPath = (
  spans: ReadonlyMap<number, Pick<GanttSpan, "end">>,
  edges: readonly TaskEdgeRead[]
): Set<number> => {
  const blockers = new Map<number, number[]>();
  for (const edge of edges) {
    if (edge.relationship_type !== "depends_on") continue;
    if (!spans.has(edge.source_id) || !spans.has(edge.target_id)) continue;
    blockers.set(edge.source_id, [...(blockers.get(edge.source_id) ?? []), edge.target_id]);
  }
  const endOf = (id: number) => spans.get(id)?.end ?? Number.NEGATIVE_INFINITY;
  const latest = (ids: Iterable<number>) =>
    [...ids].reduce<number | undefined>(
      (best, id) => (best === undefined || endOf(id) > endOf(best) ? id : best),
      undefined
    );
  const path = new Set<number>();
  let at = latest(spans.keys());
  while (at !== undefined && !path.has(at)) {
    path.add(at);
    at = latest(blockers.get(at) ?? []);
  }
  return path;
};
