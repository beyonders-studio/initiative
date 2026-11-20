import { describe, expect, it } from "vitest";

import { calendarVisibleRange } from "./visibleRange";

// Local-time construction throughout: the range feeds a query window that the
// user reads in their own timezone.
const FOCUS = new Date(2026, 1, 11, 13, 30); // Wed 11 Feb 2026, mid-afternoon

const iso = (d: Date) => `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;

describe("calendarVisibleRange", () => {
  it.each([
    ["day", FOCUS, undefined, "2026-2-11", "2026-2-11"],
    ["week", FOCUS, undefined, "2026-2-8", "2026-2-14"],
    ["week", FOCUS, 1 as const, "2026-2-9", "2026-2-15"],
    // Feb 2026 happens to run Sun 1 → Sat 28: a grid with no padding at all.
    ["month", FOCUS, undefined, "2026-2-1", "2026-2-28"],
    // Jan 2026 runs Thu 1 → Sat 31, so its grid opens on Sun 28 Dec 2025: those
    // December days are on screen and their tasks have to be fetched.
    ["month", new Date(2026, 0, 15), undefined, "2025-12-28", "2026-1-31"],
    ["year", FOCUS, undefined, "2026-1-1", "2026-12-31"],
    // The list covers the focus month exactly, without week padding.
    ["list", FOCUS, undefined, "2026-2-1", "2026-2-28"],
  ] as const)(
    "%s view of %s (week starts %s) runs %s to %s",
    (view, focus, weekStartsOn, from, to) => {
      const { start, end } = calendarVisibleRange(focus, view, weekStartsOn);
      expect(iso(start)).toBe(from);
      expect(iso(end)).toBe(to);
      // Whole days: from midnight, and inclusive of the final day.
      expect(start.getHours()).toBe(0);
      expect([end.getHours(), end.getMinutes()]).toEqual([23, 59]);
    }
  );
});
