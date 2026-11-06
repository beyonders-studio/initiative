/**
 * A range of a workbook, read the way a dashboard statement reads one.
 *
 * `sheet(file, range)` names cells in Google's A1 notation: `Sheet1!A1:B2`,
 * `Sheet1!A:C`, `Sheet1!A5:C` (row 5 down), `Sheet1!1:2`, a sheet alone, or a
 * range alone for the first visible sheet. The sheet is everything before the
 * last `!`, which no range contains, so a sheet name needs quoting only in
 * Google's own form (`'Q1 Actuals'!A:C`), which is read too. An open end stops
 * at the sheet's last filled row or column.
 *
 * The server runs this in its build of the editor (`serverEditor.ts`), so the
 * range is read by the grid's own coordinates and its formulas by the grid's
 * own evaluator: a formula cell gives what the grid shows for it.
 *
 * The first row is the header when the range has more than one row and every
 * cell in it is text, which is Google QUERY's default guess. Columns are named
 * by the header, or by their letters without one, and typed by their values.
 */

import { parseSpreadsheetContent } from "./content";
import { boundingBox, type CellValue, colIndexToLetter, letterToColIndex } from "./coords";
import { createEvaluator } from "./formula";
import { quoteSheetName, sheetNameKey, unquoteSheetName } from "./sheets";

/** The most cells one range reads. */
export const MAX_RANGE_CELLS = 100_000;

export type RangeColumnType = "number" | "date" | "datetime" | "boolean" | "text";

export interface RangeColumn {
  name: string;
  type: RangeColumnType;
}

export type RangeRead =
  | { columns: RangeColumn[]; rows: CellValue[][]; sheets: string[] }
  | { refused: "unknown_sheet" | "invalid_range" | "too_large"; sheets: string[] };

/** One corner of a range. A side the range leaves open is `null`. */
interface Corner {
  col: number | null;
  row: number | null;
}

const CORNER = /^\$?([A-Za-z]{0,3})\$?(\d*)$/;

const corner = (text: string): Corner | null => {
  const match = CORNER.exec(text.trim());
  if (!match || (!match[1] && !match[2])) return null;
  const row = match[2] ? Number(match[2]) - 1 : null;
  if (row !== null && row < 0) return null;
  return { col: match[1] ? letterToColIndex(match[1]) : null, row };
};

/** The corners a range's cells part names, or `null` when it names none. A
 *  lone corner is one cell, so it names both a column and a row. */
const corners = (text: string): [Corner, Corner] | null => {
  const parts = text.split(":");
  if (parts.length > 2) return null;
  const start = corner(parts[0]);
  const end = parts.length === 2 ? corner(parts[1]) : start;
  if (!start || !end) return null;
  if (parts.length === 1 && (start.col === null || start.row === null)) return null;
  return [start, end];
};

/** From one end to the other along one axis. Two stated ends read either way
 *  round; an open end runs to the last filled index, and a start past it reads
 *  nothing. */
const span = (start: number | null, end: number | null, last: number): [number, number] => {
  if (start !== null && end !== null) return [Math.min(start, end), Math.max(start, end)];
  return [start ?? 0, end ?? last];
};

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const ISO_DATETIME = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/;

const isDate = (value: string, pattern: RegExp) =>
  pattern.test(value) && !Number.isNaN(Date.parse(value.replace(" ", "T")));

/** A range's sheet, or `null` for the first visible one, and its cells part,
 *  empty for the whole sheet. */
export const splitRange = (range: string | null): { sheet: string | null; cells: string } => {
  const text = (range ?? "").trim();
  if (/^'(?:[^']|'')+'$/.test(text)) return { sheet: unquoteSheetName(text), cells: "" };
  const bang = text.lastIndexOf("!");
  if (bang >= 0) {
    const sheet = text.slice(0, bang).trim();
    return {
      sheet: sheet.startsWith("'") ? unquoteSheetName(sheet) : sheet,
      cells: text.slice(bang + 1).trim(),
    };
  }
  // Text that reads as a cell reference is one, and so is text with a `:`,
  // which no sheet name holds; anything else is a sheet.
  if (!text || text.includes(":") || corners(text)) return { sheet: null, cells: text };
  return { sheet: text.startsWith("'") ? unquoteSheetName(text) : text, cells: "" };
};

/** The range a sheet and a cells part make: the inverse of {@link splitRange}.
 *  A sheet alone is quoted as a formula quotes it, so a name that reads as a
 *  cell reference stays a name. */
export const joinRange = (sheet: string | null, cells: string): string | null => {
  const part = cells.trim();
  if (!sheet) return part || null;
  return part ? `${sheet}!${part}` : quoteSheetName(sheet);
};

/** `range` of the workbook `content`, as a statement reads it. Without a
 *  range, the first visible sheet's filled area. */
export const readRange = (content: unknown, range: string | null): RangeRead => {
  const workbook = parseSpreadsheetContent(content);
  const sheets = workbook.sheets.filter((sheet) => !sheet.hidden).map((sheet) => sheet.name);
  const { sheet: sheetName, cells } = splitRange(range);
  const wanted = sheetName === null ? null : sheetNameKey(sheetName);
  const sheet = workbook.sheets.find((candidate) =>
    wanted === null ? !candidate.hidden : sheetNameKey(candidate.name) === wanted
  );
  if (!sheet) return { refused: "unknown_sheet", sheets };

  const named = cells
    ? corners(cells)
    : [
        { col: null, row: null },
        { col: null, row: null },
      ];
  if (!named) return { refused: "invalid_range", sheets };
  const [start, end] = named;
  const filled = boundingBox(sheet.cells);
  const [r1, r2] = span(start.row, end.row, filled.rows - 1);
  const [c1, c2] = span(start.col, end.col, filled.cols - 1);
  const height = Math.max(0, r2 - r1 + 1);
  const width = Math.max(0, c2 - c1 + 1);
  if (height * width > MAX_RANGE_CELLS) return { refused: "too_large", sheets };

  const evaluator = createEvaluator({
    sheets: workbook.sheets.map((each) => ({
      id: each.id,
      name: each.name,
      cells: new Map(Object.entries(each.cells)),
    })),
    activeSheetId: sheet.id,
  });
  const read: CellValue[][] = [];
  for (let row = r1; row < r1 + height; row++) {
    const line: CellValue[] = [];
    for (let col = c1; col < c1 + width; col++) {
      const result = evaluator.evaluate(row, col, sheet.id);
      line.push(result.error ?? result.value ?? null);
    }
    read.push(line);
  }

  const [first] = read;
  const header =
    read.length > 1 && first.every((value) => typeof value === "string" && value.trim() !== "");
  const rows = header ? read.slice(1) : read;
  const columns = Array.from({ length: width }, (_, index): RangeColumn => {
    // What a column holds, read off its filled cells: blanks say nothing.
    const filled = rows.map((row) => row[index]).filter((value) => value !== null && value !== "");
    const text = filled.filter((value): value is string => typeof value === "string");
    const type: RangeColumnType = !filled.length
      ? "text"
      : filled.every((value) => typeof value === "number")
        ? "number"
        : filled.every((value) => typeof value === "boolean")
          ? "boolean"
          : text.length < filled.length
            ? "text"
            : text.every((value) => isDate(value, ISO_DATE))
              ? "date"
              : text.every((value) => isDate(value, ISO_DATE) || isDate(value, ISO_DATETIME))
                ? "datetime"
                : "text";
    return { name: header ? String(first[index]).trim() : colIndexToLetter(c1 + index), type };
  });
  return { columns, rows, sheets };
};
