import { describe, expect, it } from "vitest";

import { detectDesktopOs, detectPlatform } from "./platform";

const nav = (userAgent: string, maxTouchPoints = 0) => ({ userAgent, maxTouchPoints });

describe("detectPlatform", () => {
  it("reads Android off the user agent", () => {
    expect(
      detectPlatform(nav("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/125"))
    ).toBe("android");
  });

  it("reads iPhone and iPad off the user agent", () => {
    expect(detectPlatform(nav("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"))).toBe(
      "ios"
    );
    expect(detectPlatform(nav("Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)"))).toBe("ios");
  });

  it("treats a touch-screen Mac as an iPad, which is what it is", () => {
    const ipadOs = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15";
    expect(detectPlatform(nav(ipadOs, 5))).toBe("ios");
    expect(detectPlatform(nav(ipadOs, 0))).toBe("desktop");
  });

  it("falls back to desktop for everything else", () => {
    expect(detectPlatform(nav("Mozilla/5.0 (X11; Linux x86_64) Firefox/126.0"))).toBe("desktop");
    expect(detectPlatform(nav("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125"))).toBe(
      "desktop"
    );
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
