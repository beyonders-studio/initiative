import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Progress } from "./progress";

describe("Progress", () => {
  it.each(["bar", "ring"] as const)("draws a %s that reads as a percent", (variant) => {
    render(<Progress variant={variant} value={45} aria-label="Done" />);
    const bar = screen.getByRole("progressbar", { name: "Done" });
    expect(bar).toHaveAttribute("aria-valuenow", "45");
    expect(bar).toHaveAttribute("aria-valuetext", "45%");
  });

  it("shows the percent inside a ring", () => {
    render(<Progress variant="ring" value={7} max={20} />);
    expect(screen.getByText("35%")).toBeInTheDocument();
  });
});
