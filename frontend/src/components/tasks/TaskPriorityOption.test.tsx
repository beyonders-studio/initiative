import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TaskPriorityOption } from "@/components/tasks/TaskPriorityOption";
import { priorityDotClass, priorityVariant } from "@/components/tools/projects/projectTasksConfig";
import { PRIORITY_ORDER } from "@/lib/sorting";

describe("TaskPriorityOption", () => {
  it("draws a dot in the priority's colour beside its label", () => {
    render(<TaskPriorityOption priority="high" label="High" />);

    const label = screen.getByText("High");
    const dot = label.previousElementSibling;
    expect(dot).toHaveAttribute("aria-hidden", "true");
    expect(dot).toHaveClass("bg-warning");
  });

  it("gives every priority its own dot colour", () => {
    const colours = PRIORITY_ORDER.map((priority) => priorityDotClass[priority]);

    expect(new Set(colours).size).toBe(PRIORITY_ORDER.length);
  });

  it("shows high priority in the warning colour", () => {
    expect(priorityVariant.high).toBe("warning");
  });
});
