/**
 * A pop-up: something that stays on screen while a person moves around the
 * app. It rests as a pill in the corner, as its panel, or as both in turn: a
 * pill with a button that opens the panel, and the panel's close sending it
 * back to the pill. A pop-up with no pill is a panel alone, and closing it is
 * its owner's cue to stop drawing it.
 *
 * Pills and panels are drawn into the dock, which the app places once above its
 * corner buttons. Below `sm` a panel is a drawer up from the bottom of the
 * screen; from `sm` it is a card in the dock. Either way the page stays usable
 * behind it.
 *
 * ```tsx
 * <PopUp>
 *   <PopUpPill aria-label="Timer">
 *     <span>24:13</span>
 *     <PopUpTrigger asChild>
 *       <Button variant="ghost" size="icon" aria-label="Settings"><Settings /></Button>
 *     </PopUpTrigger>
 *   </PopUpPill>
 *   <PopUpPanel title="Timer">…</PopUpPanel>
 * </PopUp>
 * ```
 */

import * as React from "react";
import { createPortal } from "react-dom";

import { cn } from "@/ui/lib/utils";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/ui/sheet";

/** A pill's look: the dock's pills and the bottom navigation share it. */
export const pillClassName =
  "pointer-events-auto flex items-center gap-1 rounded-full border bg-card/90 p-1 shadow-lg backdrop-blur supports-backdrop-filter:bg-card/70";

let dock: HTMLElement | null = null;
const listeners = new Set<() => void>();

const setDock = (element: HTMLElement | null) => {
  dock = element;
  for (const listener of listeners) listener();
};

const useDock = () =>
  React.useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => dock,
    () => null
  );

/** Where pop-ups are drawn. The app places one, above its corner buttons. */
export const PopUpDock = ({ className }: { className?: string }) => (
  <div ref={setDock} className={cn("flex flex-col items-end gap-2 empty:hidden", className)} />
);

const PopUpOpenContext = React.createContext(false);

interface PopUpProps {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: React.ReactNode;
}

/** One pop-up: its pill, its panel, or both. Open means the panel shows. */
export const PopUp = ({
  open: openProp,
  defaultOpen = false,
  onOpenChange,
  children,
}: PopUpProps) => {
  const [uncontrolled, setUncontrolled] = React.useState(defaultOpen);
  const open = openProp ?? uncontrolled;
  const setOpen = (next: boolean) => {
    if (openProp === undefined) setUncontrolled(next);
    onOpenChange?.(next);
  };
  return (
    <PopUpOpenContext value={open}>
      <Sheet modal={false} open={open} onOpenChange={setOpen}>
        {children}
      </Sheet>
    </PopUpOpenContext>
  );
};

/** Opens the panel; it usually sits in the pill. */
export const PopUpTrigger = SheetTrigger;

/**
 * The pill, while the panel is closed. It is hidden rather than removed while
 * the panel shows, so closing the panel returns focus to the button in it.
 */
export const PopUpPill = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => {
  const target = useDock();
  const open = React.useContext(PopUpOpenContext);
  if (!target) return null;
  return createPortal(
    <div hidden={open} className={cn(pillClassName, className)} {...props} />,
    target
  );
};

type PopUpPanelProps = Omit<
  React.ComponentPropsWithoutRef<typeof SheetContent>,
  "side" | "container" | "title"
> & { title: React.ReactNode };

/** The panel: a drawer on a phone, a card in the dock from `sm`. */
export const PopUpPanel = ({ title, className, children, ...props }: PopUpPanelProps) => {
  const target = useDock();
  if (!target) return null;
  return (
    <SheetContent
      side="bottom"
      container={target}
      aria-describedby={undefined}
      // The page stays usable beside it, so working the page leaves it open.
      onInteractOutside={(event) => event.preventDefault()}
      className={cn(
        "pointer-events-auto flex max-h-[80dvh] flex-col gap-4 overflow-y-auto pb-[calc(var(--safe-area-inset-bottom)+1.5rem)]",
        "sm:relative sm:inset-auto sm:max-h-[min(36rem,calc(100dvh-8rem))] sm:w-96 sm:rounded-lg sm:border sm:pb-6",
        className
      )}
      {...props}
    >
      <SheetHeader className="pr-8 text-left">
        <SheetTitle className="text-base">{title}</SheetTitle>
      </SheetHeader>
      {children}
    </SheetContent>
  );
};
