import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import * as Y from "yjs";

import { parseSpreadsheetContent } from "@/lib/spreadsheet/content";
import { MAX_SHEETS } from "@/lib/spreadsheet/sheets";

import { useSpreadsheetSheets } from "./useSpreadsheetSheets";
import { SHEET_CELLS, sheetContainer, sheetPart, sheetsRoot } from "./workbookDoc";

const content = (cells: Record<string, unknown>) =>
  parseSpreadsheetContent({ sheets: [{ cells: cells as Record<string, string | number> }] });

const cellsOf = (doc: Y.Doc, id: string): Record<string, unknown> =>
  (sheetPart(sheetContainer(doc, id), SHEET_CELLS)?.toJSON() ?? {}) as Record<string, unknown>;

/** Apply one doc's full state to another, the way the provider applies the
 *  server's initial sync. */
const applyState = (target: Y.Doc, source: Y.Doc) =>
  Y.applyUpdate(target, Y.encodeStateAsUpdate(source));

describe("useSpreadsheetSheets — seeding gate", () => {
  it("seeds immediately by default (local / non-collaborative doc)", () => {
    const doc = new Y.Doc();
    const { result } = renderHook(() =>
      useSpreadsheetSheets({ yDoc: doc, initialContent: content({ "0:0": "hello" }) })
    );
    expect(result.current.sheets).toHaveLength(1);
    expect(cellsOf(doc, "s1")).toEqual({ "0:0": "hello" });
  });

  it("does not seed while seedAllowed is false", () => {
    const doc = new Y.Doc();
    const { result } = renderHook(() =>
      useSpreadsheetSheets({
        yDoc: doc,
        initialContent: content({ "0:0": "stale" }),
        seedAllowed: false,
      })
    );
    expect(sheetsRoot(doc).size).toBe(0);
    expect(result.current.sheets).toHaveLength(0);
  });

  it("seeds a still-empty doc once seedAllowed flips true (first-ever collab session)", () => {
    const doc = new Y.Doc();
    const { result, rerender } = renderHook(
      ({ seedAllowed }: { seedAllowed: boolean }) =>
        useSpreadsheetSheets({
          yDoc: doc,
          initialContent: content({ "0:0": "bootstrap" }),
          seedAllowed,
        }),
      { initialProps: { seedAllowed: false } }
    );
    expect(sheetsRoot(doc).size).toBe(0);

    rerender({ seedAllowed: true });
    expect(result.current.sheets).toHaveLength(1);
    expect(cellsOf(doc, "s1")).toEqual({ "0:0": "bootstrap" });
  });

  it("leaves synced remote state untouched when seedAllowed flips true (rejoin)", () => {
    // The rejoin scenario the gate exists for: another user's edits arrive
    // via the initial sync while our REST snapshot is stale. Seeding before
    // (or after) that sync must not push the stale snapshot into the doc.
    const server = new Y.Doc();
    renderHook(() =>
      useSpreadsheetSheets({ yDoc: server, initialContent: content({ "0:0": "edited-by-A" }) })
    );

    const doc = new Y.Doc();
    const { result, rerender } = renderHook(
      ({ seedAllowed }: { seedAllowed: boolean }) =>
        useSpreadsheetSheets({
          yDoc: doc,
          initialContent: content({ "0:0": "stale-snapshot" }),
          seedAllowed,
        }),
      { initialProps: { seedAllowed: false } }
    );
    expect(sheetsRoot(doc).size).toBe(0);

    // Initial sync lands, then the provider reports synced.
    act(() => applyState(doc, server));
    rerender({ seedAllowed: true });

    expect(cellsOf(doc, "s1")).toEqual({ "0:0": "edited-by-A" });
    expect(result.current.cellsBySheet.get("s1")?.get("0:0")).toBe("edited-by-A");
    // And nothing was broadcast back that the server doesn't already have.
    expect(Y.encodeStateAsUpdate(doc, Y.encodeStateVector(server)).length).toBeLessThanOrEqual(2);
  });
});

describe("useSpreadsheetSheets — importSheets", () => {
  const incoming = (name: string, cells: Record<string, string | number>) => ({
    id: "from-the-file",
    name,
    dimensions: { rows: 100, cols: 26 },
    cells,
    columns: {},
    rows: {},
    cellStyles: {},
    frozen: { rows: 0, cols: 0 },
  });

  it("adds a file's sheets beside what is already open", () => {
    const doc = new Y.Doc();
    const { result } = renderHook(() =>
      useSpreadsheetSheets({ yDoc: doc, initialContent: content({ "0:0": "kept" }) })
    );

    act(() => {
      result.current.importSheets([incoming("Q1", { "0:0": "one" })]);
    });

    expect(result.current.sheets.map((s) => s.name)).toEqual(["Sheet1", "Q1"]);
    // Nothing that was there is disturbed.
    expect(cellsOf(doc, "s1")).toEqual({ "0:0": "kept" });
  });

  it("mints its own ids, so a file cannot land on an open sheet", () => {
    const doc = new Y.Doc();
    const { result } = renderHook(() =>
      useSpreadsheetSheets({ yDoc: doc, initialContent: content({ "0:0": "kept" }) })
    );

    let added: string[] = [];
    act(() => {
      // The file calls its sheet by an id the workbook already uses.
      added = result.current.importSheets([
        { ...incoming("Q1", { "0:0": "one" }), id: "s1" },
      ]).added;
    });

    expect(added[0]).not.toBe("s1");
    expect(cellsOf(doc, "s1")).toEqual({ "0:0": "kept" });
    expect(cellsOf(doc, added[0])).toEqual({ "0:0": "one" });
  });

  it("gives a sheet a free name when the file's is taken", () => {
    const doc = new Y.Doc();
    const { result } = renderHook(() =>
      useSpreadsheetSheets({ yDoc: doc, initialContent: content({}) })
    );

    act(() => {
      result.current.importSheets([incoming("Sheet1", { "0:0": "one" })]);
    });

    const names = result.current.sheets.map((s) => s.name);
    expect(new Set(names).size).toBe(names.length);
  });

  it("brings every tab of a multi-sheet file", () => {
    const doc = new Y.Doc();
    const { result } = renderHook(() =>
      useSpreadsheetSheets({ yDoc: doc, initialContent: content({}) })
    );

    act(() => {
      result.current.importSheets([
        incoming("Q1", { "0:0": "one" }),
        incoming("Q2", { "0:0": "two" }),
      ]);
    });

    expect(result.current.sheets.map((s) => s.name)).toEqual(["Sheet1", "Q1", "Q2"]);
  });

  it("writes the whole file as one change", () => {
    const doc = new Y.Doc();
    const { result } = renderHook(() =>
      useSpreadsheetSheets({ yDoc: doc, initialContent: content({}) })
    );

    // One update event means one thing for a peer to apply, and one thing to
    // undo — the origin is tracked, so undo reaches the import as a whole.
    let updates = 0;
    doc.on("update", () => {
      updates += 1;
    });
    act(() => {
      result.current.importSheets([
        incoming("Q1", { "0:0": "one" }),
        incoming("Q2", { "0:0": "two" }),
      ]);
    });

    expect(updates).toBe(1);
  });
});

describe("useSpreadsheetSheets — a workbook with no room", () => {
  it("says how many sheets it could not take", () => {
    const doc = new Y.Doc();
    const { result } = renderHook(() =>
      useSpreadsheetSheets({ yDoc: doc, initialContent: content({}) })
    );

    const file = Array.from({ length: MAX_SHEETS + 5 }, (_, i) => ({
      id: `f${i}`,
      name: `S${i}`,
      dimensions: { rows: 100, cols: 26 },
      cells: {},
      columns: {},
      rows: {},
      cellStyles: {},
      frozen: { rows: 0, cols: 0 },
    }));

    let outcome = { added: [] as string[], skipped: 0 };
    act(() => {
      outcome = result.current.importSheets(file);
    });

    // One sheet was already there, so the file loses that many plus the five
    // it was over by — and the count is reported rather than swallowed.
    expect(outcome.added.length + outcome.skipped).toBe(file.length);
    expect(outcome.skipped).toBeGreaterThan(0);
    expect(result.current.sheets).toHaveLength(MAX_SHEETS);
  });
});
