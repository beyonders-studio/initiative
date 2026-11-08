import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CardGridSkeleton, PageSkeleton, SkeletonRegion, TableSkeleton } from "./page-skeletons";

describe("SkeletonRegion", () => {
  it("is a busy status region announcing the shared loading label", () => {
    render(
      <SkeletonRegion>
        <div data-testid="child" />
      </SkeletonRegion>
    );
    const region = screen.getByRole("status");
    expect(region).toHaveAttribute("aria-busy", "true");
    expect(region).toHaveTextContent("Loading…");
    const child = within(region).getByTestId("child");
    expect(child).toBeInTheDocument();
    expect(child.parentElement).toHaveAttribute("aria-hidden", "true");
  });

  it("keeps a placeholder table out of the accessibility tree", () => {
    render(
      <SkeletonRegion>
        <TableSkeleton rows={2} columns={2} />
      </SkeletonRegion>
    );
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("announces a page's own label when given one", () => {
    render(
      <SkeletonRegion label="Loading initiative…">
        <div />
      </SkeletonRegion>
    );
    expect(screen.getByRole("status")).toHaveTextContent("Loading initiative…");
  });
});

describe("TableSkeleton", () => {
  it("draws a header plus the requested rows and columns", () => {
    render(<TableSkeleton rows={4} columns={3} />);
    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(5);
    expect(within(rows[0]).getAllByRole("columnheader")).toHaveLength(3);
    expect(within(rows[1]).getAllByRole("cell")).toHaveLength(3);
  });
});

describe("CardGridSkeleton", () => {
  it("draws one card per count", () => {
    const { container } = render(<CardGridSkeleton count={5} />);
    expect(container.querySelectorAll(".rounded-2xl")).toHaveLength(5);
  });
});

describe("page skeletons", () => {
  it("wrap their layout in a labelled status region", () => {
    render(<PageSkeleton label="Loading the page…" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading the page…");
  });

  it("fall back to the shared label", () => {
    render(<PageSkeleton />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading…");
  });
});
