/**
 * Definition editing.
 *
 * These are the operations a drag, a resize, or a palette click turn into, and
 * they are pure — which is the point. The canvas can compute a change, draw it,
 * and send it, and the server's normalization comes back as the truth without
 * any of that logic living in a component.
 */
import { describe, expect, it } from "vitest";

import type { WidgetCatalog } from "@/api/generated/initiativeAPI.schemas";

import {
  addWidget,
  applyLayout,
  type DashboardDefinition,
  definitionsEqual,
  EMPTY_DEFINITION,
  effectiveBinding,
  GRID_COLUMNS,
  pruneConfig,
  readConfig,
  readDefinition,
  removeWidget,
  unboundSlots,
  updateWidget,
} from "./definition";

const catalog = {
  widgets: [
    {
      type: "gantt",
      min_w: 6,
      min_h: 3,
      default_w: 12,
      default_h: 6,
      sources: ["query"],
      options: [],
    },
    {
      type: "stat",
      min_w: 2,
      min_h: 2,
      default_w: 3,
      default_h: 2,
      sources: ["query"],
      options: [],
    },
    {
      type: "chart",
      min_w: 3,
      min_h: 3,
      default_w: 6,
      default_h: 4,
      sources: ["query"],
      options: [{ key: "mark", values: ["bar", "line"] }],
    },
  ],
  presets: [{ name: "bar_chart", primitive: "chart", options: { mark: "bar" } }],
} as unknown as WidgetCatalog;

const withWidgets = (...types: string[]): DashboardDefinition =>
  types.reduce(
    (definition, type) => addWidget(definition, catalog, type, "query"),
    EMPTY_DEFINITION
  );

describe("readDefinition", () => {
  it("treats a freshly created dashboard's empty object as an empty canvas", () => {
    expect(readDefinition({})).toEqual(EMPTY_DEFINITION);
    expect(readDefinition(null)).toEqual(EMPTY_DEFINITION);
    expect(readDefinition(undefined)).toEqual(EMPTY_DEFINITION);
  });

  it("keeps stored widgets and the authored column count", () => {
    const stored = readDefinition({ layout: { columns: 6 }, widgets: [{ id: "w1" }] });
    expect(stored.layout.columns).toBe(6);
    expect(stored.widgets).toHaveLength(1);
  });
});

describe("addWidget", () => {
  it("places a widget at its catalog default size", () => {
    const [widget] = withWidgets("gantt").widgets;
    expect(widget.grid).toMatchObject({ w: 12, h: 6, x: 0, y: 0 });
  });

  it("stacks each new widget below what is already placed", () => {
    const { widgets } = withWidgets("gantt", "stat");
    expect(widgets[1].grid.y).toBe(widgets[0].grid.y + widgets[0].grid.h);
  });

  it("gives every widget a distinct id, including after a removal", () => {
    const two = withWidgets("stat", "stat");
    const afterRemoval = removeWidget(two, "w1");
    const readded = addWidget(afterRemoval, catalog, "stat", "query");
    const ids = readded.widgets.map((widget) => widget.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("resolves a preset to its primitive with its options applied", () => {
    const [widget] = addWidget(EMPTY_DEFINITION, catalog, "bar_chart", "query").widgets;
    expect(widget.type).toBe("chart");
    expect(widget.preset).toBe("bar_chart");
    expect(widget.options).toEqual({ mark: "bar" });
  });

  it("carries the display options the picker chose", () => {
    const [widget] = addWidget(EMPTY_DEFINITION, catalog, "chart", "query", {
      mark: "pie",
    }).widgets;
    expect(widget.type).toBe("chart");
    expect(widget.preset).toBeUndefined();
    expect(widget.options).toEqual({ mark: "pie" });
  });

  it("lets a preset's own options win over the ones passed in", () => {
    // A preset *is* its options; filling in the rest is fine, contradicting it
    // is not — same order the backend normalizer applies them in.
    const [widget] = addWidget(EMPTY_DEFINITION, catalog, "bar_chart", "query", {
      mark: "pie",
      stacked: "true",
    }).widgets;
    expect(widget.options).toEqual({ mark: "bar", stacked: "true" });
  });

  it("stores no options when none were chosen", () => {
    const [widget] = addWidget(EMPTY_DEFINITION, catalog, "chart", "query").widgets;
    expect(widget.options).toBeUndefined();
  });

  it("falls back to a usable size when the catalog has not loaded", () => {
    const [widget] = addWidget(EMPTY_DEFINITION, undefined, "stat", "query").widgets;
    expect(widget.grid.w).toBeGreaterThan(0);
    expect(widget.grid.h).toBeGreaterThan(0);
  });
});

describe("applyLayout", () => {
  const definition = withWidgets("gantt");

  it("takes the canvas's placement", () => {
    const next = applyLayout(definition, catalog, [{ i: "w1", x: 2, y: 3, w: 8, h: 4 }]);
    expect(next.widgets[0].grid).toEqual({ x: 2, y: 3, w: 8, h: 4 });
  });

  it("clamps below a widget's legible minimum", () => {
    const next = applyLayout(definition, catalog, [{ i: "w1", x: 0, y: 0, w: 1, h: 1 }]);
    // The Gantt's floor, not the dragged value.
    expect(next.widgets[0].grid.w).toBe(6);
    expect(next.widgets[0].grid.h).toBe(3);
  });

  it("never lets a widget exceed the grid", () => {
    const next = applyLayout(definition, catalog, [{ i: "w1", x: 0, y: 0, w: 99, h: 4 }]);
    expect(next.widgets[0].grid.w).toBe(GRID_COLUMNS);
  });

  it("ignores negative coordinates", () => {
    const next = applyLayout(definition, catalog, [{ i: "w1", x: -5, y: -2, w: 8, h: 4 }]);
    expect(next.widgets[0].grid).toMatchObject({ x: 0, y: 0 });
  });

  it("leaves widgets the layout did not mention alone", () => {
    const two = withWidgets("gantt", "stat");
    const next = applyLayout(two, catalog, [{ i: "w1", x: 1, y: 1, w: 8, h: 4 }]);
    expect(next.widgets[1].grid).toEqual(two.widgets[1].grid);
  });
});

describe("definitionsEqual", () => {
  it("is false for a real move and true for a no-op", () => {
    const definition = withWidgets("stat");
    const moved = applyLayout(definition, catalog, [{ i: "w1", x: 4, y: 0, w: 3, h: 2 }]);
    expect(definitionsEqual(definition, moved)).toBe(false);
    expect(definitionsEqual(definition, { ...definition })).toBe(true);
  });

  it("does not mistake a different key order for a different dashboard", () => {
    // The editor compares its draft against what came back from a save, and the
    // server builds each widget's keys in its own order. Reading that as a
    // change would leave the local copy drawn forever, ignoring normalization.
    const definition = withWidgets("stat");
    const [widget] = definition.widgets;
    const reordered = {
      ...definition,
      widgets: [{ binding: widget.binding, grid: widget.grid, type: widget.type, id: widget.id }],
    };
    expect(definitionsEqual(definition, reordered)).toBe(true);
  });
});

describe("effectiveBinding", () => {
  it("layers instance config over the definition's binding", () => {
    // The seam that makes an installed listing work: the catalog definition
    // cannot know this community's counter ids, so the install fills them in.
    const definition = addWidget(EMPTY_DEFINITION, catalog, "stat", "query");
    const config = readConfig({
      widgets: { w1: { counter_group_id: 4, counter_id: 9 } },
    });
    expect(effectiveBinding(definition.widgets[0], config)).toEqual({
      source: "query",
      counter_group_id: 4,
      counter_id: 9,
    });
  });

  it("leaves a widget with no config entry on its own binding", () => {
    const definition = addWidget(EMPTY_DEFINITION, catalog, "stat", "query");
    expect(effectiveBinding(definition.widgets[0], readConfig({}))).toEqual({
      source: "query",
    });
  });
});

describe("unboundSlots", () => {
  it("names what a binding still needs", () => {
    expect(unboundSlots({ source: "query" })).toEqual(["sql"]);
  });

  it("is empty once every required parameter is filled", () => {
    expect(unboundSlots({ source: "query", sql: "SELECT title FROM tasks" })).toEqual([]);
  });
});

describe("pruneConfig", () => {
  it("drops config for widgets the definition no longer has", () => {
    const definition = withWidgets("stat");
    const config = readConfig({ widgets: { w1: { counter_id: 1 }, w9: { counter_id: 2 } } });
    expect(Object.keys(pruneConfig(definition, config).widgets)).toEqual(["w1"]);
  });

  it("leaves nothing behind when the last widget goes", () => {
    const definition = withWidgets("stat");
    const config = readConfig({ widgets: { w1: { counter_id: 1 } } });
    const emptied = removeWidget(definition, "w1");
    expect(pruneConfig(emptied, config).widgets).toEqual({});
  });
});

describe("updateWidget", () => {
  it("patches only the named widget", () => {
    const two = withWidgets("stat", "stat");
    const next = updateWidget(two, "w2", { title: "Renamed" });
    expect(next.widgets[0].title).toBeUndefined();
    expect(next.widgets[1].title).toBe("Renamed");
  });

  it("does not mutate the definition it was given", () => {
    const definition = withWidgets("stat");
    const snapshot = JSON.stringify(definition);
    updateWidget(definition, "w1", { title: "Renamed" });
    expect(JSON.stringify(definition)).toBe(snapshot);
  });
});
