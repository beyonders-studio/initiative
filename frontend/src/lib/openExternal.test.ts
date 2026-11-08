import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const platform = vi.hoisted(() => ({ name: "web" }));
const browserOpen = vi.hoisted(() => vi.fn(() => Promise.resolve()));

vi.mock("@capacitor/core", () => ({ Capacitor: { getPlatform: () => platform.name } }));
vi.mock("@capacitor/browser", () => ({ Browser: { open: browserOpen } }));

import { openExternal, reserveTab } from "./openExternal";

describe("openExternal", () => {
  let windowOpen: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    platform.name = "web";
    browserOpen.mockClear();
    windowOpen = vi.spyOn(window, "open").mockReturnValue(null);
  });
  afterEach(() => windowOpen.mockRestore());

  it("opens a new tab with no opener or referrer, and nothing for a blocked address", () => {
    openExternal("https://example.com/a");
    expect(windowOpen).toHaveBeenCalledWith(
      "https://example.com/a",
      "_blank",
      "noopener,noreferrer"
    );

    windowOpen.mockClear();
    const reserved = { close: vi.fn(), location: { href: "" } } as unknown as Window;
    openExternal("javascript:alert(1)", reserved);
    expect(windowOpen).not.toHaveBeenCalled();
    expect(reserved.close).toHaveBeenCalled();
  });

  it("points a reserved tab, opened with its opener cut", () => {
    const tab = { opener: {}, location: { href: "about:blank" } } as unknown as Window;
    windowOpen.mockReturnValue(tab);

    const reserved = reserveTab();
    expect(reserved?.opener).toBeNull();
    openExternal("https://portal.example.com/#handoff=x", reserved);
    expect(tab.location.href).toBe("https://portal.example.com/#handoff=x");
  });

  it("opens the browser sheet on a phone, which reserves no tab", () => {
    platform.name = "android";
    expect(reserveTab()).toBeNull();
    openExternal("https://example.com/a");
    expect(browserOpen).toHaveBeenCalledWith({ url: "https://example.com/a" });
    expect(windowOpen).not.toHaveBeenCalled();
  });
});
