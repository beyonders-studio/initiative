import { describe, expect, it } from "vitest";

import { CEILING, clipToCeiling, sheetGrid, usedRange } from "./bounds";
import type { CellValue } from "./coords";

const canvas = { rows: 100, cols: 26 };
const grid = (over: Partial<Parameters<typeof sheetGrid>[0]> = {}) =>
  sheetGrid({ bounds: canvas, ...over });

describe("usedRange", () => {
  it("spans where the data starts and ends, for a record or a Map, ignoring malformed keys", () => {
    expect(usedRange({})).toBeNull();
    expect(usedRange(new Map())).toBeNull();
    expect(usedRange({ "2:3": "a", "7:1": "b" })).toEqual({ r1: 2, c1: 1, r2: 7, c2: 3 });
    const cells = new Map<string, CellValue>([["4:4", 1]]);
    expect(usedRange(cells)).toEqual({ r1: 4, c1: 4, r2: 4, c2: 4 });
    expect(usedRange({ nonsense: 1, "1:1": 2 })).toEqual({ r1: 1, c1: 1, r2: 1, c2: 1 });
  });
});

describe("clipToCeiling", () => {
  it("keeps everything inside the ceiling, and counts what can never be rendered", () => {
    expect(clipToCeiling({ "0:0": 1, "99:25": 2 })).toEqual({
      kept: { "0:0": 1, "99:25": 2 },
      dropped: 0,
    });
    const { kept, dropped } = clipToCeiling({
      "0:0": "in",
      [`0:${CEILING.cols}`]: "past the columns",
      [`${CEILING.rows}:0`]: "past the rows",
    });
    expect(kept).toEqual({ "0:0": "in" });
    expect(dropped).toBe(2);
  });
});

describe("sheetGrid — clamping", () => {
  it("pulls a cell and a range's corners inside the canvas", () => {
    expect(grid().clampCell({ row: -5, col: 900 })).toEqual({ row: 0, col: 25 });
    expect(grid().clampRange({ r1: -1, c1: -1, r2: 500, c2: 500 })).toEqual({
      r1: 0,
      c1: 0,
      r2: 99,
      c2: 25,
    });
  });

  it("normalizes a selection from corners in any order, clamped to the canvas", () => {
    expect(grid().normalizeSelection({ row: 5, col: 5 }, { row: 2, col: 8 })).toEqual({
      r1: 2,
      c1: 5,
      r2: 5,
      c2: 8,
    });
    expect(grid().normalizeSelection({ row: 0, col: 0 }, { row: 5000, col: 5000 })).toEqual({
      r1: 0,
      c1: 0,
      r2: 99,
      c2: 25,
    });
  });
});

describe("sheetGrid — forEachCell", () => {
  it("visits every cell of the rectangle", () => {
    const seen: string[] = [];
    grid().forEachCell({ r1: 1, c1: 1, r2: 2, c2: 2 }, (r, c) => seen.push(`${r}:${c}`));
    expect(seen).toEqual(["1:1", "1:2", "2:1", "2:2"]);
  });

  it("visits a single cell", () => {
    const seen: string[] = [];
    grid().forEachCell({ r1: 4, c1: 4, r2: 4, c2: 4 }, (r, c) => seen.push(`${r}:${c}`));
    expect(seen).toEqual(["4:4"]);
  });
});

describe("sheetGrid — step", () => {
  it("moves one cell, staying put at the canvas edge", () => {
    expect(grid().step({ row: 3, col: 3 }, 1, 0)).toEqual({ row: 4, col: 3 });
    expect(grid().step({ row: 3, col: 3 }, 0, -1)).toEqual({ row: 3, col: 2 });
    expect(grid().step({ row: 0, col: 0 }, -1, -1)).toEqual({ row: 0, col: 0 });
    expect(grid().step({ row: 99, col: 25 }, 1, 1)).toEqual({ row: 99, col: 25 });
  });

  it("never lands on a hidden line", () => {
    const g = grid({ isRowHidden: (r) => r === 4 || r === 5 });
    expect(g.step({ row: 3, col: 0 }, 1, 0)).toEqual({ row: 6, col: 0 });
    expect(g.step({ row: 6, col: 0 }, -1, 0)).toEqual({ row: 3, col: 0 });
  });

  it("stays put when every line beyond is hidden", () => {
    const g = grid({ bounds: { rows: 6, cols: 3 }, isRowHidden: (r) => r >= 4 });
    expect(g.step({ row: 3, col: 0 }, 1, 0)).toEqual({ row: 3, col: 0 });
  });

  it("skips hidden columns too", () => {
    const g = grid({ isColHidden: (c) => c === 1 });
    expect(g.step({ row: 0, col: 0 }, 0, 1)).toEqual({ row: 0, col: 2 });
  });
});

describe("sheetGrid — cellsInWindow", () => {
  const size = { width: () => 100, height: () => 20 };
  const lines = (indexes: number[], step: number) =>
    indexes.map((index) => ({ index, start: index * step }));

  it("places the cross product of the two axes", () => {
    const placed = grid().cellsInWindow(lines([0, 1], 20), lines([0, 1], 100), size);
    expect(placed).toHaveLength(4);
    expect(placed[0]).toEqual({ row: 0, col: 0, left: 0, top: 0, width: 100, height: 20 });
    expect(placed[3]).toEqual({ row: 1, col: 1, left: 100, top: 20, width: 100, height: 20 });
  });

  it("leaves out hidden lines", () => {
    const g = grid({ isRowHidden: (r) => r === 0 });
    const placed = g.cellsInWindow(lines([0, 1], 20), lines([0], 100), size);
    expect(placed.map((p) => p.row)).toEqual([1]);
  });
});
