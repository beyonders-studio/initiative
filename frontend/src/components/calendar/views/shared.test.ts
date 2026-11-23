import { addDays } from "date-fns";
import { describe, expect, it } from "vitest";

import type { CalendarEntry } from "../CalendarView";
import { computeSpanPlacements } from "./shared";

// Monday 19 October 2026 through Sunday the 25th, in local time.
const week = Array.from({ length: 7 }, (_, i) => addDays(new Date(2026, 9, 19), i));

const event = (id: string, startAt: string, endAt: string, allDay = false): CalendarEntry => ({
  id,
  title: id,
  startAt,
  endAt,
  allDay,
  meta: { type: "event", eventId: 1 },
});

describe("where the month grid puts an event", () => {
  it("puts an evening that runs past midnight on the day it starts, as a chip", () => {
    const { spans, singleDay } = computeSpanPlacements(week, [
      event("late", "2026-10-23T20:00:00", "2026-10-24T00:30:00"),
    ]);

    expect(spans).toEqual([]);
    expect(singleDay.get("2026-10-23")?.map((e) => e.id)).toEqual(["late"]);
    expect(singleDay.has("2026-10-24")).toBe(false);
  });

  it("keeps an event that ends at midnight on its own day", () => {
    const { spans, singleDay } = computeSpanPlacements(week, [
      event("evening", "2026-10-23T18:00:00", "2026-10-24T00:00:00"),
    ]);

    expect(spans).toEqual([]);
    expect(singleDay.get("2026-10-23")?.map((e) => e.id)).toEqual(["evening"]);
  });

  it("draws a bar for a timed event of a day or more, and for all-day days", () => {
    const { spans } = computeSpanPlacements(week, [
      event("retreat", "2026-10-23T18:00:00", "2026-10-25T00:00:00"),
      event("festival", "2026-10-20T00:00:00", "2026-10-21T23:59:59", true),
    ]);

    expect(spans.map(({ entry, startCol, spanCols }) => [entry.id, startCol, spanCols])).toEqual([
      ["festival", 1, 2],
      ["retreat", 4, 2],
    ]);
  });
});
