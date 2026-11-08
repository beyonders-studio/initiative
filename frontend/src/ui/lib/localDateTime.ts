import { format } from "date-fns";

/** A calendar date in the viewer's zone, without Date's overflow normalization. */
export const parseLocalCalendarDate = (value: string): Date | null => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(0);
  date.setFullYear(year, month - 1, day);
  date.setHours(0, 0, 0, 0);
  return format(date, "yyyy-MM-dd") === value ? date : null;
};

/** A stored instant as the date-time pickers hold it: local, to the minute
 *  (`yyyy-MM-dd'T'HH:mm`), or empty for none. */
export const toPickerValue = (value: string | null | undefined): string => {
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return "";
  return format(date, "yyyy-MM-dd'T'HH:mm");
};

/** A picker's value as the instant it is stored as, or null for none. */
export const fromPickerValue = (value: string): string | null =>
  value ? new Date(value).toISOString() : null;

/**
 * Resolve wall-clock input only when it names one instant. A retained original
 * disambiguates an unchanged fold time and preserves its seconds/milliseconds.
 * New ambiguous or nonexistent times need an explicit choice rather than Date's
 * silent earlier-fold / forward-gap normalization.
 */
export const resolveLocalDateTime = (day: string, time: string, original?: string): Date | null => {
  const date = parseLocalCalendarDate(day);
  if (!date || !/^\d{2}:\d{2}(?::\d{2}(?:\.\d{1,3})?)?$/.test(time)) return null;
  const fraction = time.split(".")[1];
  const pattern =
    time.length === 5 ? "HH:mm" : fraction ? `HH:mm:ss.${"S".repeat(fraction.length)}` : "HH:mm:ss";
  const matches = (candidate: Date) =>
    !Number.isNaN(candidate.getTime()) &&
    format(candidate, "yyyy-MM-dd") === day &&
    format(candidate, pattern) === time;
  if (original) {
    const retained = new Date(original);
    if (matches(retained)) return retained;
  }
  const candidate = new Date(`${day}T${time}`);
  if (!matches(candidate)) return null;
  // Sample both sides of a transition, including half-hour DST changes.
  const offsets = new Set(
    [-2, -1, 0, 1, 2].map((days) =>
      new Date(candidate.getTime() + days * 86_400_000).getTimezoneOffset()
    )
  );
  const candidates = [...offsets]
    .map(
      (offset) => new Date(candidate.getTime() + (offset - candidate.getTimezoneOffset()) * 60_000)
    )
    .filter(matches);
  return candidates.length === 1 ? candidate : null;
};
