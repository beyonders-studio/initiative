import {
  type CSSProperties,
  type FocusEvent,
  type KeyboardEvent,
  type MouseEvent,
  memo,
  type Ref,
  useMemo,
} from "react";

import { type DraftStore, useDraft } from "@/components/tools/files/spreadsheet/draftStore";
import { FormulaCellInput } from "@/components/tools/files/spreadsheet/FormulaCellInput";
import type { RefHighlight } from "@/components/tools/files/spreadsheet/useSpreadsheetEditing";
import type { FormulaRefToken } from "@/lib/spreadsheet/formula-refs";
import { Checkbox } from "@/ui/checkbox";
import { cn } from "@/ui/lib/utils";

/** A cell's event handlers, keyed by the cell they fire on. */
export interface CellHandlers {
  mouseDown: (row: number, col: number, e: MouseEvent) => void;
  mouseEnter: (row: number, col: number, e: MouseEvent) => void;
  doubleClick: (row: number, col: number) => void;
  toggleBoolean: (row: number, col: number) => void;
  draftChange: (draft: string) => void;
  editingKeyDown: (e: KeyboardEvent<HTMLInputElement>) => void;
  editingBlur: (e: FocusEvent<HTMLInputElement>) => void;
  editingFocus: () => void;
  fillHandleMouseDown: () => void;
  fillHandleDoubleClick: () => void;
}

interface CellViewProps {
  row: number;
  col: number;
  left: number;
  top: number;
  width: number;
  height: number;
  /** Resolved style/format CSS (background, color, weight, align). */
  cellCss: CSSProperties;
  /** The focus cell — strong ring, the keyboard/edit target. */
  isActive: boolean;
  /** Inside the current selection (but not the focus cell). */
  inSelection: boolean;
  /** Inside the pending-cut source — draws a dashed "move" marquee. */
  inCut: boolean;
  /** Inside the live fill-handle drag extent — draws a preview tint. */
  inFillPreview: boolean;
  /** This is the selection's bottom-right corner — renders the fill nub. */
  showFillHandle: boolean;
  display: string;
  /** Tooltip text — used to surface a formula error token (e.g. #DIV/0!). */
  title?: string;
  booleanValue: boolean | null;
  readOnly: boolean;
  /** Set on the cell being edited only: the input draws the draft. */
  editor: {
    draft: DraftStore;
    inputRef: Ref<HTMLInputElement>;
    /** Which of the draft's references to color: the ones outlined on the
     *  sheet on screen. */
    isRefOnScreen: (token: FormulaRefToken) => boolean;
  } | null;
  /** Colors this cell as a referenced cell of the formula being edited. */
  refHighlight: RefHighlight | null;
  peerColor: string | null;
  peerName: string | null;
  /** Stable for the editor's lifetime, so it never defeats the memo. */
  handlers: CellHandlers;
}

/** The props the parent rebuilds each render, compared by their entries. */
const SHALLOW_CELL_PROPS = new Set<string>(["cellCss", "refHighlight", "editor"]);

const shallowEqual = (a: object | null, b: object | null): boolean => {
  if (a === b) return true;
  if (!a || !b) return false;
  const aKeys = Object.keys(a);
  if (aKeys.length !== Object.keys(b).length) return false;
  return aKeys.every((k) => Object.is(a[k as keyof typeof a], b[k as keyof typeof b]));
};

const cellViewPropsEqual = (prev: CellViewProps, next: CellViewProps): boolean =>
  (Object.keys(next) as (keyof CellViewProps)[]).every((k) =>
    SHALLOW_CELL_PROPS.has(k)
      ? shallowEqual(prev[k] as object | null, next[k] as object | null)
      : Object.is(prev[k], next[k])
  );

/** The input on the cell being edited. The only part of the cell that
 *  re-renders as the draft changes. */
const EditingCellInput = ({
  editor,
  handlers,
}: {
  editor: NonNullable<CellViewProps["editor"]>;
  handlers: CellHandlers;
}) => {
  const { value, tokens } = useDraft(editor.draft);
  const { isRefOnScreen } = editor;
  const shown = useMemo(() => tokens.filter(isRefOnScreen), [tokens, isRefOnScreen]);
  return (
    <FormulaCellInput
      inputRef={editor.inputRef}
      value={value}
      tokens={shown}
      onChange={handlers.draftChange}
      onKeyDown={handlers.editingKeyDown}
      onBlur={handlers.editingBlur}
      onFocus={handlers.editingFocus}
    />
  );
};

export const CellView = memo(function CellView({
  row,
  col,
  left,
  top,
  width,
  height,
  cellCss,
  isActive,
  inSelection,
  inCut,
  inFillPreview,
  showFillHandle,
  display,
  title,
  booleanValue,
  readOnly,
  editor,
  refHighlight,
  peerColor,
  peerName,
  handlers,
}: CellViewProps) {
  const isEditing = editor !== null;
  const baseClass = useMemo(
    () =>
      cn(
        "absolute box-border border-border border-r border-b text-sm",
        (isActive || isEditing) && "z-[1] ring-2 ring-primary ring-inset"
      ),
    [isActive, isEditing]
  );
  // Fill must sit *under* the value/ring; positioning + fill on the
  // container, text styling inherited by the value span.
  const containerStyle = useMemo<CSSProperties>(
    () => ({ position: "absolute", left, top, width, height, ...cellCss }),
    [left, top, width, height, cellCss]
  );
  const onMouseDown = (e: MouseEvent) => handlers.mouseDown(row, col, e);
  const onMouseEnter = (e: MouseEvent) => handlers.mouseEnter(row, col, e);
  const onDoubleClick = () => handlers.doubleClick(row, col);

  const peerOverlay =
    peerColor && peerName ? (
      <div
        className="pointer-events-none absolute inset-0 z-[2]"
        style={{ boxShadow: `inset 0 0 0 2px ${peerColor}` }}
      >
        <div
          className="absolute -top-4 right-0 max-w-full truncate rounded-t px-1.5 py-0.5 font-medium text-3xs text-slate-900 shadow-sm"
          style={{ backgroundColor: peerColor }}
        >
          {peerName}
        </div>
      </div>
    ) : null;

  // Translucent tint for non-focus cells in the selection so the user
  // fill underneath still reads through.
  const selectionOverlay =
    inSelection && !isActive ? (
      <div className="pointer-events-none absolute inset-0 bg-primary/15" />
    ) : null;

  // Dashed "move" marquee on a cell awaiting a cut-paste.
  const cutOverlay = inCut ? (
    <div className="pointer-events-none absolute inset-0 z-[1] border-2 border-primary border-dashed" />
  ) : null;

  // Tint over the new region a fill drag will write (the source already
  // reads through the selection tint, so only paint cells outside it).
  const fillPreviewOverlay =
    inFillPreview && !inSelection && !isActive ? (
      <div className="pointer-events-none absolute inset-0 bg-primary/10" />
    ) : null;

  // Colored outline marking this cell as a reference of the formula being
  // edited. Borders only on the box-boundary edges so a range reads as one
  // rectangle rather than a grid of boxes.
  const refOverlay = refHighlight ? (
    <div
      className="pointer-events-none absolute inset-0 z-[2]"
      style={{
        borderColor: refHighlight.color,
        borderStyle: "solid",
        borderTopWidth: refHighlight.top ? 2 : 0,
        borderBottomWidth: refHighlight.bottom ? 2 : 0,
        borderLeftWidth: refHighlight.left ? 2 : 0,
        borderRightWidth: refHighlight.right ? 2 : 0,
      }}
    />
  ) : null;

  // The draggable fill handle on the selection's bottom-right corner. Its
  // own mousedown starts the fill (stopping selection); double-click
  // auto-fills down. Centered on the corner, above the ring/overlays.
  const fillHandle = showFillHandle ? (
    // biome-ignore lint/a11y/noStaticElementInteractions: pointer-only affordance; grid keyboard model owns navigation
    <div
      className="absolute right-0 bottom-0 z-[3] h-[7px] w-[7px] translate-x-1/2 translate-y-1/2 cursor-crosshair rounded-[1px] border border-background bg-primary"
      onMouseDown={(e) => {
        e.stopPropagation();
        e.preventDefault();
        handlers.fillHandleMouseDown();
      }}
      onDoubleClick={(e) => {
        e.stopPropagation();
        handlers.fillHandleDoubleClick();
      }}
    />
  ) : null;

  if (editor) {
    return (
      <div className={baseClass} style={containerStyle}>
        <EditingCellInput editor={editor} handlers={handlers} />
        {peerOverlay}
      </div>
    );
  }

  if (booleanValue !== null) {
    return (
      // biome-ignore lint/a11y/noStaticElementInteractions: cell is part of a role="grid" widget; keyboard/selection is owned by the container
      <div
        className={cn(baseClass, "flex cursor-cell items-center px-1.5")}
        style={containerStyle}
        onMouseDown={onMouseDown}
        onMouseEnter={onMouseEnter}
        onDoubleClick={onDoubleClick}
      >
        <Checkbox
          checked={booleanValue}
          disabled={readOnly}
          onClick={(e) => {
            e.stopPropagation();
            handlers.toggleBoolean(row, col);
          }}
          aria-label={booleanValue ? "true" : "false"}
        />
        {selectionOverlay}
        {fillPreviewOverlay}
        {refOverlay}
        {cutOverlay}
        {peerOverlay}
        {fillHandle}
      </div>
    );
  }

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: cell is part of a role="grid" widget; keyboard/selection is owned by the container
    <div
      className={cn(baseClass, "flex cursor-cell items-center px-1.5")}
      style={containerStyle}
      title={title}
      onMouseDown={onMouseDown}
      onMouseEnter={onMouseEnter}
      onDoubleClick={onDoubleClick}
    >
      <span className="w-full truncate">{display}</span>
      {selectionOverlay}
      {fillPreviewOverlay}
      {refOverlay}
      {cutOverlay}
      {peerOverlay}
      {fillHandle}
    </div>
  );
}, cellViewPropsEqual);
