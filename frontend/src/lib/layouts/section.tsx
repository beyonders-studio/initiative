import { ChevronDown } from "lucide-react";
import { type ReactNode, useState } from "react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/ui/collapsible";
import { cn } from "@/ui/lib/utils";

/** A bordered group of parts. A title lets the reader fold it, and
 *  `collapsed` starts it folded. */
export const Section = ({
  title,
  collapsed = false,
  spacing = "space-y-4",
  children,
}: {
  title?: string;
  collapsed?: boolean;
  spacing?: "space-y-2" | "space-y-4";
  children: ReactNode;
}) => {
  const [open, setOpen] = useState(!collapsed);
  return (
    <section
      className={cn("rounded-lg border bg-card p-4 text-card-foreground shadow-sm", spacing)}
    >
      {title ? (
        <Collapsible open={open} onOpenChange={setOpen} className={spacing}>
          <CollapsibleTrigger className="flex w-full items-center justify-between gap-2 font-medium text-sm">
            {title}
            <ChevronDown
              className={cn("h-4 w-4 transition-transform", open && "rotate-180")}
              aria-hidden="true"
            />
          </CollapsibleTrigger>
          <CollapsibleContent className={spacing}>{children}</CollapsibleContent>
        </Collapsible>
      ) : (
        children
      )}
    </section>
  );
};
