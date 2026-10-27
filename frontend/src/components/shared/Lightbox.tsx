import { ChevronLeft, ChevronRight, X, ZoomIn, ZoomOut } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

export interface LightboxItem {
  /** Stable identity — what a caller keys on when the list changes under it. */
  id: number | string;
  src: string;
  alt: string;
  /** Drawn under the picture: a title, a byline, a date. */
  caption?: ReactNode;
}

interface LightboxProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  items: LightboxItem[];
  index: number;
  onIndexChange: (index: number) => void;
  /** Controls drawn in the top bar beside the close button — details, a
   *  download link, whatever the caller has for this picture. */
  actions?: ReactNode;
  /** Called as the reader nears the end of `items`, so a caller feeding it
   *  from a paged list can fetch the next page before they arrive. */
  onNearEnd?: () => void;
  /** Drawn beside the picture, or under it on a narrow screen: what the
   *  caller shows and edits of this one. Keys typed into it stay there. */
  panel?: ReactNode;
}

/** How far a finger has to travel, as a share of the width, before a drag is
 *  a swipe rather than a tap that wandered. */
const SWIPE_THRESHOLD = 0.2;

/** How many pictures from the end `onNearEnd` fires. */
const NEAR_END = 3;

/** The picture fits the screen at 1 and is never drawn smaller; past 6 there
 *  is nothing left to find in the pixels. */
const MIN_SCALE = 1;
const MAX_SCALE = 6;

/** Where a double tap lands, when it lands somewhere other than back at 1. */
const DOUBLE_TAP_SCALE = 2.5;

/** A tap counts as the second of a pair within this long, and this near. */
const DOUBLE_TAP_MS = 300;
const DOUBLE_TAP_SLOP = 30;

const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value));

interface Transform {
  scale: number;
  x: number;
  y: number;
}

const IDENTITY: Transform = { scale: 1, x: 0, y: 0 };

/**
 * One picture at a time, full size, with the rest a swipe away.
 *
 * Built on the same dialog every other overlay uses, so it closes the same
 * ways — Escape, the button, a tap outside the picture — and stacks correctly
 * over whatever opened it. What it adds is paging: chevrons for a pointer,
 * arrow keys for a keyboard, and for a finger a drag that follows it, so the
 * next picture is pulled in rather than summoned by a button somebody has to
 * find on a phone. A single item is simply a picture with no way to page.
 *
 * It also goes closer. Two fingers pinch, a double tap jumps in and back out,
 * a trackpad pinch or ctrl-scroll does the same with a pointer, and the
 * buttons and the `+`/`-` keys are there for anyone served by neither. While
 * the picture is larger than the screen a drag pans it rather than paging —
 * the pictures either side are reachable again as soon as it is back to size.
 *
 * The neighbours are fetched ahead of time — an `Image()` each — so arriving
 * at one is not the moment its bytes are first asked for.
 */
export const Lightbox = ({
  open,
  onOpenChange,
  items,
  index,
  onIndexChange,
  actions,
  onNearEnd,
  panel,
}: LightboxProps) => {
  const { t } = useTranslation("common");
  const count = items.length;
  const current = items[index];
  const hasPrev = index > 0;
  const hasNext = index < count - 1;

  const goTo = useCallback(
    (next: number) => {
      if (next < 0 || next >= count) return;
      onIndexChange(next);
    },
    [count, onIndexChange]
  );

  const stageRef = useRef<HTMLDivElement | null>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);

  // How far in, and where the picture has been pushed to look at that part of
  // it. At scale 1 the offsets are 0 and the picture is simply centred.
  const [transform, setTransform] = useState<Transform>(IDENTITY);
  const zoomed = transform.scale > 1;

  // Every pointer currently down on the stage, so a second finger is a pinch
  // rather than a second opinion about where the first one started.
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  // The single-pointer gesture in flight: a pan when zoomed, a swipe when not.
  const dragRef = useRef<{ startX: number; startY: number; from: Transform } | null>(null);
  const [swipeOffset, setSwipeOffset] = useState(0);
  // The pinch in flight — the finger spread and the transform it started from.
  const pinchRef = useRef<{ distance: number; midX: number; midY: number; from: Transform } | null>(
    null
  );
  const lastTap = useRef<{ time: number; x: number; y: number } | null>(null);
  // Where the press landed. A drag captures the pointer, and a captured
  // pointer's click is delivered to the stage rather than to what was under
  // it — so the click alone cannot tell the picture from the dark around it.
  const pressedPicture = useRef(false);

  /** Keeps the picture overlapping the stage: it can be pushed around, but
   *  only as far as there is picture off screen to bring back. */
  const clampToStage = useCallback((next: Transform): Transform => {
    const image = imageRef.current;
    const stage = stageRef.current;
    if (!image || !stage) return next;
    // `offsetWidth` is the laid-out size, which the transform scales about the
    // centre — so the overhang on each side is half of what scaling added.
    const maxX = Math.max(0, (image.offsetWidth * next.scale - stage.clientWidth) / 2);
    const maxY = Math.max(0, (image.offsetHeight * next.scale - stage.clientHeight) / 2);
    return { scale: next.scale, x: clamp(next.x, -maxX, maxX), y: clamp(next.y, -maxY, maxY) };
  }, []);

  const applyScale = useCallback(
    (nextScale: number, originX?: number, originY?: number) => {
      setTransform((prev) => {
        const scale = clamp(nextScale, MIN_SCALE, MAX_SCALE);
        if (scale === MIN_SCALE) return IDENTITY;
        const stage = stageRef.current?.getBoundingClientRect();
        // Zooming about the point under the fingers: the distance from the
        // centre to that point grows with the scale, so the offset has to
        // grow with it too for the pixel under them to stay put.
        const centreX = stage ? stage.left + stage.width / 2 : 0;
        const centreY = stage ? stage.top + stage.height / 2 : 0;
        const pointX = originX ?? centreX;
        const pointY = originY ?? centreY;
        const ratio = scale / prev.scale;
        return clampToStage({
          scale,
          x: pointX - centreX - (pointX - centreX - prev.x) * ratio,
          y: pointY - centreY - (pointY - centreY - prev.y) * ratio,
        });
      });
    },
    [clampToStage]
  );

  const resetZoom = useCallback(() => setTransform(IDENTITY), []);

  // A new picture, or a closed dialog, starts again at fit-to-screen.
  useEffect(() => {
    setTransform(IDENTITY);
    setSwipeOffset(0);
    pointers.current.clear();
    dragRef.current = null;
    pinchRef.current = null;
  }, [index, open]);

  // Keys work while the dialog is open, wherever focus happens to be inside it.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target;
      if (
        target instanceof Element &&
        target.closest("input, textarea, select, [contenteditable='true']")
      ) {
        return;
      }
      if (event.key === "ArrowLeft" && !zoomed) goTo(index - 1);
      else if (event.key === "ArrowRight" && !zoomed) goTo(index + 1);
      else if (event.key === "+" || event.key === "=") applyScale(transform.scale + 0.5);
      else if (event.key === "-") applyScale(transform.scale - 0.5);
      else if (event.key === "0") resetZoom();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, index, goTo, zoomed, applyScale, resetZoom, transform.scale]);

  // The neighbours, ahead of time.
  useEffect(() => {
    if (!open) return;
    for (const neighbour of [items[index - 1], items[index + 1]]) {
      if (neighbour) new Image().src = neighbour.src;
    }
  }, [open, index, items]);

  useEffect(() => {
    if (open && onNearEnd && count > 0 && index >= count - NEAR_END) onNearEnd();
  }, [open, index, count, onNearEnd]);

  const onPointerDown = (event: React.PointerEvent) => {
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    pressedPicture.current = event.target === imageRef.current;

    if (pointers.current.size === 2) {
      // A second finger ends whatever the first was doing and starts a pinch.
      dragRef.current = null;
      setSwipeOffset(0);
      const [a, b] = [...pointers.current.values()];
      pinchRef.current = {
        distance: Math.hypot(a.x - b.x, a.y - b.y),
        midX: (a.x + b.x) / 2,
        midY: (a.y + b.y) / 2,
        from: transform,
      };
      return;
    }
    if (pointers.current.size > 2) return;

    // A mouse pans a zoomed picture but never swipes one — a swipe is a
    // finger's way of paging, and a pointer has the chevrons. Nothing to drag
    // means nothing to capture: a captured pointer delivers its click to the
    // stage whatever it was aimed at, which would make every click a click on
    // the backdrop.
    if (event.pointerType === "mouse" && !zoomed) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = { startX: event.clientX, startY: event.clientY, from: transform };
  };

  const onPointerMove = (event: React.PointerEvent) => {
    if (!pointers.current.has(event.pointerId)) return;
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });

    const pinch = pinchRef.current;
    if (pinch && pointers.current.size >= 2) {
      const [a, b] = [...pointers.current.values()];
      const distance = Math.hypot(a.x - b.x, a.y - b.y);
      if (pinch.distance > 0) {
        const scale = clamp((pinch.from.scale * distance) / pinch.distance, MIN_SCALE, MAX_SCALE);
        const stage = stageRef.current?.getBoundingClientRect();
        const centreX = stage ? stage.left + stage.width / 2 : 0;
        const centreY = stage ? stage.top + stage.height / 2 : 0;
        const ratio = scale / pinch.from.scale;
        const midX = (a.x + b.x) / 2;
        const midY = (a.y + b.y) / 2;
        setTransform(
          clampToStage({
            scale,
            // Anchored under the fingers, and carried along as they move, so a
            // pinch that drifts takes the picture with it.
            x: pinch.from.x * ratio + (midX - pinch.midX) + (pinch.midX - centreX) * (1 - ratio),
            y: pinch.from.y * ratio + (midY - pinch.midY) + (pinch.midY - centreY) * (1 - ratio),
          })
        );
      }
      return;
    }

    const drag = dragRef.current;
    if (!drag) return;

    if (drag.from.scale > 1) {
      // Panning the picture rather than paging past it.
      setTransform(
        clampToStage({
          scale: drag.from.scale,
          x: drag.from.x + (event.clientX - drag.startX),
          y: drag.from.y + (event.clientY - drag.startY),
        })
      );
      return;
    }

    let offset = event.clientX - drag.startX;
    // Resistance at the ends, so the first and last picture say so by
    // refusing to go rather than by going nowhere.
    if ((offset > 0 && !hasPrev) || (offset < 0 && !hasNext)) offset /= 3;
    setSwipeOffset(offset);
  };

  const endPointer = (event: React.PointerEvent) => {
    pointers.current.delete(event.pointerId);
    if (pointers.current.size < 2) pinchRef.current = null;
    // A pinch that has ended below fit-to-screen springs back to it.
    if (pointers.current.size === 0) {
      setTransform((prev) => (prev.scale <= MIN_SCALE ? IDENTITY : prev));
    }

    const drag = dragRef.current;
    dragRef.current = null;
    if (!drag) return;

    const travelled = Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY);
    if (drag.from.scale <= 1) {
      const width = stageRef.current?.clientWidth ?? 1;
      const share = swipeOffset / width;
      setSwipeOffset(0);
      if (share <= -SWIPE_THRESHOLD && hasNext) goTo(index + 1);
      else if (share >= SWIPE_THRESHOLD && hasPrev) goTo(index - 1);
    }

    // A tap, not a drag — so it can be the half of a double tap.
    if (travelled < DOUBLE_TAP_SLOP && event.pointerType !== "mouse") {
      const now = Date.now();
      const previous = lastTap.current;
      if (
        previous &&
        now - previous.time < DOUBLE_TAP_MS &&
        Math.hypot(event.clientX - previous.x, event.clientY - previous.y) < DOUBLE_TAP_SLOP
      ) {
        lastTap.current = null;
        if (zoomed) resetZoom();
        else applyScale(DOUBLE_TAP_SCALE, event.clientX, event.clientY);
        return;
      }
      lastTap.current = { time: now, x: event.clientX, y: event.clientY };
    }
  };

  const onPointerCancel = (event: React.PointerEvent) => {
    pointers.current.delete(event.pointerId);
    dragRef.current = null;
    pinchRef.current = null;
    setSwipeOffset(0);
  };

  // A trackpad pinch arrives as ctrl+wheel; a plain wheel is left to the
  // browser so a scroll does not zoom by surprise.
  const onWheel = (event: React.WheelEvent) => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    applyScale(transform.scale * (1 - event.deltaY / 200), event.clientX, event.clientY);
  };

  if (!current) return null;

  const dragging = swipeOffset !== 0 || pointers.current.size > 0;
  const translateX = zoomed ? transform.x : swipeOffset;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="flex h-[100dvh] max-h-[100dvh] w-screen max-w-[100vw] flex-col gap-0 rounded-none border-0 bg-black/95 p-0 text-white shadow-none sm:max-w-[100vw]"
      >
        <DialogTitle className="sr-only">{current.alt || t("lightbox.title")}</DialogTitle>
        <DialogDescription className="sr-only">{t("lightbox.description")}</DialogDescription>

        {/* Top bar: where you are, and what you can do about it. */}
        <div className="flex shrink-0 items-center justify-between gap-2 px-3 py-2">
          <span className="text-white/70 text-xs tabular-nums">
            {count > 1 ? t("lightbox.position", { current: index + 1, total: count }) : null}
          </span>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              className="text-white hover:bg-white/10 hover:text-white"
              aria-label={t("lightbox.zoomOut")}
              disabled={transform.scale <= MIN_SCALE}
              onClick={() => applyScale(transform.scale - 0.5)}
            >
              <ZoomOut className="size-5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="text-white hover:bg-white/10 hover:text-white"
              aria-label={t("lightbox.zoomIn")}
              disabled={transform.scale >= MAX_SCALE}
              onClick={() => applyScale(transform.scale + 0.5)}
            >
              <ZoomIn className="size-5" />
            </Button>
            {actions}
            <Button
              variant="ghost"
              size="icon"
              className="text-white hover:bg-white/10 hover:text-white"
              aria-label={t("close")}
              onClick={() => onOpenChange(false)}
            >
              <X className="size-5" />
            </Button>
          </div>
        </div>

        <div className="flex min-h-0 flex-1 flex-col md:flex-row">
          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            {/* The stage. Unzoomed, `touch-action: pan-y` leaves vertical scrolling
                to the browser and takes horizontal for the swipe; zoomed, the
                picture takes both so a drag pans it. */}
            {/* biome-ignore lint/a11y/noStaticElementInteractions: the dialog owns
                the keyboard route out (Escape) and the close button; this is the
                pointer shortcut beside them.
                biome-ignore lint/a11y/useKeyWithClickEvents: the double click
                zooms, and the keyboard reaches that through the toolbar buttons
                and the +/-/0 keys the dialog listens for. */}
            <div
              ref={stageRef}
              className={cn(
                "relative flex min-h-0 flex-1 select-none items-center justify-center overflow-hidden",
                zoomed ? "touch-none" : "touch-pan-y"
              )}
              // Clicking the dark around the picture closes it, the way clicking
              // outside any other dialog does — the content fills the overlay
              // here, so there is no backdrop of its own left to click. Only the
              // stage itself: a click that landed on the picture or a chevron was
              // aimed at that. A zoomed picture may cover the stage entirely, so
              // this is the unzoomed shortcut only.
              onClick={(event) => {
                if (zoomed || pressedPicture.current) return;
                if (event.target === event.currentTarget) onOpenChange(false);
              }}
              onDoubleClick={(event) => {
                if (zoomed) resetZoom();
                else applyScale(DOUBLE_TAP_SCALE, event.clientX, event.clientY);
              }}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={endPointer}
              onPointerCancel={onPointerCancel}
              onWheel={onWheel}
            >
              <img
                key={current.id}
                ref={imageRef}
                src={current.src}
                alt={current.alt}
                draggable={false}
                referrerPolicy="no-referrer"
                style={{
                  transform: `translate3d(${translateX}px, ${zoomed ? transform.y : 0}px, 0) scale(${transform.scale})`,
                }}
                className={cn(
                  "max-h-full max-w-full object-contain",
                  dragging ? "transition-none" : "transition-transform duration-200 ease-out",
                  zoomed ? "cursor-grab" : undefined
                )}
              />
              {hasPrev && !zoomed && (
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={t("previous")}
                  onClick={() => goTo(index - 1)}
                  className="absolute left-2 hidden size-10 rounded-full bg-black/40 text-white hover:bg-black/60 hover:text-white sm:inline-flex"
                >
                  <ChevronLeft className="size-6" />
                </Button>
              )}
              {hasNext && !zoomed && (
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={t("next")}
                  onClick={() => goTo(index + 1)}
                  className="absolute right-2 hidden size-10 rounded-full bg-black/40 text-white hover:bg-black/60 hover:text-white sm:inline-flex"
                >
                  <ChevronRight className="size-6" />
                </Button>
              )}
            </div>

            {current.caption ? (
              <div className="shrink-0 px-4 py-3 text-center text-sm text-white/80">
                {current.caption}
              </div>
            ) : null}
          </div>
          {panel ? (
            <aside className="max-h-[40dvh] shrink-0 overflow-y-auto bg-background p-4 text-foreground md:max-h-none md:w-80">
              {panel}
            </aside>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
};
