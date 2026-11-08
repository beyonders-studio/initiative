/**
 * What a Gantt has to get right in the DOM: the rows a fold hides, the marker
 * for the day being read against, and the fact that a percentage is a rendering
 * of the scene's number rather than something invented here.
 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import type { TimelineLane, TimelineNode as TimelineNodeSpec } from "@/lib/widgets/sceneSpec";

import { TimelineNode } from "./TimelineNode";

const at = (year: number, month: number, day: number): number =>
  new Date(year, month, day).getTime();

const AUGUST = at(2026, 7, 1);

const project = (label: string, done: number, total: number): TimelineLane => ({
  label,
  caption: `${done}/${total}`,
  collapsed: true,
  spans: [
    {
      kind: "summary",
      label,
      start: AUGUST,
      end: at(2026, 7, 28),
      progress: done / total,
    },
  ],
  children: [
    { label: `${label} task one`, spans: [{ start: AUGUST, end: at(2026, 7, 10) }] },
    { label: `${label} task two`, spans: [{ start: at(2026, 7, 12), end: at(2026, 7, 20) }] },
  ],
});

const node = (extra: Partial<TimelineNodeSpec> = {}): TimelineNodeSpec => ({
  kind: "timeline",
  scale: "week",
  lanes: [project("Apollo", 1, 4)],
  ...extra,
});

const rowNames = (): string[] =>
  screen.getAllByRole("row").map((row) => within(row).getByRole("rowheader").textContent ?? "");

describe("TimelineNode", () => {
  it("hides a folded lane's work until it is opened", async () => {
    renderWithProviders(<TimelineNode node={node()} />);

    expect(screen.queryByText("Apollo task one")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /expand apollo/i }));
    expect(screen.getByText("Apollo task one")).toBeInTheDocument();
    expect(screen.getByText("Apollo task two")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /collapse apollo/i }));
    expect(screen.queryByText("Apollo task one")).not.toBeInTheDocument();
  });

  it("states the hierarchy on the rows, not just in the indent", async () => {
    renderWithProviders(<TimelineNode node={node()} />);

    const group = screen.getByRole("row");
    expect(group).toHaveAttribute("aria-expanded", "false");
    expect(group).toHaveAttribute("aria-level", "1");

    await userEvent.click(screen.getByRole("button", { name: /expand apollo/i }));
    expect(screen.getByRole("row", { expanded: true })).toBeInTheDocument();
    const rows = screen.getAllByRole("row");
    expect(rows[1]).toHaveAttribute("aria-level", "2");
    // A leaf is not announced as collapsible.
    expect(rows[1]).not.toHaveAttribute("aria-expanded");
  });

  it("marks the day the scene was drawn against, and only when it is in view", () => {
    const { rerender } = renderWithProviders(
      <TimelineNode node={node({ now: at(2026, 7, 14) })} />
    );
    expect(screen.getByText("Today")).toBeInTheDocument();

    // A schedule that finished last year gets no marker rather than one pinned
    // to an edge it does not sit on.
    rerender(<TimelineNode node={node({ now: at(2030, 0, 1) })} />);
    expect(screen.queryByText("Today")).not.toBeInTheDocument();
  });

  it("walks the rows and folds them from the keyboard", async () => {
    renderWithProviders(<TimelineNode node={node()} />);

    // One row in the tab order; the arrows move it from there.
    await userEvent.tab();
    expect(screen.getAllByRole("row")[0]).toHaveFocus();

    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getAllByRole("row")[0]).toHaveAttribute("aria-expanded", "true");

    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getAllByRole("row")[1]).toHaveFocus();

    // From a leaf, left climbs to the group it belongs to rather than doing
    // nothing.
    await userEvent.keyboard("{ArrowLeft}");
    expect(screen.getAllByRole("row")[0]).toHaveFocus();

    await userEvent.keyboard("{ArrowLeft}");
    expect(screen.getAllByRole("row")[0]).toHaveAttribute("aria-expanded", "false");
  });

  it("reads a summary bar's completion off the scene", () => {
    renderWithProviders(<TimelineNode node={node({ lanes: [project("Apollo", 3, 4)] })} />);
    expect(screen.getByText("75%")).toBeInTheDocument();
    expect(screen.getByText("3/4")).toBeInTheDocument();
  });

  it("places marks as a share of the window", () => {
    // An explicit window, so the assertion is about the projection rather than
    // about where fitting happened to snap the edges.
    const { container } = renderWithProviders(
      <TimelineNode
        node={{
          kind: "timeline",
          start: 0,
          end: 1000,
          now: 500,
          lanes: [{ label: "Quarter through", spans: [{ start: 250, end: 500 }] }],
        }}
      />
    );

    const bar = container.querySelector("td > div");
    expect(bar).toHaveStyle({ left: "25%", width: "25%" });
    // The marker's line and its chip are both on the halfway instant, so they
    // cannot drift apart.
    expect(container.querySelectorAll('[style*="left: 50%"]')).toHaveLength(2);
  });

  it("keeps a lane with no children as an ordinary row", () => {
    renderWithProviders(
      <TimelineNode
        node={node({
          lanes: [{ label: "Chase the vendor", spans: [{ start: AUGUST, end: at(2026, 7, 6) }] }],
        })}
      />
    );
    expect(rowNames()).toEqual(["Chase the vendor"]);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
