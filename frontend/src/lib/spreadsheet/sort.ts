/**
 * Whole-sheet sort by a single column.
 *
 * Reorders entire rows (like Excel's "Sort sheet by column"): each row
 * is treated as a record and rows are permuted by the value in the
 * chosen column, keeping every other column aligned with its row. Cell
 * values, per-cell styles, and per-row formatting (height / row style)
 * all travel with the row so a sorted sheet looks identical to its
 * pre-sort self, just reordered.
 *
 * The logic is pure (no Yjs / React) so it can be unit-tested and then
 * applied by the editor inside a single collaborative transaction.
 */

import { type CellValue, keyOf, parseKey } from "@/lib/spreadsheet/coords";
import type { CellFmt, RowFmt } from "@/lib/spreadsheet/styles";
import { collator } from "@/ui/lib/intl";

export type SortDirection = "asc" | "desc";

const isBlank = (v: CellValue | undefined): boolean => v === undefined || v === null || v === "";

// One reused collator for text comparison. Constructing a collator per
// comparison — which `String.prototype.localeCompare` effectively does —
// dominates sort time on large, text-heavy columns; a shared instance is
// dramatically faster. ``numeric`` gives natural ordering ("item2" before
// "item10") and ``sensitivity: "base"`` makes it case-insensitive. The
// sort still runs synchronously on the main thread, which is fine for the
// typical hundreds-to-low-thousands of rows; a sheet near MAX_ROWS
// (100k) with mostly text would be the case to revisit (e.g. a Worker).
const textCollator = collator(undefined, { numeric: true, sensitivity: "base" });

/**
 * Cross-type ordering (ascending): numbers, then text, then booleans —
 * matching Excel's sort precedence. Blanks are handled separately and
 * always sink to the bottom regardless of direction.
 */
const typeRank = (v: CellValue): number => {
  if (typeof v === "number") return 0;
  if (typeof v === "boolean") return 2;
  return 1; // string
};

/** Compare two non-blank cell values for ascending order. */
const compareValues = (a: CellValue, b: CellValue): number => {
  const ra = typeRank(a);
  const rb = typeRank(b);
  if (ra !== rb) return ra - rb;
  if (typeof a === "number" && typeof b === "number") {
    return a < b ? -1 : a > b ? 1 : 0;
  }
  if (typeof a === "boolean" && typeof b === "boolean") {
    return a === b ? 0 : a ? 1 : -1; // false < true
  }
  // Natural (numeric-aware), case-insensitive text compare so "item2"
  // sorts before "item10" and "Apple" next to "apple".
  return textCollator.compare(String(a), String(b));
};

export interface SortSheetResult {
  cells: Record<string, CellValue>;
  cellStyles: Record<string, CellFmt>;
  rows: Record<string, RowFmt>;
  /** False when the sort was a no-op (already ordered / nothing to sort). */
  changed: boolean;
}

interface SortSheetOptions {
  column: number;
  direction: SortDirection;
  /** First row included in the sort; rows above stay pinned (e.g. frozen
   *  header rows). Defaults to 0. */
  startRow?: number;
}

/**
 * Sort the whole sheet by one column, returning fully-remapped copies of
 * the cell map, per-cell styles, and per-row formatting.
 *
 * Rows ``[startRow, maxRow]`` (``maxRow`` = the last row that holds any
 * data or formatting) are permuted; everything outside that band is left
 * exactly where it is. Because the permutation is a bijection on the band
 * and columns never move, no two source cells can collide on a target key.
 */
export const sortSheetByColumn = (
  cells: ReadonlyMap<string, CellValue>,
  cellStyles: Record<string, CellFmt>,
  rowFmt: Record<string, RowFmt>,
  options: SortSheetOptions
): SortSheetResult => {
  const { column, direction } = options;
  const startRow = Math.max(0, options.startRow ?? 0);

  // Inclusive max row across every row-keyed structure so formatting on
  // an otherwise-empty trailing row still participates.
  let maxRow = -1;
  const scanRowColKey = (key: string) => {
    const p = parseKey(key);
    if (p && p[0] > maxRow) maxRow = p[0];
  };
  for (const key of cells.keys()) scanRowColKey(key);
  for (const key of Object.keys(cellStyles)) scanRowColKey(key);
  for (const key of Object.keys(rowFmt)) {
    const r = Number(key);
    if (Number.isInteger(r) && r > maxRow) maxRow = r;
  }

  const passthrough = (): SortSheetResult => ({
    cells: Object.fromEntries(cells),
    cellStyles: { ...cellStyles },
    rows: { ...rowFmt },
    changed: false,
  });

  if (maxRow < startRow) return passthrough();

  // Decorate-sort-undecorate so the comparator stays stable: equal keys
  // (and blanks) keep their original relative order.
  const decorated = [];
  for (let r = startRow; r <= maxRow; r++) {
    decorated.push({ row: r, idx: r - startRow, value: cells.get(keyOf(r, column)) });
  }
  decorated.sort((a, b) => {
    const aBlank = isBlank(a.value);
    const bBlank = isBlank(b.value);
    if (aBlank && bBlank) return a.idx - b.idx;
    if (aBlank) return 1; // blanks always last
    if (bBlank) return -1;
    const base = compareValues(a.value as CellValue, b.value as CellValue);
    if (base !== 0) return direction === "asc" ? base : -base;
    return a.idx - b.idx; // stable tie-break
  });

  // oldRow -> newRow within the sorted band.
  const remap = new Map<number, number>();
  decorated.forEach((entry, i) => {
    remap.set(entry.row, startRow + i);
  });
  const mapRow = (r: number): number => (r >= startRow && r <= maxRow ? (remap.get(r) ?? r) : r);

  const changed = decorated.some((entry, i) => entry.row !== startRow + i);
  if (!changed) return passthrough();

  // Remap a "r:c"-keyed structure by row, leaving columns untouched.
  const remapRowColKeys = <T>(
    src: Record<string, T> | ReadonlyMap<string, T>
  ): Record<string, T> => {
    const out: Record<string, T> = {};
    const entries = src instanceof Map ? src.entries() : Object.entries(src);
    for (const [key, value] of entries) {
      const p = parseKey(key);
      if (!p) {
        out[key] = value as T;
        continue;
      }
      out[keyOf(mapRow(p[0]), p[1])] = value as T;
    }
    return out;
  };

  // rowFmt keys are bare row indices, not "r:c".
  const newRows: Record<string, RowFmt> = {};
  for (const [key, value] of Object.entries(rowFmt)) {
    const r = Number(key);
    if (!Number.isInteger(r)) {
      newRows[key] = value;
      continue;
    }
    newRows[String(mapRow(r))] = value;
  }

  return {
    cells: remapRowColKeys(cells),
    cellStyles: remapRowColKeys(cellStyles),
    rows: newRows,
    changed: true,
  };
};
