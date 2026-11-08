/**
 * Where a placed widget's data comes from.
 *
 * Two modes, and the difference is a boundary rather than a preference. A
 * widget on a real dashboard resolves its binding through the ordinary
 * RLS-gated hooks, scoped to that dashboard's initiative. A widget in the
 * marketplace preview draws the sample library instead: the listing is not
 * installed, so it has no initiative to read and must be given none — which is
 * what these pin, at the seam where it would regress.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import type { WidgetBinding, WidgetDataResult } from "@/hooks/useWidgetData";
import type { DefinitionWidget } from "@/lib/widgets/definition";
import { WidgetErrorCode } from "@/lib/widgets/errors";
import { emptyDataFor } from "@/lib/widgets/normalize";

const useWidgetData = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/useWidgetData", () => ({ useWidgetData }));
// The served catalog is a community-scoped fetch this bare render has no handler
// for; the shapes it would carry are mirrored in `shapes.ts` for exactly the
// case below — a preview of a listing nobody has installed.
vi.mock("@/hooks/useDashboards", () => ({ useWidgetCatalog: () => ({ data: undefined }) }));

import { DashboardWidget } from "./DashboardWidget";

const binding: WidgetBinding = { source: "query" };
const widget: DefinitionWidget = {
  id: "w1",
  type: "stat",
  grid: { x: 0, y: 0, w: 3, h: 2 },
  binding,
  // Column 0 of the author's own query. The sample's column 0 is a label.
  mapping: { value: [0] },
};
/** A binding that names what it reads, so the fetch has a target to resolve. */
const boundBinding: WidgetBinding = { source: "query", sql: "SELECT name, count FROM counters" };

const render = (sampleData: boolean) => {
  useWidgetData.mockReturnValue({
    data: emptyDataFor("query"),
    isLoading: false,
    isUnbound: true,
  });
  return renderWithProviders(
    <DashboardWidget
      widget={widget}
      binding={binding}
      initiativeId={7}
      dashboardId={11}
      canEdit={false}
      sampleData={sampleData}
    />
  );
};

describe("DashboardWidget", () => {
  it("resolves the binding against the dashboard's initiative", () => {
    // And says which widget is asking: a binding carrying a statement has the
    // stored one run, so the server needs to know whose.
    render(false);
    expect(useWidgetData).toHaveBeenCalledWith(binding, 7, 11, "w1");
  });

  it("reads no initiative and no dashboard at all in sample mode", () => {
    // The hook still runs — hooks are unconditional — but without an
    // initiative it fail-closes and issues no request. The dashboard goes the
    // same way: a plug-in source has nothing to address itself to, so a preview
    // cannot reach one either. This is what keeps an uninstalled listing's
    // preview from touching the community's data.
    render(true);
    expect(useWidgetData).toHaveBeenCalledWith(binding, undefined, undefined, "w1");
  });

  it("draws the sample library rather than the resolved binding", async () => {
    // The hook is returning an *unbound* envelope, which on a real dashboard
    // renders the "configure me" notice. In sample mode the tile draws the
    // sample instead, so a value off the sample rows proves where they came
    // from — and the author's mapping, which names their own query's columns,
    // is not applied to the sample's.
    const { container } = render(true);
    // The sample's four stages total a hundred tasks. Asserted on the tile's
    // text rather than one node, because the number and its label are laid out
    // separately and the point is only that the sample's rows got here.
    await vi.waitFor(() => expect(container.textContent).toContain("100"), { timeout: 8000 });
    expect(screen.queryByText(/choose what this widget shows/i)).toBeNull();
  });
});

/**
 * The three ways a widget can have nothing to draw.
 *
 * They used to be one notice, and they are three different messages to three
 * different people: an author who has not finished setting the widget up, a
 * reader whose access does not reach the data, and anyone at all when the
 * request simply failed. Collapsing them tells two of the three something
 * untrue.
 */
describe("a widget with nothing to draw", () => {
  const renderState = (result: Partial<WidgetDataResult>, widgetBinding = binding) => {
    useWidgetData.mockReturnValue({
      data: emptyDataFor("query"),
      isLoading: false,
      isUnbound: false,
      isRestricted: false,
      refetch: vi.fn(),
      ...result,
    });
    renderWithProviders(
      <DashboardWidget
        widget={widget}
        binding={widgetBinding}
        initiativeId={7}
        dashboardId={11}
        canEdit={false}
      />
    );
  };

  it("asks for the missing choice when the binding was never finished", async () => {
    renderState({ isUnbound: true });
    expect(await screen.findByText(/choose what this shows/i)).toBeInTheDocument();
  });

  it("says the data is out of reach when the target resolved and is not there", async () => {
    renderState({ isRestricted: true }, boundBinding);
    expect(await screen.findByText(/can't see this widget's data/i)).toBeInTheDocument();
    // Nothing to configure here, so nothing invites a reader to repoint a
    // binding that was never wrong.
    expect(screen.queryByText(/choose what this shows/i)).toBeNull();
  });

  it("reports a failed fetch as a failure, not as an access decision", async () => {
    renderState({ errorCode: WidgetErrorCode.DATA_UNAVAILABLE }, boundBinding);
    expect(await screen.findByText(/could not be loaded/i)).toBeInTheDocument();
    expect(screen.queryByText(/can't see this widget's data/i)).toBeNull();
  });
});
