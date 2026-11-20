import { describe, expect, it, vi } from "vitest";

import { reconnectDelay } from "./reconnectBackoff";

describe("reconnectDelay", () => {
  it("spreads an attempt over a window that doubles with each attempt up to the cap", () => {
    vi.spyOn(Math, "random").mockReturnValue(0);
    expect(reconnectDelay(3, 1000, 30_000)).toBe(0);

    vi.spyOn(Math, "random").mockReturnValue(0.999);
    expect(reconnectDelay(0, 1000, 30_000)).toBeCloseTo(999);
    vi.spyOn(Math, "random").mockReturnValue(0.5);
    expect(reconnectDelay(0, 1000, 30_000)).toBe(500);
    expect(reconnectDelay(2, 1000, 30_000)).toBe(2000);
    expect(reconnectDelay(10, 1000, 30_000)).toBe(15_000);
  });
});
