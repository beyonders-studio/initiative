import { describe, expect, it } from "vitest";

import { dateRangeBounds } from "@/lib/dateRange";

describe("dateRangeBounds", () => {
  it("flags a range whose end falls before its start, comparing date-times by time of day", () => {
    expect(dateRangeBounds("2026-09-30", "2026-03-02").isInverted).toBe(true);
    expect(dateRangeBounds("2026-03-02", "2026-09-30").isInverted).toBe(false);
    expect(dateRangeBounds("2026-03-02", "2026-03-02").isInverted).toBe(false);
    expect(dateRangeBounds("2026-03-02", "").isInverted).toBe(false);
    expect(dateRangeBounds("", "2026-03-02").isInverted).toBe(false);
    expect(dateRangeBounds(null, undefined).isInverted).toBe(false);
    expect(dateRangeBounds("2026-03-02T15:00", "2026-03-02T09:00").isInverted).toBe(true);
    expect(dateRangeBounds("2026-03-02T09:00", "2026-03-02T15:00").isInverted).toBe(false);
  });

  it("bounds each calendar by the opposite date, unless it is unset or unparsable", () => {
    const { startCalendarProps, endCalendarProps } = dateRangeBounds("2026-03-02", "2026-09-30");

    expect(startCalendarProps?.hidden.after.getDate()).toBe(30);
    expect(startCalendarProps?.hidden.after.getMonth()).toBe(8);
    expect(endCalendarProps?.hidden.before.getDate()).toBe(2);
    expect(endCalendarProps?.hidden.before.getMonth()).toBe(2);
    // An Invalid Date here would hide every day in the picker.
    expect(dateRangeBounds("2026-03-02", "").startCalendarProps).toBeUndefined();
    expect(dateRangeBounds("", "2026-03-02").endCalendarProps).toBeUndefined();
    expect(dateRangeBounds("nonsense", "2026-03-02").endCalendarProps).toBeUndefined();
  });
});
