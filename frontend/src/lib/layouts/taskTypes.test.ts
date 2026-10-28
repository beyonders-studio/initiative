import { describe, expect, it } from "vitest";

import { buildTask, buildTaskType } from "@/__tests__/factories";
import i18n from "@/__tests__/helpers/i18n-test";
import { parseLayoutKind } from "@/lib/filters/layoutSearch";
import type { TranslateFn } from "@/types/i18n";

import { pageParts } from "./detailLayout";
import { groupables } from "./grouping";
import { TASK_LAYOUT, taskFields, taskLayoutFor, taskPageWithFields } from "./tasks";

const SHAPES = ["plain", "fix", "discussion", "dates", "repeat", "checklist"];

describe("a task type's page", () => {
  it("is drawn as its shape, and a shape this build does not know as the plain one", () => {
    expect(taskLayoutFor("plain")).toBe(TASK_LAYOUT);
    expect(taskLayoutFor("someday")).toBe(TASK_LAYOUT);
    expect(taskLayoutFor(null)).toBe(TASK_LAYOUT);
    expect(taskLayoutFor("fix")).not.toBe(TASK_LAYOUT);
  });

  it("leads with what its kind of task needs", () => {
    const side = (shape: string) => pageParts(taskLayoutFor(shape).tree(null)).slice(5, 7);
    expect(side("fix")).toEqual(["type", "priority"]);
    expect(side("dates")).toEqual(["type", "dates"]);
    expect(side("repeat")).toEqual(["type", "recurrence"]);
    expect(pageParts(taskLayoutFor("checklist").tree(null))[4]).toBe("checklist");
  });

  it("leaves out what an idea rarely needs", () => {
    const parts = pageParts(taskLayoutFor("discussion").tree(null));
    expect(parts).not.toContain("dates");
    expect(parts).not.toContain("checklist");
    expect(parts).toContain("comments");
  });

  it("can place every part and field the plain page has, whatever its shape", () => {
    for (const shape of SHAPES) {
      const spec = taskLayoutFor(shape);
      expect(new Set(spec.ownParts)).toEqual(new Set(TASK_LAYOUT.ownParts));
      expect(spec.detailFields).toEqual(TASK_LAYOUT.detailFields);
    }
  });
});

describe("a task's type as a field", () => {
  it("shows the task's type, or nothing in a project with one type", () => {
    const type = buildTaskType({ name: "Bug", icon: "bug" });
    const task = buildTask({ task_type_id: type.id, task_type: type });
    expect(taskFields([]).get("type")?.value(task)).toEqual(type);
    expect(taskFields([], [], { typed: false }).get("type")?.value(task)).toBeNull();
  });

  it("is drawn by the title in a table, which has no icon of its own for it", () => {
    const type = buildTaskType({ name: "Bug", icon: "bug" });
    const task = buildTask({ task_type_id: type.id, task_type: type });
    expect(taskFields([]).get("title")?.typeOf?.(task)).toEqual(type);
    expect(taskFields([], [], { typed: false }).get("title")?.typeOf?.(task)).toBeNull();
  });
});

describe("grouping by type", () => {
  it("is named in words, not by its key", async () => {
    await i18n.loadNamespaces(["layouts", "dashboards"]);
    const t = i18n.getFixedT("en") as TranslateFn;
    const [type] = groupables([{ name: "task_type_id", kind: "task_type" }], taskFields([]), t);
    expect(type.label).toBe("Type");
  });
});

describe("the layout editor's ?layout=", () => {
  it("names a list, the task page, or one task type's page", () => {
    expect(parseLayoutKind("board")).toBe("board");
    expect(parseLayoutKind("task")).toBe("task");
    expect(parseLayoutKind("file")).toBe("file");
    expect(parseLayoutKind("task:12")).toBe("task:12");
    expect(parseLayoutKind("task:0")).toBeUndefined();
    expect(parseLayoutKind("task:x")).toBeUndefined();
    expect(parseLayoutKind("event:3")).toBeUndefined();
  });
});

describe("a ready-made type's page", () => {
  it("is its shape's, with its fields at the end of the side's first section", () => {
    const page = taskPageWithFields("dates", [7, 9]);
    const [first, ...rest] = page.side ?? [];
    const placed = (first as { children?: { props?: { field?: string } }[] }).children ?? [];
    expect(placed.slice(-2).map((node) => node.props?.field)).toEqual(["property:7", "property:9"]);
    // The shape's own lead comes first, and nothing else moves.
    expect(placed[1]?.props?.field ?? (placed[1] as { type?: string }).type).toBe("dates");
    expect(rest).toEqual(taskPageWithFields("dates", []).side?.slice(1));
    expect(page.main).toEqual(taskPageWithFields("dates", []).main);
  });

  it("stores no one-column order, as a stored page never does", () => {
    expect(JSON.stringify(taskPageWithFields("plain", [1]))).not.toContain('"order"');
  });
});
