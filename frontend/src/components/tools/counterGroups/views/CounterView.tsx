import { type CounterRead, CounterViewMode } from "@/api/generated/initiativeAPI.schemas";

import { CounterNumberView } from "./CounterNumberView";
import { CounterProgressBarView } from "./CounterProgressBarView";
import { CounterSegmentedClockView } from "./CounterSegmentedClockView";

/** The dial runs a size smaller than the number and bar beside it. */
const CLOCK_SIZE = { "2xl": "2xl", xl: "lg", lg: "md" } as const;

interface CounterViewProps {
  counter: CounterRead;
  disabled: boolean;
  textColor: string;
  onCommit: (value: string) => void;
  size: keyof typeof CLOCK_SIZE;
}

/** A counter in its view mode; the bar and the dial need both bounds, so a
 *  counter missing one shows as a number. */
export const CounterView = ({ counter, disabled, textColor, onCommit, size }: CounterViewProps) => {
  const shared = {
    count: counter.count,
    step: counter.step,
    disabled,
    textColor,
    onCommit,
    ariaLabel: counter.name,
  };
  const { min, max } = counter;
  if (min !== null && max !== null) {
    if (counter.view_mode === CounterViewMode.progress_bar) {
      return <CounterProgressBarView {...shared} min={min} max={max} size={size} />;
    }
    if (counter.view_mode === CounterViewMode.segmented_clock) {
      return <CounterSegmentedClockView {...shared} min={min} max={max} size={CLOCK_SIZE[size]} />;
    }
  }
  return <CounterNumberView {...shared} size={size} />;
};
