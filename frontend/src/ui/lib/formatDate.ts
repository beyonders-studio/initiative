import { dateTimeFormat } from "@/ui/lib/intl";
import { hour12Option } from "@/ui/lib/timeFormat";

// A bare calendar date (no time, no zone) — how the API sends DATE columns.
const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

// `new Date("2026-08-10")` is UTC midnight, which renders as the previous day
// west of Greenwich. A date-only value names a calendar day, so build it in
// local time and it formats as the day it says.
const toDate = (value: string): Date => {
  const match = DATE_ONLY.exec(value);
  return match
    ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
    : new Date(value);
};

const format = (value: unknown, withTime: boolean): string => {
  if (typeof value !== "string" || !value) return "";
  const date = toDate(value);
  if (Number.isNaN(date.getTime())) return "";
  return dateTimeFormat(undefined, {
    dateStyle: "medium",
    ...(withTime ? { timeStyle: "short", hour12: hour12Option() } : {}),
  }).format(date);
};

/**
 * Parse an API date value into a `Date`, or `null` when it is missing or
 * unparsable. Date-only values resolve to the local calendar day, matching
 * what {@link formatDate} renders.
 */
export const parseDateValue = (value: string | null | undefined): Date | null => {
  if (!value) return null;
  const date = toDate(value);
  return Number.isNaN(date.getTime()) ? null : date;
};

/**
 * Medium browser-locale date (e.g. "Aug 3, 2026"). Returns "" for missing or
 * unparsable input — callers supply their own placeholder
 * (`formatDate(v) || "—"`).
 */
export const formatDate = (value: unknown): string => format(value, false);

/** {@link formatDate} plus a short time (e.g. "Aug 3, 2026, 9:15 PM"). */
export const formatDateTime = (value: unknown): string => format(value, true);

const pad2 = (value: number): string => String(value).padStart(2, "0");

const dayKeyOf = (date: Date): string =>
  `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;

/**
 * The reader's local calendar day an instant falls on, as `YYYY-MM-DD`, or
 * `""` when it is missing or unparsable. Keys compare and sort as days, and
 * {@link formatDayHeading} takes one back.
 *
 * Local, not UTC: an evening message west of Greenwich is already tomorrow in
 * UTC, and grouping by that would file it under the wrong day.
 */
export const localDayKey = (value: string | null | undefined): string => {
  const date = parseDateValue(value);
  return date ? dayKeyOf(date) : "";
};

/**
 * What to head a day with in a list grouped by day: "Today", "Yesterday", or
 * the date (e.g. "Wed, Jul 22, 2026"). Takes a {@link localDayKey} or an
 * instant; `""` when it is neither.
 *
 * The two days somebody is most likely to be reading are named rather than
 * dated: "Wed, Jul 22" is a fact to work out, and "Today" is one to recognise.
 */
export const formatDayHeading = (value: string, t: (key: string) => string): string => {
  const date = parseDateValue(value);
  if (!date) return "";
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const key = dayKeyOf(date);
  if (key === dayKeyOf(today)) return t("ui:days.today");
  if (key === dayKeyOf(yesterday)) return t("ui:days.yesterday");
  return dateTimeFormat(undefined, {
    weekday: "short",
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(date);
};

// A `YYYY-MM` period, as a timeline groups by. Built as a local date on the
// first of the month for the same reason `toDate` builds date-only values
// locally: parsed as UTC it renders as the previous month west of Greenwich,
// which would label a rail's ticks one month out.
const PERIOD = /^(\d{4})-(\d{2})$/;

const periodDate = (period: string): Date | null => {
  const match = PERIOD.exec(period);
  return match ? new Date(Number(match[1]), Number(match[2]) - 1, 1) : null;
};

/** A `YYYY-MM` period as a month and year in the browser's locale, e.g.
 *  "March 2026". Returns the raw period if it is not one. */
export const formatPeriod = (period: string): string => {
  const date = periodDate(period);
  return date ? dateTimeFormat(undefined, { month: "long", year: "numeric" }).format(date) : period;
};

/** Just the year of a `YYYY-MM` period, for a timeline's group headings. */
export const formatPeriodYear = (period: string): string => {
  const date = periodDate(period);
  return date ? dateTimeFormat(undefined, { year: "numeric" }).format(date) : period;
};

/**
 * An ISO instant as the local wall-clock string `<input type="datetime-local">`
 * and {@link DateTimePicker} both speak (`YYYY-MM-DDTHH:mm`), or `""` when
 * there is nothing to show.
 *
 * The offset subtraction is the point: `toISOString` renders UTC, and a picker
 * showing UTC would put a notice scheduled for 9am on the wrong hour for
 * everyone not on Greenwich.
 */
export const toLocalDateTimeInput = (value: string | null | undefined): string => {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
};

/** Whole minutes from now until `expiresAt` (never below 0), or `null` when there is none. */
export const minutesLeft = (expiresAt?: string | null): number | null => {
  if (!expiresAt) return null;
  return Math.max(0, Math.round((new Date(expiresAt).getTime() - Date.now()) / 60000));
};

/** The inverse: a picker's local wall-clock string as an ISO instant, or `null`. */
export const fromLocalDateTimeInput = (value: string): string | null => {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
};
