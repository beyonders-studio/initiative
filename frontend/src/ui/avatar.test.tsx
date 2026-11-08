import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Avatar, AvatarFallback } from "./avatar";

// Radix's <AvatarFallback> renders a <span> containing the supplied
// children once the image fails (or no image is provided). The tests
// stick to fallback-only avatars so we can assert on the fallback
// element directly via its text content.
//
// JSDOM normalizes ``backgroundColor`` HSL values to RGB on read, so the
// tests compare against the RGB equivalent rather than the HSL literal
// that ``getUserColorHsl`` returns — we only care that the color ended up
// on the element and that it's stable for the same user id.

describe("AvatarFallback", () => {
  it("uses the default bg-muted class when no userId is provided", () => {
    render(
      <Avatar>
        <AvatarFallback>AB</AvatarFallback>
      </Avatar>
    );
    const fallback = screen.getByText("AB");
    expect(fallback.className).toMatch(/bg-muted/);
    expect(fallback.style.backgroundColor).toBe("");
    expect(fallback.style.color).toBe("");
  });

  it("applies getUserColorStyle when userId is set", () => {
    render(
      <Avatar>
        <AvatarFallback userId={42}>CD</AvatarFallback>
      </Avatar>
    );
    const fallback = screen.getByText("CD");
    // bg-muted should NOT be applied when a user color is active.
    expect(fallback.className).not.toMatch(/bg-muted/);
    // A non-empty background color is set inline.
    expect(fallback.style.backgroundColor).not.toBe("");
    // Foreground is the shared dark slate-900 constant.
    expect(fallback.style.color.toLowerCase()).toBe("rgb(15, 23, 42)");
  });

  it("produces the same color across renders for a stable userId", () => {
    const userId = 7;
    const first = render(
      <Avatar>
        <AvatarFallback userId={userId}>E</AvatarFallback>
      </Avatar>
    );
    const firstBg = screen.getByText("E").style.backgroundColor;
    first.unmount();

    render(
      <Avatar>
        <AvatarFallback userId={userId}>E</AvatarFallback>
      </Avatar>
    );
    const secondBg = screen.getByText("E").style.backgroundColor;

    expect(firstBg).not.toBe("");
    expect(firstBg).toBe(secondBg);
  });

  it("yields distinct colors for different user ids", () => {
    const a = render(
      <Avatar>
        <AvatarFallback userId={1}>A</AvatarFallback>
      </Avatar>
    );
    const bgA = screen.getByText("A").style.backgroundColor;
    a.unmount();

    render(
      <Avatar>
        <AvatarFallback userId={2}>B</AvatarFallback>
      </Avatar>
    );
    const bgB = screen.getByText("B").style.backgroundColor;

    // The djb2 + Knuth spread should land ids 1 and 2 in different hue
    // buckets. This also guards against a regression where we accidentally
    // wire in a constant color.
    expect(bgA).not.toBe(bgB);
  });

  it("leaves the default behavior alone when userId is 0 or negative", () => {
    // The guard is ``userId > 0`` — users created by the seed flow start at 1,
    // so a zero/negative id signals a non-user fallback (or a sentinel).
    render(
      <Avatar>
        <AvatarFallback userId={0}>F</AvatarFallback>
      </Avatar>
    );
    const fallback = screen.getByText("F");
    expect(fallback.className).toMatch(/bg-muted/);
    expect(fallback.style.backgroundColor).toBe("");
  });
});
