import { parseDateValue } from "@/ui/lib/formatDate";

/** What a pair of start/end date pickers needs to constrain and validate itself. */
export interface DateRangeBounds {
  /** `calendarProps` for the start picker — no later than the end. */
  startCalendarProps: { hidden: { after: Date } } | undefined;
  /** `calendarProps` for the end picker — no earlier than the start. */
  endCalendarProps: { hidden: { before: Date } } | undefined;
  /** Both ends are set and the end falls before the start. */
  isInverted: boolean;
}

/**
 * Derive the calendar bounds and validity for a start/end date pair.
 *
 * Each end bounds the other's calendar, and a bound is only produced when the
 * opposite date is actually set — an unset or unparsable value yields
 * `undefined` rather than an Invalid Date, which would hide every day.
 *
 * A range with only one end set is legitimate everywhere we use this (a task
 * with just a due date, a project with just a start), so it is never inverted.
 * Equal ends are fine too: that is a single-day range. Pickers also accept a
 * typed value, so picking is not the only way a range is entered — forms use
 * `isInverted` to disable their submit and keep it out of the API.
 *
 * Accepts date-only (`2026-03-02`) and date-time (`2026-03-02T15:30`) values;
 * a date-only value resolves to the local calendar day.
 */
export const dateRangeBounds = (
  start: string | null | undefined,
  end: string | null | undefined
): DateRangeBounds => {
  const from = parseDateValue(start);
  const to = parseDateValue(end);
  return {
    startCalendarProps: to ? { hidden: { after: to } } : undefined,
    endCalendarProps: from ? { hidden: { before: from } } : undefined,
    isInverted: Boolean(from && to && to < from),
  };
};
