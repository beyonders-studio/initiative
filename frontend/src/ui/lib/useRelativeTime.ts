import { formatDistance, type Locale } from "date-fns";
import { useSyncExternalStore } from "react";

import { getClockNow, subscribeToClock } from "@/ui/lib/relativeTimeClock";
import { useDateLocale } from "@/ui/lib/useDateLocale";

/**
 * Subscribe to the shared clock and derive a value from the current time,
 * re-rendering only when that value changes.
 *
 * `compute` MUST return a primitive (string/number/boolean). React compares the
 * snapshot with `Object.is`, so a primitive that is unchanged between ticks
 * suppresses the re-render — a "3 hours ago" label costs one function call per
 * tick but no re-render until the hour rolls over. Returning an object would
 * defeat this (a fresh reference every tick forces a re-render every tick).
 */
export const useLiveClockValue = <T extends string | number | boolean | null>(
  compute: (now: number) => T
): T => {
  return useSyncExternalStore(
    subscribeToClock,
    () => compute(getClockNow()),
    () => compute(getClockNow())
  );
};

type RelativeTimeOptions = {
  addSuffix?: boolean;
  /** Override the locale; defaults to the app's current i18n locale. */
  locale?: Locale;
};

/**
 * A live-updating relative time string ("2 minutes ago") backed by the shared
 * clock. Recomputes on every tick but only triggers a re-render when the
 * formatted string actually changes, so it stays cheap in large tables.
 *
 * The locale defaults to the app's current i18n locale, so callers don't need
 * to plumb it through. Returns `null` when `date` is nullish so callers can
 * render a placeholder.
 */
export const useRelativeTime = (
  date: Date | string | number | null | undefined,
  options?: RelativeTimeOptions
): string | null => {
  const currentLocale = useDateLocale();
  const addSuffix = options?.addSuffix ?? true;
  const locale = options?.locale ?? currentLocale;
  const time =
    date == null ? null : typeof date === "object" ? date.getTime() : new Date(date).getTime();

  return useLiveClockValue((now) => {
    if (time == null || Number.isNaN(time)) {
      return null;
    }
    return formatDistance(time, now, { addSuffix, locale });
  });
};
