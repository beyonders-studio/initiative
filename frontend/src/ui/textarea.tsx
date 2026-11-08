import * as React from "react";

import { useFieldControl } from "@/ui/field";
import { fieldClass } from "@/ui/input";
import { cn } from "@/ui/lib/utils";

const Textarea = React.forwardRef<HTMLTextAreaElement, React.ComponentProps<"textarea">>(
  ({ className, ...props }, ref) => {
    return (
      <textarea
        className={cn(fieldClass, "h-auto min-h-[60px] py-2", className)}
        ref={ref}
        {...props}
        {...useFieldControl(props)}
      />
    );
  }
);
Textarea.displayName = "Textarea";

export { Textarea };
