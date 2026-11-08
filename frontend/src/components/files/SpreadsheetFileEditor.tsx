import type { ProviderAwareness } from "@lexical/yjs";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Loader2 } from "lucide-react";
import { type KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import * as Y from "yjs";

import { type CellHandlers, CellView } from "@/components/files/spreadsheet/SpreadsheetCell";
import { SpreadsheetFindBar } from "@/components/files/spreadsheet/SpreadsheetFindBar";
import { SpreadsheetFormulaBar } from "@/components/files/spreadsheet/SpreadsheetFormulaBar";
import {
  COL_HEADER_HEIGHT,
  LineHeader,
  type LineHeaderActions,
  ROW_HEADER_WIDTH,
} from "@/components/files/spreadsheet/SpreadsheetLineHeader";
import { SpreadsheetSheetTabs } from "@/components/files/spreadsheet/SpreadsheetSheetTabs";
import {
  SpreadsheetToolbar,
  type ToolbarSelection,
} from "@/components/files/spreadsheet/SpreadsheetToolbar";
import { useSpreadsheetAwareness } from "@/components/files/spreadsheet/useSpreadsheetAwareness";
import { useSpreadsheetCells } from "@/components/files/spreadsheet/useSpreadsheetCells";
import { useSpreadsheetClipboard } from "@/components/files/spreadsheet/useSpreadsheetClipboard";
import { useSpreadsheetEditing } from "@/components/files/spreadsheet/useSpreadsheetEditing";
import { useSpreadsheetFill } from "@/components/files/spreadsheet/useSpreadsheetFill";
import { useSpreadsheetFind } from "@/components/files/spreadsheet/useSpreadsheetFind";
import { useSpreadsheetFormatting } from "@/components/files/spreadsheet/useSpreadsheetFormatting";
import { useSpreadsheetHistory } from "@/components/files/spreadsheet/useSpreadsheetHistory";
import { useSpreadsheetResize } from "@/components/files/spreadsheet/useSpreadsheetResize";
import {
  ORIGIN_SELECTION,
  type SpreadsheetSelection,
  useSpreadsheetSelection,
} from "@/components/files/spreadsheet/useSpreadsheetSelection";
import { useSpreadsheetSheets } from "@/components/files/spreadsheet/useSpreadsheetSheets";
import { useSpreadsheetStructure } from "@/components/files/spreadsheet/useSpreadsheetStructure";
import { matchHistoryShortcut } from "@/hooks/useYjsHistory";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { MAX_COLS, MAX_ROWS, sheetGrid } from "@/lib/spreadsheet/bounds";
import {
  parseSpreadsheetContent,
  type SpreadsheetContent,
  type SpreadsheetSheetContent,
} from "@/lib/spreadsheet/content";
import {
  type CellValue,
  colIndexToLetter,
  keyOf,
  parseA1Range,
  parseKey,
  rangeContains,
} from "@/lib/spreadsheet/coords";
import { createEvaluator, type EvaluatorSheet, isFormula } from "@/lib/spreadsheet/formula";
import {
  MAX_SHEETS,
  type SheetId,
  type SheetMeta,
  sheetNameKey,
  visibleSheets,
} from "@/lib/spreadsheet/sheets";
import {
  formatCellValue,
  negativeRendersRed,
  resolveCellFormat,
  resolveCellStyle,
  styleToCss,
} from "@/lib/spreadsheet/styles";
import { cn } from "@/ui/lib/utils";

export type { SpreadsheetContent };

interface SpreadsheetFileEditorProps {
  /** The persisted workbook. Accepts any historical schema version — see
   *  {@link parseSpreadsheetContent}. */
  initialContent: SpreadsheetContent;
  onContentChange: (content: SpreadsheetContent) => void;
  fileTitle: string;
  readOnly: boolean;
  className?: string;
  /** When non-null, cells live in ``yDoc.getMap("cells")`` and edits
   *  broadcast to peers in real time. When null (collab disabled or
   *  not yet ready), the editor falls back to local component state
   *  with the same UX. */
  yDoc?: Y.Doc | null;
  /** Whether the collaboration provider has completed its initial sync.
   *  Until then the workbook must not be seeded from ``initialContent``
   *  (see ``useSpreadsheetSheets``). Ignored when ``yDoc`` is null. */
  isSynced?: boolean;
  /** Whether this body has synced with its room at least once. The syncing
   *  cover waits for that and no longer: a reconnect after it leaves the
   *  file in place. */
  hasSynced?: boolean;
  /** Read a file into sheets. Supplied by the host, which knows the file
   *  and community this editor is showing; absent when import is unavailable. */
  onImportFile?: (file: File) => Promise<SpreadsheetSheetContent[]>;
  /** Awareness handle from the same provider as ``yDoc``. Used to
   *  publish / observe selected-cell presence rings. */
  awareness?: ProviderAwareness | null;
  /** Local user (id + display name) for awareness state. */
  currentUser?: { id: number; name: string } | null;
}

const GROW_THRESHOLD = 5;
const ROW_GROWTH_STEP = 50;
const COL_GROWTH_STEP = 10;
// Long enough to coalesce a burst of typing, far shorter than the autosave
// debounce it feeds (2s solo, 10s collaborating).
const SNAPSHOT_DEBOUNCE_MS = 300;

// Functions that aggregate a range — picking one from the toolbar with a
// multi-cell selection fills the range in automatically (AutoSum-style).
const AGGREGATE_FUNCTIONS = new Set(["SUM", "AVERAGE", "MIN", "MAX", "COUNT", "COUNTA"]);

/** Stable empty map for the render before the workbook is bootstrapped. */
const EMPTY_CELLS: ReadonlyMap<string, CellValue> = new Map();

export const SpreadsheetFileEditor = ({
  initialContent,
  onContentChange,
  fileTitle,
  readOnly,
  className,
  yDoc = null,
  isSynced = true,
  hasSynced = isSynced,
  onImportFile,
  awareness = null,
  currentUser = null,
}: SpreadsheetFileEditorProps) => {
  const { t } = useTranslation(["files", "common"]);

  const parsedInitial = useMemo(() => parseSpreadsheetContent(initialContent), [initialContent]);

  // Always operate on a Y.Doc so the (battle-tested) collaborative code
  // path is the single path and undo/redo works even with collaboration
  // off. When the provider supplies a real doc we use it; otherwise an
  // in-memory fallback. Awareness intentionally stays on the real
  // ``yDoc`` (a fallback doc has no provider/peers).
  //
  // ``useState`` (not ``useMemo``) so the doc is created exactly once
  // per real mount and re-created if React 18 StrictMode remounts; the
  // cleanup destroys *only* the fallback doc (never the provider's
  // ``yDoc``, which the parent owns).
  const [fallbackDoc] = useState(() => new Y.Doc());
  useEffect(() => () => fallbackDoc.destroy(), [fallbackDoc]);
  const docForData = yDoc ?? fallbackDoc;

  // The workbook level: which sheets exist, and every sheet's cells (the
  // evaluator needs all of them to resolve ``=Sheet2!A1``). Called before
  // the per-sheet hooks because it is what creates their Y.Maps.
  const workbook = useSpreadsheetSheets({
    yDoc: docForData,
    initialContent: parsedInitial,
    // A provider-backed doc is empty until the initial sync lands; seeding
    // it earlier would push the stale REST snapshot into the live room.
    seedAllowed: yDoc === null || isSynced,
  });
  const { sheets, cellsBySheet, version: workbookVersion } = workbook;

  // The sheet on screen. Tracked by id and re-resolved against the live
  // list so a peer deleting the active sheet lands us on a real one rather
  // than a blank grid.
  const [requestedSheetId, setRequestedSheetId] = useState<SheetId | null>(null);
  // A hidden sheet is still a real sheet — a formula reads it, and an edit
  // in progress can belong to it — so it is only the *landing* choice that
  // skips them. ``parseSpreadsheetContent`` guarantees at least one is
  // visible, so the fallback always finds a sheet.
  const requested = sheets.find((s) => s.id === requestedSheetId);
  const activeSheet =
    requested && !requested.hidden
      ? requested
      : (visibleSheets(sheets)[0] ?? (sheets[0] as SheetMeta | undefined));
  const activeSheetId = activeSheet?.id ?? null;

  const cells = (activeSheetId ? cellsBySheet.get(activeSheetId) : undefined) ?? EMPTY_CELLS;

  const { dimensions, setCell, setCellOn, setDimensions, bulkUpdate, bulkUpdateOn, replaceAll } =
    useSpreadsheetCells({
      yDoc: docForData,
      sheetId: activeSheetId,
      version: workbookVersion,
    });
  const formatting = useSpreadsheetFormatting({
    yDoc: docForData,
    sheetId: activeSheetId,
    version: workbookVersion,
  });
  const history = useSpreadsheetHistory(docForData);
  // Stable callbacks (memoized in the hook, keyed on the doc) — depend
  // on these rather than the per-render ``history`` object literal.
  const { undo: undoHistory, redo: redoHistory } = history;

  const containerRef = useRef<HTMLDivElement>(null);
  // The grid's keyboard and clipboard handlers only fire while focus is
  // inside it, so everything that takes focus elsewhere hands it back here.
  const focusGrid = useCallback(() => containerRef.current?.focus(), []);
  // Which header/cell drag is in progress (null = not dragging).
  const selectingRef = useRef<SpreadsheetSelection["mode"] | null>(null);
  useEffect(() => {
    // Any release ends it, so a drag that ends off-grid stops extending.
    const onUp = () => {
      selectingRef.current = null;
    };
    window.addEventListener("mouseup", onUp);
    return () => window.removeEventListener("mouseup", onUp);
  }, []);

  const { drag, colWidth, rowHeight, startResize, resetSize } = useSpreadsheetResize({
    readOnly,
    formatting,
  });

  // Stable refs the virtualizer's estimateSize reads, so its callback
  // identity never changes (a changing estimateSize fights the cache);
  // we explicitly ``measure()`` below when sizes actually change.
  const colWidthRef = useRef(colWidth);
  const rowHeightRef = useRef(rowHeight);
  useEffect(() => {
    colWidthRef.current = colWidth;
    rowHeightRef.current = rowHeight;
  }, [colWidth, rowHeight]);

  // Auto-grow dimensions when the cell map writes past the canvas.
  // Local-only — each peer converges on the same size from the shared
  // cell map without a Y.Map round-trip per write.
  useEffect(() => {
    let maxRow = -1;
    let maxCol = -1;
    for (const key of cells.keys()) {
      const colon = key.indexOf(":");
      if (colon < 0) continue;
      const r = Number(key.slice(0, colon));
      const c = Number(key.slice(colon + 1));
      if (r > maxRow) maxRow = r;
      if (c > maxCol) maxCol = c;
    }
    const nextRows = Math.min(Math.max(maxRow + 1, dimensions.rows), MAX_ROWS);
    const nextCols = Math.min(Math.max(maxCol + 1, dimensions.cols), MAX_COLS);
    if (nextRows !== dimensions.rows || nextCols !== dimensions.cols) {
      setDimensions({ rows: nextRows, cols: nextCols });
    }
  }, [cells, dimensions, setDimensions]);

  // Formula evaluator bound to the current workbook snapshot. Rebuilt
  // whenever any sheet's cells change (local edit, remote peer write, and
  // undo/redo all yield fresh maps), so computed values recalc
  // automatically; each cell is evaluated at most once per snapshot via the
  // evaluator's internal cache, and only for cells the virtualized grid
  // actually renders.
  const evaluator = useMemo(() => {
    const evaluatorSheets: EvaluatorSheet[] = sheets.map((sheet) => ({
      id: sheet.id,
      name: sheet.name,
      cells: cellsBySheet.get(sheet.id) ?? EMPTY_CELLS,
    }));
    return createEvaluator({
      sheets: evaluatorSheets,
      activeSheetId: activeSheetId ?? "",
    });
  }, [sheets, cellsBySheet, activeSheetId]);

  // Emit the JSON snapshot to the parent on every change so the
  // existing autosave hook can PATCH ``file.content``. Captured in
  // a ref so callers can pass an inline arrow without thrashing this
  // effect into a setState loop.
  const onContentChangeRef = useRef(onContentChange);
  useEffect(() => {
    onContentChangeRef.current = onContentChange;
  }, [onContentChange]);
  // Skip the on-mount run so opening a doc doesn't flip ``isDirty`` and
  // arm the autosave timer with no user interaction.
  const skipFirstEmitRef = useRef(true);
  // Snapshotting serializes every sheet, and a keystroke changes one cell.
  // The save is already debounced upstream, so coalescing the snapshots
  // that feed it changes nothing a user can see and takes an O(workbook)
  // step off the keystroke path.
  const snapshotRef = useRef(workbook.snapshot);
  snapshotRef.current = workbook.snapshot;
  const snapshotTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const emitSnapshot = useCallback(() => {
    snapshotTimerRef.current = null;
    // Read the snapshot straight off the Y.Doc rather than from the
    // on-screen sheet's mirrored state: an edit on any sheet — including
    // one the user has tabbed away from — belongs in the saved workbook.
    onContentChangeRef.current(snapshotRef.current());
  }, []);
  useEffect(() => {
    if (skipFirstEmitRef.current) {
      skipFirstEmitRef.current = false;
      return;
    }
    if (snapshotTimerRef.current !== null) clearTimeout(snapshotTimerRef.current);
    snapshotTimerRef.current = setTimeout(emitSnapshot, SNAPSHOT_DEBOUNCE_MS);
  }, [workbookVersion, emitSnapshot]);
  // A snapshot still waiting when the editor goes away would strand the
  // last edit, so it goes out immediately instead.
  useEffect(
    () => () => {
      if (snapshotTimerRef.current === null) return;
      clearTimeout(snapshotTimerRef.current);
      emitSnapshot();
    },
    [emitSnapshot]
  );

  const { rows: frozenRows, cols: frozenCols } = formatting.frozen;
  const prefixRow = useMemo(() => {
    const out = [0];
    for (let r = 0; r < frozenRows; r++) out.push(out[r] + rowHeight(r));
    return out;
  }, [frozenRows, rowHeight]);
  const prefixCol = useMemo(() => {
    const out = [0];
    for (let c = 0; c < frozenCols; c++) out.push(out[c] + colWidth(c));
    return out;
  }, [frozenCols, colWidth]);
  const frozenBandHeight = prefixRow[frozenRows] ?? 0;
  const frozenBandWidth = prefixCol[frozenCols] ?? 0;

  // The header strip and the frozen band are sticky, so they cover the start
  // of the scroll box. Telling the virtualizer how much is covered is what
  // makes "scroll this cell into view" land it below them rather than
  // underneath them.
  const rowVirtualizer = useVirtualizer({
    count: dimensions.rows,
    getScrollElement: () => containerRef.current,
    estimateSize: (index) => rowHeightRef.current(index),
    overscan: 5,
    scrollPaddingStart: COL_HEADER_HEIGHT + frozenBandHeight,
  });

  const colVirtualizer = useVirtualizer({
    count: dimensions.cols,
    getScrollElement: () => containerRef.current,
    estimateSize: (index) => colWidthRef.current(index),
    horizontal: true,
    overscan: 3,
    scrollPaddingStart: ROW_HEADER_WIDTH + frozenBandWidth,
  });

  // Bring a cell into view if it isn't already. ``align: "auto"`` leaves the
  // scroll alone when the cell is visible, so this is safe to run on every
  // selection change — dragging a selection across visible cells does
  // nothing, arrowing off the edge scrolls by exactly one line.
  const scrollCellIntoView = useCallback(
    (row: number, col: number) => {
      rowVirtualizer.scrollToIndex(row, { align: "auto" });
      colVirtualizer.scrollToIndex(col, { align: "auto" });
    },
    [rowVirtualizer, colVirtualizer]
  );

  // Recompute virtual offsets when explicit sizes change (remote write,
  // local resize commit, or live drag preview). Without this the
  // virtualizer keeps stale cached sizes.
  useEffect(() => {
    rowVirtualizer.measure();
  }, [formatting.rows, drag, rowVirtualizer]);
  useEffect(() => {
    colVirtualizer.measure();
  }, [formatting.columns, drag, colVirtualizer]);

  // Auto-grow the canvas when scrolling near the edge so the grid feels
  // unbounded. Local: scroll position is a personal UX concern.
  const virtualRows = rowVirtualizer.getVirtualItems();
  const virtualCols = colVirtualizer.getVirtualItems();
  useEffect(() => {
    if (virtualRows.length === 0) return;
    const lastRow = virtualRows[virtualRows.length - 1].index;
    if (lastRow >= dimensions.rows - GROW_THRESHOLD && dimensions.rows < MAX_ROWS) {
      setDimensions({
        rows: Math.min(dimensions.rows + ROW_GROWTH_STEP, MAX_ROWS),
        cols: dimensions.cols,
      });
    }
  }, [virtualRows, dimensions, setDimensions]);
  useEffect(() => {
    if (virtualCols.length === 0) return;
    const lastCol = virtualCols[virtualCols.length - 1].index;
    if (lastCol >= dimensions.cols - GROW_THRESHOLD && dimensions.cols < MAX_COLS) {
      setDimensions({
        rows: dimensions.rows,
        cols: Math.min(dimensions.cols + COL_GROWTH_STEP, MAX_COLS),
      });
    }
  }, [virtualCols, dimensions, setDimensions]);

  // What the sheet is shaped like: how far it extends and which lines it
  // draws at zero size. Every "where can the cursor go", "which cells does
  // this range cover" and "what is the next cell" question goes through it,
  // so there is one answer rather than one per call site.
  const isRowHidden = useCallback(
    (r: number) => formatting.rows[String(r)]?.hidden === true,
    [formatting.rows]
  );
  const isColHidden = useCallback(
    (c: number) => formatting.columns[String(c)]?.hidden === true,
    [formatting.columns]
  );

  const grid = useMemo(
    () => sheetGrid({ bounds: dimensions, isRowHidden, isColHidden }),
    [dimensions, isRowHidden, isColHidden]
  );

  // What actually gets drawn. A hidden line still has a place in the
  // virtualizer — at zero size, so the lines after it sit where they should —
  // but it has no cells and no header on screen. Its offset is the next
  // line's, so anything it drew would sit on top of that line.
  const visibleRows = useMemo(
    () => virtualRows.filter((row) => !isRowHidden(row.index)),
    [virtualRows, isRowHidden]
  );
  const visibleCols = useMemo(
    () => virtualCols.filter((col) => !isColHidden(col.index)),
    [virtualCols, isColHidden]
  );

  const {
    sel,
    setSel,
    selBox,
    isInSel,
    headerActive,
    lineBand,
    label: selectionLabel,
    selectCell,
    selectLine,
    moveSelection,
    jumpSelection,
    selectToDataEnd,
  } = useSpreadsheetSelection({ grid, cells });

  // Keep the active cell on screen. Scrolling with the mouse doesn't move
  // the selection, so this never fights the user — it only runs when
  // something moved the cursor.
  const focusRow = sel.focus.row;
  const focusCol = sel.focus.col;
  useEffect(() => {
    scrollCellIntoView(focusRow, focusCol);
  }, [focusRow, focusCol, scrollCellIntoView]);

  // Name-box go-to: select the cell/range the text names (clamped to the grid)
  // and scroll its top-left into view. Invalid input is ignored — the name box
  // resets to the current selection on blur.
  const navigateToRef = useCallback(
    (text: string) => {
      // The name box accepts a sheet qualifier (``Budget!B4``), which jumps
      // tabs as well as cells. An unknown sheet name is ignored, like any
      // other unparseable input.
      let target = text;
      const bang = text.lastIndexOf("!");
      if (bang > 0) {
        const named = text.slice(0, bang).trim().replace(/^'|'$/g, "").replace(/''/g, "'");
        const match = sheets.find((s) => sheetNameKey(s.name) === sheetNameKey(named));
        if (!match) return;
        setRequestedSheetId(match.id);
        target = text.slice(bang + 1);
      }
      const parsed = parseA1Range(target);
      if (!parsed) return;
      const { r1, c1, r2, c2 } = grid.clampRange(parsed);
      // Anchor at the bottom-right so the active (focus) cell is the top-left,
      // matching how a spreadsheet lands the cursor on a navigated range.
      setSel({ anchor: { row: r2, col: c2 }, focus: { row: r1, col: c1 }, mode: "range" });
      rowVirtualizer.scrollToIndex(r1, { align: "center" });
      colVirtualizer.scrollToIndex(c1, { align: "center" });
      focusGrid();
    },
    [grid, rowVirtualizer, colVirtualizer, sheets, setSel, focusGrid]
  );

  const fill = useSpreadsheetFill({ readOnly, cells, dimensions, selBox, setSel, bulkUpdate });

  const { peerSelectionsByCell } = useSpreadsheetAwareness({
    awareness,
    clientId: yDoc?.clientID ?? null,
    user: currentUser,
    selected: sel.focus,
    sheetId: activeSheetId,
    enabled: Boolean(awareness && yDoc && currentUser),
    publishLocal: !readOnly,
  });

  const clipboard = useSpreadsheetClipboard({
    readOnly,
    doc: docForData,
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
  });
  const { clip, dropClip, dropCut } = clipboard;

  const {
    editing,
    draft,
    beginEdit,
    commitEdit,
    cancelEdit,
    leaveSheet,
    pointMouseDown,
    pointMouseEnter,
    isRefOnScreen,
    refHighlightAt,
    onKeyDown: onEditorKeyDown,
    onBlur: onEditorBlur,
    cellInput,
    formulaBar,
  } = useSpreadsheetEditing({
    readOnly,
    sheets,
    activeSheet,
    cells,
    grid,
    focus: sel.focus,
    selectCell,
    setCellOn,
    showSheet: setRequestedSheetId,
    scrollCellIntoView,
    focusGrid,
    onBegin: dropCut,
  });

  // Insert a formula from the toolbar's function menu. When an aggregate
  // (SUM/AVERAGE/…) is picked with a multi-cell range selected, drop a
  // completed ``=FN(range)`` in the cell just past the selection — below a
  // tall selection, to the right of a wide one — so the formula never sits
  // inside its own range (which would be a cycle). Otherwise begin editing
  // the focus cell with a ``=FN(`` starter so the user fills the arguments.
  const insertFunction = useCallback(
    (name: string) => {
      if (readOnly) return;
      const isAggregate = AGGREGATE_FUNCTIONS.has(name);
      const { r1, r2, c1, c2 } = selBox;
      const isRange = sel.mode === "range" && (r1 !== r2 || c1 !== c2);
      if (isAggregate && isRange) {
        const rangeRef = `${colIndexToLetter(c1)}${r1 + 1}:${colIndexToLetter(c2)}${r2 + 1}`;
        const vertical = r2 - r1 >= c2 - c1;
        // Clamp into the grid: a selection ending on the last row/column
        // would otherwise target a cell that never renders, silently
        // dropping the formula.
        const { row: targetRow, col: targetCol } = grid.clampCell({
          row: vertical ? r2 + 1 : r1,
          col: vertical ? c1 : c2 + 1,
        });
        setCell(targetRow, targetCol, `=${name}(${rangeRef})`);
        selectCell(targetRow, targetCol);
        // Return focus to the grid so arrow keys work immediately (the menu
        // suppresses its own close-auto-focus so it can't fight this).
        focusGrid();
        return;
      }
      // Begin editing the focus cell; the editing-input focus effect takes
      // over once the input mounts.
      beginEdit(sel.focus.row, sel.focus.col, `=${name}(`);
    },
    [readOnly, selBox, sel.mode, sel.focus, grid, setCell, selectCell, beginEdit, focusGrid]
  );

  // Delete every cell value covered by the selection. For a range that's
  // the rectangle; for whole-column/row selections, only the cells that
  // actually hold data (the map is sparse) so a clear is bounded.
  const clearSelection = useCallback(() => {
    if (readOnly) return;
    dropCut();
    const { r1, r2, c1, c2 } = selBox;
    bulkUpdate((draft) => {
      if (sel.mode === "range") {
        for (let r = r1; r <= r2; r++) for (let c = c1; c <= c2; c++) draft.delete(keyOf(r, c));
        return;
      }
      for (const key of Array.from(draft.keys())) {
        const p = parseKey(key);
        if (!p) continue;
        const [r, c] = p;
        if (sel.mode === "columns" ? c >= c1 && c <= c2 : r >= r1 && r <= r2) {
          draft.delete(key);
        }
      }
    });
  }, [readOnly, sel.mode, selBox, bulkUpdate, dropCut]);

  const find = useSpreadsheetFind({
    readOnly,
    cells,
    focus: sel.focus,
    selectCell,
    setCell,
    bulkUpdate,
  });
  const { setOpen: setFindOpen } = find;
  const closeFind = useCallback(() => {
    setFindOpen(false);
    focusGrid();
  }, [setFindOpen, focusGrid]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      if (editing) return;
      if (readOnly) return;
      const histAction = matchHistoryShortcut(e);
      if (histAction) {
        e.preventDefault();
        if (histAction === "undo") undoHistory();
        else redoHistory();
        return;
      }
      // Cut (Ctrl/Cmd+X) — the grid div gets no native ``cut`` event, so we
      // drive it from the keyboard. Copy/paste still use the native events.
      if ((e.ctrlKey || e.metaKey) && (e.key === "x" || e.key === "X")) {
        e.preventDefault();
        clipboard.cut();
        return;
      }
      // Find and replace.
      if ((e.ctrlKey || e.metaKey) && (e.key === "f" || e.key === "F")) {
        e.preventDefault();
        setFindOpen(true);
        return;
      }
      const { row, col } = sel.focus;
      // Ctrl/Cmd + an arrow jumps to the edge of the block of data, the way
      // it does in every spreadsheet — the only practical way to cross a
      // canvas far larger than the data on it.
      const toEdge = e.ctrlKey || e.metaKey;
      const move = toEdge ? jumpSelection : moveSelection;
      switch (e.key) {
        case "Escape":
          if (clip) {
            e.preventDefault();
            dropClip();
          }
          return;
        case "ArrowDown":
          e.preventDefault();
          move(1, 0, e.shiftKey);
          return;
        case "ArrowUp":
          e.preventDefault();
          move(-1, 0, e.shiftKey);
          return;
        case "ArrowRight":
          e.preventDefault();
          move(0, 1, e.shiftKey);
          return;
        case "ArrowLeft":
          e.preventDefault();
          move(0, -1, e.shiftKey);
          return;
        case "Home":
          e.preventDefault();
          if (toEdge) selectCell(0, 0, e.shiftKey);
          else selectCell(row, 0, e.shiftKey);
          return;
        case "End":
          e.preventDefault();
          if (toEdge) selectToDataEnd(e.shiftKey);
          else jumpSelection(0, 1, e.shiftKey);
          return;
        case "Enter":
        case "F2":
          e.preventDefault();
          beginEdit(row, col);
          return;
        case "Backspace":
        case "Delete":
          e.preventDefault();
          clearSelection();
          return;
        case "Tab":
          e.preventDefault();
          moveSelection(0, e.shiftKey ? -1 : 1);
          return;
      }
      if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();
        beginEdit(row, col, e.key);
      }
    },
    [
      editing,
      readOnly,
      clip,
      clipboard.cut,
      dropClip,
      setFindOpen,
      undoHistory,
      redoHistory,
      sel.focus,
      moveSelection,
      jumpSelection,
      selectToDataEnd,
      selectCell,
      beginEdit,
      clearSelection,
    ]
  );

  const { sortColumn, insertLines, deleteLines, setLinesHidden, unhideAll, hasHidden } =
    useSpreadsheetStructure({
      readOnly,
      doc: docForData,
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
    });

  const totalGridWidth = colVirtualizer.getTotalSize();
  const totalGridHeight = rowVirtualizer.getTotalSize();

  // The cells' event handlers, rebuilt every render so they read current
  // state. Cells call them through ``cellHandlers``, whose identity never
  // changes, so a memoised cell re-renders only when what it draws changes.
  const cellHandlersRef = useRef<CellHandlers | null>(null);
  cellHandlersRef.current = {
    mouseDown: (r, c, e) => {
      if (e.button !== 0) return;
      if (pointMouseDown(r, c, e)) return;
      focusGrid();
      selectingRef.current = "range";
      selectCell(r, c, e.shiftKey);
    },
    mouseEnter: (r, c, e) => {
      if (pointMouseEnter(r, c, e)) return;
      // A fill drag in progress takes over hover: extend its preview
      // instead of moving the selection focus.
      if (fill.extend(r, c)) return;
      if (selectingRef.current === "range") selectCell(r, c, true);
    },
    doubleClick: (r, c) => beginEdit(r, c),
    toggleBoolean: (r, c) => {
      const value = cells.get(keyOf(r, c));
      if (readOnly || typeof value !== "boolean") return;
      selectCell(r, c);
      setCell(r, c, !value);
    },
    draftChange: cellInput.onChange,
    editingKeyDown: onEditorKeyDown,
    editingBlur: onEditorBlur,
    editingFocus: cellInput.onFocus,
    fillHandleMouseDown: fill.start,
    fillHandleDoubleClick: fill.autofillDown,
  };
  const cellHandlers = useMemo<CellHandlers>(
    () => ({
      mouseDown: (r, c, e) => cellHandlersRef.current?.mouseDown(r, c, e),
      mouseEnter: (r, c, e) => cellHandlersRef.current?.mouseEnter(r, c, e),
      doubleClick: (r, c) => cellHandlersRef.current?.doubleClick(r, c),
      toggleBoolean: (r, c) => cellHandlersRef.current?.toggleBoolean(r, c),
      draftChange: (text) => cellHandlersRef.current?.draftChange(text),
      editingKeyDown: (e) => cellHandlersRef.current?.editingKeyDown(e),
      editingBlur: (e) => cellHandlersRef.current?.editingBlur(e),
      editingFocus: () => cellHandlersRef.current?.editingFocus(),
      fillHandleMouseDown: () => cellHandlersRef.current?.fillHandleMouseDown(),
      fillHandleDoubleClick: () => cellHandlersRef.current?.fillHandleDoubleClick(),
    }),
    []
  );

  const attachCellInput = cellInput.attach;
  const fillPreview = fill.preview;
  const renderCell = useCallback(
    (r: number, c: number, left: number, top: number) => {
      const isActive = sel.focus.row === r && sel.focus.col === c;
      const isEditing =
        editing?.sheetId === activeSheetId && editing?.row === r && editing?.col === c;
      const value = cells.get(keyOf(r, c));
      const numberFormat = resolveCellFormat(r, c, formatting);
      // Formula cells show their computed result (or an error token); the
      // raw "=..." text is what ``beginEdit`` puts back in the input. The
      // computed result also drives number formatting and the red-negative
      // rule, exactly as a literal value would.
      const evaluated = isFormula(value) ? evaluator.evaluate(r, c) : null;
      const error = evaluated?.error ?? null;
      const resolved = evaluated ? evaluated.value : (value ?? null);
      const display = isEditing
        ? ""
        : error
          ? error
          : resolved == null
            ? ""
            : formatCellValue(resolved, numberFormat);
      const isBoolean = typeof value === "boolean" && !numberFormat;
      const peer = peerSelectionsByCell.get(keyOf(r, c));
      const inCut =
        clip !== null && clip.sheetId === activeSheetId && rangeContains(clip.origin, r, c);
      const cellCss = styleToCss(resolveCellStyle(r, c, formatting));
      // A formula error, or a red/redParens negative number, wins over any
      // explicit text color (Excel's numFmt color section overrides font).
      if (error || negativeRendersRed(resolved, numberFormat)) cellCss.color = "#dc2626";
      // The fill handle sits on the bottom-right corner of a cell-range
      // selection; the preview tint covers the live drag extent.
      const isFillCorner =
        !readOnly && !isEditing && sel.mode === "range" && r === selBox.r2 && c === selBox.c2;
      const inFillPreview = fillPreview
        ? r >= fillPreview.r1 && r <= fillPreview.r2 && c >= fillPreview.c1 && c <= fillPreview.c2
        : false;
      return (
        <CellView
          key={keyOf(r, c)}
          row={r}
          col={c}
          left={left}
          top={top}
          width={colWidth(c)}
          height={rowHeight(r)}
          cellCss={cellCss}
          isActive={isActive}
          inSelection={isInSel(r, c)}
          inCut={inCut}
          inFillPreview={inFillPreview}
          showFillHandle={isFillCorner}
          display={display}
          title={error ?? undefined}
          booleanValue={isBoolean ? (value as boolean) : null}
          readOnly={readOnly}
          editor={isEditing ? { draft, inputRef: attachCellInput, isRefOnScreen } : null}
          peerColor={peer?.selection.color ?? null}
          peerName={peer?.user.name ?? null}
          refHighlight={refHighlightAt(r, c)}
          handlers={cellHandlers}
        />
      );
    },
    [
      cells,
      evaluator,
      formatting,
      sel.focus,
      sel.mode,
      selBox,
      isInSel,
      clip,
      fillPreview,
      editing,
      activeSheetId,
      draft,
      attachCellInput,
      isRefOnScreen,
      refHighlightAt,
      readOnly,
      peerSelectionsByCell,
      colWidth,
      rowHeight,
      cellHandlers,
    ]
  );

  // The formula bar shows the focus cell's raw value (its formula/value as
  // stored, not the computed result) until an edit puts the draft there.
  const formulaBarValue = useMemo(() => {
    const raw = cells.get(keyOf(sel.focus.row, sel.focus.col));
    return raw == null ? "" : String(raw);
  }, [cells, sel.focus.row, sel.focus.col]);

  // --- sheet tabs ---------------------------------------------------------

  // Each sheet keeps its own cursor, so tabbing away and back lands where
  // you left off. A ref (not state) because nothing renders from it — the
  // selection it restores is written straight into ``setSel``.
  const selBySheetRef = useRef(new Map<SheetId, SpreadsheetSelection>());

  const selectSheet = useCallback(
    (id: SheetId) => {
      if (id === activeSheetId) return;
      if (activeSheetId) selBySheetRef.current.set(activeSheetId, sel);
      setRequestedSheetId(id);
      setSel(selBySheetRef.current.get(id) ?? ORIGIN_SELECTION);
      if (leaveSheet()) return;
      // The tab that was clicked now holds focus. Hand it back to the grid,
      // or the first thing you do on the new sheet does nothing.
      requestAnimationFrame(focusGrid);
    },
    [activeSheetId, sel, setSel, leaveSheet, focusGrid]
  );

  const handleAddSheet = useCallback(() => {
    const id = workbook.addSheet(activeSheetId ?? undefined);
    if (!id) {
      toast.info(t("files:spreadsheet.sheets.maxReached"));
      return;
    }
    commitEdit();
    setRequestedSheetId(id);
    setSel(ORIGIN_SELECTION);
  }, [workbook, activeSheetId, commitEdit, setSel, t]);

  const handleDuplicateSheet = useCallback(
    (id: SheetId) => {
      const copyId = workbook.duplicateSheet(id);
      if (!copyId) {
        toast.info(t("files:spreadsheet.sheets.maxReached"));
        return;
      }
      setRequestedSheetId(copyId);
    },
    [workbook, t]
  );

  const handleSetSheetHidden = useCallback(
    (id: SheetId, hidden: boolean) => {
      // Hiding the sheet being edited would leave the draft with nowhere
      // visible to land, so the edit is committed first.
      if (hidden && editing?.sheetId === id) commitEdit();
      if (!workbook.setSheetHidden(id, hidden)) {
        toast.info(t("files:spreadsheet.sheets.hideLastBlocked"));
        return;
      }
      // Reveal lands you on the sheet you just brought back; hide leaves
      // the active-sheet fallback to pick the next visible one.
      if (!hidden) setRequestedSheetId(id);
    },
    [workbook, editing, commitEdit, t]
  );

  // Import: the host reads the file, this writes what comes back. Every sheet
  // lands in one transaction (see ``importSheets``), so a file is one thing to
  // undo however many tabs it brought.
  const importInputRef = useRef<HTMLInputElement | null>(null);
  const [importing, setImporting] = useState(false);

  const handleImportFile = useCallback(
    async (file: File) => {
      if (!onImportFile) return;
      setImporting(true);
      try {
        const incoming = await onImportFile(file);
        const { added, skipped } = workbook.importSheets(incoming);
        if (added.length === 0) {
          toast.info(t("files:spreadsheet.sheets.maxReached"));
          return;
        }
        setRequestedSheetId(added[0]);
        if (skipped > 0) {
          // Some of the file is in and some is not; saying only how much
          // arrived would read as all of it.
          toast.warning(
            t("files:spreadsheet.sheets.importedPartly", {
              count: added.length,
              skipped,
            })
          );
        } else {
          toast.success(t("files:spreadsheet.sheets.imported", { count: added.length }));
        }
      } catch (error) {
        toast.error(getErrorMessage(error, "files:spreadsheet.sheets.importFailed"));
      } finally {
        setImporting(false);
      }
    },
    [onImportFile, workbook, t]
  );

  const handleDeleteSheet = useCallback(
    (id: SheetId) => {
      // Drop an edit anchored to this sheet before it goes: its container
      // is about to disappear, so committing would write nowhere.
      if (editing?.sheetId === id) cancelEdit();
      if (!workbook.deleteSheet(id)) {
        toast.info(t("files:spreadsheet.sheets.deleteLastBlocked"));
        return;
      }
      selBySheetRef.current.delete(id);
      // Formulas elsewhere that named the sheet keep their text and start
      // reporting #REF!, so undo (or renaming a sheet back) restores them.
      toast.info(t("files:spreadsheet.sheets.deleted"));
    },
    [workbook, t, editing, cancelEdit]
  );

  const headerActions: LineHeaderActions = {
    mouseDown: (axis, index, e) => {
      if (e.button !== 0) return;
      focusGrid();
      selectingRef.current = axis === "col" ? "columns" : "rows";
      selectLine(axis, index, e.shiftKey);
    },
    mouseEnter: (axis, index) => {
      if (selectingRef.current === (axis === "col" ? "columns" : "rows"))
        selectLine(axis, index, true);
    },
    // Right-click doesn't go through mousedown, so the line the menu acts on
    // is selected here — unless it is inside a selected band of lines, which
    // the menu then acts on whole.
    contextMenu: (axis, index) => {
      focusGrid();
      const band = sel.mode === (axis === "col" ? "columns" : "rows");
      if (!(band && headerActive(axis, index))) selectLine(axis, index);
    },
    startResize,
    resetSize,
    insert: insertLines,
    delete: deleteLines,
    hide: (axis, band) => setLinesHidden(axis, band, true),
    unhideAll,
    sort: sortColumn,
  };

  return (
    <div
      className={cn(
        "relative flex flex-col overflow-hidden rounded-lg border border-border bg-background",
        className
      )}
    >
      {yDoc !== null && !hasSynced && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-background/80">
          <div className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span>{t("files:spreadsheet.syncing")}</span>
          </div>
        </div>
      )}
      {/* Toolbar buttons must not take focus: the grid owns the keyboard,
          and clipboard events only reach a focused element. Inputs and the
          labels wrapping them keep their default click behaviour. */}
      {/* biome-ignore lint/a11y/noStaticElementInteractions: mousedown only suppresses focus theft; every control inside keeps its own semantics */}
      <div
        className="flex min-w-0 shrink-0 items-center gap-2 overflow-hidden border-border border-b bg-muted/20 px-3 py-2"
        onMouseDown={(e) => {
          const target = e.target as HTMLElement | null;
          if (target?.closest("input,label,textarea,[contenteditable]")) return;
          e.preventDefault();
        }}
      >
        <SpreadsheetToolbar
          selection={
            {
              mode: sel.mode,
              r1: selBox.r1,
              r2: selBox.r2,
              c1: selBox.c1,
              c2: selBox.c2,
              focusRow: sel.focus.row,
              focusCol: sel.focus.col,
            } satisfies ToolbarSelection
          }
          formatting={formatting}
          readOnly={readOnly}
          onInsertFunction={insertFunction}
          onUndo={history.undo}
          onRedo={history.redo}
          canUndo={history.canUndo}
          canRedo={history.canRedo}
        />
      </div>

      <SpreadsheetFormulaBar
        selectionLabel={selectionLabel}
        onNavigate={navigateToRef}
        value={formulaBarValue}
        draft={draft}
        editing={editing !== null}
        inputRef={formulaBar.inputRef}
        onChange={formulaBar.onChange}
        onFocus={formulaBar.onFocus}
        onKeyDown={onEditorKeyDown}
        onBlur={onEditorBlur}
        readOnly={readOnly}
      />

      {find.open && (
        <SpreadsheetFindBar
          query={find.query}
          replacement={find.replacement}
          options={find.options}
          matchCount={find.matchCount}
          matchIndex={find.matchIndex}
          readOnly={readOnly}
          onQueryChange={find.setQuery}
          onReplacementChange={find.setReplacement}
          onOptionsChange={find.setOptions}
          onStep={find.step}
          onReplace={find.replaceCurrent}
          onReplaceAll={find.replaceEvery}
          onClose={closeFind}
        />
      )}

      {/* biome-ignore lint/a11y/useSemanticElements: virtualized absolute layout doesn't fit a <table>; ARIA grid roles convey semantics */}
      <div
        ref={containerRef}
        role="grid"
        tabIndex={0}
        aria-label={fileTitle}
        aria-rowcount={dimensions.rows}
        aria-colcount={dimensions.cols}
        onKeyDown={handleKeyDown}
        // An edit's input handles its own clipboard.
        onPaste={editing ? undefined : clipboard.paste}
        onCopy={editing ? undefined : clipboard.copy}
        className="relative min-h-0 flex-1 select-none overflow-auto focus:outline-none focus-visible:outline-2 focus-visible:outline-primary"
      >
        <div
          style={{
            width: ROW_HEADER_WIDTH + totalGridWidth,
            height: COL_HEADER_HEIGHT + totalGridHeight,
            position: "relative",
          }}
        >
          {/* Column-header strip — sticky top keeps letters glued while
              scrolling vertically. */}
          <div
            className="sticky top-0 z-20 bg-muted"
            style={{
              left: 0,
              height: COL_HEADER_HEIGHT,
              width: ROW_HEADER_WIDTH + totalGridWidth,
            }}
          >
            <div
              className="sticky top-0 left-0 z-30 border-border border-r border-b bg-muted"
              style={{ width: ROW_HEADER_WIDTH, height: COL_HEADER_HEIGHT }}
            />
            {visibleCols.map((col) => (
              <LineHeader
                key={`colh-${col.index}`}
                axis="col"
                index={col.index}
                start={col.start}
                size={col.size}
                active={headerActive("col", col.index)}
                readOnly={readOnly}
                band={lineBand("col", col.index)}
                canUnhide={hasHidden("col")}
                actions={headerActions}
              />
            ))}
          </div>

          {/* Frozen panes use CSS ``position: sticky`` (compositor-driven)
              instead of per-frame JS repositioning, so they no longer lag a
              render behind the scroll. Each band is a zero-size sticky
              positioning context placed in flow right after the column header
              (natural top = COL_HEADER_HEIGHT, so it pins there); an opaque
              backing rect masks the body cells scrolling underneath. Only the
              axis that should stay frozen gets a sticky inset — the other axis
              has no inset and scrolls naturally with the body. */}

          {/* Frozen rows band — pinned vertically (sticky top), scrolls
              horizontally with the body. */}
          {frozenRows > 0 && (
            <div
              className="sticky"
              style={{ top: COL_HEADER_HEIGHT, width: 0, height: 0, zIndex: 6 }}
            >
              <div
                className="absolute bg-background"
                style={{
                  left: ROW_HEADER_WIDTH,
                  top: 0,
                  width: totalGridWidth,
                  height: frozenBandHeight,
                }}
              />
              {visibleCols.map((col) =>
                col.index < frozenCols
                  ? null
                  : Array.from({ length: frozenRows }, (_, r) =>
                      isRowHidden(r)
                        ? null
                        : renderCell(r, col.index, ROW_HEADER_WIDTH + col.start, prefixRow[r])
                    )
              )}
            </div>
          )}

          {/* Frozen cols band — pinned horizontally (sticky left), scrolls
              vertically with the body. */}
          {frozenCols > 0 && (
            <div
              className="sticky"
              style={{ left: ROW_HEADER_WIDTH, width: 0, height: 0, zIndex: 5 }}
            >
              <div
                className="absolute bg-background"
                style={{ left: 0, top: 0, width: frozenBandWidth, height: totalGridHeight }}
              />
              {visibleRows.map((row) =>
                row.index < frozenRows
                  ? null
                  : Array.from({ length: frozenCols }, (_, c) =>
                      isColHidden(c) ? null : renderCell(row.index, c, prefixCol[c], row.start)
                    )
              )}
            </div>
          )}

          {/* Frozen corner — pinned on both axes. */}
          {frozenRows > 0 && frozenCols > 0 && (
            <div
              className="sticky"
              style={{
                top: COL_HEADER_HEIGHT,
                left: ROW_HEADER_WIDTH,
                width: 0,
                height: 0,
                zIndex: 7,
              }}
            >
              <div
                className="absolute bg-background"
                style={{ left: 0, top: 0, width: frozenBandWidth, height: frozenBandHeight }}
              />
              {Array.from({ length: frozenRows }, (_, r) =>
                Array.from({ length: frozenCols }, (_, c) =>
                  renderCell(r, c, prefixCol[c], prefixRow[r])
                )
              )}
            </div>
          )}

          {/* Row-header strip — sticky left keeps numbers glued while
              scrolling horizontally. */}
          <div
            className="sticky left-0 z-10 bg-muted"
            style={{ width: ROW_HEADER_WIDTH, height: totalGridHeight }}
          >
            {visibleRows.map((row) => (
              <LineHeader
                key={`rowh-${row.index}`}
                axis="row"
                index={row.index}
                start={row.start}
                size={row.size}
                active={headerActive("row", row.index)}
                readOnly={readOnly}
                band={lineBand("row", row.index)}
                canUnhide={hasHidden("row")}
                actions={headerActions}
              />
            ))}
          </div>

          {/* Body cells (excludes anything covered by a frozen band). */}
          {visibleRows.map((row) =>
            visibleCols.map((col) => {
              if (row.index < frozenRows || col.index < frozenCols) return null;
              return renderCell(
                row.index,
                col.index,
                ROW_HEADER_WIDTH + col.start,
                COL_HEADER_HEIGHT + row.start
              );
            })
          )}
        </div>
      </div>

      <SpreadsheetSheetTabs
        sheets={sheets}
        activeSheetId={activeSheetId}
        readOnly={readOnly}
        canAdd={sheets.length < MAX_SHEETS}
        onSelect={selectSheet}
        onAdd={handleAddSheet}
        onImport={onImportFile && !importing ? () => importInputRef.current?.click() : undefined}
        onRename={workbook.renameSheet}
        onDelete={handleDeleteSheet}
        onDuplicate={handleDuplicateSheet}
        onMove={workbook.moveSheet}
        onSetHidden={handleSetSheetHidden}
      />
      {onImportFile && (
        <input
          ref={importInputRef}
          type="file"
          accept=".csv,.tsv,.xlsx,.xlsm"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            // Cleared so choosing the same file twice fires again.
            e.target.value = "";
            if (file) void handleImportFile(file);
          }}
        />
      )}
    </div>
  );
};
