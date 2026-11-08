import { ChevronRight } from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { formatValue } from "@/lib/widgets/format";
import type { SceneNode, TimelineSpan } from "@/lib/widgets/sceneSpec";
import {
  type AxisSegment,
  type AxisTick,
  axisTicks,
  type FlatLane,
  flattenLanes,
  majorSegments,
  positionIn,
  type TimelineRange,
  type TimeUnit,
  timelineWindow,
  weekendBands,
  weekStartDay,
} from "@/lib/widgets/timelineAxis";
import { toneColor } from "@/lib/widgets/tone";
import { dateTimeFormat } from "@/ui/lib/intl";
import { cn } from "@/ui/lib/utils";

type Node = Extract<SceneNode, { kind: "timeline" }>;

/** The task grid down the left. Fixed rather than measured: a Gantt is floored
 *  at six grid columns, and a proportional gutter would shrink to nothing on the
 *  narrowest tile the canvas allows. */
const LANE_LABEL_WIDTH = 168;
const ROW_HEIGHT = 26;
const INDENT = 12;
/** Below this share of the window a bar has no room for a read-out beside it,
 *  so the number lives only in the row's caption and its tooltip. */
const MIN_WIDTH_FOR_CAPTION = 8;

/**
 * Spans on a shared time axis — the Gantt shape.
 *
 * Drawn with positioned divs over a percentage-based axis so it reflows with the
 * tile instead of needing a measured width, and layered so the chart reads the
 * way a Gantt is expected to: non-working days shaded behind everything, the
 * gridlines and the current-date line over that, then the bars.
 *
 * Four span shapes, because they mean four different things — a block of work, a
 * bracket rolling up everything folded beneath it, a diamond for a dated instant
 * with no duration, and a ghost of what was originally planned under work that
 * landed somewhere else.
 *
 * Times arrive as epoch milliseconds and are resolved here, in the viewer's
 * locale and timezone — the widget that produced them had neither, which is also
 * why "now" rides in on the node instead of being read from this side's clock.
 */
export function TimelineNode({ node }: { node: Node }) {
  const { t, i18n } = useTranslation(["dashboards", "common"]);
  const locale = i18n.language;

  const weekStart = useMemo(() => weekStartDay(locale), [locale]);
  const unit: TimeUnit = node.scale ?? "week";
  const range = useMemo(() => timelineWindow(node, weekStart), [node, weekStart]);
  const ticks = useMemo(() => axisTicks(range, unit, weekStart), [range, unit, weekStart]);
  const major = useMemo(() => majorSegments(range, unit, weekStart), [range, unit, weekStart]);
  // Only worth painting where a single day is still a visible column; over a
  // year of quarters the stripes would be the chart.
  const bands = useMemo(
    () => (unit === "day" || unit === "week" ? weekendBands(range) : []),
    [range, unit]
  );

  // Which lanes are open is the reader's, not the widget's: the scene says what
  // a lane *starts* as, and this records every click since. Keyed by position in
  // the tree because lane labels repeat.
  const [folds, setFolds] = useState<Record<string, boolean>>({});
  const rows = useMemo(
    () => flattenLanes(node.lanes, (path, lane) => folds[path] ?? !lane.collapsed),
    [node.lanes, folds]
  );
  const toggle = useCallback((path: string, open: boolean) => {
    setFolds((current) => ({ ...current, [path]: !open }));
  }, []);

  // Roving focus across the rows, which is what makes a treegrid navigable
  // without a mouse: one row is in the tab order and the arrow keys move it.
  const body = useRef<HTMLTableSectionElement>(null);
  const [focused, setFocused] = useState(0);
  const current = Math.min(focused, Math.max(0, rows.length - 1));
  // Folding changes which rows exist, so a focus that pointed past the end has
  // to come back inside rather than leave the table untabbable.
  if (focused !== current) setFocused(current);

  const focusRow = useCallback((index: number) => {
    const row = body.current?.querySelectorAll("tr")[index];
    if (row) {
      setFocused(index);
      row.focus();
    }
  }, []);

  const onKeyDown = (event: React.KeyboardEvent<HTMLTableSectionElement>) => {
    const row = rows[current];
    if (!row) return;
    switch (event.key) {
      case "ArrowDown":
        focusRow(Math.min(current + 1, rows.length - 1));
        break;
      case "ArrowUp":
        focusRow(Math.max(current - 1, 0));
        break;
      case "Home":
        focusRow(0);
        break;
      case "End":
        focusRow(rows.length - 1);
        break;
      case "ArrowRight":
        // Open a shut group, then step into it — the ordinary tree gesture.
        if (row.hasChildren && !row.expanded) toggle(row.path, false);
        else if (row.expanded) focusRow(current + 1);
        else return;
        break;
      case "ArrowLeft": {
        if (row.expanded) {
          toggle(row.path, true);
          break;
        }
        // Otherwise climb: the nearest row above sitting a level shallower.
        let parent = -1;
        for (let index = current - 1; index >= 0; index--) {
          if (rows[index].depth < row.depth) {
            parent = index;
            break;
          }
        }
        if (parent < 0) return;
        focusRow(parent);
        break;
      }
      default:
        return;
    }
    event.preventDefault();
  };

  const at = (value: number) => positionIn(range, value);
  const nowInside = node.now !== undefined && node.now >= range.start && node.now <= range.end;
  const nowAt = nowInside && node.now !== undefined ? at(node.now) : undefined;

  const date = (value: number) => formatValue(value, "date", { locale });

  const tickLabel = (tick: AxisTick): string => {
    const when = new Date(tick.at);
    switch (tick.unit) {
      case "day":
        return dateTimeFormat(locale, { day: "numeric" }).format(when);
      case "month":
        return dateTimeFormat(locale, { month: "short" }).format(when);
      case "quarter":
        return t("timeline.quarter", { quarter: Math.floor(when.getMonth() / 3) + 1 });
      case "year":
        return dateTimeFormat(locale, { year: "numeric" }).format(when);
      default:
        return dateTimeFormat(locale, { month: "short", day: "numeric" }).format(when);
    }
  };

  const segmentLabel = (segment: AxisSegment): string =>
    dateTimeFormat(
      locale,
      major.unit === "year" ? { year: "numeric" } : { month: "long", year: "numeric" }
    ).format(new Date(segment.at));

  return (
    <div className="flex h-full w-full flex-col overflow-hidden text-xs">
      {/* Two-tier header: the coarser unit over its own divisions, so a column
          of bare day numbers still says which month it is in. */}
      <div className="flex shrink-0 border-b">
        <div className="shrink-0" style={{ width: LANE_LABEL_WIDTH }} />
        <div className="relative h-9 flex-1 overflow-hidden">
          {major.segments.map((segment) => (
            <div
              key={segment.at}
              className="absolute top-0 h-4 truncate border-l px-1 font-medium text-3xs text-muted-foreground leading-4"
              style={{
                left: `${at(segment.start)}%`,
                width: `${at(segment.end) - at(segment.start)}%`,
              }}
            >
              {segmentLabel(segment)}
            </div>
          ))}
          {ticks.map((tick) => (
            <div
              key={tick.at}
              className="absolute bottom-1 truncate px-1 text-3xs text-muted-foreground"
              style={{ left: `${at(tick.at)}%` }}
            >
              {tickLabel(tick)}
            </div>
          ))}
          {nowAt !== undefined && (
            <div
              className="absolute bottom-0 -translate-x-1/2 whitespace-nowrap rounded-sm bg-primary px-1 font-medium text-3xs text-primary-foreground leading-4"
              style={{ left: `${nowAt}%` }}
            >
              {t("common:calendar.today")}
            </div>
          )}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="relative min-w-full">
          {/* Behind every row and pointer-transparent, so the chart's context
              never intercepts a click meant for a bar. */}
          <div
            className="pointer-events-none absolute inset-y-0 right-0"
            style={{ left: LANE_LABEL_WIDTH }}
            aria-hidden
          >
            {bands.map((band) => (
              <div
                key={band.start}
                className="absolute inset-y-0 bg-muted/50"
                style={{
                  left: `${at(band.start)}%`,
                  width: `${at(band.end) - at(band.start)}%`,
                }}
              />
            ))}
            {ticks.map((tick) => (
              <div
                key={tick.at}
                className="absolute inset-y-0 w-px bg-border/60"
                style={{ left: `${at(tick.at)}%` }}
              />
            ))}
            {nowAt !== undefined && (
              <div className="absolute inset-y-0 w-px bg-primary" style={{ left: `${nowAt}%` }} />
            )}
          </div>

          {/* A real table, because the rows are a work breakdown with columns.
              `treegrid` is what names the folding for a reader who cannot see
              the indent, and it is the role ARIA defines for a table whose rows
              expand — the pattern the W3C's own guidance points at Gantt
              charts. */}
          <table
            className="w-full table-fixed border-collapse"
            // biome-ignore lint/a11y/noNoninteractiveElementToInteractiveRole: a table is treegrid's documented host element, and the rows below carry the focus management the role implies
            role="treegrid"
            aria-label={t("timeline.label")}
          >
            <tbody ref={body} onKeyDown={onKeyDown}>
              {rows.map((row, index) => (
                <LaneRow
                  key={row.path}
                  row={row}
                  range={range}
                  focused={index === current}
                  onFocus={() => setFocused(index)}
                  onToggle={toggle}
                  formatDate={date}
                />
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

interface LaneRowProps {
  row: FlatLane;
  range: TimelineRange;
  onToggle: (path: string, open: boolean) => void;
  formatDate: (value: number) => string;
  /** The one row in the tab order — the rest are reached with the arrow keys. */
  focused: boolean;
  onFocus: () => void;
}

function LaneRow({ row, range, onToggle, formatDate, focused, onFocus }: LaneRowProps) {
  // Its own hook rather than a `t` handed down: the namespace binding is what
  // types the keys, and it does not survive being passed as a prop.
  const { t } = useTranslation("dashboards");
  const { lane, depth, hasChildren, expanded } = row;
  const label = lane.label ?? "";

  return (
    <tr
      aria-level={depth + 1}
      aria-posinset={row.position}
      aria-setsize={row.setSize}
      aria-expanded={hasChildren ? expanded : undefined}
      tabIndex={focused ? 0 : -1}
      onFocus={onFocus}
      className="border-border/40 border-b outline-none last:border-b-0 hover:bg-muted/30 focus-visible:bg-muted/50 focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-inset"
      style={{ height: ROW_HEIGHT }}
    >
      <th scope="row" className="p-0 text-left font-normal" style={{ width: LANE_LABEL_WIDTH }}>
        <div className="flex items-center gap-1 pr-2" style={{ paddingLeft: 4 + depth * INDENT }}>
          {hasChildren ? (
            <button
              type="button"
              onClick={() => onToggle(row.path, expanded)}
              className="-m-0.5 shrink-0 rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label={
                expanded
                  ? t("timeline.collapse", { name: label })
                  : t("timeline.expand", { name: label })
              }
            >
              <ChevronRight
                className={cn("h-3 w-3 transition-transform", expanded && "rotate-90")}
                aria-hidden
              />
            </button>
          ) : (
            <span className="w-3 shrink-0" aria-hidden />
          )}
          <span
            className={cn(
              "min-w-0 flex-1 truncate",
              hasChildren ? "font-medium" : "text-muted-foreground"
            )}
            title={label}
          >
            {label}
          </span>
          {lane.caption && (
            <span className="shrink-0 text-3xs text-muted-foreground tabular-nums">
              {lane.caption}
            </span>
          )}
        </div>
      </th>

      <td className="relative p-0">
        {lane.spans.map((span, index) => (
          <SpanMark
            // biome-ignore lint/suspicious/noArrayIndexKey: two spans may share a start time, so position is the identity
            key={`${span.start}-${index}`}
            span={span}
            range={range}
            formatDate={formatDate}
          />
        ))}
      </td>
    </tr>
  );
}

interface SpanMarkProps {
  span: TimelineSpan;
  range: TimelineRange;
  formatDate: (value: number) => string;
}

/** One bar, bracket, or diamond, with whatever belongs beside it. */
function SpanMark({ span, range, formatDate }: SpanMarkProps) {
  const color = toneColor(span.tone);
  const left = positionIn(range, span.start);
  const right = positionIn(range, span.end);
  const width = Math.max(0.4, right - left);
  const progress =
    span.progress === undefined ? undefined : Math.min(1, Math.max(0, span.progress));

  const percent = progress === undefined ? undefined : `${Math.round(progress * 100)}%`;
  const tooltip = [span.label, `${formatDate(span.start)} → ${formatDate(span.end)}`, percent]
    .filter(Boolean)
    .join(" · ");

  // A summary's own read-out is its percentage; a leaf bar's is whatever the
  // widget put there (an owner, a count). Only shown where the bar leaves room.
  const beside = span.kind === "summary" ? percent : span.caption;
  const showBeside = beside !== undefined && width >= MIN_WIDTH_FOR_CAPTION;

  if (span.kind === "milestone") {
    return (
      <>
        <div
          className="absolute top-1/2 h-2.5 w-2.5"
          style={{
            left: `${left}%`,
            backgroundColor: color,
            transform: "translate(-50%, -50%) rotate(45deg)",
          }}
          title={tooltip}
        />
        {span.label && (
          <span
            className="absolute top-1/2 -translate-y-1/2 whitespace-nowrap pl-2 text-3xs text-muted-foreground"
            style={{ left: `${left}%` }}
          >
            {span.label}
          </span>
        )}
      </>
    );
  }

  if (span.kind === "summary") {
    return (
      <>
        <div
          className="absolute top-1/2 -translate-y-1/2"
          style={{ left: `${left}%`, width: `${width}%` }}
        >
          <div className="relative h-1.5">
            <div
              className="absolute inset-0 rounded-sm"
              style={{ backgroundColor: color, opacity: 0.25 }}
            />
            {progress !== undefined && (
              <div
                className="absolute inset-y-0 left-0 rounded-sm"
                style={{ width: `${progress * 100}%`, backgroundColor: color }}
                title={tooltip}
              />
            )}
          </div>
          {/* The downward caps that make a bracket read as "everything under
              me" rather than as another task bar. */}
          <span className="absolute top-1.5 left-0" style={capStyle(color)} aria-hidden />
          <span className="absolute top-1.5 right-0" style={capStyle(color)} aria-hidden />
        </div>
        {showBeside && (
          <span
            className="absolute top-1/2 -translate-y-1/2 whitespace-nowrap pl-1.5 font-medium text-3xs text-muted-foreground tabular-nums"
            style={{ left: `${right}%` }}
          >
            {beside}
          </span>
        )}
      </>
    );
  }

  return (
    <>
      {span.baseline && (
        <div
          className="absolute bottom-1 h-[3px] rounded-full opacity-40"
          style={{
            left: `${positionIn(range, span.baseline.start)}%`,
            width: `${Math.max(
              0.4,
              positionIn(range, span.baseline.end) - positionIn(range, span.baseline.start)
            )}%`,
            backgroundColor: "var(--muted-foreground)",
          }}
          title={`${formatDate(span.baseline.start)} → ${formatDate(span.baseline.end)}`}
        />
      )}
      <div
        className={cn(
          "absolute top-1/2 h-3 -translate-y-1/2 overflow-hidden rounded-sm",
          span.baseline && "-mt-1"
        )}
        style={{ left: `${left}%`, width: `${width}%` }}
        title={tooltip}
      >
        <div className="absolute inset-0" style={{ backgroundColor: color, opacity: 0.25 }} />
        {progress !== undefined && progress > 0 && (
          <div
            className="absolute inset-y-0 left-0"
            style={{ width: `${progress * 100}%`, backgroundColor: color }}
          />
        )}
      </div>
      {showBeside && (
        <span
          className={cn(
            "absolute top-1/2 -translate-y-1/2 whitespace-nowrap pl-1.5 text-3xs text-muted-foreground",
            span.baseline && "-mt-1"
          )}
          style={{ left: `${right}%` }}
        >
          {beside}
        </span>
      )}
    </>
  );
}

/** The triangular end cap on a summary bracket, drawn with borders so it stays
 *  a plain style value. */
const capStyle = (color: string): React.CSSProperties => ({
  width: 0,
  height: 0,
  borderLeft: "3px solid transparent",
  borderRight: "3px solid transparent",
  borderTop: `4px solid ${color}`,
});
