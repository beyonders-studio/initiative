import { describe, expect, it } from "vitest";

import { isKnownTimezone } from "./timezones";

describe("isKnownTimezone", () => {
  it("knows a real zone, listed or not, and not a made-up one", () => {
    expect(isKnownTimezone("UTC")).toBe(true);
    expect(isKnownTimezone("Africa/Johannesburg")).toBe(true);
    expect(isKnownTimezone("Mars/Olympus")).toBe(false);
  });
});
