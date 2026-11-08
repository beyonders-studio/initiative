import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Link } from "@tanstack/react-router";
import {
  Copy,
  GripVertical,
  Maximize2,
  Minus,
  MoreVertical,
  Pencil,
  Plus,
  RotateCcw,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type { CounterRead } from "@/api/generated/initiativeAPI.schemas";
import { getContrastingTextColor } from "@/lib/counter-color";
import { isAtMax, isAtMin } from "@/lib/counter-math";
import { Button } from "@/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";
import { cn } from "@/ui/lib/utils";

import { CounterView } from "./views/CounterView";

export type CounterLayout = "row" | "grid";

interface CounterRowProps {
  counter: CounterRead;
  canWrite: boolean;
  layout?: CounterLayout;
  /** Link to the full-screen single-counter view. Hides the button when omitted. */
  focusHref?: string;
  onSetCount: (value: string) => void;
  onIncrement: () => void;
  onDecrement: () => void;
  onReset: () => void;
  onEdit: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
}

export const CounterRow = ({
  counter,
  canWrite,
  layout = "row",
  focusHref,
  onSetCount,
  onIncrement,
  onDecrement,
  onReset,
  onEdit,
  onDuplicate,
  onDelete,
}: CounterRowProps) => {
  const { t } = useTranslation(["counterGroups", "common"]);
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: counter.id.toString(),
    disabled: !canWrite,
    data: { type: "counter" },
  });

  const bg = counter.color ?? "hsl(var(--card))";
  const fg = getContrastingTextColor(counter.color) ?? "hsl(var(--card-foreground))";
  const isLight = fg === "#0F172A";

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    background: bg,
    color: fg,
  };

  const viewElement = (
    <CounterView
      counter={counter}
      disabled={!canWrite}
      textColor={fg}
      onCommit={onSetCount}
      size={layout === "grid" ? "xl" : "lg"}
    />
  );

  // Tinted backgrounds for +/- buttons that contrast clearly against the
  // card color — darker overlay on light cards, lighter overlay on dark.
  const stepButtonClass = isLight
    ? "bg-black/25 hover:bg-black/35 active:bg-black/45"
    : "bg-white/25 hover:bg-white/35 active:bg-white/45";

  const moreHoverClass = isLight
    ? "hover:bg-black/15 focus-visible:bg-black/15"
    : "hover:bg-white/15 focus-visible:bg-white/15";

  // Buttons are h-11 in row layout (44px iOS HIG target). Grid cards use
  // h-10 so the value stays visually dominant.
  const stepButtonSize = layout === "grid" ? "h-10 w-10" : "h-11 w-11";
  const stepIconSize = "h-5 w-5";

  const dragHandle = (
    <button
      type="button"
      className={cn(
        "shrink-0 cursor-grab touch-none rounded p-1 opacity-50 transition disabled:cursor-not-allowed disabled:opacity-25",
        isLight ? "hover:bg-black/10" : "hover:bg-white/10"
      )}
      disabled={!canWrite}
      aria-label={t("dragToReorder")}
      {...attributes}
      {...listeners}
    >
      <GripVertical className="h-4 w-4" />
    </button>
  );

  const moreMenu = (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("more")}
          className={cn("h-7 w-7 opacity-70 hover:opacity-100", moreHoverClass)}
          style={{ color: fg }}
        >
          <MoreVertical className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {focusHref && (
          <DropdownMenuItem asChild>
            <Link to={focusHref}>
              <Maximize2 className="h-4 w-4" />
              {t("focus.openFocus")}
            </Link>
          </DropdownMenuItem>
        )}
        <DropdownMenuItem onSelect={onReset} disabled={!canWrite}>
          <RotateCcw className="h-4 w-4" />
          {t("reset")}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={onEdit} disabled={!canWrite}>
          <Pencil className="h-4 w-4" />
          {t("editCounter")}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={onDuplicate} disabled={!canWrite}>
          <Copy className="h-4 w-4" />
          {t("common:subToolDuplicate.action")}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={onDelete} disabled={!canWrite} className="text-destructive">
          <Trash2 className="h-4 w-4" />
          {t("removeCounter")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );

  const atMin = isAtMin(counter);
  const atMax = isAtMax(counter);

  // `touch-manipulation` relaxes the mobile browser's tap-vs-scroll heuristic
  // and drops the synthetic-click delay, so small finger movement during a
  // press still fires the click instead of being interpreted as a swipe.
  const minusButton = (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      onClick={onDecrement}
      disabled={!canWrite || atMin}
      aria-label={t("decrement")}
      className={cn(
        stepButtonSize,
        "touch-manipulation rounded-md text-current shadow-sm",
        stepButtonClass
      )}
      style={{ color: fg }}
    >
      <Minus className={stepIconSize} />
    </Button>
  );

  const plusButton = (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      onClick={onIncrement}
      disabled={!canWrite || atMax}
      aria-label={t("increment")}
      className={cn(
        stepButtonSize,
        "touch-manipulation rounded-md text-current shadow-sm",
        stepButtonClass
      )}
      style={{ color: fg }}
    >
      <Plus className={stepIconSize} />
    </Button>
  );

  if (layout === "grid") {
    // Grid: drag handle + more menu sit in the top corners (absolute) so
    // the inner column can give all of its vertical space to the name and
    // value — both centered and visually dominant.
    return (
      <div
        ref={setNodeRef}
        style={style}
        className={cn(
          // Phones (2-up): no aspect-square — it conflicts with min-h-45 (the
          // resolved height exceeds the grid row track and bleeds into the next
          // row). A min-height floor + content-driven growth avoids overlap.
          // md+ cards are wide enough that the square height clears the floor,
          // so aspect-square is safe and restores the square look.
          "relative flex min-h-45 flex-col overflow-hidden rounded-lg border border-black/10 px-3 pt-2 pb-3 shadow-sm sm:aspect-square dark:border-white/10",
          isDragging && "opacity-70"
        )}
      >
        <div className="absolute inset-x-2 top-1 -mx-1 flex items-center justify-between">
          {dragHandle}
          {moreMenu}
        </div>
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-1 px-1 pt-5">
          <span
            className="line-clamp-1 px-1 text-center font-semibold text-sm leading-tight"
            style={{ color: fg }}
            title={counter.name}
          >
            {counter.name}
          </span>
          <div className="flex min-h-0 w-full flex-1 items-center justify-center">
            {viewElement}
          </div>
        </div>
        <div className="mt-2 flex items-center justify-between gap-2">
          {minusButton}
          {plusButton}
        </div>
      </div>
    );
  }

  // Row layout: name on its own full-width line, then [grip] [-] [view] [+] [more].
  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "flex flex-col gap-2 overflow-hidden rounded-lg border border-black/10 p-3 shadow-sm dark:border-white/10",
        isDragging && "opacity-70"
      )}
    >
      <div className="truncate text-center font-semibold text-base" style={{ color: fg }}>
        {counter.name}
      </div>
      <div className="flex items-center gap-2 sm:gap-3">
        {dragHandle}
        {minusButton}
        <div className="flex min-w-0 flex-1 justify-center">{viewElement}</div>
        {plusButton}
        {moreMenu}
      </div>
    </div>
  );
};
