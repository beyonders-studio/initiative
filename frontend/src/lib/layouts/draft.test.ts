import { describe, expect, it } from "vitest";

import { buildPropertyDefinition } from "@/__tests__/factories";
import { MetadataType } from "@/api/generated/initiativeAPI.schemas";

import { pageParts, type StoredRegions, storedLayout } from "./detailLayout";
import {
  addableFields,
  addablePluginParts,
  canRequire,
  changeAt,
  dropAt,
  dropInto,
  dropOn,
  historyReducer,
  indexPaths,
  insertAt,
  moveNode,
  nodeAt,
  pathAfterMove,
  pathAfterRemove,
  removable,
  startHistory,
} from "./draft";
import { TASK_LAYOUT, taskFields } from "./tasks";
import type { LayoutNode } from "./tree";

const field = (id: string): LayoutNode => ({ type: "field", props: { field: id } });

const CARD: LayoutNode = {
  type: "card",
  children: [{ type: "stack", children: [field("title"), field("description")] }, field("tags")],
};

describe("editing a tree by path", () => {
  it("changes or takes out one node and leaves the rest as they were", () => {
    const renamed = changeAt(CARD, [0, 1], () => field("priority"));
    const removed = changeAt(CARD, [0, 0], () => null);

    expect(nodeAt(renamed, [0, 1])).toEqual(field("priority"));
    expect(renamed.children?.[1]).toBe(CARD.children?.[1]);
    expect(nodeAt(removed, [0])?.children).toEqual([field("description")]);
    expect(nodeAt(CARD, [0])?.children).toHaveLength(2);
  });

  it("puts a node into a group, and moves one within its group or out of it", () => {
    const added = insertAt(CARD, [0], field("priority"), 1);
    const within = moveNode(CARD, [0, 0], [0, 1]);
    const out = moveNode(CARD, [0, 1], [2]);
    const fields = (node: LayoutNode | undefined) =>
      node?.children?.map((child) => child.props?.field ?? child.type);

    expect(fields(nodeAt(added, [0]))).toEqual(["title", "priority", "description"]);
    expect(fields(nodeAt(within, [0]))).toEqual(["description", "title"]);
    expect(fields(out)).toEqual(["stack", "tags", "description"]);
    expect(fields(nodeAt(out, [0]))).toEqual(["title"]);
  });

  it("names every node by its path", () => {
    const paths = indexPaths(CARD);

    expect(paths.get(CARD)).toBe("");
    expect(paths.get(nodeAt(CARD, [0, 1]) as LayoutNode)).toBe("0.1");
  });
});

describe("historyReducer", () => {
  it("undoes and redoes each change, and a new change ends what could be redone", () => {
    let history = startHistory("A");
    history = historyReducer(history, { type: "change", present: "B" });
    history = historyReducer(history, { type: "change", present: "C" });

    history = historyReducer(history, { type: "undo" });
    expect(history.present).toBe("B");
    history = historyReducer(history, { type: "redo" });
    expect(history.present).toBe("C");

    history = historyReducer(history, { type: "undo" });
    history = historyReducer(history, { type: "change", present: "D" });
    expect(history.future).toEqual([]);
    expect(historyReducer(history, { type: "reset", present: "A" })).toEqual(startHistory("A"));
  });
});

describe("what the editor allows", () => {
  const fields = taskFields([buildPropertyDefinition({ id: 12, name: "Effort" })]);

  it("never takes off the title, nor a group that holds it", () => {
    expect(removable(field("tags"), fields)).toBe(true);
    expect(removable(field("title"), fields)).toBe(false);
    expect(removable(nodeAt(CARD, [0]) as LayoutNode, fields)).toBe(false);
  });

  it("offers a card what it does not show, and no property alone where it shows them all", () => {
    const ids = (card: LayoutNode) =>
      addableFields({ kind: "board", definition: { card: card as never } }, fields).map(
        (each) => each.id
      );

    expect(ids(CARD)).not.toContain("tags");
    expect(ids(CARD)).toContain("property:12");
    expect(
      ids({ ...CARD, children: [...(CARD.children ?? []), { type: "properties" }] })
    ).not.toContain("property:12");
  });

  it("offers a table the fields it draws as columns and has not", () => {
    const ids = addableFields(
      { kind: "table", definition: { columns: ["title", "dueDate"] } },
      fields
    ).map((each) => each.id);

    expect(ids).toEqual(["assignees", "startDate", "priority", "comments", "tags", "property:12"]);
  });

  it("requires what a person fills in, and nothing a counter's page holds", () => {
    const withCheckbox = taskFields([
      buildPropertyDefinition({ id: 12, name: "Effort" }),
      buildPropertyDefinition({ id: 13, name: "Done", type: MetadataType.checkbox }),
    ]);
    const can = (node: LayoutNode, parts = TASK_LAYOUT.requiredParts) =>
      canRequire(node, withCheckbox, parts);

    expect(can(field("description"))).toBe(true);
    expect(can(field("property:12"))).toBe(true);
    expect(can({ type: "dates" })).toBe(true);
    // A title is always required; a type, a status and a byline are never empty
    // or filled by nobody; a checkbox is always on or off.
    expect(can(field("title"))).toBe(false);
    expect(can(field("type"))).toBe(false);
    expect(can({ type: "status" })).toBe(false);
    expect(can({ type: "byline" })).toBe(false);
    expect(can(field("property:13"))).toBe(false);
    expect(can(field("description"), null)).toBe(false);
  });

  it("offers each of a plug-in's parts once, and none past the server's limit", () => {
    const parts = ["a", "b", "c", "d"].map((id) => ({ id }));
    const placing = (...ids: string[]): LayoutNode => ({
      type: "card",
      children: ids.map((part) => ({ type: "plugin", props: { plugin: 3, part } })),
    });

    expect(addablePluginParts(placing("a"), 3, parts).map((part) => part.id)).toEqual([
      "b",
      "c",
      "d",
    ]);
    expect(addablePluginParts(placing("a"), 4, parts)).toHaveLength(4);
    expect(addablePluginParts(placing("a", "b", "c"), 3, parts)).toEqual([]);
  });
});

describe("a selection as the card changes", () => {
  it("follows the part it names when parts move", () => {
    // The group's third part moves to the front.
    expect(pathAfterMove([0, 2], [0, 2], [0, 0])).toEqual([0, 0]);
    expect(pathAfterMove([0, 0], [0, 2], [0, 0])).toEqual([0, 1]);
    expect(pathAfterMove([0, 3, 1], [0, 2], [0, 0])).toEqual([0, 3, 1]);
    expect(pathAfterMove([1], [0, 2], [0, 0])).toEqual([1]);
    // A group moves out from in front of its sibling, and takes what it holds.
    expect(pathAfterMove([0, 1, 4], [0, 1], [2])).toEqual([2, 4]);
    expect(pathAfterMove([0, 2], [0, 1], [2])).toEqual([0, 1]);
  });

  it("closes up after a part is taken out, and is gone with it", () => {
    expect(pathAfterRemove([0, 2], [0, 1])).toEqual([0, 1]);
    expect(pathAfterRemove([0, 0], [0, 1])).toEqual([0, 0]);
    expect(pathAfterRemove([0, 1, 3], [0, 1])).toBeNull();
    expect(pathAfterRemove([1], [0, 1])).toEqual([1]);
  });
});

describe("where a dragged part lands", () => {
  it("takes the place of what it is dropped on, and never goes inside itself", () => {
    // Down its own group, it takes the place; into another, it goes before.
    expect(dropOn([0, 0], [0, 1])).toEqual([0, 1]);
    expect(dropOn([0, 1], [1])).toEqual([1]);
    expect(dropOn([1], [0, 1])).toEqual([0, 1]);
    expect(dropOn([0], [0, 1])).toBeNull();
  });

  it("goes before or after the part it is put beside", () => {
    // After the description, from ahead of it in its own group.
    expect(dropAt([0, 0], [0], 2)).toEqual([0, 1]);
    // Before the title, from outside the group.
    expect(dropAt([1], [0], 0)).toEqual([0, 0]);
    // After the group, from inside it.
    expect(dropAt([0, 1], [], 1)).toEqual([1]);
    expect(dropAt([0], [0, 1], 0)).toBeNull();
  });

  it("goes last in a group dropped into", () => {
    expect(dropInto(CARD, [1], [0])).toEqual([0, 2]);
    expect(dropInto(CARD, [0, 0], [0])).toEqual([0, 1]);
    expect(dropInto(CARD, [0], [0])).toBeNull();
    expect(moveNode(CARD, [1], dropInto(CARD, [1], [0]) as number[]).children).toHaveLength(1);
  });
});

describe("a task detail laid out", () => {
  it("reads top to bottom as a phone draws it, for an export of the page", () => {
    // A plug-in's part after the checklist, which only a browser draws.
    const stored = storedLayout(
      insertAt(TASK_LAYOUT.root(null), [1], { type: "plugin", props: { plugin: 3, part: "ci" } }, 2)
    );

    expect(pageParts(TASK_LAYOUT.tree(stored as StoredRegions))).toEqual([
      "title",
      "actions",
      "byline",
      "notice",
      "description",
      "type",
      "status",
      "priority",
      "assignees",
      "dates",
      "recurrence",
      "tags",
      "properties",
      "checklist",
      "case",
      "relations",
      "comments",
    ]);
  });

  it("is stored whole, without the shipped page's one-column order", () => {
    const shipped = TASK_LAYOUT.root(null);
    // Relations to the top of Main, then Checklist into the Description section.
    const moved = moveNode(moveNode(shipped, [2, 1], [1, 0]), [1, 2], [1, 1, 1]);
    const layout = storedLayout(moved);

    expect(JSON.stringify(layout)).not.toContain("order");
    expect(layout.main?.[0]).toEqual({ type: "relations" });
    expect((layout.main?.[1] as LayoutNode | undefined)?.children?.[1]).toEqual({
      type: "field",
      props: { field: "checklist" },
    });
    expect(layout.header).toHaveLength(3);
  });

  it("reads on a phone as the shipped page does once laid out anew", () => {
    // Stored after any change: no one-column order of its own, and a plug-in
    // part added after the checklist.
    const stored = storedLayout(
      insertAt(TASK_LAYOUT.root(null), [1], { type: "plugin", props: { plugin: 3, part: "ci" } }, 2)
    );
    const tree = TASK_LAYOUT.tree(stored as StoredRegions);
    const orders = (index: number) =>
      tree.children?.[index]?.children?.map((node) => [
        // A section by its first part.
        node.props?.field ??
          node.children?.[0]?.props?.field ??
          node.children?.[0]?.type ??
          node.type,
        node.props?.order,
      ]);

    // Description, the fields, the checklist and what follows it, case,
    // relations, then comments.
    expect(orders(1)).toEqual([
      ["description", 1],
      ["checklist", 3],
      ["plugin", 3],
      ["case", 4],
      ["comments", 6],
    ]);
    expect(orders(2)).toEqual([
      ["type", 2],
      ["relations", 5],
    ]);
  });
});
