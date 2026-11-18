/**
 * Client-side counter arithmetic for optimistic updates.
 *
 * These mirror the backend's ``clamp`` / value-op semantics so optimistic
 * cache writes match what the server will return. Using Number is fine for
 * the ranges counters realistically hit (HP, ammo, scores); the server is
 * still the source of truth and refetch on settled fixes any drift.
 */

import {
  CounterLook,
  type CounterRead,
  CounterViewMode,
} from "@/api/generated/initiativeAPI.schemas";
import type { CounterShown } from "@/ui/properties/CounterView";

/** The look a counter's view mode draws it in. */
const LOOKS: Record<CounterViewMode, CounterLook> = {
  [CounterViewMode.number]: CounterLook.number,
  [CounterViewMode.progress_bar]: CounterLook.bar,
  [CounterViewMode.segmented_clock]: CounterLook.clock,
};

/** A counter as the kit draws it. */
export const counterShown = (counter: CounterRead): CounterShown => ({
  count: counter.count,
  step: counter.step,
  min: counter.min,
  max: counter.max,
  look: LOOKS[counter.view_mode],
});

const toNum = (value: string | null | undefined): number => {
  if (value == null || value === "") return Number.NaN;
  const n = Number(value);
  return Number.isFinite(n) ? n : Number.NaN;
};

const formatNumber = (value: number): string => {
  if (!Number.isFinite(value)) return "0";
  // Strip trailing zeros but keep "0" — matches backend's _format_decimal.
  const fixed = value.toFixed(10);
  if (fixed.includes(".")) {
    return fixed.replace(/0+$/, "").replace(/\.$/, "") || "0";
  }
  return fixed;
};

export const clampCount = (value: number, min: string | null, max: string | null): number => {
  const lo = min === null ? Number.NEGATIVE_INFINITY : toNum(min);
  const hi = max === null ? Number.POSITIVE_INFINITY : toNum(max);
  if (Number.isFinite(lo) && value < lo) value = lo;
  if (Number.isFinite(hi) && value > hi) value = hi;
  return value;
};

export const optimisticIncrement = (counter: CounterRead): string =>
  formatNumber(clampCount(toNum(counter.count) + toNum(counter.step), counter.min, counter.max));

export const optimisticDecrement = (counter: CounterRead): string =>
  formatNumber(clampCount(toNum(counter.count) - toNum(counter.step), counter.min, counter.max));

export const optimisticReset = (counter: CounterRead): string =>
  formatNumber(clampCount(toNum(counter.initial_count), counter.min, counter.max));

export const optimisticSetCount = (counter: CounterRead, value: string): string =>
  formatNumber(clampCount(toNum(value), counter.min, counter.max));

/** True when the counter is at (or past) its lower bound. ``null`` min = never. */
export const isAtMin = (counter: CounterRead): boolean => {
  if (counter.min === null) return false;
  return toNum(counter.count) <= toNum(counter.min);
};

/** True when the counter is at (or past) its upper bound. ``null`` max = never. */
export const isAtMax = (counter: CounterRead): boolean => {
  if (counter.max === null) return false;
  return toNum(counter.count) >= toNum(counter.max);
};
