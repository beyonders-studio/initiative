import { beforeEach, describe, expect, it, vi } from "vitest";

import { normalizeColor, themeColor, withAlpha } from "@/lib/cssColor";

describe("normalizeColor", () => {
  it("keeps a colour a canvas already understands, and says nothing about one it cannot read", () => {
    expect(normalizeColor("#0ea5e9")).toBe("#0ea5e9");
    // Nonsense never comes back as a colour — a wrong colour is harder to
    // spot than none.
    expect(normalizeColor("not-a-colour")).toBeNull();
    expect(normalizeColor("   ")).toBeNull();
  });
});

describe("themeColor", () => {
  it("falls back rather than handing back an empty string", () => {
    // A variable the theme does not define resolves to "", which a renderer
    // would take as "draw nothing".
    expect(themeColor("--nothing-defines-this", "#123456")).toBe("#123456");
  });
});

describe("withAlpha", () => {
  it("says a hex or rgb colour more quietly, and leaves one it cannot read alone", () => {
    expect(withAlpha("#0ea5e9", 0.4)).toBe("#0ea5e966");
    expect(withAlpha("#fff", 0.4)).toBe("#ffffff66");
    expect(withAlpha("rgb(14, 165, 233)", 0.5)).toContain("rgba(");
    expect(withAlpha("not-a-colour", 0.5)).toBe("not-a-colour");
  });
});

/**
 * The conversion that matters, with a canvas standing in for a browser's.
 *
 * jsdom has no canvas at all, and the case worth proving is the one that was
 * broken: a theme colour in `oklch()` has to come back as something sigma reads,
 * because a browser that understands `oklch()` hands `fillStyle` straight back
 * unchanged and the renderer then draws it black.
 */
describe("converting a colour the renderer cannot read", () => {
  const painted = (rgba: [number, number, number, number]) => ({
    clearRect: vi.fn(),
    fillRect: vi.fn(),
    fillStyle: "",
    getImageData: () => ({ data: Uint8ClampedArray.from(rgba) }),
  });

  beforeEach(() => {
    vi.resetModules();
  });

  const withCanvas = async (rgba: [number, number, number, number]) => {
    const context = painted(rgba);
    vi.spyOn(document, "createElement").mockReturnValueOnce({
      width: 0,
      height: 0,
      getContext: () => context,
    } as unknown as HTMLCanvasElement);
    return await import("@/lib/cssColor");
  };

  it("turns an oklch colour into hex", async () => {
    const { normalizeColor } = await withCanvas([14, 165, 233, 255]);
    expect(normalizeColor("oklch(0.6 0.118 184.704)")).toBe("#0ea5e9");
  });

  it("keeps a colour that is not fully opaque as rgba", async () => {
    const { normalizeColor } = await withCanvas([255, 255, 255, 26]);
    expect(normalizeColor("oklch(1 0 0 / 10%)")).toMatch(/^rgba\(255, 255, 255, 0\.10/);
  });

  it("reads a colour the browser painted nothing for as no colour", async () => {
    const { normalizeColor } = await withCanvas([0, 0, 0, 0]);
    expect(normalizeColor("oklch(nonsense)")).toBeNull();
  });
});
