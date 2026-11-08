import { describe, expect, it } from "vitest";

import { buildTask } from "@/__tests__/factories";
import type { TaskEdgeRead } from "@/api/generated/initiativeAPI.schemas";
import {
  criticalPath,
  DAY,
  draggedDates,
  ganttWindow,
  heldDays,
  scheduledDates,
  spanOf,
  taskRows,
  waitingOn,
  wholesOf,
} from "@/lib/gantt";

const day = (iso: string) => new Date(`${iso}T00:00:00`).getTime();
const at = (iso: string) => new Date(`${iso}T09:30:00`).toISOString();
const partOf = (source_id: number, target_id: number): TaskEdgeRead => ({
  id: source_id * 1000 + target_id,
  source_id,
  target_id,
  relationship_type: "part_of",
});

describe("gantt", () => {
  it("draws a task from its first day to the end of its last, or as one day", () => {
    expect(spanOf({ start_date: at("2026-03-02"), due_date: at("2026-03-04") })).toEqual({
      start: day("2026-03-02"),
      end: day("2026-03-05"),
      kind: "bar",
    });
    expect(spanOf({ start_date: null, due_date: at("2026-03-04") })).toEqual({
      start: day("2026-03-04"),
      end: day("2026-03-05"),
      kind: "due",
    });
    expect(spanOf({ start_date: at("2026-03-02"), due_date: null })?.kind).toBe("start");
    expect(spanOf({ start_date: null, due_date: null })).toBeNull();
  });

  it("covers every task and today, and at least the scale's least", () => {
    const now = day("2026-03-10");
    const window = ganttWindow([{ start: day("2026-01-01"), end: day("2026-01-03") }], "day", now);
    expect(window.start).toBeLessThan(day("2026-01-01"));
    expect(window.end).toBeGreaterThan(now);
    const alone = ganttWindow([], "month", now);
    expect(Math.round((alone.end - alone.start) / DAY)).toBeGreaterThanOrEqual(540);
  });

  it("nests a task's parts under it, folds them, and spans what they cover", () => {
    const whole = buildTask({ start_date: null, due_date: null });
    const first = buildTask({ start_date: at("2026-03-02"), due_date: at("2026-03-03") });
    const second = buildTask({ start_date: null, due_date: at("2026-03-09") });
    const loose = buildTask();
    const tasks = [first, whole, loose, second];
    const wholes = wholesOf(tasks, [partOf(first.id, whole.id), partOf(second.id, whole.id)]);

    const rows = taskRows(tasks, wholes, new Set());
    expect(rows.map((row) => row.type === "task" && [row.task.id, row.depth])).toEqual([
      [whole.id, 0],
      [first.id, 1],
      [second.id, 1],
      [loose.id, 0],
    ]);
    expect(rows[0]).toMatchObject({
      hasParts: true,
      open: true,
      parts: { start: day("2026-03-02"), end: day("2026-03-10") },
    });

    const folded = taskRows(tasks, wholes, new Set([String(whole.id)]));
    expect(folded.map((row) => row.type === "task" && row.task.id)).toEqual([whole.id, loose.id]);
  });

  it("keeps a part under one whole, and a loop of parts at the top", () => {
    const [a, b, c] = [buildTask(), buildTask(), buildTask()];
    const wholes = wholesOf(
      [a, b, c],
      [partOf(a.id, b.id), partOf(b.id, a.id), partOf(a.id, c.id)]
    );
    expect([...wholes]).toEqual([[a.id, b.id]]);
  });

  it("moves the dates a drag holds, and an end no further than the other", () => {
    const task = { start_date: at("2026-03-02"), due_date: at("2026-03-04") };
    const moved = draggedDates(task, "move", 2);
    expect(new Date(moved.start_date as string).getDate()).toBe(4);
    expect(new Date(moved.due_date as string).getHours()).toBe(9);
    expect(Object.keys(draggedDates(task, "end", 1))).toEqual(["due_date"]);

    const span = spanOf(task);
    if (!span) throw new Error("a dated task has a span");
    expect(heldDays(span, "start", 5)).toBe(2);
    expect(heldDays(span, "end", -5)).toBe(-2);
    expect(heldDays(span, "move", -5)).toBe(-5);
  });

  it("schedules a task across the days dragged, either way, in calendar days", () => {
    expect(scheduledDates(day("2026-03-05"), -3)).toEqual({
      start_date: new Date(day("2026-03-02")).toISOString(),
      due_date: new Date(day("2026-03-05")).toISOString(),
    });
    // Across a clock change, the last day is still its own day.
    expect(scheduledDates(day("2026-10-31"), 2).due_date).toBe(
      new Date(day("2026-11-02")).toISOString()
    );
  });

  it("finds what waits on a task through the chain, once each, of the project's", () => {
    const waits = (source_id: number, target_id: number): TaskEdgeRead => ({
      id: source_id * 1000 + target_id,
      source_id,
      target_id,
      relationship_type: "depends_on",
    });
    const edges = [waits(2, 1), waits(3, 2), waits(4, 2), waits(1, 3), waits(9, 1)];
    expect(waitingOn(1, edges, new Set([1, 2, 3, 4])).sort()).toEqual([2, 3, 4]);

    // The chain ending last: 4 ends after 3, and waits on 2, which waits on 1.
    const spans = new Map([
      [1, { end: day("2026-03-03") }],
      [2, { end: day("2026-03-06") }],
      [3, { end: day("2026-03-08") }],
      [4, { end: day("2026-03-10") }],
    ]);
    expect([...criticalPath(spans, edges.slice(0, 3))]).toEqual([4, 2, 1]);
  });
});
