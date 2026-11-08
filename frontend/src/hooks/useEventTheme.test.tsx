import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { removeItem } from "@/lib/storage";

import { EventThemeProvider, useEventTheme } from "./useEventTheme";

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <EventThemeProvider>{children}</EventThemeProvider>
);

const onDate = (iso: string) => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(iso));
};

afterEach(() => {
  vi.useRealTimers();
  delete document.documentElement.dataset.eventTheme;
  removeItem("initiative-event-themes");
});

describe("useEventTheme", () => {
  it.each([
    ["2026-06-15T12:00:00", "pride"],
    ["2026-12-01T12:00:00", "christmas"],
    ["2026-12-25T12:00:00", "christmas"],
    ["2026-12-26T12:00:00", "newYear"],
    ["2027-01-01T12:00:00", "newYear"],
    ["2027-01-02T12:00:00", null],
    ["2026-03-15T12:00:00", null],
  ])("on %s shows %s", (iso, expected) => {
    onDate(iso);

    const { result } = renderHook(() => useEventTheme(), { wrapper });

    expect(result.current.active?.id ?? null).toBe(expected);
    expect(document.documentElement.dataset.eventTheme).toBe(expected ?? undefined);
  });

  it("turning it off hides the running event, and stays off across mounts", () => {
    onDate("2026-06-15T12:00:00");
    const { result, unmount } = renderHook(() => useEventTheme(), { wrapper });

    act(() => result.current.setAllowed(false));
    expect(result.current.active).toBeNull();
    expect(document.documentElement.dataset.eventTheme).toBeUndefined();
    unmount();

    const { result: remounted } = renderHook(() => useEventTheme(), { wrapper });
    expect(remounted.current.allowed).toBe(false);
    expect(remounted.current.active).toBeNull();
  });

  it("falls back to no event without a provider", () => {
    const { result } = renderHook(() => useEventTheme());
    expect(result.current.active).toBeNull();
    expect(() => result.current.setAllowed(false)).not.toThrow();
  });
});
