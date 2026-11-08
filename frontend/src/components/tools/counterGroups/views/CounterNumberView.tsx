import { CounterValueInput } from "@/components/tools/counterGroups/CounterValueInput";
import { cn } from "@/ui/lib/utils";

interface CounterNumberViewProps {
  count: string;
  step?: string;
  disabled?: boolean;
  textColor?: string;
  onCommit: (value: string) => void;
  ariaLabel?: string;
  className?: string;
  /** Size hint — "xl" for grid cards, "2xl" for fullscreen focus. */
  size?: "2xl" | "xl" | "lg";
}

export const CounterNumberView = ({
  count,
  step,
  disabled,
  textColor,
  onCommit,
  ariaLabel,
  className,
  size = "lg",
}: CounterNumberViewProps) => (
  <div className={cn("flex w-full min-w-0 items-center justify-center", className)}>
    <CounterValueInput
      value={count}
      step={step}
      disabled={disabled}
      onCommit={onCommit}
      textColor={textColor}
      size={size}
      ariaLabel={ariaLabel}
    />
  </div>
);
