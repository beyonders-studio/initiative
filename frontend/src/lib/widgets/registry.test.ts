/**
 * Built-in widget drift + conformance.
 *
 * Two things are checked here, and the second is the point of the whole
 * one-harness design: the built-ins are not merely *described* as sandboxed
 * modules, they are executed as ones — through the same runtime, validator, and
 * vocabulary an installed listing's widget would go through. A built-in that
 * quietly needed a capability, or emitted something outside the SceneSpec,
 * fails here rather than at a customer's dashboard.
 */
import { describe, expect, it } from "vitest";

import { WidgetType } from "@/api/generated/initiativeAPI.schemas";

import { BUILTIN_WIDGET_TYPES, builtinWidgetSource } from "./registry";
import { renderInSandbox } from "./runtime/sandbox";
import { sampleFor } from "./sampleData";
import { resolveMapping } from "./shape";
import { validateScene } from "./validateScene";

describe("built-in widget registry", () => {
  it("covers exactly the widget types the backend declares", () => {
    expect(BUILTIN_WIDGET_TYPES.sort()).toEqual(Object.values(WidgetType).sort());
  });

  it("has no renderer for a type the backend does not know", () => {
    expect(builtinWidgetSource("iframe")).toBeUndefined();
  });
});

describe("built-ins run in the sandbox like any other widget", () => {
  /** The shape each widget declares, mirrored from the backend's WIDGET_SPECS.
   *  The served catalog is the authority; this copy is what lets the widget
   *  tests run without a backend, and `dashboards_test.py` is what would catch
   *  the two drifting. */
  const SHAPES: Record<
    string,
    { name: string; types: string[]; required?: boolean; repeatable?: boolean }[]
  > = {
    gantt: [
      { name: "label", types: ["text", "enum", "reference"] },
      { name: "start", types: ["date"] },
      { name: "end", types: ["date"] },
      { name: "group", types: ["text", "enum", "reference"], required: false },
    ],
    stat: [
      { name: "value", types: ["number"] },
      { name: "label", types: ["text", "enum", "reference"], required: false },
    ],
    chart: [
      { name: "label", types: ["text", "enum", "reference", "date"] },
      { name: "value", types: ["number"], repeatable: true },
    ],
    funnel: [
      { name: "label", types: ["text", "enum", "reference"] },
      { name: "value", types: ["number"] },
    ],
    progress: [
      { name: "value", types: ["number"] },
      { name: "total", types: ["number"], required: false },
      { name: "label", types: ["text", "enum", "reference"], required: false },
    ],
    heatmap: [
      { name: "at", types: ["date"] },
      { name: "value", types: ["number"] },
    ],
    board: [
      { name: "card", types: ["text", "enum", "reference"] },
      { name: "column", types: ["text", "enum", "reference"] },
      { name: "date", types: ["date"], required: false },
    ],
    table: [],
  };

  const slotsFor = (type: string, data: { columns: { name: string; type: string }[] }) =>
    resolveMapping(
      data.columns as never,
      (SHAPES[type] ?? []).map((slot) => ({
        required: true,
        repeatable: false,
        ...slot,
      })) as never
    );

  it.each(BUILTIN_WIDGET_TYPES)("%s draws the shape it declares", async (type) => {
    const widgetSource = builtinWidgetSource(type);
    expect(widgetSource, `no module for ${type}`).toBeDefined();
    const data = sampleFor(type);

    const result = await renderInSandbox({
      source: widgetSource as string,
      data,
      config: {},
      slots: slotsFor(type, data),
      now: Date.UTC(2026, 7, 11),
    });

    expect(result.ok, `${type} failed: ${JSON.stringify(result)}`).toBe(true);
    if (!result.ok) return;

    const validation = validateScene(result.value);
    expect(validation.ok, `${type} emitted an invalid scene: ${JSON.stringify(validation)}`).toBe(
      true
    );
    if (!validation.ok) return;

    // A widget handed data it can draw should draw it, not bail to an empty
    // tile — that would hide a broken binding behind a plausible-looking card.
    expect(validation.spec.scene.kind, `${type} fell through to an empty tile`).not.toBe("empty");
  });

  it.each(BUILTIN_WIDGET_TYPES)(
    "%s degrades to an empty tile with nothing mapped",
    async (type) => {
      // Every widget but the table needs its slots filled; the table draws
      // whatever it is given, which is what makes it the fallback.
      const data = sampleFor(type);
      const result = await renderInSandbox({
        source: builtinWidgetSource(type) as string,
        data,
        config: {},
        slots: {},
      });
      expect(result.ok).toBe(true);
      if (!result.ok) return;
      const validation = validateScene(result.value);
      expect(validation.ok).toBe(true);
      if (!validation.ok) return;
      expect(validation.spec.scene.kind).toBe(type === "table" ? "table" : "empty");
    }
  );

  it.each(BUILTIN_WIDGET_TYPES)("%s survives empty data", async (type) => {
    const data = { ...sampleFor(type), rows: [] };
    const result = await renderInSandbox({
      source: builtinWidgetSource(type) as string,
      data,
      config: {},
      slots: slotsFor(type, data),
    });
    expect(result.ok, `${type} threw on empty rows: ${JSON.stringify(result)}`).toBe(true);
    if (!result.ok) return;
    expect(validateScene(result.value).ok).toBe(true);
  });
});
