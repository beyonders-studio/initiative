import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TaskPriorityOption } from "./TaskPriorityOption";

describe("TaskPriorityOption", () => {
  it("draws a dot in the priority's colour beside its label", () => {
    render(<TaskPriorityOption priority="high" label="High" />);

    const label = screen.getByText("High");
    const dot = label.previousElementSibling;
    expect(dot).toHaveAttribute("aria-hidden", "true");
    expect(dot).toHaveClass("bg-warning");
  });
});
