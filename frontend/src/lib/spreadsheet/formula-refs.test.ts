import { describe, expect, it } from "vitest";

import {
  extractReferences,
  isFormula,
  otherSheetFilter,
  referenceInsertTarget,
  renameSheetReferences,
  shiftFormulaReferences,
  translateFormula,
} from "./formula-refs";

// The same old-index -> new-index mappers transformSheet builds.
const insertMap =
  (at: number, count: number) =>
  (i: number): number | null =>
    i < at ? i : i + count;
const deleteMap = (at: number, count: number) => {
  const end = at + count;
  return (i: number): number | null => (i < at ? i : i >= end ? i - count : null);
};

describe("isFormula", () => {
  it("is true only for strings beginning with =", () => {
    expect(isFormula("=A1+1")).toBe(true);
    expect(isFormula("=")).toBe(true);
    expect(isFormula("A1+1")).toBe(false);
    expect(isFormula("123")).toBe(false);
    expect(isFormula(42)).toBe(false);
    expect(isFormula(true)).toBe(false);
    expect(isFormula(null)).toBe(false);
    expect(isFormula(undefined)).toBe(false);
  });
});

describe("shiftFormulaReferences", () => {
  it.each([
    // Insert 1 row at row 0: A5 (index 4) shows as A6.
    ["=A5+1", "row", insertMap(0, 1), "=A6+1"],
    // A5 is above an insert at row 5, so it stays.
    ["=A5+1", "row", insertMap(5, 1), "=A5+1"],
    ["=$A$5", "row", insertMap(0, 1), "=$A$6"],
    ["=A$5", "row", insertMap(0, 1), "=A$6"],
    // The col axis moves letters and never the row digits, and vice versa.
    ["=B5", "col", insertMap(0, 1), "=C5"],
    ["=B5", "row", insertMap(0, 1), "=B6"],
    ["=SUM(A1:A10)", "row", insertMap(0, 2), "=SUM(A3:A12)"],
    // An interior delete shrinks a range.
    ["=SUM(A1:A10)", "row", deleteMap(4, 1), "=SUM(A1:A9)"],
    ["=A5", "row", deleteMap(4, 1), "=#REF!"],
    // A deleted endpoint collapses the whole range, never =SUM(#REF!:A10).
    ["=SUM(A2:A11)", "row", deleteMap(1, 1), "=SUM(#REF!)"],
    ["=SUM(A2:A11)", "row", deleteMap(10, 1), "=SUM(#REF!)"],
    ["=A10", "row", deleteMap(4, 2), "=A8"],
    // String literals, function names and plain text are left alone.
    ['="A5 total"&A5', "row", insertMap(0, 1), '="A5 total"&A6'],
    ["=LOG10(A5)", "row", insertMap(0, 1), "=LOG10(A6)"],
    ["A5 plain text", "row", insertMap(0, 1), "A5 plain text"],
    ["=A5+B5*C1", "row", insertMap(0, 1), "=A6+B6*C2"],
  ] as const)("shifts %j on the %s axis", (formula, axis, map, expected) => {
    expect(shiftFormulaReferences(formula, axis, map)).toBe(expected);
  });
});

describe("translateFormula", () => {
  it.each([
    ["=A1+B1", 2, 0, "=A3+B3"],
    ["=A1+B1", 0, 2, "=C1+D1"],
    ["=A1", 2, 3, "=D3"],
    // $-absolute components stay pinned.
    ["=$A$1+B1", 2, 0, "=$A$1+B3"],
    ["=A$1", 2, 3, "=D$1"],
    ["=$A1", 2, 3, "=$A3"],
    // Pulled off the grid, a reference or a whole range is #REF!.
    ["=A1", -1, 0, "=#REF!"],
    ["=A1", 0, -1, "=#REF!"],
    ["=SUM(A1:A3)", 5, 0, "=SUM(A6:A8)"],
    ["=SUM(A1:A3)", -1, 0, "=SUM(#REF!)"],
    ['="A1 total"&A1', 1, 0, '="A1 total"&A2'],
    ["=LOG10(A1)", 1, 0, "=LOG10(A2)"],
    ["plain A1", 1, 0, "plain A1"],
  ])("moves %j by %i rows and %i cols", (formula, rows, cols, expected) => {
    expect(translateFormula(formula, rows, cols)).toBe(expected);
  });
});

describe("extractReferences", () => {
  it("finds nothing outside a formula, in a string literal, or in a function name", () => {
    expect(extractReferences("hello")).toEqual([]);
    expect(extractReferences("123")).toEqual([]);
    expect(extractReferences('="A5 total"')).toEqual([]);
    expect(extractReferences("=LOG10(2)")).toEqual([]);
    expect(extractReferences("=SUM(1,2)")).toEqual([]);
  });

  it("locates a single cell reference with its box and span", () => {
    // "=A1" — A1 is row 0, col 0; the token spans offsets 1..3 in "=A1".
    expect(extractReferences("=A1")).toEqual([
      { text: "A1", start: 1, end: 3, r1: 0, c1: 0, r2: 0, c2: 0, sheet: null, colorIndex: 0 },
    ]);
  });

  it("normalizes a range to a single token / box", () => {
    const [ref] = extractReferences("=SUM(B2:C4)");
    expect(ref).toMatchObject({ text: "B2:C4", r1: 1, c1: 1, r2: 3, c2: 2 });
    expect(ref.start).toBe(5);
    expect(ref.end).toBe(10);
  });

  it("colours distinct references in appearance order, repeats alike, each at its offset", () => {
    expect(extractReferences("=A1+B2").map((r) => r.colorIndex)).toEqual([0, 1]);
    expect(extractReferences("=A1+A1").map((r) => r.colorIndex)).toEqual([0, 0]);
    const refs = extractReferences("=A1+B2");
    expect(refs.map((r) => [r.start, r.end])).toEqual([
      [1, 3],
      [4, 6],
    ]);
  });

  it("captures absolute ($) references with the $ markers in the text", () => {
    const [ref] = extractReferences("=$A$1");
    expect(ref).toMatchObject({ text: "$A$1", r1: 0, c1: 0, r2: 0, c2: 0 });
  });
});

describe("referenceInsertTarget", () => {
  it("inserts after the leading = ", () => {
    expect(referenceInsertTarget("=", 1)).toEqual({ kind: "insert", at: 1 });
  });

  it("inserts after an operator, ( or ,", () => {
    expect(referenceInsertTarget("=A1+", 4)).toEqual({ kind: "insert", at: 4 });
    expect(referenceInsertTarget("=SUM(", 5)).toEqual({ kind: "insert", at: 5 });
    expect(referenceInsertTarget("=SUM(A1,", 8)).toEqual({ kind: "insert", at: 8 });
  });

  it("inserts after trailing whitespace following an operator", () => {
    expect(referenceInsertTarget("=A1+ ", 5)).toEqual({ kind: "insert", at: 5 });
  });

  it("replaces a reference that follows the = or an operator", () => {
    expect(referenceInsertTarget("=A1", 3)).toEqual({ kind: "replace", start: 1, end: 3 });
    expect(referenceInsertTarget("=SUM(A1", 7)).toEqual({ kind: "replace", start: 5, end: 7 });
    expect(referenceInsertTarget("=B2+C3", 6)).toEqual({ kind: "replace", start: 4, end: 6 });
  });

  it("returns none mid-literal or for a non-formula", () => {
    expect(referenceInsertTarget("=hello", 6)).toEqual({ kind: "none" });
    expect(referenceInsertTarget("plain", 5)).toEqual({ kind: "none" });
  });
});

describe("sheet-qualified references", () => {
  it("does not mistake a sheet name for a cell reference", () => {
    // "Sheet2" alone matches the A1 pattern (letters then digits); the
    // trailing "!" is what tells the two apart.
    expect(extractReferences("=Sheet2!A1").map((t) => t.text)).toEqual(["Sheet2!A1"]);
    expect(shiftFormulaReferences("=Sheet2!A1", "row", insertMap(0, 1))).toBe("=Sheet2!A1");
  });

  it("records the sheet a token names", () => {
    const [local, qualified, quoted] = extractReferences("=A1+Data!B2+'Q1 Actuals'!C3");
    expect(local.sheet).toBeNull();
    expect(qualified.sheet).toBe("Data");
    expect(quoted.sheet).toBe("Q1 Actuals");
    expect(quoted.text).toBe("'Q1 Actuals'!C3");
    // The box is the referenced cell, wherever it lives.
    expect({ r1: qualified.r1, c1: qualified.c1 }).toEqual({ r1: 1, c1: 1 });
  });

  it("treats a qualified range as one token", () => {
    const [token] = extractReferences("=SUM(Data!A1:B3)");
    expect(token.text).toBe("Data!A1:B3");
    expect(token.sheet).toBe("Data");
    expect({ r1: token.r1, c1: token.c1, r2: token.r2, c2: token.c2 }).toEqual({
      r1: 0,
      c1: 0,
      r2: 2,
      c2: 1,
    });
  });

  it("leaves other sheets' references alone by default", () => {
    // Inserting a row here must not move a reference into a sheet that
    // didn't change.
    expect(shiftFormulaReferences("=A5+Data!A5", "row", insertMap(0, 1))).toBe("=A6+Data!A5");
  });

  it("collapses a deleted qualified reference to a bare #REF!", () => {
    // "Data!#REF!" is not valid input to the evaluator's grammar, and the
    // token is already unambiguous on its own.
    expect(
      shiftFormulaReferences("=Data!A5", "row", deleteMap(4, 1), otherSheetFilter("Data"))
    ).toBe("=#REF!");
  });

  it("translates a qualified reference's coordinates but keeps its sheet", () => {
    // Copying "=Data!A1" one row down gives "=Data!A2" (Excel).
    expect(translateFormula("=Data!A1", 1, 0)).toBe("=Data!A2");
    expect(translateFormula("='Q1 Actuals'!$A1", 2, 3)).toBe("='Q1 Actuals'!$A3");
  });

  it("recognizes a qualified reference in point mode", () => {
    expect(referenceInsertTarget("=Data!A1", 8)).toEqual({ kind: "replace", start: 1, end: 8 });
    expect(referenceInsertTarget("='Q1 Actuals'!A1", 16)).toEqual({
      kind: "replace",
      start: 1,
      end: 16,
    });
  });
});

describe("renameSheetReferences", () => {
  it.each([
    // Only the renamed sheet, matched case-insensitively, in both endpoints.
    ["=Data!A1+Other!B2+A3", "Data", "Numbers", "=Numbers!A1+Other!B2+A3"],
    ["=dAtA!A1", "Data", "Numbers", "=Numbers!A1"],
    ["=SUM(Data!A1:B3)", "Data", "Numbers", "=SUM(Numbers!A1:B3)"],
    // Re-quoted when the new name needs it, unquoted when it doesn't; "Q1"
    // reads as a cell reference, so it stays quoted.
    ["=Data!A1", "Data", "Q1 Actuals", "='Q1 Actuals'!A1"],
    ["='Q1 Actuals'!A1", "Q1 Actuals", "Actuals", "=Actuals!A1"],
    ["=Data!A1", "Data", "Q1", "='Q1'!A1"],
    ["=A1+B2", "Data", "Numbers", "=A1+B2"],
    ['="Data!A1"', "Data", "Numbers", '="Data!A1"'],
  ])("re-spells %j from %s to %s", (formula, from, to, expected) => {
    expect(renameSheetReferences(formula, from, to)).toBe(expected);
  });
});
