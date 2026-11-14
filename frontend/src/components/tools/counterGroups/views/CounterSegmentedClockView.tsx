import { CounterValueInput } from "@/components/tools/counterGroups/CounterValueInput";
import { cn } from "@/ui/lib/utils";

interface CounterSegmentedClockViewProps {
  count: string;
  min: string;
  max: string;
  step: string;
  disabled?: boolean;
  textColor?: string;
  onCommit: (value: string) => void;
  ariaLabel?: string;
  className?: string;
  /** Size hint — "lg" doubles the diameter for grid cards, "2xl" for fullscreen focus. */
  size?: "2xl" | "lg" | "md";
}

const toNum = (value: string): number => {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
};

export const CounterSegmentedClockView = ({
  count,
  min,
  max,
  step,
  disabled,
  textColor,
  onCommit,
  ariaLabel,
  className,
  size = "md",
}: CounterSegmentedClockViewProps) => {
  const minN = toNum(min);
  const maxN = toNum(max);
  const stepN = toNum(step);
  const range = maxN - minN;
  const value = Math.max(minN, Math.min(maxN, toNum(count)));
  const rawSegments = stepN > 0 && range > 0 ? Math.round(range / stepN) : 0;
  const segments = rawSegments > 0 && rawSegments <= 60 ? rawSegments : 0;
  const filledCount = segments > 0 ? Math.round((value - minN) / stepN) : 0;
  const pct = range > 0 ? ((value - minN) / range) * 100 : 0;

  // SVG is drawn in a fixed 72-unit viewBox; the wrapper element scales it.
  const SIZE = 72;
  const CENTER = SIZE / 2;
  const RADIUS = 30;
  const circumference = 2 * Math.PI * RADIUS;
  const strokeDashoffset = circumference - (pct / 100) * circumference;
  const fillColor = textColor ?? "rgba(255,255,255,0.9)";

  // Grid cards ("lg") size the dial responsively: on a 2-up phone the card's
  // value area is only ~65px tall, so start small and grow with the breakpoints
  // that widen the grid. The row layout ("md") keeps a fixed dial.
  // "2xl" is the fullscreen focus dial — fills most of the focus viewport area.
  const wrapperSize =
    size === "2xl"
      ? "h-64 w-64 sm:h-72 sm:w-72"
      : size === "lg"
        ? "h-16 w-16 sm:h-20 sm:w-20 md:h-24 md:w-24"
        : "h-20 w-20";
  const inputSize = size === "2xl" ? "2xl" : size === "lg" ? "lg" : "md";
  const strokeWidth = size === "2xl" ? 4 : 6;

  return (
    <div className={cn("relative inline-flex items-center justify-center", wrapperSize, className)}>
      <svg
        className="absolute inset-0 h-full w-full"
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        aria-hidden="true"
      >
        <circle
          strokeWidth={strokeWidth}
          fill="transparent"
          stroke="rgba(0,0,0,0.18)"
          r={RADIUS}
          cx={CENTER}
          cy={CENTER}
        />
        <circle
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          fill="transparent"
          stroke={fillColor}
          r={RADIUS}
          cx={CENTER}
          cy={CENTER}
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          transform={`rotate(-90 ${CENTER} ${CENTER})`}
        />
        {segments > 0 &&
          Array.from({ length: segments }).map((_, i) => {
            const angle = (i / segments) * 360 - 90;
            const inner = RADIUS - 4;
            const outer = RADIUS + 4;
            const rad = (angle * Math.PI) / 180;
            const x1 = CENTER + inner * Math.cos(rad);
            const y1 = CENTER + inner * Math.sin(rad);
            const x2 = CENTER + outer * Math.cos(rad);
            const y2 = CENTER + outer * Math.sin(rad);
            const isFilled = i < filledCount;
            return (
              <line
                // biome-ignore lint/suspicious/noArrayIndexKey: segments are stable by index
                key={i}
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
                stroke={isFilled ? fillColor : "rgba(0,0,0,0.18)"}
                strokeWidth={1.5}
                strokeLinecap="round"
              />
            );
          })}
      </svg>
      <CounterValueInput
        value={count}
        step={step}
        disabled={disabled}
        onCommit={onCommit}
        textColor={textColor}
        size={inputSize}
        ariaLabel={ariaLabel}
        className="relative z-10"
      />
    </div>
  );
};
