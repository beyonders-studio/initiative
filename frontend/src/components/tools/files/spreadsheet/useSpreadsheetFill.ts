import { useCallback, useEffect, useRef, useState } from "react";

import type { SpreadsheetCellsStore } from "@/components/tools/files/spreadsheet/useSpreadsheetCells";
import type { SpreadsheetSelection } from "@/components/tools/files/spreadsheet/useSpreadsheetSelection";
import type { SheetBounds } from "@/lib/spreadsheet/bounds";
import { type CellRange, type CellValue, keyOf } from "@/lib/spreadsheet/coords";
import { computeAutofillTarget, computeFillWrites } from "@/lib/spreadsheet/fill";

interface UseSpreadsheetFillArgs {
  readOnly: boolean;
  cells: ReadonlyMap<string, CellValue>;
  dimensions: SheetBounds;
  selBox: CellRange;
  setSel: (sel: SpreadsheetSelection) => void;
  bulkUpdate: SpreadsheetCellsStore["bulkUpdate"];
}

/** The fill handle: drag it to extend the selection's pattern, or
 *  double-click it to fill down as far as the neighbouring column goes. */
export const useSpreadsheetFill = ({
  readOnly,
  cells,
  dimensions,
  selBox,
  setSel,
  bulkUpdate,
}: UseSpreadsheetFillArgs) => {
  // ``sourceRef`` is the rectangle captured when the drag began, ``targetRef``
  // the latest extended rectangle. Both live in refs so the once-registered
  // window ``mouseup`` listener reads current values, never a stale closure.
  // ``preview`` mirrors the target in state purely to drive the tint.
  const sourceRef = useRef<CellRange | null>(null);
  const targetRef = useRef<CellRange | null>(null);
  const [preview, setPreview] = useState<CellRange | null>(null);

  // Tile / extrapolate the source rectangle across the new region in one
  // transaction, then keep the filled block selected. A target identical to
  // the source (a click with no drag) is a no-op. ``null`` writes clear
  // their cell so the map stays sparse.
  const commit = useCallback(
    (source: CellRange, target: CellRange) => {
      if (readOnly) return;
      const writes = computeFillWrites((r, c) => cells.get(keyOf(r, c)) ?? null, source, target);
      if (writes.size === 0) return;
      bulkUpdate((draft) => {
        for (const [key, value] of writes) {
          if (value == null) draft.delete(key);
          else draft.set(key, value);
        }
      });
      // Anchor on the target's top-left (not the source's) so an up/left
      // fill keeps the whole written region selected.
      setSel({
        anchor: { row: target.r1, col: target.c1 },
        focus: { row: target.r2, col: target.c2 },
        mode: "range",
      });
    },
    [readOnly, cells, bulkUpdate, setSel]
  );
  const commitRef = useRef(commit);
  commitRef.current = commit;

  // Grab the handle: the current selection is the source, and the preview
  // starts there (a click with no drag stays a no-op).
  const start = useCallback(() => {
    if (readOnly) return;
    sourceRef.current = selBox;
    targetRef.current = selBox;
    setPreview(selBox);
  }, [readOnly, selBox]);

  // Extend an in-progress fill toward a hovered cell, constrained to the
  // dominant axis (vertical vs horizontal), the way a fill handle is.
  // Returns whether a fill is in progress to take the hover.
  const extend = useCallback((row: number, col: number): boolean => {
    const source = sourceRef.current;
    if (!source) return false;
    const vert = Math.max(0, row - source.r2, source.r1 - row);
    const horiz = Math.max(0, col - source.c2, source.c1 - col);
    let target: CellRange;
    if (vert === 0 && horiz === 0) target = source;
    else if (vert >= horiz)
      target = { ...source, r1: Math.min(source.r1, row), r2: Math.max(source.r2, row) };
    else target = { ...source, c1: Math.min(source.c1, col), c2: Math.max(source.c2, col) };
    targetRef.current = target;
    setPreview(target);
    return true;
  }, []);

  const autofillDown = useCallback(() => {
    if (readOnly) return;
    const target = computeAutofillTarget(
      (r, c) => cells.get(keyOf(r, c)) ?? null,
      selBox,
      dimensions
    );
    commit(selBox, target);
  }, [readOnly, cells, selBox, dimensions, commit]);

  // A drag commits on release wherever the pointer is, on the grid or off.
  useEffect(() => {
    const onUp = () => {
      const source = sourceRef.current;
      if (!source) return;
      const target = targetRef.current ?? source;
      sourceRef.current = null;
      targetRef.current = null;
      setPreview(null);
      commitRef.current(source, target);
    };
    window.addEventListener("mouseup", onUp);
    return () => window.removeEventListener("mouseup", onUp);
  }, []);

  return { preview, start, extend, autofillDown };
};
