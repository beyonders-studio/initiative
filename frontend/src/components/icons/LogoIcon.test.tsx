import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EventThemeProvider } from "@/hooks/useEventTheme";
import { removeItem } from "@/lib/storage";

import { LogoIcon } from "./LogoIcon";

afterEach(() => {
  vi.useRealTimers();
  delete document.documentElement.dataset.eventTheme;
  // A stale "off" would hide the event these tests fake, so clear it rather
  // than rely on the global setup cleanup.
  removeItem("initiative-event-themes");
});

describe("LogoIcon", () => {
  it("uses the theme primary color when no event runs", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-03-15T12:00:00Z")); // not June

    const { container } = render(
      <EventThemeProvider>
        <LogoIcon />
      </EventThemeProvider>
    );

    expect(container.querySelector("linearGradient")).toBeNull();
    expect(container.querySelector("path")?.getAttribute("fill")).toBe("currentColor");
    expect(container.querySelector("svg")?.classList.contains("event-logo")).toBe(false);
  });

  it("paints the mark with a rainbow gradient during Pride", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-06-15T12:00:00Z")); // June: Pride

    const { container } = render(
      <EventThemeProvider>
        <LogoIcon />
      </EventThemeProvider>
    );

    const gradient = container.querySelector("linearGradient");
    expect(gradient).not.toBeNull();
    // All six Pride flag bands are present.
    expect(gradient?.querySelectorAll("stop")).toHaveLength(6);

    const svg = container.querySelector("svg");
    expect(svg?.classList.contains("event-logo")).toBe(true);

    // Every painted shape references the gradient instead of currentColor.
    const fills = Array.from(container.querySelectorAll("path, ellipse")).map((el) =>
      el.getAttribute("fill")
    );
    expect(fills.length).toBeGreaterThan(0);
    for (const fill of fills) {
      expect(fill).toMatch(/^url\(#/);
    }
  });

  it.each([
    ["2026-12-28T12:00:00", "2027"],
    ["2027-01-01T12:00:00", "2027"],
  ])("on %s the New Year banner reads %s", (iso, year) => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(iso));

    const { container } = render(
      <EventThemeProvider>
        <LogoIcon />
      </EventThemeProvider>
    );

    expect(container.querySelector("text")?.textContent).toBe(year);
  });
});
