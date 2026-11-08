import { act, render, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CLOCK_TICK_MS } from "@/ui/lib/relativeTimeClock";

import { useRelativeTime } from "./useRelativeTime";

/**
 * Anchor "now" so the relative labels are deterministic. `toFake: ["Date",
 * "setInterval", ...]` lets the shared clock's interval advance under
 * `vi.advanceTimersByTime` while `Date.now()` moves in lockstep.
 */
const NOW = new Date("2026-07-22T12:00:00.000Z");

beforeEach(() => {
  vi.useFakeTimers({ now: NOW });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useRelativeTime", () => {
  it("formats a past timestamp with a suffix", () => {
    const twoMinutesAgo = new Date(NOW.getTime() - 2 * 60_000).toISOString();
    const { result } = renderHook(() => useRelativeTime(twoMinutesAgo));
    expect(result.current).toBe("2 minutes ago");
  });

  it("returns null for nullish or unparseable input", () => {
    const { result: nullResult } = renderHook(() => useRelativeTime(null));
    expect(nullResult.current).toBeNull();

    const { result: badResult } = renderHook(() => useRelativeTime("not-a-date"));
    expect(badResult.current).toBeNull();
  });

  it("advances in place as the shared clock ticks", () => {
    const start = new Date(NOW.getTime() - 60_000).toISOString();
    const { result } = renderHook(() => useRelativeTime(start));
    expect(result.current).toBe("1 minute ago");

    // Advance real time by two ticks worth so the label crosses into the next
    // minute bucket, then let the clock's interval fire.
    act(() => {
      vi.advanceTimersByTime(2 * CLOCK_TICK_MS);
    });
    expect(result.current).toBe("2 minutes ago");
  });

  it("only re-renders when the displayed string changes", () => {
    // A timestamp years in the past never changes label, so ticking the clock
    // must not re-render the consumer.
    const longAgo = new Date(NOW.getTime() - 3 * 365 * 24 * 60 * 60_000).toISOString();
    let renders = 0;
    const Probe = () => {
      renders += 1;
      return <span>{useRelativeTime(longAgo)}</span>;
    };
    render(<Probe />);
    const initialRenders = renders;

    act(() => {
      vi.advanceTimersByTime(10 * CLOCK_TICK_MS);
    });
    expect(renders).toBe(initialRenders);
  });
});
