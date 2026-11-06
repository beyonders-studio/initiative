/**
 * A range of a workbook, as a dashboard statement reads one.
 *
 * The server runs this in its build of the editor, so what is asserted here is
 * what a statement's `sheet()` gets back: the cells, with formulas worked out,
 * named by the header or by their letters, and typed by their values.
 */
import { describe, expect, it } from "vitest";

import { joinRange, readRange, splitRange } from "./range";

const workbook = {
  sheets: [
    {
      id: "s1",
      name: "Q3 Actuals",
      cells: {
        "0:0": "Region",
        "0:1": "Amount",
        "0:2": "Due",
        "0:3": "Done",
        "1:0": "North",
        "1:1": 10,
        "1:2": "2026-01-05",
        "1:3": true,
        "2:0": "South",
        "2:1": "=B2*2",
        "2:2": "2026-02-05",
        "2:3": false,
        "3:0": "East",
        "3:1": "=Other!A1+1",
      },
    },
    { id: "s2", name: "Other", hidden: true, cells: { "0:0": 41, "0:1": "=1/0" } },
  ],
};

describe("readRange", () => {
  it("names the columns by the header, works out formulas and types the values", () => {
    expect(readRange(workbook, "Q3 Actuals!A1:D")).toEqual({
      columns: [
        { name: "Region", type: "text" },
        { name: "Amount", type: "number" },
        { name: "Due", type: "date" },
        { name: "Done", type: "boolean" },
      ],
      rows: [
        ["North", 10, "2026-01-05", true],
        ["South", 20, "2026-02-05", false],
        ["East", 42, null, null],
      ],
      sheets: ["Q3 Actuals"],
    });
  });

  it("reads open ends to the last filled cell, and the first visible sheet unnamed", () => {
    expect(readRange(workbook, "A:B")).toMatchObject({
      rows: [
        ["North", 10],
        ["South", 20],
        ["East", 42],
      ],
    });
    expect(readRange(workbook, "'Q3 Actuals'!B3:B")).toMatchObject({
      columns: [{ name: "B", type: "number" }],
      rows: [[20], [42]],
    });
    expect(readRange(workbook, "Q3 Actuals!2:3")).toMatchObject({
      columns: [
        { name: "A", type: "text" },
        { name: "B", type: "number" },
        { name: "C", type: "date" },
        { name: "D", type: "boolean" },
      ],
    });
    expect(readRange(workbook, null)).toMatchObject({
      rows: expect.arrayContaining([["East", 42, null, null]]),
    });
  });

  it("reads a hidden sheet by name, with an error as the text the grid shows", () => {
    expect(readRange(workbook, "Other")).toEqual({
      columns: [
        { name: "A", type: "number" },
        { name: "B", type: "text" },
      ],
      rows: [[41, "#DIV/0!"]],
      sheets: ["Q3 Actuals"],
    });
  });

  it("says what a range got wrong", () => {
    expect(readRange(workbook, "Q4!A1")).toEqual({
      refused: "unknown_sheet",
      sheets: ["Q3 Actuals"],
    });
    expect(readRange(workbook, "A1:B2:C3")).toMatchObject({ refused: "invalid_range" });
    expect(readRange(workbook, "A1:ZZ99999")).toMatchObject({ refused: "too_large" });
  });
});

describe("splitRange and joinRange", () => {
  it("take a range apart and put it back the way it reads", () => {
    for (const [range, parts] of [
      ["Q3 Actuals!A1:D", { sheet: "Q3 Actuals", cells: "A1:D" }],
      ["'Q3 Actuals'!A:C", { sheet: "Q3 Actuals", cells: "A:C" }],
      ["A1:D", { sheet: null, cells: "A1:D" }],
      ["Budget", { sheet: "Budget", cells: "" }],
      ["'A1'", { sheet: "A1", cells: "" }],
      ["'Wow!'", { sheet: "Wow!", cells: "" }],
    ] as const) {
      expect(splitRange(range)).toEqual(parts);
    }
    expect(joinRange("Q3 Actuals", "A1:D")).toBe("Q3 Actuals!A1:D");
    expect(joinRange("Q3 Actuals", "")).toBe("'Q3 Actuals'");
    expect(joinRange("A1", "")).toBe("'A1'");
    expect(joinRange(null, "")).toBeNull();
  });
});
