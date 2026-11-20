import { describe, expect, it } from "vitest";

import { buildTag, buildTaskType } from "@/__tests__/factories";
import { buildTask, buildTaskAssignee } from "@/__tests__/factories/task.factory";

import { buildTaskCalendarEntries, buildTaskOccurrenceEntries } from "./taskCalendarEntries";

// Local-time ISO strings (no trailing "Z") so parseISO / isSameDay don't shift
// the day across timezones in CI.
const COLOR = "#3b82f6";

describe("buildTaskCalendarEntries", () => {
  it("carries the task's type to draw by its title, in a project with several", () => {
    const type = buildTaskType({ name: "Bug", icon: "bug" });
    const task = buildTask({
      start_date: "2026-01-15T00:00:00",
      due_date: "2026-01-20T00:00:00",
      task_type_id: type.id,
      task_type: type,
    });

    const typed = buildTaskCalendarEntries(task, COLOR, true, { typed: true });
    expect(typed.map((entry) => entry.taskType)).toEqual([type, type]);
    expect(buildTaskCalendarEntries(task, COLOR).map((entry) => entry.taskType)).toEqual([
      null,
      null,
    ]);
  });

  it("renders one timed span for same-day start & due with real times", () => {
    const task = buildTask({
      id: 7,
      start_date: "2026-01-15T09:00:00",
      due_date: "2026-01-15T17:00:00",
    });

    const entries = buildTaskCalendarEntries(task, COLOR);

    expect(entries).toHaveLength(1);
    const [entry] = entries;
    expect(entry.id).toBe("task-7");
    expect(entry.allDay).toBe(false);
    expect(entry.startAt).toBe("2026-01-15T09:00:00");
    expect(entry.endAt).toBe("2026-01-15T17:00:00");
    expect(entry.kind).toBeUndefined();
    expect(entry.meta).toMatchObject({ type: "task", taskId: 7, kind: "span" });
  });

  it("renders one all-day entry when same-day start & due are both midnight", () => {
    const task = buildTask({
      id: 8,
      start_date: "2026-01-15T00:00:00",
      due_date: "2026-01-15T00:00:00",
    });

    const entries = buildTaskCalendarEntries(task, COLOR);

    expect(entries).toHaveLength(1);
    expect(entries[0].allDay).toBe(true);
    expect(entries[0].meta).toMatchObject({ kind: "span" });
  });

  it("renders two labeled markers when start & due fall on different days", () => {
    const task = buildTask({
      id: 9,
      start_date: "2026-01-15T09:00:00",
      due_date: "2026-01-18T17:00:00",
    });

    const entries = buildTaskCalendarEntries(task, COLOR);

    expect(entries).toHaveLength(2);
    const start = entries.find((e) => e.kind === "start");
    const due = entries.find((e) => e.kind === "due");
    expect(start?.id).toBe("task-9-start");
    expect(start?.allDay).toBe(true);
    expect(start?.startAt).toBe("2026-01-15T09:00:00");
    expect(start?.meta).toMatchObject({ type: "task", taskId: 9, kind: "start" });
    expect(due?.id).toBe("task-9-due");
    expect(due?.startAt).toBe("2026-01-18T17:00:00");
    expect(due?.meta).toMatchObject({ type: "task", taskId: 9, kind: "due" });
  });

  it("keeps each marker on its own day rather than spanning start → due", () => {
    // Load-bearing for the calendar's fetch: EventsPage windows tasks on
    // "start_date OR due_date in the visible range", which is only complete
    // because a task occupies those two days and nothing in between. A task
    // straddling the whole window renders nothing inside it, so fetching it
    // would be pointless. If tasks ever render as a bar across the two dates,
    // that window has to widen to match — or spanning tasks vanish.
    const task = buildTask({
      id: 11,
      start_date: "2026-01-15T09:00:00",
      due_date: "2026-03-20T17:00:00",
    });

    const entries = buildTaskCalendarEntries(task, COLOR);

    expect(entries).toHaveLength(2);
    for (const entry of entries) {
      expect(entry.startAt).toBe(entry.endAt);
    }
  });

  it.each([
    ["2026-01-15T09:00:00", undefined, ["start"]],
    [undefined, "2026-01-15T17:00:00", ["due"]],
    [undefined, undefined, []],
  ])("renders a marker for each date set (start %s, due %s)", (start_date, due_date, kinds) => {
    const task = buildTask({ id: 10, start_date, due_date });
    const entries = buildTaskCalendarEntries(task, COLOR);
    expect(entries.map((entry) => entry.kind)).toEqual(kinds);
    expect(entries.map((entry) => (entry.meta as { kind: string }).kind)).toEqual(kinds);
  });

  it("propagates the draggable flag onto entries (defaults to true)", () => {
    const task = buildTask({
      id: 14,
      start_date: "2026-01-15T09:00:00",
      due_date: "2026-01-18T17:00:00",
    });
    expect(buildTaskCalendarEntries(task, COLOR).every((e) => e.draggable === true)).toBe(true);
    expect(buildTaskCalendarEntries(task, COLOR, false).every((e) => e.draggable === false)).toBe(
      true
    );
  });

  it("propagates color, tags, and assignees onto entries", () => {
    const tag = buildTag({ name: "urgent" });
    const task = buildTask({
      id: 13,
      start_date: "2026-01-15T09:00:00",
      tags: [tag],
      assignees: [buildTaskAssignee({ id: 42, display_name: "Alice" })],
    });

    const [entry] = buildTaskCalendarEntries(task, COLOR);

    expect(entry.color).toBe(COLOR);
    expect(entry.tags).toEqual([tag]);
    expect(entry.attendees).toEqual([{ name: "Alice", avatarUrl: null, userId: 42 }]);
  });

  it("keeps an occurrence apart from the task and still", () => {
    const task = buildTask({ id: 15, start_date: undefined, due_date: "2026-01-15T17:00:00" });
    const next = { ...task, due_date: "2026-01-22T17:00:00" };
    const [current] = buildTaskCalendarEntries(task, COLOR);
    const [occurrence] = buildTaskOccurrenceEntries(next, COLOR);
    expect(occurrence.id).not.toBe(current.id);
    expect(occurrence).toMatchObject({
      startAt: "2026-01-22T17:00:00",
      draggable: false,
      meta: { taskId: 15 },
    });
  });
});
