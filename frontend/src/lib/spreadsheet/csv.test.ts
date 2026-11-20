import { describe, expect, it } from "vitest";

import { clipboardToCells, coerceScalar, csvToCells, offsetCells } from "./csv";

describe("csvToCells", () => {
  it("reads a grid, re-coercing values, with commas and newlines inside quotes", () => {
    expect(csvToCells("Date,Amount\n2026-05-01,42.5\n,true").cells).toEqual({
      "0:0": "Date",
      "0:1": "Amount",
      "1:0": "2026-05-01",
      "1:1": 42.5,
      "2:1": true,
    });
    expect(csvToCells('"hello, world",ok').cells).toEqual({ "0:0": "hello, world", "0:1": "ok" });
    expect(csvToCells('"line one\nline two"').cells).toEqual({ "0:0": "line one\nline two" });
  });
});

describe("coerceScalar", () => {
  it.each([
    ["42", 42],
    ["-3.5", -3.5],
    ["1e3", 1000],
    [".7", 0.7],
    ["-.25", -0.25],
    // Leading zeros are kept (likely IDs or phone numbers), trimmed.
    ["0123", "0123"],
    ["00", "00"],
    [" 0123", "0123"],
    ["0123 ", "0123"],
    ["\t00\n", "00"],
    ["true", true],
    ["FALSE", false],
    ["TruE", true],
    ["hello", "hello"],
    ["2026-05-01", "2026-05-01"],
  ])("coerces %j to %j", (text, expected) => {
    expect(coerceScalar(text)).toBe(expected);
  });
});

describe("clipboardToCells", () => {
  it("splits a tab-delimited block into a grid", () => {
    expect(clipboardToCells("a\tb\nc\td")).toEqual({
      cells: { "0:0": "a", "0:1": "b", "1:0": "c", "1:1": "d" },
      rows: 2,
      cols: 2,
    });
    expect(clipboardToCells("")).toEqual({ cells: {}, rows: 0, cols: 0 });
  });

  it("puts comma text in a single column, one row per line", () => {
    expect(clipboardToCells("a,b\nc,d")).toEqual({
      cells: { "0:0": "a,b", "1:0": "c,d" },
      rows: 2,
      cols: 1,
    });
  });

  it.each([
    ["a sentence with commas stays one cell", "hi, there, friend", { "0:0": "hi, there, friend" }],
    ["tabs still split mixed text", "hi, there\tok", { "0:0": "hi, there", "0:1": "ok" }],
    ["quotes stay literal in prose", '"quoted" thing', { "0:0": '"quoted" thing' }],
    ["blank lines are empty rows", "a\n\nb", { "0:0": "a", "2:0": "b" }],
    ["CRLF line endings", "a\r\nb", { "0:0": "a", "1:0": "b" }],
    ["scalars coerce as typing does", "42\ntrue", { "0:0": 42, "1:0": true }],
  ])("%s", (_why, text, expected) => {
    expect(clipboardToCells(text).cells).toEqual(expected);
  });
});

describe("offsetCells", () => {
  it("shifts a cell map by the given origin, dropping malformed keys", () => {
    expect(offsetCells({ "0:0": "a", "0:1": "b", "1:0": "c", garbage: "x" }, 5, 7)).toEqual({
      "5:7": "a",
      "5:8": "b",
      "6:7": "c",
    });
  });
});
