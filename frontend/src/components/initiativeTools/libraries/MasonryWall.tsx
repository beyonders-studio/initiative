import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";

/** One thing on the wall: its identity, its shape, and how to draw it. */
export interface MasonryEntry {
  key: string | number;
  /** Width over height. What the wall lays out from — no measuring. */
  aspectRatio: number;
  render: () => ReactNode;
}

interface MasonryWallProps {
  entries: MasonryEntry[];
  /** The narrowest a column gets before the wall drops one. */
  minColumnWidth: number;
  gap?: number;
  /** How far beyond the viewport, in pixels, an entry is kept mounted. */
  overscan?: number;
}

interface Placement {
  entry: MasonryEntry;
  left: number;
  top: number;
  width: number;
  height: number;
}

/** The app's scroller, found once. */
const scroller = () => document.querySelector<HTMLElement>("[data-app-scroll]");

/**
 * A wall of pictures at their own shapes, packed into columns, of which only
 * the ones near the viewport are in the DOM.
 *
 * Nothing is measured. Every picture arrives knowing its shape, so a
 * column's contents and heights follow from the width alone: each entry goes
 * to the shortest column, in order. That is what makes the wall stable — a
 * page arriving underneath appends to the columns without moving anything
 * above it, a resize recomputes the whole thing in one pass, and the tile
 * somebody is looking at is never remounted because a neighbour changed.
 *
 * Virtualization is a window over the placements: the container is given the
 * wall's full height, and only the entries whose box crosses the viewport
 * (plus `overscan`) are rendered, absolutely positioned. Scrolling is read off
 * the app's scroller, throttled to a frame.
 */
export const MasonryWall = ({
  entries,
  minColumnWidth,
  gap = 12,
  overscan = 800,
}: MasonryWallProps) => {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  // The slice of the wall in view, in wall-relative pixels.
  const [window, setWindow] = useState<{ top: number; bottom: number } | null>(null);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    setWidth(element.clientWidth);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setWidth(element.clientWidth));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const { placements, height } = useMemo(() => {
    if (width <= 0) return { placements: [] as Placement[], height: 0 };
    const columns = Math.max(1, Math.floor((width + gap) / (minColumnWidth + gap)));
    const columnWidth = (width - gap * (columns - 1)) / columns;
    const heights = new Array<number>(columns).fill(0);
    const placed: Placement[] = entries.map((entry) => {
      let column = 0;
      for (let index = 1; index < columns; index += 1) {
        if (heights[index] < heights[column]) column = index;
      }
      const entryHeight = columnWidth / entry.aspectRatio;
      const placement = {
        entry,
        left: column * (columnWidth + gap),
        top: heights[column],
        width: columnWidth,
        height: entryHeight,
      };
      heights[column] += entryHeight + gap;
      return placement;
    });
    return { placements: placed, height: Math.max(0, Math.max(...heights, 0) - gap) };
  }, [entries, width, minColumnWidth, gap]);

  // Where the viewport is over the wall. Read on scroll and on resize, a frame
  // at a time; the wall's own offset inside the scroller is read each time
  // rather than cached, because what is above it (a filter panel opening, an
  // upload strip appearing) moves it.
  const measure = useCallback(() => {
    const element = ref.current;
    const target = scroller();
    if (!element) return;
    const rect = element.getBoundingClientRect();
    const viewportTop = target ? target.getBoundingClientRect().top : 0;
    const viewportHeight = target ? target.clientHeight : globalThis.innerHeight;
    const top = viewportTop - rect.top;
    setWindow({ top: top - overscan, bottom: top + viewportHeight + overscan });
  }, [overscan]);

  useEffect(() => {
    const target: HTMLElement | Window = scroller() ?? globalThis.window;
    let frame: number | null = null;
    const onScroll = () => {
      if (frame !== null) return;
      frame = requestAnimationFrame(() => {
        frame = null;
        measure();
      });
    };
    measure();
    target.addEventListener("scroll", onScroll, { passive: true });
    globalThis.addEventListener("resize", onScroll);
    return () => {
      target.removeEventListener("scroll", onScroll);
      globalThis.removeEventListener("resize", onScroll);
      if (frame !== null) cancelAnimationFrame(frame);
    };
  }, [measure]);

  // The wall changed shape under the viewport: re-read where the viewport is.
  useEffect(() => {
    measure();
  }, [height, measure]);

  const visible =
    window === null
      ? placements.slice(0, 0)
      : placements.filter((p) => p.top + p.height >= window.top && p.top <= window.bottom);

  return (
    <div ref={ref} className="relative w-full" style={{ height }}>
      {visible.map((placement) => (
        <div
          key={placement.entry.key}
          className="absolute"
          style={{
            left: placement.left,
            top: placement.top,
            width: placement.width,
            height: placement.height,
          }}
        >
          {placement.entry.render()}
        </div>
      ))}
    </div>
  );
};
