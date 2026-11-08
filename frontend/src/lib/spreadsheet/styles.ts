/**
 * Pure formatting model for spreadsheet files (schema v2).
 *
 * Mirrors the backend normalizer in
 * ``backend/app/services/tenant/files_spreadsheet.py`` — caps, enums, and
 * the "drop bad entries, never throw" discipline are kept in sync so a
 * client never sends something the server would silently strip.
 *
 * No React / DOM / date-fns imports: everything here is a pure function
 * so it can be unit-tested in isolation and reused by the xlsx mapper.
 *
 * Number formatting is **display-only**. The raw scalar in the cell map
 * is never transformed by these helpers — CSV export, the Y.Map, and
 * the inline editor all operate on the untouched value.
 */

import type { CSSProperties } from "react";

import { numberFormat } from "@/ui/lib/intl";

import type { CellValue } from "./coords";

export type CellAlign = "left" | "center" | "right";
export type CellVAlign = "top" | "middle" | "bottom";
/** How negative numbers render. ``minus`` is the default (omitted). */
export type NegativeStyle = "minus" | "red" | "parens" | "redParens";

export type BorderLineStyle = "thin" | "medium" | "thick" | "dashed" | "dotted" | "double";

export interface BorderEdge {
  style: BorderLineStyle;
  /** ``#rrggbb`` (lowercase, validated). */
  color: string;
}

/** Per-edge borders; an absent edge means "no custom border" (the
 *  default grid line shows through). */
export interface CellBorder {
  top?: BorderEdge;
  right?: BorderEdge;
  bottom?: BorderEdge;
  left?: BorderEdge;
}

export interface CellStyle {
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  strike?: boolean;
  /** ``#rrggbb`` (lowercase, validated). */
  color?: string;
  /** ``#rrggbb`` (lowercase, validated). */
  fill?: string;
  align?: CellAlign;
  /** Vertical alignment; absent = bottom-ish default (centered here). */
  valign?: CellVAlign;
  /** Font size in px (the model's unit, like width/height); converted
   *  to/from points on xlsx round-trip. */
  fontSize?: number;
  border?: CellBorder;
}

export type NumberFormat =
  | { type: "plain" }
  | {
      type: "currency";
      currency: string;
      decimals: number;
      /** Thousands separator. Default for currency is grouped. */
      grouping?: boolean;
      negatives?: NegativeStyle;
    }
  | { type: "percent"; decimals: number }
  | { type: "date"; pattern: "iso" | "us" | "eu" }
  | {
      type: "fixed";
      decimals: number;
      /** Thousands separator. Default for plain numbers is ungrouped. */
      grouping?: boolean;
      negatives?: NegativeStyle;
    };

export interface ColumnFmt {
  width?: number;
  format?: NumberFormat;
  style?: CellStyle;
  /** Drawn at zero width. The cells still exist, still hold values and are
   *  still read by formulas — the column is simply not shown, and the
   *  cursor steps over it. */
  hidden?: boolean;
}

export interface RowFmt {
  height?: number;
  style?: CellStyle;
  /** Drawn at zero height — see {@link ColumnFmt.hidden}. */
  hidden?: boolean;
}

export interface CellFmt {
  style?: CellStyle;
  format?: NumberFormat;
}

export interface SpreadsheetFormatting {
  columns: Record<string, ColumnFmt>;
  rows: Record<string, RowFmt>;
  cellStyles: Record<string, CellFmt>;
  frozen: { rows: number; cols: number };
}

// Keep these in lockstep with the backend constants.
export const MIN_COL_WIDTH = 24;
export const MAX_COL_WIDTH = 2_000;
export const MIN_ROW_HEIGHT = 16;
export const MAX_ROW_HEIGHT = 1_000;
export const MAX_DECIMALS = 10;
export const MAX_FROZEN = 8;
export const MIN_FONT_SIZE = 6;
export const MAX_FONT_SIZE = 96;

const HEX_COLOR_RE = /^#[0-9a-fA-F]{6}$/;
const CURRENCY_RE = /^[A-Za-z]{3}$/;
const INDEX_KEY_RE = /^\d+$/;
const CELL_KEY_RE = /^(\d+):(\d+)$/;
const ALIGN_VALUES: ReadonlySet<string> = new Set(["left", "center", "right"]);
const VALIGN_VALUES: ReadonlySet<string> = new Set(["top", "middle", "bottom"]);
const NEGATIVE_STYLES: ReadonlySet<string> = new Set(["red", "parens", "redParens"]);
const DATE_PATTERNS: ReadonlySet<string> = new Set(["iso", "us", "eu"]);
const BORDER_STYLES: ReadonlySet<string> = new Set([
  "thin",
  "medium",
  "thick",
  "dashed",
  "dotted",
  "double",
]);
const BORDER_EDGES = ["top", "right", "bottom", "left"] as const;
const FORMAT_TYPES: ReadonlySet<string> = new Set([
  "currency",
  "percent",
  "date",
  "fixed",
  "plain",
]);

const clampInt = (value: unknown, lo: number, hi: number): number | undefined => {
  if (typeof value !== "number" || !Number.isInteger(value)) return undefined;
  return Math.max(lo, Math.min(value, hi));
};

const clampDecimals = (value: unknown, fallback: number): number => {
  if (typeof value !== "number" || !Number.isInteger(value)) return fallback;
  return Math.max(0, Math.min(value, MAX_DECIMALS));
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** Sanitize a {@link CellStyle}. Unknown keys stripped; bad values drop
 *  their key. Explicit ``bold``/``italic`` booleans (including ``false``)
 *  are preserved so a per-cell override can toggle a column/row style
 *  back off through the spread-merge in {@link resolveCellStyle}. */
export const sanitizeStyle = (value: unknown): CellStyle | undefined => {
  if (!isRecord(value)) return undefined;
  const out: CellStyle = {};
  if (typeof value.bold === "boolean") out.bold = value.bold;
  if (typeof value.italic === "boolean") out.italic = value.italic;
  if (typeof value.underline === "boolean") out.underline = value.underline;
  if (typeof value.strike === "boolean") out.strike = value.strike;
  if (typeof value.color === "string" && HEX_COLOR_RE.test(value.color))
    out.color = value.color.toLowerCase();
  if (typeof value.fill === "string" && HEX_COLOR_RE.test(value.fill))
    out.fill = value.fill.toLowerCase();
  if (typeof value.align === "string" && ALIGN_VALUES.has(value.align))
    out.align = value.align as CellAlign;
  if (typeof value.valign === "string" && VALIGN_VALUES.has(value.valign))
    out.valign = value.valign as CellVAlign;
  const fontSize = clampInt(value.fontSize, MIN_FONT_SIZE, MAX_FONT_SIZE);
  if (fontSize !== undefined) out.fontSize = fontSize;
  const border = sanitizeBorder(value.border);
  if (border) out.border = border;
  return Object.keys(out).length > 0 ? out : undefined;
};

const sanitizeBorderEdge = (value: unknown): BorderEdge | undefined => {
  if (!isRecord(value)) return undefined;
  if (typeof value.style !== "string" || !BORDER_STYLES.has(value.style)) return undefined;
  if (typeof value.color !== "string" || !HEX_COLOR_RE.test(value.color)) return undefined;
  return { style: value.style as BorderLineStyle, color: value.color.toLowerCase() };
};

/** Sanitize a {@link CellBorder}. Each edge is independent — a bad edge
 *  is dropped, not the whole border; no valid edge → ``undefined``. */
export const sanitizeBorder = (value: unknown): CellBorder | undefined => {
  if (!isRecord(value)) return undefined;
  const out: CellBorder = {};
  for (const edge of BORDER_EDGES) {
    const e = sanitizeBorderEdge(value[edge]);
    if (e) out[edge] = e;
  }
  return Object.keys(out).length > 0 ? out : undefined;
};

/** Sanitize a {@link NumberFormat} preset. Unknown ``type`` → dropped. */
export const sanitizeFormat = (value: unknown): NumberFormat | undefined => {
  if (!isRecord(value)) return undefined;
  const type = value.type;
  if (typeof type !== "string" || !FORMAT_TYPES.has(type)) return undefined;
  if (type === "plain") return { type: "plain" };
  if (type === "date") {
    const pattern =
      typeof value.pattern === "string" && DATE_PATTERNS.has(value.pattern)
        ? (value.pattern as "iso" | "us" | "eu")
        : "iso";
    return { type: "date", pattern };
  }
  const negatives =
    typeof value.negatives === "string" && NEGATIVE_STYLES.has(value.negatives)
      ? (value.negatives as NegativeStyle)
      : undefined;
  if (type === "currency") {
    const raw = typeof value.currency === "string" ? value.currency.trim() : "";
    const currency = CURRENCY_RE.test(raw) ? raw.toUpperCase() : "USD";
    const out: NumberFormat = {
      type: "currency",
      currency,
      decimals: clampDecimals(value.decimals, 2),
    };
    if (typeof value.grouping === "boolean") out.grouping = value.grouping;
    if (negatives) out.negatives = negatives;
    return out;
  }
  if (type === "percent") {
    return { type: "percent", decimals: clampDecimals(value.decimals, 1) };
  }
  // fixed
  const out: NumberFormat = { type: "fixed", decimals: clampDecimals(value.decimals, 2) };
  if (typeof value.grouping === "boolean") out.grouping = value.grouping;
  if (negatives) out.negatives = negatives;
  return out;
};

export const sanitizeColumnFmt = (value: unknown): ColumnFmt | undefined => {
  if (!isRecord(value)) return undefined;
  const out: ColumnFmt = {};
  const width = clampInt(value.width, MIN_COL_WIDTH, MAX_COL_WIDTH);
  if (width !== undefined) out.width = width;
  const format = sanitizeFormat(value.format);
  if (format) out.format = format;
  const style = sanitizeStyle(value.style);
  if (style) out.style = style;
  if (value.hidden === true) out.hidden = true;
  return Object.keys(out).length > 0 ? out : undefined;
};

export const sanitizeRowFmt = (value: unknown): RowFmt | undefined => {
  if (!isRecord(value)) return undefined;
  const out: RowFmt = {};
  const height = clampInt(value.height, MIN_ROW_HEIGHT, MAX_ROW_HEIGHT);
  if (height !== undefined) out.height = height;
  const style = sanitizeStyle(value.style);
  if (style) out.style = style;
  if (value.hidden === true) out.hidden = true;
  return Object.keys(out).length > 0 ? out : undefined;
};

export const sanitizeCellFmt = (value: unknown): CellFmt | undefined => {
  if (!isRecord(value)) return undefined;
  const out: CellFmt = {};
  const style = sanitizeStyle(value.style);
  if (style) out.style = style;
  const format = sanitizeFormat(value.format);
  if (format) out.format = format;
  return Object.keys(out).length > 0 ? out : undefined;
};

/**
 * Coerce an arbitrary ``content``-blob slice into the canonical
 * {@link SpreadsheetFormatting}. Accepts v1 (everything absent) or v2.
 * Bad keys/entries are dropped — never throws (the backend is the
 * authority on hard rejects; the client stays forgiving).
 */
export const sanitizeFormatting = (raw: unknown): SpreadsheetFormatting => {
  const src = isRecord(raw) ? raw : {};
  const columns: Record<string, ColumnFmt> = {};
  if (isRecord(src.columns)) {
    for (const [key, entry] of Object.entries(src.columns)) {
      if (!INDEX_KEY_RE.test(key)) continue;
      const norm = sanitizeColumnFmt(entry);
      if (norm) columns[String(Number(key))] = norm;
    }
  }
  const rows: Record<string, RowFmt> = {};
  if (isRecord(src.rows)) {
    for (const [key, entry] of Object.entries(src.rows)) {
      if (!INDEX_KEY_RE.test(key)) continue;
      const norm = sanitizeRowFmt(entry);
      if (norm) rows[String(Number(key))] = norm;
    }
  }
  const cellStyles: Record<string, CellFmt> = {};
  if (isRecord(src.cellStyles)) {
    for (const [key, entry] of Object.entries(src.cellStyles)) {
      const m = CELL_KEY_RE.exec(key);
      if (!m) continue;
      const norm = sanitizeCellFmt(entry);
      if (norm) cellStyles[`${Number(m[1])}:${Number(m[2])}`] = norm;
    }
  }
  const frozenSrc = isRecord(src.frozen) ? src.frozen : {};
  const frozen = {
    rows: clampInt(frozenSrc.rows, 0, MAX_FROZEN) ?? 0,
    cols: clampInt(frozenSrc.cols, 0, MAX_FROZEN) ?? 0,
  };
  return { columns, rows, cellStyles, frozen };
};

/**
 * Resolve the effective style for a cell. Precedence (lowest → highest,
 * later wins per-property): row → column → cell. Spread-merge means a
 * cell-level ``bold:false`` overrides a column-level ``bold:true`` while
 * leaving an unrelated column ``fill`` intact.
 */
export const resolveCellStyle = (
  row: number,
  col: number,
  fmt: SpreadsheetFormatting
): CellStyle => {
  const rowStyle = fmt.rows[String(row)]?.style ?? {};
  const colStyle = fmt.columns[String(col)]?.style ?? {};
  const cellStyle = fmt.cellStyles[`${row}:${col}`]?.style ?? {};
  return { ...rowStyle, ...colStyle, ...cellStyle };
};

/** Resolve the effective number format: per-cell override wins over the
 *  column default; rows don't carry a format. */
export const resolveCellFormat = (
  row: number,
  col: number,
  fmt: SpreadsheetFormatting
): NumberFormat | undefined =>
  fmt.cellStyles[`${row}:${col}`]?.format ?? fmt.columns[String(col)]?.format;

/** Translate a resolved {@link CellStyle} to inline CSS for the grid.
 *  Returned object only carries keys that are actually set so it can be
 *  spread onto the cell's positioning style without clobbering it. */
export const styleToCss = (style: CellStyle): CSSProperties => {
  const css: CSSProperties = {};
  if (style.bold) css.fontWeight = 600;
  if (style.italic) css.fontStyle = "italic";
  if (style.underline || style.strike) {
    css.textDecorationLine = [
      style.underline ? "underline" : null,
      style.strike ? "line-through" : null,
    ]
      .filter(Boolean)
      .join(" ");
  }
  if (style.color) css.color = style.color;
  if (style.fill) css.backgroundColor = style.fill;
  if (style.align) css.textAlign = style.align;
  if (style.valign)
    css.alignItems =
      style.valign === "top" ? "flex-start" : style.valign === "bottom" ? "flex-end" : "center";
  if (style.fontSize) css.fontSize = `${style.fontSize}px`;
  if (style.border) {
    const b = style.border;
    if (b.top) css.borderTop = borderCss(b.top);
    if (b.right) css.borderRight = borderCss(b.right);
    if (b.bottom) css.borderBottom = borderCss(b.bottom);
    if (b.left) css.borderLeft = borderCss(b.left);
  }
  return css;
};

// Custom edges set an inline border, which overrides the cell's default
// 1px grid line on that side; absent edges fall through to the grid.
const BORDER_CSS: Record<BorderLineStyle, string> = {
  thin: "1px solid",
  medium: "2px solid",
  thick: "3px solid",
  dashed: "1px dashed",
  dotted: "1px dotted",
  // ``double`` needs >=3px to actually render two lines.
  double: "3px double",
};
const borderCss = (edge: BorderEdge): string => `${BORDER_CSS[edge.style]} ${edge.color}`;

const pad = (n: number, width = 2): string => String(n).padStart(width, "0");

const extractDate = (raw: CellValue): { y: number; m: number; d: number } | null => {
  if (raw == null || typeof raw === "boolean") return null;
  const s = String(raw).trim();
  const iso = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (iso) return { y: Number(iso[1]), m: Number(iso[2]), d: Number(iso[3]) };
  const parsed = new Date(s);
  if (Number.isNaN(parsed.getTime())) return null;
  return {
    y: parsed.getFullYear(),
    m: parsed.getMonth() + 1,
    d: parsed.getDate(),
  };
};

/**
 * Format a raw cell value for **display** per a resolved number format.
 * Non-numeric values fall through to their string form unchanged
 * (formatting a text cell as currency must not corrupt it). Percent
 * follows the spreadsheet convention of multiplying the stored value by
 * 100 (a stored ``0.25`` shows ``25%``), matching xlsx ``numFmt`` and
 * round-tripping cleanly.
 */
export const formatCellValue = (raw: CellValue, fmt: NumberFormat | undefined): string => {
  if (raw == null) return "";
  if (!fmt || fmt.type === "plain") return String(raw);

  if (fmt.type === "date") {
    const parts = extractDate(raw);
    if (!parts) return String(raw);
    const { y, m, d } = parts;
    if (fmt.pattern === "us") return `${pad(m)}/${pad(d)}/${y}`;
    if (fmt.pattern === "eu") return `${pad(d)}/${pad(m)}/${y}`;
    return `${y}-${pad(m)}-${pad(d)}`;
  }

  const num = typeof raw === "number" ? raw : Number(raw);
  if (typeof raw === "boolean" || !Number.isFinite(num)) return String(raw);

  if (fmt.type === "percent") {
    return `${(num * 100).toFixed(fmt.decimals)}%`;
  }

  // currency / fixed share grouping + negative-style handling. The
  // magnitude is formatted unsigned; we add the sign / parentheses so
  // the convention is consistent regardless of locale.
  const grouped = fmt.type === "currency" ? (fmt.grouping ?? true) : (fmt.grouping ?? false);
  const abs = Math.abs(num);
  let body: string;
  if (fmt.type === "currency") {
    try {
      body = numberFormat(undefined, {
        style: "currency",
        currency: fmt.currency,
        minimumFractionDigits: fmt.decimals,
        maximumFractionDigits: fmt.decimals,
        useGrouping: grouped,
        signDisplay: "never",
      }).format(abs);
    } catch {
      // Unknown currency code → fall back to a plain fixed render.
      body = abs.toFixed(fmt.decimals);
    }
  } else {
    body = numberFormat(undefined, {
      minimumFractionDigits: fmt.decimals,
      maximumFractionDigits: fmt.decimals,
      useGrouping: grouped,
      signDisplay: "never",
    }).format(abs);
  }
  if (num >= 0) return body;
  const parens = fmt.negatives === "parens" || fmt.negatives === "redParens";
  return parens ? `(${body})` : `-${body}`;
};

/** Whether the renderer should paint this value red — true only for a
 *  negative number under a ``red``/``redParens`` currency/fixed format.
 *  (The red can't live in the formatted string, so the cell view
 *  applies it; the string itself comes from {@link formatCellValue}.) */
export const negativeRendersRed = (raw: CellValue, fmt: NumberFormat | undefined): boolean => {
  if (!fmt || (fmt.type !== "currency" && fmt.type !== "fixed")) return false;
  if (fmt.negatives !== "red" && fmt.negatives !== "redParens") return false;
  if (typeof raw === "boolean") return false;
  const num = typeof raw === "number" ? raw : Number(raw);
  return Number.isFinite(num) && num < 0;
};
