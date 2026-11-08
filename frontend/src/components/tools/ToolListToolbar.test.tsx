import fs from "node:fs";
import path from "node:path";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ToolListToolbar } from "./ToolListToolbar";

describe("ToolListToolbar heading", () => {
  it("keeps the heading on the control row, in a container that still wraps", () => {
    render(
      <ToolListToolbar
        heading={<h2>Project tasks</h2>}
        filters={{ open: false, onOpenChange: () => {}, activeCount: 0 }}
      />
    );

    const heading = screen.getByRole("heading", { name: "Project tasks" });
    const filterButton = screen.getByRole("button", { name: /filters/i });

    // Same flex row: the heading's wrapper and the controls' group are siblings
    // inside the toolbar, rather than the heading sitting on a line above it.
    const row = heading.parentElement?.parentElement;
    expect(row).toBe(filterButton.parentElement?.parentElement);
    // Wrapping is what lets the controls drop to a second line when the row
    // runs out of room instead of squeezing against the heading.
    expect(row).toHaveClass("flex-wrap");
  });

  it("renders no heading container when the list has no heading", () => {
    render(<ToolListToolbar filters={{ open: false, onOpenChange: () => {} }} />);

    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
  });
});

/**
 * A page with filters has something to open them with.
 *
 * `ToolFilterPanel` holds the fields; the button that reveals it lives in the
 * toolbar and only appears if the page passes `filters`. Forget that and the
 * filters are still there, still working, and unreachable — which is exactly
 * how the posts board shipped its unread filter with no way to reach it.
 */
describe("every filtered list can open its filters", () => {
  const SRC = path.resolve(__dirname, "../../..");

  const walk = (dir: string, found: string[] = []): string[] => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full, found);
      else if (entry.name.endsWith(".tsx") && !entry.name.includes(".test.")) found.push(full);
    }
    return found;
  };

  it("passes `filters` to the toolbar wherever a filter bar is rendered", () => {
    const offenders: string[] = [];
    for (const file of walk(SRC)) {
      const source = fs.readFileSync(file, "utf-8");
      // The page that RENDERS a filter bar, not the bar's own definition.
      if (!/<\w+FilterBar[\s/>]/.test(source)) continue;
      if (!source.includes("filters={")) offenders.push(path.relative(SRC, file));
    }

    expect(
      offenders,
      `these render a filter bar with no way to open it — pass \`filters\` to ToolListToolbar: ${offenders.join(", ")}`
    ).toEqual([]);
  });
});
