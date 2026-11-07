/**
 * A time of day on the reader's clock: "1:30 PM" or "13:30".
 *
 * The formatters that need it are mostly plain functions — `formatDateTime`,
 * a calendar's hour gutter, the clock beside a message — called from deep
 * inside render trees that have no business threading a preference down. So
 * they read the host's clock (`getClock`), which the app writes from the
 * signed-in account (see `useClockSync`). React components that must
 * re-render when it changes subscribe through `useTimeFormat`; everything else
 * just reads it at format time.
 */

import { dateTimeFormat } from "@/lib/intl";
import { getClock } from "@/ui/host";

const current = () => getClock().timeFormat;

/**
 * The `hour12` to hand `Intl.DateTimeFormat`. `undefined` on `system` is the
 * point: it leaves the locale's own convention alone rather than overriding it
 * with a guess at what the locale would have said.
 */
export const hour12Option = (): boolean | undefined => {
  const answer = current();
  return answer === "system" ? undefined : answer === "12";
};

/**
 * The same answer resolved to a definite yes or no, for code that has to pick
 * a pattern rather than pass an option — a date-fns format string, a hand-built
 * "9am" label. On `system` the browser is asked what its locale does.
 */
export const isHour12 = (): boolean => {
  const answer = current();
  if (answer !== "system") return answer === "12";
  return systemPrefersHour12();
};

const systemPrefersHour12 = (): boolean => {
  try {
    const resolved = dateTimeFormat(undefined, { hour: "numeric" }).resolvedOptions();
    // `hour12` is the direct answer where a runtime reports it; `hourCycle`
    // is the one every modern engine gives, and h11/h12 are the 12-hour ones.
    if (typeof resolved.hour12 === "boolean") return resolved.hour12;
    return resolved.hourCycle === "h11" || resolved.hourCycle === "h12";
  } catch {
    return true;
  }
};

/** A date-fns pattern for a time of day: "1:30 PM" or "13:30". */
export const timePattern = (options?: { seconds?: boolean }): string => {
  const minutes = options?.seconds ? "mm:ss" : "mm";
  return isHour12() ? `h:${minutes} a` : `HH:${minutes}`;
};

/** A date-fns pattern for a date and a time of day together. */
export const dateTimePattern = (datePattern: string, options?: { seconds?: boolean }): string =>
  `${datePattern} ${timePattern(options)}`;

/**
 * A wall-clock time as this account reads it. `HH:mm` and `HH:mm:ss` inputs
 * both work, which is what the half-hour slot lists and the `<input
 * type="time">` values around the event dialogs speak.
 */
export const formatClockSlot = (slot: string): string => {
  const [rawHour, rawMinute] = slot.split(":");
  const hour = Number(rawHour);
  const minute = Number(rawMinute);
  if (!Number.isInteger(hour) || !Number.isInteger(minute)) return slot;
  const paddedMinute = String(minute).padStart(2, "0");
  if (!isHour12()) return `${String(hour).padStart(2, "0")}:${paddedMinute}`;
  return `${hour % 12 || 12}:${paddedMinute} ${hour < 12 ? "AM" : "PM"}`;
};

/**
 * A whole hour as a gutter label — deliberately terse ("9am", "09"), because
 * these sit in the narrow column down the left of a day or week grid.
 */
export const formatHourLabel = (hour: number): string => {
  if (!isHour12()) return String(hour).padStart(2, "0");
  if (hour === 0) return "12am";
  if (hour < 12) return `${hour}am`;
  if (hour === 12) return "12pm";
  return `${hour - 12}pm`;
};

/**
 * A `Date`'s time of day, minutes dropped when they are zero ("9am", "9:30am",
 * "09:00"). The compact form an event block in a calendar cell wears.
 */
export const formatCompactTime = (date: Date): string => {
  const hour = date.getHours();
  const minute = date.getMinutes();
  const paddedMinute = String(minute).padStart(2, "0");
  if (!isHour12()) return `${String(hour).padStart(2, "0")}:${paddedMinute}`;
  const suffix = hour >= 12 ? "pm" : "am";
  const displayHour = hour % 12 || 12;
  return minute === 0 ? `${displayHour}${suffix}` : `${displayHour}:${paddedMinute}${suffix}`;
};
