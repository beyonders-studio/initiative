import type { RowData } from "@tanstack/react-table";

import { TaskPriority } from "@/api/generated/initiativeAPI.schemas";
import type { AppRow } from "@/ui/lib/table";

const toTimestamp = (value: unknown): number | null => {
  if (!value) {
    return null;
  }

  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value.getTime();
  }

  if (typeof value === "string" || typeof value === "number") {
    const date = new Date(value);
    const time = date.getTime();
    return Number.isNaN(time) ? null : time;
  }

  return null;
};

/**
 * Sorts nullable date-ish values while keeping undated rows at the bottom.
 */
export const dateSortingFn = <TData extends RowData>(
  rowA: AppRow<TData>,
  rowB: AppRow<TData>,
  columnId: string
) => {
  const valueA = toTimestamp(rowA.getValue(columnId));
  const valueB = toTimestamp(rowB.getValue(columnId));

  if (valueA === valueB) {
    return 0;
  }

  if (valueA === null) {
    return 1;
  }

  if (valueB === null) {
    return -1;
  }

  return valueA - valueB;
};

/**
 * Canonical task-priority ranking, low → urgent. Keyed by `TaskPriority` so
 * adding a priority to the backend enum surfaces as a compile error here until
 * it is ranked — this is the single source of truth for priority ordering.
 */
export const priorityRank: Record<TaskPriority, number> = {
  low: 0,
  medium: 1,
  high: 2,
  urgent: 3,
};

/**
 * Task priorities in ascending order (low → urgent). Derived from the generated
 * `TaskPriority` enum so it always covers every backend value, sorted by
 * `priorityRank`. Route all "ordered priority list" UIs through this.
 */
export const PRIORITY_ORDER: TaskPriority[] = (Object.values(TaskPriority) as TaskPriority[]).sort(
  (a, b) => priorityRank[a] - priorityRank[b]
);

/**
 * One value to sort a list of names by: the first alphabetically, ignoring
 * case. Nothing for no names, which a column sorts last.
 */
export const firstName = (names: readonly string[]): string | undefined =>
  names
    .map((name) => name.toLowerCase())
    .reduce<string | undefined>(
      (first, name) => (first === undefined || name.localeCompare(first) < 0 ? name : first),
      undefined
    );

/** One value to sort tags by, as the task list sorts them. */
export const firstTagName = (tags: readonly { name: string }[]): string | undefined =>
  firstName(tags.map((tag) => tag.name));

/**
 * Sorts text in the reader's language order.
 */
export const textSortingFn = <TData extends RowData>(
  rowA: AppRow<TData>,
  rowB: AppRow<TData>,
  columnId: string
) => rowA.getValue<string>(columnId).localeCompare(rowB.getValue<string>(columnId));

/**
 * Sorts by task priority (low to urgent)
 */
export const prioritySortingFn = <TData extends RowData>(
  rowA: AppRow<TData>,
  rowB: AppRow<TData>,
  columnId: string
) => {
  const priorityA = rowA.getValue<TaskPriority>(columnId);
  const priorityB = rowB.getValue<TaskPriority>(columnId);
  const aRank = priorityA ? priorityRank[priorityA] : -1;
  const bRank = priorityB ? priorityRank[priorityB] : -1;
  return aRank - bRank;
};
