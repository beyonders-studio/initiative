/**
 * The canvas — many widgets, freely arranged.
 *
 * A 12-column grid where each widget carries its own `{x, y, w, h}`. Layout is
 * part of the definition, so arranging a dashboard is *authoring*: it writes the
 * dashboard's own row and takes DAC write, which is why a viewer without it gets
 * a static grid rather than a disabled-looking one.
 *
 * Below the grid's breakpoint the canvas stacks into a single column, view-only.
 * Drag and resize are desktop authoring affordances; fighting a touch target for
 * them would trade a real interaction for a fiddly one.
 */

import { Loader2 } from "lucide-react";
import { useMemo, useState } from "react";
import {
  type Layout,
  type LayoutItem,
  ResponsiveGridLayout,
  useContainerWidth,
  verticalCompactor,
} from "react-grid-layout";
import { useTranslation } from "react-i18next";

import type { WidgetCatalog } from "@/api/generated/initiativeAPI.schemas";
import {
  applyLayout,
  catalogEntry,
  type DashboardConfig,
  type DashboardDefinition,
  effectiveBinding,
  GRID_COLUMNS,
} from "@/lib/widgets/definition";
import { cn } from "@/ui/lib/utils";

import { DashboardWidget } from "./DashboardWidget";

// v2 folds the resize-handle styles into its own stylesheet; the separate
// react-resizable CSS the v1 docs pair this with no longer exists.
import "react-grid-layout/css/styles.css";

// v2 replaced the WidthProvider HOC with a hook, so the measured element is
// ours and the grid is told the width explicitly.
const ROW_HEIGHT = 56;
const MARGIN: [number, number] = [12, 12];
// The surface is the padded region; the grid fills it edge to edge. Keeping the
// grid's own padding at zero means cell (0,0) sits exactly on the surface's
// origin, which is what lets the dot grid below line up with real cells.
const NO_PADDING: [number, number] = [0, 0];

/**
 * Two breakpoints, because there are only two *kinds* of layout: the authored
 * one and the derived stack. A third that also held 12 columns would be a
 * second place the same arrangement lives, and telling them apart in the
 * change callback is exactly where that goes wrong.
 *
 * Below the threshold a phone reads the canvas top to bottom in layout order
 * rather than squeezing a Gantt into a quarter of the screen.
 */
const STACKED = "xs";
const AUTHORED = "lg";
const STACK_BELOW = 768;
const BREAKPOINTS = { [AUTHORED]: STACK_BELOW, [STACKED]: 0 };
const COLS = { [AUTHORED]: GRID_COLUMNS, [STACKED]: 1 };

export interface DashboardCanvasProps {
  definition: DashboardDefinition;
  config: DashboardConfig;
  catalog: WidgetCatalog | undefined;
  /** The dashboard's own initiative. Every widget reads within it. */
  initiativeId: number | undefined;
  /** The dashboard row. Only `plugin` widgets need it — their data is community-level,
   *  so the proxy is told which initiative-scoped surface is asking. A preview
   *  has none, which is one of the reasons it fetches nothing. */
  dashboardId?: number;
  /** DAC write on this dashboard. Arranging is authoring. */
  canEdit: boolean;
  /** Render every widget from the sample library instead of its binding — the
   *  marketplace preview's and a list card's mode. Nothing is fetched; see
   *  `DashboardWidget`. */
  sampleData?: boolean;
  /** The dashboard row is still on its way. The canvas is the only region that
   *  shows this — the page around it is already correct and must not flicker. */
  isLoading?: boolean;
  onLayoutChange: (next: DashboardDefinition) => void;
  onConfigureWidget?: (widgetId: string) => void;
  onRemoveWidget?: (widgetId: string) => void;
}

export function DashboardCanvas({
  definition,
  config,
  catalog,
  initiativeId,
  dashboardId,
  canEdit,
  sampleData,
  isLoading,
  onLayoutChange,
  onConfigureWidget,
  onRemoveWidget,
}: DashboardCanvasProps) {
  const { t } = useTranslation("dashboards");
  const [dragging, setDragging] = useState(false);
  const { width, mounted, containerRef } = useContainerWidth();

  // Whether the user is looking at the authored layout or the derived stack.
  // Derived from the measured width rather than tracked separately, because
  // that is the same number the grid picks its own breakpoint from — so the
  // two can never disagree, including before the first measurement lands.
  const authoring = width >= STACK_BELOW;

  // RGL fires onLayoutChange on mount as well as on every settle. Comparing
  // against the definition we are *currently rendering* is what tells the two
  // apart: opening a dashboard you can edit must not write its row.
  const placed = JSON.stringify(definition.widgets.map((widget) => widget.grid));

  const layouts = useMemo(() => {
    const items: LayoutItem[] = definition.widgets.map((widget) => {
      const entry = catalogEntry(catalog, widget.type);
      return {
        i: widget.id,
        x: widget.grid.x,
        y: widget.grid.y,
        w: widget.grid.w,
        h: widget.grid.h,
        minW: entry?.min_w ?? 1,
        minH: entry?.min_h ?? 1,
        static: !canEdit,
      };
    });
    // The stacked breakpoint is derived, not authored: full width, in order.
    const stacked: LayoutItem[] = definition.widgets.map((widget, index) => ({
      i: widget.id,
      x: 0,
      y: index,
      w: 1,
      h: widget.grid.h,
      static: true,
    }));
    return { [AUTHORED]: items, [STACKED]: stacked };
  }, [definition.widgets, catalog, canEdit]);

  const handleLayoutChange = (current: Layout) => {
    if (!canEdit) return;
    // The stacked layout is derived, not authored — writing it back would
    // flatten everyone's arrangement to one column. `current` is whichever
    // breakpoint the user is actually on, so it is the only correct source:
    // reading a named breakpoint out of `all` would take a stale copy of the
    // one they are not editing.
    if (!authoring) return;
    const next = applyLayout(definition, catalog, [...current]);
    if (JSON.stringify(next.widgets.map((widget) => widget.grid)) === placed) return;
    onLayoutChange(next);
  };

  // The dot grid: one dot per cell, sitting in the gutter so it reads as the
  // seam between cells rather than as a mark inside one. Drawn only for someone
  // who can actually arrange things — to a viewer it would be texture promising
  // an interaction they don't have. It is also why the surface keeps a minimum
  // height: a canvas with one widget on it should still look like a canvas.
  const showGrid = canEdit && authoring && !isLoading;
  const cellWidth = (width - MARGIN[0] * (GRID_COLUMNS - 1)) / GRID_COLUMNS;
  const dotGrid = {
    backgroundImage: "radial-gradient(circle, currentColor 1px, transparent 1px)",
    backgroundSize: `${cellWidth + MARGIN[0]}px ${ROW_HEIGHT + MARGIN[1]}px`,
    backgroundPosition: `${-(cellWidth + MARGIN[0]) / 2 - MARGIN[0] / 2}px ${-(ROW_HEIGHT + MARGIN[1]) / 2 - MARGIN[1] / 2}px`,
  };

  return (
    <div ref={containerRef} className="w-full">
      <div
        className={cn(
          "relative min-h-64 rounded-lg transition-colors",
          showGrid && (dragging ? "text-muted-foreground/60" : "text-muted-foreground/30")
        )}
        style={showGrid ? dotGrid : undefined}
      >
        {isLoading ? (
          <CanvasNotice>
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            {t("loadingDashboard")}
          </CanvasNotice>
        ) : !definition.widgets.length ? (
          <CanvasNotice>
            <span className="space-y-1">
              <span className="block font-medium text-foreground text-sm">{t("canvas.empty")}</span>
              <span className="block">
                {canEdit ? t("canvas.emptyHint") : t("canvas.emptyReadOnly")}
              </span>
            </span>
          </CanvasNotice>
        ) : (
          // Nothing is placed until the container has a width, or every widget
          // would mount at the fallback size and then jump.
          mounted && (
            <ResponsiveGridLayout
              width={width}
              className={cn(dragging && "select-none")}
              layouts={layouts}
              breakpoints={BREAKPOINTS}
              cols={COLS}
              rowHeight={ROW_HEIGHT}
              margin={MARGIN}
              containerPadding={NO_PADDING}
              // v2 groups these; the handle selector is what keeps a widget's
              // own content from becoming a drag surface.
              dragConfig={{ enabled: canEdit, handle: "[data-widget-handle]" }}
              resizeConfig={{ enabled: canEdit }}
              onDragStart={() => setDragging(true)}
              onDragStop={() => setDragging(false)}
              onResizeStart={() => setDragging(true)}
              onResizeStop={() => setDragging(false)}
              onLayoutChange={handleLayoutChange}
              // Widgets settle upward into free space and never overlap.
              compactor={verticalCompactor}
            >
              {definition.widgets.map((widget) => (
                <div key={widget.id}>
                  <DashboardWidget
                    widget={widget}
                    binding={effectiveBinding(widget, config)}
                    initiativeId={initiativeId}
                    dashboardId={dashboardId}
                    canEdit={canEdit}
                    sampleData={sampleData}
                    onConfigure={onConfigureWidget}
                    onRemove={onRemoveWidget}
                  />
                </div>
              ))}
            </ResponsiveGridLayout>
          )
        )}
      </div>
    </div>
  );
}

/** Centred text on the canvas surface, for the states where there is nothing to
 *  arrange yet. Kept inside the surface so the dot grid stays behind it. */
function CanvasNotice({ children }: { children: React.ReactNode }) {
  return (
    <div className="absolute inset-0 flex items-center justify-center gap-2 p-6 text-center text-muted-foreground text-sm">
      {children}
    </div>
  );
}
