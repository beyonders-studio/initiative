import * as HoverCardPrimitive from "@radix-ui/react-hover-card";
import * as React from "react";

import { cn } from "@/ui/lib/utils";

const HoverCard = HoverCardPrimitive.Root;

const HoverCardTrigger = HoverCardPrimitive.Trigger;

/**
 * Portaled, because a hover card is opened from inside somebody's prose.
 *
 * Rendered where it is triggered, the card inherits whatever that prose sets
 * on its descendants — a comment body indents every `ul` it contains, a
 * document sizes its own text — and it is clipped by any scrolling box it
 * happens to sit in. At the end of the body it is only ever the card.
 */
const HoverCardContent = React.forwardRef<
  React.ElementRef<typeof HoverCardPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof HoverCardPrimitive.Content>
>(({ className, align = "center", sideOffset = 4, ...props }, ref) => (
  <HoverCardPrimitive.Portal>
    <HoverCardPrimitive.Content
      ref={ref}
      align={align}
      sideOffset={sideOffset}
      className={cn(
        "data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 z-50 w-64 origin-(--radix-hover-card-content-transform-origin) rounded-md border bg-popover p-4 text-popover-foreground shadow-md outline-none data-[state=closed]:animate-out data-[state=open]:animate-in",
        className
      )}
      {...props}
    />
  </HoverCardPrimitive.Portal>
));
HoverCardContent.displayName = HoverCardPrimitive.Content.displayName;

export { HoverCard, HoverCardContent, HoverCardTrigger };
