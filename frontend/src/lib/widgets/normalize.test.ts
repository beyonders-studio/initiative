/**
 * From what an endpoint answered to what a widget reads.
 *
 * A statement's columns arrive already typed. What is asserted here is that
 * they come out in the envelope a widget reads, and that it cannot hand a
 * widget a row it would index past the end of.
 */
import { describe, expect, it } from "vitest";

import { emptyDataFor, normalizeQueryRows } from "./normalize";

describe("normalizeQueryRows", () => {
  it("preserves calendar-date metadata without marking true timestamps", () => {
    const { columns } = normalizeQueryRows(
      [
        { name: "day", type: "date", date_only: true },
        { name: "at", type: "date", date_only: false },
      ],
      []
    );
    expect(columns[0]).toEqual({ name: "day", type: "date", date_only: true });
    expect(columns[1].date_only).not.toBe(true);
  });

  it("keeps a grain it knows and drops one it does not", () => {
    const { columns } = normalizeQueryRows(
      [
        { name: "m", type: "date", grain: "month" },
        { name: "h", type: "date", grain: "hour" },
        { name: "d", type: "date", grain: null },
      ],
      []
    );
    expect(columns).toEqual([
      { name: "m", type: "date", grain: "month" },
      { name: "h", type: "date" },
      { name: "d", type: "date" },
    ]);
  });

  const columns = [
    { name: "stage", type: "text" as const },
    { name: "tasks", type: "number" as const },
  ];

  it("keeps rows positional against the described columns", () => {
    expect(normalizeQueryRows(columns, [["Backlog", 4]]).rows).toEqual([["Backlog", 4]]);
  });

  it("holds a row to the described width", () => {
    // Longer is cut, shorter is padded, so a widget indexing by position can
    // never read past the end of a row.
    const { rows } = normalizeQueryRows(columns, [["a", 1, "extra"], ["b"]]);
    expect(rows).toEqual([
      ["a", 1],
      ["b", null],
    ]);
  });

  it("carries scalars as themselves and nulls anything else", () => {
    const mixed = [
      { name: "n", type: "number" as const },
      { name: "b", type: "boolean" as const },
      { name: "o", type: "text" as const },
    ];
    expect(normalizeQueryRows(mixed, [[2, false, { nested: true }]]).rows).toEqual([
      [2, false, null],
    ]);
  });

  it("reports no rows for a statement that returned none", () => {
    expect(normalizeQueryRows(columns, []).rows).toEqual([]);
  });
});

describe("emptyDataFor", () => {
  it("gives a statement an empty tabular envelope", () => {
    expect(emptyDataFor("query")).toEqual({ source: "rows", columns: [], rows: [] });
  });

  it("gives a plug-in binding its own empty envelope", () => {
    expect(emptyDataFor("plugin")).toEqual({ source: "plugin", rows: [], values: {} });
  });
});
