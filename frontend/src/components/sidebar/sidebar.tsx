"use client";

import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { PanelLeft } from "lucide-react";
import * as React from "react";
import { useTranslation } from "react-i18next";

import { getItem, setItem } from "@/lib/storage";
import { Button } from "@/ui/button";
import { Input } from "@/ui/input";
import { atLeast, useWidthClass } from "@/ui/lib/useWidthClass";
import { cn } from "@/ui/lib/utils";
import { Separator } from "@/ui/separator";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/ui/sheet";
import { Skeleton } from "@/ui/skeleton";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/ui/tooltip";

//: The narrowest the column goes when the app has not said otherwise — the
//: 16rem this component has always defaulted to. Widening it is for a wiki
//: with pages filed three deep; nobody needs it narrower than the navigation
//: was designed for.
const SIDEBAR_MIN_WIDTH = 256;
//: How much of the window the column may take. Half is the point at which a
//: navigation column stops being one.
const SIDEBAR_MAX_FRACTION = 0.5;
//: Per device, not per account: how wide a column should be is a fact about
//: the screen somebody is looking at, not about who they are.
const SIDEBAR_WIDTH_KEY = "sidebar-width";

/** A CSS length in pixels, for the two units a sidebar width is ever written
 *  in. Anything else is somebody's business and not this component's. */
function toPixels(value: string | undefined): number | null {
  if (!value) return null;
  const amount = Number.parseFloat(value);
  if (!Number.isFinite(amount)) return null;
  if (value.trim().endsWith("rem")) {
    const root = Number.parseFloat(getComputedStyle(document.documentElement).fontSize);
    return Math.round(amount * (Number.isFinite(root) ? root : 16));
  }
  return Math.round(amount);
}
const SIDEBAR_WIDTH_MOBILE = "18rem";
const SIDEBAR_WIDTH_ICON = "3rem";
const SIDEBAR_KEYBOARD_SHORTCUT = "b";

// Mobile drawer swipe tuning.
const SIDEBAR_TRANSITION_MS = 300; // keep in sync with the inline transform transition
const SIDEBAR_SWIPE_THRESHOLD = 60; // px the finger must travel to commit an open/close
const SIDEBAR_SWIPE_ENGAGE = 8; // px before a gesture is treated as a horizontal drag
const SIDEBAR_EDGE_SIZE = 24; // px from the screen edge that starts a swipe-to-open

type SidebarContextProps = {
  state: "expanded" | "collapsed";
  open: boolean;
  setOpen: (open: boolean) => void;
  openMobile: boolean;
  setOpenMobile: (open: boolean) => void;
  isMobile: boolean;
  toggleSidebar: () => void;
  sidebarWidthMobile: string;
  /** How wide the column is, in pixels. */
  width: number;
  /** Whether a drag is under way, so transitions can get out of its way. */
  isResizing: boolean;
  /** Begins a drag from the sidebar's edge. */
  startResize: (event: React.PointerEvent<HTMLElement>) => void;
  /** Back to the width it has always had. */
  resetWidth: () => void;
  /** Suppress the next navigation-triggered auto-close (e.g. switching communities
   * navigates but should leave the sidebar open). Consumed once. */
  suppressNextAutoClose: () => void;
  /** Read-and-reset the suppression flag. Used by useAutoCloseSidebar. */
  consumeAutoCloseSuppression: () => boolean;
  /** Temporarily disable the mobile drawer's swipe-to-close — e.g. while a
   * community reorder drag is in progress so the two gestures don't fight. */
  setSwipeCloseLocked: (locked: boolean) => void;
  /** Whether swipe-to-close is currently locked. Read by the drawer gesture. */
  isSwipeCloseLocked: () => boolean;
};

const SidebarContext = React.createContext<SidebarContextProps | null>(null);

function useSidebar() {
  const context = React.useContext(SidebarContext);
  if (!context) {
    throw new Error("useSidebar must be used within a SidebarProvider.");
  }

  return context;
}

const SidebarProvider = React.forwardRef<
  HTMLDivElement,
  React.ComponentProps<"div"> & {
    defaultOpen?: boolean;
    open?: boolean;
    onOpenChange?: (open: boolean) => void;
  }
>(
  (
    {
      defaultOpen = true,
      open: openProp,
      onOpenChange: setOpenProp,
      className,
      style,
      children,
      ...props
    },
    ref
  ) => {
    const isMobile = !atLeast(useWidthClass(), "md");
    const [openMobile, setOpenMobile] = React.useState(false);

    // Extract sidebar-width-mobile from style prop or use default
    const sidebarWidthMobile =
      (style?.["--sidebar-width-mobile" as keyof React.CSSProperties] as string) ||
      SIDEBAR_WIDTH_MOBILE;

    // The narrowest the column goes is the width the app asked for: whatever
    // `--sidebar-width` the caller set is what the navigation was designed
    // around, so dragging only ever makes it wider.
    const minWidth = React.useMemo(
      () =>
        toPixels(style?.["--sidebar-width" as keyof React.CSSProperties] as string | undefined) ??
        SIDEBAR_MIN_WIDTH,
      [style]
    );

    // How wide the column is. Kept on the device (see SIDEBAR_WIDTH_KEY), so
    // the same person on a laptop and a desktop gets the width each screen
    // deserves rather than one answer following them around.
    const [width, setWidth] = React.useState<number>(() => {
      const saved = Number(getItem(SIDEBAR_WIDTH_KEY));
      return Number.isFinite(saved) && saved > 0 ? saved : minWidth;
    });
    const [isResizing, setIsResizing] = React.useState(false);

    const clampWidth = React.useCallback(
      (value: number) => {
        const ceiling = Math.max(minWidth, Math.round(window.innerWidth * SIDEBAR_MAX_FRACTION));
        return Math.min(Math.max(Math.round(value), minWidth), ceiling);
      },
      [minWidth]
    );

    // A window that got narrower takes the column with it: half of it is the
    // limit whatever the width was when it was last dragged. Runs on mount
    // too, so a width remembered from a wider screen arrives already inside
    // what this one can give it.
    React.useEffect(() => {
      const fitToWindow = () => setWidth((current) => clampWidth(current));
      fitToWindow();
      window.addEventListener("resize", fitToWindow);
      return () => window.removeEventListener("resize", fitToWindow);
    }, [clampWidth]);

    const startResize = React.useCallback(
      (event: React.PointerEvent<HTMLElement>) => {
        // The column is a whole drawer on a phone, and a drawer has no edge to
        // pull.
        if (isMobile || event.button !== 0) return;
        event.preventDefault();

        // Which way widening runs, read off the sidebar this rail belongs to.
        const side = event.currentTarget.closest("[data-side]")?.getAttribute("data-side");
        const towards = side === "right" ? -1 : 1;
        const startX = event.clientX;
        const startWidth = width;
        let dragged = false;

        const onPointerMove = (move: PointerEvent) => {
          const travelled = (move.clientX - startX) * towards;
          if (!dragged && Math.abs(travelled) < 3) return;
          if (!dragged) {
            dragged = true;
            setIsResizing(true);
          }
          setWidth(clampWidth(startWidth + travelled));
        };

        const onPointerUp = () => {
          window.removeEventListener("pointermove", onPointerMove);
          if (!dragged) return;
          setIsResizing(false);
          // Written once the drag is over rather than on every pixel of it.
          setWidth((settled) => {
            setItem(SIDEBAR_WIDTH_KEY, String(settled));
            return settled;
          });
        };

        window.addEventListener("pointermove", onPointerMove);
        window.addEventListener("pointerup", onPointerUp, { once: true });
      },
      [clampWidth, isMobile, width]
    );

    const resetWidth = React.useCallback(() => {
      setWidth(minWidth);
      setItem(SIDEBAR_WIDTH_KEY, String(minWidth));
    }, [minWidth]);

    // This is the internal state of the sidebar.
    // We use openProp and setOpenProp for control from outside the component.
    const [_open, _setOpen] = React.useState(defaultOpen);
    const open = openProp ?? _open;
    const setOpen = React.useCallback(
      (value: boolean | ((value: boolean) => boolean)) => {
        const openState = typeof value === "function" ? value(open) : value;
        if (setOpenProp) {
          setOpenProp(openState);
        } else {
          _setOpen(openState);
        }
      },
      [setOpenProp, open]
    );

    // Helper to toggle the sidebar.
    const toggleSidebar = React.useCallback(() => {
      return isMobile ? setOpenMobile((open) => !open) : setOpen((open) => !open);
    }, [isMobile, setOpen, setOpenMobile]);

    // One-shot flag so a navigation can opt out of the auto-close (e.g. a community
    // switch). Set synchronously before navigating; consumed by the auto-close
    // effect when the resulting pathname change fires.
    const suppressAutoCloseRef = React.useRef(false);
    const suppressNextAutoClose = React.useCallback(() => {
      suppressAutoCloseRef.current = true;
    }, []);
    const consumeAutoCloseSuppression = React.useCallback(() => {
      const suppressed = suppressAutoCloseRef.current;
      suppressAutoCloseRef.current = false;
      return suppressed;
    }, []);

    // Lets a nested drag gesture (e.g. reordering communities in the rail) suspend
    // the drawer's swipe-to-close so the two don't fight.
    const swipeCloseLockedRef = React.useRef(false);
    const setSwipeCloseLocked = React.useCallback((locked: boolean) => {
      swipeCloseLockedRef.current = locked;
    }, []);
    const isSwipeCloseLocked = React.useCallback(() => swipeCloseLockedRef.current, []);

    // Adds a keyboard shortcut to toggle the sidebar.
    React.useEffect(() => {
      const handleKeyDown = (event: KeyboardEvent) => {
        if (event.key === SIDEBAR_KEYBOARD_SHORTCUT && (event.metaKey || event.ctrlKey)) {
          event.preventDefault();
          toggleSidebar();
        }
      };

      window.addEventListener("keydown", handleKeyDown);
      return () => window.removeEventListener("keydown", handleKeyDown);
    }, [toggleSidebar]);

    // We add a state so that we can do data-state="expanded" or "collapsed".
    // This makes it easier to style the sidebar with Tailwind classes.
    const state = open ? "expanded" : "collapsed";

    const contextValue = React.useMemo<SidebarContextProps>(
      () => ({
        state,
        open,
        setOpen,
        isMobile,
        openMobile,
        setOpenMobile,
        toggleSidebar,
        sidebarWidthMobile,
        width,
        isResizing,
        startResize,
        resetWidth,
        suppressNextAutoClose,
        consumeAutoCloseSuppression,
        setSwipeCloseLocked,
        isSwipeCloseLocked,
      }),
      [
        state,
        open,
        setOpen,
        isMobile,
        openMobile,
        toggleSidebar,
        sidebarWidthMobile,
        width,
        isResizing,
        startResize,
        resetWidth,
        suppressNextAutoClose,
        consumeAutoCloseSuppression,
        setSwipeCloseLocked,
        isSwipeCloseLocked,
      ]
    );

    return (
      <SidebarContext.Provider value={contextValue}>
        <TooltipProvider delayDuration={0}>
          <div
            style={
              {
                "--sidebar-width-mobile": SIDEBAR_WIDTH_MOBILE,
                "--sidebar-width-icon": SIDEBAR_WIDTH_ICON,
                ...style,
                // Last, because what the caller wrote is the FLOOR (read into
                // `minWidth` above) and this is where the column actually is.
                "--sidebar-width": `${width}px`,
              } as React.CSSProperties
            }
            data-resizing={isResizing ? "true" : undefined}
            className={cn(
              "group/sidebar-wrapper flex min-h-svh w-full has-[[data-variant=inset]]:bg-sidebar",
              // A drag is direct manipulation: the column follows the pointer,
              // so nothing inside it may animate towards where it is going,
              // and nothing may be selected on the way past.
              "data-[resizing=true]:select-none [&[data-resizing=true]_*]:transition-none",
              className
            )}
            ref={ref}
            {...props}
          >
            {children}
          </div>
        </TooltipProvider>
      </SidebarContext.Provider>
    );
  }
);
SidebarProvider.displayName = "SidebarProvider";

type DragState = { base: "open" | "closed"; delta: number };

/**
 * Mobile off-canvas drawer with finger-following swipe gestures.
 *
 * Position is driven entirely by an inline `translateX` so the drawer can be
 * dragged open from the screen edge and closed from any point — Radix's own
 * slide keyframes are disabled (`animation: none`) to avoid the two animation
 * systems fighting (which caused the drawer to snap fully open before sliding
 * shut). We keep the Sheet mounted for the length of the close transition, then
 * unmount once it has finished sliding off-screen.
 */
const MobileSidebar = ({
  side,
  openMobile,
  setOpenMobile,
  sidebarWidthMobile,
  enableSwipeToOpen,
  isSwipeCloseLocked,
  children,
}: {
  side: "left" | "right";
  openMobile: boolean;
  setOpenMobile: (open: boolean) => void;
  sidebarWidthMobile: string;
  enableSwipeToOpen: boolean;
  isSwipeCloseLocked: () => boolean;
  children: React.ReactNode;
}) => {
  const isLeft = side === "left";
  const closedTx = isLeft ? "-100%" : "100%";

  // `mounted` controls whether the Sheet is rendered; `atOpen` is the resting
  // position (true = translateX(0)). `drag` overrides position while a finger
  // is down. They are decoupled so the close transition can play out before we
  // unmount.
  const [mounted, setMounted] = React.useState(openMobile);
  const [atOpen, setAtOpen] = React.useState(false);
  const [drag, setDrag] = React.useState<DragState | null>(null);

  const contentRef = React.useRef<HTMLDivElement>(null);
  const widthRef = React.useRef(0);
  const openMobileRef = React.useRef(openMobile);

  React.useEffect(() => {
    openMobileRef.current = openMobile;
  }, [openMobile]);

  // Sync the visual state machine to the external openMobile source of truth
  // (hamburger trigger, overlay click, auto-close-on-navigation).
  React.useEffect(() => {
    if (openMobile) {
      setMounted(true);
      const id = requestAnimationFrame(() => setAtOpen(true));
      return () => cancelAnimationFrame(id);
    }
    setAtOpen(false);
    const id = window.setTimeout(() => setMounted(false), SIDEBAR_TRANSITION_MS);
    return () => clearTimeout(id);
  }, [openMobile]);

  // Measure the drawer width once it is on screen so drag progress (used for
  // the overlay fade) is accurate; falls back to the viewport width.
  React.useEffect(() => {
    if (mounted && contentRef.current) {
      widthRef.current = contentRef.current.offsetWidth;
    }
  }, [mounted]);

  // Swipe-to-open: listen at the window level so a swipe starting on the page
  // edge can pull the drawer in even though it is unmounted.
  React.useEffect(() => {
    if (!enableSwipeToOpen) return;

    let active = false;
    let engaged = false;
    let startX = 0;
    let startY = 0;

    const onStart = (e: TouchEvent) => {
      if (openMobileRef.current) return;
      const touch = e.touches[0];
      const nearEdge = isLeft
        ? touch.clientX <= SIDEBAR_EDGE_SIZE
        : touch.clientX >= window.innerWidth - SIDEBAR_EDGE_SIZE;
      if (!nearEdge) return;
      active = true;
      engaged = false;
      startX = touch.clientX;
      startY = touch.clientY;
    };

    const onMove = (e: TouchEvent) => {
      if (!active) return;
      const touch = e.touches[0];
      const dx = touch.clientX - startX;
      const dy = touch.clientY - startY;

      if (!engaged) {
        if (Math.abs(dx) <= Math.abs(dy)) {
          // Vertical-dominant — let the page scroll.
          active = false;
          return;
        }
        const opening = isLeft ? dx > 0 : dx < 0;
        if (!opening) {
          active = false;
          return;
        }
        if (Math.abs(dx) < SIDEBAR_SWIPE_ENGAGE) return;
        engaged = true;
        setMounted(true);
      }

      e.preventDefault();
      setDrag({ base: "closed", delta: dx });
    };

    const onEnd = (e: TouchEvent) => {
      if (!active) return;
      active = false;
      if (!engaged) return;
      const dx = e.changedTouches[0].clientX - startX;
      setDrag(null);
      // Directional, mirroring the swipe-to-close handler (only commit on a
      // swipe in the opening direction).
      const shouldOpen = isLeft ? dx > SIDEBAR_SWIPE_THRESHOLD : dx < -SIDEBAR_SWIPE_THRESHOLD;
      if (shouldOpen) {
        setAtOpen(true);
        setOpenMobile(true);
      } else {
        // Cancelled — slide back closed, then unmount.
        setAtOpen(false);
        window.setTimeout(() => {
          if (!openMobileRef.current) setMounted(false);
        }, SIDEBAR_TRANSITION_MS);
      }
    };

    window.addEventListener("touchstart", onStart, { passive: true });
    window.addEventListener("touchmove", onMove, { passive: false });
    window.addEventListener("touchend", onEnd, { passive: true });
    window.addEventListener("touchcancel", onEnd, { passive: true });
    return () => {
      window.removeEventListener("touchstart", onStart);
      window.removeEventListener("touchmove", onMove);
      window.removeEventListener("touchend", onEnd);
      window.removeEventListener("touchcancel", onEnd);
    };
  }, [enableSwipeToOpen, isLeft, setOpenMobile]);

  // Swipe-to-close: gesture handlers on the drawer itself.
  const closeGesture = React.useRef({ x: 0, y: 0, active: false, engaged: false });

  const handleTouchStart = (e: React.TouchEvent) => {
    const touch = e.touches[0];
    closeGesture.current = { x: touch.clientX, y: touch.clientY, active: true, engaged: false };
  };

  const handleTouchMove = (e: React.TouchEvent) => {
    const state = closeGesture.current;
    if (!state.active) return;
    if (isSwipeCloseLocked()) {
      // A nested drag (e.g. reordering communities) owns this gesture.
      state.active = false;
      return;
    }
    const touch = e.touches[0];
    const dx = touch.clientX - state.x;
    const dy = touch.clientY - state.y;

    if (!state.engaged) {
      if (Math.abs(dx) <= Math.abs(dy)) return; // allow vertical scrolling
      const closing = isLeft ? dx < 0 : dx > 0;
      if (!closing) {
        state.active = false;
        return;
      }
      if (Math.abs(dx) < SIDEBAR_SWIPE_ENGAGE) return;
      state.engaged = true;
    }

    e.preventDefault();
    setDrag({ base: "open", delta: dx });
  };

  const handleTouchEnd = (e: React.TouchEvent) => {
    const state = closeGesture.current;
    if (!state.active) return;
    state.active = false;
    if (!state.engaged) return;
    const dx = e.changedTouches[0].clientX - state.x;
    const shouldClose = isLeft ? dx < -SIDEBAR_SWIPE_THRESHOLD : dx > SIDEBAR_SWIPE_THRESHOLD;
    setDrag(null);
    if (shouldClose) {
      setAtOpen(false);
      setOpenMobile(false);
    }
    // Otherwise atOpen stays true and the drawer animates back open.
  };

  if (!mounted) return null;

  const dragging = drag !== null;
  const transform = dragging
    ? `translateX(clamp(${isLeft ? closedTx : "0%"}, calc(${
        drag.base === "open" ? "0%" : closedTx
      } + ${drag.delta}px), ${isLeft ? "0%" : closedTx}))`
    : `translateX(${atOpen ? "0%" : closedTx})`;

  // Overlay opacity tracks how open the drawer is.
  let progress = atOpen ? 1 : 0;
  if (dragging) {
    const width = widthRef.current || window.innerWidth;
    const moved = Math.min(Math.abs(drag.delta), width) / width;
    progress = drag.base === "closed" ? moved : 1 - moved;
  }

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/80"
        style={{
          opacity: progress,
          transition: dragging ? "none" : `opacity ${SIDEBAR_TRANSITION_MS}ms ease-out`,
          pointerEvents: progress > 0 ? "auto" : "none",
        }}
        onClick={() => setOpenMobile(false)}
        aria-hidden="true"
      />
      <Sheet open={mounted} onOpenChange={setOpenMobile} modal={false}>
        <SheetContent
          ref={contentRef}
          data-sidebar="sidebar"
          data-mobile="true"
          className="bg-sidebar p-0 text-sidebar-foreground [&>button]:hidden"
          style={{
            width: sidebarWidthMobile,
            maxWidth: sidebarWidthMobile,
            height: "100dvh",
            maxHeight: "100dvh",
            transform,
            transition: dragging ? "none" : `transform ${SIDEBAR_TRANSITION_MS}ms ease-out`,
            animation: "none",
          }}
          side={side}
          // Don't pull focus into the drawer on open: Radix would focus the
          // first control (the community expand toggle), and its focus-triggered
          // tooltip would then stay stuck open until the user taps elsewhere.
          onOpenAutoFocus={(e) => e.preventDefault()}
          // Don't let the Sheet dismiss itself on outside interaction. Nested
          // poppers (the user-footer dropdown, tooltips, selects) portal to the
          // body, so opening one reads as a focus/pointer event "outside" the
          // drawer and would otherwise collapse it. Tap-outside-to-close is
          // already handled by the custom overlay below, plus swipe and the X.
          onInteractOutside={(e) => e.preventDefault()}
          onTouchStart={handleTouchStart}
          onTouchMove={handleTouchMove}
          onTouchEnd={handleTouchEnd}
        >
          <SheetHeader className="sr-only">
            <SheetTitle>Sidebar</SheetTitle>
            <SheetDescription>Displays the mobile sidebar.</SheetDescription>
          </SheetHeader>
          <div className="flex h-full w-full flex-col">{children}</div>
        </SheetContent>
      </Sheet>
    </>
  );
};

const Sidebar = React.forwardRef<
  HTMLDivElement,
  React.ComponentProps<"div"> & {
    side?: "left" | "right";
    variant?: "sidebar" | "floating" | "inset";
    collapsible?: "offcanvas" | "icon" | "none";
    enableSwipeToOpen?: boolean;
  }
>(
  (
    {
      side = "left",
      variant = "sidebar",
      collapsible = "offcanvas",
      enableSwipeToOpen = side === "left",
      className,
      children,
      ...props
    },
    ref
  ) => {
    const { isMobile, state, openMobile, setOpenMobile, sidebarWidthMobile, isSwipeCloseLocked } =
      useSidebar();

    if (collapsible === "none") {
      return (
        <div
          className={cn(
            // `relative` so the edge has something to hang off: this column
            // cannot be folded away, but it can still be made wider.
            "relative flex h-full w-(--sidebar-width) flex-col bg-sidebar text-sidebar-foreground",
            className
          )}
          ref={ref}
          {...props}
        >
          {children}
          <SidebarResizeHandle side={side} collapsible={collapsible} />
        </div>
      );
    }

    if (isMobile) {
      return (
        <MobileSidebar
          side={side}
          openMobile={openMobile}
          setOpenMobile={setOpenMobile}
          sidebarWidthMobile={sidebarWidthMobile}
          enableSwipeToOpen={enableSwipeToOpen}
          isSwipeCloseLocked={isSwipeCloseLocked}
        >
          {children}
        </MobileSidebar>
      );
    }

    return (
      <div
        ref={ref}
        className="group peer hidden text-sidebar-foreground md:block"
        data-state={state}
        data-collapsible={state === "collapsed" ? collapsible : ""}
        data-variant={variant}
        data-side={side}
      >
        {/* This is what handles the sidebar gap on desktop */}
        <div
          className={cn(
            "relative w-(--sidebar-width) bg-transparent transition-[width] duration-200 ease-linear",
            "group-data-[collapsible=offcanvas]:w-0",
            "group-data-[side=right]:rotate-180",
            variant === "floating" || variant === "inset"
              ? "group-data-[collapsible=icon]:w-[calc(var(--sidebar-width-icon)_+_theme(spacing.4))]"
              : "group-data-[collapsible=icon]:w-(--sidebar-width-icon)"
          )}
        />
        <div
          className={cn(
            "fixed inset-y-0 z-10 hidden h-svh w-(--sidebar-width) transition-[left,right,width] duration-200 ease-linear md:flex",
            side === "left"
              ? "left-0 group-data-[collapsible=offcanvas]:left-[calc(var(--sidebar-width)*-1)]"
              : "right-0 group-data-[collapsible=offcanvas]:right-[calc(var(--sidebar-width)*-1)]",
            // Adjust the padding for floating and inset variants.
            variant === "floating" || variant === "inset"
              ? "p-2 group-data-[collapsible=icon]:w-[calc(var(--sidebar-width-icon)_+_theme(spacing.4)_+2px)]"
              : "group-data-[collapsible=icon]:w-(--sidebar-width-icon) group-data-[side=left]:border-r group-data-[side=right]:border-l",
            className
          )}
          {...props}
        >
          <div
            data-sidebar="sidebar"
            className="flex h-full w-full flex-col bg-sidebar group-data-[variant=floating]:rounded-lg group-data-[variant=floating]:border group-data-[variant=floating]:border-sidebar-border group-data-[variant=floating]:shadow"
          >
            {children}
          </div>
          <SidebarResizeHandle side={side} collapsible={collapsible} />
        </div>
      </div>
    );
  }
);
Sidebar.displayName = "Sidebar";

interface SidebarTriggerProps extends React.ComponentProps<typeof Button> {
  icon: React.ReactNode;
}

/**
 * The edge you pull to decide how wide the navigation is.
 *
 * It sits on the inner edge of the column, is invisible until a pointer is
 * near it, and does one thing — a click toggles nothing, because folding the
 * column away already has a control and a keystroke. Double-click puts the
 * width back to what the app asked for.
 *
 * Not offered on a phone: there the column is a whole drawer, and a drawer has
 * no edge to pull.
 */
const SidebarResizeHandle = ({
  side,
  collapsible,
}: {
  side: "left" | "right";
  collapsible: "offcanvas" | "icon" | "none";
}) => {
  const { t } = useTranslation("nav");
  const { startResize, resetWidth, isResizing, isMobile, state } = useSidebar();

  // Nothing to size while the column is folded away — and a column that cannot
  // fold is never folded, whatever the toggle thinks.
  if (isMobile || (collapsible !== "none" && state === "collapsed")) return null;

  return (
    <button
      type="button"
      data-sidebar="resize"
      aria-label={t("sidebar.resize")}
      title={t("sidebar.resize")}
      tabIndex={-1}
      onPointerDown={startResize}
      onDoubleClick={resetWidth}
      className={cn(
        "absolute inset-y-0 z-20 hidden w-2 cursor-col-resize touch-none md:block",
        side === "left" ? "right-0" : "left-0",
        // A line under the pointer, and while the drag is on: enough to say
        // the edge is a thing you can take hold of, not enough to draw a
        // border down a column that already has one.
        "after:absolute after:inset-y-0 after:left-1/2 after:w-[2px] after:-translate-x-1/2 hover:after:bg-sidebar-border",
        isResizing && "after:bg-sidebar-border"
      )}
    />
  );
};

const SidebarTrigger = React.forwardRef<React.ElementRef<typeof Button>, SidebarTriggerProps>(
  ({ className, onClick, icon, ...props }, ref) => {
    const { toggleSidebar } = useSidebar();
    const Icon = icon || <PanelLeft />;

    return (
      <Button
        ref={ref}
        data-sidebar="trigger"
        variant="ghost"
        size="icon"
        className={cn("h-7 w-7", className)}
        onClick={(event) => {
          onClick?.(event);
          toggleSidebar();
        }}
        {...props}
      >
        {Icon}
        <span className="sr-only">Toggle Sidebar</span>
      </Button>
    );
  }
);
SidebarTrigger.displayName = "SidebarTrigger";

const SidebarRail = React.forwardRef<HTMLButtonElement, React.ComponentProps<"button">>(
  ({ className, ...props }, ref) => {
    const { toggleSidebar } = useSidebar();

    return (
      <button
        ref={ref}
        data-sidebar="rail"
        aria-label="Toggle Sidebar"
        tabIndex={-1}
        onClick={toggleSidebar}
        title="Toggle Sidebar"
        className={cn(
          "absolute inset-y-0 z-20 hidden w-4 -translate-x-1/2 transition-all ease-linear after:absolute after:inset-y-0 after:left-1/2 after:w-[2px] hover:after:bg-sidebar-border group-data-[side=left]:-right-4 group-data-[side=right]:left-0 sm:flex",
          "[[data-side=left]_&]:cursor-w-resize [[data-side=right]_&]:cursor-e-resize",
          "[[data-side=left][data-state=collapsed]_&]:cursor-e-resize [[data-side=right][data-state=collapsed]_&]:cursor-w-resize",
          "group-data-[collapsible=offcanvas]:translate-x-0 group-data-[collapsible=offcanvas]:hover:bg-sidebar group-data-[collapsible=offcanvas]:after:left-full",
          "[[data-side=left][data-collapsible=offcanvas]_&]:-right-2",
          "[[data-side=right][data-collapsible=offcanvas]_&]:-left-2",
          className
        )}
        {...props}
      />
    );
  }
);
SidebarRail.displayName = "SidebarRail";

const SidebarInset = React.forwardRef<HTMLDivElement, React.ComponentProps<"main">>(
  ({ className, ...props }, ref) => {
    return (
      <main
        ref={ref}
        className={cn(
          "relative flex w-full flex-1 flex-col bg-background",
          "md:peer-data-[state=collapsed]:peer-data-[variant=inset]:ml-2 md:peer-data-[variant=inset]:m-2 md:peer-data-[variant=inset]:ml-0 md:peer-data-[variant=inset]:rounded-xl md:peer-data-[variant=inset]:shadow",
          className
        )}
        {...props}
      />
    );
  }
);
SidebarInset.displayName = "SidebarInset";

const SidebarInput = React.forwardRef<
  React.ElementRef<typeof Input>,
  React.ComponentProps<typeof Input>
>(({ className, ...props }, ref) => {
  return (
    <Input
      ref={ref}
      data-sidebar="input"
      className={cn(
        "h-8 w-full bg-background shadow-none focus-visible:ring-2 focus-visible:ring-sidebar-ring",
        className
      )}
      {...props}
    />
  );
});
SidebarInput.displayName = "SidebarInput";

const SidebarHeader = React.forwardRef<HTMLDivElement, React.ComponentProps<"div">>(
  ({ className, ...props }, ref) => {
    return (
      <div
        ref={ref}
        data-sidebar="header"
        className={cn("flex flex-col gap-2 p-2", className)}
        {...props}
      />
    );
  }
);
SidebarHeader.displayName = "SidebarHeader";

const SidebarFooter = React.forwardRef<HTMLDivElement, React.ComponentProps<"div">>(
  ({ className, ...props }, ref) => {
    return (
      <div
        ref={ref}
        data-sidebar="footer"
        className={cn("flex flex-col gap-2 p-2", className)}
        {...props}
      />
    );
  }
);
SidebarFooter.displayName = "SidebarFooter";

const SidebarSeparator = React.forwardRef<
  React.ElementRef<typeof Separator>,
  React.ComponentProps<typeof Separator>
>(({ className, ...props }, ref) => {
  return (
    <Separator
      ref={ref}
      data-sidebar="separator"
      className={cn("mx-2 w-auto bg-sidebar-border", className)}
      {...props}
    />
  );
});
SidebarSeparator.displayName = "SidebarSeparator";

const SidebarContent = React.forwardRef<HTMLDivElement, React.ComponentProps<"div">>(
  ({ className, ...props }, ref) => {
    return (
      <div
        ref={ref}
        data-sidebar="content"
        className={cn(
          "flex min-h-0 flex-1 flex-col gap-2 overflow-auto group-data-[collapsible=icon]:overflow-hidden",
          className
        )}
        {...props}
      />
    );
  }
);
SidebarContent.displayName = "SidebarContent";

const SidebarGroup = React.forwardRef<HTMLDivElement, React.ComponentProps<"div">>(
  ({ className, ...props }, ref) => {
    return (
      <div
        ref={ref}
        data-sidebar="group"
        className={cn("relative flex w-full min-w-0 flex-col p-2", className)}
        {...props}
      />
    );
  }
);
SidebarGroup.displayName = "SidebarGroup";

const SidebarGroupLabel = React.forwardRef<
  HTMLDivElement,
  React.ComponentProps<"div"> & { asChild?: boolean }
>(({ className, asChild = false, ...props }, ref) => {
  const Comp = asChild ? Slot : "div";

  return (
    <Comp
      ref={ref}
      data-sidebar="group-label"
      className={cn(
        "flex h-8 shrink-0 items-center rounded-md px-2 font-medium text-sidebar-foreground/70 text-xs outline-none ring-sidebar-ring transition-[margin,opacity] duration-200 ease-linear focus-visible:ring-2 [&>svg]:size-4 [&>svg]:shrink-0",
        "group-data-[collapsible=icon]:-mt-8 group-data-[collapsible=icon]:opacity-0",
        className
      )}
      {...props}
    />
  );
});
SidebarGroupLabel.displayName = "SidebarGroupLabel";

const SidebarGroupAction = React.forwardRef<
  HTMLButtonElement,
  React.ComponentProps<"button"> & { asChild?: boolean }
>(({ className, asChild = false, ...props }, ref) => {
  const Comp = asChild ? Slot : "button";

  return (
    <Comp
      ref={ref}
      data-sidebar="group-action"
      className={cn(
        "absolute top-3.5 right-3 flex aspect-square w-5 items-center justify-center rounded-md p-0 text-sidebar-foreground outline-none ring-sidebar-ring transition-transform hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 [&>svg]:size-4 [&>svg]:shrink-0",
        // Increases the hit area of the button on mobile.
        "after:absolute after:-inset-2 after:md:hidden",
        "group-data-[collapsible=icon]:hidden",
        className
      )}
      {...props}
    />
  );
});
SidebarGroupAction.displayName = "SidebarGroupAction";

const SidebarGroupContent = React.forwardRef<HTMLDivElement, React.ComponentProps<"div">>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      data-sidebar="group-content"
      className={cn("w-full text-sm", className)}
      {...props}
    />
  )
);
SidebarGroupContent.displayName = "SidebarGroupContent";

const SidebarMenu = React.forwardRef<HTMLUListElement, React.ComponentProps<"ul">>(
  ({ className, ...props }, ref) => (
    <ul
      ref={ref}
      data-sidebar="menu"
      className={cn("flex w-full min-w-0 flex-col gap-1", className)}
      {...props}
    />
  )
);
SidebarMenu.displayName = "SidebarMenu";

const SidebarMenuItem = React.forwardRef<HTMLLIElement, React.ComponentProps<"li">>(
  ({ className, ...props }, ref) => (
    <li
      ref={ref}
      data-sidebar="menu-item"
      className={cn("group/menu-item relative", className)}
      {...props}
    />
  )
);
SidebarMenuItem.displayName = "SidebarMenuItem";

const sidebarMenuButtonVariants = cva(
  "peer/menu-button group-data-[collapsible=icon]:!size-8 group-data-[collapsible=icon]:!p-2 flex w-full items-center gap-2 overflow-hidden rounded-md p-2 text-left text-sm outline-none ring-sidebar-ring transition-[width,height,padding] hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 active:bg-sidebar-accent active:text-sidebar-accent-foreground disabled:pointer-events-none disabled:opacity-50 group-has-[[data-sidebar=menu-action]]/menu-item:pr-8 aria-disabled:pointer-events-none aria-disabled:opacity-50 data-[active=true]:bg-sidebar-accent data-[active=true]:font-medium data-[active=true]:text-sidebar-accent-foreground data-[state=open]:hover:bg-sidebar-accent data-[state=open]:hover:text-sidebar-accent-foreground [&>span:last-child]:truncate [&>svg]:size-4 [&>svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
        outline:
          "bg-background shadow-[0_0_0_1px_hsl(var(--sidebar-border))] hover:bg-sidebar-accent hover:text-sidebar-accent-foreground hover:shadow-[0_0_0_1px_hsl(var(--sidebar-accent))]",
      },
      size: {
        default: "h-8 text-sm",
        sm: "h-7 text-xs",
        lg: "group-data-[collapsible=icon]:!p-0 h-12 text-sm",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

const SidebarMenuButton = React.forwardRef<
  HTMLButtonElement,
  React.ComponentProps<"button"> & {
    asChild?: boolean;
    isActive?: boolean;
    tooltip?: string | React.ComponentProps<typeof TooltipContent>;
  } & VariantProps<typeof sidebarMenuButtonVariants>
>(
  (
    {
      asChild = false,
      isActive = false,
      variant = "default",
      size = "default",
      tooltip,
      className,
      ...props
    },
    ref
  ) => {
    const Comp = asChild ? Slot : "button";
    const { isMobile, state } = useSidebar();

    const button = (
      <Comp
        ref={ref}
        data-sidebar="menu-button"
        data-size={size}
        data-active={isActive}
        className={cn(sidebarMenuButtonVariants({ variant, size }), className)}
        {...props}
      />
    );

    if (!tooltip) {
      return button;
    }

    if (typeof tooltip === "string") {
      tooltip = {
        children: tooltip,
      };
    }

    return (
      <Tooltip>
        <TooltipTrigger asChild>{button}</TooltipTrigger>
        <TooltipContent
          side="right"
          align="center"
          hidden={state !== "collapsed" || isMobile}
          {...tooltip}
        />
      </Tooltip>
    );
  }
);
SidebarMenuButton.displayName = "SidebarMenuButton";

const SidebarMenuAction = React.forwardRef<
  HTMLButtonElement,
  React.ComponentProps<"button"> & {
    asChild?: boolean;
    showOnHover?: boolean;
  }
>(({ className, asChild = false, showOnHover = false, ...props }, ref) => {
  const Comp = asChild ? Slot : "button";

  return (
    <Comp
      ref={ref}
      data-sidebar="menu-action"
      className={cn(
        "absolute top-1.5 right-1 flex aspect-square w-5 items-center justify-center rounded-md p-0 text-sidebar-foreground outline-none ring-sidebar-ring transition-transform hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 peer-hover/menu-button:text-sidebar-accent-foreground [&>svg]:size-4 [&>svg]:shrink-0",
        // Increases the hit area of the button on mobile.
        "after:absolute after:-inset-2 after:md:hidden",
        "peer-data-[size=sm]/menu-button:top-1",
        "peer-data-[size=default]/menu-button:top-1.5",
        "peer-data-[size=lg]/menu-button:top-2.5",
        "group-data-[collapsible=icon]:hidden",
        showOnHover &&
          "group-focus-within/menu-item:opacity-100 group-hover/menu-item:opacity-100 data-[state=open]:opacity-100 peer-data-[active=true]/menu-button:text-sidebar-accent-foreground md:opacity-0",
        className
      )}
      {...props}
    />
  );
});
SidebarMenuAction.displayName = "SidebarMenuAction";

const SidebarMenuBadge = React.forwardRef<HTMLDivElement, React.ComponentProps<"div">>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      data-sidebar="menu-badge"
      className={cn(
        "pointer-events-none absolute right-1 flex h-5 min-w-5 select-none items-center justify-center rounded-md px-1 font-medium text-sidebar-foreground text-xs tabular-nums",
        "peer-hover/menu-button:text-sidebar-accent-foreground peer-data-[active=true]/menu-button:text-sidebar-accent-foreground",
        "peer-data-[size=sm]/menu-button:top-1",
        "peer-data-[size=default]/menu-button:top-1.5",
        "peer-data-[size=lg]/menu-button:top-2.5",
        "group-data-[collapsible=icon]:hidden",
        className
      )}
      {...props}
    />
  )
);
SidebarMenuBadge.displayName = "SidebarMenuBadge";

const SidebarMenuSkeleton = React.forwardRef<
  HTMLDivElement,
  React.ComponentProps<"div"> & {
    showIcon?: boolean;
  }
>(({ className, showIcon = false, ...props }, ref) => {
  // Random width between 50 to 90%.
  const width = React.useMemo(() => {
    return `${Math.floor(Math.random() * 40) + 50}%`;
  }, []);

  return (
    <div
      ref={ref}
      data-sidebar="menu-skeleton"
      className={cn("flex h-8 items-center gap-2 rounded-md px-2", className)}
      {...props}
    >
      {showIcon && <Skeleton className="size-4 rounded-md" data-sidebar="menu-skeleton-icon" />}
      <Skeleton
        className="h-4 max-w-(--skeleton-width) flex-1"
        data-sidebar="menu-skeleton-text"
        style={
          {
            "--skeleton-width": width,
          } as React.CSSProperties
        }
      />
    </div>
  );
});
SidebarMenuSkeleton.displayName = "SidebarMenuSkeleton";

const SidebarMenuSub = React.forwardRef<HTMLUListElement, React.ComponentProps<"ul">>(
  ({ className, ...props }, ref) => (
    <ul
      ref={ref}
      data-sidebar="menu-sub"
      className={cn(
        "mx-3.5 flex min-w-0 translate-x-px flex-col gap-1 border-sidebar-border border-l px-2.5 py-0.5",
        "group-data-[collapsible=icon]:hidden",
        className
      )}
      {...props}
    />
  )
);
SidebarMenuSub.displayName = "SidebarMenuSub";

const SidebarMenuSubItem = React.forwardRef<HTMLLIElement, React.ComponentProps<"li">>(
  ({ ...props }, ref) => <li ref={ref} {...props} />
);
SidebarMenuSubItem.displayName = "SidebarMenuSubItem";

const SidebarMenuSubButton = React.forwardRef<
  HTMLAnchorElement,
  React.ComponentProps<"a"> & {
    asChild?: boolean;
    size?: "sm" | "md";
    isActive?: boolean;
  }
>(({ asChild = false, size = "md", isActive, className, ...props }, ref) => {
  const Comp = asChild ? Slot : "a";

  return (
    <Comp
      ref={ref}
      data-sidebar="menu-sub-button"
      data-size={size}
      data-active={isActive}
      className={cn(
        "flex h-7 min-w-0 -translate-x-px items-center gap-2 overflow-hidden rounded-md px-2 text-sidebar-foreground outline-none ring-sidebar-ring hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 active:bg-sidebar-accent active:text-sidebar-accent-foreground disabled:pointer-events-none disabled:opacity-50 aria-disabled:pointer-events-none aria-disabled:opacity-50 [&>span:last-child]:truncate [&>svg]:size-4 [&>svg]:shrink-0 [&>svg]:text-sidebar-accent-foreground",
        "data-[active=true]:bg-sidebar-accent data-[active=true]:text-sidebar-accent-foreground",
        size === "sm" && "text-xs",
        size === "md" && "text-sm",
        "group-data-[collapsible=icon]:hidden",
        className
      )}
      {...props}
    />
  );
});
SidebarMenuSubButton.displayName = "SidebarMenuSubButton";

export {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupAction,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInput,
  SidebarInset,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSkeleton,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  SidebarProvider,
  SidebarRail,
  SidebarSeparator,
  SidebarTrigger,
  useSidebar,
};
