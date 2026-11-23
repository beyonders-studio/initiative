import { describe, expect, it } from "vitest";

import { detectDesktopOs, detectPlatform } from "./platform";

const nav = (userAgent: string, maxTouchPoints = 0) => ({ userAgent, maxTouchPoints });

describe("detectPlatform", () => {
  const ipadOs = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15";
  it.each([
    ["Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/125", 0, "android"],
    ["Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)", 0, "ios"],
    ["Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)", 0, "ios"],
    // A touch-screen Mac is an iPad, which is what it is.
    [ipadOs, 5, "ios"],
    [ipadOs, 0, "desktop"],
    ["Mozilla/5.0 (X11; Linux x86_64) Firefox/126.0", 0, "desktop"],
    ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125", 0, "desktop"],
  ])("reads %s with %i touch points as %s", (userAgent, touchPoints, expected) => {
    expect(detectPlatform(nav(userAgent, touchPoints))).toBe(expected);
  });
});

describe("detectDesktopOs", () => {
  it("names the computer the download button is for", () => {
    expect(detectDesktopOs({ userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" })).toBe(
      "windows"
    );
    expect(detectDesktopOs({ userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5)" })).toBe(
      "mac"
    );
    expect(detectDesktopOs({ userAgent: "Mozilla/5.0 (X11; Linux x86_64)" })).toBe("linux");
    expect(detectDesktopOs({ userAgent: "Mozilla/5.0" })).toBeNull();
  });
});
