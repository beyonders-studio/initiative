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
  it.each([
    // 1-hour event; move start to 16:00 → end follows to 17:00.
    [
      "keeps a same-day duration",
      ["2026-07-01", "09:00", "2026-07-01", "10:00"],
      ["2026-07-01", "16:00"],
      ["2026-07-01", "17:00"],
    ],
    // 25-hour event (Jul 1 09:00 → Jul 2 10:00); move start to Jul 5 09:00.
    [
      "rolls a multi-day span onto a later day",
      ["2026-07-01", "09:00", "2026-07-02", "10:00"],
      ["2026-07-05", "09:00"],
      ["2026-07-06", "10:00"],
    ],
    [
      "defaults to one hour with no prior end",
      ["", "09:00", "", "10:00"],
      ["2026-07-01", "14:00"],
      ["2026-07-01", "15:00"],
    ],
  ] as const)(
    "%s",
    (_label, [startDate, startTime, endDate, endTime], [nextDate, nextTime], [
      wantDate,
      wantTime,
    ]) => {
      expect(
        shiftEndPreservingDuration(startDate, startTime, endDate, endTime, nextDate, nextTime)
      ).toMatchObject({ endDate: wantDate, endTime: wantTime });
    }
  );
});

describe("endTimeOptionsFor", () => {
  it("hides slots at or before the start on the same day, and allows every slot on a later day", () => {
    const opts = endTimeOptionsFor("2026-07-01", "2026-07-01", "09:00");
    expect(opts.some((o) => o.value === "09:00")).toBe(false);
    expect(opts.some((o) => o.value === "09:30")).toBe(true);

    const later = endTimeOptionsFor("2026-07-01", "2026-07-03", "09:00");
    expect(later).toHaveLength(48);
    expect(later.some((o) => o.value === "00:00")).toBe(true);
  });
});

describe("datesAreValid", () => {
  it.each([
    ["a multi-day timed range", false, "2026-07-01", "14:00", "2026-07-03", "16:00", true],
    ["an end before the start", false, "2026-07-03", "16:00", "2026-07-01", "14:00", false],
    [
      "an all-day event ending on the same day",
      true,
      "2026-07-01",
      "00:00",
      "2026-07-01",
      "00:00",
      true,
    ],
  ])("judges %s valid: %s", (_label, allDay, startDate, startTime, endDate, endTime, valid) => {
    expect(datesAreValid(allDay, startDate, startTime, endDate, endTime)).toBe(valid);
  });
});

describe("reconcileEndTime", () => {
  it.each([
    // End was 12:00 on a later day; rolled back to the start day where the
    // start is 14:00 — 12:00 is no longer selectable, so snap to 15:00.
    ["snaps a now-invalid end forward on the start day", "14:00", "2026-07-01", "12:00", "15:00"],
    ["leaves a still-valid same-day end", "09:00", "2026-07-01", "10:00", "10:00"],
    ["leaves an end on a later day", "14:00", "2026-07-03", "12:00", "12:00"],
  ])("%s", (_label, startTime, endDate, endTime, expected) => {
    expect(reconcileEndTime("2026-07-01", startTime, endDate, endTime)).toBe(expected);
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
