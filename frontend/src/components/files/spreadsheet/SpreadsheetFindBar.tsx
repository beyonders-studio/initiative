import { ChevronDown, ChevronUp, X } from "lucide-react";
import { type KeyboardEvent, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import type { FindOptions } from "@/lib/spreadsheet/find";
import { Button } from "@/ui/button";
import { Checkbox } from "@/ui/checkbox";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";

interface SpreadsheetFindBarProps {
  query: string;
  replacement: string;
  options: FindOptions;
  /** How many cells match, and which one the cursor is on (1-based, 0 when
   *  the cursor isn't on a match). */
  matchCount: number;
  matchIndex: number;
  readOnly: boolean;
  onQueryChange: (value: string) => void;
  onReplacementChange: (value: string) => void;
  onOptionsChange: (next: FindOptions) => void;
  onStep: (delta: 1 | -1) => void;
  onReplace: () => void;
  onReplaceAll: () => void;
  onClose: () => void;
}

/**
 * The find-and-replace strip, pinned under the formula bar.
 *
 * Deliberately not a dialog: the point of a find is watching the grid move
 * underneath it, which a modal would cover and a modal's focus trap would
 * fight. Enter steps to the next match and Escape closes, so the whole
 * thing is usable without the mouse leaving the query field.
 */
export const SpreadsheetFindBar = ({
  query,
  replacement,
  options,
  matchCount,
  matchIndex,
  readOnly,
  onQueryChange,
  onReplacementChange,
  onOptionsChange,
  onStep,
  onReplace,
  onReplaceAll,
  onClose,
}: SpreadsheetFindBarProps) => {
  const { t } = useTranslation(["files", "common"]);
  const queryRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    queryRef.current?.focus();
    queryRef.current?.select();
  }, []);

  const handleKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      onStep(e.shiftKey ? -1 : 1);
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  };

  const status =
    query === ""
      ? ""
      : matchCount === 0
        ? t("files:spreadsheet.find.noMatches")
        : t("files:spreadsheet.find.position", { index: matchIndex, count: matchCount });

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: Enter/Escape shortcuts for the inputs inside, which carry their own semantics
    <div
      className="flex shrink-0 flex-wrap items-center gap-2 border-border border-b bg-muted/20 px-3 py-2"
      onKeyDown={handleKeyDown}
    >
      <Input
        ref={queryRef}
        value={query}
        onChange={(e) => onQueryChange(e.target.value)}
        placeholder={t("files:spreadsheet.find.searchPlaceholder")}
        aria-label={t("files:spreadsheet.find.searchPlaceholder")}
        className="h-8 w-44"
      />
      <span className="min-w-24 text-muted-foreground text-xs" aria-live="polite">
        {status}
      </span>
      <Button
        type="button"
        size="icon-sm"
        variant="ghost"
        onClick={() => onStep(-1)}
        disabled={matchCount === 0}
        aria-label={t("files:spreadsheet.find.previous")}
        title={t("files:spreadsheet.find.previous")}
      >
        <ChevronUp className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        size="icon-sm"
        variant="ghost"
        onClick={() => onStep(1)}
        disabled={matchCount === 0}
        aria-label={t("files:spreadsheet.find.next")}
        title={t("files:spreadsheet.find.next")}
      >
        <ChevronDown className="h-4 w-4" />
      </Button>

      {!readOnly && (
        <>
          <Input
            value={replacement}
            onChange={(e) => onReplacementChange(e.target.value)}
            placeholder={t("files:spreadsheet.find.replacePlaceholder")}
            aria-label={t("files:spreadsheet.find.replacePlaceholder")}
            className="h-8 w-44"
          />
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={onReplace}
            disabled={matchCount === 0}
          >
            {t("files:spreadsheet.find.replace")}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={onReplaceAll}
            disabled={matchCount === 0}
          >
            {t("files:spreadsheet.find.replaceAll")}
          </Button>
        </>
      )}

      <Label className="flex items-center gap-1.5 text-xs">
        <Checkbox
          checked={options.matchCase}
          onCheckedChange={(v) => onOptionsChange({ ...options, matchCase: v === true })}
        />
        {t("files:spreadsheet.find.matchCase")}
      </Label>
      <Label className="flex items-center gap-1.5 text-xs">
        <Checkbox
          checked={options.wholeCell}
          onCheckedChange={(v) => onOptionsChange({ ...options, wholeCell: v === true })}
        />
        {t("files:spreadsheet.find.wholeCell")}
      </Label>

      <Button
        type="button"
        size="icon-sm"
        variant="ghost"
        className="ml-auto"
        onClick={onClose}
        aria-label={t("common:close")}
        title={t("common:close")}
      >
        <X className="h-4 w-4" />
      </Button>
    </div>
  );
};
