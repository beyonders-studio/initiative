import { describe, expect, it } from "vitest";

import { buildTask } from "@/__tests__/factories";
import type { TaskListRead } from "@/api/generated/initiativeAPI.schemas";
import type { TaskGroupRow } from "@/lib/layouts/grouping";
import { flattenTaskTree, nestTaskRows, type TaskTreeRow, treeParents } from "@/lib/taskTree";

const task = (id: number, parent?: number): TaskListRead =>
  buildTask({
    id,
    title: `Task ${id}`,
    parent: parent ? { id: parent, title: `Task ${parent}` } : null,
  });

/** Each row as `id` or `id[parts…]`, so a tree reads at a glance. */
const shape = (rows: readonly TaskTreeRow[]): string[] =>
  rows.map((row) => (row.subRows ? `${row.id}[${shape(row.subRows).join(",")}]` : `${row.id}`));

describe("nestTaskRows", () => {
  it("lists each task under its parent, at every depth, in the list's order", () => {
    const rows = nestTaskRows([task(1), task(2, 1), task(3), task(4, 2), task(5, 1)]);

    expect(shape(rows)).toEqual(["1[2[4],5]", "3"]);
    expect(flattenTaskTree(rows).map((row) => [row.id, row.level])).toEqual([
      [1, 0],
      [2, 1],
      [4, 2],
      [5, 1],
      [3, 0],
    ]);
  });

  it("lists a task whose parent is not in the list at the top", () => {
    expect(shape(nestTaskRows([task(2, 1), task(3)]))).toEqual(["2", "3"]);
  });

  it("nests within a group, and a part in another group than its parent is at its top", () => {
    const rows: TaskGroupRow[] = [
      { ...task(1), group: "a" },
      { ...task(2, 1), group: "a" },
      { ...task(3, 1), group: "b" },
    ];

    expect(shape(nestTaskRows(rows))).toEqual(["1[2]", "3"]);
  });

  it("lists the tasks of a loop of parents at the top, with what hangs off them", () => {
    expect(shape(nestTaskRows([task(1, 2), task(2, 1), task(3, 1)]))).toEqual(["1[3]", "2"]);
  });
});

describe("treeParents", () => {
  it("names the task each row is listed under, and none at the top", () => {
    const parents = treeParents(nestTaskRows([task(1), task(2, 1), task(3), task(4, 2)]));

    expect([...parents]).toEqual([
      [1, null],
      [2, 1],
      [4, 2],
      [3, null],
    ]);
  });
});
