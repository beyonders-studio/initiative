import { describe, expect, it } from "vitest";

import type { WidgetBinding } from "@/hooks/useWidgetData";
import type { WidgetSource } from "@/lib/widgets/dataShapes";
import { paramsFor, SOURCES, unboundSlots } from "@/lib/widgets/sources";

const binding = (partial: Partial<WidgetBinding> & { source: WidgetSource }): WidgetBinding =>
  partial as WidgetBinding;

describe("the source registry", () => {
  it("describes the two bindings there are", () => {
    // The registry is what the config dialog and unboundSlots read, so a
    // binding missing here has no controls and no description anywhere.
    expect(Object.keys(SOURCES).sort()).toEqual(["plugin", "query"]);
  });

  it("says a statement is the whole of a query binding", () => {
    const params = paramsFor("query");
    expect(params).toHaveLength(1);
    expect(params[0]).toMatchObject({ kind: "sql", key: "sql", required: true });
  });

  it("reports the parameters a binding still needs", () => {
    expect(unboundSlots(binding({ source: "query" }))).toEqual(["sql"]);
    expect(unboundSlots(binding({ source: "query", sql: "SELECT 1" }))).toEqual([]);
    expect(unboundSlots(binding({ source: "plugin", plugin_uid: "abc" }))).toEqual(["endpoint_id"]);
  });

  it("says nothing about a source it does not know", () => {
    expect(unboundSlots(binding({ source: "nonsense" as WidgetSource }))).toEqual([]);
    expect(paramsFor("nonsense")).toEqual([]);
  });
});
