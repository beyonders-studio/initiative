import { ChevronDown, EyeOff, Plus, Upload } from "lucide-react";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  MAX_SHEET_NAME_LENGTH,
  type SheetId,
  type SheetMeta,
  visibleSheets,
} from "@/lib/spreadsheet/sheets";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";
import { cn } from "@/ui/lib/utils";

interface SpreadsheetSheetTabsProps {
  sheets: SheetMeta[];
  activeSheetId: SheetId | null;
  readOnly: boolean;
  /** False once the workbook is at its sheet cap — the add button stays
   *  visible but inert so the ceiling is discoverable. */
  canAdd: boolean;
  onSelect: (id: SheetId) => void;
  onAdd: () => void;
  /** Absent when the surface cannot import (read-only, or a host that has
   *  not wired a file source). */
  onImport?: () => void;
  onRename: (id: SheetId, name: string) => void;
  onDelete: (id: SheetId) => void;
  onDuplicate: (id: SheetId) => void;
  onMove: (id: SheetId, delta: number) => void;
  onSetHidden: (id: SheetId, hidden: boolean) => void;
}

/**
 * The strip of sheet tabs along the bottom of the grid.
 *
 * Every action reachable by right-click is also on a per-tab dropdown, so
 * the whole feature works on a touch screen where there is no right-click:
 * tap to switch, tap the chevron on the active tab for the menu, and
 * double-tap (or "Rename" from that menu) to edit the name in place.
 * Reordering is a menu action rather than a drag for the same reason.
 */
export const SpreadsheetSheetTabs = ({
  sheets,
  activeSheetId,
  readOnly,
  canAdd,
  onSelect,
  onAdd,
  onImport,
  onRename,
  onDelete,
  onDuplicate,
  onMove,
  onSetHidden,
}: SpreadsheetSheetTabsProps) => {
  const { t } = useTranslation(["files", "common"]);
  // The sheet being renamed and its draft are separate pieces of state on
  // purpose: the effect below selects the input's text, and it must run
  // when the rename *starts*, not on every keystroke — a combined
  // ``{ id, draft }`` object changes identity on each character typed,
  // which re-selected the whole name and made the next keystroke replace
  // everything the user had typed so far.
  const [renamingId, setRenamingId] = useState<SheetId | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const renameInputRef = useRef<HTMLInputElement>(null);
  const activeTabRef = useRef<HTMLDivElement>(null);

  const shown = visibleSheets(sheets);
  const hidden = sheets.filter((sheet) => sheet.hidden);

  const startRename = (sheet: SheetMeta) => {
    setRenamingId(sheet.id);
    setRenameDraft(sheet.name);
  };

  useEffect(() => {
    if (renamingId) renameInputRef.current?.select();
  }, [renamingId]);

  // Keep the active tab on screen when it changes from elsewhere — a
  // committed cross-sheet formula switches back to the sheet it lives on,
  // which may be scrolled out of the strip.
  useEffect(() => {
    activeTabRef.current?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [activeSheetId]);

  const commitRename = () => {
    if (!renamingId) return;
    const trimmed = renameDraft.trim();
    if (trimmed) onRename(renamingId, trimmed);
    setRenamingId(null);
  };

  const handleRenameKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      commitRename();
    } else if (e.key === "Escape") {
      e.preventDefault();
      setRenamingId(null);
    }
  };

  return (
    <div
      className="flex shrink-0 items-center gap-1 overflow-x-auto border-border border-t bg-muted/20 px-2 py-1"
      role="tablist"
      aria-label={t("files:spreadsheet.sheets.tablist")}
    >
      {!readOnly && (
        <button
          type="button"
          onClick={onAdd}
          disabled={!canAdd}
          title={
            canAdd ? t("files:spreadsheet.sheets.add") : t("files:spreadsheet.sheets.maxReached")
          }
          aria-label={t("files:spreadsheet.sheets.add")}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
        >
          <Plus className="h-4 w-4" />
        </button>
      )}

      {!readOnly && onImport && (
        <button
          type="button"
          onClick={onImport}
          disabled={!canAdd}
          title={
            canAdd ? t("files:spreadsheet.sheets.import") : t("files:spreadsheet.sheets.maxReached")
          }
          aria-label={t("files:spreadsheet.sheets.import")}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
        >
          <Upload className="h-4 w-4" />
        </button>
      )}

      {shown.map((sheet, index) => {
        const isActive = sheet.id === activeSheetId;
        const isRenaming = renamingId === sheet.id;
        return (
          <div
            key={sheet.id}
            ref={isActive ? activeTabRef : null}
            className={cn(
              "flex shrink-0 items-center rounded-t border-border border-x border-t",
              isActive ? "bg-background font-medium text-foreground" : "bg-muted/40"
            )}
          >
            {isRenaming ? (
              <input
                ref={renameInputRef}
                value={renameDraft}
                maxLength={MAX_SHEET_NAME_LENGTH}
                // biome-ignore lint/a11y/noAutofocus: the input replaces the tab the user just chose to rename
                autoFocus
                aria-label={t("files:spreadsheet.sheets.renameLabel")}
                onChange={(e) => setRenameDraft(e.target.value)}
                onKeyDown={handleRenameKeyDown}
                onBlur={commitRename}
                className="w-28 bg-transparent px-2 py-1 text-sm outline-none ring-1 ring-primary ring-inset"
              />
            ) : (
              <button
                type="button"
                role="tab"
                aria-selected={isActive}
                onClick={() => onSelect(sheet.id)}
                onDoubleClick={() => {
                  if (!readOnly) startRename(sheet);
                }}
                className="max-w-48 truncate px-3 py-1 text-sm"
              >
                {sheet.name}
              </button>
            )}

            {!readOnly && !isRenaming && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    aria-label={t("files:spreadsheet.sheets.menu", { name: sheet.name })}
                    className="flex h-7 w-5 items-center justify-center text-muted-foreground hover:text-foreground"
                  >
                    <ChevronDown className="h-3.5 w-3.5" />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start">
                  <DropdownMenuItem onSelect={() => startRename(sheet)}>
                    {t("files:spreadsheet.sheets.rename")}
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => onDuplicate(sheet.id)}>
                    {t("files:spreadsheet.sheets.duplicate")}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem disabled={index === 0} onSelect={() => onMove(sheet.id, -1)}>
                    {t("files:spreadsheet.sheets.moveLeft")}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    disabled={index === shown.length - 1}
                    onSelect={() => onMove(sheet.id, 1)}
                  >
                    {t("files:spreadsheet.sheets.moveRight")}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    disabled={shown.length <= 1}
                    onSelect={() => onSetHidden(sheet.id, true)}
                  >
                    {t("files:spreadsheet.sheets.hide")}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    disabled={sheets.length <= 1}
                    onSelect={() => onDelete(sheet.id)}
                    className="text-destructive focus:text-destructive"
                  >
                    {t("files:spreadsheet.sheets.delete")}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
        );
      })}

      {!readOnly && hidden.length > 0 && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              title={t("files:spreadsheet.sheets.hiddenCount", { count: hidden.length })}
              aria-label={t("files:spreadsheet.sheets.hiddenCount", { count: hidden.length })}
              className="flex h-7 shrink-0 items-center gap-1 rounded px-2 text-muted-foreground text-xs hover:bg-muted hover:text-foreground"
            >
              <EyeOff className="h-3.5 w-3.5" />
              {hidden.length}
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            {hidden.map((sheet) => (
              <DropdownMenuItem key={sheet.id} onSelect={() => onSetHidden(sheet.id, false)}>
                {t("files:spreadsheet.sheets.unhideNamed", { name: sheet.name })}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  );
};
