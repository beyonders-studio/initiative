/**
 * Shared IANA timezone list for any UI that lets the user pick one
 * (Settings → Profile, Settings → Notifications, …).
 *
 * Prefers ``Intl.supportedValuesOf("timeZone")`` (returns the full
 * IANA list the runtime knows about). Falls back to a small curated
 * set when the API isn't available — old browsers, locked-down
 * environments, or test runners with stripped Intl data.
 */

import { dateTimeFormat } from "@/ui/lib/intl";

const FALLBACK_TIMEZONES = [
  "UTC",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "Europe/London",
  "Europe/Berlin",
  "Europe/Paris",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
];

const resolveTimezones = (): string[] => {
  const intl = Intl as typeof Intl & { supportedValuesOf?: (key: string) => string[] };
  if (typeof intl.supportedValuesOf === "function") {
    try {
      // Chromium's list leaves out "UTC", which is the account default.
      const zones = intl.supportedValuesOf("timeZone");
      return zones.includes("UTC") ? zones : ["UTC", ...zones];
    } catch {
      return FALLBACK_TIMEZONES;
    }
  }
  return FALLBACK_TIMEZONES;
};

/** Resolved once at module load — the list doesn't change at runtime. */
export const TIMEZONE_OPTIONS = resolveTimezones();

/**
 * Whether this runtime can show the time in a zone: any zone in the list, or
 * one the list leaves out but `Intl` still knows. A runtime that cannot
 * enumerate its zones offers a short list to pick from, but a zone named
 * somewhere else (a published home layout's clock) still draws there.
 */
export const isKnownTimezone = (zone: string): boolean => {
  if (TIMEZONE_OPTIONS.includes(zone)) return true;
  try {
    dateTimeFormat("en-US", { timeZone: zone });
    return true;
  } catch {
    return false;
  }
};
