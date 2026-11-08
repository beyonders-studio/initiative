import { parseLocalCalendarDate, resolveLocalDateTime } from "@/ui/lib/localDateTime";

// Shared date/time helpers for the event create dialog and edit page so both
// use the identical pickers, half-hour slots, and duration-preserving logic.

export const DEFAULT_DURATION_MINUTES = 60;
const DAY_END_MINUTES = 23 * 60 + 30; // last selectable slot (23:30)

// Half-hour time slots, as the `HH:MM` values a Select binds to. The label a
// reader sees is `formatClockSlot(value)` at render time, because it depends on
// the account's clock convention and this list is built once per module.
export const TIME_OPTIONS = Array.from({ length: 48 }, (_, i) => {
  const hour = String(Math.floor(i / 2)).padStart(2, "0");
  const minute = i % 2 === 0 ? "00" : "30";
  return { value: `${hour}:${minute}` };
});

export const toMinutes = (slot: string): number => {
  const [h, m] = slot.split(":").map(Number);
  return h * 60 + m;
};

export const toSlot = (minutes: number): string => {
  const clamped = Math.max(0, Math.min(minutes, DAY_END_MINUTES));
  return `${String(Math.floor(clamped / 60)).padStart(2, "0")}:${String(clamped % 60).padStart(2, "0")}`;
};

// Slot one hour after `start`, used to seed the end time on first open.
export const offsetEndTime = (start: string): string =>
  toSlot(toMinutes(start) + DEFAULT_DURATION_MINUTES);

// Parse a "yyyy-MM-dd" string as a local date to avoid the UTC-midnight shift
// that `new Date("yyyy-MM-dd")` introduces in negative-offset timezones.
export const parseLocalDate = (value: string): Date | undefined =>
  parseLocalCalendarDate(value) ?? undefined;

// Gap/fold input is refused unless an unchanged original identifies the instant.
export const composeDateTime = (date: string, time: string, original?: string): Date | null =>
  resolveLocalDateTime(date, time || "00:00", original);

export const toDateKey = (d: Date): string =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

export const toTimeSlot = (d: Date): string =>
  `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;

/**
 * Given the current start/end (each a date + time slot) and a new start,
 * return the end that keeps the event's current length. A 90-minute event
 * stays 90 minutes; a multi-day event keeps its span (the end may land on a
 * later day). Returns null when the next start can't be parsed.
 */
export const shiftEndPreservingDuration = (
  prevStartDate: string,
  prevStartTime: string,
  prevEndDate: string,
  prevEndTime: string,
  nextDate: string,
  nextTime: string,
  originalStart?: string,
  originalEnd?: string
): { endDate: string; endTime: string; endInstant: string } | null => {
  const nextStart = composeDateTime(nextDate, nextTime, originalStart);
  if (!nextStart) return null;
  const prevStart = composeDateTime(prevStartDate, prevStartTime, originalStart);
  const prevEnd = composeDateTime(prevEndDate || prevStartDate, prevEndTime, originalEnd);
  const durationMs = prevStart && prevEnd ? prevEnd.getTime() - prevStart.getTime() : 0;
  const keepMs = durationMs > 0 ? durationMs : DEFAULT_DURATION_MINUTES * 60_000;
  const nextEnd = new Date(nextStart.getTime() + keepMs);
  return {
    endDate: toDateKey(nextEnd),
    endTime: toTimeSlot(nextEnd),
    endInstant: nextEnd.toISOString(),
  };
};

// When the end date moves onto the start day and the current end time is no
// longer after the start, snap it forward so the end-time Select never shows a
// value that its filtered options exclude. Across days (or when still valid)
// the end time is left untouched.
export const reconcileEndTime = (
  startDate: string,
  startTime: string,
  nextEndDate: string,
  endTime: string
): string => {
  if (nextEndDate === startDate && toMinutes(endTime) <= toMinutes(startTime)) {
    return offsetEndTime(startTime);
  }
  return endTime;
};

// End-time slots offered for the given range. On the same day the end must be
// after the start, so earlier slots are hidden; across days every time is valid.
export const endTimeOptionsFor = (startDate: string, endDate: string, startTime: string) => {
  if (startDate && endDate && endDate !== startDate) return TIME_OPTIONS;
  const startMinutes = toMinutes(startTime);
  return TIME_OPTIONS.filter((opt) => toMinutes(opt.value) > startMinutes);
};

// Whether the start/end pair is a valid (non-negative-length) range.
export const datesAreValid = (
  allDay: boolean,
  startDate: string,
  startTime: string,
  endDate: string,
  endTime: string,
  originalStart?: string,
  originalEnd?: string
): boolean => {
  if (!startDate) return false;
  if (allDay) {
    const s = parseLocalDate(startDate);
    const e = parseLocalDate(endDate || startDate);
    return !!s && !!e && e >= s;
  }
  const s = composeDateTime(startDate, startTime, originalStart);
  const e = composeDateTime(endDate || startDate, endTime, originalEnd);
  return !!s && !!e && e > s;
};
