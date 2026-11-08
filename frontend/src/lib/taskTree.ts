/**
 * A list of tasks as a tree: each task listed under the task it is part of
 * (`TaskListRead.parent`), where that task is in the list too. A grouped list
 * nests within each group, so a subtask in another group than its parent is
 * listed there at the top.
 */

import type { TaskGroupRow } from "@/lib/layouts/grouping";

/** A row of a task tree: the task, how deep it is, and its parts' rows. */
export type TaskTreeRow = TaskGroupRow & { level: number; subRows?: TaskTreeRow[] };

const keyOf = (id: number, group: string | undefined) => `${group ?? ""}\u0000${id}`;

/** `rows` nested under their parents, in their order. A task in a loop of
 *  parents is listed at the top, as nothing in the loop comes first. */
export const nestTaskRows = (rows: readonly TaskGroupRow[]): TaskTreeRow[] => {
  const held = new Set(rows.map((row) => keyOf(row.id, row.group)));
  const up = new Map<string, string>();
  for (const row of rows) {
    const parent = row.parent ? keyOf(row.parent.id, row.group) : undefined;
    if (parent !== undefined && held.has(parent)) up.set(keyOf(row.id, row.group), parent);
  }
  const inLoop = (key: string) => {
    const seen = new Set<string>();
    for (let at = up.get(key); at !== undefined; at = up.get(at)) {
      if (at === key) return true;
      if (seen.has(at)) return false;
      seen.add(at);
    }
    return false;
  };
  const parts = new Map<string, TaskGroupRow[]>();
  const roots: TaskGroupRow[] = [];
  for (const row of rows) {
    const key = keyOf(row.id, row.group);
    const parent = up.get(key);
    if (parent === undefined || inLoop(key)) {
      roots.push(row);
    } else {
      parts.set(parent, [...(parts.get(parent) ?? []), row]);
    }
  }
  const build = (row: TaskGroupRow, level: number): TaskTreeRow => {
    const own = parts.get(keyOf(row.id, row.group));
    return own
      ? { ...row, level, subRows: own.map((part) => build(part, level + 1)) }
      : { ...row, level };
  };
  return roots.map((row) => build(row, 0));
};

/** Every row of a tree, each before its parts, as the table draws them. */
export const flattenTaskTree = (rows: readonly TaskTreeRow[]): TaskTreeRow[] =>
  rows.flatMap((row) => [row, ...flattenTaskTree(row.subRows ?? [])]);

/** The task each row of a tree is listed under, by task id; null at the top. */
export const treeParents = (rows: readonly TaskTreeRow[]): Map<number, number | null> => {
  const parents = new Map<number, number | null>();
  const visit = (row: TaskTreeRow, parent: number | null) => {
    parents.set(row.id, parent);
    for (const part of row.subRows ?? []) visit(part, row.id);
  };
  for (const row of rows) visit(row, null);
  return parents;
};
