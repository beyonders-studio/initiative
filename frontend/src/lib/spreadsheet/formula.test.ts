import { describe, expect, it } from "vitest";

import type { CellValue } from "./coords";
import { createEvaluator } from "./formula";

const sheet = (obj: Record<string, CellValue>) => createEvaluator(new Map(Object.entries(obj)));

/** Evaluate the formula sitting in A1 (key "0:0"), with optional extra
 *  cells in the surrounding map. Returns the CellResult. */
const evalA1 = (formula: string, rest: Record<string, CellValue> = {}) =>
  sheet({ "0:0": formula, ...rest }).evaluate(0, 0);

const workbook = (
  sheets: { id: string; name: string; cells: Record<string, CellValue> }[],
  activeSheetId = sheets[0].id
) =>
  createEvaluator({
    sheets: sheets.map((s) => ({ ...s, cells: new Map(Object.entries(s.cells)) })),
    activeSheetId,
  });

describe("evaluating one cell", () => {
  // B1 is "0:1", A2..A4 are "1:0".."3:0".
  it.each<[string, Record<string, CellValue>, CellValue]>([
    ["=1+2*3", {}, 7],
    ["=(1+2)*3", {}, 9],
    ["=2^3", {}, 8],
    ["=-5+2", {}, -3],
    // A decimal written without its leading zero.
    ["=.5*2", {}, 1],
    ["=SUM(-.25,1.5)", {}, 1.25],
    ['=".5"&.5', {}, ".50.5"],
    ["=50%", {}, 0.5],
    ['="a"&"b"', {}, "ab"],
    ["=1<2", {}, true],
    ["=2<=1", {}, false],
    ["=B1+C1", { "0:1": 2, "0:2": 3 }, 5],
    ["=SUM(A2:A4)", { "1:0": 10, "2:0": 20, "3:0": 30 }, 60],
    ["=AVERAGE(A2:A3)", { "1:0": 4, "2:0": 8 }, 6],
    ["=MIN(A2:A3)", { "1:0": 4, "2:0": 8 }, 4],
    ["=MAX(A2:A3)", { "1:0": 4, "2:0": 8 }, 8],
    // COUNT skips text; COUNTA counts anything non-empty.
    ["=COUNT(A2:A4)", { "1:0": 4, "2:0": 8, "3:0": "x" }, 2],
    ["=COUNTA(A2:A4)", { "1:0": 4, "2:0": 8, "3:0": "x" }, 3],
    // An empty referenced cell is zero in arithmetic.
    ["=A2+1", {}, 1],
    ['=IF(A2>10,"hi","lo")', { "1:0": 20 }, "hi"],
    ['=IF(A2>10,"hi","lo")', { "1:0": 5 }, "lo"],
    ["=ROUND(3.14159,2)", {}, 3.14],
    ["=ABS(-5)", {}, 5],
  ])("%s is %j", (formula, rest, expected) => {
    expect(evalA1(formula, rest).value).toBe(expected);
  });

  it.each<[string, Record<string, CellValue>, string]>([
    ["=FOO(1)", {}, "#NAME?"],
    // Nothing that would reach outside the workbook is a known name.
    ['=WEBSERVICE("https://example.com")', {}, "#NAME?"],
    ['=FILTERXML("<a/>","//a")', {}, "#NAME?"],
    ["=1/0", {}, "#DIV/0!"],
    ['="abc"+1', {}, "#VALUE!"],
    // The first error propagates, through a reference too.
    ["=1/0+1", {}, "#DIV/0!"],
    ["=A2+1", { "1:0": "=1/0" }, "#DIV/0!"],
  ])("%s fails with %s", (formula, rest, expected) => {
    expect(evalA1(formula, rest).error).toBe(expected);
  });
});

describe("cycles", () => {
  it("flags a direct self-reference", () => {
    expect(evalA1("=A1+1").error).toBe("#CYCLE!");
  });

  it("flags a mutual reference", () => {
    const cells = { "0:0": "=B1", "0:1": "=A1" };
    const ev = createEvaluator(new Map(Object.entries(cells)));
    expect(ev.evaluate(0, 0).error).toBe("#CYCLE!");
    expect(ev.evaluate(0, 1).error).toBe("#CYCLE!");
  });
});

describe("chained formulas", () => {
  it("evaluates a dependency chain", () => {
    // A1=2, B1==A1*2, C1==B1+1  -> C1 = 5
    const cells = { "0:0": 2, "0:1": "=A1*2", "0:2": "=B1+1" };
    expect(createEvaluator(new Map(Object.entries(cells))).evaluate(0, 2).value).toBe(5);
  });
});

describe("cross-sheet references", () => {
  it("resolves a qualified cell reference", () => {
    const e = workbook([
      { id: "s1", name: "Summary", cells: { "0:0": "=Data!A1" } },
      { id: "s2", name: "Data", cells: { "0:0": 42 } },
    ]);
    expect(e.evaluate(0, 0)).toEqual({ value: 42, error: null });
  });

  it("resolves a qualified range through a function", () => {
    const e = workbook([
      { id: "s1", name: "Summary", cells: { "0:0": "=SUM(Data!A1:A3)" } },
      { id: "s2", name: "Data", cells: { "0:0": 1, "1:0": 2, "2:0": 3 } },
    ]);
    expect(e.evaluate(0, 0)).toEqual({ value: 6, error: null });
  });

  it("matches sheet names case-insensitively", () => {
    const e = workbook([
      { id: "s1", name: "Summary", cells: { "0:0": "=dAtA!A1" } },
      { id: "s2", name: "Data", cells: { "0:0": 7 } },
    ]);
    expect(e.evaluate(0, 0).value).toBe(7);
  });

  it("accepts a quoted sheet name", () => {
    const e = workbook([
      { id: "s1", name: "Summary", cells: { "0:0": "='Q1 Actuals'!B2" } },
      { id: "s2", name: "Q1 Actuals", cells: { "1:1": 12 } },
    ]);
    expect(e.evaluate(0, 0).value).toBe(12);
  });

  it("reports #REF! for a sheet that doesn't exist", () => {
    const e = workbook([{ id: "s1", name: "Summary", cells: { "0:0": "=Gone!A1" } }]);
    expect(e.evaluate(0, 0)).toEqual({ value: null, error: "#REF!" });
  });

  it("evaluates a formula on a non-active sheet against its own sheet", () => {
    // B's "=A1" must read B's own A1, not the active sheet's.
    const e = workbook(
      [
        { id: "s1", name: "A", cells: { "0:0": 1 } },
        { id: "s2", name: "B", cells: { "0:0": 100, "0:1": "=A1" } },
      ],
      "s1"
    );
    expect(e.evaluate(0, 1, "s2").value).toBe(100);
  });

  it("chains a formula through another sheet", () => {
    const e = workbook([
      { id: "s1", name: "Summary", cells: { "0:0": "=Data!A1*2" } },
      { id: "s2", name: "Data", cells: { "0:0": "=B1+1", "0:1": 4 } },
    ]);
    expect(e.evaluate(0, 0).value).toBe(10);
  });

  it("detects a cycle that only closes by hopping sheets", () => {
    const e = workbook([
      { id: "s1", name: "One", cells: { "0:0": "=Two!A1" } },
      { id: "s2", name: "Two", cells: { "0:0": "=One!A1" } },
    ]);
    expect(e.evaluate(0, 0).error).toBe("#CYCLE!");
  });
});

describe("formulas that read other formula cells", () => {
  it("passes a formula cell as a function argument", () => {
    expect(evalA1("=IF(B2<0,0,B2)", { "1:1": "=1+1" }).value).toBe(2);
  });

  it("aggregates a range made entirely of formula cells", () => {
    expect(evalA1("=SUM(A2:A4)", { "1:0": "=1*1", "2:0": "=2*2", "3:0": "=3*3" }).value).toBe(14);
  });

  it("nests several levels deep", () => {
    expect(
      evalA1("=SUM(A2:A3)", {
        "1:0": "=MAX(A4,A5)",
        "2:0": "=MIN(A4,A5)",
        "3:0": 10,
        "4:0": "=2+3",
      }).value
    ).toBe(15);
  });

  it("evaluates identically whatever order the cells are asked for", () => {
    const cells = { "0:0": "=IF(B2<0,0,B2)", "1:1": "=1+1" };
    // Cold: the dependency is resolved mid-parse of the outer formula.
    expect(sheet(cells).evaluate(0, 0).value).toBe(2);
    // Warm: the dependency was evaluated (and cached) first.
    const warm = sheet(cells);
    warm.evaluate(1, 1);
    expect(warm.evaluate(0, 0).value).toBe(2);
  });

  it("passes a formula cell from another sheet as a function argument", () => {
    const e = workbook([
      { id: "s1", name: "Summary", cells: { "0:0": "=IF(Data!A1>0,Data!A1,0)" } },
      { id: "s2", name: "Data", cells: { "0:0": "=B1+1", "0:1": 4 } },
    ]);
    expect(e.evaluate(0, 0).value).toBe(5);
  });

  it("still reports a cycle reached through a function argument", () => {
    expect(evalA1("=IF(A1>0,1,2)").error).toBe("#CYCLE!");
  });

  it("still reports a cycle that closes two formulas away", () => {
    expect(evalA1("=IF(B1>0,1,2)", { "0:1": "=A1+1" }).error).toBe("#CYCLE!");
  });
});

describe("functions the library leaves unimplemented", () => {
  // A2..A6 = 4, 8, 1, 9, 6 — a set with a clear median and no ties.
  const data = { "1:0": 4, "2:0": 8, "3:0": 1, "4:0": 9, "5:0": 6 };

  it("MEDIAN of an odd and an even count", () => {
    expect(evalA1("=MEDIAN(A2:A6)", data).value).toBe(6);
    expect(evalA1("=MEDIAN(1,2,3,4)").value).toBe(2.5);
    expect(evalA1("=MEDIAN(A2:A3)", {}).error).toBe("#NUM!");
  });

  it("LARGE and SMALL count from opposite ends, 1-based", () => {
    expect(evalA1("=LARGE(A2:A6,1)", data).value).toBe(9);
    expect(evalA1("=LARGE(A2:A6,2)", data).value).toBe(8);
    expect(evalA1("=SMALL(A2:A6,1)", data).value).toBe(1);
    expect(evalA1("=SMALL(A2:A6,9)", data).error).toBe("#NUM!");
  });

  it("RANK orders largest-first by default", () => {
    expect(evalA1("=RANK(9,A2:A6)", data).value).toBe(1);
    expect(evalA1("=RANK(1,A2:A6)", data).value).toBe(5);
    expect(evalA1("=RANK(1,A2:A6,1)", data).value).toBe(1);
    expect(evalA1("=RANK(7,A2:A6)", data).error).toBe("#N/A");
  });

  it("STDEV and VAR treat their input as a sample, STDEVP/VARP as everything", () => {
    const set = { "1:0": 2, "2:0": 4, "3:0": 4, "4:0": 4, "5:0": 5, "6:0": 5, "7:0": 7, "8:0": 9 };
    expect(evalA1("=VARP(A2:A9)", set).value).toBe(4);
    expect(evalA1("=STDEVP(A2:A9)", set).value).toBe(2);
    expect(evalA1("=VAR(A2:A9)", set).value).toBeCloseTo(4.571, 3);
    expect(evalA1("=STDEV(A2:A9)", set).value).toBeCloseTo(2.138, 3);
    expect(evalA1("=STDEV(A2:A2)", { "1:0": 1 }).error).toBe("#DIV/0!");
  });

  it("COUNTBLANK counts the empties a range covers", () => {
    expect(evalA1("=COUNTBLANK(A2:A5)", { "1:0": 1, "3:0": 3 }).value).toBe(2);
  });

  it("UPPER", () => {
    expect(evalA1('=UPPER("aBc")').value).toBe("ABC");
  });

  it("SUBSTITUTE replaces every occurrence, or one named instance", () => {
    expect(evalA1('=SUBSTITUTE("a-a-a","a","b")').value).toBe("b-b-b");
    expect(evalA1('=SUBSTITUTE("a-a-a","a","b",2)').value).toBe("a-b-a");
    expect(evalA1('=SUBSTITUTE("abc","","z")').value).toBe("abc");
    expect(evalA1('=SUBSTITUTE("abc","a","z",0)').error).toBe("#VALUE!");
  });

  it("TEXTJOIN joins, dropping empties unless told otherwise", () => {
    expect(evalA1('=TEXTJOIN(", ",TRUE,"a","b")').value).toBe("a, b");
    expect(evalA1('=TEXTJOIN("-",TRUE,A2:A4)', { "1:0": "a", "3:0": "c" }).value).toBe("a-c");
    expect(evalA1('=TEXTJOIN("-",FALSE,A2:A4)', { "1:0": "a", "3:0": "c" }).value).toBe("a--c");
  });

  it("VALUE reads a number out of text", () => {
    expect(evalA1('=VALUE("12.5")').value).toBe(12.5);
    expect(evalA1('=VALUE("1,200")').value).toBe(1200);
    expect(evalA1('=VALUE("abc")').error).toBe("#VALUE!");
  });

  it("SEARCH ignores case where FIND does not", () => {
    expect(evalA1('=SEARCH("B","abc")').value).toBe(2);
    expect(evalA1('=FIND("B","abc")').error).toBe("#VALUE!");
    expect(evalA1('=SEARCH("a","banana",3)').value).toBe(4);
    expect(evalA1('=SEARCH("z","abc")').error).toBe("#VALUE!");
  });

  it("MATCH finds a position, exactly or by closest-not-past", () => {
    expect(evalA1("=MATCH(8,A2:A6,0)", data).value).toBe(2);
    expect(evalA1("=MATCH(7,A2:A6,0)", data).error).toBe("#N/A");
    const sorted = { "1:0": 1, "2:0": 5, "3:0": 9 };
    expect(evalA1("=MATCH(7,A2:A4,1)", sorted).value).toBe(2);
    expect(evalA1('=MATCH("b",A2:A4,0)', { "1:0": "a", "2:0": "B" }).value).toBe(2);
  });

  it("INDEX reads a position out of a range", () => {
    expect(evalA1("=INDEX(A2:A6,3)", data).value).toBe(1);
    expect(evalA1("=INDEX(B1:D1,2)", { "0:1": "x", "0:2": "y", "0:3": "z" }).value).toBe("y");
    expect(evalA1("=INDEX(A2:B3,2,2)", { "1:0": 1, "1:1": 2, "2:0": 3, "2:1": 4 }).value).toBe(4);
    expect(evalA1("=INDEX(A2:A6,99)", data).error).toBe("#REF!");
  });

  it("INDEX reads from the sheet its range names, not the formula's own", () => {
    const e = workbook([
      { id: "s1", name: "Summary", cells: { "0:0": "=INDEX(Data!A1:A3,3)", "2:0": "wrong" } },
      { id: "s2", name: "Data", cells: { "0:0": "a", "1:0": "b", "2:0": "right" } },
    ]);
    expect(e.evaluate(0, 0).value).toBe("right");
  });

  it("INDEX and MATCH together, across sheets", () => {
    const e = workbook([
      {
        id: "s1",
        name: "Summary",
        cells: { "0:0": "=INDEX(Data!A1:A3,MATCH(MAX(Data!B1:B3),Data!B1:B3,0))" },
      },
      {
        id: "s2",
        name: "Data",
        cells: { "0:0": "low", "1:0": "high", "2:0": "mid", "0:1": 1, "1:1": 9, "2:1": 5 },
      },
    ]);
    expect(e.evaluate(0, 0).value).toBe("high");
  });

  it("CHOOSE picks an argument, 1-based", () => {
    expect(evalA1('=CHOOSE(2,"a","b","c")').value).toBe("b");
    expect(evalA1('=CHOOSE(4,"a")').error).toBe("#VALUE!");
  });

  it("SWITCH matches text the way Excel's = does, ignoring case", () => {
    expect(evalA1('=SWITCH("YES","yes","matched","no","nope")').value).toBe("matched");
    expect(evalA1('=SWITCH(A2,"Open",1,"Closed",2)', { "1:0": "OPEN" }).value).toBe(1);
  });

  it("SWITCH compares pairs and falls back to a trailing default", () => {
    expect(evalA1('=SWITCH(2,1,"one",2,"two")').value).toBe("two");
    expect(evalA1('=SWITCH(9,1,"one",2,"two","none")').value).toBe("none");
    expect(evalA1('=SWITCH(9,1,"one")').error).toBe("#N/A");
  });

  it("takes the fractional part of a cell, lowercase reference and all", () => {
    // C10 is "9:2". The idiom is =(C10-INT(C10)); references are
    // case-insensitive, and the inner call reads the same cell as the
    // subtraction.
    expect(evalA1("=(c10-INT(c10))", { "9:2": 3.75 }).value).toBeCloseTo(0.75, 10);
    expect(evalA1("=(C10-INT(C10))", { "9:2": 3.75 }).value).toBeCloseTo(0.75, 10);
    expect(evalA1("=c10-INT(c10)", { "9:2": -3.25 }).value).toBeCloseTo(0.75, 10);
  });

  it("takes the fractional part of a cell that is itself a formula", () => {
    // The shape that used to fail: the inner INT() re-enters the parser
    // while the outer subtraction is mid-parse.
    expect(evalA1("=(c10-INT(c10))", { "9:2": "=1.5*2.5" }).value).toBeCloseTo(0.75, 10);
  });
});
