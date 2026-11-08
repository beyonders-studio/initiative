import {
  type FocusEvent,
  type KeyboardEvent,
  type MouseEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { useTranslation } from "react-i18next";

import { toast } from "@/lib/mascotToast";
import type { CellPos, SheetGrid } from "@/lib/spreadsheet/bounds";
import { type CellValue, colIndexToLetter, keyOf } from "@/lib/spreadsheet/coords";
import { coerceScalar } from "@/lib/spreadsheet/csv";
import { isFormula } from "@/lib/spreadsheet/formula";
import {
  FORMULA_REF_COLORS,
  type FormulaRefToken,
  referenceInsertTarget,
} from "@/lib/spreadsheet/formula-refs";
import {
  draftResolution,
  formatSheetPrefix,
  type SheetId,
  type SheetMeta,
  sheetNameKey,
} from "@/lib/spreadsheet/sheets";

import { createDraftStore } from "./draftStore";
import type { SpreadsheetCellsStore } from "./useSpreadsheetCells";

/** A formula-reference highlight on one cell: its color and which of its
 *  edges sit on the boundary of the reference's box (so the four edges of a
 *  range draw a single outline rather than a grid of boxes). */
export interface RefHighlight {
  color: string;
  top: boolean;
  right: boolean;
  bottom: boolean;
  left: boolean;
}

/** The cell an edit belongs to. Its text lives in the draft store. */
interface EditTarget {
  sheetId: SheetId;
  row: number;
  col: number;
}

interface UseSpreadsheetEditingArgs {
  readOnly: boolean;
  sheets: SheetMeta[];
  activeSheet: SheetMeta | undefined;
  cells: ReadonlyMap<string, CellValue>;
  grid: SheetGrid;
  focus: CellPos;
  selectCell: (row: number, col: number) => void;
  setCellOn: SpreadsheetCellsStore["setCellOn"];
  /** Put a sheet on screen. */
  showSheet: (id: SheetId) => void;
  scrollCellIntoView: (row: number, col: number) => void;
  focusGrid: () => void;
  /** Called as an edit begins. */
  onBegin: () => void;
}

/**
 * Editing a cell, from the in-cell input or the formula bar — both edit the
 * same draft, so a formula can be built from either — including pointing at
 * cells to put their references into a formula.
 *
 * The draft's text is kept out of React state (see ``createDraftStore``):
 * only the two inputs render it, so a keystroke re-renders those two and
 * not the editor. The editor re-renders when the cells the formula points at
 * change, because it outlines them.
 */
export const useSpreadsheetEditing = ({
  readOnly,
  sheets,
  activeSheet,
  cells,
  grid,
  focus,
  selectCell,
  setCellOn,
  showSheet,
  scrollCellIntoView,
  focusGrid,
  onBegin,
}: UseSpreadsheetEditingArgs) => {
  const { t } = useTranslation("files");
  const activeSheetId = activeSheet?.id ?? null;

  // An edit is anchored to the sheet it started on. While a formula is
  // being typed the user can switch tabs to point at another sheet's cells,
  // so the active sheet and the sheet being edited can differ; committing
  // writes to ``editing.sheetId`` and returns there.
  const [editing, setEditing] = useState<EditTarget | null>(null);
  const [draft] = useState(createDraftStore);

  const cellInputRef = useRef<HTMLInputElement | null>(null);
  const formulaBarInputRef = useRef<HTMLInputElement>(null);
  // The editing surface point-mode reference insertion and caret restoration
  // target: the in-cell input or the formula-bar input, whichever last gained
  // focus.
  const activeEditorRef = useRef<HTMLInputElement | null>(null);
  // Set when an edit is begun by focusing the formula bar, so the in-cell
  // input doesn't take focus from the bar when it attaches.
  const focusBarOnEditRef = useRef(false);
  // Set when an edit ends via the keyboard (Enter/Tab/Escape) so focus
  // returns to the grid — otherwise it falls to <body> as the input
  // unmounts and type-to-edit on the next cell stops working. A blur
  // (click-away) leaves this false so focus stays where the user clicked.
  const refocusGridRef = useRef(false);
  // Point mode (click/drag a cell into the formula being edited). The most
  // recently inserted reference: ``anchor`` is the cell it started on, ``span``
  // the draft range it currently occupies (so an extend re-splices over it).
  // Persists across the mouseup that ends a click — a later shift-click reads
  // it to extend into a range — and is cleared when the edit ends or the user
  // types (which invalidates the recorded span).
  const pointRefRef = useRef<{ anchor: CellPos; span: { start: number; end: number } } | null>(
    null
  );
  // True only while the mouse button is held after a point-mode click, so a
  // hover extends the range during a drag but not on a stray pass-over.
  const pointDraggingRef = useRef(false);
  useEffect(() => {
    const onUp = () => {
      // Keep the last reference so a follow-up shift-click can extend it.
      pointDraggingRef.current = false;
    };
    window.addEventListener("mouseup", onUp);
    return () => window.removeEventListener("mouseup", onUp);
  }, []);

  const beginEdit = useCallback(
    (row: number, col: number, initialDraft?: string) => {
      if (readOnly || !activeSheetId) return;
      onBegin();
      const existing = cells.get(keyOf(row, col));
      draft.set(initialDraft ?? (existing == null ? "" : String(existing)));
      // The cell may be selected but scrolled out of view, in which case it
      // isn't mounted and there is no input to type into. Bring it back
      // first; the input focuses itself when it attaches.
      scrollCellIntoView(row, col);
      setEditing({ sheetId: activeSheetId, row, col });
    },
    [cells, readOnly, activeSheetId, scrollCellIntoView, onBegin, draft]
  );

  const endEdit = useCallback(() => {
    setEditing(null);
    draft.set("");
    pointRefRef.current = null;
  }, [draft]);

  const commitEdit = useCallback(
    (next?: CellPos) => {
      if (!editing) return;
      const value = coerceScalar(draft.get());
      setCellOn(editing.sheetId, editing.row, editing.col, value === "" ? null : value);
      endEdit();
      // Building a cross-sheet formula leaves the grid on the sheet that was
      // being pointed at; committing belongs back where the formula lives.
      if (editing.sheetId !== activeSheetId) showSheet(editing.sheetId);
      if (next) selectCell(next.row, next.col);
    },
    [editing, draft, setCellOn, endEdit, selectCell, activeSheetId, showSheet]
  );

  // Hiding a sheet from the menu commits the draft on it first. Undo, redo
  // and a peer reach the same state without passing through there, so the
  // rule is applied to the sheets themselves rather than to the one action
  // that used to change them.
  useEffect(() => {
    if (!editing) return;
    const resolution = draftResolution(sheets, editing.sheetId);
    if (resolution === "commit") commitEdit();
    else if (resolution === "cancel") endEdit();
  }, [editing, sheets, commitEdit, endEdit]);

  // The sheet an open edit belongs to can vanish underneath it — a peer
  // deletes it, or an undo removes it. Committing would then write into a
  // container that no longer exists and quietly drop the draft, which reads
  // as "saved". End the edit explicitly instead, and say why.
  useEffect(() => {
    if (!editing || sheets.length === 0) return;
    if (sheets.some((s) => s.id === editing.sheetId)) return;
    endEdit();
    toast.info(t("spreadsheet.sheets.editSheetRemoved"));
  }, [editing, sheets, endEdit, t]);

  // A blur that hands focus to the *other* editing surface is a surface
  // switch, not an edit end — keep the draft alive instead of committing.
  const onBlur = useCallback(
    (e: FocusEvent<HTMLInputElement>) => {
      const next = e.relatedTarget;
      if (next === formulaBarInputRef.current || next === cellInputRef.current) return;
      commitEdit();
    },
    [commitEdit]
  );

  const onKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (!editing) return;
      switch (e.key) {
        case "Enter":
          e.preventDefault();
          refocusGridRef.current = true;
          commitEdit({ row: editing.row + 1, col: editing.col });
          return;
        case "Escape":
          e.preventDefault();
          refocusGridRef.current = true;
          endEdit();
          return;
        case "Tab":
          e.preventDefault();
          refocusGridRef.current = true;
          commitEdit(grid.step({ row: editing.row, col: editing.col }, 0, e.shiftKey ? -1 : 1));
          return;
      }
    },
    [editing, commitEdit, endEdit, grid]
  );

  // Typing invalidates the recorded reference span, so a later shift-click
  // starts a fresh reference rather than re-splicing.
  const onDraftChange = useCallback(
    (text: string) => {
      pointRefRef.current = null;
      draft.set(text);
    },
    [draft]
  );

  // Splice the clicked cell's reference into the formula being edited.
  // ``extend`` builds an ``A1:B3`` range from the drag anchor and overwrites
  // the reference inserted on mousedown; otherwise it resolves the caret
  // position (insert vs replace-the-last-ref) and seeds the drag. Returns
  // false when the caret isn't in a reference-accepting spot.
  const insertReference = useCallback(
    (row: number, col: number, extend: boolean): boolean => {
      if (!editing) return false;
      const input = activeEditorRef.current ?? cellInputRef.current;
      if (!input) return false;
      const text = draft.get();
      // Pointing at a cell on a sheet other than the formula's own has to
      // spell the sheet out — that IS the cross-sheet reference.
      const prefix =
        activeSheet && editing.sheetId !== activeSheetId ? formatSheetPrefix(activeSheet.name) : "";
      const cellRef = (r: number, c: number) => `${prefix}${colIndexToLetter(c)}${r + 1}`;
      let span: { start: number; end: number };
      let refText: string;
      if (extend) {
        const last = pointRefRef.current;
        if (!last) return false;
        span = last.span;
        const r1 = Math.min(last.anchor.row, row);
        const r2 = Math.max(last.anchor.row, row);
        const c1 = Math.min(last.anchor.col, col);
        const c2 = Math.max(last.anchor.col, col);
        refText =
          r1 === r2 && c1 === c2 ? cellRef(r1, c1) : `${cellRef(r1, c1)}:${cellRef(r2, c2)}`;
      } else {
        const target = referenceInsertTarget(text, input.selectionStart ?? text.length);
        if (target.kind === "none") return false;
        span =
          target.kind === "insert"
            ? { start: target.at, end: target.at }
            : { start: target.start, end: target.end };
        refText = cellRef(row, col);
        pointRefRef.current = { anchor: { row, col }, span };
      }
      const newEnd = span.start + refText.length;
      if (pointRefRef.current) pointRefRef.current.span = { start: span.start, end: newEnd };
      draft.set(text.slice(0, span.start) + refText + text.slice(span.end), {
        input,
        at: newEnd,
      });
      return true;
    },
    [editing, draft, activeSheet, activeSheetId]
  );

  // Point mode, on a cell's mousedown: while a formula is being edited, a
  // click puts the cell's reference into it rather than moving the
  // selection. Returns whether the click was taken.
  const pointMouseDown = useCallback(
    (row: number, col: number, e: MouseEvent): boolean => {
      if (!editing || !isFormula(draft.get())) return false;
      // Shift-click extends the last inserted reference into a range.
      const extend = e.shiftKey && pointRefRef.current !== null;
      if (!insertReference(row, col, extend)) return false;
      // Keeps the input focused, so the edit isn't committed by a blur.
      e.preventDefault();
      pointDraggingRef.current = true;
      return true;
    },
    [editing, draft, insertReference]
  );

  // Point mode, on a cell's mouseenter: a drag with the button still held
  // extends the reference into a range. Gated on the live button state so
  // a missed mouseup (release off-window) can't leave the drag stuck
  // following the cursor.
  const pointMouseEnter = useCallback(
    (row: number, col: number, e: MouseEvent): boolean => {
      if (!pointDraggingRef.current) return false;
      if (e.buttons === 0) {
        pointDraggingRef.current = false;
        return false;
      }
      insertReference(row, col, true);
      return true;
    },
    [insertReference]
  );

  // Null while the edit belongs to another sheet: the in-cell input isn't
  // mounted then, and the formula bar carries the draft instead.
  const editingCellKey =
    editing && editing.sheetId === activeSheetId ? `${editing.row}:${editing.col}` : null;
  // Focus the in-cell input when it *attaches*, not when the edit begins.
  // Typing into a cell that is selected but scrolled out of view has to
  // scroll it back first, and the input only exists a render later.
  const attachCellInput = useCallback((node: HTMLInputElement | null) => {
    cellInputRef.current = node;
    if (!node) return;
    // Edit begun from the formula bar: leave focus there.
    if (focusBarOnEditRef.current) {
      focusBarOnEditRef.current = false;
      return;
    }
    activeEditorRef.current = node;
    node.focus();
  }, []);
  const onCellInputFocus = useCallback(() => {
    activeEditorRef.current = cellInputRef.current;
  }, []);

  useEffect(() => {
    if (editingCellKey) return;
    // Edit ended via the keyboard: pull focus back to the grid (the input
    // has now unmounted) so the next keystroke is handled.
    if (!refocusGridRef.current) return;
    refocusGridRef.current = false;
    focusGrid();
  }, [editingCellKey, focusGrid]);

  // Focusing the bar begins an edit of the focus cell (unless one is already
  // live); the flag keeps focus in the bar instead of the cell input.
  const onFormulaBarFocus = useCallback(() => {
    activeEditorRef.current = formulaBarInputRef.current;
    if (readOnly || editing) return;
    focusBarOnEditRef.current = true;
    beginEdit(focus.row, focus.col);
  }, [readOnly, editing, beginEdit, focus.row, focus.col]);

  const onFormulaBarChange = useCallback(
    (text: string) => {
      if (!editing) {
        if (!activeSheetId) return;
        setEditing({ sheetId: activeSheetId, row: focus.row, col: focus.col });
      }
      onDraftChange(text);
    },
    [editing, activeSheetId, focus.row, focus.col, onDraftChange]
  );

  // Before the sheet on screen changes. Mid-formula, switching tabs is how
  // you point at another sheet, so the draft stays alive — but the in-cell
  // input is about to unmount, so focus moves to the formula bar. Anything
  // else commits, exactly like clicking away would. Returns whether the edit
  // is still open.
  const leaveSheet = useCallback((): boolean => {
    if (!editing) return false;
    if (isFormula(draft.get())) {
      activeEditorRef.current = formulaBarInputRef.current;
      requestAnimationFrame(() => formulaBarInputRef.current?.focus());
      return true;
    }
    commitEdit();
    return false;
  }, [editing, draft, commitEdit]);

  // Which of the formula's references point at the sheet on screen — one
  // to another sheet has no box to outline here. An unqualified reference
  // belongs to the sheet the formula lives on, which is only the visible
  // one when the user hasn't tabbed away mid-formula.
  const activeKey = activeSheet ? sheetNameKey(activeSheet.name) : null;
  const editingHere = editing?.sheetId === activeSheetId;
  const isRefOnScreen = useCallback(
    (token: FormulaRefToken): boolean =>
      activeKey !== null &&
      (token.sheet === null ? editingHere : sheetNameKey(token.sheet) === activeKey),
    [activeKey, editingHere]
  );
  const boxes = useSyncExternalStore(draft.subscribe, draft.boxes);
  const visibleRefs = useMemo(() => boxes.filter(isRefOnScreen), [boxes, isRefOnScreen]);

  // The reference highlight for a single cell, or null. Scans the (few)
  // references rather than enumerating every cell of every range, so a huge
  // ``A1:A100000`` stays cheap.
  const refHighlightAt = useCallback(
    (r: number, c: number): RefHighlight | null => {
      for (const token of visibleRefs) {
        if (r >= token.r1 && r <= token.r2 && c >= token.c1 && c <= token.c2) {
          return {
            color: FORMULA_REF_COLORS[token.colorIndex % FORMULA_REF_COLORS.length],
            top: r === token.r1,
            bottom: r === token.r2,
            left: c === token.c1,
            right: c === token.c2,
          };
        }
      }
      return null;
    },
    [visibleRefs]
  );

  return {
    editing,
    draft,
    beginEdit,
    commitEdit,
    cancelEdit: endEdit,
    leaveSheet,
    pointMouseDown,
    pointMouseEnter,
    isRefOnScreen,
    refHighlightAt,
    /** Handlers shared by the in-cell input and the formula bar. */
    onKeyDown,
    onBlur,
    cellInput: { attach: attachCellInput, onFocus: onCellInputFocus, onChange: onDraftChange },
    formulaBar: {
      inputRef: formulaBarInputRef,
      onFocus: onFormulaBarFocus,
      onChange: onFormulaBarChange,
    },
  };
};
