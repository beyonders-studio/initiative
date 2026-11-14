import {
  type PointerEvent as ReactPointerEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  MAX_COL_WIDTH,
  MAX_ROW_HEIGHT,
  MIN_COL_WIDTH,
  MIN_ROW_HEIGHT,
} from "@/lib/spreadsheet/styles";
import type { LineAxis } from "@/lib/spreadsheet/transform";

import type { SpreadsheetFormattingStore } from "./useSpreadsheetFormatting";

export const ROW_HEIGHT = 28;
export const COL_WIDTH = 110;

interface DragState {
  kind: LineAxis;
  index: number;
  size: number;
}

/** Column widths and row heights, and dragging a header edge to change one. */
export const useSpreadsheetResize = ({
  readOnly,
  formatting,
}: {
  readOnly: boolean;
  formatting: SpreadsheetFormattingStore;
}) => {
  const [drag, setDrag] = useState<DragState | null>(null);
  const dragRef = useRef<DragState | null>(null);
  const startRef = useRef<{ pos: number; size: number }>({ pos: 0, size: 0 });
  // Owns the window listeners attached during a drag. Held in a ref so the
  // unmount cleanup (below) can abort an in-flight drag, preventing a stale
  // formatting write after the editor has gone away.
  const abortRef = useRef<AbortController | null>(null);
  // The latest formatting mutators, for listeners attached once per drag.
  const formattingRef = useRef(formatting);
  formattingRef.current = formatting;

  // Effective per-index sizes: an in-flight resize preview wins over the
  // shared formatting value, which wins over the constant default.
  // A hidden line is drawn at zero size — the virtualizer then lays the grid
  // out with it collapsed, and everything downstream (offsets, the fill
  // handle, the frozen bands) follows without knowing about hiding at all.
  // A live resize drag still wins, so dragging a line back open works.
  const colWidth = useCallback(
    (c: number): number => {
      if (drag?.kind === "col" && drag.index === c) return drag.size;
      const fmt = formatting.columns[String(c)];
      if (fmt?.hidden) return 0;
      return fmt?.width ?? COL_WIDTH;
    },
    [drag, formatting.columns]
  );
  const rowHeight = useCallback(
    (r: number): number => {
      if (drag?.kind === "row" && drag.index === r) return drag.size;
      const fmt = formatting.rows[String(r)];
      if (fmt?.hidden) return 0;
      return fmt?.height ?? ROW_HEIGHT;
    },
    [drag, formatting.rows]
  );

  // Listeners are attached synchronously here, in the pointerdown handler,
  // so there is never a gap between "drag started" and "pointerup is
  // handled". An effect would run after paint, and a quick release (common
  // on Mac trackpads) could land before it.
  const startResize = useCallback(
    (kind: LineAxis, index: number, e: ReactPointerEvent) => {
      if (readOnly) return;
      e.preventDefault();
      e.stopPropagation();
      const size = kind === "col" ? colWidth(index) : rowHeight(index);
      startRef.current = { pos: kind === "col" ? e.clientX : e.clientY, size };
      const next = { kind, index, size };
      dragRef.current = next;
      setDrag(next);

      // Abort any previous drag's listeners (defensive — shouldn't happen,
      // but a missed pointerup would otherwise leak them indefinitely).
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      const { signal } = controller;

      const onMove = (ev: PointerEvent) => {
        const cur = dragRef.current;
        if (!cur) return;
        const delta =
          cur.kind === "col"
            ? ev.clientX - startRef.current.pos
            : ev.clientY - startRef.current.pos;
        const lo = cur.kind === "col" ? MIN_COL_WIDTH : MIN_ROW_HEIGHT;
        const hi = cur.kind === "col" ? MAX_COL_WIDTH : MAX_ROW_HEIGHT;
        // Round to integer: pointer coords are fractional on Retina/Mac, and
        // sanitizeColumnFmt/RowFmt drop non-integer sizes, which would make
        // the commit delete the entry and revert to the default size.
        const newSize = Math.round(Math.max(lo, Math.min(startRef.current.size + delta, hi)));
        const updated = { ...cur, size: newSize };
        dragRef.current = updated;
        setDrag(updated);
      };

      const teardown = () => {
        controller.abort();
        if (abortRef.current === controller) abortRef.current = null;
        dragRef.current = null;
        setDrag(null);
      };

      const commit = () => {
        const cur = dragRef.current;
        if (cur) {
          const fmt = formattingRef.current;
          if (cur.kind === "col") fmt.updateColumn(cur.index, { width: cur.size });
          else fmt.updateRow(cur.index, { height: cur.size });
        }
        teardown();
      };

      // pointercancel fires on Mac when the OS reclassifies a trackpad
      // gesture as a scroll — the user wasn't trying to resize, so the
      // in-flight drag is discarded rather than written.
      window.addEventListener("pointermove", onMove, { signal });
      window.addEventListener("pointerup", commit, { signal });
      window.addEventListener("pointercancel", teardown, { signal });
    },
    [readOnly, colWidth, rowHeight]
  );

  useEffect(
    () => () => {
      abortRef.current?.abort();
      abortRef.current = null;
    },
    []
  );

  const resetSize = useCallback(
    (kind: LineAxis, index: number) => {
      if (readOnly) return;
      if (kind === "col") formatting.updateColumn(index, { width: undefined });
      else formatting.updateRow(index, { height: undefined });
    },
    [readOnly, formatting]
  );

  return { drag, colWidth, rowHeight, startResize, resetSize };
};
