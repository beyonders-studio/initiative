import { type ClipboardEvent, useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type * as Y from "yjs";

import { toast } from "@/lib/mascotToast";
import { CEILING, clipToCeiling, type SheetGrid } from "@/lib/spreadsheet/bounds";
import {
  type Clip,
  type ClipMode,
  type ClipReader,
  clipFromSelection,
  clipMatchesClipboard,
  placeClip,
} from "@/lib/spreadsheet/clipboard";
import {
  type CellRange,
  type CellValue,
  cellRange,
  keyOf,
  parseKey,
} from "@/lib/spreadsheet/coords";
import { clipboardToCells, coerceScalar, offsetCells } from "@/lib/spreadsheet/csv";
import { type Evaluator, isFormula } from "@/lib/spreadsheet/formula";
import type { SheetId, SheetMeta } from "@/lib/spreadsheet/sheets";
import type { CellFmt } from "@/lib/spreadsheet/styles";

import { SPREADSHEET_ORIGINS } from "./origins";
import type { SpreadsheetCellsStore } from "./useSpreadsheetCells";
import type { SpreadsheetFormattingStore } from "./useSpreadsheetFormatting";
import type { SpreadsheetSelection } from "./useSpreadsheetSelection";

interface UseSpreadsheetClipboardArgs {
  readOnly: boolean;
  doc: Y.Doc;
  activeSheet: SheetMeta | undefined;
  cells: ReadonlyMap<string, CellValue>;
  evaluator: Evaluator;
  formatting: SpreadsheetFormattingStore;
  sel: SpreadsheetSelection;
  selBox: CellRange;
  setSel: (sel: SpreadsheetSelection) => void;
  grid: SheetGrid;
  setCell: SpreadsheetCellsStore["setCell"];
  bulkUpdate: SpreadsheetCellsStore["bulkUpdate"];
  bulkUpdateOn: SpreadsheetCellsStore["bulkUpdateOn"];
}

/**
 * Copy, cut and paste. The block most recently copied or cut is kept here
 * with its formulas and formatting; the OS clipboard gets the same block as
 * TSV of displayed values so it can be pasted into anything else.
 */
export const useSpreadsheetClipboard = ({
  readOnly,
  doc,
  activeSheet,
  cells,
  evaluator,
  formatting,
  sel,
  selBox,
  setSel,
  grid,
  setCell,
  bulkUpdate,
  bulkUpdateOn,
}: UseSpreadsheetClipboardArgs) => {
  const { t } = useTranslation("files");
  // A cut isn't destructive until a paste consumes it, so the marquee is a
  // promise rather than a change; Escape drops it. Both modes survive a
  // sheet switch, which is what makes copying between tabs work.
  const [clip, setClip] = useState<Clip | null>(null);

  const dropClip = useCallback(() => setClip(null), []);
  // An edit or a clear cancels a pending cut (Excel); a copy stays.
  const dropCut = useCallback(() => setClip((c) => (c?.mode === "cut" ? null : c)), []);

  // Resolve a cell to the value that should leave the editor: a formula
  // yields its computed result (or error token), a literal yields itself.
  // Keeps pastes as data, never raw ``=...`` text whose relative refs
  // wouldn't survive the move.
  const clipReader = useMemo<ClipReader>(
    () => ({
      raw: (row, col) => cells.get(keyOf(row, col)) ?? null,
      style: (row, col) => formatting.cellStyles[keyOf(row, col)],
      display: (row, col) => {
        const v = cells.get(keyOf(row, col)) ?? null;
        if (!isFormula(v)) return v;
        const { value, error } = evaluator.evaluate(row, col);
        return error ?? value;
      },
    }),
    [cells, formatting.cellStyles, evaluator]
  );

  const takeClip = useCallback(
    (mode: ClipMode): Clip | null => {
      if (!activeSheet) return null;
      // A whole-column or whole-row selection has no bounded rectangle, so
      // it takes the focus cell.
      const range = sel.mode === "range" ? selBox : cellRange(sel.focus.row, sel.focus.col);
      return clipFromSelection(
        mode,
        { sheetId: activeSheet.id, sheetName: activeSheet.name, range },
        clipReader
      );
    },
    [activeSheet, sel.mode, sel.focus, selBox, clipReader]
  );

  // Cut is driven from the keyboard because a non-editable grid gets no
  // native ``cut`` event; copy and paste use theirs.
  const cut = useCallback(() => {
    if (readOnly) return;
    const taken = takeClip("cut");
    if (!taken) return;
    setClip(taken);
    if (!taken.text) return;
    // Writing to the OS clipboard is asynchronous and refusable. Whether it
    // landed decides how a later paste breaks the tie with content copied
    // somewhere else, so the answer is recorded rather than assumed.
    void navigator.clipboard
      ?.writeText(taken.text)
      .then(() => setClip((c) => (c === taken ? { ...c, textOnClipboard: true } : c)))
      .catch(() => {});
  }, [readOnly, takeClip]);

  const copy = useCallback(
    (e: ClipboardEvent<HTMLDivElement>) => {
      const taken = takeClip("copy");
      if (!taken || taken.text === "") return;
      e.preventDefault();
      e.clipboardData.setData("text/plain", taken.text);
      setClip({ ...taken, textOnClipboard: true }); // supersedes any pending cut
    },
    [takeClip]
  );

  // Write a block into the sheet, clipped to the ceiling: cells past it can
  // neither be rendered nor saved, so they're dropped and counted rather
  // than written where nothing will ever show them. A cut's source clear
  // rides in the same transaction, so the move is one undo step and peers
  // never see the block in two places.
  const writeBlock = useCallback(
    (
      block: {
        cells: Record<string, CellValue>;
        /** Formatting to *replace* across ``range`` — a pasted block brings
         *  its own look, so whatever the target wore is cleared first. */
        styles?: { range: CellRange; values: Record<string, CellFmt> };
      },
      clear?: { sheetId: SheetId; keys: string[] }
    ) => {
      const { kept, dropped } = clipToCeiling(block.cells, CEILING);
      const styles = block.styles;
      doc.transact(() => {
        if (clear) {
          bulkUpdateOn(clear.sheetId, (draft) => {
            for (const key of clear.keys) draft.delete(key);
          });
        }
        bulkUpdate((draft) => {
          for (const [key, value] of Object.entries(kept)) {
            if (value === null) draft.delete(key);
            else draft.set(key, value);
          }
        });
        if (styles) {
          grid.forEachCell(grid.clampRange(styles.range), (r, c) =>
            formatting.updateCell(r, c, null)
          );
          for (const [key, fmt] of Object.entries(styles.values)) {
            const at = parseKey(key);
            if (!at || at[0] >= CEILING.rows || at[1] >= CEILING.cols) continue;
            formatting.updateCell(at[0], at[1], { style: fmt.style, format: fmt.format ?? null });
          }
        }
      }, SPREADSHEET_ORIGINS.PASTE);
      if (dropped > 0) toast.info(t("spreadsheet.pasteClipped", { count: dropped }));
    },
    [doc, bulkUpdate, bulkUpdateOn, formatting, grid, t]
  );

  const paste = useCallback(
    (e: ClipboardEvent<HTMLDivElement>) => {
      if (readOnly || !activeSheet) return;
      const { row, col } = sel.focus;
      const text = e.clipboardData.getData("text/plain");

      // Our own block, still on the clipboard: paste what was actually
      // copied — formulas and formatting — rather than the flattened text
      // the OS clipboard had to reduce it to.
      if (clipMatchesClipboard(clip, text)) {
        e.preventDefault();
        const placed = placeClip(clip, { sheetId: activeSheet.id, row, col });
        writeBlock(
          { cells: placed.cells, styles: { range: placed.target, values: placed.styles } },
          placed.clear.length > 0 ? { sheetId: clip.sheetId, keys: placed.clear } : undefined
        );
        const target = grid.clampRange(placed.target);
        setSel({
          anchor: { row: target.r1, col: target.c1 },
          focus: { row: target.r2, col: target.c2 },
          mode: "range",
        });
        if (clip.mode === "cut") setClip(null);
        return;
      }

      // Pasting something copied elsewhere: a marquee still pointing at our
      // own block is now stale and would only mislead.
      if (clip) setClip(null);
      if (!text) return;
      e.preventDefault();
      if (!text.includes("\n") && !text.includes("\r") && !text.includes("\t")) {
        setCell(row, col, coerceScalar(text));
        return;
      }
      const parsed = clipboardToCells(text);
      writeBlock({ cells: offsetCells(parsed.cells, row, col) });
    },
    [readOnly, activeSheet, clip, sel.focus, grid, setSel, setCell, writeBlock]
  );

  return { clip, dropClip, dropCut, cut, copy, paste };
};
