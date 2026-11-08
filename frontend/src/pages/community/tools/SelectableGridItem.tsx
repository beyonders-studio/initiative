import { Check } from "lucide-react";
import type { ReactNode } from "react";

import type { GridToggleOptions } from "@/hooks/useGridSelection";
import { cn } from "@/ui/lib/utils";

interface SelectableGridItemProps {
  /** Whether the list is in selection mode. When false, children render as-is. */
  active: boolean;
  selected: boolean;
  /** Called with `extend` when the click held shift, asking for a range. */
  onToggle: (options: GridToggleOptions) => void;
  children: ReactNode;
  label?: string;
}

/**
 * Wraps a grid card so it can be multi-selected without touching the card
 * component. In selection mode the card underneath is made non-interactive (its
 * link won't navigate) and a full-card toggle button + checkbox overlay is shown.
 * Holding shift asks the list for a range from the last card clicked to this one
 * — keyboard activation counts too, since Shift+Enter/Space fires a click with
 * the modifier set.
 */
export function SelectableGridItem({
  active,
  selected,
  onToggle,
  children,
  label,
}: SelectableGridItemProps) {
  if (!active) return <>{children}</>;

  return (
    <div className="relative">
      {/* `inert` blocks pointer *and* keyboard/AT focus from reaching the card's
          links/buttons while selecting — the overlay is the only interactive part. */}
      <div inert className="select-none">
        {children}
      </div>
      <button
        type="button"
        onClick={(event) => onToggle({ extend: event.shiftKey })}
        aria-pressed={selected}
        aria-label={label}
        className={cn(
          "absolute inset-0 z-10 select-none rounded-2xl ring-inset transition focus:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          selected ? "bg-primary/5 ring-2 ring-primary" : "hover:bg-muted/20"
        )}
      >
        {/* Purely decorative — the overlay button carries the pressed state and
            label. A real checkbox here would nest a <button> inside a <button>. */}
        <span
          aria-hidden="true"
          className={cn(
            "absolute top-3 left-3 grid h-4 w-4 shrink-0 place-content-center rounded-sm border-2 shadow",
            selected
              ? "border-primary bg-primary text-primary-foreground"
              : "border-primary bg-background"
          )}
        >
          {selected ? <Check className="h-4 w-4" /> : null}
        </span>
      </button>
    </div>
  );
}
