/**
 * Bars, lines, areas and slices.
 *
 * The mark specs here are fixed rather than per-chart, so every widget's output
 * reads as one system: thin marks, a hairline solid grid, a 2px gap in the
 * surface color separating touching fills, and labels that appear only where
 * they carry the story. A widget chooses *what* is plotted; it does not get to
 * choose how loud it is drawn.
 *
 * Two of those are worth naming because they are easy to get backwards:
 *
 * - **The gap between touching fills is surface, not a border.** Stacked
 *   segments are separated by a 2px stroke painted in the card color, which is
 *   negative space rendered as a stroke — not an outline around the mark, which
 *   would add ink that is not data.
 * - **Values are labelled selectively or not at all.** A number beside every
 *   point is chaos and goes unread, so the scene can ask for the extremes or
 *   the line's end, and the axis, legend, tooltip and table view carry the rest.
 */

import { useMemo } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatAxisValue, formatTimeBucket, formatValue } from "@/lib/widgets/format";
import type { NumberFormat, SceneNode, SeriesTimeUnit } from "@/lib/widgets/sceneSpec";
import { seriesColor, toneColor } from "@/lib/widgets/tone";

type Node = Extract<SceneNode, { kind: "series" }>;

/** Recharts wants one row per x with a column per series; a scene carries one
 *  list of points per series. Merging on x keeps series aligned even when they
 *  don't cover the same categories.
 *
 *  Within *one* series an x appears once — two points sharing it are two values
 *  for one mark, which a chart cannot draw. The first is kept rather than the
 *  last, so a widget that emits a duplicate cannot replace a value it already
 *  reported; the extra is dropped, which the table view shows identically. */
const toRows = (node: Node) => {
  const byX = new Map<string | number, Record<string, string | number>>();
  const order: (string | number)[] = [];

  node.series.forEach((series, index) => {
    const key = `s${index}`;
    for (const point of series.points) {
      let row = byX.get(point.x);
      if (!row) {
        row = { x: point.x };
        byX.set(point.x, row);
        order.push(point.x);
      }
      if (row[key] === undefined) row[key] = point.y;
    }
  });

  return order.map((x) => byX.get(x) as Record<string, string | number>);
};

const axisProps = {
  stroke: "var(--muted-foreground)",
  fontSize: 12,
  tickLine: false,
  axisLine: false,
} as const;

/** Bars never fill their band — the leftover is the air that keeps a chart from
 *  reading as a wall of blocks. */
const MAX_BAR = 24;
/** The surface gap, painted as a stroke in the card color. */
const GAP = 2;

/**
 * One tooltip listing every series at the hovered x.
 *
 * The value leads and the series name follows — the legend's hierarchy
 * inverted, because a reader who has already found the series wants the number.
 * Identity is a short stroke of the series color rather than a filled box: at
 * this density a swatch is data-weight ink doing a label's job.
 */
function SeriesTooltip({
  active,
  payload,
  label,
  format,
  xTime,
  colors,
}: {
  active?: boolean;
  payload?: { name?: string; value?: number; dataKey?: string }[];
  label?: string | number;
  format?: NumberFormat;
  xTime?: SeriesTimeUnit;
  colors: string[];
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border bg-popover px-2.5 py-2 text-popover-foreground shadow-md">
      <p className="mb-1 font-medium text-xs">
        {xTime && label !== undefined
          ? formatTimeBucket(label, xTime)
          : formatAxisValue(label ?? "", format)}
      </p>
      <ul className="space-y-0.5">
        {payload.map((entry, index) => (
          <li key={entry.dataKey ?? index} className="flex items-center gap-2 text-xs">
            <span
              aria-hidden
              className="h-0.5 w-3 shrink-0 rounded-full"
              style={{ backgroundColor: colors[index] ?? colors[0] }}
            />
            <span className="font-semibold tabular-nums">
              {typeof entry.value === "number" ? formatValue(entry.value, format) : "—"}
            </span>
            <span className="truncate text-muted-foreground">{entry.name}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Which points in a series get a number drawn on them.
 *
 * Direct labels work *because* they are sparing: `extremes` marks the highest
 * and lowest, `end` marks where a line finishes. Anything denser stops being a
 * label and becomes noise, which is why "all" is not a value the scene can ask
 * for.
 */
const labelledIndexes = (values: number[], mode: Node["labels"]): Set<number> => {
  if (!values.length || !mode || mode === "none") return new Set();
  if (mode === "end") return new Set([values.length - 1]);
  let lowest = 0;
  let highest = 0;
  values.forEach((value, index) => {
    if (value < values[lowest]) lowest = index;
    if (value > values[highest]) highest = index;
  });
  return new Set([lowest, highest]);
};

export function SeriesNode({ node }: { node: Node }) {
  const rows = useMemo(() => toRows(node), [node]);
  const names = node.series.map((series, index) => series.name ?? `Series ${index + 1}`);
  const stackId = node.stacked ? "stack" : undefined;

  // Emphasis: one series keeps its color and the rest go to the de-emphasis
  // gray. Color still follows the entity — the emphasized index is a property
  // of the scene, not of the current sort order — so filtering never repaints
  // the survivors.
  const colors = node.series.map((series, index) =>
    node.emphasis !== undefined && node.emphasis !== index
      ? toneColor("muted")
      : seriesColor(index, series.tone)
  );

  // Recharts hands its callbacks loosely-typed values, so these take `unknown`
  // and narrow, rather than asserting a shape the library does not promise.
  const tickFormatter = (value: unknown) =>
    typeof value === "string" || typeof value === "number"
      ? formatAxisValue(value, node.format)
      : "";
  // The category axis: a moment at the series' grain when x is a time, and
  // otherwise the same formatting as the values.
  const xFormatter = (value: unknown) =>
    node.xTime && (typeof value === "string" || typeof value === "number")
      ? formatTimeBucket(value, node.xTime)
      : tickFormatter(value);

  if (!rows.length) return null;

  /** A label list for one series, or nothing when the scene asked for none. */
  const labelsFor = (index: number) => {
    const values = node.series[index].points.map((point) => point.y);
    const wanted = labelledIndexes(values, node.labels);
    if (!wanted.size) return null;
    return (
      <LabelList
        dataKey={`s${index}`}
        position={node.horizontal ? "right" : "top"}
        fontSize={11}
        // Values wear a text token; the colored mark beside them carries
        // identity. A light categorical hue is illegible as text.
        fill="var(--muted-foreground)"
        // Only the points the mode asked for. The rest return undefined, which
        // draws nothing rather than an empty label box.
        valueAccessor={(entry: unknown, position: number) =>
          wanted.has(position)
            ? formatValue((entry as { value?: number })?.value ?? 0, node.format)
            : undefined
        }
      />
    );
  };

  const tooltip = (
    <Tooltip
      cursor={{ fill: "var(--muted)", fillOpacity: 0.4 }}
      content={<SeriesTooltip format={node.format} xTime={node.xTime} colors={colors} />}
    />
  );

  // A pie shows a single series as parts of a whole; extra series have no
  // meaning in that shape, so only the first is drawn.
  if (node.mark === "pie") {
    const slices = node.series[0]?.points ?? [];
    return (
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          {tooltip}
          {node.showLegend && <Legend wrapperStyle={{ fontSize: 11 }} />}
          <Pie
            data={slices.map((point) => ({
              name: node.xTime ? formatTimeBucket(point.x, node.xTime) : String(point.x),
              value: point.y,
            }))}
            dataKey="value"
            nameKey="name"
            innerRadius="45%"
            outerRadius="80%"
          >
            {slices.map((point, index) => (
              <Cell
                key={String(point.x)}
                fill={seriesColor(index)}
                // The gap between slices is the surface showing through, the
                // same 2px every other touching fill gets.
                stroke="var(--card)"
                strokeWidth={GAP}
              />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
    );
  }

  const grid = (
    <CartesianGrid
      stroke="var(--border)"
      vertical={node.horizontal}
      horizontal={!node.horizontal}
    />
  );
  const legend = node.showLegend ? <Legend wrapperStyle={{ fontSize: 11 }} /> : null;
  const target =
    node.target === undefined ? null : (
      <ReferenceLine
        {...(node.horizontal ? { x: node.target } : { y: node.target })}
        stroke="var(--muted-foreground)"
        strokeWidth={1}
        label={
          node.targetLabel
            ? { value: node.targetLabel, position: "insideTopRight", fontSize: 11 }
            : undefined
        }
      />
    );

  if (node.mark === "line" || node.mark === "area") {
    const Chart = node.mark === "line" ? LineChart : AreaChart;
    return (
      <ResponsiveContainer width="100%" height="100%">
        <Chart data={rows}>
          {grid}
          <XAxis dataKey="x" {...axisProps} tickFormatter={xFormatter} />
          <YAxis {...axisProps} width={44} tickFormatter={tickFormatter} />
          {tooltip}
          {legend}
          {target}
          {node.series.map((series, index) =>
            node.mark === "line" ? (
              <Line
                key={names[index]}
                type="monotone"
                dataKey={`s${index}`}
                name={names[index]}
                stroke={colors[index]}
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
                dot={false}
                // The end marker carries a surface ring so it stays legible
                // where lines cross.
                activeDot={{ r: 4, strokeWidth: GAP, stroke: "var(--card)" }}
              >
                {labelsFor(index)}
              </Line>
            ) : (
              <Area
                key={names[index]}
                type="monotone"
                dataKey={`s${index}`}
                name={names[index]}
                stackId={stackId}
                stroke={colors[index]}
                strokeWidth={2}
                fill={colors[index]}
                fillOpacity={0.1}
                activeDot={{ r: 4, strokeWidth: GAP, stroke: "var(--card)" }}
              >
                {labelsFor(index)}
              </Area>
            )
          )}
        </Chart>
      </ResponsiveContainer>
    );
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={rows} layout={node.horizontal ? "vertical" : "horizontal"}>
        {grid}
        {node.horizontal ? (
          <>
            <XAxis type="number" {...axisProps} tickFormatter={tickFormatter} />
            <YAxis
              type="category"
              dataKey="x"
              {...axisProps}
              width={96}
              tickFormatter={node.xTime ? xFormatter : undefined}
            />
          </>
        ) : (
          <>
            <XAxis dataKey="x" {...axisProps} tickFormatter={xFormatter} />
            <YAxis {...axisProps} width={44} tickFormatter={tickFormatter} />
          </>
        )}
        {tooltip}
        {legend}
        {target}
        {node.series.map((series, index) => (
          <Bar
            key={names[index]}
            dataKey={`s${index}`}
            name={names[index]}
            stackId={stackId}
            fill={colors[index]}
            maxBarSize={MAX_BAR}
            // Rounded at the data end, square at the baseline.
            radius={node.horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]}
            // Surface-colored separation between touching fills — the stacked
            // segments here, and neighbouring bars at dense category counts.
            stroke="var(--card)"
            strokeWidth={stackId ? GAP : 0}
            activeBar={{ fillOpacity: 0.85 }}
          >
            {labelsFor(index)}
          </Bar>
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}
