/**
 * From what an endpoint answered to what a widget reads.
 *
 * A statement's columns arrive already typed — the server described them rather
 * than guessing from the first row — so everything downstream of here sees the
 * same {@link TabularData}, whatever the statement read.
 */

import type { CellValue, ColumnGrain, DataColumn, WidgetData, WidgetSource } from "./dataShapes";

/** A cell, in the three shapes a JSON value can usefully be.
 *
 *  Anything else is nothing: a widget can draw a string, a number or a yes/no,
 *  and writing an object out would put "[object Object]" in a table rather than
 *  showing that the cell held nothing it could render. */
const cell = (value: unknown): CellValue => {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return value;
  }
  return null;
};

/**
 * A statement's answer, held to its own described width.
 *
 * A row longer than the described columns is cut and a shorter one padded, so a
 * widget indexing by column position can never read past the end of a row.
 */
export const normalizeQueryRows = (
  columns: (Omit<DataColumn, "grain"> & { grain?: string | null })[],
  rows: unknown[][]
): { columns: DataColumn[]; rows: CellValue[][] } => ({
  columns: columns.map(({ name, type, grain, date_only }) => ({
    name,
    type,
    ...(isColumnGrain(grain) ? { grain } : {}),
    ...(date_only === undefined ? {} : { date_only }),
  })),
  rows: rows.map((row) => columns.map((_column, index) => cell(row[index]))),
});

/** The periods a column may say it is rounded to. Anything else is dropped,
 *  so a widget only ever reads a grain it knows. */
const COLUMN_GRAINS = ["day", "week", "month", "quarter", "year"] as const;

const isColumnGrain = (grain: string | null | undefined): grain is ColumnGrain =>
  COLUMN_GRAINS.some((known) => known === grain);

/** The envelope for a binding we fetched nothing for — one whose parameters the
 *  instance config has not filled in yet. */
export const emptyDataFor = (source: WidgetSource): WidgetData =>
  source === "plugin"
    ? { source: "plugin", rows: [], values: {} }
    : { source: "rows", columns: [], rows: [] };
