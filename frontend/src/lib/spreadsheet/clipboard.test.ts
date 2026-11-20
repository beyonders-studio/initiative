import { describe, expect, it } from "vitest";

import {
  type Clip,
  type ClipReader,
  clipFromSelection,
  clipMatchesClipboard,
  placeClip,
  rangeToTsv,
} from "./clipboard";
import type { CellRange, CellValue } from "./coords";
import type { CellFmt } from "./styles";

const readerOf = (
  cells: Record<string, CellValue>,
  styles: Record<string, CellFmt> = {},
  display: Record<string, CellValue> = {}
): ClipReader => ({
  raw: (r, c) => cells[`${r}:${c}`] ?? null,
  style: (r, c) => styles[`${r}:${c}`],
  display: (r, c) => display[`${r}:${c}`] ?? cells[`${r}:${c}`] ?? null,
});

const range = (r1: number, c1: number, r2: number, c2: number): CellRange => ({ r1, c1, r2, c2 });

const take = (
  mode: "copy" | "cut",
  cells: Record<string, CellValue>,
  box: CellRange,
  extra: { styles?: Record<string, CellFmt>; display?: Record<string, CellValue> } = {}
): Clip =>
  clipFromSelection(
    mode,
    { sheetId: "s1", sheetName: "Sheet1", range: box },
    readerOf(cells, extra.styles, extra.display)
  );

describe("rangeToTsv", () => {
  it("writes displayed values, tab-separated, row per line", () => {
    const read = readerOf({ "0:0": 1, "0:1": "two", "1:0": true });
    expect(rangeToTsv(range(0, 0, 1, 1), read.display)).toBe("1\ttwo\ntrue\t");
  });

  it("writes what a formula shows, not the formula", () => {
    const read = readerOf({ "0:0": "=1+1" }, {}, { "0:0": 2 });
    expect(rangeToTsv(range(0, 0, 0, 0), read.display)).toBe("2");
  });
});

describe("clipFromSelection", () => {
  it("keys cells by offset from the block's top-left", () => {
    const clip = take("copy", { "5:5": "a", "6:6": "b" }, range(5, 5, 6, 6));
    expect(clip.cells).toEqual({ "0:0": "a", "1:1": "b" });
  });

  it("keeps formulas as written", () => {
    const clip = take("copy", { "0:0": "=B1*2" }, range(0, 0, 0, 0), { display: { "0:0": 8 } });
    expect(clip.cells["0:0"]).toBe("=B1*2");
    expect(clip.text).toBe("8");
  });

  it("carries formatting", () => {
    const clip = take("copy", { "0:0": 1 }, range(0, 0, 0, 0), {
      styles: { "0:0": { style: { bold: true } } },
    });
    expect(clip.styles["0:0"]).toEqual({ style: { bold: true } });
  });

  it("skips empty cells and empty styles", () => {
    const clip = take("copy", { "0:0": 1 }, range(0, 0, 1, 1), { styles: { "0:1": {} } });
    expect(Object.keys(clip.cells)).toEqual(["0:0"]);
    expect(clip.styles).toEqual({});
  });

  it("starts with no merges", () => {
    expect(take("copy", { "0:0": 1 }, range(0, 0, 0, 0)).merges).toEqual([]);
  });
});

describe("placeClip — copy", () => {
  it("lands the block at the target", () => {
    const clip = take("copy", { "0:0": "a", "0:1": "b" }, range(0, 0, 0, 1));
    const placed = placeClip(clip, { sheetId: "s1", row: 3, col: 4 });
    expect(placed.cells).toEqual({ "3:4": "a", "3:5": "b" });
    expect(placed.target).toEqual(range(3, 4, 3, 5));
  });

  it("translates relative references by the move", () => {
    const clip = take("copy", { "0:0": "=A2*2" }, range(0, 0, 0, 0));
    const placed = placeClip(clip, { sheetId: "s1", row: 3, col: 0 });
    expect(placed.cells["3:0"]).toBe("=A5*2");
  });

  it("leaves absolute references pinned", () => {
    const clip = take("copy", { "0:0": "=$A$2*2" }, range(0, 0, 0, 0));
    const placed = placeClip(clip, { sheetId: "s1", row: 3, col: 0 });
    expect(placed.cells["3:0"]).toBe("=$A$2*2");
  });

  it("keeps a cross-sheet reference pointing at its sheet", () => {
    const clip = take("copy", { "0:0": "=Data!A2" }, range(0, 0, 0, 0));
    const placed = placeClip(clip, { sheetId: "s2", row: 1, col: 0 });
    expect(placed.cells["1:0"]).toBe("=Data!A3");
  });

  it("clears nothing", () => {
    const clip = take("copy", { "0:0": "a" }, range(0, 0, 0, 0));
    expect(placeClip(clip, { sheetId: "s1", row: 9, col: 9 }).clear).toEqual([]);
  });

  it("carries formatting to the target", () => {
    const clip = take("copy", { "0:0": 1 }, range(0, 0, 0, 0), {
      styles: { "0:0": { style: { bold: true } } },
    });
    const placed = placeClip(clip, { sheetId: "s1", row: 2, col: 2 });
    expect(placed.styles).toEqual({ "2:2": { style: { bold: true } } });
  });
});

describe("placeClip — cut", () => {
  it("moves references verbatim within a sheet", () => {
    const clip = take("cut", { "0:0": "=A2*2" }, range(0, 0, 0, 0));
    const placed = placeClip(clip, { sheetId: "s1", row: 5, col: 0 });
    expect(placed.cells["5:0"]).toBe("=A2*2");
  });

  it("reports the source cells to clear", () => {
    const clip = take("cut", { "0:0": "a", "1:1": "b" }, range(0, 0, 1, 1));
    const placed = placeClip(clip, { sheetId: "s1", row: 4, col: 4 });
    expect(placed.clear.sort()).toEqual(["0:0", "0:1", "1:0", "1:1"]);
  });

  it("names the source sheet on references that named none, crossing sheets", () => {
    const clip = take("cut", { "0:0": "=A2+B2" }, range(0, 0, 0, 0));
    const placed = placeClip(clip, { sheetId: "s2", row: 0, col: 0 });
    expect(placed.cells["0:0"]).toBe("=Sheet1!A2+Sheet1!B2");
  });

  it("names the source sheet once on a range", () => {
    const clip = take("cut", { "0:0": "=SUM(A2:B9)" }, range(0, 0, 0, 0));
    const placed = placeClip(clip, { sheetId: "s2", row: 0, col: 0 });
    expect(placed.cells["0:0"]).toBe("=SUM(Sheet1!A2:B9)");
  });

  it("leaves a reference that already named a sheet alone", () => {
    const clip = take("cut", { "0:0": "=Other!A2" }, range(0, 0, 0, 0));
    const placed = placeClip(clip, { sheetId: "s2", row: 0, col: 0 });
    expect(placed.cells["0:0"]).toBe("=Other!A2");
  });

  it("does not qualify a move that stays on its own sheet", () => {
    const clip = take("cut", { "0:0": "=A2" }, range(0, 0, 0, 0));
    const placed = placeClip(clip, { sheetId: "s1", row: 7, col: 0 });
    expect(placed.cells["7:0"]).toBe("=A2");
  });
});

describe("placeClip — blanks in the copied block", () => {
  it("clears a destination cell the source had empty", () => {
    // A 2x1 block whose second cell is blank.
    const clip = take("copy", { "0:0": "a" }, range(0, 0, 1, 0));
    const placed = placeClip(clip, { sheetId: "s1", row: 5, col: 0 });
    expect(placed.cells).toEqual({ "5:0": "a", "6:0": null });
  });

  it("covers the whole rectangle even when the source was entirely empty", () => {
    const clip = take("copy", {}, range(0, 0, 1, 1));
    const placed = placeClip(clip, { sheetId: "s1", row: 0, col: 0 });
    expect(placed.cells).toEqual({ "0:0": null, "0:1": null, "1:0": null, "1:1": null });
  });
});

describe("clipMatchesClipboard", () => {
  it("holds a copy, or a cut that reached the clipboard, only while its text is still there", () => {
    expect(clipMatchesClipboard(null, "anything")).toBe(false);
    const copy = take("copy", { "0:0": "a" }, range(0, 0, 0, 0));
    expect(clipMatchesClipboard(copy, "a")).toBe(true);
    expect(clipMatchesClipboard(copy, "from another app")).toBe(false);
    // A cut whose text never reached the clipboard holds regardless.
    const cut = take("cut", { "0:0": "a" }, range(0, 0, 0, 0));
    expect(clipMatchesClipboard(cut, "from another app")).toBe(true);
    const copiedCut = { ...cut, textOnClipboard: true };
    expect(clipMatchesClipboard(copiedCut, "a")).toBe(true);
    expect(clipMatchesClipboard(copiedCut, "from another app")).toBe(false);
  });
});
