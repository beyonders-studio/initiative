import * as DialogPrimitive from "@radix-ui/react-dialog";
import { ChevronLeft, ChevronRight, Minus, MoreVertical, Plus, RotateCcw, X } from "lucide-react";
import { type ElementType, type ReactNode, type TouchEvent, useRef } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";

import { type CounterShown, CounterView } from "./CounterView";

const SWIPE_THRESHOLD_PX = 60;

/** A header button drawn on the counter's colours. */
const CHROME_BUTTON =
  "h-10 w-10 text-current hover:bg-current/10 hover:text-current focus-visible:bg-current/10";

/** Where a counter sits among others the focus view moves between. */
export interface CounterFocusNavigation {
  /** Its place, from zero. */
  index: number;
  total: number;
  onMove: (by: 1 | -1) => void;
}

/** What a counter's full screen is given by the page it opens from: the
 *  name and colour it is drawn with, whether it is open where the page keeps
 *  that, and the counters it moves between. */
export interface CounterFocusHost {
  name?: string;
  color?: string | null;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  navigation?: CounterFocusNavigation;
}

export interface CounterFocusProps {
  counter: CounterShown;
  name: string;
  /** The counter's own colour, behind it, with its text in `textColor`; the
   *  page's colours without. */
  color?: string | null;
  textColor?: string;
  disabled: boolean;
  onStep: (up: boolean) => void;
  onCommit: (value: string) => void;
  onExit: () => void;
  /** Puts the counter back to its initial value, from the menu. */
  onReset?: () => void;
  /** More buttons in the header, before the menu, given the class that draws
   *  them on the counter's colours. */
  actions?: (buttonClassName: string) => ReactNode;
  /** More of the menu, after the reset. */
  menuItems?: ReactNode;
  /** The counters it moves between, with the arrows or a swipe. */
  navigation?: CounterFocusNavigation;
  /** What its name is drawn as: a heading, or a dialog's title. */
  Title?: ElementType;
}

/**
 * A counter full screen: its name, its value in its look, and two big
 * buttons that step it. Swiping sideways moves to the next counter where
 * there are others.
 */
export const CounterFocus = ({
  counter,
  name,
  color,
  textColor,
  disabled,
  onStep,
  onCommit,
  onExit,
  onReset,
  actions,
  menuItems,
  navigation,
  Title = "h1",
}: CounterFocusProps) => {
  const { t } = useTranslation("properties");
  const touchStart = useRef<{ x: number; y: number } | null>(null);
  const fg = (color && textColor) || "var(--foreground)";
  const count = Number(counter.count);
  const atMin = counter.min !== null && count <= Number(counter.min);
  const atMax = counter.max !== null && count >= Number(counter.max);
  const moving = navigation && navigation.total > 1 ? navigation : null;

  const handleTouchStart = (event: TouchEvent<HTMLDivElement>) => {
    const touch = event.touches[0];
    touchStart.current = touch ? { x: touch.clientX, y: touch.clientY } : null;
  };

  const handleTouchEnd = (event: TouchEvent<HTMLDivElement>) => {
    const start = touchStart.current;
    const touch = event.changedTouches[0];
    touchStart.current = null;
    if (!moving || !start || !touch) return;
    const dx = touch.clientX - start.x;
    const dy = touch.clientY - start.y;
    if (Math.abs(dx) < SWIPE_THRESHOLD_PX || Math.abs(dx) <= Math.abs(dy)) return;
    moving.onMove(dx < 0 ? 1 : -1);
  };

  const stepButton = (up: boolean) => (
    <Button
      type="button"
      variant="ghost"
      onClick={() => onStep(up)}
      disabled={disabled || (up ? atMax : atMin)}
      aria-label={t(up ? "input.stepUp" : "input.stepDown", { name })}
      className="h-24 touch-manipulation rounded-2xl bg-current/15 text-current shadow-sm hover:bg-current/25 hover:text-current active:bg-current/35 sm:h-28"
    >
      {up ? <Plus className="h-10 w-10" /> : <Minus className="h-10 w-10" />}
    </Button>
  );

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col"
      style={{ background: color ?? "var(--background)", color: fg }}
    >
      <header className="flex items-center justify-between gap-2 px-3 pt-[max(env(safe-area-inset-top),0.75rem)] pb-2">
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("counter.focus.exit")}
          className={CHROME_BUTTON}
          onClick={onExit}
        >
          <X className="h-5 w-5" />
        </Button>
        <Title className="min-w-0 flex-1 truncate text-center font-semibold text-lg" title={name}>
          {name}
        </Title>
        {actions?.(CHROME_BUTTON)}
        {onReset || menuItems ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                aria-label={t("counter.focus.more")}
                className={CHROME_BUTTON}
              >
                <MoreVertical className="h-5 w-5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {onReset ? (
                <DropdownMenuItem disabled={disabled} onSelect={onReset}>
                  <RotateCcw className="h-4 w-4" />
                  {t("input.reset", { name })}
                </DropdownMenuItem>
              ) : null}
              {menuItems}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </header>

      {moving ? (
        <div className="flex items-center justify-between gap-3 px-3 pb-2">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => moving.onMove(-1)}
            aria-label={t("counter.focus.previous")}
            className={CHROME_BUTTON}
          >
            <ChevronLeft className="h-5 w-5" />
          </Button>
          <span className="font-mono text-sm tabular-nums opacity-70">
            {t("counter.focus.position", { current: moving.index + 1, total: moving.total })}
          </span>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => moving.onMove(1)}
            aria-label={t("counter.focus.next")}
            className={CHROME_BUTTON}
          >
            <ChevronRight className="h-5 w-5" />
          </Button>
        </div>
      ) : null}

      <div
        className="flex min-h-0 flex-1 items-center justify-center overflow-hidden px-6 py-4"
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
      >
        <div className="flex w-full max-w-sm items-center justify-center sm:max-w-md">
          <CounterView
            counter={counter}
            name={name}
            disabled={disabled}
            textColor={fg}
            onCommit={onCommit}
            size="2xl"
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 px-3 pt-2 pb-[max(env(safe-area-inset-bottom),0.75rem)]">
        {stepButton(false)}
        {stepButton(true)}
      </div>
    </div>
  );
};

/** The focus view over the page, for a counter that has no page of its own
 *  to be full screen on: Escape or its close button closes it. */
export const CounterFocusDialog = ({
  open,
  onOpenChange,
  ...focus
}: Omit<CounterFocusProps, "onExit" | "Title"> & {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) => (
  <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
    <DialogPrimitive.Portal>
      <DialogPrimitive.Content className="fixed inset-0 z-50" aria-describedby={undefined}>
        <CounterFocus {...focus} Title={DialogPrimitive.Title} onExit={() => onOpenChange(false)} />
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  </DialogPrimitive.Root>
);
