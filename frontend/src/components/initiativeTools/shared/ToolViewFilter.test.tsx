/**
 * The one view filter every tool list wears. Its whole job is to be visible:
 * every view the tool has on screen with its total, so the reader can see that
 * templates and archived rows exist without opening anything. The Radix
 * default of clearing a single-select group on a second click would leave the
 * list with no view at all, so that is pinned down too.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolViewFilter } from "@/components/initiativeTools/shared/ToolViewFilter";

const options = () =>
  screen.getAllByRole("radio").map((option) => option.getAttribute("aria-label"));

describe("ToolViewFilter", () => {
  it("shows every view the tool has, with its total", () => {
    render(
      <ToolViewFilter
        tool={Tool.project}
        value="active"
        onChange={vi.fn()}
        counts={{ active: 8, templates: 3, archived: 5 }}
      />
    );

    expect(options()).toEqual(["Active", "Templates", "Archived"]);
    for (const [label, count] of [
      ["Active", "8"],
      ["Templates", "3"],
      ["Archived", "5"],
    ]) {
      expect(screen.getByRole("radio", { name: label })).toHaveTextContent(count);
    }
    expect(screen.getByRole("radio", { name: "Active" })).toHaveAttribute("data-state", "on");
  });

  it("offers no templates for a tool without them", () => {
    render(<ToolViewFilter tool={Tool.counter_group} value="active" onChange={vi.fn()} />);
    expect(options()).toEqual(["Active", "Archived"]);
  });

  it("renders without totals before they load", () => {
    render(<ToolViewFilter tool={Tool.file} value="templates" onChange={vi.fn()} />);
    const templates = screen.getByRole("radio", { name: "Templates" });
    expect(templates).toHaveAttribute("data-state", "on");
    expect(templates).toHaveTextContent(/^Templates$/);
  });

  it("offers both archive states at once to an export", () => {
    render(<ToolViewFilter tool={Tool.project} includeAll value="all" onChange={vi.fn()} />);
    expect(options()).toEqual(["All", "Active", "Archived"]);
  });

  it("reports the view the reader picked", async () => {
    const onChange = vi.fn();
    render(<ToolViewFilter tool={Tool.project} value="active" onChange={onChange} />);

    await userEvent.click(screen.getByRole("radio", { name: "Archived" }));
    expect(onChange).toHaveBeenCalledWith("archived");
  });

  it("keeps the current view when it is clicked again", async () => {
    const onChange = vi.fn();
    render(<ToolViewFilter tool={Tool.project} value="active" onChange={onChange} />);

    await userEvent.click(screen.getByRole("radio", { name: "Active" }));
    expect(onChange).not.toHaveBeenCalled();
  });
});
