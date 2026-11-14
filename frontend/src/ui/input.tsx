import * as React from "react";

import { useFieldControl } from "@/ui/field";
import { cn } from "@/ui/lib/utils";

/** The box every field in the kit draws: an input, a textarea, a select's
 *  trigger and the triggers of the fields that open a popover. */
export const fieldClass =
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-base shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-destructive sm:text-sm";

const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          fieldClass,
          "file:border-0 file:bg-transparent file:font-medium file:text-foreground file:text-sm",
          className
        )}
        ref={ref}
        {...props}
        {...useFieldControl(props)}
      />
    );
  }
);
Input.displayName = "Input";

export { Input };
