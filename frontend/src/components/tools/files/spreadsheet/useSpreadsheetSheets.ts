import { useCallback, useEffect, useMemo, useState } from "react";
import type * as Y from "yjs";

import {
  ensureSheetContainer,
  ensureWorkbook,
  META_COLS,
  META_FROZEN_COLS,
  META_FROZEN_ROWS,
  META_HIDDEN,
  META_NAME,
  META_ORDER,
  META_ROWS,
  readSheetOrder,
  SHEET_CELLS,
  SHEET_CELLSTYLES,
  SHEET_COLUMNS,
  SHEET_META,
  SHEET_ROWS,
  type SheetContainer,
  seedSheet,
  sheetContainer,
  sheetPart,
  sheetsRoot,
} from "@/components/tools/files/spreadsheet/workbookDoc";
import { MAX_COLS, MAX_ROWS } from "@/lib/spreadsheet/bounds";
import {
  SPREADSHEET_SCHEMA_VERSION,
  type SpreadsheetContent,
  type SpreadsheetSheetContent,
} from "@/lib/spreadsheet/content";
import type { CellValue } from "@/lib/spreadsheet/coords";
import { isFormula, renameSheetReferences } from "@/lib/spreadsheet/formula-refs";
import {
  MAX_SHEETS,
  newSheetId,
  nextSheetName,
  type SheetId,
  type SheetMeta,
  sanitizeSheetName,
  sheetNameKey,
  uniqueSheetName,
} from "@/lib/spreadsheet/sheets";
import type { CellFmt, ColumnFmt, RowFmt } from "@/lib/spreadsheet/styles";

import { SPREADSHEET_ORIGINS } from "./origins";

/**
 * The workbook level of a spreadsheet file: which sheets exist, what
 * they're called, what order the tabs sit in — and, because a formula can
 * reach across sheets, every sheet's cell map at once.
 *
 * The per-sheet stores (``useSpreadsheetCells`` /
 * ``useSpreadsheetFormatting``) hang off whichever sheet is on screen; this
 * hook is the only one that sees all of them. That's what
 * {@link SpreadsheetSheetsStore.cellsBySheet} is for — the evaluator needs
 * the whole workbook to resolve ``=Sheet2!A1`` — and what
 * {@link SpreadsheetSheetsStore.snapshot} is for: the JSON the autosave
 * PATCH persists covers every sheet, not just the visible one.
 *
 * Change tracking is deliberately per-sheet. A deep observer would make
 * every keystroke rebuild every sheet's map; instead each event's path
 * names the sheet it touched, so only that one is rebuilt and the rest keep
 * their identity (and the memos that depend on them).
 */
export interface SpreadsheetSheetsStore {
  /** Sheets in tab order. Never empty once the doc is bootstrapped. */
  sheets: SheetMeta[];
  /** Every sheet's cells, keyed by sheet id — the evaluator's workbook. */
  cellsBySheet: Map<SheetId, Map<string, CellValue>>;
  /** Bumped on any change anywhere in the workbook, including ones that
   *  don't alter the sheet list (a cell edit on an off-screen sheet still
   *  has to reach the autosave snapshot). */
  version: number;
  /** Append a sheet after ``afterId`` (or at the end) and return its id.
   *  Returns ``null`` at {@link MAX_SHEETS}. */
  addSheet: (afterId?: SheetId) => SheetId | null;
  /** Rename a sheet, rewriting every formula in the workbook that named it
   *  so cross-sheet references survive. Returns the name actually applied
   *  (sanitized and de-duplicated), or ``null`` if nothing changed. */
  renameSheet: (id: SheetId, name: string) => string | null;
  /** Delete a sheet. Refuses to remove the last one. */
  deleteSheet: (id: SheetId) => boolean;
  /** Show or hide a sheet's tab. Refuses to hide the last visible one —
   *  a workbook with nothing to show has nothing to render. */
  setSheetHidden: (id: SheetId, hidden: boolean) => boolean;
  /** Move a sheet ``delta`` positions in the tab order. */
  moveSheet: (id: SheetId, delta: number) => void;
  /** Copy a sheet (content, formatting, formulas verbatim) in right after
   *  the original. Returns the new id. */
  duplicateSheet: (id: SheetId) => SheetId | null;
  /** Add whole sheets, content and all, as new tabs. Reports the ids added
   *  and how many the workbook had no room for, so a partial import is never
   *  announced as a whole one. */
  importSheets: (sheets: SpreadsheetSheetContent[]) => {
    added: SheetId[];
    skipped: number;
  };
  /** The whole workbook as the persisted v3 JSON snapshot. */
  snapshot: () => SpreadsheetContent;
}

const readScalarMap = (map: Y.Map<unknown> | null): Map<string, CellValue> => {
  const out = new Map<string, CellValue>();
  map?.forEach((value, key) => {
    if (
      typeof value === "string" ||
      typeof value === "number" ||
      typeof value === "boolean" ||
      value === null
    ) {
      out.set(key, value as CellValue);
    }
  });
  return out;
};

const readObjectMap = <T>(map: Y.Map<unknown> | null): Record<string, T> => {
  const out: Record<string, T> = {};
  map?.forEach((value, key) => {
    if (value && typeof value === "object") out[key] = value as T;
  });
  return out;
};

const readInt = (map: Y.Map<unknown> | null, key: string, fallback: number): number => {
  const value = map?.get(key);
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
};

const readCells = (doc: Y.Doc | null, id: SheetId): Map<string, CellValue> =>
  readScalarMap(sheetPart(sheetContainer(doc, id), SHEET_CELLS));

const sameSheets = (a: SheetMeta[], b: SheetMeta[]): boolean =>
  a.length === b.length &&
  a.every(
    (s, i) => s.id === b[i].id && s.name === b[i].name && Boolean(s.hidden) === Boolean(b[i].hidden)
  );

/** Rewrite ``order`` so the tabs are 0..n-1 in ``ids`` order. Must run
 *  inside a transaction. */
const renumber = (doc: Y.Doc, ids: SheetId[]): void => {
  ids.forEach((id, index) => {
    const meta = sheetPart(sheetContainer(doc, id), SHEET_META);
    if (meta && meta.get(META_ORDER) !== index) meta.set(META_ORDER, index);
  });
};

const copyInto = (source: Y.Map<unknown> | null, target: Y.Map<unknown> | null): void => {
  if (!source || !target) return;
  source.forEach((value, key) => {
    // Formatting entries are plain JSON objects replaced wholesale, so a
    // shallow copy is a real copy — there are no nested Y types to clone.
    target.set(key, value);
  });
};

interface UseSpreadsheetSheetsArgs {
  yDoc: Y.Doc | null;
  /** Parsed v3 content, used only to seed a doc that has no workbook yet. */
  initialContent: SpreadsheetContent;
  /** Gate for the one-shot seed. A collaborative doc must not be seeded
   *  before the provider's initial sync completes: the doc looks empty
   *  only because the server state hasn't arrived yet, and seeding it
   *  from the (possibly stale) REST snapshot creates writes concurrent
   *  with everything other users did since — which last-write-wins can
   *  resolve in the stale seed's favor, for every connected client.
   *  Pass ``false`` until the provider reports synced; defaults to
   *  ``true`` for local (non-collaborative) docs. */
  seedAllowed?: boolean;
}

export const useSpreadsheetSheets = ({
  yDoc,
  initialContent,
  seedAllowed = true,
}: UseSpreadsheetSheetsArgs): SpreadsheetSheetsStore => {
  // Seeding runs during render, not in an effect, because the per-sheet
  // hooks called after this one resolve their Y.Maps during *their* render
  // — an effect would leave them pointed at nothing for the first frame.
  // ``ensureWorkbook`` returns immediately when the doc already has sheets,
  // so a re-render (or StrictMode's double invoke) costs nothing.
  useMemo(() => {
    if (seedAllowed) ensureWorkbook(yDoc, initialContent);
  }, [yDoc, initialContent, seedAllowed]);

  const [sheets, setSheets] = useState<SheetMeta[]>(() => readSheetOrder(yDoc));
  const [cellsBySheet, setCellsBySheet] = useState<Map<SheetId, Map<string, CellValue>>>(() => {
    const out = new Map<SheetId, Map<string, CellValue>>();
    for (const sheet of readSheetOrder(yDoc)) out.set(sheet.id, readCells(yDoc, sheet.id));
    return out;
  });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (!yDoc) return;
    const root = sheetsRoot(yDoc);
    // ``dirty === null`` means "rebuild everything" — used when adopting a
    // doc, where nothing about the previous mirror can be trusted.
    const sync = (dirty: Set<SheetId> | null) => {
      const next = readSheetOrder(yDoc);
      setSheets((prev) => (sameSheets(prev, next) ? prev : next));
      setCellsBySheet((prev) => {
        const out = new Map(prev);
        const live = new Set(next.map((s) => s.id));
        for (const id of Array.from(out.keys())) if (!live.has(id)) out.delete(id);
        for (const id of live) {
          if (!dirty || dirty.has(id) || !out.has(id)) out.set(id, readCells(yDoc, id));
        }
        return out;
      });
    };

    const handler = (events: Y.YEvent<Y.AbstractType<unknown>>[]) => {
      // ``path`` is relative to the observed root, so its first element is
      // the sheet id — except for a change to the root itself (a sheet
      // added or removed), where it's empty and every sheet is suspect.
      let structural = false;
      const dirty = new Set<SheetId>();
      for (const event of events) {
        const [id] = event.path;
        if (typeof id === "string") dirty.add(id);
        else structural = true;
      }
      sync(structural ? null : dirty);
      // Only real changes bump the version. Adoption must not, or opening a
      // file would arm the autosave timer with no user interaction.
      setVersion((v) => v + 1);
    };

    root.observeDeep(handler);
    // A doc swap (provider reconnect) hands us a different, already-seeded
    // tree; adopt it rather than waiting for the first edit.
    sync(null);
    return () => root.unobserveDeep(handler);
  }, [yDoc]);

  const addSheet = useCallback(
    (afterId?: SheetId): SheetId | null => {
      if (!yDoc) return null;
      const current = readSheetOrder(yDoc);
      if (current.length >= MAX_SHEETS) return null;
      const id = newSheetId();
      const name = nextSheetName(current.map((s) => s.name));
      const at = afterId ? current.findIndex((s) => s.id === afterId) : -1;
      const ids = current.map((s) => s.id);
      ids.splice(at < 0 ? ids.length : at + 1, 0, id);
      yDoc.transact(() => {
        const container = ensureSheetContainer(yDoc, id);
        const meta = sheetPart(container, SHEET_META);
        meta?.set(META_NAME, name);
        meta?.set(META_ROWS, initialContent.sheets[0]?.dimensions.rows ?? 100);
        meta?.set(META_COLS, initialContent.sheets[0]?.dimensions.cols ?? 26);
        meta?.set(META_FROZEN_ROWS, 0);
        meta?.set(META_FROZEN_COLS, 0);
        renumber(yDoc, ids);
      }, SPREADSHEET_ORIGINS.SHEET_ADD);
      return id;
    },
    [yDoc, initialContent]
  );

  const renameSheet = useCallback(
    (id: SheetId, raw: string): string | null => {
      if (!yDoc) return null;
      const current = readSheetOrder(yDoc);
      const target = current.find((s) => s.id === id);
      if (!target) return null;
      const cleaned = sanitizeSheetName(raw);
      if (!cleaned) return null;
      const others = current.filter((s) => s.id !== id).map((s) => s.name);
      const name = uniqueSheetName(cleaned, others);
      if (sheetNameKey(name) === sheetNameKey(target.name) && name === target.name) return null;
      yDoc.transact(() => {
        sheetPart(sheetContainer(yDoc, id), SHEET_META)?.set(META_NAME, name);
        // Every formula in the workbook that spelled the old name has to be
        // re-spelled, or it would resolve to a sheet that no longer exists.
        for (const sheet of current) {
          const cells = sheetPart(sheetContainer(yDoc, sheet.id), SHEET_CELLS);
          if (!cells) continue;
          const rewrites: [string, string][] = [];
          cells.forEach((value, key) => {
            if (typeof value !== "string" || !isFormula(value)) return;
            const next = renameSheetReferences(value, target.name, name);
            if (next !== value) rewrites.push([key, next]);
          });
          for (const [key, value] of rewrites) cells.set(key, value);
        }
      }, SPREADSHEET_ORIGINS.SHEET_RENAME);
      return name;
    },
    [yDoc]
  );

  const deleteSheet = useCallback(
    (id: SheetId): boolean => {
      if (!yDoc) return false;
      const current = readSheetOrder(yDoc);
      if (current.length <= 1 || !current.some((s) => s.id === id)) return false;
      yDoc.transact(() => {
        sheetsRoot(yDoc).delete(id);
        renumber(
          yDoc,
          current.filter((s) => s.id !== id).map((s) => s.id)
        );
      }, SPREADSHEET_ORIGINS.SHEET_DELETE);
      return true;
    },
    [yDoc]
  );

  const setSheetHidden = useCallback(
    (id: SheetId, hidden: boolean): boolean => {
      if (!yDoc) return false;
      const current = readSheetOrder(yDoc);
      if (!current.some((s) => s.id === id)) return false;
      const visibleAfter = current.filter((s) => (s.id === id ? !hidden : !s.hidden));
      if (visibleAfter.length === 0) return false;
      yDoc.transact(() => {
        const meta = sheetPart(sheetContainer(yDoc, id), SHEET_META);
        // Absence is the default, so showing a sheet clears the flag
        // instead of storing a negative in every saved workbook.
        if (hidden) meta?.set(META_HIDDEN, true);
        else meta?.delete(META_HIDDEN);
      }, SPREADSHEET_ORIGINS.SHEET_HIDDEN);
      return true;
    },
    [yDoc]
  );

  const moveSheet = useCallback(
    (id: SheetId, delta: number) => {
      if (!yDoc) return;
      const ids = readSheetOrder(yDoc).map((s) => s.id);
      const from = ids.indexOf(id);
      if (from < 0) return;
      const to = Math.max(0, Math.min(ids.length - 1, from + delta));
      if (to === from) return;
      ids.splice(to, 0, ...ids.splice(from, 1));
      yDoc.transact(() => renumber(yDoc, ids), SPREADSHEET_ORIGINS.SHEET_MOVE);
    },
    [yDoc]
  );

  const importSheets = useCallback(
    (incoming: SpreadsheetSheetContent[]) => {
      if (!yDoc || incoming.length === 0) return { added: [], skipped: 0 };
      const current = readSheetOrder(yDoc);
      const room = Math.max(MAX_SHEETS - current.length, 0);
      const skipped = Math.max(incoming.length - room, 0);
      if (room <= 0) return { added: [], skipped };

      const taken = current.map((s) => s.name);
      const ids = current.map((s) => s.id);
      const added: SheetId[] = [];
      // One transaction for the whole file: peers receive the import as a
      // single change, and it is one thing to undo however many tabs it
      // brought. Ids are minted here rather than taken from the file, so an
      // imported sheet can never land on top of one already open.
      yDoc.transact(() => {
        for (const sheet of incoming.slice(0, room)) {
          const id = newSheetId();
          const name = uniqueSheetName(sheet.name, taken);
          taken.push(name);
          ids.push(id);
          added.push(id);
          seedSheet(yDoc, { ...sheet, id, name }, ids.length - 1);
        }
        renumber(yDoc, ids);
      }, SPREADSHEET_ORIGINS.IMPORT);
      return { added, skipped };
    },
    [yDoc]
  );

  const duplicateSheet = useCallback(
    (id: SheetId): SheetId | null => {
      if (!yDoc) return null;
      const current = readSheetOrder(yDoc);
      if (current.length >= MAX_SHEETS) return null;
      const source = sheetContainer(yDoc, id);
      const original = current.find((s) => s.id === id);
      if (!source || !original) return null;
      const copyId = newSheetId();
      const name = uniqueSheetName(
        `${original.name} copy`,
        current.map((s) => s.name)
      );
      const ids = current.map((s) => s.id);
      ids.splice(ids.indexOf(id) + 1, 0, copyId);
      yDoc.transact(() => {
        const target = ensureSheetContainer(yDoc, copyId);
        // Formulas copy verbatim: an unqualified reference now points at the
        // copy's own cells, and a qualified one still points across — the
        // same thing Excel's "Move or Copy" does.
        for (const part of [SHEET_CELLS, SHEET_COLUMNS, SHEET_ROWS, SHEET_CELLSTYLES]) {
          copyInto(sheetPart(source, part), sheetPart(target, part));
        }
        const sourceMeta = sheetPart(source, SHEET_META);
        const meta = sheetPart(target, SHEET_META);
        meta?.set(META_NAME, name);
        meta?.set(META_ROWS, readInt(sourceMeta, META_ROWS, 100));
        meta?.set(META_COLS, readInt(sourceMeta, META_COLS, 26));
        meta?.set(META_FROZEN_ROWS, readInt(sourceMeta, META_FROZEN_ROWS, 0));
        meta?.set(META_FROZEN_COLS, readInt(sourceMeta, META_FROZEN_COLS, 0));
        renumber(yDoc, ids);
      }, SPREADSHEET_ORIGINS.SHEET_DUPLICATE);
      return copyId;
    },
    [yDoc]
  );

  const snapshot = useCallback((): SpreadsheetContent => {
    const order = readSheetOrder(yDoc);
    const sheetContents: SpreadsheetSheetContent[] = order.map((meta) => {
      const container = sheetContainer(yDoc, meta.id) as SheetContainer | null;
      const metaMap = sheetPart(container, SHEET_META);
      const cells: Record<string, CellValue> = {};
      for (const [key, value] of readScalarMap(sheetPart(container, SHEET_CELLS))) {
        cells[key] = value;
      }
      return {
        id: meta.id,
        name: meta.name,
        ...(meta.hidden ? { hidden: true as const } : {}),
        dimensions: {
          rows: Math.min(readInt(metaMap, META_ROWS, 100), MAX_ROWS),
          cols: Math.min(readInt(metaMap, META_COLS, 26), MAX_COLS),
        },
        cells,
        columns: readObjectMap<ColumnFmt>(sheetPart(container, SHEET_COLUMNS)),
        rows: readObjectMap<RowFmt>(sheetPart(container, SHEET_ROWS)),
        cellStyles: readObjectMap<CellFmt>(sheetPart(container, SHEET_CELLSTYLES)),
        frozen: {
          rows: readInt(metaMap, META_FROZEN_ROWS, 0),
          cols: readInt(metaMap, META_FROZEN_COLS, 0),
        },
      };
    });
    return {
      schema_version: SPREADSHEET_SCHEMA_VERSION,
      kind: "spreadsheet",
      sheets: sheetContents,
    };
  }, [yDoc]);

  return {
    sheets,
    cellsBySheet,
    version,
    addSheet,
    renameSheet,
    deleteSheet,
    setSheetHidden,
    moveSheet,
    duplicateSheet,
    importSheets,
    snapshot,
  };
};
