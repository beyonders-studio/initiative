/**
 * A funnel's bars stay inside the panel.
 *
 * A funnel narrows by convention, not by construction: a statement grouping by
 * status returns its rows in whatever order it likes, and "stage one" is then
 * not the widest. Scaling every bar against the first stage drew the larger
 * ones past the end of the tile — so what the bars are measured against, and
 * that none of them exceeds the box, is what these pin.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FunnelNode } from "./FunnelNode";

const funnel = (values: number[]) => ({
  kind: "funnel" as const,
  stages: values.map((value, index) => ({ label: `s${index}`, value })),
});

/** The drawn width of each bar, in order. */
const widths = (container: HTMLElement): string[] =>
  Array.from(container.querySelectorAll<HTMLElement>("[style*='width']")).map(
    (bar) => bar.style.width
  );

describe("a funnel that does not narrow", () => {
  it("measures against its widest stage, not its first", () => {
    // Ordered by a status enum rather than by size: the biggest is third.
    const { container } = render(<FunnelNode node={funnel([257, 254, 273, 262])} />);
    const drawn = widths(container);
    expect(drawn[2]).toBe("100%");
    // And everything else is a share of it rather than of the first stage.
    expect(drawn[0]).toBe(`${(257 / 273) * 100}%`);
  });

  it("draws no bar past the end of the panel", () => {
    const { container } = render(<FunnelNode node={funnel([10, 400, 25])} />);
    for (const width of widths(container)) {
      expect(Number.parseFloat(width)).toBeLessThanOrEqual(100);
    }
  });

  it("still shows the smallest stage as something", () => {
    const { container } = render(<FunnelNode node={funnel([1000, 1])} />);
    expect(Number.parseFloat(widths(container)[1])).toBeGreaterThan(0);
  });

  it("draws a full bar where every stage is nothing", () => {
    const { container } = render(<FunnelNode node={funnel([0, 0])} />);
    expect(widths(container)).toEqual(["100%", "100%"]);
  });

  it("names every stage", () => {
    render(<FunnelNode node={funnel([3, 2])} />);
    expect(screen.getByText("s0")).toBeInTheDocument();
    expect(screen.getByText("s1")).toBeInTheDocument();
  });
});
