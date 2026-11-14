import { describe, expect, it } from "vitest";

import { DEFAULT_COLS, DEFAULT_ROWS } from "@/lib/spreadsheet/bounds";
import { parseSpreadsheetContent } from "@/lib/spreadsheet/content";
import fixture from "@/lib/spreadsheet/sheet-schema.fixture.json";

describe("parseSpreadsheetContent — junk", () => {
  it("produces a usable workbook from junk", () => {
    for (const junk of [null, undefined, 42, "nope", []]) {
      const out = parseSpreadsheetContent(junk);
      expect(out.sheets).toHaveLength(1);
      expect(out.sheets[0].dimensions).toEqual({ rows: DEFAULT_ROWS, cols: DEFAULT_COLS });
    }
  });
});

describe("parseSpreadsheetContent — v3", () => {
  it("keeps sheets, order, and per-sheet content", () => {
    const out = parseSpreadsheetContent({
      schema_version: 3,
      kind: "spreadsheet",
      sheets: [
        { id: "s1", name: "Summary", cells: { "0:0": "=Data!A1" } },
        { id: "sx", name: "Data", cells: { "0:0": 5 } },
      ],
    });
    expect(out.sheets.map((s) => s.name)).toEqual(["Summary", "Data"]);
    expect(out.sheets.map((s) => s.id)).toEqual(["s1", "sx"]);
    expect(out.sheets[0].cells).toEqual({ "0:0": "=Data!A1" });
  });

  it("de-duplicates names case-insensitively", () => {
    const out = parseSpreadsheetContent({
      schema_version: 3,
      sheets: [
        { id: "a", name: "Budget" },
        { id: "b", name: "BUDGET" },
      ],
    });
    expect(out.sheets.map((s) => s.name)).toEqual(["Budget", "BUDGET 2"]);
  });

  it("re-issues a duplicated id so two tabs never share one container", () => {
    const out = parseSpreadsheetContent({
      schema_version: 3,
      sheets: [
        { id: "same", name: "One" },
        { id: "same", name: "Two" },
      ],
    });
    expect(new Set(out.sheets.map((s) => s.id)).size).toBe(2);
  });

  it("names an unnamed sheet by position and repairs an unusable one", () => {
    const out = parseSpreadsheetContent({
      schema_version: 3,
      sheets: [{ id: "a" }, { id: "b", name: "  ///  " }],
    });
    expect(out.sheets.map((s) => s.name)).toEqual(["Sheet1", "Sheet2"]);
  });

  it("opens on one empty sheet when sheets is empty or not a list", () => {
    expect(parseSpreadsheetContent({ schema_version: 3, sheets: [] }).sheets).toHaveLength(1);
    const notAList = parseSpreadsheetContent({ sheets: {}, cells: { "0:0": "x" } });
    expect(notAList.sheets).toHaveLength(1);
    expect(notAList.sheets[0].cells).toEqual({});
  });

  it("grows a sheet's canvas to cover its furthest cell", () => {
    const out = parseSpreadsheetContent({
      schema_version: 3,
      sheets: [{ id: "a", name: "Big", cells: { "499:2": "far" } }],
    });
    expect(out.sheets[0].dimensions.rows).toBe(500);
  });

  it("drops non-scalar cells and canonicalizes leading-zero keys", () => {
    const out = parseSpreadsheetContent({
      schema_version: 3,
      sheets: [{ id: "a", name: "S", cells: { "01:02": "x", "0:0": { nested: 1 }, "1:1": "" } }],
    });
    expect(out.sheets[0].cells).toEqual({ "1:2": "x" });
  });
});

describe("schema fixture — nothing the model defines is dropped", () => {
  /** Every leaf in a value, as a dotted path, with data-keyed maps
   *  generalised so ``columns.0.width`` and ``columns.7.width`` are one
   *  path rather than two. */
  const leafPaths = (value: unknown, prefix = "", out = new Set<string>()): Set<string> => {
    if (value === null || typeof value !== "object") {
      if (prefix) out.add(prefix);
      return out;
    }
    for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
      const segment = /^\d+(:\d+)?$/.test(key) ? "*" : key;
      leafPaths(child, prefix ? `${prefix}.${segment}` : segment, out);
    }
    return out;
  };

  it("round-trips every field in sheet-schema.fixture.json", () => {
    const out = parseSpreadsheetContent({
      schema_version: 3,
      kind: "spreadsheet",
      // The fixture sheet is hidden, and a workbook with nothing on show
      // has its first sheet revealed — so it needs a companion to stay
      // hidden and prove the flag survives.
      sheets: [{ id: "visible", name: "Visible" }, fixture.sheet],
    });
    const kept = leafPaths(out.sheets[1]);
    expect([...leafPaths(fixture.sheet)].filter((path) => !kept.has(path))).toEqual([]);
  });
});
