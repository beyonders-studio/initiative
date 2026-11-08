import {
  AlignCenter,
  AlignLeft,
  AlignRight,
  AlignVerticalJustifyCenter,
  AlignVerticalJustifyEnd,
  AlignVerticalJustifyStart,
  ArrowDownToLine,
  ArrowLeftToLine,
  ArrowRightToLine,
  ArrowUpToLine,
  Baseline,
  Bold,
  Eraser,
  Grid2x2,
  Hash,
  Italic,
  PaintBucket,
  Palette,
  Redo2,
  Sigma,
  Snowflake,
  Square,
  SquareDashed,
  SquareDashedTopSolid,
  Strikethrough,
  Type,
  Underline,
  Undo2,
} from "lucide-react";
import { Fragment, type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import { HISTORY_SHORTCUT } from "@/hooks/useYjsHistory";
import type {
  BorderLineStyle,
  CellAlign,
  CellBorder,
  CellStyle,
  CellVAlign,
  NegativeStyle,
  NumberFormat,
} from "@/lib/spreadsheet/styles";
import { Button } from "@/ui/button";
import { ColorPickerPopover } from "@/ui/color-picker-popover";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";
import { cn } from "@/ui/lib/utils";
import {
  OverflowMenuItem,
  OverflowSubmenu,
  OverflowToolbar,
  type OverflowToolbarItem,
} from "@/ui/overflow-toolbar";
import { Popover, PopoverContent, PopoverTrigger } from "@/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/ui/toggle-group";

import type { SpreadsheetFormattingStore } from "./useSpreadsheetFormatting";

export type SelectionMode = "range" | "columns" | "rows";

/** Normalized selection summary the toolbar acts on. ``r1..r2`` /
 *  ``c1..c2`` are inclusive bounds; ``focus`` is the active cell whose
 *  explicit formatting drives the toggle/indicator state. */
export interface ToolbarSelection {
  mode: SelectionMode;
  r1: number;
  r2: number;
  c1: number;
  c2: number;
  focusRow: number;
  focusCol: number;
}

/** Iterating a huge shift-selected range would emit one op per cell;
 *  cap per-cell style/format application so a pathological selection
 *  can't lock the tab. Column/row application is unaffected (bounded by
 *  the column/row count). */
const MAX_RANGE_CELLS = 50_000;

interface SpreadsheetToolbarProps {
  selection: ToolbarSelection;
  formatting: SpreadsheetFormattingStore;
  readOnly: boolean;
  /** Insert a formula for the named function (e.g. "SUM") into the sheet. */
  onInsertFunction: (name: string) => void;
  onUndo: () => void;
  onRedo: () => void;
  canUndo: boolean;
  canRedo: boolean;
}

const NUMBER_PRESETS: { key: string; value: NumberFormat }[] = [
  { key: "plain", value: { type: "plain" } },
  { key: "fixed", value: { type: "fixed", decimals: 2 } },
  { key: "currency", value: { type: "currency", currency: "USD", decimals: 2 } },
  { key: "percent", value: { type: "percent", decimals: 1 } },
  { key: "date", value: { type: "date", pattern: "iso" } },
];

// Module-level so their identity is stable across the toolbar's
// frequent re-renders — an inline component would remount on every
// formatting change and slam any open popover shut mid-edit.

/** One labelled popover per related group of controls, so the toolbar
 *  stays a short row instead of a long horizontal scroll. Once the row
 *  runs out of width the group sheds, and the overflow panel shows these
 *  same controls unfolded under the group's name instead. */
const GroupPopover = ({
  icon,
  label,
  disabled,
  children,
}: {
  icon: ReactNode;
  label: string;
  disabled?: boolean;
  children: ReactNode;
}) => (
  <Popover>
    <PopoverTrigger asChild>
      <Button type="button" size="sm" variant="ghost" disabled={disabled} className="h-8 gap-1.5">
        {icon}
        <span>{label}</span>
      </Button>
    </PopoverTrigger>
    <PopoverContent align="start" className="w-auto max-w-[18rem] p-3">
      {children}
    </PopoverContent>
  </Popover>
);

/** Formatting controls for the spreadsheet. Acts on the current
 *  selection: a cell range applies per-cell overrides, a column
 *  selection applies column-level formatting, a row selection
 *  row-level — so one toolbar covers every granularity with no scope
 *  picker. Toggle/indicator state reflects the focus (active) cell. */
export const SpreadsheetToolbar = ({
  selection,
  formatting,
  readOnly,
  onInsertFunction,
  onUndo,
  onRedo,
  canUndo,
  canRedo,
}: SpreadsheetToolbarProps) => {
  const { t } = useTranslation(["files", "common"]);
  const { mode, r1, r2, c1, c2, focusRow, focusCol } = selection;
  const isRows = mode === "rows";
  // Border style/color are toolbar-local choices (not stored formatting)
  // — they parameterize whatever border preset the user then picks.
  const [borderStyle, setBorderStyle] = useState<BorderLineStyle>("thin");
  const [borderColor, setBorderColor] = useState("#475569");

  // Indicator state comes from the focus cell's *explicit* formatting at
  // the selection's granularity (not the resolved cascade) so a toggle
  // reflects what this scope sets, and flips the whole selection.
  const focusStyle: CellStyle =
    (mode === "columns"
      ? formatting.columns[String(focusCol)]?.style
      : isRows
        ? formatting.rows[String(focusRow)]?.style
        : formatting.cellStyles[`${focusRow}:${focusCol}`]?.style) ?? {};
  const focusFormat: NumberFormat | undefined =
    mode === "columns"
      ? formatting.columns[String(focusCol)]?.format
      : isRows
        ? undefined
        : formatting.cellStyles[`${focusRow}:${focusCol}`]?.format;

  const applyStyle = (patch: Partial<CellStyle>) => {
    if (readOnly) return;
    formatting.batch(() => {
      if (mode === "columns") {
        for (let c = c1; c <= c2; c++) formatting.updateColumn(c, { style: patch });
      } else if (isRows) {
        for (let r = r1; r <= r2; r++) formatting.updateRow(r, { style: patch });
      } else {
        if ((r2 - r1 + 1) * (c2 - c1 + 1) > MAX_RANGE_CELLS) return;
        for (let r = r1; r <= r2; r++)
          for (let c = c1; c <= c2; c++) formatting.updateCell(r, c, { style: patch });
      }
    });
  };

  const applyFormat = (format: NumberFormat | null) => {
    if (readOnly || isRows) return;
    formatting.batch(() => {
      if (mode === "columns") {
        for (let c = c1; c <= c2; c++) formatting.updateColumn(c, { format });
      } else {
        if ((r2 - r1 + 1) * (c2 - c1 + 1) > MAX_RANGE_CELLS) return;
        for (let r = r1; r <= r2; r++)
          for (let c = c1; c <= c2; c++) formatting.updateCell(r, c, { format });
      }
    });
  };

  const clearScope = () => {
    if (readOnly) return;
    formatting.batch(() => {
      if (mode === "columns") {
        for (let c = c1; c <= c2; c++) formatting.updateColumn(c, null);
      } else if (isRows) {
        for (let r = r1; r <= r2; r++) formatting.updateRow(r, null);
      } else {
        if ((r2 - r1 + 1) * (c2 - c1 + 1) > MAX_RANGE_CELLS) return;
        for (let r = r1; r <= r2; r++)
          for (let c = c1; c <= c2; c++) formatting.updateCell(r, c, null);
      }
    });
  };

  // ``all`` / ``none`` set or clear the whole border; ``outer`` draws a
  // box (per-cell edges for a range; ``all`` for whole column/row, whose
  // perimeter is unbounded). The four single sides are *additive /
  // subtractive*: they toggle just that edge and keep the others. The
  // toggle direction is decided once from the focus cell's existing
  // border at this scope, then applied uniformly (Sheets behavior).
  const applyBorder = (preset: "all" | "outer" | "top" | "right" | "bottom" | "left" | "none") => {
    if (readOnly) return;
    const edge = { style: borderStyle, color: borderColor };
    const colBorder = (c: number) => formatting.columns[String(c)]?.style?.border;
    const rowBorder = (r: number) => formatting.rows[String(r)]?.style?.border;
    const cellBorder = (r: number, c: number) => formatting.cellStyles[`${r}:${c}`]?.style?.border;

    if (preset === "top" || preset === "right" || preset === "bottom" || preset === "left") {
      const side = preset;
      const focusBorder =
        mode === "columns"
          ? colBorder(focusCol)
          : isRows
            ? rowBorder(focusRow)
            : cellBorder(focusRow, focusCol);
      const turnOn = !focusBorder?.[side];
      const withEdge = (base: CellBorder | undefined): CellBorder | undefined => {
        const next: CellBorder = { ...(base ?? {}) };
        if (turnOn) next[side] = edge;
        else delete next[side];
        return Object.keys(next).length > 0 ? next : undefined;
      };
      formatting.batch(() => {
        if (mode === "columns") {
          for (let c = c1; c <= c2; c++)
            formatting.updateColumn(c, { style: { border: withEdge(colBorder(c)) } });
        } else if (isRows) {
          for (let r = r1; r <= r2; r++)
            formatting.updateRow(r, { style: { border: withEdge(rowBorder(r)) } });
        } else {
          if ((r2 - r1 + 1) * (c2 - c1 + 1) > MAX_RANGE_CELLS) return;
          for (let r = r1; r <= r2; r++)
            for (let c = c1; c <= c2; c++)
              formatting.updateCell(r, c, {
                style: { border: withEdge(cellBorder(r, c)) },
              });
        }
      });
      return;
    }

    const uniform = (): CellBorder | undefined =>
      preset === "none" ? undefined : { top: edge, right: edge, bottom: edge, left: edge };
    const perCell = (r: number, c: number): CellBorder | undefined => {
      if (preset !== "outer") return uniform();
      const b: CellBorder = {};
      if (r === r1) b.top = edge;
      if (r === r2) b.bottom = edge;
      if (c === c1) b.left = edge;
      if (c === c2) b.right = edge;
      return Object.keys(b).length > 0 ? b : undefined;
    };
    formatting.batch(() => {
      if (mode === "columns") {
        for (let c = c1; c <= c2; c++) formatting.updateColumn(c, { style: { border: uniform() } });
      } else if (isRows) {
        for (let r = r1; r <= r2; r++) formatting.updateRow(r, { style: { border: uniform() } });
      } else {
        if ((r2 - r1 + 1) * (c2 - c1 + 1) > MAX_RANGE_CELLS) return;
        for (let r = r1; r <= r2; r++)
          for (let c = c1; c <= c2; c++)
            formatting.updateCell(r, c, { style: { border: perCell(r, c) } });
      }
    });
  };

  const borderStyleLabel = (key: string): string => {
    switch (key) {
      case "medium":
        return t("files:spreadsheet.format.borderMedium");
      case "thick":
        return t("files:spreadsheet.format.borderThick");
      case "dashed":
        return t("files:spreadsheet.format.borderDashed");
      case "dotted":
        return t("files:spreadsheet.format.borderDotted");
      case "double":
        return t("files:spreadsheet.format.borderDouble");
      default:
        return t("files:spreadsheet.format.borderThin");
    }
  };

  const scopeStyle = focusStyle;
  const scopeFormat = focusFormat;

  // Decimal places apply to fixed/currency/percent; grouping and the
  // negative style only to fixed/currency.
  const numericFmt =
    scopeFormat &&
    (scopeFormat.type === "fixed" ||
      scopeFormat.type === "currency" ||
      scopeFormat.type === "percent")
      ? scopeFormat
      : undefined;
  const groupNegFmt =
    numericFmt && (numericFmt.type === "fixed" || numericFmt.type === "currency")
      ? numericFmt
      : undefined;
  const curDecimals = numericFmt ? numericFmt.decimals : 2;
  const curGrouping = groupNegFmt
    ? (groupNegFmt.grouping ?? groupNegFmt.type === "currency")
    : false;
  const curNegatives: string = groupNegFmt ? (groupNegFmt.negatives ?? "minus") : "minus";

  const setDecimals = (d: number) => {
    if (numericFmt) applyFormat({ ...numericFmt, decimals: d });
  };
  const toggleGrouping = () => {
    if (groupNegFmt) applyFormat({ ...groupNegFmt, grouping: !curGrouping });
  };
  const setNegatives = (v: string) => {
    if (groupNegFmt)
      applyFormat({
        ...groupNegFmt,
        negatives: v === "minus" ? undefined : (v as NegativeStyle),
      });
  };

  const FONT_SIZES = [10, 11, 12, 14, 16, 18, 20, 24, 28, 36];

  const currentFormatKey =
    NUMBER_PRESETS.find((p) => p.value.type === (scopeFormat?.type ?? "plain"))?.key ?? "plain";

  // Literal keys (not a template literal) so the typed ``t`` resolves.
  const presetLabel = (key: string): string => {
    switch (key) {
      case "fixed":
        return t("files:spreadsheet.format.preset.fixed");
      case "currency":
        return t("files:spreadsheet.format.preset.currency");
      case "percent":
        return t("files:spreadsheet.format.preset.percent");
      case "date":
        return t("files:spreadsheet.format.preset.date");
      default:
        return t("files:spreadsheet.format.preset.plain");
    }
  };

  const fontControls = (
    <div className="flex flex-wrap items-center gap-1.5">
      <Select
        value={scopeStyle.fontSize ? String(scopeStyle.fontSize) : "14"}
        onValueChange={(v) => applyStyle({ fontSize: Number(v) })}
        disabled={readOnly}
      >
        <SelectTrigger className="h-8 w-18" aria-label={t("files:spreadsheet.format.fontSize")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {FONT_SIZES.map((s) => (
            <SelectItem key={s} value={String(s)}>
              {s}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button
        type="button"
        size="icon-sm"
        variant={scopeStyle.bold ? "secondary" : "ghost"}
        disabled={readOnly}
        onClick={() => applyStyle({ bold: !scopeStyle.bold })}
        aria-label={t("files:spreadsheet.format.bold")}
        aria-pressed={Boolean(scopeStyle.bold)}
      >
        <Bold className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        size="icon-sm"
        variant={scopeStyle.italic ? "secondary" : "ghost"}
        disabled={readOnly}
        onClick={() => applyStyle({ italic: !scopeStyle.italic })}
        aria-label={t("files:spreadsheet.format.italic")}
        aria-pressed={Boolean(scopeStyle.italic)}
      >
        <Italic className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        size="icon-sm"
        variant={scopeStyle.underline ? "secondary" : "ghost"}
        disabled={readOnly}
        onClick={() => applyStyle({ underline: !scopeStyle.underline })}
        aria-label={t("files:spreadsheet.format.underline")}
        aria-pressed={Boolean(scopeStyle.underline)}
      >
        <Underline className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        size="icon-sm"
        variant={scopeStyle.strike ? "secondary" : "ghost"}
        disabled={readOnly}
        onClick={() => applyStyle({ strike: !scopeStyle.strike })}
        aria-label={t("files:spreadsheet.format.strike")}
        aria-pressed={Boolean(scopeStyle.strike)}
      >
        <Strikethrough className="h-4 w-4" />
      </Button>
    </div>
  );

  const alignControls = (
    <div className="flex flex-wrap items-center gap-2">
      <ToggleGroup
        type="single"
        size="sm"
        value={scopeStyle.align ?? ""}
        onValueChange={(v) => applyStyle({ align: (v || undefined) as CellAlign | undefined })}
        disabled={readOnly}
        aria-label={t("files:spreadsheet.format.alignment")}
      >
        <ToggleGroupItem value="left" aria-label={t("files:spreadsheet.format.alignLeft")}>
          <AlignLeft className="h-4 w-4" />
        </ToggleGroupItem>
        <ToggleGroupItem value="center" aria-label={t("files:spreadsheet.format.alignCenter")}>
          <AlignCenter className="h-4 w-4" />
        </ToggleGroupItem>
        <ToggleGroupItem value="right" aria-label={t("files:spreadsheet.format.alignRight")}>
          <AlignRight className="h-4 w-4" />
        </ToggleGroupItem>
      </ToggleGroup>
      <ToggleGroup
        type="single"
        size="sm"
        value={scopeStyle.valign ?? ""}
        onValueChange={(v) => applyStyle({ valign: (v || undefined) as CellVAlign | undefined })}
        disabled={readOnly}
        aria-label={t("files:spreadsheet.format.valignment")}
      >
        <ToggleGroupItem value="top" aria-label={t("files:spreadsheet.format.alignTop")}>
          <AlignVerticalJustifyStart className="h-4 w-4" />
        </ToggleGroupItem>
        <ToggleGroupItem value="middle" aria-label={t("files:spreadsheet.format.alignMiddle")}>
          <AlignVerticalJustifyCenter className="h-4 w-4" />
        </ToggleGroupItem>
        <ToggleGroupItem value="bottom" aria-label={t("files:spreadsheet.format.alignBottom")}>
          <AlignVerticalJustifyEnd className="h-4 w-4" />
        </ToggleGroupItem>
      </ToggleGroup>
    </div>
  );

  const colorControls = (
    <div className="flex flex-col gap-2">
      <ColorTrigger
        icon={<Baseline className="h-4 w-4" />}
        label={t("files:spreadsheet.format.textColor")}
        value={scopeStyle.color ?? "#111111"}
        active={Boolean(scopeStyle.color)}
        disabled={readOnly}
        onPick={(hex) => applyStyle({ color: hex })}
        onClear={() => applyStyle({ color: undefined })}
        clearLabel={t("files:spreadsheet.format.clearColor")}
      />
      <ColorTrigger
        icon={<PaintBucket className="h-4 w-4" />}
        label={t("files:spreadsheet.format.fill")}
        value={scopeStyle.fill ?? "#fff7cc"}
        active={Boolean(scopeStyle.fill)}
        disabled={readOnly}
        onPick={(hex) => applyStyle({ fill: hex })}
        onClear={() => applyStyle({ fill: undefined })}
        clearLabel={t("files:spreadsheet.format.clearFill")}
      />
    </div>
  );

  const borderPresets: {
    key: Parameters<typeof applyBorder>[0];
    icon: ReactNode;
    label: string;
  }[] = [
    {
      key: "all",
      icon: <Grid2x2 className="h-4 w-4" />,
      label: t("files:spreadsheet.format.borderAll"),
    },
    {
      key: "outer",
      icon: <Square className="h-4 w-4" />,
      label: t("files:spreadsheet.format.borderOuter"),
    },
    {
      key: "top",
      icon: <ArrowUpToLine className="h-4 w-4" />,
      label: t("files:spreadsheet.format.borderTop"),
    },
    {
      key: "right",
      icon: <ArrowRightToLine className="h-4 w-4" />,
      label: t("files:spreadsheet.format.borderRight"),
    },
    {
      key: "bottom",
      icon: <ArrowDownToLine className="h-4 w-4" />,
      label: t("files:spreadsheet.format.borderBottom"),
    },
    {
      key: "left",
      icon: <ArrowLeftToLine className="h-4 w-4" />,
      label: t("files:spreadsheet.format.borderLeft"),
    },
    {
      key: "none",
      icon: <SquareDashed className="h-4 w-4" />,
      label: t("files:spreadsheet.format.borderNone"),
    },
  ];

  const borderControls = (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Select
          value={borderStyle}
          onValueChange={(v) => setBorderStyle(v as BorderLineStyle)}
          disabled={readOnly}
        >
          <SelectTrigger
            className="h-8 w-28"
            aria-label={t("files:spreadsheet.format.borderStyle")}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(["thin", "medium", "thick", "dashed", "dotted", "double"] as const).map((s) => (
              <SelectItem key={s} value={s}>
                {borderStyleLabel(s)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <ColorTrigger
          icon={<SquareDashedTopSolid className="h-4 w-4" />}
          label={t("files:spreadsheet.format.borderColor")}
          value={borderColor}
          active
          disabled={readOnly}
          onPick={setBorderColor}
        />
      </div>
      <div className="grid grid-cols-2 gap-1">
        {borderPresets.map((p) => (
          <Button
            key={p.key}
            type="button"
            size="sm"
            variant="ghost"
            disabled={readOnly}
            onClick={() => applyBorder(p.key)}
            className="h-8 justify-start gap-1.5"
          >
            {p.icon}
            <span className="truncate">{p.label}</span>
          </Button>
        ))}
      </div>
    </div>
  );

  const numberControls = (
    <div className="flex flex-col gap-2">
      <Select
        value={currentFormatKey}
        onValueChange={(key) => {
          const preset = NUMBER_PRESETS.find((p) => p.key === key);
          if (preset) applyFormat(preset.value);
        }}
        disabled={readOnly || isRows}
      >
        <SelectTrigger className="h-8 w-32" aria-label={t("files:spreadsheet.format.numberFormat")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {NUMBER_PRESETS.map((p) => (
            <SelectItem key={p.key} value={p.key}>
              {presetLabel(p.key)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {numericFmt && (
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <span>{t("files:spreadsheet.format.decimals")}</span>
          <Select
            value={String(curDecimals)}
            onValueChange={(v) => setDecimals(Number(v))}
            disabled={readOnly}
          >
            <SelectTrigger className="h-8 w-16" aria-label={t("files:spreadsheet.format.decimals")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {[0, 1, 2, 3, 4, 5, 6].map((d) => (
                <SelectItem key={d} value={String(d)}>
                  {d}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
      {groupNegFmt && (
        <>
          <Button
            type="button"
            size="sm"
            variant={curGrouping ? "secondary" : "outline"}
            disabled={readOnly}
            onClick={toggleGrouping}
            aria-pressed={curGrouping}
            className="h-8 justify-start gap-1.5"
          >
            <Hash className="h-4 w-4" />
            {t("files:spreadsheet.format.thousandsSeparator")}
          </Button>
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span>{t("files:spreadsheet.format.negatives")}</span>
            <Select value={curNegatives} onValueChange={setNegatives} disabled={readOnly}>
              <SelectTrigger
                className="h-8 w-36"
                aria-label={t("files:spreadsheet.format.negatives")}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="minus">{t("files:spreadsheet.format.negMinus")}</SelectItem>
                <SelectItem value="red">{t("files:spreadsheet.format.negRed")}</SelectItem>
                <SelectItem value="parens">{t("files:spreadsheet.format.negParens")}</SelectItem>
                <SelectItem value="redParens">
                  {t("files:spreadsheet.format.negRedParens")}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
        </>
      )}
    </div>
  );

  const freezeControls = (
    <div className="flex flex-col gap-1">
      <Button
        type="button"
        size="sm"
        variant="ghost"
        className="h-8 justify-start"
        disabled={readOnly}
        onClick={() => formatting.setFrozen({ rows: focusRow + 1, cols: formatting.frozen.cols })}
      >
        {t("files:spreadsheet.format.freezeRowsHere", { count: focusRow + 1 })}
      </Button>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        className="h-8 justify-start"
        disabled={readOnly}
        onClick={() => formatting.setFrozen({ rows: formatting.frozen.rows, cols: focusCol + 1 })}
      >
        {t("files:spreadsheet.format.freezeColsHere", { count: focusCol + 1 })}
      </Button>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        className="h-8 justify-start"
        disabled={readOnly}
        onClick={() => formatting.setFrozen({ rows: 0, cols: 0 })}
      >
        {t("files:spreadsheet.format.unfreeze")}
      </Button>
    </div>
  );

  const clearButton = (
    <Button
      type="button"
      size="sm"
      variant="ghost"
      disabled={readOnly}
      onClick={clearScope}
      className="h-8 gap-1.5"
    >
      <Eraser className="h-4 w-4" />
      {t("files:spreadsheet.format.clear")}
    </Button>
  );

  // Literal t() keys (the typed t rejects template literals — see
  // ``presetLabel`` above). Grouped so aggregates sit apart from the
  // logic/math helpers in the menu.
  const functionGroups = [
    {
      title: t("files:spreadsheet.formula.aggregateGroup"),
      items: [
        { name: "SUM", desc: t("files:spreadsheet.formula.desc.SUM") },
        { name: "AVERAGE", desc: t("files:spreadsheet.formula.desc.AVERAGE") },
        { name: "MIN", desc: t("files:spreadsheet.formula.desc.MIN") },
        { name: "MAX", desc: t("files:spreadsheet.formula.desc.MAX") },
        { name: "COUNT", desc: t("files:spreadsheet.formula.desc.COUNT") },
        { name: "COUNTA", desc: t("files:spreadsheet.formula.desc.COUNTA") },
      ],
    },
    {
      title: t("files:spreadsheet.formula.otherGroup"),
      items: [
        { name: "IF", desc: t("files:spreadsheet.formula.desc.IF") },
        { name: "ROUND", desc: t("files:spreadsheet.formula.desc.ROUND") },
        { name: "ABS", desc: t("files:spreadsheet.formula.desc.ABS") },
      ],
    },
  ];

  // The function list, shared by the row's own menu and the overflow branch.
  const functionItems = (
    <>
      {functionGroups.map((group, gi) => (
        <Fragment key={group.title}>
          {gi > 0 && <DropdownMenuSeparator />}
          <DropdownMenuLabel className="text-muted-foreground text-xs">
            {group.title}
          </DropdownMenuLabel>
          {group.items.map((fn) => (
            <DropdownMenuItem
              key={fn.name}
              onSelect={() => onInsertFunction(fn.name)}
              className="flex-col items-start gap-0.5"
            >
              <span className="font-mono text-sm">{fn.name}</span>
              <span className="text-muted-foreground text-xs">{fn.desc}</span>
            </DropdownMenuItem>
          ))}
        </Fragment>
      ))}
      <DropdownMenuSeparator />
      <p className="px-2 py-1.5 text-muted-foreground text-xs">
        {t("files:spreadsheet.formula.hint")}
      </p>
    </>
  );

  const functionMenu = (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={readOnly}
          className="h-8 gap-1.5"
          aria-label={t("files:spreadsheet.formula.menuLabel")}
        >
          <Sigma className="h-4 w-4" />
          <span>{t("files:spreadsheet.formula.menu")}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        className="max-w-[16rem]"
        // Let the editor place focus (cell input or grid) without the menu
        // yanking it back to the trigger on close.
        onCloseAutoFocus={(e) => e.preventDefault()}
      >
        {functionItems}
      </DropdownMenuContent>
    </DropdownMenu>
  );

  const historyControls = (
    <div className="flex shrink-0 items-center">
      <Button
        type="button"
        size="icon-sm"
        variant="ghost"
        disabled={readOnly || !canUndo}
        onClick={onUndo}
        aria-label={t("files:spreadsheet.undo")}
        title={`${t("files:spreadsheet.undo")} (${HISTORY_SHORTCUT.undo})`}
      >
        <Undo2 className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        size="icon-sm"
        variant="ghost"
        disabled={readOnly || !canRedo}
        onClick={onRedo}
        aria-label={t("files:spreadsheet.redo")}
        title={`${t("files:spreadsheet.redo")} (${HISTORY_SHORTCUT.redo})`}
      >
        <Redo2 className="h-4 w-4" />
      </Button>
    </div>
  );

  // A group as one entry of the row, and the same controls as a named branch
  // of the overflow menu — one definition, two placements.
  const group = (
    id: string,
    icon: ReactNode,
    label: string,
    controls: ReactNode,
    disabled = readOnly
  ): OverflowToolbarItem => ({
    id,
    node: (
      <GroupPopover icon={icon} label={label} disabled={disabled}>
        {controls}
      </GroupPopover>
    ),
    menu: (
      <OverflowSubmenu id={id} icon={icon} label={label} className="max-w-72 p-3">
        {controls}
      </OverflowSubmenu>
    ),
  });

  // Ordered by reach, because the row sheds from the right: the formula menu
  // is the last to go, and the group a sheet is least likely to want mid-edit
  // is the first.
  const groups: OverflowToolbarItem[] = [
    {
      id: "formula",
      node: functionMenu,
      menu: (
        <OverflowSubmenu
          id="formula"
          icon={<Sigma className="h-4 w-4" />}
          label={t("files:spreadsheet.formula.menu")}
        >
          {functionItems}
        </OverflowSubmenu>
      ),
    },
    {
      ...group(
        "font",
        <Type className="h-4 w-4" />,
        t("files:spreadsheet.format.font"),
        fontControls
      ),
      startsGroup: true,
    },
    group(
      "alignment",
      <AlignLeft className="h-4 w-4" />,
      t("files:spreadsheet.format.alignment"),
      alignControls
    ),
    group(
      "colors",
      <Palette className="h-4 w-4" />,
      t("files:spreadsheet.format.colors"),
      colorControls
    ),
    group(
      "numberFormat",
      <Hash className="h-4 w-4" />,
      t("files:spreadsheet.format.numberFormat"),
      numberControls,
      readOnly || isRows
    ),
    group(
      "borders",
      <SquareDashedTopSolid className="h-4 w-4" />,
      t("files:spreadsheet.format.borders"),
      borderControls
    ),
    group(
      "freeze",
      <Snowflake className="h-4 w-4" />,
      t("files:spreadsheet.format.freeze"),
      freezeControls
    ),
    {
      id: "clear",
      startsGroup: true,
      node: clearButton,
      menu: (
        <OverflowMenuItem onSelect={clearScope} disabled={readOnly}>
          <Eraser className="h-4 w-4" />
          <span>{t("files:spreadsheet.format.clear")}</span>
        </OverflowMenuItem>
      ),
    },
  ];

  return (
    <OverflowToolbar
      items={groups}
      label={t("files:spreadsheet.format.title")}
      moreLabel={t("files:spreadsheet.format.title")}
      // Undo and redo are the one pair nobody should have to open a menu for.
      leading={historyControls}
      className="w-full"
    />
  );
};

interface ColorTriggerProps {
  icon: React.ReactNode;
  label: string;
  value: string;
  active: boolean;
  disabled: boolean;
  onPick: (hex: string) => void;
  /** Clear affordance is shown only when ``onClear`` is provided (it's
   *  meaningless for the border-color selector, which has no "unset"). */
  onClear?: () => void;
  clearLabel?: string;
}

// Live ticks only move the swatch here; the colour is applied once, when the
// picker closes, because applying it re-formats the whole selection (a Yjs
// write and a grid re-render).
const ColorTrigger = ({
  icon,
  label,
  clearLabel,
  value,
  active,
  disabled,
  onPick,
  onClear,
}: ColorTriggerProps) => {
  const [draft, setDraft] = useState(value);

  // The committed value only changes externally (other clients, clear),
  // never mid-pick — so syncing the swatch here can't fight the drag.
  const [prevValue, setPrevValue] = useState(value);
  if (prevValue !== value) {
    setPrevValue(value);
    setDraft(value);
  }

  return (
    <div className="flex items-center" title={label}>
      <ColorPickerPopover
        value={value}
        onChange={setDraft}
        onChangeComplete={onPick}
        disabled={disabled}
        triggerLabel={label}
        opaque
      >
        <button
          type="button"
          disabled={disabled}
          className={cn(
            "relative flex h-8 cursor-pointer items-center gap-1.5 rounded-md border border-input bg-background px-2 hover:bg-accent",
            disabled && "pointer-events-none opacity-50",
            active && "ring-2 ring-primary"
          )}
        >
          <span className="text-muted-foreground" aria-hidden>
            {icon}
          </span>
          <span
            aria-hidden
            className="h-4 w-4 rounded-sm border border-border"
            style={{ backgroundColor: active ? draft : "transparent" }}
          />
        </button>
      </ColorPickerPopover>
      {onClear && active && !disabled && (
        <Button
          type="button"
          size="icon-sm"
          variant="ghost"
          className="h-8"
          onClick={onClear}
          aria-label={clearLabel}
        >
          <Eraser className="h-3.5 w-3.5" />
        </Button>
      )}
    </div>
  );
};
