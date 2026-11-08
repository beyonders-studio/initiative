/**
 * The Yjs layout of a multi-sheet spreadsheet, and the one-shot bootstrap
 * that guarantees it exists.
 *
 * Everything hangs off a single top-level ``Y.Map`` named ``"sheets"``,
 * keyed by sheet id. Each value is a container ``Y.Map`` holding the five
 * structures a sheet owns:
 *
 * ```
 * sheets
 *   └── <sheetId>            Y.Map
 *         ├── meta           Y.Map  name, order, rows, cols, frozenRows, frozenCols
 *         ├── cells          Y.Map  "r:c" -> scalar
 *         ├── columns        Y.Map  "c"   -> ColumnFmt
 *         ├── rows           Y.Map  "r"   -> RowFmt
 *         └── cellStyles     Y.Map  "r:c" -> CellFmt
 * ```
 *
 * One top-level type means undo/redo needs a single scope entry: a
 * ``Y.UndoManager`` tracks any nested type whose parent chain reaches a
 * scoped one, so sheets added later are covered without re-registering.
 *
 * Files written before multi-sheet kept those five maps at the *top*
 * level. {@link ensureWorkbook} folds such a doc into sheet one on first
 * open (see {@link migrateLegacyLayout}), which matters because a live
 * ``yjs_state`` blob can be ahead of the JSON snapshot.
 */

import * as Y from "yjs";

import type { SpreadsheetContent, SpreadsheetSheetContent } from "@/lib/spreadsheet/content";
import { DEFAULT_SHEET_ID, type SheetId, type SheetMeta } from "@/lib/spreadsheet/sheets";

import { SPREADSHEET_SEED_ORIGINS } from "./origins";

export const Y_SHEETS_KEY = "sheets";

/** Keys of a sheet container. */
export const SHEET_META = "meta";
export const SHEET_CELLS = "cells";
export const SHEET_COLUMNS = "columns";
export const SHEET_ROWS = "rows";
export const SHEET_CELLSTYLES = "cellStyles";

/** Keys inside a sheet's ``meta`` map. */
export const META_NAME = "name";
export const META_ORDER = "order";
export const META_ROWS = "rows";
export const META_COLS = "cols";
export const META_FROZEN_ROWS = "frozenRows";
export const META_FROZEN_COLS = "frozenCols";
export const META_HIDDEN = "hidden";

/** The structural maps every sheet container carries, in creation order. */
const SHEET_PARTS = [SHEET_META, SHEET_CELLS, SHEET_COLUMNS, SHEET_ROWS, SHEET_CELLSTYLES] as const;

export type SheetContainer = Y.Map<unknown>;

export const sheetsRoot = (doc: Y.Doc): Y.Map<unknown> => doc.getMap(Y_SHEETS_KEY);

export const sheetContainer = (doc: Y.Doc | null, id: SheetId | null): SheetContainer | null => {
  if (!doc || !id) return null;
  const container = sheetsRoot(doc).get(id);
  return container instanceof Y.Map ? (container as SheetContainer) : null;
};

/** One of a container's five structural maps, or ``null`` when the sheet
 *  (or the doc) isn't there — the caller renders nothing rather than
 *  creating structure as a side effect of reading. */
export const sheetPart = (container: SheetContainer | null, key: string): Y.Map<unknown> | null => {
  if (!container) return null;
  const part = container.get(key);
  return part instanceof Y.Map ? (part as Y.Map<unknown>) : null;
};

/**
 * Create (or complete) the container for one sheet. Must run inside a
 * ``doc.transact``. Idempotent: an existing container keeps its data and
 * only gains any structural map it was missing, so two peers racing to add
 * the same sheet id converge instead of clobbering each other.
 */
export const ensureSheetContainer = (doc: Y.Doc, id: SheetId): SheetContainer => {
  const root = sheetsRoot(doc);
  let container = root.get(id);
  if (!(container instanceof Y.Map)) {
    container = new Y.Map();
    root.set(id, container);
  }
  const typed = container as SheetContainer;
  for (const part of SHEET_PARTS) {
    if (!(typed.get(part) instanceof Y.Map)) typed.set(part, new Y.Map());
  }
  return typed;
};

/** Write a sheet's JSON content into its (fresh) container. Must run inside
 *  a ``doc.transact``. */
export const seedSheet = (doc: Y.Doc, sheet: SpreadsheetSheetContent, order: number): void => {
  const container = ensureSheetContainer(doc, sheet.id);
  const meta = sheetPart(container, SHEET_META);
  const cells = sheetPart(container, SHEET_CELLS);
  const columns = sheetPart(container, SHEET_COLUMNS);
  const rows = sheetPart(container, SHEET_ROWS);
  const cellStyles = sheetPart(container, SHEET_CELLSTYLES);
  if (!meta || !cells || !columns || !rows || !cellStyles) return;
  meta.set(META_NAME, sheet.name);
  meta.set(META_ORDER, order);
  meta.set(META_ROWS, sheet.dimensions.rows);
  meta.set(META_COLS, sheet.dimensions.cols);
  meta.set(META_FROZEN_ROWS, sheet.frozen.rows);
  meta.set(META_FROZEN_COLS, sheet.frozen.cols);
  // Absent rather than false for a shown sheet, matching how it is read.
  if (sheet.hidden) meta.set(META_HIDDEN, true);
  for (const [k, v] of Object.entries(sheet.cells)) cells.set(k, v);
  for (const [k, v] of Object.entries(sheet.columns)) columns.set(k, v);
  for (const [k, v] of Object.entries(sheet.rows)) rows.set(k, v);
  for (const [k, v] of Object.entries(sheet.cellStyles)) cellStyles.set(k, v);
};

/** The workbook's sheets in tab order. Ties on ``order`` (concurrent adds)
 *  break by id so every peer lists them the same way. */
export const readSheetOrder = (doc: Y.Doc | null): SheetMeta[] => {
  if (!doc) return [];
  const out: (SheetMeta & { order: number })[] = [];
  sheetsRoot(doc).forEach((value, id) => {
    if (!(value instanceof Y.Map)) return;
    const meta = sheetPart(value as SheetContainer, SHEET_META);
    const name = meta?.get(META_NAME);
    const order = meta?.get(META_ORDER);
    out.push({
      id,
      name: typeof name === "string" && name ? name : id,
      hidden: meta?.get(META_HIDDEN) === true,
      order: typeof order === "number" && Number.isFinite(order) ? order : Number.MAX_SAFE_INTEGER,
    });
  });
  out.sort((a, b) => a.order - b.order || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  // ``hidden`` is absent rather than false when a sheet is shown, so a
  // sheet's identity stays the two fields it has always been.
  return out.map(({ id, name, hidden }) => (hidden ? { id, name, hidden } : { id, name }));
};

/** The top-level map names a pre-multi-sheet file used. */
const LEGACY_KEYS = [SHEET_CELLS, SHEET_COLUMNS, SHEET_ROWS, SHEET_CELLSTYLES, SHEET_META] as const;

const legacyHasContent = (doc: Y.Doc): boolean =>
  LEGACY_KEYS.some((key) => doc.getMap(key).size > 0);

/**
 * Fold a pre-multi-sheet doc's top-level maps into sheet one, preserving
 * whatever the live Yjs state holds (which can be newer than the JSON
 * snapshot the editor was handed). Must run inside a ``doc.transact``.
 *
 * The legacy maps are emptied afterwards: they're unreachable once the
 * editor reads through sheet containers, and leaving a second copy of every
 * cell in the file would double its synced size forever.
 */
const migrateLegacyLayout = (doc: Y.Doc, name: string): void => {
  const container = ensureSheetContainer(doc, DEFAULT_SHEET_ID);
  for (const key of LEGACY_KEYS) {
    const legacy = doc.getMap(key);
    const target = sheetPart(container, key);
    if (!target) continue;
    legacy.forEach((value, mapKey) => {
      target.set(mapKey, value);
    });
    for (const mapKey of Array.from(legacy.keys())) legacy.delete(mapKey);
  }
  const meta = sheetPart(container, SHEET_META);
  if (meta && typeof meta.get(META_NAME) !== "string") meta.set(META_NAME, name);
  if (meta && typeof meta.get(META_ORDER) !== "number") meta.set(META_ORDER, 0);
};

/**
 * Make sure ``doc`` holds a workbook, seeding it from ``content`` when it
 * doesn't. Safe to call on every render: it returns immediately once the
 * doc has any sheet.
 *
 * Two clients opening the same empty doc at once both run this, which is
 * why the first sheet's id is the fixed {@link DEFAULT_SHEET_ID} and why
 * {@link ensureSheetContainer} merges rather than replaces — the two seeds
 * are byte-identical writes to the same keys, so Yjs converges on one sheet
 * instead of two.
 */
export const ensureWorkbook = (doc: Y.Doc | null, content: SpreadsheetContent): void => {
  if (!doc) return;
  if (sheetsRoot(doc).size > 0) return;
  doc.transact(() => {
    // Re-check inside the transaction: another effect on this tick may have
    // seeded already.
    if (sheetsRoot(doc).size > 0) return;
    if (legacyHasContent(doc)) {
      migrateLegacyLayout(doc, content.sheets[0]?.name ?? "Sheet1");
      return;
    }
    content.sheets.forEach((sheet, index) => {
      seedSheet(doc, sheet, index);
    });
  }, SPREADSHEET_SEED_ORIGINS.BOOTSTRAP);
};
