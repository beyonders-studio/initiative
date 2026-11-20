import { afterEach, describe, expect, it } from "vitest";

import {
  getClock,
  notifyClock,
  parseTimeFormat,
  parseWeekStart,
  setClock,
  subscribeClock,
  writeClock,
} from "@/ui/host";
import { formatDateTime } from "@/ui/lib/formatDate";
import {
  dateTimePattern,
  formatClockSlot,
  formatCompactTime,
  formatHourLabel,
  hour12Option,
  isHour12,
  timePattern,
} from "@/ui/lib/timeFormat";

afterEach(() => {
  setClock({ timeFormat: "system", weekStart: 0 });
});

describe("parseTimeFormat", () => {
  // An older client, a hand-edited row, or a field that isn't there yet all
  // fall back to system, and none of them should force a convention on the reader.
  it.each([
    ["system", "system"],
    ["12", "12"],
    ["24", "24"],
    ["48", "system"],
    [undefined, "system"],
    [null, "system"],
  ])("reads %s as %s", (raw, expected) => {
    expect(parseTimeFormat(raw)).toBe(expected);
  });
});

describe("parseWeekStart", () => {
  it("keeps a day of the week and falls back to Sunday", () => {
    expect(parseWeekStart(1)).toBe(1);
    expect(parseWeekStart(6)).toBe(6);
    expect(parseWeekStart(7)).toBe(0);
    expect(parseWeekStart(null)).toBe(0);
  });
});

describe("the hour convention", () => {
  // The test runtime is en-US, which is a 12-hour locale.
  it.each([
    ["system", undefined, true],
    ["12", true, true],
    ["24", false, false],
  ] as const)("on %s, states %s and answers %s", (timeFormat, option, hour12) => {
    setClock({ timeFormat });
    expect(hour12Option()).toBe(option);
    expect(isHour12()).toBe(hour12);
  });
});

describe("patterns", () => {
  it("switches the date-fns time pattern, keeping seconds when asked", () => {
    setClock({ timeFormat: "12" });
    expect(timePattern()).toBe("h:mm a");
    expect(dateTimePattern("PP")).toBe("PP h:mm a");
    expect(timePattern({ seconds: true })).toBe("h:mm:ss a");

    setClock({ timeFormat: "24" });
    expect(timePattern()).toBe("HH:mm");
    expect(dateTimePattern("PP")).toBe("PP HH:mm");
    expect(dateTimePattern("PP", { seconds: true })).toBe("PP HH:mm:ss");
  });
});

describe("formatClockSlot", () => {
  it("renders a half-hour slot on each clock", () => {
    setClock({ timeFormat: "12" });
    expect(formatClockSlot("00:00")).toBe("12:00 AM");
    expect(formatClockSlot("09:30")).toBe("9:30 AM");
    expect(formatClockSlot("13:30")).toBe("1:30 PM");

    setClock({ timeFormat: "24" });
    expect(formatClockSlot("00:00")).toBe("00:00");
    expect(formatClockSlot("09:30")).toBe("09:30");
    expect(formatClockSlot("13:30")).toBe("13:30");
  });

  it("hands back anything that isn't a slot", () => {
    expect(formatClockSlot("not a time")).toBe("not a time");
  });
});

describe("formatHourLabel", () => {
  it("renders a gutter hour on each clock", () => {
    setClock({ timeFormat: "12" });
    expect([0, 9, 12, 15].map(formatHourLabel)).toEqual(["12am", "9am", "12pm", "3pm"]);

    setClock({ timeFormat: "24" });
    expect([0, 9, 12, 15].map(formatHourLabel)).toEqual(["00", "09", "12", "15"]);
  });
});

describe("formatCompactTime", () => {
  const at = (hours: number, minutes: number) => new Date(2026, 0, 15, hours, minutes);

  it("drops the minutes on the hour in 12-hour, and always shows both in 24-hour", () => {
    setClock({ timeFormat: "12" });
    expect(formatCompactTime(at(9, 0))).toBe("9am");
    expect(formatCompactTime(at(9, 30))).toBe("9:30am");
    expect(formatCompactTime(at(13, 5))).toBe("1:05pm");

    // So widths line up.
    setClock({ timeFormat: "24" });
    expect(formatCompactTime(at(9, 0))).toBe("09:00");
    expect(formatCompactTime(at(13, 5))).toBe("13:05");
  });
});

describe("writeClock", () => {
  it("takes effect for a formatter without notifying anybody", () => {
    let calls = 0;
    const unsubscribe = subscribeClock(() => {
      calls += 1;
    });

    expect(writeClock({ timeFormat: "24" })).toBe(true);
    expect(isHour12()).toBe(false);
    expect(calls).toBe(0);

    // Repeating the same answer is a no-op, which is what makes it safe to
    // call on every render of the root.
    expect(writeClock({ timeFormat: "24" })).toBe(false);

    notifyClock();
    expect(calls).toBe(1);
    unsubscribe();
  });

  it("keeps the week start beside the time format", () => {
    expect(writeClock({ weekStart: 1 })).toBe(true);
    expect(getClock()).toEqual({ timeFormat: "system", weekStart: 1 });
  });
});

describe("subscribeClock", () => {
  it("notifies on a change and not on a repeat", () => {
    let calls = 0;
    const unsubscribe = subscribeClock(() => {
      calls += 1;
    });

    setClock({ timeFormat: "24" });
    setClock({ timeFormat: "24" });
    expect(calls).toBe(1);

    unsubscribe();
    setClock({ timeFormat: "12" });
    expect(calls).toBe(1);
  });
});

describe("formatDateTime", () => {
  it("follows the preference, a date-only value's midnight included", () => {
    setClock({ timeFormat: "24" });
    expect(formatDateTime("2026-08-03T21:15:00Z")).not.toMatch(/\b(AM|PM)\b/);
    expect(formatDateTime("2026-08-03")).toBe("Aug 3, 2026, 00:00");

    setClock({ timeFormat: "12" });
    expect(formatDateTime("2026-08-03T21:15:00Z")).toMatch(/\b(AM|PM)\b/);
    expect(formatDateTime("2026-08-03")).toBe("Aug 3, 2026, 12:00 AM");
  });
});
