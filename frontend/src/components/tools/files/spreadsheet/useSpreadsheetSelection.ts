import { useCallback, useMemo, useState } from "react";

import { type CellPos, type SheetGrid, usedRange } from "@/lib/spreadsheet/bounds";
import { type CellValue, colIndexToLetter, keyOf } from "@/lib/spreadsheet/coords";
import type { LineAxis } from "@/lib/spreadsheet/transform";

/** ``anchor`` is where the selection started, ``focus`` the active cell
 *  (it drives editing, the keyboard and the toolbar's state). ``mode``
 *  decides what formatting targets: a cell rectangle, whole columns (a
 *  header click), or whole rows. */
export interface SpreadsheetSelection {
  anchor: CellPos;
  focus: CellPos;
  mode: "range" | "columns" | "rows";
}

export const ORIGIN_SELECTION: SpreadsheetSelection = {
  anchor: { row: 0, col: 0 },
  focus: { row: 0, col: 0 },
  mode: "range",
};

interface UseSpreadsheetSelectionArgs {
  grid: SheetGrid;
  cells: ReadonlyMap<string, CellValue>;
}

/** The selection on the sheet on screen, and every way of moving it. */
export const useSpreadsheetSelection = ({ grid, cells }: UseSpreadsheetSelectionArgs) => {
  const [sel, setSel] = useState<SpreadsheetSelection>(ORIGIN_SELECTION);

  const selBox = useMemo(
    () => grid.normalizeSelection(sel.anchor, sel.focus),
    [grid, sel.anchor, sel.focus]
  );

  const isInSel = useCallback(
    (r: number, c: number): boolean => {
      const { r1, r2, c1, c2 } = selBox;
      if (sel.mode === "columns") return c >= c1 && c <= c2;
      if (sel.mode === "rows") return r >= r1 && r <= r2;
      return r >= r1 && r <= r2 && c >= c1 && c <= c2;
    },
    [sel.mode, selBox]
  );

  const headerActive = useCallback(
    (axis: LineAxis, index: number): boolean =>
      axis === "col"
        ? sel.mode !== "rows" && index >= selBox.c1 && index <= selBox.c2
        : sel.mode !== "columns" && index >= selBox.r1 && index <= selBox.r2,
    [sel.mode, selBox]
  );

  // The contiguous band a header context-menu should act on: the active
  // multi-selection when the right-clicked header falls inside it (so
  // insert/delete operate on every selected line), otherwise just the
  // single clicked line.
  const lineBand = useCallback(
    (axis: LineAxis, index: number): { start: number; count: number } => {
      if (axis === "col" && sel.mode === "columns" && index >= selBox.c1 && index <= selBox.c2)
        return { start: selBox.c1, count: selBox.c2 - selBox.c1 + 1 };
      if (axis === "row" && sel.mode === "rows" && index >= selBox.r1 && index <= selBox.r2)
        return { start: selBox.r1, count: selBox.r2 - selBox.r1 + 1 };
      return { start: index, count: 1 };
    },
    [sel.mode, selBox]
  );

  const selectCell = useCallback((row: number, col: number, extend = false) => {
    setSel((p) =>
      extend
        ? { anchor: p.anchor, focus: { row, col }, mode: "range" }
        : { anchor: { row, col }, focus: { row, col }, mode: "range" }
    );
  }, []);

  // A whole column or row. ``extend`` grows a band of the same kind from its
  // anchor; from anything else it starts a new one.
  const selectLine = useCallback((axis: LineAxis, index: number, extend = false) => {
    const mode = axis === "col" ? "columns" : "rows";
    const at = axis === "col" ? { row: 0, col: index } : { row: index, col: 0 };
    setSel((p) => ({ anchor: extend && p.mode === mode ? p.anchor : at, focus: at, mode }));
  }, []);

  const moveSelection = useCallback(
    (dRow: number, dCol: number, extend = false) => {
      setSel((p) => {
        const { row, col } = grid.step(p.focus, dRow, dCol);
        return extend
          ? { anchor: p.anchor, focus: { row, col }, mode: "range" }
          : { anchor: { row, col }, focus: { row, col }, mode: "range" };
      });
    },
    [grid]
  );

  // Jump to the far edge of the current block of data along one axis —
  // Ctrl+Arrow. From a filled cell, the last filled cell before a gap; from
  // an empty one, the next filled cell. Excel's behaviour, and the reason a
  // sheet stays navigable when the canvas is far bigger than the data.
  const jumpSelection = useCallback(
    (dRow: number, dCol: number, extend = false) => {
      setSel((p) => {
        const filled = (row: number, col: number) => cells.get(keyOf(row, col)) != null;
        let at = grid.clampCell(p.focus);
        const startFilled = filled(at.row, at.col);
        for (;;) {
          const next = grid.step(at, dRow, dCol);
          if (next.row === at.row && next.col === at.col) break;
          const nextFilled = filled(next.row, next.col);
          // Leaving data: stop on the last filled cell. Crossing a gap:
          // stop on the first filled cell we reach.
          if (startFilled && !nextFilled) break;
          at = next;
          if (!startFilled && nextFilled) break;
        }
        return extend
          ? { anchor: p.anchor, focus: at, mode: "range" }
          : { anchor: at, focus: at, mode: "range" };
      });
    },
    [grid, cells]
  );

  // Select out to the end of the sheet's data (Ctrl+End) — the used range,
  // not the canvas, which is usually far larger and mostly empty.
  const selectToDataEnd = useCallback(
    (extend: boolean) => {
      const used = usedRange(cells);
      if (!used) return;
      const target = grid.clampCell({ row: used.r2, col: used.c2 });
      setSel((p) =>
        extend
          ? { anchor: p.anchor, focus: target, mode: "range" }
          : { anchor: target, focus: target, mode: "range" }
      );
    },
    [grid, cells]
  );

  // The name box label: the active cell ref, or the selection range / band.
  const label = useMemo(() => {
    const { r1, r2, c1, c2 } = selBox;
    if (sel.mode === "columns") {
      return c1 === c2 ? colIndexToLetter(c1) : `${colIndexToLetter(c1)}:${colIndexToLetter(c2)}`;
    }
    if (sel.mode === "rows") return r1 === r2 ? `${r1 + 1}` : `${r1 + 1}:${r2 + 1}`;
    const ref = (r: number, c: number) => `${colIndexToLetter(c)}${r + 1}`;
    return r1 === r2 && c1 === c2 ? ref(r1, c1) : `${ref(r1, c1)}:${ref(r2, c2)}`;
  }, [sel.mode, selBox]);

  return {
    sel,
    setSel,
    selBox,
    isInSel,
    headerActive,
    lineBand,
    label,
    selectCell,
    selectLine,
    moveSelection,
    jumpSelection,
    selectToDataEnd,
  };
};
