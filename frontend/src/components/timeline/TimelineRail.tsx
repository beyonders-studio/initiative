import { ChevronsUpDown } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/ui/lib/utils";

/**
 * One stop on the rail.
 *
 * Deliberately not any tool's own shape. A month with things in it and a place
 * to land is the whole vocabulary — a board's notices, a calendar's events and
 * a project's activity would each hand back this same list, so the rail is
 * written once and each tool adapts its own response into it.
 */
export interface TimelineStop {
  /** Stable identity, and what an active stop is compared by. `YYYY-MM`. */
  period: string;
  /** How many rows fall in it — what gives the rail its density. */
  count: number;
}

interface TimelineRailProps<T extends TimelineStop> {
  stops: T[];
  /** The `period` currently at the top of the view, marked on the rail. */
  activePeriod?: string | null;
  onPick: (stop: T) => void;
  /** Localized label for a stop, e.g. "March 2026". Kept out of the rail so it
   *  formats in the caller's own locale and vocabulary. */
  formatLabel: (stop: T) => string;
  /** Short label drawn beside a tick where the year changes, e.g. "2026". */
  formatGroup: (stop: T) => string;
  className?: string;
}

/** The tallest a tick gets relative to the rail, and the shortest. A month
 *  with one row still has to be a target somebody can hit. */
const MIN_TICK = 0.35;

/** How wide the rail's hit area is. The visible ticks are narrower; this is
 *  what a finger actually lands on, and it is the reason the rail is usable on
 *  a phone rather than a desktop-only affordance.
 *
 *  Wide enough for a year to sit INSIDE it. A label placed outside the rail —
 *  `right-full`, say — hangs over whatever the rail is beside, which on a feed
 *  is the content somebody is reading. */
const RAIL_HIT_WIDTH = "w-11";

/** How long the thumb stays up after the feed stops moving. Long enough to
 *  reach for, short enough that it is not sitting over what somebody settled
 *  down to read. */
const REST_MS = 1400;

/**
 * The scroller the rail is riding in, found by walking up from the rail rather
 * than named by the caller — so the next tool that drops a rail beside its own
 * feed gets the appearing thumb without wiring anything.
 */
const scrollParent = (node: HTMLElement | null): HTMLElement | Window | null => {
  for (let element = node?.parentElement ?? null; element; element = element.parentElement) {
    const { overflowY } = getComputedStyle(element);
    if (
      (overflowY === "auto" || overflowY === "scroll") &&
      element.scrollHeight > element.clientHeight
    )
      return element;
  }
  return typeof window === "undefined" ? null : window;
};

/** How far down the scroller is, 0 at the top and 1 at the bottom. */
const scrollProgress = (target: HTMLElement | Window): number => {
  const [at, range] =
    target instanceof Window
      ? [window.scrollY, document.documentElement.scrollHeight - window.innerHeight]
      : [target.scrollTop, target.scrollHeight - target.clientHeight];
  return range > 0 ? Math.min(Math.max(at / range, 0), 1) : 0;
};

/**
 * A draggable rail of periods, for jumping a long feed to a date.
 *
 * The photo-library pattern: months as ticks down the edge, years labelled,
 * and a bubble that follows a finger or a cursor naming the month under it.
 * One control that behaves the same on a phone and a desktop rather than a
 * hover affordance with a separate mobile substitute.
 *
 * What differs by screen is only how much of it is standing there when nobody
 * is using it. A wide screen has room beside the feed, so the rail sits in it
 * and stays. A phone does not: there the rail is an overlay costing no width,
 * and it comes and goes in three steps —
 *
 * - **idle**: nothing, and nothing to tap by accident either;
 * - **peek**: the feed is moving, so a thumb at the edge says how far down it
 *   the reader is, and fades a moment after they stop;
 * - **open**: the thumb has been grabbed, and the whole rail is there — ticks,
 *   years, and the bubble naming the month under the finger.
 *
 * Each stop is a real `<button>`, so the rail is a list somebody can tab
 * through and a screen reader can read, and the dragging is layered on top of
 * that rather than replacing it. Tabbing into it opens it, which is why the
 * hidden state is drawn with opacity rather than taken out of the page.
 * `touch-action: none` is what stops a drag scrolling the page underneath it.
 *
 * Density is drawn, not counted: a tick's length is its share of the busiest
 * month, which is what makes a year of quiet months and one loud one legible
 * at a glance.
 */
export function TimelineRail<T extends TimelineStop>({
  stops,
  activePeriod,
  onPick,
  formatLabel,
  formatGroup,
  className,
}: TimelineRailProps<T>) {
  const { t } = useTranslation("common");
  const railRef = useRef<HTMLElement | null>(null);
  // The stop under the finger mid-drag, and where on the rail the finger is.
  // Separate from `activePeriod`, which is where the feed actually is: during a
  // drag the bubble runs ahead of it.
  const [dragging, setDragging] = useState<{ stop: T; offset: number; moved: boolean } | null>(
    null
  );
  // The feed has moved in the last moment. What summons the thumb on a phone,
  // where there is nothing else standing there to reach for.
  const [moving, setMoving] = useState(false);
  // How far down the feed the reader is, which is where the thumb sits. Read
  // off the scroller rather than derived from `activePeriod`: a thumb is a
  // scrollbar's, and it has to move with the feed. Placing it at the active
  // month's tick would leave it still through a busy month and then leap a
  // whole step at the boundary — and a pinned notice lifted to the top of the
  // feed from some other month would send it down the rail and back again in
  // the space of one card.
  const [progress, setProgress] = useState(0);
  // The rail is being used — hovered, or held. Distinct from `moving`: this is
  // what opens it the rest of the way.
  const [engaged, setEngaged] = useState(false);

  const open = engaged || dragging !== null;
  const state = open ? "open" : moving ? "peek" : "idle";

  useEffect(() => {
    const target = scrollParent(railRef.current);
    if (!target) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setProgress(scrollProgress(target));
    const onScroll = () => {
      setProgress(scrollProgress(target));
      setMoving(true);
      clearTimeout(timer);
      timer = setTimeout(() => setMoving(false), REST_MS);
    };
    target.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      target.removeEventListener("scroll", onScroll);
      clearTimeout(timer);
    };
  }, []);

  const busiest = useMemo(
    () => stops.reduce((most, stop) => Math.max(most, stop.count), 1),
    [stops]
  );

  /** The stop under a pointer at this y, clamped to the ends so a drag that
   *  runs off the rail keeps tracking rather than going dead. */
  const stopAt = useCallback(
    (clientY: number): T | null => {
      const rail = railRef.current;
      if (!rail || stops.length === 0) return null;
      const box = rail.getBoundingClientRect();
      const ratio = (clientY - box.top) / Math.max(box.height, 1);
      const index = Math.round(ratio * (stops.length - 1));
      return stops[Math.min(Math.max(index, 0), stops.length - 1)] ?? null;
    },
    [stops]
  );

  const track = useCallback(
    (event: React.PointerEvent, moved: boolean) => {
      const rail = railRef.current;
      const stop = stopAt(event.clientY);
      if (!rail || !stop) return;
      const box = rail.getBoundingClientRect();
      // Clamped to the rail, so a drag that runs off the end leaves the bubble
      // at the end rather than sliding away up the page with the finger.
      const offset = Math.min(Math.max(event.clientY - box.top, 0), box.height);
      setDragging((current) => ({ stop, offset, moved: moved || (current?.moved ?? false) }));
    },
    [stopAt]
  );

  // Under the finger while dragging, and otherwise as far down the rail as the
  // reader is down the feed.
  const thumbTop = dragging ? `${dragging.offset}px` : `${progress * 100}%`;

  if (stops.length === 0) return null;

  return (
    <nav
      ref={railRef}
      data-state={state}
      // `touch-action: none` so a drag down the rail scrubs it rather than
      // scrolling the feed behind it.
      className={cn(
        "relative shrink-0 touch-none select-none transition-opacity duration-200",
        RAIL_HIT_WIDTH,
        // On a phone the rail overlays the feed — a negative margin cancels its
        // own width, so the notices get the whole screen and the rail costs
        // nothing when it is not being used. From `sm` up there is room for it
        // beside the feed, where it simply stays.
        "-ml-11 sm:ml-0",
        // Hidden means untouchable: an invisible strip down the edge of a card
        // would swallow taps meant for the notice under it.
        state === "idle" && "pointer-events-none opacity-0",
        state === "peek" && "pointer-events-none opacity-100",
        "focus-within:pointer-events-auto focus-within:opacity-100",
        "sm:pointer-events-auto sm:opacity-100",
        className
      )}
      aria-label={t("timeline.label")}
      onPointerDown={(event) => {
        // Capture, so the drag keeps tracking once the finger leaves the rail.
        event.currentTarget.setPointerCapture(event.pointerId);
        setEngaged(true);
        track(event, false);
      }}
      onPointerMove={(event) => {
        if (dragging) track(event, true);
      }}
      onPointerUp={(event) => {
        const stop = stopAt(event.clientY);
        // A press that never moved is a click, and the stop under it is a real
        // button whose own handler is about to fire — picking here as well
        // would run the caller's callback twice for one activation. A press on
        // the rail's own space has no button to fall through to, so it is
        // picked here.
        const wasDrag = dragging?.moved ?? false;
        const target = event.target as Element | null;
        const onButton = target?.closest("button") != null;
        const onThumb = target?.closest('[data-slot="timeline-thumb"]') != null;
        setDragging(null);
        setEngaged(false);
        if (stop && (wasDrag || (!onButton && !onThumb))) onPick(stop);
      }}
      onPointerCancel={() => {
        setDragging(null);
        setEngaged(false);
      }}
      // A mouse opens the rail by arriving at it; a finger has the thumb.
      onPointerEnter={(event) => {
        if (event.pointerType === "mouse") setEngaged(true);
      }}
      onPointerLeave={() => {
        if (!dragging) setEngaged(false);
      }}
    >
      {/* The months themselves. Only drawn once the rail is open, because on a
          phone they are drawn over the feed: a thumb says where you are, and a
          full rail is for when you have said you want one. */}
      <div
        className={cn(
          "absolute inset-0 flex flex-col justify-between py-1 transition-opacity duration-200",
          open ? "opacity-100" : "opacity-0",
          "sm:opacity-100"
        )}
      >
        {stops.map((stop, index) => {
          const isActive = stop.period === activePeriod;
          const isUnderFinger = dragging?.stop.period === stop.period;
          // A year label where the year changes, and on the first stop, so the
          // top of the rail always says what it is showing. It sits in the flow
          // above its first tick rather than beside the rail — anything placed
          // outside the rail's own width lands on top of the feed it is next
          // to. Overlaying one, it carries its own backing so the year stays
          // readable over whatever it happens to cross.
          const group = formatGroup(stop);
          const startsGroup = index === 0 || formatGroup(stops[index - 1]) !== group;
          return (
            <div key={stop.period} className="flex flex-col items-end gap-0.5">
              {startsGroup && (
                <span
                  aria-hidden
                  className="pointer-events-none rounded-full bg-background/80 px-1 text-3xs text-muted-foreground tabular-nums leading-none backdrop-blur-[2px]"
                >
                  {group}
                </span>
              )}
              <button
                type="button"
                title={formatLabel(stop)}
                aria-label={formatLabel(stop)}
                aria-current={isActive ? "true" : undefined}
                onClick={() => onPick(stop)}
                className="group flex h-3 w-full items-center justify-end pr-0.5"
              >
                <span
                  className={cn(
                    "h-0.5 rounded-full transition-colors",
                    isActive || isUnderFinger
                      ? "bg-primary"
                      : "bg-muted-foreground/30 group-hover:bg-muted-foreground/60"
                  )}
                  style={{
                    width: `${Math.round((MIN_TICK + (1 - MIN_TICK) * (stop.count / busiest)) * 100)}%`,
                  }}
                />
              </button>
            </div>
          );
        })}
      </div>

      {/* The thumb: where the reader is in the months, and on a phone the one
          thing there is to grab. It carries its own `pointer-events` because
          the rail around it has none while it is only peeking — the events it
          receives still bubble to the rail's own handlers, so grabbing it is
          grabbing the rail. Hidden from a screen reader, which has the ticks:
          this is the touch target, not a second control. */}
      <span
        aria-hidden
        data-slot="timeline-thumb"
        style={{ top: thumbTop }}
        className={cn(
          "absolute right-0 flex size-7 -translate-y-1/2 touch-none items-center justify-center rounded-full border bg-popover text-muted-foreground shadow-sm transition-opacity duration-200",
          state === "idle" ? "pointer-events-none" : "pointer-events-auto",
          open && "text-primary",
          "sm:hidden"
        )}
      >
        <ChevronsUpDown className="size-3.5" />
      </span>

      {/* The bubble, naming the month under the finger. Only while dragging:
          a label that is always there is a legend, not a readout. */}
      {dragging && (
        <span
          role="status"
          style={{ top: dragging.offset }}
          className="pointer-events-none absolute right-full z-20 mr-2 -translate-y-1/2 whitespace-nowrap rounded-md border bg-popover px-2 py-1 font-medium text-popover-foreground text-xs shadow-md"
        >
          {formatLabel(dragging.stop)}
        </span>
      )}
    </nav>
  );
}
