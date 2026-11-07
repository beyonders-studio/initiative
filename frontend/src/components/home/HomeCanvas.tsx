/**
 * The home page's canvas: the reader's widgets, where they put them.
 *
 * Wide, it is the dashboard canvas's twelve-column grid, each widget its own
 * `{x, y, w, h}`, dragged and resized while the page is being customized.
 * Narrow, the same widgets stack in reading order, each as tall as it needs,
 * and customizing moves them up and down instead: a grid you have to drag on is
 * no way to arrange a phone.
 *
 * While customizing, a widget's own content is inert — a tile full of
 * checkboxes and links is not a drag surface anyone could use otherwise.
 */

import { ArrowDown, ArrowUp, GripVertical, Settings2, TriangleAlert, X } from "lucide-react";
import { Component, type ReactNode, useMemo, useState } from "react";
import GridLayout, { type Layout, useContainerWidth, verticalCompactor } from "react-grid-layout";
import { useTranslation } from "react-i18next";

import { HOME_WIDGETS } from "@/components/home/widgets";
import {
  HOME_GRID_COLUMNS,
  type HomeLayout,
  type HomeWidget,
  type HomeWidgetOptions,
  readingOrder,
} from "@/lib/home/layout";
import { HOME_WIDGET_SIZES } from "@/lib/home/widgetTypes";
import { Button } from "@/ui/button";
import { cn } from "@/ui/lib/utils";

import "react-grid-layout/css/styles.css";

const ROW_HEIGHT = 56;
const MARGIN: [number, number] = [16, 16];
const NO_PADDING: [number, number] = [0, 0];

export interface HomeCanvasProps {
  layout: HomeLayout;
  editing: boolean;
  /** Room for the grid: the page measures its own width, since what it says
   *  about arranging depends on the same answer. */
  wide: boolean;
  /** The grid settled somewhere new: every widget's position, by id. */
  onArrange: (placed: Layout) => void;
  onMove: (id: string, step: -1 | 1) => void;
  onRemove: (id: string) => void;
  onConfigure: (id: string) => void;
  onOptionsChange: (id: string, options: HomeWidgetOptions) => void;
}

export function HomeCanvas({
  layout,
  editing,
  wide,
  onArrange,
  onMove,
  onRemove,
  onConfigure,
  onOptionsChange,
}: HomeCanvasProps) {
  return (
    <div className="w-full">
      {wide ? (
        <WideCanvas
          layout={layout}
          editing={editing}
          onArrange={onArrange}
          onRemove={onRemove}
          onConfigure={onConfigure}
          onOptionsChange={onOptionsChange}
        />
      ) : (
        <ol className="space-y-4">
          {readingOrder(layout.widgets).map((widget, index, all) => (
            <li key={widget.id}>
              <HomeTile
                widget={widget}
                editing={editing}
                stacked
                onMoveUp={index > 0 ? () => onMove(widget.id, -1) : undefined}
                onMoveDown={index < all.length - 1 ? () => onMove(widget.id, 1) : undefined}
                onRemove={() => onRemove(widget.id)}
                onConfigure={() => onConfigure(widget.id)}
                onOptionsChange={(options) => onOptionsChange(widget.id, options)}
              />
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function WideCanvas({
  layout,
  editing,
  onArrange,
  onRemove,
  onConfigure,
  onOptionsChange,
}: Omit<HomeCanvasProps, "onMove" | "wide">) {
  const [dragging, setDragging] = useState(false);
  const { width, mounted, containerRef } = useContainerWidth();

  const items = useMemo<Layout>(
    () =>
      layout.widgets.map((widget) => ({
        i: widget.id,
        ...widget.grid,
        minW: HOME_WIDGET_SIZES[widget.type].minW,
        minH: HOME_WIDGET_SIZES[widget.type].minH,
        static: !editing,
      })),
    [layout.widgets, editing]
  );

  // The grid reports a layout on mount as well as on every settle; only a
  // change while customizing is the reader's doing. Anything else (the grid
  // settling a stored layout it compacted) is left for the next real change.
  const handleLayoutChange = (next: Layout) => {
    if (editing) onArrange(next);
  };

  // A dot per cell, in the gutters, while there is arranging to do.
  const cellWidth = (width - MARGIN[0] * (HOME_GRID_COLUMNS - 1)) / HOME_GRID_COLUMNS;
  const dotGrid = {
    backgroundImage: "radial-gradient(circle, currentColor 1px, transparent 1px)",
    backgroundSize: `${cellWidth + MARGIN[0]}px ${ROW_HEIGHT + MARGIN[1]}px`,
    backgroundPosition: `${-(cellWidth + MARGIN[0]) / 2 - MARGIN[0] / 2}px ${-(ROW_HEIGHT + MARGIN[1]) / 2 - MARGIN[1] / 2}px`,
  };

  return (
    <div
      ref={containerRef}
      className={cn(
        "w-full rounded-lg transition-colors",
        editing && (dragging ? "text-muted-foreground/60" : "text-muted-foreground/30")
      )}
      style={editing ? dotGrid : undefined}
    >
      {/* Nothing is placed until the container has a width, or every widget
          would mount at the fallback size and then jump. */}
      {mounted && (
        <GridLayout
          width={width}
          layout={items}
          className={cn(dragging && "select-none")}
          gridConfig={{
            cols: HOME_GRID_COLUMNS,
            rowHeight: ROW_HEIGHT,
            margin: MARGIN,
            containerPadding: NO_PADDING,
          }}
          dragConfig={{
            enabled: editing,
            handle: "[data-home-tile-handle]",
            cancel: "[data-home-tile-actions]",
          }}
          resizeConfig={{ enabled: editing }}
          compactor={verticalCompactor}
          onDragStart={() => setDragging(true)}
          onDragStop={() => setDragging(false)}
          onResizeStart={() => setDragging(true)}
          onResizeStop={() => setDragging(false)}
          onLayoutChange={handleLayoutChange}
        >
          {layout.widgets.map((widget) => (
            <div key={widget.id}>
              <HomeTile
                widget={widget}
                editing={editing}
                onRemove={() => onRemove(widget.id)}
                onConfigure={() => onConfigure(widget.id)}
                onOptionsChange={(options) => onOptionsChange(widget.id, options)}
              />
            </div>
          ))}
        </GridLayout>
      )}
    </div>
  );
}

interface HomeTileProps {
  widget: HomeWidget;
  editing: boolean;
  /** In the narrow stack, where it is as tall as its content. */
  stacked?: boolean;
  onMoveUp?: () => void;
  onMoveDown?: () => void;
  onRemove: () => void;
  onConfigure: () => void;
  onOptionsChange: (options: HomeWidgetOptions) => void;
}

const EMPTY_OPTIONS: HomeWidgetOptions = {};

function HomeTile({
  widget,
  editing,
  stacked = false,
  onMoveUp,
  onMoveDown,
  onRemove,
  onConfigure,
  onOptionsChange,
}: HomeTileProps) {
  const { t } = useTranslation("home");
  const definition = HOME_WIDGETS[widget.type];
  const { Component: Widget } = definition;
  const title = t(`widgets.${widget.type}.title`);

  const actions = (
    <>
      {stacked ? (
        <>
          <TileButton
            label={t("tile.moveUp", { title })}
            onClick={onMoveUp}
            icon={<ArrowUp className="size-4" />}
          />
          <TileButton
            label={t("tile.moveDown", { title })}
            onClick={onMoveDown}
            icon={<ArrowDown className="size-4" />}
          />
        </>
      ) : null}
      {definition.Settings ? (
        <TileButton
          label={t("tile.settings", { title })}
          onClick={onConfigure}
          icon={<Settings2 className="size-4" />}
        />
      ) : null}
      <TileButton
        label={t("tile.remove", { title })}
        onClick={onRemove}
        icon={<X className="size-4" />}
      />
    </>
  );

  // The widget sits in the same place in the tree whether or not the page is
  // being customized, so toggling never remounts it (or refetches it).
  return (
    <div
      className={cn(
        "relative",
        !stacked && "h-full",
        stacked && editing && "space-y-2 rounded-xl border-2 border-primary/50 border-dashed p-2"
      )}
    >
      {/* Stacked, the controls get a row of their own above the widget: a
          narrow tile has no spare corner to float them in without covering
          the widget's own title and controls. */}
      {stacked && editing ? (
        <div className="flex items-center justify-between gap-2">
          <span className="min-w-0 truncate px-1 font-medium text-sm">{title}</span>
          <div className="flex shrink-0 items-center gap-1">{actions}</div>
        </div>
      ) : null}

      <div
        inert={editing}
        className={cn(
          !stacked && "h-full",
          editing && "pointer-events-none select-none opacity-60"
        )}
      >
        <WidgetBoundary title={title}>
          <Widget
            widget={widget}
            options={widget.options ?? EMPTY_OPTIONS}
            onOptionsChange={onOptionsChange}
            stacked={stacked}
            onConfigure={onConfigure}
            onRemove={onRemove}
          />
        </WidgetBoundary>
      </div>

      {!stacked && editing ? (
        <div
          data-home-tile-handle=""
          className="absolute inset-0 flex cursor-move items-start justify-between gap-2 rounded-xl border-2 border-primary/50 border-dashed p-2"
        >
          <span className="flex min-w-0 items-center gap-1.5 rounded-md bg-background/90 px-2 py-1 font-medium text-sm shadow-sm">
            <GripVertical className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            <span className="truncate">{title}</span>
          </span>
          {/* Buttons are not drag handles: a press on one is a click. */}
          <div
            data-home-tile-actions=""
            className="flex shrink-0 items-center gap-1 rounded-md bg-background/90 p-0.5 shadow-sm"
          >
            {actions}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function TileButton({
  label,
  icon,
  onClick,
}: {
  label: string;
  icon: ReactNode;
  onClick?: () => void;
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className="size-8"
      aria-label={label}
      title={label}
      disabled={!onClick}
      onClick={onClick}
    >
      {icon}
    </Button>
  );
}

/** One widget failing draws its own error, not the page's. */
class WidgetBoundary extends Component<
  { title: string; children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    return this.state.failed ? <WidgetFailed title={this.props.title} /> : this.props.children;
  }
}

function WidgetFailed({ title }: { title: string }) {
  const { t } = useTranslation("home");
  return (
    <div className="flex h-full min-h-24 flex-col items-center justify-center gap-2 rounded-xl border border-destructive/40 p-4 text-center text-destructive text-sm">
      <TriangleAlert className="size-5" aria-hidden="true" />
      {t("widgetError", { title })}
    </div>
  );
}
