import { describe, expect, it } from "vitest";

import { clipboardToCells, coerceScalar, csvToCells, offsetCells } from "./csv";

describe("csvToCells", () => {
  it("reads a small grid", () => {
    const parsed = csvToCells("Date,Amount\n2026-05-01,42.5\n,true");
    // Numeric / boolean values get re-coerced from their string form.
    expect(parsed.cells).toEqual({
      "0:0": "Date",
      "0:1": "Amount",
      "1:0": "2026-05-01",
      "1:1": 42.5,
      "2:1": true,
    });
  });

  it("keeps embedded commas inside quotes", () => {
    expect(csvToCells('"hello, world",ok').cells).toEqual({ "0:0": "hello, world", "0:1": "ok" });
  });

  it("keeps embedded newlines inside quotes", () => {
    expect(csvToCells('"line one\nline two"').cells).toEqual({ "0:0": "line one\nline two" });
  });
});

describe("coerceScalar", () => {
  it("coerces numeric-looking strings to numbers", () => {
    expect(coerceScalar("42")).toBe(42);
    expect(coerceScalar("-3.5")).toBe(-3.5);
    expect(coerceScalar("1e3")).toBe(1000);
    expect(coerceScalar(".7")).toBe(0.7);
    expect(coerceScalar("-.25")).toBe(-0.25);
  });

  it("preserves leading zeros (likely IDs / phone numbers)", () => {
    expect(coerceScalar("0123")).toBe("0123");
    expect(coerceScalar("00")).toBe("00");
  });

  it("trims surrounding whitespace from leading-zero strings", () => {
    expect(coerceScalar(" 0123")).toBe("0123");
    expect(coerceScalar("0123 ")).toBe("0123");
    expect(coerceScalar("\t00\n")).toBe("00");
  });

  it("coerces true / false case-insensitively", () => {
    expect(coerceScalar("true")).toBe(true);
    expect(coerceScalar("FALSE")).toBe(false);
    expect(coerceScalar("TruE")).toBe(true);
  });

  it("leaves other strings alone", () => {
    expect(coerceScalar("hello")).toBe("hello");
    expect(coerceScalar("2026-05-01")).toBe("2026-05-01");
  });
});

describe("clipboardToCells", () => {
  it("splits a tab-delimited block into a grid", () => {
    expect(clipboardToCells("a\tb\nc\td")).toEqual({
      cells: { "0:0": "a", "0:1": "b", "1:0": "c", "1:1": "d" },
      rows: 2,
      cols: 2,
    });
  });

  it("keeps a sentence with commas in one cell", () => {
    expect(clipboardToCells("hi, there, friend")).toEqual({
      cells: { "0:0": "hi, there, friend" },
      rows: 1,
      cols: 1,
    });
  });

  it("puts comma text in a single column, one row per line", () => {
    expect(clipboardToCells("a,b\nc,d")).toEqual({
      cells: { "0:0": "a,b", "1:0": "c,d" },
      rows: 2,
      cols: 1,
    });
  });

  it("still splits columns when tabs and commas are mixed", () => {
    expect(clipboardToCells("hi, there\tok").cells).toEqual({
      "0:0": "hi, there",
      "0:1": "ok",
    });
  });

  it("keeps quote characters literal in untabbed prose", () => {
    expect(clipboardToCells('"quoted" thing').cells).toEqual({ "0:0": '"quoted" thing' });
  });

  it("preserves blank lines as empty rows", () => {
    expect(clipboardToCells("a\n\nb").cells).toEqual({ "0:0": "a", "2:0": "b" });
  });

  it("handles CRLF line endings", () => {
    expect(clipboardToCells("a\r\nb").cells).toEqual({ "0:0": "a", "1:0": "b" });
  });

  it("coerces scalars the same way typing does", () => {
    expect(clipboardToCells("42\ntrue").cells).toEqual({ "0:0": 42, "1:0": true });
  });

  it("returns an empty map for empty text", () => {
    expect(clipboardToCells("")).toEqual({ cells: {}, rows: 0, cols: 0 });
  });
});

describe("offsetCells", () => {
  it("shifts a cell map by the given origin", () => {
    const result = offsetCells({ "0:0": "a", "0:1": "b", "1:0": "c" }, 5, 7);
    expect(result).toEqual({ "5:7": "a", "5:8": "b", "6:7": "c" });
  });

  it("ignores malformed keys", () => {
    const result = offsetCells({ "0:0": "a", garbage: "x" }, 1, 1);
    expect(result).toEqual({ "1:1": "a" });
  });
});
