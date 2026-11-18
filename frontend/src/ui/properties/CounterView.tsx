import { CounterLook } from "@/api/generated/initiativeAPI.schemas";

import { CounterNumberView } from "./CounterNumberView";
import { CounterProgressBarView } from "./CounterProgressBarView";
import { CounterSegmentedClockView } from "./CounterSegmentedClockView";

/** The dial runs a size smaller than the number and bar beside it. */
const CLOCK_SIZE = { "2xl": "2xl", xl: "lg", lg: "md" } as const;

/** What a counter draws: its count, step and bounds as written, and how it
 *  is drawn. */
export interface CounterShown {
  count: string;
  step: string;
  min: string | null;
  max: string | null;
  look: CounterLook;
}

interface CounterViewProps {
  counter: CounterShown;
  /** Its name, which its value is read by. */
  name: string;
  disabled: boolean;
  textColor: string;
  onCommit: (value: string) => void;
  size: keyof typeof CLOCK_SIZE;
}

/** A counter in its look; the bar and the dial need both bounds, so a
 *  counter missing one shows as a number. */
export const CounterView = ({
  counter,
  name,
  disabled,
  textColor,
  onCommit,
  size,
}: CounterViewProps) => {
  const shared = {
    count: counter.count,
    step: counter.step,
    disabled,
    textColor,
    onCommit,
    ariaLabel: name,
  };
  const { min, max } = counter;
  if (min !== null && max !== null) {
    if (counter.look === CounterLook.bar) {
      return <CounterProgressBarView {...shared} min={min} max={max} size={size} />;
    }
    if (counter.look === CounterLook.clock) {
      return <CounterSegmentedClockView {...shared} min={min} max={max} size={CLOCK_SIZE[size]} />;
    }
  }
  return <CounterNumberView {...shared} size={size} />;
};
