import { useVirtualizer } from "@tanstack/react-virtual";
import { type ReactNode, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

export interface VirtualRow {
  key: string;
  /** A first guess at the row's height, corrected by measurement on mount. */
  estimate: number;
  render: () => ReactNode;
}

interface VirtualRowsProps {
  rows: VirtualRow[];
  /** Rows kept mounted either side of the window. */
  overscan?: number;
  /** The first row in view, whenever it changes — for a rail that marks
   *  where the reader is. */
  onFirstVisible?: (index: number) => void;
}

/** The gap between rows, applied INSIDE each measured element so the
 *  virtualizer's model is not short by the gap on every row. */
const ROW_GAP = "pb-3";

/**
 * A column of rows of which only the ones near the viewport are mounted.
 *
 * The grid and the timeline are both rows — a row of tiles, or a day's worth
 * — of heights that differ, so one virtualizer serves both. The page itself
 * scrolls, not a box inside it, so this measures against the app's scroller
 * and offsets by where the list starts; virtualized from the first render,
 * for the reason the board is: turning it on partway down moves the reader.
 */
export const VirtualRows = ({ rows, overscan = 3, onFirstVisible }: VirtualRowsProps) => {
  const listRef = useRef<HTMLDivElement | null>(null);
  const scrollerRef = useRef<HTMLElement | null>(null);
  const getScrollElement = useCallback(() => {
    scrollerRef.current ??= document.querySelector<HTMLElement>("[data-app-scroll]");
    return scrollerRef.current;
  }, []);

  // How far down the scrolled content the list starts — everything above it:
  // the header, the toolbar, the filter panel, the selection bar, the upload
  // strip. Every one of those opens and closes without this component
  // remounting, and an offset measured once at mount would then be wrong by
  // their height: the virtualizer mounts the wrong rows and leaves a blank
  // band. So it is re-read whenever the page moves, a frame at a time.
  const [listOffset, setListOffset] = useState(0);
  const measure = useCallback(() => {
    const list = listRef.current;
    const scroller = getScrollElement();
    if (!list || !scroller) return;
    setListOffset(
      list.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop
    );
  }, [getScrollElement]);

  useLayoutEffect(measure, [measure]);

  // The rows themselves changing height is the other way the list moves.
  useLayoutEffect(measure, [measure, rows]);

  useEffect(() => {
    const scroller = getScrollElement();
    if (!scroller) return;
    let frame: number | null = null;
    const remeasure = () => {
      if (frame !== null) return;
      frame = requestAnimationFrame(() => {
        frame = null;
        measure();
      });
    };
    scroller.addEventListener("scroll", remeasure, { passive: true });
    globalThis.addEventListener("resize", remeasure);
    // What is above the list changes height without the list re-rendering,
    // so the scroller's own content box is what to watch.
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(remeasure);
    observer?.observe(scroller);
    return () => {
      scroller.removeEventListener("scroll", remeasure);
      globalThis.removeEventListener("resize", remeasure);
      observer?.disconnect();
      if (frame !== null) cancelAnimationFrame(frame);
    };
  }, [getScrollElement, measure]);

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement,
    estimateSize: (index) => rows[index]?.estimate ?? 200,
    overscan,
    scrollMargin: listOffset,
    getItemKey: (index) => rows[index]?.key ?? index,
  });

  const items = virtualizer.getVirtualItems();
  const paddingTop = items.length > 0 ? items[0].start - listOffset : 0;
  const paddingBottom =
    items.length > 0 ? virtualizer.getTotalSize() - items[items.length - 1].end : 0;

  const firstVisible = (() => {
    const top = virtualizer.scrollOffset ?? 0;
    return (items.find((item) => item.end > top) ?? items[0])?.index;
  })();
  useEffect(() => {
    if (firstVisible !== undefined) onFirstVisible?.(firstVisible);
  }, [firstVisible, onFirstVisible]);

  return (
    <div ref={listRef} style={{ paddingTop, paddingBottom }}>
      {items.map((item) => {
        const row = rows[item.index];
        if (!row) return null;
        return (
          <div
            key={row.key}
            data-index={item.index}
            ref={virtualizer.measureElement}
            className={ROW_GAP}
          >
            {row.render()}
          </div>
        );
      })}
    </div>
  );
};
