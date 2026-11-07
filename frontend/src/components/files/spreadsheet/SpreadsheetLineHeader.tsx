import type { MouseEvent, PointerEvent, ReactNode } from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { LineBand } from "@/components/files/spreadsheet/useSpreadsheetStructure";
import { colIndexToLetter } from "@/lib/spreadsheet/coords";
import type { SortDirection } from "@/lib/spreadsheet/sort";
import type { LineAxis } from "@/lib/spreadsheet/transform";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuSub,
  ContextMenuSubContent,
  ContextMenuSubTrigger,
  ContextMenuTrigger,
} from "@/ui/context-menu";
import { cn } from "@/ui/lib/utils";

export const ROW_HEADER_WIDTH = 56;
export const COL_HEADER_HEIGHT = 26;
const RESIZE_HANDLE = 5;

/** What a header does, for either axis. */
export interface LineHeaderActions {
  mouseDown: (axis: LineAxis, index: number, e: MouseEvent) => void;
  mouseEnter: (axis: LineAxis, index: number) => void;
  contextMenu: (axis: LineAxis, index: number) => void;
  startResize: (axis: LineAxis, index: number, e: PointerEvent) => void;
  resetSize: (axis: LineAxis, index: number) => void;
  insert: (axis: LineAxis, band: LineBand, count: number, after: boolean) => void;
  delete: (axis: LineAxis, band: LineBand) => void;
  hide: (axis: LineAxis, band: LineBand) => void;
  unhideAll: (axis: LineAxis) => void;
  sort: (col: number, direction: SortDirection) => void;
}

interface LineHeaderProps {
  axis: LineAxis;
  index: number;
  /** Where the line starts along its axis, and how long it is. */
  start: number;
  size: number;
  active: boolean;
  readOnly: boolean;
  /** The lines the menu acts on: the selected band when it covers this
   *  header, otherwise just this line. */
  band: LineBand;
  /** Whether any line on this axis is hidden, to offer revealing them. */
  canUnhide: boolean;
  actions: LineHeaderActions;
}

/** A column letter or row number: selects the line, resizes it from its
 *  far edge, and opens the line menu on right-click. */
export const LineHeader = ({
  axis,
  index,
  start,
  size,
  active,
  readOnly,
  band,
  canUnhide,
  actions,
}: LineHeaderProps) => {
  const isCol = axis === "col";
  const header = (
    <button
      type="button"
      onMouseDown={(e) => actions.mouseDown(axis, index, e)}
      onContextMenu={() => actions.contextMenu(axis, index)}
      onMouseEnter={() => actions.mouseEnter(axis, index)}
      className={cn(
        "absolute flex cursor-pointer items-center justify-center border-border border-r border-b font-mono text-xs",
        active ? "bg-primary/20 text-foreground" : "bg-muted text-muted-foreground"
      )}
      style={
        isCol
          ? { left: ROW_HEADER_WIDTH + start, top: 0, width: size, height: COL_HEADER_HEIGHT }
          : { left: 0, top: start, width: ROW_HEADER_WIDTH, height: size }
      }
    >
      {isCol ? colIndexToLetter(index) : index + 1}
      {!readOnly && (
        <div
          onMouseDown={(e) => e.stopPropagation()}
          onPointerDown={(e) => actions.startResize(axis, index, e)}
          onDoubleClick={(e) => {
            e.stopPropagation();
            actions.resetSize(axis, index);
          }}
          className={cn(
            "absolute z-10 hover:bg-primary/40",
            isCol
              ? "top-0 right-0 h-full cursor-col-resize"
              : "bottom-0 left-0 w-full cursor-row-resize"
          )}
          style={isCol ? { width: RESIZE_HANDLE } : { height: RESIZE_HANDLE }}
          aria-hidden
        />
      )}
    </button>
  );
  if (readOnly) return header;
  return (
    <HeaderContextMenu
      axis={axis}
      band={band}
      onInsert={(count, after) => actions.insert(axis, band, count, after)}
      onDelete={() => actions.delete(axis, band)}
      onSort={isCol ? (direction) => actions.sort(index, direction) : undefined}
      onHide={() => actions.hide(axis, band)}
      onUnhideAll={canUnhide ? () => actions.unhideAll(axis) : undefined}
    >
      {header}
    </HeaderContextMenu>
  );
};

/** Largest N the "insert multiple" stepper accepts; the transform also
 *  clamps to the remaining grid capacity, this just keeps the input sane. */
const MAX_INSERT_N = 1_000;
/** Stepper default — reset on every menu open so a value typed for one
 *  header never bleeds into another (the menus are keyed by index, so React
 *  reuses an instance across different rows/cols after an insert/delete). */
const DEFAULT_INSERT_N = 2;

interface HeaderContextMenuProps {
  axis: LineAxis;
  /** The contiguous band the menu acts on: the active multi-selection
   *  when it covers this header, otherwise just the clicked line. */
  band: LineBand;
  onInsert: (count: number, after: boolean) => void;
  onDelete: () => void;
  /** Columns only — sort the whole sheet by this column. */
  onSort?: (direction: SortDirection) => void;
  onHide: () => void;
  /** Reveal every hidden line on this axis. Absent when none are hidden. */
  onUnhideAll?: () => void;
  /** The header button that triggers the menu. */
  children: ReactNode;
}

/** Right-click menu shared by the row and column headers: insert one
 *  line either side, insert N via a stepper submenu, or delete the
 *  selected band. Column headers additionally get the sort actions. */
const HeaderContextMenu = ({
  axis,
  band,
  onInsert,
  onDelete,
  onSort,
  onHide,
  onUnhideAll,
  children,
}: HeaderContextMenuProps) => {
  const { t } = useTranslation(["files", "common"]);
  const [n, setN] = useState(DEFAULT_INSERT_N);
  const isRow = axis === "row";
  const before = isRow ? "insertRowAbove" : "insertColumnLeft";
  const after = isRow ? "insertRowBelow" : "insertColumnRight";
  const beforeN = isRow ? "insertRowsAboveN" : "insertColumnsLeftN";
  const afterN = isRow ? "insertRowsBelowN" : "insertColumnsRightN";

  return (
    <ContextMenu onOpenChange={(open) => open && setN(DEFAULT_INSERT_N)}>
      <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem onSelect={() => onInsert(1, false)}>
          {t(`files:spreadsheet.${before}`)}
        </ContextMenuItem>
        <ContextMenuItem onSelect={() => onInsert(1, true)}>
          {t(`files:spreadsheet.${after}`)}
        </ContextMenuItem>
        <ContextMenuSub>
          <ContextMenuSubTrigger>{t("files:spreadsheet.insertMultiple")}</ContextMenuSubTrigger>
          <ContextMenuSubContent>
            <div className="flex items-center gap-2 px-2 py-1.5">
              <span className="text-muted-foreground text-xs">
                {t("files:spreadsheet.insertCount")}
              </span>
              <input
                type="number"
                min={1}
                max={MAX_INSERT_N}
                value={n}
                // biome-ignore lint/a11y/noAutofocus: focuses the stepper when the submenu opens so the user can type N immediately
                autoFocus
                // Keep keystrokes in the input — otherwise the menu's
                // typeahead steals them and jumps focus to an item.
                onKeyDown={(e) => e.stopPropagation()}
                onFocus={(e) => e.currentTarget.select()}
                onChange={(e) => {
                  const next = Number.parseInt(e.target.value, 10);
                  setN(Number.isFinite(next) ? Math.max(1, Math.min(next, MAX_INSERT_N)) : 1);
                }}
                className="w-16 rounded border border-border bg-background px-1.5 py-0.5 text-sm outline-none focus:border-primary"
              />
            </div>
            <ContextMenuItem onSelect={() => onInsert(n, false)}>
              {t(`files:spreadsheet.${beforeN}`, { count: n })}
            </ContextMenuItem>
            <ContextMenuItem onSelect={() => onInsert(n, true)}>
              {t(`files:spreadsheet.${afterN}`, { count: n })}
            </ContextMenuItem>
          </ContextMenuSubContent>
        </ContextMenuSub>
        <ContextMenuSeparator />
        <ContextMenuItem onSelect={onHide}>
          {t(isRow ? "files:spreadsheet.hideRows" : "files:spreadsheet.hideColumns", {
            count: band.count,
          })}
        </ContextMenuItem>
        {onUnhideAll && (
          <ContextMenuItem onSelect={onUnhideAll}>
            {t(isRow ? "files:spreadsheet.unhideRows" : "files:spreadsheet.unhideColumns")}
          </ContextMenuItem>
        )}
        <ContextMenuSeparator />
        <ContextMenuItem onSelect={onDelete} className="text-destructive focus:text-destructive">
          {t(isRow ? "files:spreadsheet.deleteRows" : "files:spreadsheet.deleteColumns", {
            count: band.count,
          })}
        </ContextMenuItem>
        {onSort && (
          <>
            <ContextMenuSeparator />
            <ContextMenuItem onSelect={() => onSort("asc")}>
              {t("files:spreadsheet.sortAscending")}
            </ContextMenuItem>
            <ContextMenuItem onSelect={() => onSort("desc")}>
              {t("files:spreadsheet.sortDescending")}
            </ContextMenuItem>
          </>
        )}
      </ContextMenuContent>
    </ContextMenu>
  );
};
