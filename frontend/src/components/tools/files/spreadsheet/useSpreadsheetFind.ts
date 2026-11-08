import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { toast } from "@/lib/mascotToast";
import type { CellPos } from "@/lib/spreadsheet/bounds";
import { type CellValue, keyOf } from "@/lib/spreadsheet/coords";
import { coerceScalar } from "@/lib/spreadsheet/csv";
import {
  type CellMatch,
  type FindOptions,
  findInCells,
  replaceAllInCells,
  replaceInValue,
} from "@/lib/spreadsheet/find";

import type { SpreadsheetCellsStore } from "./useSpreadsheetCells";

/** Stable empty result so a closed find bar doesn't churn its memos. */
const EMPTY_MATCHES: CellMatch[] = [];

interface UseSpreadsheetFindArgs {
  readOnly: boolean;
  cells: ReadonlyMap<string, CellValue>;
  focus: CellPos;
  selectCell: (row: number, col: number) => void;
  setCell: SpreadsheetCellsStore["setCell"];
  bulkUpdate: SpreadsheetCellsStore["bulkUpdate"];
}

/**
 * Find & replace on the sheet on screen. The strip is only mounted while
 * open, so the query survives a close only as long as the editor does —
 * which is what a find bar is expected to do.
 */
export const useSpreadsheetFind = ({
  readOnly,
  cells,
  focus,
  selectCell,
  setCell,
  bulkUpdate,
}: UseSpreadsheetFindArgs) => {
  const { t } = useTranslation("files");
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [replacement, setReplacement] = useState("");
  const [options, setOptions] = useState<FindOptions>({ matchCase: false, wholeCell: false });

  const matches = useMemo(
    () => (open && query ? findInCells(cells, query, options) : EMPTY_MATCHES),
    [open, query, options, cells]
  );

  // Where the cursor sits among the matches: an index, or -1 off them.
  const current = useMemo(
    () => matches.findIndex((m) => m.row === focus.row && m.col === focus.col),
    [matches, focus.row, focus.col]
  );

  // Step to the next (or previous) match and put the cursor on it, wrapping
  // at the ends the way a find always has.
  const step = useCallback(
    (delta: 1 | -1) => {
      if (matches.length === 0) return;
      // Not on a match yet: step forward to the first one after the cursor.
      const from =
        current >= 0
          ? current
          : delta === 1
            ? matches.findIndex(
                (m) => m.row > focus.row || (m.row === focus.row && m.col >= focus.col)
              )
            : -1;
      const base = from >= 0 ? from : delta === 1 ? -1 : 0;
      const next =
        current >= 0 || from < 0 ? (base + delta + matches.length) % matches.length : base;
      const target = matches[next];
      if (!target) return;
      selectCell(target.row, target.col);
    },
    [matches, current, focus.row, focus.col, selectCell]
  );

  const replaceCurrent = useCallback(() => {
    if (readOnly || matches.length === 0) return;
    const on = matches[current];
    if (!on) {
      step(1);
      return;
    }
    const next = replaceInValue(
      cells.get(keyOf(on.row, on.col)) ?? null,
      query,
      replacement,
      options
    );
    if (next === null) return;
    setCell(on.row, on.col, next === "" ? null : coerceScalar(next));
    step(1);
  }, [readOnly, matches, current, cells, query, replacement, options, setCell, step]);

  const replaceEvery = useCallback(() => {
    if (readOnly) return;
    const writes = replaceAllInCells(cells, query, replacement, options, coerceScalar);
    const count = Object.keys(writes).length;
    if (count === 0) return;
    bulkUpdate((draft) => {
      for (const [key, value] of Object.entries(writes)) {
        if (value == null) draft.delete(key);
        else draft.set(key, value);
      }
    });
    toast.success(t("spreadsheet.find.replaced", { count }));
  }, [readOnly, cells, query, replacement, options, bulkUpdate, t]);

  return {
    open,
    setOpen,
    query,
    setQuery,
    replacement,
    setReplacement,
    options,
    setOptions,
    matchCount: matches.length,
    /** 1-based; 0 when the cursor isn't on a match. */
    matchIndex: current + 1,
    step,
    replaceCurrent,
    replaceEvery,
  };
};
