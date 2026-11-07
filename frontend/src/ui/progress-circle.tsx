import type React from "react";

import { cn } from "@/ui/lib/utils";

interface ProgressCircleProps extends React.HTMLProps<HTMLDivElement> {
  value: number;
  showPercentage?: boolean;
}

export const ProgressCircle = ({
  value,
  showPercentage = true,
  className,
  ...props
}: ProgressCircleProps) => {
  const radius = 24;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (value / 100) * circumference;

  return (
    <div className={cn("relative h-14 w-14", className)} {...props}>
      <svg className="h-full w-full" viewBox="0 0 60 60" aria-hidden="true">
        <circle
          className="stroke-current text-muted"
          strokeWidth="6"
          strokeLinecap="round"
          fill="transparent"
          r={radius}
          cx="30"
          cy="30"
        />
        <circle
          className="stroke-current text-primary"
          strokeWidth="6"
          strokeLinecap="round"
          fill="transparent"
          r={radius}
          cx="30"
          cy="30"
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          transform="rotate(-90 30 30)"
        />
      </svg>
      {showPercentage && (
        <div className="absolute inset-0 flex items-center justify-center font-semibold text-foreground text-xs">
          {value}%
        </div>
      )}
    </div>
  );
};
