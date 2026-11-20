import { describe, expect, it } from "vitest";

import {
  draftResolution,
  formatSheetPrefix,
  MAX_SHEET_NAME_LENGTH,
  needsSheetQuoting,
  newSheetId,
  nextSheetName,
  quoteSheetName,
  sanitizeSheetName,
  sheetNameKey,
  uniqueSheetName,
  unquoteSheetName,
} from "@/lib/spreadsheet/sheets";

describe("sanitizeSheetName", () => {
  it("drops delimiters, collapses whitespace and trims edge quotes", () => {
    expect(sanitizeSheetName("Q1/Q2: *plan*?")).toBe("Q1Q2 plan");
    expect(sanitizeSheetName("a[b]c\\d")).toBe("abcd");
    expect(sanitizeSheetName("  Q1   Actuals  ")).toBe("Q1 Actuals");
    expect(sanitizeSheetName("'quoted'")).toBe("quoted");
    expect(sanitizeSheetName("   ")).toBe("");
    expect(sanitizeSheetName("///")).toBe("");
  });

  it("caps at Excel's limit without leaving a trailing space", () => {
    const long = `${"x".repeat(30)} tail`;
    const out = sanitizeSheetName(long);
    expect(out.length).toBeLessThanOrEqual(MAX_SHEET_NAME_LENGTH);
    expect(out).toBe("x".repeat(30));
  });
});

describe("uniqueSheetName", () => {
  it("de-duplicates case-insensitively — references resolve that way", () => {
    expect(uniqueSheetName("Data", ["Summary"])).toBe("Data");
    expect(uniqueSheetName("budget", ["BUDGET"])).toBe("budget 2");
    expect(uniqueSheetName("Data", ["Data", "Data 2"])).toBe("Data 3");
  });

  it("keeps the suffixed name inside the length cap", () => {
    const base = "y".repeat(MAX_SHEET_NAME_LENGTH);
    const out = uniqueSheetName(base, [base]);
    expect(out.length).toBeLessThanOrEqual(MAX_SHEET_NAME_LENGTH);
    expect(out.endsWith(" 2")).toBe(true);
  });
});

describe("nextSheetName", () => {
  it("picks the first free Sheet<n>", () => {
    expect(nextSheetName([])).toBe("Sheet1");
    expect(nextSheetName(["Sheet1", "Sheet3"])).toBe("Sheet2");
    expect(nextSheetName(["sheet1", "Sheet2"])).toBe("Sheet3");
  });
});

describe("quoting", () => {
  it("quotes only what would not read as a bare name, escaping apostrophes", () => {
    expect(needsSheetQuoting("Sheet2")).toBe(false);
    expect(quoteSheetName("Sheet2")).toBe("Sheet2");
    expect(formatSheetPrefix("Sheet2")).toBe("Sheet2!");
    expect(quoteSheetName("Q1 Actuals")).toBe("'Q1 Actuals'");
    expect(formatSheetPrefix("Q1 Actuals")).toBe("'Q1 Actuals'!");
    expect(quoteSheetName("2026")).toBe("'2026'");
    // Unquoted, these would parse as a cell reference / a literal.
    expect(needsSheetQuoting("A1")).toBe(true);
    expect(needsSheetQuoting("TRUE")).toBe(true);
    expect(quoteSheetName("A1")).toBe("'A1'");
    expect(quoteSheetName("Bob's Data")).toBe("'Bob''s Data'");
    expect(unquoteSheetName("'Bob''s Data'")).toBe("Bob's Data");
    expect(unquoteSheetName("Sheet2")).toBe("Sheet2");
  });
});

describe("sheetNameKey", () => {
  it("is case- and edge-whitespace-insensitive", () => {
    expect(sheetNameKey(" Data ")).toBe(sheetNameKey("DATA"));
  });
});

describe("newSheetId", () => {
  it("mints distinct ids that survive the formula-safe id charset", () => {
    const ids = new Set(Array.from({ length: 50 }, () => newSheetId()));
    expect(ids.size).toBe(50);
    for (const id of ids) expect(id).toMatch(/^[A-Za-z0-9_-]+$/);
  });
});

describe("draftResolution", () => {
  const visible = [{ id: "s1", name: "Sheet1" }];
  const hidden = [{ id: "s1", name: "Sheet1", hidden: true }];

  it("keeps an edit on screen, commits one whose sheet was hidden, drops one whose sheet went", () => {
    expect(draftResolution(visible, "s1")).toBe("keep");
    // The sheet still holds the value, so the edit belongs in it — the same
    // rule the hide menu applies before it hides anything.
    expect(draftResolution(hidden, "s1")).toBe("commit");
    expect(draftResolution(visible, "s2")).toBe("cancel");
    expect(draftResolution(visible, null)).toBe("keep");
  });
});
