import { describe, expect, it } from "vitest";

import { buildPropertyDefinition } from "@/__tests__/factories";

import {
  addableFields,
  addablePluginParts,
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
import { storedLayout, taskFields, taskPageRoot, unplacedFields } from "./tasks";
import type { ViewNode } from "./tree";

const field = (id: string): ViewNode => ({ type: "field", props: { field: id } });

const CARD: ViewNode = {
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
    const fields = (node: ViewNode | undefined) =>
      node?.children?.map((child) => child.props?.field ?? child.type);

    expect(fields(nodeAt(added, [0]))).toEqual(["title", "priority", "description"]);
    expect(fields(nodeAt(within, [0]))).toEqual(["description", "title"]);
    expect(fields(out)).toEqual(["stack", "tags", "description"]);
    expect(fields(nodeAt(out, [0]))).toEqual(["title"]);
  });

  it("names every node by its path", () => {
    const paths = indexPaths(CARD);

    expect(paths.get(CARD)).toBe("");
    expect(paths.get(nodeAt(CARD, [0, 1]) as ViewNode)).toBe("0.1");
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
    expect(removable(nodeAt(CARD, [0]) as ViewNode, fields)).toBe(false);
  });

  it("offers a card what it does not show, and no property alone where it shows them all", () => {
    const ids = (card: ViewNode) =>
      addableFields({ layout: { type: "board" }, card: card as never }, fields).map(
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
      { layout: { type: "table" }, columns: ["title", "dueDate"] },
      fields
    ).map((each) => each.id);

    expect(ids).toEqual(["startDate", "priority", "comments", "tags", "property:12"]);
  });

  it("offers each of a plug-in's parts once, and none past the server's limit", () => {
    const parts = ["a", "b", "c", "d"].map((id) => ({ id }));
    const placing = (...ids: string[]): ViewNode => ({
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

describe("a task page laid out", () => {
  it("is stored whole, without the shipped page's one-column order", () => {
    const shipped = taskPageRoot(null);
    // Relations to the top of Main, then Checklist into the Description section.
    const moved = moveNode(moveNode(shipped, [2, 1], [1, 0]), [1, 2], [1, 1, 1]);
    const layout = storedLayout(moved);

    expect(JSON.stringify(layout)).not.toContain("order");
    expect(layout.main?.[0]).toEqual({ type: "relations" });
    expect((layout.main?.[1] as ViewNode | undefined)?.children?.[1]).toEqual({
      type: "field",
      props: { field: "checklist" },
    });
    expect(layout.header).toHaveLength(3);
  });

  it("names what it places nowhere, which More fields then draws", () => {
    const page = taskPageRoot({ side: [] });
    const unplaced = unplacedFields({
      header: page.children?.[0]?.children ?? [],
      main: page.children?.[1]?.children ?? [],
      side: [],
    });

    expect(unplaced.map((node) => node.props?.field ?? node.type)).toEqual([
      "status",
      "priority",
      "assignees",
      "dates",
      "recurrence",
      "tags",
      "properties",
    ]);
  });
});
