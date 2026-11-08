import { useVirtualizer } from "@tanstack/react-virtual";
import {
  type ReactNode,
  type RefObject,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

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
 * The rows of a list near the view, of `count`, for a list the page itself
 * scrolls rather than a box of its own: the app's scroller
 * (`[data-app-scroll]`), not the window, measured against where the list
 * starts in it. `listRef` is the element the rows are drawn in, which holds
 * `paddingTop` before the first row it mounts and `paddingBottom` after the
 * last, for the rows it does not. Turned off, it measures and mounts nothing.
 */
export const useVirtualRows = (
  listRef: RefObject<HTMLElement | null>,
  {
    count,
    estimateSize,
    overscan,
    getItemKey,
    enabled = true,
  }: {
    count: number;
    estimateSize: (index: number) => number;
    overscan: number;
    getItemKey?: (index: number) => string | number;
    enabled?: boolean;
  }
) => {
  const scrollerRef = useRef<HTMLElement | null>(null);
  const getScrollElement = useCallback(() => {
    scrollerRef.current ??= document.querySelector<HTMLElement>("[data-app-scroll]");
    return scrollerRef.current;
  }, []);

  // How far down the scrolled content the list starts — everything above it:
  // the header, the toolbar, the filter panel, the selection bar, a table's
  // head. Every one of those opens and closes without the list remounting,
  // and an offset measured once at mount would then be wrong by their height:
  // the virtualizer mounts the wrong rows and leaves a blank band. So it is
  // read again after every render, and whenever the page moves, a frame at a
  // time.
  const [listOffset, setListOffset] = useState(0);
  const measure = useCallback(() => {
    const list = listRef.current;
    const scroller = getScrollElement();
    if (!enabled || !list || !scroller) return;
    setListOffset(
      list.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop
    );
  }, [enabled, listRef, getScrollElement]);

  useLayoutEffect(measure);

  useEffect(() => {
    const scroller = enabled ? getScrollElement() : null;
    if (!scroller) return;
    let frame: number | null = null;
    const remeasure = () => {
      if (frame !== null) return;
      frame = requestAnimationFrame(() => {
        frame = null;
        measure();
      });
    };
    // Captured, so that a box scrolling inside the page, as the layout
    // editor's canvas does, moves the list as the page scrolling does.
    const listening = { capture: true, passive: true };
    scroller.addEventListener("scroll", remeasure, listening);
    globalThis.addEventListener("resize", remeasure);
    // The scroller changes size without the window as well, when the sidebar
    // beside it opens or closes.
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(remeasure);
    observer?.observe(scroller);
    return () => {
      scroller.removeEventListener("scroll", remeasure, listening);
      globalThis.removeEventListener("resize", remeasure);
      observer?.disconnect();
      if (frame !== null) cancelAnimationFrame(frame);
    };
  }, [enabled, getScrollElement, measure]);

  const virtualizer = useVirtualizer({
    count,
    getScrollElement,
    estimateSize,
    overscan,
    getItemKey,
    enabled,
    scrollMargin: listOffset,
    // Where the page already is. The virtualizer moves its scroller to this
    // offset as it takes it, which would otherwise be the top: a page coming
    // back to where its reader left it would lose its place.
    initialOffset: () => getScrollElement()?.scrollTop ?? 0,
  });

  // A row's start and end count from the top of the scroller, the total size
  // from the top of the list.
  const items = virtualizer.getVirtualItems();
  const last = items.at(-1);
  return {
    virtualizer,
    items,
    paddingTop: items.length > 0 ? items[0].start - listOffset : 0,
    paddingBottom: last ? virtualizer.getTotalSize() - (last.end - listOffset) : 0,
  };
};

/**
 * A column of rows of which only the ones near the viewport are mounted.
 *
 * The grid and the timeline are both rows — a row of tiles, or a day's worth
 * — of heights that differ, so one virtualizer serves both. Virtualized from
 * the first render, for the reason the board is: turning it on partway down
 * moves the reader.
 */
export const VirtualRows = ({ rows, overscan = 3, onFirstVisible }: VirtualRowsProps) => {
  const listRef = useRef<HTMLDivElement | null>(null);
  const { virtualizer, items, paddingTop, paddingBottom } = useVirtualRows(listRef, {
    count: rows.length,
    estimateSize: (index) => rows[index]?.estimate ?? 200,
    overscan,
    getItemKey: (index) => rows[index]?.key ?? index,
  });

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
