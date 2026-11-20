import { describe, expect, it } from "vitest";

import type { CellValue } from "./coords";
import { coerceScalar } from "./csv";
import { findInCells, replaceAllInCells, replaceInValue } from "./find";

const sheet = (obj: Record<string, CellValue>) => new Map(Object.entries(obj));
const loose = { matchCase: false, wholeCell: false };

describe("findInCells", () => {
  it("finds a literal substring, ignoring case unless asked, or the whole cell", () => {
    expect(findInCells(sheet({ "0:0": "Total cost", "1:0": "other" }), "total", loose)).toEqual([
      { row: 0, col: 0 },
    ]);
    const cased = sheet({ "0:0": "Total", "1:0": "total" });
    expect(findInCells(cased, "total", { matchCase: true, wholeCell: false })).toEqual([
      { row: 1, col: 0 },
    ]);
    const whole = sheet({ "0:0": "cost", "1:0": "cost of goods" });
    expect(findInCells(whole, "cost", { matchCase: false, wholeCell: true })).toEqual([
      { row: 0, col: 0 },
    ]);
    expect(findInCells(sheet({ "0:0": "a.c", "1:0": "abc" }), "a.c", loose)).toEqual([
      { row: 0, col: 0 },
    ]);
    expect(findInCells(sheet({ "0:0": "anything" }), "", loose)).toEqual([]);
  });

  it("searches the stored text: a formula's source, a number's or boolean's text", () => {
    expect(findInCells(sheet({ "0:0": "=SUM(A2:A9)" }), "sum(", loose)).toEqual([
      { row: 0, col: 0 },
    ]);
    const cells = sheet({ "0:0": 1234, "1:0": true });
    expect(findInCells(cells, "23", loose)).toEqual([{ row: 0, col: 0 }]);
    expect(findInCells(cells, "true", loose)).toEqual([{ row: 1, col: 0 }]);
  });

  it("returns matches in reading order", () => {
    const cells = sheet({ "2:0": "x", "0:5": "x", "0:1": "x", "1:9": "x" });
    expect(findInCells(cells, "x", loose)).toEqual([
      { row: 0, col: 1 },
      { row: 0, col: 5 },
      { row: 1, col: 9 },
      { row: 2, col: 0 },
    ]);
  });
});

describe("replaceInValue", () => {
  it.each([
    ["hello", "xyz", "!", loose, null],
    ["a-a-a", "a", "b", loose, "b-b-b"],
    // Case-insensitive, but the replacement is written as typed.
    ["Total total", "total", "sum", loose, "sum sum"],
    ["cost of goods", "COST OF GOODS", "x", { matchCase: false, wholeCell: true }, "x"],
    ["=SUM(A1:A9)", "A1", "B1", loose, "=SUM(B1:A9)"],
  ])("replaces in %j: %j for %j", (value, query, replacement, options, expected) => {
    expect(replaceInValue(value, query, replacement, options)).toBe(expected);
  });
});

describe("replaceAllInCells", () => {
  it("writes only the cells that changed, re-coerced, and nothing for an empty query", () => {
    const cells = sheet({ "0:0": "cost", "0:1": "other", "1:0": "cost centre" });
    expect(replaceAllInCells(cells, "cost", "price", loose, coerceScalar)).toEqual({
      "0:0": "price",
      "1:0": "price centre",
    });
    expect(replaceAllInCells(sheet({ "0:0": "12x" }), "x", "", loose, coerceScalar)["0:0"]).toBe(
      12
    );
    // Replaced down to nothing clears the cell.
    expect(
      replaceAllInCells(sheet({ "0:0": "x" }), "x", "", loose, coerceScalar)["0:0"]
    ).toBeNull();
    expect(replaceAllInCells(sheet({ "0:0": "a" }), "", "b", loose, coerceScalar)).toEqual({});
  });
});
