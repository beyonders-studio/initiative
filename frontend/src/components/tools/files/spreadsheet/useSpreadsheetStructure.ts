import { type Dispatch, type SetStateAction, useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import type * as Y from "yjs";

import { SPREADSHEET_ORIGINS } from "@/components/tools/files/spreadsheet/origins";
import type { SpreadsheetCellsStore } from "@/components/tools/files/spreadsheet/useSpreadsheetCells";
import type { SpreadsheetFormattingStore } from "@/components/tools/files/spreadsheet/useSpreadsheetFormatting";
import type { SpreadsheetSelection } from "@/components/tools/files/spreadsheet/useSpreadsheetSelection";
import { toast } from "@/lib/mascotToast";
import { MAX_COLS, MAX_ROWS, type SheetBounds, type SheetGrid } from "@/lib/spreadsheet/bounds";
import type { CellValue } from "@/lib/spreadsheet/coords";
import type { SheetId, SheetMeta } from "@/lib/spreadsheet/sheets";
import { type SortDirection, sortSheetByColumn } from "@/lib/spreadsheet/sort";
import {
  type LineAxis,
  type LineOp,
  rewriteReferencesToSheet,
  transformSheet,
} from "@/lib/spreadsheet/transform";

/** A run of whole rows or columns: the ones a header menu acts on. */
export interface LineBand {
  start: number;
  count: number;
}

const EMPTY_CELLS: ReadonlyMap<string, CellValue> = new Map();

interface UseSpreadsheetStructureArgs {
  readOnly: boolean;
  doc: Y.Doc;
  sheets: SheetMeta[];
  cellsBySheet: Map<SheetId, Map<string, CellValue>>;
  activeSheet: SheetMeta | undefined;
  cells: ReadonlyMap<string, CellValue>;
  dimensions: SheetBounds;
  formatting: SpreadsheetFormattingStore;
  replaceAll: SpreadsheetCellsStore["replaceAll"];
  bulkUpdate: SpreadsheetCellsStore["bulkUpdate"];
  bulkUpdateOn: SpreadsheetCellsStore["bulkUpdateOn"];
  grid: SheetGrid;
  setSel: Dispatch<SetStateAction<SpreadsheetSelection>>;
  /** Called before rows move: a pending copy or cut would point at the
   *  wrong cells afterwards. */
  dropClip: () => void;
}

/** What the header menus do to whole lines: insert, delete, hide, sort. */
export const useSpreadsheetStructure = ({
  readOnly,
  doc,
  sheets,
  cellsBySheet,
  activeSheet,
  cells,
  dimensions,
  formatting,
  replaceAll,
  bulkUpdate,
  bulkUpdateOn,
  grid,
  setSel,
  dropClip,
}: UseSpreadsheetStructureArgs) => {
  const { t } = useTranslation("files");

  // Sort the whole sheet by a column. Rows are reordered as records, keeping
  // every other column aligned; cell values, per-cell styles, and per-row
  // formatting all travel with the row. Frozen header rows stay pinned (the
  // sort starts below them).
  const sortColumn = useCallback(
    (col: number, direction: SortDirection) => {
      if (readOnly) return;
      dropClip();
      const result = sortSheetByColumn(cells, formatting.cellStyles, formatting.rows, {
        column: col,
        direction,
        startRow: formatting.frozen.rows,
      });
      if (!result.changed) return;
      // One transaction so peers see the reorder atomically and undo
      // rolls the whole sort back in a single step. The inner store
      // transacts flatten into this outer one (same pattern as import).
      doc.transact(() => {
        bulkUpdate((draft) => {
          draft.clear();
          for (const [key, value] of Object.entries(result.cells)) draft.set(key, value);
        });
        formatting.replaceAll({
          columns: formatting.columns,
          rows: result.rows,
          cellStyles: result.cellStyles,
          frozen: formatting.frozen,
        });
      }, SPREADSHEET_ORIGINS.SORT);
    },
    [readOnly, cells, formatting, bulkUpdate, doc, dropClip]
  );

  // Insert / delete whole rows or columns. The pure ``transformSheet``
  // shifts every downstream line and remaps all four index-keyed structures
  // plus frozen + dimensions; the result is applied in one transaction so
  // peers see the structural change atomically and undo rolls it back in a
  // single step. ``replaceAll`` broadcasts the new dimensions alongside the
  // cells so a delete actually shrinks the canvas for everyone instead of
  // relying on the local-only auto-grow.
  const applyLineTransform = useCallback(
    (op: Pick<LineOp, "axis" | "mode" | "at" | "count">) => {
      if (readOnly) return;
      dropClip();
      if (!activeSheet) return;
      const result = transformSheet(
        {
          cells,
          cellStyles: formatting.cellStyles,
          columns: formatting.columns,
          rows: formatting.rows,
          frozen: formatting.frozen,
          dimensions,
        },
        { ...op, maxRows: MAX_ROWS, maxCols: MAX_COLS, sheetName: activeSheet.name }
      );
      if (!result) {
        // The op was blocked by a guard (deleting the last remaining
        // line, or inserting into a grid already at MAX). Surface why so
        // the silent no-op is discoverable.
        const blockedKey =
          op.mode === "delete"
            ? op.axis === "row"
              ? "spreadsheet.deleteLastRowBlocked"
              : "spreadsheet.deleteLastColumnBlocked"
            : op.axis === "row"
              ? "spreadsheet.maxRowsReached"
              : "spreadsheet.maxColumnsReached";
        toast.info(t(`${blockedKey}`));
        return;
      }
      doc.transact(() => {
        replaceAll(result.cells, result.dimensions);
        formatting.replaceAll({
          columns: result.columns,
          rows: result.rows,
          cellStyles: result.cellStyles,
          frozen: result.frozen,
        });
        // A formula on another sheet that reaches into this one has to move
        // with the lines it points at, exactly like a local reference does.
        for (const other of sheets) {
          if (other.id === activeSheet.id) continue;
          const rewritten = rewriteReferencesToSheet(cellsBySheet.get(other.id) ?? EMPTY_CELLS, {
            sheetName: activeSheet.name,
            axis: op.axis,
            mapIndex: result.mapIndex,
          });
          if (!rewritten) continue;
          bulkUpdateOn(other.id, (draft) => {
            for (const [key, value] of Object.entries(rewritten)) draft.set(key, value);
          });
        }
      }, SPREADSHEET_ORIGINS.STRUCTURE);

      // Remap the selection along the shifted axis so it tracks the same
      // content — otherwise an insert-above leaves the stale band straddling
      // the freshly inserted blank lines, and a later right-click would
      // delete more than intended. ``delta`` is signed and respects capping:
      // > 0 inserted, < 0 deleted.
      const axisIsRow = op.axis === "row";
      const at = Math.max(0, Math.trunc(op.at));
      const delta =
        (axisIsRow ? result.dimensions.rows : result.dimensions.cols) -
        (axisIsRow ? dimensions.rows : dimensions.cols);
      const newDim = axisIsRow ? result.dimensions.rows : result.dimensions.cols;
      const remapIdx = (i: number): number => {
        if (delta >= 0) return i >= at ? i + delta : i; // insert
        const removed = -delta;
        if (i < at) return i;
        if (i >= at + removed) return i - removed;
        return Math.min(at, newDim - 1); // line was inside the deleted band
      };
      setSel((p) => ({
        mode: p.mode,
        anchor: axisIsRow
          ? { row: remapIdx(p.anchor.row), col: p.anchor.col }
          : { row: p.anchor.row, col: remapIdx(p.anchor.col) },
        focus: axisIsRow
          ? { row: remapIdx(p.focus.row), col: p.focus.col }
          : { row: p.focus.row, col: remapIdx(p.focus.col) },
      }));

      if (result.capped) {
        // Fewer lines than requested were applied — a guard kept the last
        // line (delete) or the grid cap left room for only some (insert).
        // Hint so the leftover/missing line isn't a silent mystery.
        const cappedKey =
          op.mode === "delete"
            ? op.axis === "row"
              ? "spreadsheet.deleteLastRowKept"
              : "spreadsheet.deleteLastColumnKept"
            : op.axis === "row"
              ? "spreadsheet.insertRowsCapped"
              : "spreadsheet.insertColumnsCapped";
        toast.info(t(`${cappedKey}`));
      }
    },
    [
      readOnly,
      cells,
      formatting,
      dimensions,
      replaceAll,
      doc,
      t,
      activeSheet,
      sheets,
      cellsBySheet,
      bulkUpdateOn,
      setSel,
      dropClip,
    ]
  );

  // Insert ``count`` lines before (left/above, at the band start) or after
  // (right/below, just past the band end) the band.
  const insertLines = useCallback(
    (axis: LineAxis, band: LineBand, count: number, after: boolean) => {
      applyLineTransform({
        axis,
        mode: "insert",
        at: after ? band.start + band.count : band.start,
        count,
      });
    },
    [applyLineTransform]
  );
  const deleteLines = useCallback(
    (axis: LineAxis, band: LineBand) => {
      applyLineTransform({ axis, mode: "delete", at: band.start, count: band.count });
    },
    [applyLineTransform]
  );

  // Hiding is formatting, not deletion: the cells keep their values, keep
  // being read by formulas, and keep their place in the coordinate space.
  // Only the drawing and the cursor skip them.
  const setLinesHidden = useCallback(
    (axis: LineAxis, band: LineBand, hidden: boolean) => {
      if (readOnly) return;
      formatting.batch(() => {
        for (let i = band.start; i < band.start + band.count; i++) {
          if (axis === "row") formatting.updateRow(i, { hidden });
          else formatting.updateColumn(i, { hidden });
        }
      });
      // The cursor can't stay on a line that is no longer drawn.
      if (!hidden) return;
      setSel((p) => {
        const inBand = (i: number) => i >= band.start && i < band.start + band.count;
        if (axis === "row" ? !inBand(p.focus.row) : !inBand(p.focus.col)) return p;
        const focus = grid.step(p.focus, axis === "row" ? 1 : 0, axis === "row" ? 0 : 1);
        return { anchor: focus, focus, mode: "range" };
      });
    },
    [readOnly, formatting, grid, setSel]
  );

  const hiddenRowIndexes = useMemo(
    () =>
      Object.entries(formatting.rows)
        .filter(([, fmt]) => fmt?.hidden)
        .map(([index]) => Number(index)),
    [formatting.rows]
  );
  const hiddenColIndexes = useMemo(
    () =>
      Object.entries(formatting.columns)
        .filter(([, fmt]) => fmt?.hidden)
        .map(([index]) => Number(index)),
    [formatting.columns]
  );

  const unhideAll = useCallback(
    (axis: LineAxis) => {
      if (readOnly) return;
      const indexes = axis === "row" ? hiddenRowIndexes : hiddenColIndexes;
      formatting.batch(() => {
        for (const i of indexes) {
          if (axis === "row") formatting.updateRow(i, { hidden: false });
          else formatting.updateColumn(i, { hidden: false });
        }
      });
    },
    [readOnly, formatting, hiddenRowIndexes, hiddenColIndexes]
  );

  const hasHidden = useCallback(
    (axis: LineAxis) => (axis === "row" ? hiddenRowIndexes : hiddenColIndexes).length > 0,
    [hiddenRowIndexes, hiddenColIndexes]
  );

  return { sortColumn, insertLines, deleteLines, setLinesHidden, unhideAll, hasHidden };
};
