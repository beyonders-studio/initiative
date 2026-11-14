/**
 * One reaction's chip: a round pill holding the emoji and how many gave it,
 * pressed while the reader is one of them. The reaction bar draws one per
 * emoji; a suggestion's upvote is the same chip, its 👍 grey until pressed,
 * pointed at or focused, and drawn larger.
 */

import type { ComponentPropsWithRef } from "react";

import { cn } from "@/ui/lib/utils";

interface ReactionChipProps extends Omit<ComponentPropsWithRef<"button">, "children"> {
  emoji: string;
  /** The number shown beside the emoji; left out, the emoji stands alone. */
  count?: number;
  pressed: boolean;
  /** Larger, for a chip that is a page's main control: 36px tall, 44px on a phone. */
  size?: "default" | "lg";
  /** The emoji in grey until the chip is pressed, pointed at or focused. */
  greyscale?: boolean;
  /** The count moves in as it changes, where motion is welcome. */
  tick?: boolean;
}

export const ReactionChip = ({
  emoji,
  count,
  pressed,
  size = "default",
  greyscale = false,
  tick = false,
  className,
  ...props
}: ReactionChipProps) => (
  <button
    type="button"
    aria-pressed={pressed}
    className={cn(
      "group flex items-center rounded-full border transition-colors motion-reduce:transition-none",
      "disabled:cursor-default disabled:opacity-70",
      size === "lg"
        ? "h-11 min-w-15 justify-center gap-1.5 px-3 font-medium text-sm sm:h-9"
        : "h-7 gap-1 px-2 text-xs",
      pressed
        ? "border-primary/40 bg-primary/10 text-foreground"
        : "border-border bg-muted/40 text-muted-foreground hover:bg-muted",
      className
    )}
    {...props}
  >
    <span
      className={cn(
        "leading-none",
        size === "lg" ? "text-base" : "text-sm",
        greyscale && !pressed && "grayscale group-hover:grayscale-0 group-focus-visible:grayscale-0"
      )}
    >
      {emoji}
    </span>
    {count === undefined ? null : (
      <span
        key={tick ? count : undefined}
        className={cn(
          "tabular-nums",
          tick && "motion-safe:fade-in-0 motion-safe:slide-in-from-bottom-1 motion-safe:animate-in"
        )}
      >
        {count}
      </span>
    )}
  </button>
);
