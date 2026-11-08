import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";
import * as Y from "yjs";

import { createYjsUndoManager } from "@/hooks/useYjsHistory";
import { DEFAULT_SHEET_ID } from "@/lib/spreadsheet/sheets";

import {
  ALL_SPREADSHEET_ORIGINS,
  SPREADSHEET_ORIGINS,
  SPREADSHEET_SEED_ORIGINS,
  UNDOABLE_SPREADSHEET_ORIGINS,
} from "./origins";
import {
  ensureSheetContainer,
  SHEET_CELLS,
  sheetContainer,
  sheetPart,
  Y_SHEETS_KEY,
} from "./workbookDoc";

/** The scope `useSpreadsheetHistory` uses, so these exercise the real wiring. */
const scope = (doc: Y.Doc) => [doc.getMap(Y_SHEETS_KEY)];

const undoManagerFor = (doc: Y.Doc) =>
  createYjsUndoManager(doc, {
    getScope: scope,
    trackedOrigins: UNDOABLE_SPREADSHEET_ORIGINS,
  })!;

/** A workbook with one sheet, seeded the way the editor seeds it. */
const workbook = () => {
  const doc = new Y.Doc();
  doc.transact(() => {
    ensureSheetContainer(doc, DEFAULT_SHEET_ID);
  }, SPREADSHEET_SEED_ORIGINS.BOOTSTRAP);
  return doc;
};

const cellsOf = (doc: Y.Doc) =>
  sheetPart(sheetContainer(doc, DEFAULT_SHEET_ID), SHEET_CELLS) as Y.Map<unknown>;

describe("spreadsheet undo", () => {
  it("takes a pasted block back in one press", () => {
    const doc = workbook();
    const um = undoManagerFor(doc);
    const cells = cellsOf(doc);
    doc.transact(() => cells.set("0:0", "kept"), SPREADSHEET_ORIGINS.EDIT);

    // A paste writes every cell of the block inside one outer transaction.
    doc.transact(() => {
      cells.set("1:0", "a");
      cells.set("1:1", "b");
      cells.set("2:0", "c");
      cells.set("2:1", "d");
    }, SPREADSHEET_ORIGINS.PASTE);

    expect(um.undoStack.length).toBe(2);

    um.undo();

    // The whole block goes, and only the block.
    expect(cells.has("1:0")).toBe(false);
    expect(cells.has("1:1")).toBe(false);
    expect(cells.has("2:0")).toBe(false);
    expect(cells.has("2:1")).toBe(false);
    expect(cells.get("0:0")).toBe("kept");
  });

  it("takes a cut's move back in one press, source and destination", () => {
    const doc = workbook();
    const cells = cellsOf(doc);
    doc.transact(() => {
      cells.set("0:0", "moving");
    }, SPREADSHEET_ORIGINS.EDIT);
    const um = undoManagerFor(doc);

    // A cut clears its source in the same transaction as the write.
    doc.transact(() => {
      cells.delete("0:0");
      cells.set("5:5", "moving");
    }, SPREADSHEET_ORIGINS.PASTE);

    um.undo();

    expect(cells.get("0:0")).toBe("moving");
    expect(cells.has("5:5")).toBe(false);
  });

  it("makes hiding a sheet undoable, like every other sheet action", () => {
    const doc = workbook();
    const um = undoManagerFor(doc);
    const container = sheetContainer(doc, DEFAULT_SHEET_ID)!;

    doc.transact(() => {
      (container.get("meta") as Y.Map<unknown>).set("hidden", true);
    }, SPREADSHEET_ORIGINS.SHEET_HIDDEN);

    expect(um.undoStack.length).toBe(1);
    um.undo();
    expect((container.get("meta") as Y.Map<unknown>).get("hidden")).toBeUndefined();
  });

  it("never undoes the seeding of a file", () => {
    const doc = new Y.Doc();
    const um = undoManagerFor(doc);
    doc.transact(() => {
      ensureSheetContainer(doc, DEFAULT_SHEET_ID);
    }, SPREADSHEET_SEED_ORIGINS.BOOTSTRAP);

    expect(um.undoStack.length).toBe(0);
  });
});

// ── the registry is the only list ────────────────────────────────────────────

/** Every tree a spreadsheet transaction can be written from. */
const SOURCE_ROOTS = [
  join(__dirname, ".."), // components/files, spreadsheet/ included
  join(__dirname, "..", "..", "..", "lib", "spreadsheet"),
];

/** Every source file under those trees, at any depth. */
const sourceFiles = (): string[] => {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(path);
        continue;
      }
      if (!/\.tsx?$/.test(entry.name)) continue;
      if (entry.name.includes(".test.")) continue;
      if (entry.name === "origins.ts") continue;
      out.push(path);
    }
  };
  for (const root of SOURCE_ROOTS) walk(root);
  return out;
};

/** Every `"spreadsheet-…"` string literal written outside the registry. */
const originLiteralsInSource = (): Set<string> => {
  const found = new Set<string>();
  for (const file of sourceFiles()) {
    for (const [, literal] of readFileSync(file, "utf8").matchAll(/"(spreadsheet-[a-z-]+)"/g)) {
      found.add(literal);
    }
  }
  return found;
};

/** Every registry key the source actually writes under. */
const originKeysUsed = (): Set<string> => {
  const used = new Set<string>();
  for (const file of sourceFiles()) {
    for (const [, key] of readFileSync(file, "utf8").matchAll(
      /SPREADSHEET_(?:SEED_)?ORIGINS\.([A-Z_]+)/g
    )) {
      used.add(key);
    }
  }
  return used;
};

describe("spreadsheet transaction origins", () => {
  it("finds the source it is meant to be guarding", () => {
    // A guard that reads nothing passes forever.
    expect(sourceFiles().length).toBeGreaterThan(10);
    expect(originKeysUsed().size).toBeGreaterThan(10);
  });

  it("are written as constants, never as bare strings", () => {
    // A bare literal is how an origin comes into being without anyone deciding
    // whether undo should reach it — which is the way paste arrived.
    expect([...originLiteralsInSource()]).toEqual([]);
  });

  it("hold no entry that nothing writes under", () => {
    const used = originKeysUsed();
    const declared = [
      ...Object.keys(SPREADSHEET_ORIGINS),
      ...Object.keys(SPREADSHEET_SEED_ORIGINS),
    ];
    expect(declared.filter((key) => !used.has(key))).toEqual([]);
  });

  it("are undoable unless they seed a file", () => {
    expect(UNDOABLE_SPREADSHEET_ORIGINS).toContain(SPREADSHEET_ORIGINS.PASTE);
    expect(UNDOABLE_SPREADSHEET_ORIGINS).not.toContain(SPREADSHEET_SEED_ORIGINS.BOOTSTRAP);
    expect(ALL_SPREADSHEET_ORIGINS).toContain(SPREADSHEET_SEED_ORIGINS.BOOTSTRAP);
  });
});
