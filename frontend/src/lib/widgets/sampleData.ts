/**
 * Sample rows, in the one shape `dataShapes.ts` documents.
 *
 * Ships with the app rather than living beside the tests, because the widget
 * picker previews every widget by *running* it — the same sandbox, validator
 * and renderer a live tile uses, over these rows. So someone choosing a widget
 * sees the real thing before adding it, and the widget tests exercise the same
 * contract the previews do.
 *
 * One sample per *shape*, not per source. A widget draws columns now, so what a
 * preview needs is a set of columns its slots can be filled from — and two
 * widgets that draw the same shape can honestly share one.
 *
 * Frozen values throughout: the sandbox has a frozen clock, so the samples get
 * a frozen calendar and a preview renders identically every time.
 */

import type { TabularData } from "./dataShapes";

const DAY = 86_400_000;
/** A fixed anchor. Live tiles never use this; the host hands them the real
 *  minute. */
export const SAMPLE_NOW = Date.UTC(2026, 7, 3);
const T0 = SAMPLE_NOW;

const rows = (columns: TabularData["columns"], body: TabularData["rows"]): TabularData => ({
  source: "rows",
  columns,
  rows: body,
});

/** A label and a count — the shape most tiles want, and the one a `GROUP BY`
 *  produces. Stages read widest to narrowest so a funnel has something to be. */
const labelled = rows(
  [
    { name: "stage", type: "text" },
    { name: "tasks", type: "number" },
  ],
  [
    ["Backlog", 42],
    ["In progress", 18],
    ["In review", 9],
    ["Done", 31],
  ]
);

/** A label and two measures — a part against a whole, which is what a progress
 *  bar and a stacked chart both read. */
const parts = rows(
  [
    { name: "project", type: "text" },
    { name: "done", type: "number" },
    { name: "total", type: "number" },
  ],
  [
    ["Website relaunch", 14, 20],
    ["Mobile app", 6, 25],
    ["Data migration", 19, 19],
  ]
);

/** A day and a count. Only this shape has a calendar to place values on, which
 *  is what a heatmap needs. */
const overTime = rows(
  [
    { name: "day", type: "date" },
    { name: "completed", type: "number" },
  ],
  Array.from({ length: 21 }, (_, index) => [
    T0 - (20 - index) * DAY,
    [0, 1, 3, 2, 5, 8, 4][index % 7],
  ])
);

/** A label and a span. Work with a start and an end, which is a timeline. */
const spans = rows(
  [
    { name: "task", type: "text" },
    { name: "starts", type: "date" },
    { name: "ends", type: "date" },
    { name: "status", type: "text" },
  ],
  [
    ["Design review", T0 - 12 * DAY, T0 - 5 * DAY, "Done"],
    ["Build the importer", T0 - 6 * DAY, T0 + 4 * DAY, "In progress"],
    ["Write the migration", T0 - 2 * DAY, T0 + 9 * DAY, "In progress"],
    ["Ship it", T0 + 8 * DAY, T0 + 11 * DAY, "Backlog"],
  ]
);

/** Cards with a column to sit in, and a date to be late by. */
const cards = rows(
  [
    { name: "task", type: "text" },
    { name: "status", type: "text" },
    { name: "due", type: "date" },
  ],
  [
    ["Draft the brief", "Backlog", T0 + 3 * DAY],
    ["Wire the endpoint", "In progress", T0 - 1 * DAY],
    ["Review the copy", "In progress", T0 + 6 * DAY],
    ["Publish", "Done", T0 - 4 * DAY],
  ]
);

/** Which sample previews each widget. Keyed by the shape the widget declares,
 *  which is why several share one. */
const BY_WIDGET: Record<string, TabularData> = {
  gantt: spans,
  board: cards,
  heatmap: overTime,
  progress: parts,
  chart: labelled,
  funnel: labelled,
  stat: labelled,
  table: parts,
};

/** The samples, for a test that wants to run every widget over every shape. */
export const ALL_SAMPLES: TabularData[] = [labelled, parts, overTime, spans, cards];

/**
 * Sample rows for a widget.
 *
 * Total on purpose: the picker previews whatever the *served* catalog offers, so
 * a widget this build has no sample for previews as an empty tile rather than
 * taking the dialog down with it.
 */
export const sampleFor = (widgetType?: string): TabularData =>
  (widgetType && BY_WIDGET[widgetType]) || labelled;
