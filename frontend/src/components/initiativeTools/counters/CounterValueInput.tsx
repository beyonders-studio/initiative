import { type ChangeEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";

import { cn } from "@/ui/lib/utils";

interface CounterValueInputProps {
  /** Server-side count (string). The input syncs to this when not actively edited. */
  value: string;
  step?: string;
  disabled?: boolean;
  /** Called with the typed value after blur, debounce, or Enter. */
  onCommit: (value: string) => void;
  /** Visual size — affects font size only. */
  size?: "2xl" | "xl" | "lg" | "md" | "sm";
  /** Apply this text color (e.g. contrasting against a colored card). */
  textColor?: string;
  className?: string;
  /** Hard width override in `ch`. Defaults to sizing to the typed content. */
  widthCh?: number;
  /** Aria label for accessibility. */
  ariaLabel?: string;
}

const DEBOUNCE_MS = 400;

/** Editable counter value. The input *is* the display — there is no separate
 * static label. Borderless and transparent so it can sit on a colored card. */
export const CounterValueInput = ({
  value,
  step,
  disabled,
  onCommit,
  size = "md",
  textColor,
  className,
  widthCh,
  ariaLabel,
}: CounterValueInputProps) => {
  const [draft, setDraft] = useState(value);
  const lastCommittedRef = useRef<string>(value);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (value !== lastCommittedRef.current) {
      lastCommittedRef.current = value;
      setDraft(value);
    }
  }, [value]);

  const commit = (next: string) => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (next !== lastCommittedRef.current) {
      lastCommittedRef.current = next;
      onCommit(next);
    }
  };

  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    const next = event.target.value;
    setDraft(next);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => commit(next), DEBOUNCE_MS);
  };

  const handleBlur = () => commit(draft);

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      commit(draft);
      (event.target as HTMLInputElement).blur();
    }
  };

  // Step the font size down as the value gets longer so big counts
  // (e.g. 3000000000) stay inside the card instead of overflowing at a fixed
  // size. Each `size` starts at its nominal scale and shrinks by char count.
  const valueLength = Math.max(draft.length, 1);
  const sizeClass = (() => {
    if (size === "sm") return "text-sm";
    if (size === "md") return valueLength <= 10 ? "text-xl" : "text-base";
    if (size === "lg") {
      if (valueLength <= 5) return "text-3xl";
      if (valueLength <= 8) return "text-2xl";
      if (valueLength <= 11) return "text-xl";
      return "text-base";
    }
    if (size === "xl") {
      if (valueLength <= 4) return "text-5xl";
      if (valueLength <= 6) return "text-4xl";
      if (valueLength <= 8) return "text-3xl";
      if (valueLength <= 11) return "text-2xl";
      return "text-xl";
    }
    // "2xl" (fullscreen focus view)
    if (valueLength <= 3) return "text-8xl";
    if (valueLength <= 5) return "text-7xl";
    if (valueLength <= 7) return "text-6xl";
    if (valueLength <= 10) return "text-5xl";
    return "text-4xl";
  })();

  // Size the box to the typed content (font-mono ⇒ 1 char ≈ 1ch) so the input —
  // and its focus ring — never overflows the card. +1ch leaves room for the
  // caret; max-w-full keeps it inside the parent on extreme values.
  const effectiveWidthCh = widthCh ?? Math.max(2, draft.length + 1);

  return (
    <input
      type="number"
      inputMode="decimal"
      value={draft}
      onChange={handleChange}
      onBlur={handleBlur}
      onKeyDown={handleKeyDown}
      disabled={disabled}
      step={step}
      aria-label={ariaLabel}
      style={{
        color: textColor,
        width: `${effectiveWidthCh}ch`,
        // Tap-to-edit: avoid native iOS zoom on focus while preserving spinners-off.
        WebkitAppearance: "none",
        MozAppearance: "textfield",
      }}
      className={cn(
        "max-w-full appearance-none border-0 bg-transparent p-0 text-center font-mono font-semibold tabular-nums",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-current focus-visible:ring-offset-1 focus-visible:ring-offset-transparent",
        "disabled:cursor-not-allowed disabled:opacity-60",
        "[&::-webkit-inner-spin-button]:m-0 [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none",
        sizeClass,
        className
      )}
    />
  );
};
