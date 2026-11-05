import { useCallback, useMemo, useRef, useState } from "react";

import { resolveCardClick } from "@/lib/selectionRange";

/** Options a single card click carries. */
export interface GridToggleOptions {
  /** Shift was held — extend the selection from the last clicked card. */
  extend?: boolean;
}

const NO_ITEMS: readonly never[] = [];

/**
 * Multi-select state for a card/grid list (projects, counter groups, …).
 * Selection is a mode you enter explicitly — cards become checkboxes and their
 * links stop navigating while it's active.
 *
 * Selected items are stored **by value**, not derived from the current page, so a
 * selection survives pagination/filtering: pick items on page 1, page to page 2,
 * pick more, and all of them are acted on together.
 *
 * Pass the cards in the order they render to enable shift-click range selection;
 * the range runs along that order.
 */
export function useGridSelection<T extends { id: number }>(items: readonly T[] = NO_ITEMS) {
  const [active, setActive] = useState(false);
  const [selectedMap, setSelectedMap] = useState<Map<number, T>>(new Map());

  // Only ever read from a click handler, so the latest render's list is the
  // right one — a range is measured against what the user is looking at.
  const itemsRef = useRef(items);
  itemsRef.current = items;
  const anchorRef = useRef<number | null>(null);

  const selectedItems = useMemo(() => [...selectedMap.values()], [selectedMap]);
  const selectedIds = useMemo(() => new Set(selectedMap.keys()), [selectedMap]);

  const toggle = useCallback((item: T, options?: GridToggleOptions) => {
    // Read the anchor and the list *now*: React runs the updater below at render
    // time, by which point the refs already describe the next click.
    const anchorId = anchorRef.current;
    const items = itemsRef.current;
    anchorRef.current = item.id;

    setSelectedMap((prev) => {
      const { add, remove } = resolveCardClick(item, {
        items,
        anchorId,
        isSelected: (id) => prev.has(id),
        extend: options?.extend,
      });
      const next = new Map(prev);
      for (const id of remove) next.delete(id);
      for (const added of add) next.set(added.id, added);
      return next;
    });
  }, []);

  /** Select or drop every one of `items` at once — a table's header checkbox. */
  const setMany = useCallback((many: readonly T[], selected: boolean) => {
    anchorRef.current = null;
    setSelectedMap((prev) => {
      const next = new Map(prev);
      for (const item of many) {
        if (selected) next.set(item.id, item);
        else next.delete(item.id);
      }
      return next;
    });
  }, []);

  const clear = useCallback(() => {
    anchorRef.current = null;
    setSelectedMap(new Map());
  }, []);

  const enter = useCallback(() => setActive(true), []);
  const exit = useCallback(() => {
    anchorRef.current = null;
    setActive(false);
    setSelectedMap(new Map());
  }, []);

  return { active, selectedIds, selectedItems, toggle, setMany, clear, enter, exit };
}
