/**
 * A repeat goes out as the RRULE its days were picked in, and comes back from
 * the server in UTC terms: read in the viewer's zone, it is the rule the form
 * built. Berlin, so a Monday 00:30 start is a Sunday in UTC.
 */
process.env.TZ = "Europe/Berlin";

import { describe, expect, it } from "vitest";

import {
  fromStored,
  isValidTaskRecurrence,
  maxOccurrences,
  type RecurrenceRule,
  summarizeStored,
  toRRule,
} from "@/ui/recurrence/recurrence";

const rule = (overrides: Partial<RecurrenceRule>): RecurrenceRule => ({
  frequency: "weekly",
  interval: 1,
  weekdays: [],
  monthly_mode: "day_of_month",
  month_days: [],
  months: [],
  weekday_position: null,
  weekday: null,
  set_position: "last",
  ends: "never",
  end_after_occurrences: null,
  end_date: null,
  ...overrides,
});

// Monday 5 October 2026, 00:30 in Berlin.
const START = "2026-10-04T22:30:00Z";

describe("toRRule", () => {
  it.each([29, 30, 31])("keeps every selected yearly month when clamping day %i", (day) => {
    const picked = rule({ frequency: "yearly", month_days: [day], months: [1, 2, 4, 7] });
    const stored = toRRule(picked);
    expect(stored).not.toContain("BYSETPOS");
    expect(stored).toContain("BYYEARDAY=");
    expect(fromStored(stored, "2026-01-29T09:00:00Z")).toEqual(picked);
  });

  it("keeps arbitrary year-day rules custom instead of guessing their intent", () => {
    expect(
      fromStored("RRULE:FREQ=YEARLY;BYYEARDAY=1,200;BYMONTH=1,7", "2026-01-01T09:00:00Z")
    ).toBe("custom");
  });

  it("writes the picked days, and the end of the picked day in UTC", () => {
    expect(toRRule(rule({ weekdays: ["wednesday", "monday"] }))).toBe(
      "RRULE:FREQ=WEEKLY;BYDAY=MO,WE"
    );
    expect(
      toRRule(
        rule({
          frequency: "monthly",
          monthly_mode: "weekday",
          weekday_position: "second",
          weekday: "monday",
          ends: "on_date",
          end_date: "2026-12-14",
        })
      )
    ).toBe("RRULE:FREQ=MONTHLY;BYDAY=2MO;UNTIL=20261214T225959Z");
    // The 31st falls on a short month's last day, as it always has.
    expect(toRRule(rule({ frequency: "monthly", month_days: [31] }))).toBe(
      "RRULE:FREQ=MONTHLY;BYMONTHDAY=28,29,30,31;BYSETPOS=-1"
    );
    expect(
      toRRule(rule({ frequency: "daily", ends: "on_date", end_date: "2026-12-14" }), {
        allDay: true,
      })
    ).toBe("RRULE:FREQ=DAILY;UNTIL=20261214");
    // A counted repeat ends within a hundred years of its first.
    expect(maxOccurrences(rule({ frequency: "yearly" }))).toBe(101);
    expect(maxOccurrences(rule({ frequency: "yearly", interval: 366 }))).toBe(1);
    expect(maxOccurrences(rule({ frequency: "daily" }))).toBe(10000);
  });
});

describe("every shape the editor builds", () => {
  const shapes: [Partial<RecurrenceRule>, string][] = [
    [{ frequency: "monthly", month_days: [-1, 15, 1] }, "RRULE:FREQ=MONTHLY;BYMONTHDAY=1,15,-1"],
    [
      {
        frequency: "monthly",
        monthly_mode: "weekday",
        weekday_position: "fifth",
        weekday: "friday",
      },
      "RRULE:FREQ=MONTHLY;BYDAY=5FR",
    ],
    [
      {
        frequency: "monthly",
        interval: 2,
        monthly_mode: "weekdays",
        weekdays: ["monday", "wednesday"],
      },
      "RRULE:FREQ=MONTHLY;INTERVAL=2;BYDAY=MO,WE",
    ],
    [
      {
        frequency: "monthly",
        monthly_mode: "set",
        weekdays: ["monday", "tuesday", "wednesday", "thursday", "friday"],
      },
      "RRULE:FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1",
    ],
    [
      { frequency: "yearly", month_days: [15], months: [7, 1] },
      "RRULE:FREQ=YEARLY;BYMONTHDAY=15;BYMONTH=1,7",
    ],
  ];

  it.each(shapes)("writes and reads back %j", (picked, line) => {
    const built = rule(picked);
    expect(toRRule(built)).toBe(line);
    // Read back where it was picked, it is the rule that was built.
    expect(fromStored(line, START, 1440)).toEqual({
      ...built,
      month_days: [...(built.month_days ?? [])].sort(
        (a, b) => (a === -1 ? 32 : a) - (b === -1 ? 32 : b)
      ),
      months: [...(built.months ?? [])].sort((a, b) => a - b),
    });
  });

  it("says each in words", () => {
    const t = ((key: string, values?: Record<string, unknown>) =>
      values ? `${key}(${Object.values(values).join("|")})` : key) as Parameters<
      typeof summarizeStored
    >[3];
    expect(
      summarizeStored("RRULE:FREQ=MONTHLY;BYMONTHDAY=-1", START, { shift: 1440 }, t)
    ).toContain("ui:recurrence.summary.onLastDay");
    expect(
      summarizeStored(
        "RRULE:FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=1",
        START,
        { shift: 1440 },
        t
      )
    ).toContain("ui:recurrence.summary.onFirstWorkDay");
  });

  it("reads an all-day event's days as they are, and a year's last work day as custom", () => {
    // An all-day event's days are UTC dates, the same for every viewer.
    expect(fromStored("RRULE:FREQ=WEEKLY;BYDAY=MO", START, 0, true)).toMatchObject({
      weekdays: ["monday"],
    });
    // The last of some days is taken once a year there, not once a month.
    expect(
      fromStored("RRULE:FREQ=YEARLY;BYMONTH=1,7;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1", START, 1440)
    ).toBe("custom");
  });

  it("reads a set or every-weekday rule from another zone's days as custom", () => {
    // In UTC days (no shift), Berlin's Monday is a Sunday: the last weekday of
    // a month moves across its end on some months, so no one rule says it.
    expect(fromStored("RRULE:FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1", START)).toBe("custom");
    expect(fromStored("RRULE:FREQ=MONTHLY;BYDAY=MO", START)).toBe("custom");
  });
});

describe("fromStored", () => {
  it("reads a rule as picked, and one in UTC days in the viewer's", () => {
    // Picked here, in Berlin: the days are the viewer's already.
    expect(fromStored("RRULE:FREQ=WEEKLY;BYDAY=MO,WE", START, 1440)).toMatchObject({
      weekdays: ["monday", "wednesday"],
    });
    // In UTC days (no shift): read on Berlin's side of midnight.
    expect(fromStored("RRULE:FREQ=WEEKLY;BYDAY=SU,TU", START)).toMatchObject({
      frequency: "weekly",
      weekdays: ["monday", "wednesday"],
    });
    expect(
      fromStored(
        "RRULE:FREQ=MONTHLY;UNTIL=20261214T225959Z;BYDAY=SU;BYMONTHDAY=7,8,9,10,11,12,13",
        START
      )
    ).toMatchObject({
      monthly_mode: "weekday",
      weekday_position: "second",
      weekday: "monday",
      ends: "on_date",
      end_date: "2026-12-14",
    });
    expect(fromStored("RRULE:FREQ=MONTHLY;BYMONTHDAY=28,29,30,31;BYSETPOS=-1", null)).toMatchObject(
      { month_days: [31] }
    );
    expect(fromStored(null, START)).toBeNull();
  });

  it("keeps a rule the form can't show as custom", () => {
    expect(fromStored("RRULE:FREQ=HOURLY;BYHOUR=9,17", START)).toBe("custom");
    expect(fromStored("RRULE:FREQ=WEEKLY\nEXDATE:20261012T223000Z", START)).toBe("custom");
    const t = ((key: string) => key) as Parameters<typeof summarizeStored>[3];
    expect(summarizeStored("RRULE:FREQ=HOURLY", START, undefined, t)).toBe(
      "ui:recurrence.summary.custom"
    );
  });
});

describe("hourly completion repeat", () => {
  it("roundtrips a normal hourly RRULE only for consumers that support it", () => {
    const hourly = rule({ frequency: "hourly", interval: 4 });
    expect(toRRule(hourly)).toBe("RRULE:FREQ=HOURLY;INTERVAL=4");
    expect(fromStored(toRRule(hourly), START, 0, false, true)).toEqual(hourly);
    expect(fromStored(toRRule(hourly), START)).toBe("custom");
    expect(fromStored("RRULE:FREQ=HOURLY;INTERVAL=4;BYHOUR=9,17", START, 0, false, true)).toBe(
      "custom"
    );
  });

  it("summarises hourly units and an optional daily maximum", () => {
    const translate = (key: string) => key;
    const limited = summarizeStored(
      "RRULE:FREQ=HOURLY;INTERVAL=4",
      START,
      { strategy: "rolling", limit: 3 },
      translate
    );
    expect(limited).toContain("ui:recurrence.summary.afterCompletion");
    expect(limited).toContain("ui:recurrence.summary.dailyLimit");
    expect(
      summarizeStored(
        "RRULE:FREQ=HOURLY;INTERVAL=4",
        START,
        { strategy: "rolling", limit: null },
        translate
      )
    ).not.toContain("ui:recurrence.summary.dailyLimit");
    expect(
      summarizeStored("RRULE:FREQ=HOURLY", START, { strategy: "rolling" }, translate)
    ).not.toBe("ui:recurrence.summary.custom");
  });

  it("accepts no maximum or any integer maximum from 1 to 24 without promising a daily count", () => {
    const hourly = rule({ frequency: "hourly", interval: 4 });
    expect(isValidTaskRecurrence({ rule: hourly, strategy: "rolling", limit: null })).toBe(true);
    expect(isValidTaskRecurrence({ rule: hourly, strategy: "rolling", limit: 7 })).toBe(true);
    expect(isValidTaskRecurrence({ rule: hourly, strategy: "rolling", limit: 24 })).toBe(true);
    for (const limit of [0, 25, 2.5, Number.NaN]) {
      expect(isValidTaskRecurrence({ rule: hourly, strategy: "rolling", limit })).toBe(false);
    }
    expect(isValidTaskRecurrence({ rule: hourly, strategy: "fixed", limit: null })).toBe(false);
    expect(
      isValidTaskRecurrence({ rule: rule({ frequency: "daily" }), strategy: "rolling", limit: 3 })
    ).toBe(false);
  });
});
