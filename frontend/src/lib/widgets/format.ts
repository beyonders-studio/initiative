/**
 * Number and date formatting for scenes.
 *
 * Deliberately on this side of the sandbox: the widget says *what kind* of
 * value it produced and the app decides how a human reads it, using the
 * viewer's locale and timezone. A widget has neither — its clock is frozen and
 * it has no `Intl` locale data — so this is the only place formatting can
 * correctly happen.
 */

import { dateTimeFormat, numberFormat } from "@/ui/lib/intl";

import type { NumberFormat, SeriesTimeUnit } from "./sceneSpec";

const DURATION_UNITS: [number, string][] = [
  [86_400_000, "d"],
  [3_600_000, "h"],
  [60_000, "m"],
  [1_000, "s"],
];

/** Milliseconds as a compact "2d 4h". Zero is "0s" rather than empty, so a tile
 *  reads as measured rather than missing. */
const formatDuration = (ms: number): string => {
  if (!Number.isFinite(ms)) return "—";
  const sign = ms < 0 ? "-" : "";
  let rest = Math.abs(ms);
  const parts: string[] = [];
  for (const [size, suffix] of DURATION_UNITS) {
    if (rest >= size) {
      parts.push(`${Math.floor(rest / size)}${suffix}`);
      rest %= size;
    }
    if (parts.length === 2) break;
  }
  return sign + (parts.join(" ") || "0s");
};

export interface FormatOptions {
  locale?: string;
  /** ISO 4217. Falls back to USD only when a scene asks for currency without
   *  the app having said which — the alternative is throwing. */
  currency?: string;
}

export function formatValue(
  value: number,
  format: NumberFormat | undefined,
  options: FormatOptions = {}
): string {
  if (!Number.isFinite(value)) return "—";
  const locale = options.locale;

  switch (format) {
    case "percent":
      return numberFormat(locale, {
        style: "percent",
        maximumFractionDigits: 1,
      }).format(value);

    case "currency":
      return numberFormat(locale, {
        style: "currency",
        currency: options.currency ?? "USD",
        maximumFractionDigits: 0,
      }).format(value);

    case "compact":
      return numberFormat(locale, {
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(value);

    case "duration":
      return formatDuration(value);

    case "date":
    case "date-only":
      return dateTimeFormat(locale, {
        ...(format === "date-only" ? { timeZone: "UTC" } : {}),
        month: "short",
        day: "numeric",
        year: "numeric",
      }).format(new Date(value));

    default:
      return numberFormat(locale, {
        maximumFractionDigits: 2,
      }).format(value);
  }
}

/** Axis ticks and cell labels, where a full date is too long. */
export const formatAxisValue = (
  value: string | number,
  format: NumberFormat | undefined,
  options: FormatOptions = {}
): string => {
  if (typeof value === "string") return value;
  if (format === "date" || format === "date-only") {
    return dateTimeFormat(options.locale, {
      ...(format === "date-only" ? { timeZone: "UTC" } : {}),
      month: "short",
      day: "numeric",
    }).format(new Date(value));
  }
  return formatValue(value, format ?? "compact", options);
};

/** A moment on a time series, labelled at the grain the series is grouped by.
 *
 *  Read in UTC: the database rounds a date down to its day, week, month… at
 *  midnight UTC, and reading that in a timezone west of it would label every
 *  point with the day before. */
export const formatTimeBucket = (
  value: string | number,
  unit: SeriesTimeUnit,
  options: FormatOptions = {}
): string => {
  const at = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(at)) return String(value);
  const date = new Date(at);
  const utc = { timeZone: "UTC" } as const;
  switch (unit) {
    case "year":
      return String(date.getUTCFullYear());
    case "quarter":
      return `Q${Math.floor(date.getUTCMonth() / 3) + 1} ${date.getUTCFullYear()}`;
    case "month":
      return dateTimeFormat(options.locale, {
        ...utc,
        month: "short",
        year: "numeric",
      }).format(date);
    default:
      return dateTimeFormat(options.locale, {
        ...utc,
        month: "short",
        day: "numeric",
      }).format(date);
  }
};
