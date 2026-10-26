/**
 * A sketch of each tool, for somebody who has never seen one.
 *
 * The create wizard asks "what is this initiative made of?" of people on their
 * first minute in the app, and a name plus a sentence is not enough to answer
 * it — "queue" and "counter" mean nothing until you have seen one. So each
 * card carries a small picture of the screen it is standing in for, drawn from
 * what that screen actually renders: the queue's numbered rows with a "current
 * turn" pill and an avatar, the counter's [−] value [+] in its number, bar and
 * ring forms, the calendar's weekday header over a month of cells with event
 * chips that run across days.
 *
 * Shapes, not screenshots: it has to read at thumbnail size and in either
 * theme, and it must never look like a real screen somebody could try to
 * click. Every sketch is drawn in the same three inks and sits in the same
 * frame, so the grid reads as one set.
 *
 * Keyed by Tool so `tools.test.ts` catches a new tool that arrives without a
 * sketch, the same way it catches one without an icon.
 */

import { Minus, Plus } from "lucide-react";
import type { ReactNode } from "react";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { TOOL_ICONS } from "@/lib/tools";
import { cn } from "@/lib/utils";

interface SketchProps {
  /** Whether the tool is ticked — the sketch brightens to match the card. */
  active: boolean;
}

/** The inks every sketch is drawn in: a strong one, a faint one, and a second
 *  hue for the things a real screen colours differently (event chips, tags). */
const ink = (active: boolean) => (active ? "bg-primary/60" : "bg-muted-foreground/30");
const faint = (active: boolean) => (active ? "bg-primary/20" : "bg-muted-foreground/12");
const accent = (active: boolean) => (active ? "bg-amber-400/70" : "bg-muted-foreground/25");
const line = (active: boolean) => (active ? "border-primary/30" : "border-muted-foreground/20");

/** Fixed shape lists, keyed on their element rather than a map index. */
const BOARD_COLUMNS = [
  { id: "todo", cards: ["a", "b", "c"] },
  { id: "doing", cards: ["a", "b"] },
  { id: "done", cards: ["a"] },
] as const;
const TOOLBAR_GROUPS = [
  { id: "style", buttons: ["b", "i", "u"] },
  { id: "block", buttons: ["h", "q"] },
  { id: "list", buttons: ["ul", "ol"] },
] as const;
const WEEKDAYS = ["m", "t", "w", "th", "f", "s", "su"] as const;
const MONTH_DAYS = Array.from({ length: 28 }, (_, i) => i + 1);
const TODAY = 10;
/** Event chips as (day, span, hue) — one runs across three days. */
const EVENTS = [
  { id: "standup", day: 3, span: 1, tone: ink },
  { id: "offsite", day: 9, span: 3, tone: accent },
  { id: "review", day: 17, span: 1, tone: ink },
  { id: "launch", day: 24, span: 2, tone: accent },
] as const;
const QUEUE_ROWS = [
  { id: "first", position: "1", current: true },
  { id: "second", position: "2", current: false },
  { id: "third", position: "3", current: false },
] as const;
const CHART_BARS = [
  { id: "q1", height: 40 },
  { id: "q2", height: 70 },
  { id: "q3", height: 55 },
  { id: "q4", height: 90 },
] as const;
const CATALOG_TILES = [
  { id: "p1", tall: true, tone: ink },
  { id: "p2", tall: false, tone: faint },
  { id: "p3", tall: false, tone: accent },
  { id: "p4", tall: false, tone: faint },
  { id: "p5", tall: true, tone: faint },
  { id: "p6", tall: false, tone: ink },
] as const;

const Frame = ({ children }: { children: ReactNode }) => (
  <div
    aria-hidden="true"
    className="h-24 w-full overflow-hidden rounded-md border border-border/60 bg-background/70 p-2"
  >
    {children}
  </div>
);

/** A tiny round face, the way every people-shaped screen draws one. */
const Avatar = ({ active, size = "h-3.5 w-3.5" }: SketchProps & { size?: string }) => (
  <div className={cn("shrink-0 rounded-full", size, faint(active), "ring-1", line(active))} />
);

/** The board: three status columns, each with a coloured dot, a count, and
 *  cards carrying a title, a tag and an assignee. */
const ProjectSketch = ({ active }: SketchProps) => (
  <Frame>
    <div className="flex h-full gap-1.5">
      {BOARD_COLUMNS.map((column, columnIndex) => (
        <div key={column.id} className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex items-center gap-1">
            <div
              className={cn(
                "h-1.5 w-1.5 rounded-full",
                columnIndex === 1 ? accent(active) : ink(active)
              )}
            />
            <div className={cn("h-1 flex-1 rounded-sm", ink(active))} />
            <div className={cn("h-1.5 w-2 rounded-sm", faint(active))} />
          </div>
          {column.cards.map((card) => (
            <div
              key={card}
              className={cn(
                "flex flex-col gap-1 rounded-sm border p-1",
                line(active),
                faint(active)
              )}
            >
              <div className={cn("h-1 w-5/6 rounded-sm", ink(active))} />
              <div className="flex items-center justify-between">
                <div className={cn("h-1 w-1/3 rounded-full", accent(active))} />
                <Avatar active={active} size="h-2 w-2" />
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  </Frame>
);

/** The editor: a toolbar in button groups, a heading, paragraph lines and a
 *  bulleted list. */
const FileSketch = ({ active }: SketchProps) => (
  <Frame>
    <div className="flex h-full flex-col gap-1.5">
      <div className="flex items-center gap-1.5">
        {TOOLBAR_GROUPS.map((group, groupIndex) => (
          <div key={group.id} className="flex items-center gap-1">
            {groupIndex > 0 ? <div className={cn("h-3 w-px", ink(active))} /> : null}
            {group.buttons.map((button) => (
              <div key={button} className={cn("h-2.5 w-2.5 rounded-sm", ink(active))} />
            ))}
          </div>
        ))}
      </div>
      <div className={cn("mt-0.5 h-2 w-1/2 rounded-sm", ink(active))} />
      <div className={cn("h-1 w-full rounded-sm", faint(active))} />
      <div className={cn("h-1 w-11/12 rounded-sm", faint(active))} />
      <div className="mt-0.5 flex flex-col gap-1 pl-1">
        {(["one", "two"] as const).map((bullet) => (
          <div key={bullet} className="flex items-center gap-1.5">
            <div className={cn("h-1 w-1 rounded-full", ink(active))} />
            <div
              className={cn("h-1 rounded-sm", faint(active), bullet === "one" ? "w-2/3" : "w-1/2")}
            />
          </div>
        ))}
      </div>
    </div>
  </Frame>
);

/** The month: a weekday header over four weeks of cells, each with its day
 *  number, today ringed, and event chips — one of them running across days. */
const CalendarSketch = ({ active }: SketchProps) => (
  <Frame>
    <div className="flex h-full flex-col gap-0.5">
      <div className="grid grid-cols-7 gap-px">
        {WEEKDAYS.map((weekday) => (
          <div key={weekday} className="flex justify-center">
            <div className={cn("h-1 w-2 rounded-sm", ink(active))} />
          </div>
        ))}
      </div>
      <div className={cn("relative grid flex-1 grid-cols-7 gap-px rounded-sm", faint(active))}>
        {MONTH_DAYS.map((day) => (
          <div
            key={day}
            className={cn(
              "relative bg-background/80 p-0.5",
              day === TODAY &&
                cn("ring-1 ring-inset", active ? "ring-primary" : "ring-muted-foreground/50")
            )}
          >
            <div
              className={cn("h-1 w-1 rounded-sm", day === TODAY ? ink(active) : faint(active))}
            />
          </div>
        ))}
        {EVENTS.map((event) => {
          const row = Math.floor((event.day - 1) / 7);
          const col = (event.day - 1) % 7;
          return (
            <div
              key={event.id}
              className={cn("absolute h-1.5 rounded-sm", event.tone(active))}
              style={{
                top: `calc(${row} * 25% + 9px)`,
                left: `calc(${col} / 7 * 100% + 2px)`,
                width: `calc(${event.span} / 7 * 100% - 4px)`,
              }}
            />
          );
        })}
      </div>
    </div>
  </Frame>
);

/** The queue: numbered rows, each a name over who holds it and an avatar at
 *  the end, with the current turn lit and pinned by its pill. */
const QueueSketch = ({ active }: SketchProps) => (
  <Frame>
    <div className="flex h-full flex-col justify-between">
      {QUEUE_ROWS.map((row) => (
        <div
          key={row.id}
          className={cn(
            "flex items-center gap-1.5 rounded-sm border px-1 py-0.5",
            row.current ? cn(line(active), faint(active)) : "border-transparent"
          )}
        >
          <div
            className={cn(
              "h-2 w-2 rounded-sm text-center",
              row.current ? ink(active) : faint(active)
            )}
          />
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <div className="flex items-center gap-1">
              <div
                className={cn(
                  "h-1.5 rounded-sm",
                  row.current ? ink(active) : faint(active),
                  "w-1/2"
                )}
              />
              {row.current ? <div className={cn("h-1.5 w-5 rounded-full", ink(active))} /> : null}
            </div>
            <div className={cn("h-1 w-1/3 rounded-sm", faint(active))} />
          </div>
          <Avatar active={active} />
        </div>
      ))}
    </div>
  </Frame>
);

/** Counters: a minus on the left, a plus on the right, the number in the
 *  middle — the row exactly as the tool draws it — over the bar it fills. */
const CounterGroupSketch = ({ active }: SketchProps) => (
  <Frame>
    <div className="flex h-full flex-col justify-between">
      <div className={cn("h-1.5 w-1/3 rounded-sm", ink(active))} />
      <div className="flex items-center justify-between gap-2 px-1">
        <div
          className={cn(
            "flex h-6 w-6 shrink-0 items-center justify-center rounded-md border",
            line(active),
            faint(active),
            active ? "text-primary" : "text-muted-foreground"
          )}
        >
          <Minus className="h-3.5 w-3.5" strokeWidth={3} />
        </div>
        <div
          className={cn(
            "font-bold font-mono text-2xl tabular-nums leading-none",
            active ? "text-primary" : "text-muted-foreground/70"
          )}
        >
          24
        </div>
        <div
          className={cn(
            "flex h-6 w-6 shrink-0 items-center justify-center rounded-md border",
            line(active),
            faint(active),
            active ? "text-primary" : "text-muted-foreground"
          )}
        >
          <Plus className="h-3.5 w-3.5" strokeWidth={3} />
        </div>
      </div>
      <div className={cn("h-2 w-full overflow-hidden rounded-full", faint(active))}>
        <div className={cn("h-full w-3/5 rounded-full", accent(active))} />
      </div>
    </div>
  </Frame>
);

/** The dashboard: a bar chart, a sparkline, a big number and a donut. */
const DashboardSketch = ({ active }: SketchProps) => (
  <Frame>
    <div className="grid h-full grid-cols-2 gap-1">
      <div className={cn("flex items-end gap-0.5 rounded-sm p-1", faint(active))}>
        {CHART_BARS.map((bar) => (
          <div
            key={bar.id}
            className={cn("flex-1 rounded-[1px]", ink(active))}
            style={{ height: `${bar.height}%` }}
          />
        ))}
      </div>
      <div className={cn("rounded-sm p-1", faint(active))}>
        <svg viewBox="0 0 40 16" className="h-full w-full" preserveAspectRatio="none">
          <polyline
            points="0,13 8,9 16,11 24,5 32,7 40,2"
            fill="none"
            strokeWidth="2"
            className={active ? "stroke-primary/70" : "stroke-muted-foreground/40"}
          />
        </svg>
      </div>
      <div className={cn("flex flex-col justify-center gap-1 rounded-sm p-1", faint(active))}>
        <div className={cn("h-3.5 w-2/3 rounded-sm", ink(active))} />
        <div className={cn("h-1 w-1/2 rounded-sm", accent(active))} />
      </div>
      <div className={cn("flex items-center justify-center rounded-sm p-1", faint(active))}>
        <div
          className={cn(
            "h-6 w-6 rounded-full border-4",
            active ? "border-primary/60 border-r-amber-400/70" : "border-muted-foreground/30"
          )}
        />
      </div>
    </div>
  </Frame>
);

/** The board: a pinned notice with its author, its text and reactions, then
 *  the next one down. */
const PostSketch = ({ active }: SketchProps) => (
  <Frame>
    <div className="flex h-full flex-col gap-1.5">
      <div
        className={cn(
          "relative flex flex-col gap-1 rounded-sm border p-1",
          line(active),
          faint(active)
        )}
      >
        <div
          className={cn("absolute top-1 right-1 h-2 w-2 rotate-45 rounded-[1px]", accent(active))}
        />
        <div className="flex items-center gap-1.5">
          <Avatar active={active} />
          <div className={cn("h-1.5 w-1/3 rounded-sm", ink(active))} />
          <div className={cn("h-1 w-6 rounded-sm", faint(active))} />
        </div>
        <div className={cn("h-1 w-full rounded-sm", faint(active))} />
        <div className={cn("h-1 w-4/5 rounded-sm", faint(active))} />
        <div className="flex gap-1">
          {(["r1", "r2"] as const).map((reaction) => (
            <div key={reaction} className={cn("h-2 w-5 rounded-full", faint(active))} />
          ))}
        </div>
      </div>
      <div className="flex items-center gap-1.5 px-1">
        <Avatar active={active} />
        <div className={cn("h-1.5 w-1/4 rounded-sm", ink(active))} />
        <div className={cn("h-1 flex-1 rounded-sm", faint(active))} />
      </div>
    </div>
  </Frame>
);

/** The wall: pictures at their own heights, packed three across. */
const CatalogSketch = ({ active }: SketchProps) => (
  <Frame>
    <div className="grid h-full grid-cols-3 grid-rows-3 gap-1">
      {CATALOG_TILES.map((tile) => (
        <div
          key={tile.id}
          className={cn("rounded-sm", tile.tone(active), tile.tall && "row-span-2")}
        />
      ))}
    </div>
  </Frame>
);

/**
 * A wiki: the page tree down the left, the page itself on the right. The split
 * IS the tool — a wiki is navigated before it is read — so the sketch shows the
 * navigation taking its own column rather than a page on its own.
 */
const WikiSketch = ({ active }: SketchProps) => (
  <Frame>
    <div className="flex h-full gap-1.5">
      <div className={cn("flex w-1/3 flex-col gap-1 border-r pr-1.5", line(active))}>
        <div className={cn("h-1.5 w-3/4 rounded-sm", ink(active))} />
        {(["a", "b"] as const).map((row) => (
          <div key={row} className="flex flex-col gap-1 pl-1">
            <div className={cn("h-1 w-full rounded-sm", faint(active))} />
            <div className={cn("ml-1.5 h-1 w-2/3 rounded-sm", faint(active))} />
          </div>
        ))}
        <div className={cn("ml-1 h-1 w-1/2 rounded-sm", ink(active))} />
      </div>
      <div className="flex flex-1 flex-col gap-1">
        <div className={cn("h-2 w-2/3 rounded-sm", ink(active))} />
        <div className={cn("h-1 w-full rounded-sm", faint(active))} />
        <div className={cn("h-1 w-11/12 rounded-sm", faint(active))} />
        <div className={cn("h-1 w-1/3 rounded-sm", ink(active))} />
        <div className={cn("h-1 w-5/6 rounded-sm", faint(active))} />
      </div>
    </div>
  </Frame>
);

export const TOOL_SKETCHES: Record<Tool, (props: SketchProps) => ReactNode> = {
  [Tool.project]: ProjectSketch,
  [Tool.file]: FileSketch,
  [Tool.calendar]: CalendarSketch,
  [Tool.queue]: QueueSketch,
  [Tool.counter_group]: CounterGroupSketch,
  [Tool.dashboard]: DashboardSketch,
  [Tool.post]: PostSketch,
  [Tool.catalog]: CatalogSketch,
  [Tool.wiki]: WikiSketch,
};

export interface ToolSketchProps extends SketchProps {
  tool: Tool;
}

/** The sketch for one tool. */
export const ToolSketch = ({ tool, active }: ToolSketchProps) => {
  const Sketch = TOOL_SKETCHES[tool];
  return <Sketch active={active} />;
};

/** The tool's icon in a tile, lit when the tool is picked. Kept beside the
 *  sketch rather than replaced by it: the icon is what the sidebar will show,
 *  so seeing them together is what teaches the association. */
export const ToolIconTile = ({ tool, active }: ToolSketchProps) => {
  const Icon = TOOL_ICONS[tool];
  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-colors",
        active
          ? "bg-primary/15 text-primary shadow-[inset_0_0_0_1px] shadow-primary/40"
          : "bg-muted text-muted-foreground"
      )}
    >
      <Icon className="h-5 w-5" />
    </span>
  );
};
