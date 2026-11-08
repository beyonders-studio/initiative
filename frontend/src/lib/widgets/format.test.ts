import { describe, expect, it } from "vitest";

import { dateTimeFormat } from "@/ui/lib/intl";

import { formatAxisValue, formatTimeBucket, formatValue } from "./format";

describe("calendar dates and instants", () => {
  const at = Date.parse("2026-08-03T00:00:00Z");

  it("keeps a SQL DATE on its calendar day in full and compact labels", () => {
    expect(formatValue(at, "date-only", { locale: "en-US" })).toBe("Aug 3, 2026");
    expect(formatAxisValue(at, "date-only", { locale: "en-US" })).toBe("Aug 3");
  });

  it("still formats true timestamps in the viewer's timezone", () => {
    expect(formatValue(at, "date", { locale: "en-US" })).toBe(
      dateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" }).format(at)
    );
    expect(formatAxisValue(at, "date", { locale: "en-US" })).toBe(
      dateTimeFormat("en-US", { month: "short", day: "numeric" }).format(at)
    );
  });
});

describe("formatTimeBucket", () => {
  const at = (iso: string) => Date.parse(`${iso}T00:00:00Z`);

  it("labels each grain the way a reader names it", () => {
    expect(formatTimeBucket(at("2026-03-05"), "day", { locale: "en-US" })).toBe("Mar 5");
    expect(formatTimeBucket(at("2026-03-02"), "week", { locale: "en-US" })).toBe("Mar 2");
    expect(formatTimeBucket(at("2026-03-01"), "month", { locale: "en-US" })).toBe("Mar 2026");
    expect(formatTimeBucket(at("2026-04-01"), "quarter")).toBe("Q2 2026");
    expect(formatTimeBucket(at("2026-01-01"), "year")).toBe("2026");
  });

  it("reads the moment in UTC, so midnight is never the day before", () => {
    expect(formatTimeBucket(at("2026-01-01"), "month", { locale: "en-US" })).toBe("Jan 2026");
  });

  it("passes a label that is not a moment through", () => {
    expect(formatTimeBucket("Other", "month")).toBe("Other");
  });
});
