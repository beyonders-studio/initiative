import { useCallback, useEffect, useMemo, useState } from "react";
import type * as Y from "yjs";

import { DEFAULT_COLS, DEFAULT_ROWS } from "@/lib/spreadsheet/bounds";
import { type CellValue, keyOf } from "@/lib/spreadsheet/coords";
import type { SheetId } from "@/lib/spreadsheet/sheets";

import { SPREADSHEET_ORIGINS } from "./origins";
import {
  META_COLS,
  META_ROWS,
  SHEET_CELLS,
  SHEET_META,
  sheetContainer,
  sheetPart,
} from "./workbookDoc";

/**
 * Write access to one sheet's cell map, plus its grid dimensions.
 *
 * Reads come from ``useSpreadsheetSheets``, which mirrors every sheet at
 * once (a formula can reach across sheets, so something has to). This hook
 * owns the *writes* for the sheet on screen — and, because a formula edit
 * or a structural change can land on a sheet the user isn't looking at, the
 * ``…On`` variants that target any sheet by id.
 *
 * Multi-cell operations (paste, fill, bulk clear) wrap their writes in
 * ``yDoc.transact(...)`` so peers receive a single update event instead of
 * one per cell. ``replaceAll`` writes both the cells AND the new dimensions
 * inside the same transaction so a shrinking import doesn't leave peers
 * stuck on the old grid size.
 *
 * Dimensions are a hybrid on purpose. The persisted value lives in the
 * sheet's ``meta`` map and only structural operations write it; scroll- and
 * cell-driven *growth* is local, because broadcasting it would mean one
 * peer's scrolling restarted every other peer's autosave debounce, and
 * because every peer's grow rule derives the same answer from the shared
 * cell map anyway.
 */
export interface SpreadsheetCellsStore {
  dimensions: { rows: number; cols: number };
  setCell: (row: number, col: number, value: CellValue) => void;
  /** Write into a specific sheet — used when an edit is committed after the
   *  user has already tabbed away to build a cross-sheet reference. */
  setCellOn: (sheetId: SheetId, row: number, col: number, value: CellValue) => void;
  setDimensions: (next: { rows: number; cols: number }) => void;
  bulkUpdate: (mutator: (draft: Map<string, CellValue>) => void) => void;
  bulkUpdateOn: (sheetId: SheetId, mutator: (draft: Map<string, CellValue>) => void) => void;
  replaceAll: (
    nextCells: Record<string, CellValue>,
    nextDimensions: { rows: number; cols: number }
  ) => void;
}

const readCellsMap = (yMap: Y.Map<unknown> | null): Map<string, CellValue> => {
  const out = new Map<string, CellValue>();
  yMap?.forEach((value, key) => {
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

const readDimensions = (yMeta: Y.Map<unknown> | null): { rows: number; cols: number } => {
  const rows = yMeta?.get(META_ROWS);
  const cols = yMeta?.get(META_COLS);
  return {
    rows: typeof rows === "number" && Number.isFinite(rows) && rows > 0 ? rows : DEFAULT_ROWS,
    cols: typeof cols === "number" && Number.isFinite(cols) && cols > 0 ? cols : DEFAULT_COLS,
  };
};

interface UseSpreadsheetCellsArgs {
  yDoc: Y.Doc | null;
  /** The sheet on screen, or ``null`` before the workbook is bootstrapped. */
  sheetId: SheetId | null;
  /** Bumped by the workbook store on any change; re-resolves the Y.Maps
   *  after a sheet is added, so a freshly created tab isn't inert. */
  version: number;
}

export const useSpreadsheetCells = ({
  yDoc,
  sheetId,
  version,
}: UseSpreadsheetCellsArgs): SpreadsheetCellsStore => {
  const partsFor = useCallback(
    (id: SheetId | null) => {
      const container = sheetContainer(yDoc, id);
      return {
        cells: sheetPart(container, SHEET_CELLS),
        meta: sheetPart(container, SHEET_META),
      };
    },
    [yDoc]
  );

  // ``version`` is in the dependency list on purpose: adding a sheet
  // creates its Y.Maps, and this memo has to re-resolve them.
  const { cells: yCells, meta: yMeta } = useMemo(
    () => partsFor(sheetId),
    [partsFor, sheetId, version]
  );

  // The persisted canvas size, mirrored so a peer's structural change (a
  // deleted row band) actually shrinks this client's grid.
  const [persisted, setPersisted] = useState(() => readDimensions(yMeta));
  useEffect(() => {
    setPersisted(readDimensions(yMeta));
    if (!yMeta) return;
    const handler = () => setPersisted(readDimensions(yMeta));
    yMeta.observe(handler);
    return () => yMeta.unobserve(handler);
  }, [yMeta]);

  // Local-only growth, scoped to the sheet it was measured on so switching
  // tabs doesn't carry one sheet's scroll extent onto another.
  const [grown, setGrown] = useState<{ sheetId: SheetId; rows: number; cols: number } | null>(null);

  const dimensions = useMemo(() => {
    if (!grown || grown.sheetId !== sheetId) return persisted;
    return {
      rows: Math.max(persisted.rows, grown.rows),
      cols: Math.max(persisted.cols, grown.cols),
    };
  }, [persisted, grown, sheetId]);

  const setDimensions = useCallback(
    (next: { rows: number; cols: number }) => {
      if (!sheetId) return;
      setGrown((prev) =>
        prev && prev.sheetId === sheetId && prev.rows === next.rows && prev.cols === next.cols
          ? prev
          : { sheetId, rows: next.rows, cols: next.cols }
      );
    },
    [sheetId]
  );

  const setCellOn = useCallback(
    (targetSheet: SheetId, row: number, col: number, value: CellValue) => {
      const { cells } = partsFor(targetSheet);
      if (!yDoc || !cells) return;
      const key = keyOf(row, col);
      yDoc.transact(() => {
        if (value === null || value === "") cells.delete(key);
        else cells.set(key, value);
      }, SPREADSHEET_ORIGINS.EDIT);
    },
    [yDoc, partsFor]
  );

  const setCell = useCallback(
    (row: number, col: number, value: CellValue) => {
      if (sheetId) setCellOn(sheetId, row, col, value);
    },
    [sheetId, setCellOn]
  );

  const bulkUpdateOn = useCallback(
    (targetSheet: SheetId, mutator: (draft: Map<string, CellValue>) => void) => {
      const { cells } = partsFor(targetSheet);
      if (!yDoc || !cells) return;
      // Compute the next state outside the Y transaction so the mutator's
      // logic doesn't need to know about Y.Map semantics, then diff-apply
      // inside one transaction so peers receive a single update.
      const prev = readCellsMap(cells);
      const next = new Map(prev);
      mutator(next);
      yDoc.transact(() => {
        // Diff against ``prev`` so we only emit ops for actually-changed
        // cells — otherwise peers see N writes even when most were
        // unchanged, which inflates the snapshot history and can flicker.
        for (const [key, value] of next) {
          if (prev.get(key) !== value) cells.set(key, value);
        }
        for (const key of prev.keys()) {
          if (!next.has(key)) cells.delete(key);
        }
      }, SPREADSHEET_ORIGINS.BULK);
    },
    [yDoc, partsFor]
  );

  const bulkUpdate = useCallback(
    (mutator: (draft: Map<string, CellValue>) => void) => {
      if (sheetId) bulkUpdateOn(sheetId, mutator);
    },
    [sheetId, bulkUpdateOn]
  );

  const replaceAll = useCallback(
    (nextCells: Record<string, CellValue>, nextDimensions: { rows: number; cols: number }) => {
      if (!yDoc || !yCells || !yMeta || !sheetId) return;
      yDoc.transact(() => {
        for (const key of Array.from(yCells.keys())) yCells.delete(key);
        for (const [key, value] of Object.entries(nextCells)) yCells.set(key, value);
        // Broadcast new dimensions atomically with the cells so peers don't
        // transiently see (new cells, old dimensions).
        yMeta.set(META_ROWS, nextDimensions.rows);
        yMeta.set(META_COLS, nextDimensions.cols);
      }, SPREADSHEET_ORIGINS.REPLACE_ALL);
      // A structural change is the authority on canvas size; drop the local
      // growth so deleting a band actually shrinks the grid.
      setGrown(null);
    },
    [yDoc, yCells, yMeta, sheetId]
  );

  return {
    dimensions,
    setCell,
    setCellOn,
    setDimensions,
    bulkUpdate,
    bulkUpdateOn,
    replaceAll,
  };
};
