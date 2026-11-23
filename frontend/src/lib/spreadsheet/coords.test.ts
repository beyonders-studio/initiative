import { describe, expect, it } from "vitest";

import {
  boundingBox,
  colIndexToLetter,
  keyOf,
  letterToColIndex,
  parseA1Range,
  parseKey,
} from "./coords";

describe("colIndexToLetter / letterToColIndex", () => {
  it.each([
    [0, "A"],
    [25, "Z"],
    [26, "AA"],
    [51, "AZ"],
    [52, "BA"],
    [701, "ZZ"],
    [702, "AAA"],
  ])("round-trips column %i as %s", (index, letter) => {
    expect(colIndexToLetter(index)).toBe(letter);
    expect(letterToColIndex(letter)).toBe(index);
  });

  it("parses case-insensitively, and refuses what is not a column", () => {
    expect(letterToColIndex("aa")).toBe(26);
    expect(letterToColIndex("Aa")).toBe(26);
    for (const bad of ["", "A1", "@"]) expect(letterToColIndex(bad)).toBe(-1);
    expect(colIndexToLetter(-1)).toBe("");
    expect(colIndexToLetter(0.5)).toBe("");
  });
});

describe("keyOf / parseKey", () => {
  it("round-trips r:c keys and rejects malformed ones", () => {
    expect(keyOf(0, 0)).toBe("0:0");
    expect(keyOf(7, 12)).toBe("7:12");
    expect(parseKey("7:12")).toEqual([7, 12]);
    for (const bad of ["A1", "0,0", "0", ""]) expect(parseKey(bad)).toBeNull();
  });
});

describe("boundingBox", () => {
  it("is max + 1 in each dimension, for a record or a Map, ignoring malformed keys", () => {
    expect(boundingBox({})).toEqual({ rows: 0, cols: 0 });
    expect(boundingBox(new Map())).toEqual({ rows: 0, cols: 0 });
    expect(boundingBox({ "0:0": "a", "2:5": 42, "1:7": true })).toEqual({ rows: 3, cols: 8 });
    expect(boundingBox({ "0:0": "a", garbage: 1, "5:5": 2 })).toEqual({ rows: 6, cols: 6 });
    const map = new Map<string, string | number>([
      ["0:0", "a"],
      ["3:1", 99],
    ]);
    expect(boundingBox(map)).toEqual({ rows: 4, cols: 2 });
  });
});

describe("parseA1Range", () => {
  it.each([
    ["B12", { r1: 11, c1: 1, r2: 11, c2: 1 }],
    ["A1", { r1: 0, c1: 0, r2: 0, c2: 0 }],
    ["A1:C3", { r1: 0, c1: 0, r2: 2, c2: 2 }],
    // Endpoint order is normalized; case, whitespace and $ anchors are tolerated.
    ["C3:A1", { r1: 0, c1: 0, r2: 2, c2: 2 }],
    ["  aa2  ", { r1: 1, c1: 26, r2: 1, c2: 26 }],
    ["$A$1:$B$2", { r1: 0, c1: 0, r2: 1, c2: 1 }],
  ])("parses %j", (text, expected) => {
    expect(parseA1Range(text)).toEqual(expected);
  });

  it("rejects non-references", () => {
    for (const bad of ["", "1", "A", "A0", "1A", "A1:", ":A1", "foo", "A1 B2"]) {
      expect(parseA1Range(bad)).toBeNull();
    }
  });
});
