/**
 * CSV parsing for spreadsheet cells.
 *
 * Import wraps papaparse, which already handles quoted fields, embedded
 * commas, escaped quotes, and CRLF / LF line endings.
 */

import Papa from "papaparse";

import { type CellValue, keyOf, parseKey } from "./coords";

/**
 * Parse CSV / TSV text into a sparse cell map.
 *
 * Numbers are coerced to ``number``; the literal strings "true" /
 * "false" (case-insensitive) become booleans. Everything else stays a
 * string. Empty cells are not written to the map.
 */
export const csvToCells = (
  text: string,
  options: { delimiter?: string } = {}
): { cells: Record<string, CellValue>; rows: number; cols: number } => {
  const result = Papa.parse<string[]>(text, {
    delimiter: options.delimiter ?? "",
    skipEmptyLines: false,
    dynamicTyping: false,
  });

  const cells: Record<string, CellValue> = {};
  let rows = 0;
  let cols = 0;
  for (let r = 0; r < result.data.length; r++) {
    const row = result.data[r];
    if (!Array.isArray(row)) continue;
    for (let c = 0; c < row.length; c++) {
      const raw = row[c];
      if (raw === undefined || raw === "") continue;
      cells[keyOf(r, c)] = coerceScalar(raw);
      if (r + 1 > rows) rows = r + 1;
      if (c + 1 > cols) cols = c + 1;
    }
  }
  return { cells, rows, cols };
};

/**
 * Coerce a single text input from the user (or the clipboard, or a CSV
 * cell) to a scalar. Mirrors the heuristic the inline editor uses so
 * paste and direct typing produce the same shape.
 */
export const coerceScalar = (raw: string): CellValue => {
  const trimmed = raw.trim();
  if (trimmed === "") return "";
  const lower = trimmed.toLowerCase();
  if (lower === "true") return true;
  if (lower === "false") return false;
  // Numeric coercion: must look entirely numeric (allow ., -, e/E for
  // exponent notation, and a bare leading "." like ".7") and round-trip
  // cleanly. Don't coerce things like "01234" since those usually are
  // IDs / phone numbers, not numbers — preserving the leading zero matters.
  if (/^-?\d*\.?\d+([eE][-+]?\d+)?$/.test(trimmed)) {
    if (trimmed.startsWith("0") && !trimmed.startsWith("0.") && trimmed !== "0") {
      // Return the trimmed form so leading/trailing whitespace from a
      // clipboard paste (" 0123") doesn't get persisted with padding
      // intact.
      return trimmed;
    }
    const num = Number(trimmed);
    if (Number.isFinite(num)) return num;
  }
  return raw;
};

/**
 * Parse clipboard text into a sparse cell map.
 *
 * Tabs are the only column delimiter: that's what Numbers / Excel /
 * Sheets write when you copy a multi-cell range, and it keeps a pasted
 * sentence ("hi, there, friend") in the one cell the user aimed at
 * instead of spreading its commas over the neighbours. Text with no
 * tabs becomes a single column, one row per line — same as pasting
 * raw CSV text into Excel or Sheets, which both need an explicit
 * split-to-columns step afterwards.
 */
export const clipboardToCells = (
  text: string
): { cells: Record<string, CellValue>; rows: number; cols: number } => {
  if (text.includes("\t")) return csvToCells(text, { delimiter: "\t" });

  // No tabs: split rows ourselves rather than handing the text to
  // papaparse, so quote characters in prose stay literal.
  const cells: Record<string, CellValue> = {};
  const lines = text.split(/\r\n|\n|\r/);
  let rows = 0;
  for (let r = 0; r < lines.length; r++) {
    if (lines[r] === "") continue;
    cells[keyOf(r, 0)] = coerceScalar(lines[r]);
    rows = r + 1;
  }
  return { cells, rows, cols: rows === 0 ? 0 : 1 };
};

/**
 * Apply a parsed cell map starting at an origin offset. Used by the
 * paste handler so a 3×3 clipboard block dropped at B2 lands at B2:D4
 * rather than A1:C3.
 */
export const offsetCells = (
  cells: Record<string, CellValue>,
  originRow: number,
  originCol: number
): Record<string, CellValue> => {
  const out: Record<string, CellValue> = {};
  for (const [key, value] of Object.entries(cells)) {
    const parsed = parseKey(key);
    if (!parsed) continue;
    out[keyOf(parsed[0] + originRow, parsed[1] + originCol)] = value;
  }
  return out;
};
