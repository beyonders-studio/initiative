import { describe, expect, it } from "vitest";

import { eventRange } from "./EventDateTimeFields";
import {
  datesAreValid,
  endTimeOptionsFor,
  offsetEndTime,
  reconcileEndTime,
  shiftEndPreservingDuration,
  toTimeSlot,
} from "./eventDateTime";

describe("offsetEndTime", () => {
  it("adds one hour, clamping at the end of the day", () => {
    expect(offsetEndTime("09:00")).toBe("10:00");
    expect(offsetEndTime("23:00")).toBe("23:30"); // clamped to last slot
  });
});

describe("shiftEndPreservingDuration", () => {
  it("keeps a same-day duration when the start moves", () => {
    // 1-hour event; move start to 16:00 → end follows to 17:00.
    expect(
      shiftEndPreservingDuration(
        "2026-07-01",
        "09:00",
        "2026-07-01",
        "10:00",
        "2026-07-01",
        "16:00"
      )
    ).toMatchObject({
      endDate: "2026-07-01",
      endTime: "17:00",
    });
  });

  it("preserves a multi-day span and rolls the end onto a later day", () => {
    // 25-hour event (Jul 1 09:00 → Jul 2 10:00); move start to Jul 5 09:00.
    expect(
      shiftEndPreservingDuration(
        "2026-07-01",
        "09:00",
        "2026-07-02",
        "10:00",
        "2026-07-05",
        "09:00"
      )
    ).toMatchObject({
      endDate: "2026-07-06",
      endTime: "10:00",
    });
  });

  it("defaults to a one-hour duration when there is no prior end", () => {
    expect(
      shiftEndPreservingDuration("", "09:00", "", "10:00", "2026-07-01", "14:00")
    ).toMatchObject({
      endDate: "2026-07-01",
      endTime: "15:00",
    });
  });
});

describe("endTimeOptionsFor", () => {
  it("hides slots at or before the start on the same day", () => {
    const opts = endTimeOptionsFor("2026-07-01", "2026-07-01", "09:00");
    expect(opts.some((o) => o.value === "09:00")).toBe(false);
    expect(opts.some((o) => o.value === "09:30")).toBe(true);
  });

  it("allows every slot when the end is on a later day", () => {
    const opts = endTimeOptionsFor("2026-07-01", "2026-07-03", "09:00");
    expect(opts).toHaveLength(48);
    expect(opts.some((o) => o.value === "00:00")).toBe(true);
  });
});

describe("datesAreValid", () => {
  it("accepts a multi-day timed range", () => {
    expect(datesAreValid(false, "2026-07-01", "14:00", "2026-07-03", "16:00")).toBe(true);
  });

  it("rejects an end before the start", () => {
    expect(datesAreValid(false, "2026-07-03", "16:00", "2026-07-01", "14:00")).toBe(false);
  });

  it("allows an all-day event ending on the same day", () => {
    expect(datesAreValid(true, "2026-07-01", "00:00", "2026-07-01", "00:00")).toBe(true);
  });
});

describe("reconcileEndTime", () => {
  it("snaps a now-invalid end time forward when the end rolls back to the start day", () => {
    // End was 12:00 on a later day; rolled back to the start day where the
    // start is 14:00 — 12:00 is no longer selectable, so snap to 15:00.
    expect(reconcileEndTime("2026-07-01", "14:00", "2026-07-01", "12:00")).toBe("15:00");
  });

  it("leaves a still-valid same-day end time untouched", () => {
    expect(reconcileEndTime("2026-07-01", "09:00", "2026-07-01", "10:00")).toBe("10:00");
  });

  it("leaves the end time untouched when the end is on a later day", () => {
    expect(reconcileEndTime("2026-07-01", "14:00", "2026-07-03", "12:00")).toBe("12:00");
  });
});

describe("toTimeSlot", () => {
  it("preserves imported off-grid times", () => {
    expect(toTimeSlot(new Date("2026-07-01T14:15:00"))).toBe("14:15");
    expect(toTimeSlot(new Date("2026-07-01T14:07:00"))).toBe("14:07");
  });
});

describe("precise event ranges", () => {
  it("preserves an unchanged off-grid start when its end changes", () => {
    const start = new Date("2026-07-01T09:15:27.123").toISOString();
    expect(
      eventRange({
        allDay: false,
        startDate: "2026-07-01",
        startTime: "09:15",
        endDate: "2026-07-01",
        endTime: "11:00",
        startInstant: start,
      })
    ).toEqual({ start_at: start, end_at: new Date("2026-07-01T11:00:00").toISOString() });
  });
});
