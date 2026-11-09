import { describe, expect, it } from "vitest";
import * as Y from "yjs";

import { parseSpreadsheetContent } from "@/lib/spreadsheet/content";

import {
  ensureSheetContainer,
  ensureWorkbook,
  META_NAME,
  readSheetOrder,
  SHEET_CELLS,
  SHEET_META,
  sheetContainer,
  sheetPart,
  sheetsRoot,
} from "./workbookDoc";

const cellsOf = (doc: Y.Doc, id: string): Record<string, unknown> =>
  (sheetPart(sheetContainer(doc, id), SHEET_CELLS)?.toJSON() ?? {}) as Record<string, unknown>;

describe("ensureWorkbook — seeding", () => {
  it("seeds every sheet of the parsed content, in order", () => {
    const doc = new Y.Doc();
    ensureWorkbook(
      doc,
      parseSpreadsheetContent({
        schema_version: 3,
        sheets: [
          { id: "s1", name: "Summary", cells: { "0:0": "=Data!A1" } },
          { id: "sx", name: "Data", cells: { "0:0": 5 } },
        ],
      })
    );
    expect(readSheetOrder(doc)).toEqual([
      { id: "s1", name: "Summary" },
      { id: "sx", name: "Data" },
    ]);
    expect(cellsOf(doc, "sx")).toEqual({ "0:0": 5 });
  });

  it("is a no-op once the doc already has a workbook", () => {
    const doc = new Y.Doc();
    const content = parseSpreadsheetContent({ sheets: [{ cells: { "0:0": "first" } }] });
    ensureWorkbook(doc, content);
    sheetPart(sheetContainer(doc, "s1"), SHEET_CELLS)?.set("0:0", "edited");
    ensureWorkbook(doc, content);
    expect(cellsOf(doc, "s1")).toEqual({ "0:0": "edited" });
  });

  it("converges when two peers seed the same empty doc concurrently", () => {
    // Both clients see an empty doc and seed it before syncing. The fixed
    // first-sheet id is what keeps this from producing two sheets.
    const a = new Y.Doc();
    const b = new Y.Doc();
    const content = parseSpreadsheetContent({ sheets: [{ cells: { "0:0": "hello" } }] });
    ensureWorkbook(a, content);
    ensureWorkbook(b, content);
    Y.applyUpdate(a, Y.encodeStateAsUpdate(b));
    Y.applyUpdate(b, Y.encodeStateAsUpdate(a));
    expect(readSheetOrder(a)).toHaveLength(1);
    expect(readSheetOrder(b)).toHaveLength(1);
    expect(cellsOf(a, "s1")).toEqual({ "0:0": "hello" });
  });
});

describe("readSheetOrder", () => {
  it("orders by the stored order and breaks ties by id", () => {
    const doc = new Y.Doc();
    doc.transact(() => {
      for (const [id, name, order] of [
        ["c", "Third", 2],
        ["a", "First", 0],
        ["b", "Second", 1],
      ] as const) {
        const meta = sheetPart(ensureSheetContainer(doc, id), SHEET_META);
        meta?.set(META_NAME, name);
        meta?.set("order", order);
      }
    });
    expect(readSheetOrder(doc).map((s) => s.name)).toEqual(["First", "Second", "Third"]);
  });

  it("returns an empty list for a doc with no workbook", () => {
    expect(readSheetOrder(new Y.Doc())).toEqual([]);
    expect(readSheetOrder(null)).toEqual([]);
  });
});

describe("ensureSheetContainer", () => {
  it("keeps existing data while completing a partial container", () => {
    const doc = new Y.Doc();
    doc.transact(() => {
      const container = new Y.Map();
      container.set(SHEET_CELLS, new Y.Map());
      sheetsRoot(doc).set("partial", container);
      (container.get(SHEET_CELLS) as Y.Map<unknown>).set("0:0", "kept");
    });
    doc.transact(() => ensureSheetContainer(doc, "partial"));
    expect(cellsOf(doc, "partial")).toEqual({ "0:0": "kept" });
    expect(sheetPart(sheetContainer(doc, "partial"), SHEET_META)).not.toBeNull();
  });
});
