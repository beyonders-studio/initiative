import { ChevronLeft, ChevronRight, MoreHorizontal } from "lucide-react";
import {
  type ComponentProps,
  createContext,
  Fragment,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import { Button } from "@/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";
import { cn } from "@/ui/lib/utils";

/**
 * How many items of a single row fit, given the width the row actually has.
 *
 * Widths are read from the laid-out row and remembered against each item's id,
 * because an item that has been put away measures nothing — and putting items
 * away is the whole point. Keying on id rather than position means a row whose
 * contents swap (an editor toolbar entering a code block, say) measures the
 * new items rather than reusing the old ones' widths.
 *
 * Where there is no layout to read (a row that has not been painted, a test
 * environment), everything stays in the row: showing too much is a far better
 * failure than hiding something with nowhere to reach it.
 *
 * Room for the control that holds the overflow is not reserved here. That
 * control is a sibling of the row rather than one of its children, so it takes
 * its width out of the row's before any of this runs — layout does the
 * reserving, and there is no width left to guess.
 */
export const useRowCapacity = (ids: string[]) => {
  const rowRef = useRef<HTMLDivElement>(null);
  const widths = useRef<Map<string, number>>(new Map());
  const [fits, setFits] = useState(ids.length);

  // The measurement runs from an effect, after the items it should measure
  // have rendered — so it reads the ids from a ref rather than closing over
  // an array that is a new one on every render.
  const idsRef = useRef(ids);
  idsRef.current = ids;
  const signature = ids.join("\n");

  const measure = useCallback(() => {
    const row = rowRef.current;
    if (!row) return;

    const current = idsRef.current;
    const children = Array.from(row.children) as HTMLElement[];
    current.forEach((id, index) => {
      const width = children[index]?.offsetWidth ?? 0;
      if (width > 0) widths.current.set(id, width);
    });

    const known = current.map((id) => widths.current.get(id) ?? 0);
    if (known.some((width) => !width)) {
      setFits(current.length);
      return;
    }

    const gap = Number.parseFloat(getComputedStyle(row).columnGap) || 0;
    const available = row.clientWidth;
    const total = known.reduce((sum, width) => sum + width + gap, -gap);
    if (total <= available) {
      setFits(current.length);
      return;
    }

    let used = 0;
    let fitted = 0;
    for (const width of known) {
      if (used + width > available) break;
      used += width + gap;
      fitted += 1;
    }
    setFits(fitted);
    // `signature` rather than `ids`: the array is a new one every render, and
    // what matters is whether the items in it changed.
  }, [signature]);

  // `fits` is a dependency so the pass that puts the overflow control on screen
  // is followed by one that measures against the narrower row it left behind.
  useLayoutEffect(measure, [measure, fits]);

  useEffect(() => {
    const row = rowRef.current;
    if (!row || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(row);
    // The items too, not only the row: a control can grow without the row
    // doing so — the block-type picker names the block the caret is in, and
    // "Numbered list" is wider than "H1". The row is parent-determined, so
    // nothing about that reaches an observer watching only the row, and the
    // control would be clipped rather than shed until the next resize.
    for (const child of Array.from(row.children)) observer.observe(child);
    return () => observer.disconnect();
  }, [measure]);

  return { rowRef, fits };
};

/**
 * Which branch of the overflow menu is open, and how to open one.
 *
 * `null` is the top of the menu. A branch, once opened, provides `null` again
 * to its own children, so the entries inside it render exactly as they would at
 * the top — that is the whole of the drill-down.
 */
const DrilldownContext = createContext<{
  open: string | null;
  setOpen: (id: string | null) => void;
}>({ open: null, setOpen: () => {} });

/**
 * One entry of the overflow menu.
 *
 * It renders only where it belongs: at the top of the menu, or inside whichever
 * branch is open. Use it instead of a bare `DropdownMenuItem` for anything the
 * toolbar hands to `OverflowToolbar` directly.
 */
export const OverflowMenuItem = ({
  children,
  ...props
}: ComponentProps<typeof DropdownMenuItem>) => {
  const { open } = useContext(DrilldownContext);
  if (open !== null) return null;
  return <DropdownMenuItem {...props}>{children}</DropdownMenuItem>;
};

/**
 * A branch of the overflow menu, for a control that is itself a list of
 * choices — a block-type picker, a palette, a group of number formats.
 *
 * It drills down rather than flying out to the side: a fly-out has to fit
 * beside a menu that is already there, which on a phone leaves it less room
 * than it needs and cuts it off. Opening a branch replaces the menu's contents
 * instead, so a branch always has the whole width the menu has.
 */
export const OverflowSubmenu = ({
  id,
  icon,
  label,
  className,
  children,
}: {
  /** Distinguishes this branch from its siblings. */
  id: string;
  icon?: ReactNode;
  label: string;
  className?: string;
  children: ReactNode;
}) => {
  const { open, setOpen } = useContext(DrilldownContext);

  if (open === null) {
    return (
      <DropdownMenuItem
        // The menu stays open: selecting this goes deeper rather than acting.
        onSelect={(event) => {
          event.preventDefault();
          setOpen(id);
        }}
      >
        {icon}
        <span className="flex-1">{label}</span>
        <ChevronRight className="size-4 text-muted-foreground" aria-hidden />
      </DropdownMenuItem>
    );
  }

  if (open !== id) return null;

  return (
    <DrilldownContext.Provider value={{ open: null, setOpen }}>
      <DropdownMenuItem
        onSelect={(event) => {
          event.preventDefault();
          setOpen(null);
        }}
      >
        <ChevronLeft className="size-4 text-muted-foreground" aria-hidden />
        <span className="font-medium">{label}</span>
      </DropdownMenuItem>
      <DropdownMenuSeparator />
      <div className={className}>{children}</div>
    </DrilldownContext.Provider>
  );
};

/** The rule between two groups of a toolbar row. */
export const ToolbarDivider = () => (
  <span aria-hidden="true" className="mx-1 h-5 w-px shrink-0 bg-border" />
);

/**
 * One control of a toolbar, as data rather than as a position in the markup.
 *
 * It has to be data because the same control is placed two ways: in the row
 * while it fits, in the overflow panel once it doesn't.
 */
export interface OverflowToolbarItem {
  id: string;
  /** What the row shows: the control itself. */
  node: ReactNode;
  /**
   * What the menu shows once the row has shed this control: labelled entries,
   * or a submenu where the control is itself a list of choices. A control with
   * no menu form cannot shed, so every item needs one.
   */
  menu: ReactNode;
  /** Opens a new group: a rule goes before it, in the row and in the menu. */
  startsGroup?: boolean;
  /**
   * Never in the row, always in the menu — for a control a surface keeps out
   * of the way however wide it gets.
   */
  menuOnly?: boolean;
}

interface OverflowToolbarProps extends Omit<ComponentProps<"div">, "children"> {
  items: OverflowToolbarItem[];
  /** Names the toolbar for assistive technology. */
  label: string;
  /** Names the control that opens the overflow panel. */
  moreLabel: string;
  /** Pinned to the start of the row, outside the measurement: never sheds. */
  leading?: ReactNode;
  /** Applied to the measured row. */
  rowClassName?: string;
  /** Applied to the overflow menu. */
  panelClassName?: string;
}

/**
 * A toolbar row that never wraps.
 *
 * As it narrows, the controls that no longer fit move into a menu at its end
 * rather than stacking into a second row or scrolling out of reach — named
 * there, since a lone icon in a list has nothing around it to read it by. What
 * fits is measured from the row itself, so a toolbar in a pane beside the
 * sidebar sheds at the width it really has rather than the width the window
 * reports.
 */
export const OverflowToolbar = ({
  items,
  label,
  moreLabel,
  leading,
  className,
  rowClassName,
  panelClassName,
  ...rest
}: OverflowToolbarProps) => {
  const [openBranch, setOpenBranch] = useState<string | null>(null);
  // Who was working when the menu opened — the grid, a cell input, the body of
  // a document. A menu takes focus while it is open, and Radix hands it to the
  // `…` button on the way out; the surface below is where it belongs.
  const focusedBeforeOpen = useRef<HTMLElement | null>(null);
  const rowItems = items.filter((item) => !item.menuOnly);
  const { rowRef, fits } = useRowCapacity(rowItems.map((item) => item.id));
  const panelItems = [...rowItems.slice(fits), ...items.filter((item) => item.menuOnly)];

  return (
    <div
      role="toolbar"
      aria-label={label}
      className={cn("flex min-w-0 items-center gap-1.5", className)}
      {...rest}
    >
      {leading}
      <div
        ref={rowRef}
        className={cn("flex min-w-0 flex-1 items-center gap-1.5 overflow-hidden", rowClassName)}
      >
        {rowItems.map((item, index) => (
          // One element per item, its rule included, so the row's children line
          // up one-to-one with what is being measured.
          //
          // Hidden by the attribute rather than a class: preflight's
          // `!important` display rule beats one, and the attribute is what
          // takes the control out of the accessibility tree.
          <span key={item.id} hidden={index >= fits} className="flex shrink-0 items-center gap-1.5">
            {item.startsGroup && index > 0 && <ToolbarDivider />}
            {item.node}
          </span>
        ))}
      </div>

      <span hidden={panelItems.length === 0} className="flex shrink-0 items-center">
        <DropdownMenu
          onOpenChange={(isOpen) => {
            if (isOpen) {
              const active = document.activeElement;
              focusedBeforeOpen.current =
                active instanceof HTMLElement && active !== document.body ? active : null;
              return;
            }
            // A menu opened again starts at the top, not wherever it was left.
            setOpenBranch(null);
          }}
        >
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              className="text-muted-foreground hover:text-foreground"
              title={moreLabel}
              aria-label={moreLabel}
              // The surface below keeps the caret or the cell it had, so what
              // the menu then does lands where the writer left off.
              onMouseDown={(event) => event.preventDefault()}
            >
              <MoreHorizontal className="h-4 w-4" aria-hidden={true} />
            </Button>
          </DropdownMenuTrigger>
          {/* On a phone the menu is taller than what is left of the screen.
              Radix reports how much room the side it chose actually has; cap
              the menu at that and scroll inside it, so the end of the list is
              never off the top. A branch sizes itself, within the same cap. */}
          <DropdownMenuContent
            align="end"
            collisionPadding={8}
            onCloseAutoFocus={(event) => {
              // Nothing to go back to: let Radix put focus on the trigger.
              const previous = focusedBeforeOpen.current;
              if (!previous?.isConnected) return;
              event.preventDefault();
              previous.focus({ preventScroll: true });
            }}
            className={cn(
              "max-h-(--radix-dropdown-menu-content-available-height) max-w-(--radix-dropdown-menu-content-available-width) overflow-y-auto",
              openBranch === null ? "w-56" : "w-auto",
              panelClassName
            )}
          >
            <DrilldownContext.Provider value={{ open: openBranch, setOpen: setOpenBranch }}>
              {panelItems.map((item, index) => (
                <Fragment key={item.id}>
                  {openBranch === null && item.startsGroup && index > 0 && (
                    <DropdownMenuSeparator />
                  )}
                  {item.menu}
                </Fragment>
              ))}
            </DrilldownContext.Provider>
          </DropdownMenuContent>
        </DropdownMenu>
      </span>
    </div>
  );
};
