import * as AvatarPrimitive from "@radix-ui/react-avatar";
import * as React from "react";

import { getUserColorStyle } from "@/ui/lib/userColor";
import { cn } from "@/ui/lib/utils";

const Avatar = React.forwardRef<
  React.ElementRef<typeof AvatarPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof AvatarPrimitive.Root>
>(({ className, ...props }, ref) => (
  <AvatarPrimitive.Root
    ref={ref}
    data-slot="avatar"
    className={cn("relative flex h-10 w-10 shrink-0 overflow-hidden rounded-full", className)}
    {...props}
  />
));
Avatar.displayName = AvatarPrimitive.Root.displayName;

const AvatarImage = React.forwardRef<
  React.ElementRef<typeof AvatarPrimitive.Image>,
  React.ComponentPropsWithoutRef<typeof AvatarPrimitive.Image>
>(({ className, ...props }, ref) => (
  // ``referrerPolicy="no-referrer"`` so loading an avatar from ``/uploads/`` (or
  // a user-supplied ``avatar_url``) never sends the current page URL as the
  // Referer header. Callers may still override through ``props``.
  <AvatarPrimitive.Image
    ref={ref}
    referrerPolicy="no-referrer"
    className={cn("aspect-square h-full w-full", className)}
    {...props}
  />
));
AvatarImage.displayName = AvatarPrimitive.Image.displayName;

interface AvatarFallbackProps
  extends React.ComponentPropsWithoutRef<typeof AvatarPrimitive.Fallback> {
  /**
   * When set, the fallback's background + foreground are driven by the
   * deterministic ``getUserColorStyle`` hash — the same hue that powers
   * whiteboard cursors and the Lexical editor caret. Leave undefined for
   * non-user avatars (community icons, generic placeholders), which keep the
   * default ``bg-muted`` look.
   */
  userId?: number | null;
}

const AvatarFallback = React.forwardRef<
  React.ElementRef<typeof AvatarPrimitive.Fallback>,
  AvatarFallbackProps
>(({ className, style, userId, ...props }, ref) => {
  const hasUserColor = typeof userId === "number" && userId > 0;
  const mergedStyle = hasUserColor ? { ...getUserColorStyle(userId), ...style } : style;
  return (
    <AvatarPrimitive.Fallback
      ref={ref}
      className={cn(
        "flex h-full w-full items-center justify-center rounded-full",
        // Only fall back to ``bg-muted`` when there's no user color. Inline
        // ``backgroundColor`` would otherwise win anyway, but skipping the
        // class keeps the computed styles tidy and avoids surprise overrides.
        !hasUserColor && "bg-muted",
        className
      )}
      style={mergedStyle}
      {...props}
    />
  );
});
AvatarFallback.displayName = AvatarPrimitive.Fallback.displayName;

export { Avatar, AvatarFallback, AvatarImage };
