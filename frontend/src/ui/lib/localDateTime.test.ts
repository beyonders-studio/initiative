import { describe, expect, it, vi } from "vitest";

import { parseLocalCalendarDate, resolveLocalDateTime } from "./localDateTime";

describe("strict local calendar input", () => {
  it.each(["2026-02-30", "2025-02-29", "2026-04-31", "2026-13-01"])("rejects %s", (value) => {
    expect(parseLocalCalendarDate(value)).toBeNull();
  });

  it("accepts leap day and literal early years", () => {
    expect(parseLocalCalendarDate("2024-02-29")?.getDate()).toBe(29);
    expect(parseLocalCalendarDate("0099-01-01")?.getFullYear()).toBe(99);
  });

  it("refuses skipped and ambiguous Amsterdam times, preserving an unchanged fold instant", () => {
    vi.stubEnv("TZ", "Europe/Amsterdam");
    expect(resolveLocalDateTime("2026-03-29", "02:30")).toBeNull();
    expect(resolveLocalDateTime("2026-10-25", "02:30")).toBeNull();
    expect(
      resolveLocalDateTime("2026-10-25", "02:30", "2026-10-25T01:30:27.123Z")?.toISOString()
    ).toBe("2026-10-25T01:30:27.123Z");
    expect(resolveLocalDateTime("2026-03-29", "03:30")?.toISOString()).toBe(
      "2026-03-29T01:30:00.000Z"
    );
  });
});
