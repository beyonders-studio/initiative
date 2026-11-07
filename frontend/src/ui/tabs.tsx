import * as TabsPrimitive from "@radix-ui/react-tabs";
import * as React from "react";

import { cn } from "@/ui/lib/utils";

const Tabs = TabsPrimitive.Root;

const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.List
    ref={ref}
    className={cn(
      "inline-flex h-9 items-center justify-center rounded-lg bg-muted p-1 text-muted-foreground",
      className
    )}
    {...props}
  />
));
TabsList.displayName = TabsPrimitive.List.displayName;

/**
 * The page-level tab bar: spans the width of its container, keeps its triggers
 * at their label width and left-aligned, and scrolls horizontally once they
 * stop fitting. A mouse wheel only scrolls up and down, so a fine pointer gets a
 * thin scrollbar to drag; a touch screen swipes and shows none. Use this for
 * every navigation-style tab bar; inline segmented controls (a view picker
 * sitting in a toolbar) keep a bare `TabsList` so they stay sized to their
 * content.
 */
const TabsBar = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List> & {
    /** Extra classes for the scroll container wrapping the list. */
    containerClassName?: string;
  }
>(({ className, containerClassName, ...props }, ref) => (
  <div
    className={cn(
      "scrollbar-thin -mx-1 overflow-x-auto px-1 pointer-coarse:[scrollbar-width:none] pointer-coarse:[&::-webkit-scrollbar]:hidden",
      containerClassName
    )}
  >
    {/* `min-w-max` keeps the triggers at their label width once they overflow,
        so the container scrolls rather than the labels shrinking. */}
    <TabsList ref={ref} className={cn("w-full min-w-max justify-start", className)} {...props} />
  </div>
));
TabsBar.displayName = "TabsBar";

const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn(
      "inline-flex items-center justify-center whitespace-nowrap rounded-md px-3 py-1 font-medium text-sm ring-offset-background transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow",
      className
    )}
    {...props}
  />
));
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName;

const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn(
      "mt-2 ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
      className
    )}
    {...props}
  />
));
TabsContent.displayName = TabsPrimitive.Content.displayName;

export { Tabs, TabsBar, TabsContent, TabsList, TabsTrigger };
