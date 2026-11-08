import { useCallback, useEffect, useMemo, useState } from "react";
import type * as Y from "yjs";

import {
  META_FROZEN_COLS,
  META_FROZEN_ROWS,
  SHEET_CELLSTYLES,
  SHEET_COLUMNS,
  SHEET_META,
  SHEET_ROWS,
  sheetContainer,
  sheetPart,
} from "@/components/tools/files/spreadsheet/workbookDoc";
import type { SheetId } from "@/lib/spreadsheet/sheets";
import {
  type CellFmt,
  type CellStyle,
  type ColumnFmt,
  MAX_FROZEN,
  type NumberFormat,
  type RowFmt,
  type SpreadsheetFormatting,
  sanitizeCellFmt,
  sanitizeColumnFmt,
  sanitizeRowFmt,
} from "@/lib/spreadsheet/styles";

import { SPREADSHEET_ORIGINS } from "./origins";

/**
 * Collaborative store for one sheet's formatting structures (schema v2's
 * model, now per sheet): per-column, per-row, and per-cell style/format
 * plus the frozen-pane hint.
 *
 * Parallel to — deliberately not merged into — ``useSpreadsheetCells.ts``.
 * Cells are a hot path of scalar writes; formatting is bursty struct
 * writes. The two share the same ``yDoc``, the same sheet container, and
 * the same transaction discipline.
 *
 * Within a sheet's container:
 *   - ``columns`` / ``rows`` / ``cellStyles`` are same-named ``Y.Map``s;
 *     each value is a small plain JSON object replaced wholesale (no nested
 *     Y types — formatting entries are tiny and never deep-mutated,
 *     mirroring how ``cells`` stores scalars).
 *   - ``frozen`` lives in the sheet's ``meta`` map under ``"frozenRows"`` /
 *     ``"frozenCols"`` (sibling to the dimension keys
 *     ``useSpreadsheetCells`` owns).
 *
 * Mutators do a **read-merge-write** inside one ``yDoc.transact`` so a
 * concurrent edit to a *different* field of the same column/row isn't
 * clobbered (narrows the last-write-wins window to truly-concurrent
 * same-field edits).
 */
export interface SpreadsheetFormattingStore extends SpreadsheetFormatting {
  /** Merge a patch into a column entry. ``null`` deletes the entry.
   *  ``patch.style`` shallow-merges into the existing style; a style
   *  property set to ``undefined`` removes just that property. */
  updateColumn: (col: number, patch: ColumnPatch | null) => void;
  updateRow: (row: number, patch: RowPatch | null) => void;
  updateCell: (row: number, col: number, patch: CellPatch | null) => void;
  setFrozen: (next: { rows: number; cols: number }) => void;
  /** Run several mutators as one collaborative transaction / undo step.
   *  The per-mutator ``transact`` calls flatten into this outer one, so
   *  applying a style to a whole selection is a single broadcast. */
  batch: (fn: () => void) => void;
  /** Replace every formatting structure atomically (structural transform,
   *  sort, import). When collaborating this writes inside whatever
   *  transaction is already open, so the caller can wrap it together with
   *  the cell replace in a single ``yDoc.transact`` and peers never see a
   *  torn state. */
  replaceAll: (next: SpreadsheetFormatting) => void;
}

export interface ColumnPatch {
  width?: number;
  format?: NumberFormat | null;
  style?: Partial<CellStyle>;
  hidden?: boolean;
}
export interface RowPatch {
  height?: number;
  style?: Partial<CellStyle>;
  hidden?: boolean;
}
export interface CellPatch {
  format?: NumberFormat | null;
  style?: Partial<CellStyle>;
}

type FmtRecord<T> = Record<string, T>;

const yMapToRecord = <T>(yMap: Y.Map<unknown> | null): FmtRecord<T> => {
  const out: FmtRecord<T> = {};
  yMap?.forEach((value, key) => {
    if (value && typeof value === "object") out[key] = value as T;
  });
  return out;
};

const readFrozen = (yMeta: Y.Map<unknown> | null): { rows: number; cols: number } => {
  const r = yMeta?.get(META_FROZEN_ROWS);
  const c = yMeta?.get(META_FROZEN_COLS);
  return {
    rows: typeof r === "number" && Number.isInteger(r) && r >= 0 ? r : 0,
    cols: typeof c === "number" && Number.isInteger(c) && c >= 0 ? c : 0,
  };
};

const clampFrozen = (value: number): number => Math.max(0, Math.min(Math.trunc(value), MAX_FROZEN));

/** Shallow-merge a style patch; ``undefined`` values remove their key. */
const mergeStyle = (
  base: CellStyle | undefined,
  patch: Partial<CellStyle> | undefined
): Record<string, unknown> | undefined => {
  if (patch === undefined) return base as Record<string, unknown> | undefined;
  const merged: Record<string, unknown> = { ...(base ?? {}) };
  for (const [k, v] of Object.entries(patch)) {
    if (v === undefined) delete merged[k];
    else merged[k] = v;
  }
  return merged;
};

const applyColumnPatch = (
  prev: ColumnFmt | undefined,
  patch: ColumnPatch
): ColumnFmt | undefined => {
  const draft: Record<string, unknown> = { ...(prev ?? {}) };
  if ("width" in patch) draft.width = patch.width;
  if ("format" in patch) {
    if (patch.format == null) delete draft.format;
    else draft.format = patch.format;
  }
  if ("style" in patch) draft.style = mergeStyle(prev?.style, patch.style);
  // ``hidden: false`` removes the flag rather than storing it, so an
  // unhidden line leaves nothing behind in the saved workbook.
  if ("hidden" in patch) {
    if (patch.hidden) draft.hidden = true;
    else delete draft.hidden;
  }
  return sanitizeColumnFmt(draft);
};

const applyRowPatch = (prev: RowFmt | undefined, patch: RowPatch): RowFmt | undefined => {
  const draft: Record<string, unknown> = { ...(prev ?? {}) };
  if ("height" in patch) draft.height = patch.height;
  if ("style" in patch) draft.style = mergeStyle(prev?.style, patch.style);
  if ("hidden" in patch) {
    if (patch.hidden) draft.hidden = true;
    else delete draft.hidden;
  }
  return sanitizeRowFmt(draft);
};

const applyCellPatch = (prev: CellFmt | undefined, patch: CellPatch): CellFmt | undefined => {
  const draft: Record<string, unknown> = { ...(prev ?? {}) };
  if ("format" in patch) {
    if (patch.format == null) delete draft.format;
    else draft.format = patch.format;
  }
  if ("style" in patch) draft.style = mergeStyle(prev?.style, patch.style);
  return sanitizeCellFmt(draft);
};

interface UseSpreadsheetFormattingArgs {
  yDoc: Y.Doc | null;
  /** The sheet on screen, or ``null`` before the workbook is bootstrapped. */
  sheetId: SheetId | null;
  /** Bumped by the workbook store on any change; re-resolves the Y.Maps
   *  after a sheet is added. */
  version: number;
}

export const useSpreadsheetFormatting = ({
  yDoc,
  sheetId,
  version,
}: UseSpreadsheetFormattingArgs): SpreadsheetFormattingStore => {
  // ``version`` is in the dependency list on purpose: adding a sheet
  // creates its Y.Maps, and this memo has to re-resolve them.
  const maps = useMemo(() => {
    const container = sheetContainer(yDoc, sheetId);
    return {
      columns: sheetPart(container, SHEET_COLUMNS),
      rows: sheetPart(container, SHEET_ROWS),
      cellStyles: sheetPart(container, SHEET_CELLSTYLES),
      meta: sheetPart(container, SHEET_META),
    };
  }, [yDoc, sheetId, version]);
  const { columns: yColumns, rows: yRows, cellStyles: yCellStyles, meta: yMeta } = maps;

  const [columns, setColumns] = useState<FmtRecord<ColumnFmt>>(() => yMapToRecord(yColumns));
  const [rows, setRows] = useState<FmtRecord<RowFmt>>(() => yMapToRecord(yRows));
  const [cellStyles, setCellStyles] = useState<FmtRecord<CellFmt>>(() => yMapToRecord(yCellStyles));
  const [frozen, setFrozenState] = useState(() => readFrozen(yMeta));

  // Observers — rebuild a fresh Record (new identity) on every committed
  // change so consumers that depend on these references re-render exactly
  // when something actually changed. Each also re-reads on attach, which is
  // what re-points the mirror after a sheet switch.
  useEffect(() => {
    setColumns(yMapToRecord(yColumns));
    if (!yColumns) return;
    const handler = () => setColumns(yMapToRecord(yColumns));
    yColumns.observe(handler);
    return () => yColumns.unobserve(handler);
  }, [yColumns]);
  useEffect(() => {
    setRows(yMapToRecord(yRows));
    if (!yRows) return;
    const handler = () => setRows(yMapToRecord(yRows));
    yRows.observe(handler);
    return () => yRows.unobserve(handler);
  }, [yRows]);
  useEffect(() => {
    setCellStyles(yMapToRecord(yCellStyles));
    if (!yCellStyles) return;
    const handler = () => setCellStyles(yMapToRecord(yCellStyles));
    yCellStyles.observe(handler);
    return () => yCellStyles.unobserve(handler);
  }, [yCellStyles]);
  useEffect(() => {
    setFrozenState(readFrozen(yMeta));
    if (!yMeta) return;
    const handler = () =>
      setFrozenState((prev) => {
        const next = readFrozen(yMeta);
        return next.rows === prev.rows && next.cols === prev.cols ? prev : next;
      });
    yMeta.observe(handler);
    return () => yMeta.unobserve(handler);
  }, [yMeta]);

  const updateColumn = useCallback(
    (col: number, patch: ColumnPatch | null) => {
      if (!yDoc || !yColumns) return;
      const key = String(col);
      yDoc.transact(() => {
        if (patch === null) {
          yColumns.delete(key);
          return;
        }
        const next = applyColumnPatch(yColumns.get(key) as ColumnFmt, patch);
        if (next) yColumns.set(key, next);
        else yColumns.delete(key);
      }, SPREADSHEET_ORIGINS.FMT_EDIT);
    },
    [yDoc, yColumns]
  );

  const updateRow = useCallback(
    (row: number, patch: RowPatch | null) => {
      if (!yDoc || !yRows) return;
      const key = String(row);
      yDoc.transact(() => {
        if (patch === null) {
          yRows.delete(key);
          return;
        }
        const next = applyRowPatch(yRows.get(key) as RowFmt, patch);
        if (next) yRows.set(key, next);
        else yRows.delete(key);
      }, SPREADSHEET_ORIGINS.FMT_EDIT);
    },
    [yDoc, yRows]
  );

  const updateCell = useCallback(
    (row: number, col: number, patch: CellPatch | null) => {
      if (!yDoc || !yCellStyles) return;
      const key = `${row}:${col}`;
      yDoc.transact(() => {
        if (patch === null) {
          yCellStyles.delete(key);
          return;
        }
        const next = applyCellPatch(yCellStyles.get(key) as CellFmt, patch);
        if (next) yCellStyles.set(key, next);
        else yCellStyles.delete(key);
      }, SPREADSHEET_ORIGINS.FMT_EDIT);
    },
    [yDoc, yCellStyles]
  );

  const setFrozen = useCallback(
    (next: { rows: number; cols: number }) => {
      if (!yDoc || !yMeta) return;
      yDoc.transact(() => {
        yMeta.set(META_FROZEN_ROWS, clampFrozen(next.rows));
        yMeta.set(META_FROZEN_COLS, clampFrozen(next.cols));
      }, SPREADSHEET_ORIGINS.FMT_EDIT);
    },
    [yDoc, yMeta]
  );

  const batch = useCallback(
    (fn: () => void) => {
      if (yDoc) yDoc.transact(fn, SPREADSHEET_ORIGINS.FMT_BATCH);
      else fn();
    },
    [yDoc]
  );

  const replaceAll = useCallback(
    (next: SpreadsheetFormatting) => {
      if (!yDoc || !yColumns || !yRows || !yCellStyles || !yMeta) return;
      // Nested ``transact`` is flattened by Yjs into whatever transaction is
      // already open, so the editor can wrap this and the cell replaceAll in
      // one outer transact for atomicity.
      yDoc.transact(() => {
        for (const k of Array.from(yColumns.keys())) yColumns.delete(k);
        for (const k of Array.from(yRows.keys())) yRows.delete(k);
        for (const k of Array.from(yCellStyles.keys())) yCellStyles.delete(k);
        for (const [k, v] of Object.entries(next.columns)) yColumns.set(k, v);
        for (const [k, v] of Object.entries(next.rows)) yRows.set(k, v);
        for (const [k, v] of Object.entries(next.cellStyles)) yCellStyles.set(k, v);
        yMeta.set(META_FROZEN_ROWS, clampFrozen(next.frozen.rows));
        yMeta.set(META_FROZEN_COLS, clampFrozen(next.frozen.cols));
      }, SPREADSHEET_ORIGINS.FMT_REPLACE_ALL);
    },
    [yDoc, yColumns, yRows, yCellStyles, yMeta]
  );

  return {
    columns,
    rows,
    cellStyles,
    frozen,
    updateColumn,
    updateRow,
    updateCell,
    setFrozen,
    batch,
    replaceAll,
  };
};
