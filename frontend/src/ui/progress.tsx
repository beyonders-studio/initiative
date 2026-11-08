import * as ProgressPrimitive from "@radix-ui/react-progress";
import * as React from "react";
import { useTranslation } from "react-i18next";

import { numberFormat } from "@/ui/lib/intl";
import { cn } from "@/ui/lib/utils";

interface ProgressProps extends React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root> {
  /** A bar across its container, or a ring with the percent inside it. */
  variant?: "bar" | "ring";
}

const RING_RADIUS = 24;
const RING_LENGTH = 2 * Math.PI * RING_RADIUS;

/** How far along something is, as a bar or a ring. Either is a progressbar whose
 *  value reads as a percent in the reader's language. */
const Progress = React.forwardRef<React.ElementRef<typeof ProgressPrimitive.Root>, ProgressProps>(
  ({ className, value, max = 100, variant = "bar", ...props }, ref) => {
    const { i18n } = useTranslation();
    const percent = (done: number, of: number) =>
      numberFormat(i18n.resolvedLanguage ?? i18n.language, {
        style: "percent",
        maximumFractionDigits: 0,
      }).format(done / of);
    const share = (value ?? 0) / max;

    if (variant === "ring") {
      return (
        <ProgressPrimitive.Root
          ref={ref}
          value={value}
          max={max}
          getValueLabel={percent}
          className={cn("relative size-14", className)}
          {...props}
        >
          <svg className="size-full" viewBox="0 0 60 60" aria-hidden="true">
            <circle
              className="stroke-current text-muted"
              strokeWidth="6"
              strokeLinecap="round"
              fill="transparent"
              r={RING_RADIUS}
              cx="30"
              cy="30"
            />
            <circle
              className="stroke-current text-primary"
              strokeWidth="6"
              strokeLinecap="round"
              fill="transparent"
              r={RING_RADIUS}
              cx="30"
              cy="30"
              strokeDasharray={RING_LENGTH}
              strokeDashoffset={RING_LENGTH * (1 - share)}
              transform="rotate(-90 30 30)"
            />
          </svg>
          <span
            aria-hidden="true"
            className="absolute inset-0 flex items-center justify-center font-semibold text-foreground text-xs"
          >
            {percent(value ?? 0, max)}
          </span>
        </ProgressPrimitive.Root>
      );
    }

    return (
      <ProgressPrimitive.Root
        ref={ref}
        value={value}
        max={max}
        getValueLabel={percent}
        className={cn("relative h-2 w-full overflow-hidden rounded-full bg-primary/20", className)}
        {...props}
      >
        <ProgressPrimitive.Indicator
          className="h-full w-full flex-1 bg-primary transition-all"
          style={{ transform: `translateX(-${100 - share * 100}%)` }}
        />
      </ProgressPrimitive.Root>
    );
  }
);
Progress.displayName = ProgressPrimitive.Root.displayName;

export { Progress };
