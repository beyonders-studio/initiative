/**
 * Canvas behaviour that only shows up in a render.
 *
 * The load-bearing one is the read-only case: arranging a dashboard is
 * authoring, so a viewer without DAC write must get a static grid and no
 * authoring affordances at all — not a disabled-looking one that still emits
 * layout changes.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// jsdom measures every element at zero, which would put the canvas on its
// stacked breakpoint and make every assertion below pass for the wrong reason.
// A desktop width is what these tests are actually about.
const VIEWPORT_WIDTH = 1200;
vi.mock("react-grid-layout", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-grid-layout")>()),
  useContainerWidth: () => ({
    width: VIEWPORT_WIDTH,
    mounted: true,
    containerRef: { current: null },
    measureWidth: () => {},
  }),
}));

import { renderWithProviders } from "@/__tests__/helpers/render";
import type { WidgetCatalog } from "@/api/generated/initiativeAPI.schemas";
import {
  addWidget,
  applyLayout,
  type DashboardDefinition,
  EMPTY_DEFINITION,
  readConfig,
} from "@/lib/widgets/definition";

import { DashboardCanvas } from "./DashboardCanvas";

const catalog = {
  widgets: [
    {
      type: "stat",
      min_w: 2,
      min_h: 2,
      default_w: 3,
      default_h: 2,
      sources: ["counter"],
      options: [],
    },
  ],
  presets: [],
} as unknown as WidgetCatalog;

const withStat = (): DashboardDefinition => addWidget(EMPTY_DEFINITION, catalog, "stat", "counter");

const render = (
  definition: DashboardDefinition,
  canEdit: boolean,
  onLayoutChange = vi.fn(),
  isLoading = false
) => {
  const { container } = renderWithProviders(
    <DashboardCanvas
      definition={definition}
      config={readConfig({})}
      catalog={catalog}
      initiativeId={undefined}
      canEdit={canEdit}
      isLoading={isLoading}
      onLayoutChange={onLayoutChange}
    />
  );
  return Object.assign(onLayoutChange, { container });
};

/** The dot grid is a background on the canvas surface, so it is read off the
 *  style rather than found as an element. */
const surface = (container: HTMLElement) => container.querySelector("[style*='radial-gradient']");

describe("DashboardCanvas", () => {
  it("invites the author to add a widget when the canvas is empty", () => {
    render(EMPTY_DEFINITION, true);
    expect(screen.getByText("This dashboard has no widgets yet.")).toBeInTheDocument();
    expect(screen.getByText("Add a widget to start showing your data.")).toBeInTheDocument();
  });

  it("tells a viewer without write access who can fill it instead", () => {
    render(EMPTY_DEFINITION, false);
    expect(screen.getByText("Someone with edit access can add widgets to it.")).toBeInTheDocument();
  });

  it("offers no authoring affordances without write access", () => {
    render(withStat(), false);
    // The per-widget menu is the entry point to configure and remove; without
    // write there is nothing to open.
    expect(screen.queryByRole("button", { name: /options for/i })).toBeNull();
  });

  it("offers the widget menu with write access", () => {
    render(withStat(), true);
    expect(screen.getByRole("button", { name: /options for/i })).toBeInTheDocument();
  });

  it("never reports a layout change for a read-only canvas", () => {
    // A static canvas must never write the dashboard's row on someone else's
    // behalf, whatever the grid reports.
    const onLayoutChange = render(withStat(), false);
    expect(onLayoutChange).not.toHaveBeenCalled();
  });

  it("shows the wait inside the canvas, not in place of it", () => {
    // The page around the canvas is already correct while the row loads;
    // swapping the whole page for a spinner is what made an ordinary load look
    // like a reload.
    const onLayoutChange = render(withStat(), true, vi.fn(), true);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /options for/i })).toBeNull();
    expect(onLayoutChange).not.toHaveBeenCalled();
  });

  it("gives an author a resize handle", () => {
    const { container } = render(withStat(), true);
    expect(container.querySelector(".react-resizable-handle")).not.toBeNull();
    expect(container.querySelector(".react-resizable-hide")).toBeNull();
  });

  it("hides the resize handle from a viewer", () => {
    const { container } = render(withStat(), false);
    expect(container.querySelector(".react-resizable-hide")).not.toBeNull();
  });

  it("stops a resize at each widget's catalog size floor", () => {
    // A Gantt squeezed to two columns is unreadable, so a resize lands on the
    // floor rather than being refused. The grid enforces it live from each
    // item's minW/minH; this pins the value that gets saved.
    const shrunk = applyLayout(withStat(), catalog, [{ i: "w1", x: 0, y: 0, w: 1, h: 1 }]);
    expect(shrunk.widgets[0].grid).toMatchObject({ w: 2, h: 2 });
  });

  it("draws the grid for someone who can arrange it", () => {
    const { container } = render(withStat(), true);
    expect(surface(container)).not.toBeNull();
  });

  it("draws no grid for a viewer", () => {
    // Dots promise that things snap into place; without write access they don't.
    const { container } = render(withStat(), false);
    expect(surface(container)).toBeNull();
  });

  it("opening a dashboard does not write its layout", () => {
    // Pinned as an end-to-end guarantee rather than a test of one guard: today
    // the grid does not report a change on mount at this width, and the
    // definition comparison in the handler covers the widths where it does.
    // Either way, viewing a dashboard must never bump its updated_at — so if a
    // future grid release starts emitting here, this fails.
    const onLayoutChange = render(withStat(), true);
    expect(onLayoutChange).not.toHaveBeenCalled();
  });
});
