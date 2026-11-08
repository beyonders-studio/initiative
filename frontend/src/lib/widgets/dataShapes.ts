/**
 * What a widget receives.
 *
 * A binding names a `source` (§6 of the design); the host resolves it through
 * the ordinary RLS-gated hooks — per viewer, through the six gates — and hands
 * the widget the normalized envelope below. The widget never names an endpoint
 * and never sees a token: by the time it runs, authorization has already
 * happened and it is looking at rows the viewer could have loaded themselves.
 *
 * **There are two envelopes, not nine.** A statement and a spreadsheet range
 * both answer with columns and rows, so both arrive as {@link TabularData} and
 * a widget never learns which it was given. An installed plug-in's data is its own
 * shape, declared in its own manifest, and its widget ships alongside — that is
 * {@link PluginRows}, and no built-in widget reads it.
 *
 * **All timestamps are epoch milliseconds, UTC.** The sandbox has a frozen
 * clock and no timezone, deliberately: rendering a timestamp for a human is the
 * renderer's job, not the widget's.
 */

/**
 * What a column holds, in the field registry's own vocabulary.
 *
 * Declared here rather than imported from the generated client, because this
 * file is the sandbox's contract and a widget written against it must not move
 * when a serializer does. `dataShapes.test.ts` holds it equal to the served
 * `FieldType`, so the two say the same words without one importing the other.
 */
export type ColumnType = "text" | "number" | "date" | "boolean" | "enum" | "reference";

/** The period a date column is rounded to, when the statement rounded it. */
export type ColumnGrain = "day" | "week" | "month" | "quarter" | "year";

/** One output column: what it is called, and what it holds. */
export interface DataColumn {
  name: string;
  type: ColumnType;
  /** For a date the statement rounded with `date_trunc`, the unit it rounded
   *  to. A chart labels its points by this; absent means a plain date. */
  grain?: ColumnGrain;
  /** A SQL DATE encoded at UTC midnight, whose calendar day is zone independent. */
  date_only?: boolean;
}

/** A cell. Dates are epoch milliseconds, like every other timestamp here. */
export type CellValue = string | number | boolean | null;

/**
 * Columns and rows — what a query returned, or what a sheet range held.
 *
 * The one envelope whose shape the *binding* decides rather than this file. A
 * widget bound to a statement knows only what `columns` says, which is why the
 * columns are described rather than assumed, and why a widget declares the
 * shape it can draw instead of the source it can read.
 *
 * Rows are positional against `columns`, not keyed by name, for the reason
 * `SELECT t.id, p.id` gives: two output columns may share a name, and a mapping
 * would keep one value where the statement returned two.
 */
export interface TabularData {
  source: "rows";
  columns: DataColumn[];
  rows: CellValue[][];
}

/**
 * An installed plug-in's data source, in the two shapes its manifest declared.
 *
 * The one source whose *keys* this build does not describe, and deliberately
 * so: they are the endpoint's own `returns`, and the widget that draws them
 * ships in the same manifest, so the two agree because they were published
 * together. What the proxy does is read the answer through that declaration —
 * the returns holding several become `rows`, read side by side; the ones
 * holding a single value stay whole in `values`, so a total or a reason there
 * is nothing survives an empty set.
 *
 * They are still *data*. The sandbox receives values, and the SceneSpec it has
 * to return has no `html` mark, no raw-string passthrough and no way to name a
 * URL, so a plug-in cannot turn its own rows into rendering.
 */
export interface PluginRows {
  source: "plugin";
  /** One entry per index across the endpoint's `list` returns. */
  rows: Record<string, unknown>[];
  /** The endpoint's single-valued returns, once. */
  values: Record<string, unknown>;
}

/**
 * What the host knows about the rows that the rows themselves cannot say.
 *
 * `total` is the count the viewer's own query matched; `rows` may be a leading
 * slice of it, because the list endpoints answer within a fixed window. A
 * widget that reports a number computed from a slice is reporting a wrong
 * number, so the slice is stated rather than implied — the tile draws it as a
 * chip, and a widget can read it and caption accordingly.
 *
 * Counts here are always *this viewer's*: what the six gates let their session
 * see, never the author's total.
 */
export interface DataMeta {
  total?: number;
  truncated?: boolean;
}

export type WidgetData = (TabularData | PluginRows) & { meta?: DataMeta };

/** What a *binding* may name — as distinct from the envelope it produces. */
export type WidgetSource = "query" | "plugin";

/** Widget-level display options, already validated by the backend against the
 *  primitive's allow-list (`WIDGET_SPECS[...].options`). Values are strings —
 *  the option vocabulary is a flat set of literals on both sides. */
export type WidgetConfig = Record<string, string>;
