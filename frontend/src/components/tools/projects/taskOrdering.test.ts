import type { DragEndEvent, DragOverEvent } from "@dnd-kit/core";
import { describe, expect, it } from "vitest";

import {
  computeMidpoint,
  isDraggingDown,
  reorderTaskList,
  resolveKanbanDropTarget,
  shouldInsertAfter,
} from "./taskOrdering";

describe("computeMidpoint", () => {
  it("returns the midpoint between two neighbors", () => {
    const tasks = [{ position: 1 }, { position: 2 }];
    // Insert at index 1 -> between position 1 and 2.
    expect(computeMidpoint(tasks, 1)).toBe(1.5);
  });

  it("returns one less than the first task when inserting at the top", () => {
    const tasks = [{ position: 5 }, { position: 6 }];
    expect(computeMidpoint(tasks, 0)).toBe(4);
  });

  it("returns one more than the last task when inserting at the bottom", () => {
    const tasks = [{ position: 1 }, { position: 2 }];
    expect(computeMidpoint(tasks, 2)).toBe(3);
  });

  it("returns 0 for an empty list", () => {
    expect(computeMidpoint([], 0)).toBe(0);
  });

  it("produces a fractional value between fractional neighbors", () => {
    const tasks = [{ position: 1.5 }, { position: 1.75 }];
    expect(computeMidpoint(tasks, 1)).toBe(1.625);
  });

  it("clamps precision to 10 decimal places", () => {
    const tasks = [{ position: 1 }, { position: 1.0000000001 }];
    const result = computeMidpoint(tasks, 1);
    // (1 + 1.0000000001) / 2 = 1.00000000005, rounded to 10 dp.
    expect(result).toBe(Number((1.00000000005).toFixed(10)));
  });
});

describe("resolveKanbanDropTarget", () => {
  const rect = { top: 0, height: 40 };
  // A collision entry as dnd-kit builds it: the winning droppable's container,
  // whose data/rect are live refs.
  const collision = (id: string, data: { type: string; statusId: number }) => ({
    id,
    data: {
      droppableContainer: { id, data: { current: data }, rect: { current: rect } },
      value: 0,
    },
  });
  // dnd-kit's `over`, which only refreshes when the winning id changes.
  const over = (id: string, data: { type: string; statusId: number }) =>
    ({ id, rect, disabled: false, data: { current: data } }) as unknown as DragOverEvent["over"];
  const event = (partial: Partial<DragEndEvent>) => partial as DragEndEvent;

  it("uses the collision under the pointer when over went stale", () => {
    // The card the pointer crossed on its way into the Done column, kept by the
    // caller as the last non-null `over`.
    const stale = over("7", { type: "task", statusId: 1 });
    const result = resolveKanbanDropTarget(
      event({ over: null, collisions: [collision("42", { type: "task", statusId: 2 })] }),
      stale
    );
    expect(result?.data?.statusId).toBe(2);
    expect(result?.id).toBe("42");
  });

  it("resolves to the column when the pointer is on empty column body", () => {
    const result = resolveKanbanDropTarget(
      event({ over: null, collisions: [collision("column-2", { type: "column", statusId: 2 })] }),
      null
    );
    expect(result?.data).toEqual({ type: "column", statusId: 2 });
  });

  it("falls back to over when collision detection came up empty", () => {
    const result = resolveKanbanDropTarget(
      event({ over: over("9", { type: "task", statusId: 3 }), collisions: [] }),
      null
    );
    expect(result?.data?.statusId).toBe(3);
  });

  it("falls back to the last over when the drop has neither", () => {
    const result = resolveKanbanDropTarget(
      event({ over: null, collisions: null }),
      over("9", { type: "task", statusId: 3 })
    );
    expect(result?.data?.statusId).toBe(3);
  });

  it("returns null when there is nothing to drop onto", () => {
    expect(resolveKanbanDropTarget(event({ over: null, collisions: null }), null)).toBeNull();
  });
});

describe("shouldInsertAfter", () => {
  it("returns true when the dragged card's center is below the target's", () => {
    const active = { top: 100, height: 40 }; // center 120
    const over = { top: 90, height: 40 }; // center 110
    expect(shouldInsertAfter(active, over)).toBe(true);
  });

  it("returns false when the dragged card's center is above the target's", () => {
    const active = { top: 80, height: 40 }; // center 100
    const over = { top: 100, height: 40 }; // center 120
    expect(shouldInsertAfter(active, over)).toBe(false);
  });

  it("defaults to false (insert before) when a rect is missing", () => {
    expect(shouldInsertAfter(null, { top: 0, height: 40 })).toBe(false);
    expect(shouldInsertAfter({ top: 0, height: 40 }, undefined)).toBe(false);
  });
});

describe("isDraggingDown", () => {
  const tasks = [{ id: 1 }, { id: 2 }, { id: 3 }];

  it("is true when the active card sits above the target (drag down)", () => {
    // Drag the top card (1) onto the second (2): should land after it.
    expect(isDraggingDown(tasks, 1, 2)).toBe(true);
  });

  it("is false when the active card sits below the target (drag up to top)", () => {
    // Drag the bottom card (3) onto the top card (1): should land before it,
    // i.e. reach the first slot — this is the regression that snapped to second.
    expect(isDraggingDown(tasks, 3, 1)).toBe(false);
  });

  it("is false when there is no target card", () => {
    expect(isDraggingDown(tasks, 1, null)).toBe(false);
  });

  it("is false when a card is not in the list", () => {
    expect(isDraggingDown(tasks, 99, 1)).toBe(false);
    expect(isDraggingDown(tasks, 1, 99)).toBe(false);
  });
});

describe("reorderTaskList", () => {
  // A simple project: two statuses (1 = Todo, 2 = Done), global order by index.
  const todo = (id: number) => ({ id, task_status_id: 1 });
  const done = (id: number) => ({ id, task_status_id: 2 });
  const ids = <T extends { id: number }>(tasks: T[]) => tasks.map((t) => t.id);

  it("moves the top card below the second when dropped after it", () => {
    const base = [todo(1), todo(2), todo(3)];
    const result = reorderTaskList(base, todo(1), 2, true, 1);
    expect(ids(result)).toEqual([2, 1, 3]);
  });

  it("keeps the card before the target when dropped above it", () => {
    const base = [todo(1), todo(2), todo(3)];
    const result = reorderTaskList(base, todo(3), 1, false, 1);
    expect(ids(result)).toEqual([3, 1, 2]);
  });

  it("reaches the first slot of another column when dropped above its first card", () => {
    const base = [todo(1), done(2), done(3)];
    // Move task 1 into the Done column, above its first card (2).
    const moved = { id: 1, task_status_id: 2 };
    const result = reorderTaskList(base, moved, 2, false, 2);
    expect(ids(result)).toEqual([1, 2, 3]);
    expect(result.find((t) => t.id === 1)?.task_status_id).toBe(2);
  });

  it("reaches the second slot of another column when dropped below its first card", () => {
    const base = [todo(1), done(2), done(3)];
    const moved = { id: 1, task_status_id: 2 };
    const result = reorderTaskList(base, moved, 2, true, 2);
    expect(ids(result)).toEqual([2, 1, 3]);
  });

  it("appends to the end of the target column when dropped on empty body", () => {
    const base = [todo(1), todo(2), done(3)];
    // Move task 1 into Done with no specific target card.
    const moved = { id: 1, task_status_id: 2 };
    const result = reorderTaskList(base, moved, null, false, 2);
    // Inserted right after the last Done card (3).
    expect(ids(result)).toEqual([2, 3, 1]);
  });

  it("appends as the first card when the target column is empty", () => {
    const base = [todo(1), todo(2)];
    const moved = { id: 1, task_status_id: 2 };
    const result = reorderTaskList(base, moved, null, false, 2);
    // No existing Done card -> lastIndex stays -1 -> inserted at front.
    expect(ids(result)).toEqual([1, 2]);
    expect(result[0].task_status_id).toBe(2);
  });
});
