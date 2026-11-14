/**
 * The "there's a newer version" affordance.
 *
 * It is only ever an offer. Applying a version replaces the dashboard's canvas,
 * so it takes the same write access editing does — and it must not appear at all
 * for a dashboard nobody installed, a listing that is gone, a version this build
 * cannot run, or a version already pinned. Each of those is a separate reason to
 * show nothing, and getting any of them wrong puts a button in front of someone
 * that either does nothing or changes their dashboard when they didn't ask.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import type {
  DashboardRead,
  MarketplaceListingDetail,
} from "@/api/generated/initiativeAPI.schemas";

import { DashboardUpdateBadge } from "./DashboardUpdateBadge";

const upgrade = vi.fn();
let listing: Partial<MarketplaceListingDetail> | undefined;

vi.mock("@/hooks/useMarketplace", () => ({
  useMarketplaceListingByUid: (uid: string | null | undefined) => ({
    data: uid ? listing : undefined,
  }),
}));

vi.mock("@/hooks/useDashboards", () => ({
  useUpgradeDashboard: () => ({ mutate: upgrade, isPending: false }),
}));

const dashboard = (overrides: Partial<DashboardRead> = {}) =>
  ({
    id: 3,
    name: "Sprint health",
    listing_uid: "NSTA0000000001",
    listing_version: "1.0.0",
    ...overrides,
  }) as DashboardRead;

const publishing = (version: string, installable = true) => ({
  installable,
  latest_version: { version, compatible: installable },
});

beforeEach(() => {
  upgrade.mockClear();
  listing = publishing("2.0.0") as Partial<MarketplaceListingDetail>;
});

describe("DashboardUpdateBadge", () => {
  it("offers the newer version to someone who can apply it", () => {
    renderWithProviders(<DashboardUpdateBadge dashboard={dashboard()} canEdit />);
    expect(screen.getByRole("button", { name: /2\.0\.0/ })).toBeInTheDocument();
  });

  it("applies it only when asked", async () => {
    const user = userEvent.setup();
    renderWithProviders(<DashboardUpdateBadge dashboard={dashboard()} canEdit />);
    expect(upgrade).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /2\.0\.0/ }));
    expect(upgrade).toHaveBeenCalledTimes(1);
  });

  it("tells a viewer without write access rather than offering a button", () => {
    renderWithProviders(<DashboardUpdateBadge dashboard={dashboard()} canEdit={false} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/2\.0\.0/)).toBeInTheDocument();
  });

  it("shows nothing for a dashboard that was authored here", () => {
    const { container } = renderWithProviders(
      <DashboardUpdateBadge dashboard={dashboard({ listing_uid: null })} canEdit />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows nothing when the pinned version is the current one", () => {
    listing = publishing("1.0.0") as Partial<MarketplaceListingDetail>;
    const { container } = renderWithProviders(
      <DashboardUpdateBadge dashboard={dashboard()} canEdit />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows nothing when this build cannot run the newer version", () => {
    // Offering it would produce a 409; the listing page is where "upgrade the
    // app first" belongs, not a button here that cannot work.
    listing = publishing("3.0.0", false) as Partial<MarketplaceListingDetail>;
    const { container } = renderWithProviders(
      <DashboardUpdateBadge dashboard={dashboard()} canEdit />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows nothing when the listing has been withdrawn", () => {
    // A withdrawn listing can still have a newer version on record. Installing
    // or upgrading it is refused, so offering the button would only fail.
    listing = {
      installable: false,
      available: false,
      latest_version: { version: "2.0.0", compatible: true },
    } as Partial<MarketplaceListingDetail>;
    const { container } = renderWithProviders(
      <DashboardUpdateBadge dashboard={dashboard()} canEdit />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows nothing when the listing is no longer in the catalog", () => {
    listing = undefined;
    const { container } = renderWithProviders(
      <DashboardUpdateBadge dashboard={dashboard()} canEdit />
    );
    expect(container).toBeEmptyDOMElement();
  });
});
