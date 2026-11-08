/**
 * Browsing the catalog.
 *
 * The load-bearing detail is where "already installed" comes from. The catalog
 * is platform-level and holds nothing about this community, so the badge has to be
 * derived from the community's own dashboards — matched on the listing uid an
 * install pins, not on the name or the public id.
 */
import { Capacitor } from "@capacitor/core";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import type { MarketplaceListingSummary } from "@/api/generated/initiativeAPI.schemas";

import { BrowsePage } from "./BrowsePage";

const listingsFor = vi.fn();
let installed: Record<string, number> = {};

vi.mock("@/hooks/useMarketplace", () => ({
  useMarketplaceListings: (params: unknown) => listingsFor(params),
}));

let installedFailed = false;
let installedPlugins: { listing_uid: string }[] = [];

vi.mock("@/hooks/useDashboards", () => ({
  useInstalledListings: () => ({
    data: installedFailed ? undefined : { counts: installed },
    isError: installedFailed,
  }),
}));

vi.mock("@/hooks/useCommunityPlugins", () => ({
  useCommunityPlugins: () => ({
    data: installedFailed ? undefined : { items: installedPlugins },
    isError: installedFailed,
  }),
}));

const listing = (overrides: Partial<MarketplaceListingSummary> = {}) =>
  ({
    id: 1,
    uid: "SPRNT000000001",
    public_id: "core.sprint",
    kind: "dashboard",
    source: "builtin",
    name: "Sprint health",
    publisher: "Initiative",
    description: "How the sprint is going.",
    avatar_url: "/marketplace/sprint.svg",
    images: [],
    installs_count: 0,
    available: true,
    installable: true,
    latest_version: { version: "1.0.0", compatible: true, published_at: "" },
    updated_at: "",
    ...overrides,
  }) as MarketplaceListingSummary;

beforeEach(() => {
  installed = {};
  installedPlugins = [];
  installedFailed = false;
  listingsFor.mockReturnValue({
    data: { items: [listing()], total: 1 },
    isLoading: false,
  });
});

describe("BrowsePage", () => {
  it("shows a card per listing", async () => {
    renderPage(BrowsePage);
    expect(await screen.findByText("Sprint health")).toBeInTheDocument();
    // Attribution rides along with how the listing got here, so a card never
    // shows an author's name on its own.
    expect(screen.getByText("by Initiative")).toBeInTheDocument();
  });

  it("asks the catalog only for dashboards", async () => {
    // Defaulted by the page itself: `useSearch({ strict: false })` does not run
    // the route's validation, so a page that leaned on it would drop the filter
    // and mix plug-ins into the grid.
    renderPage(BrowsePage);
    await screen.findByText("Sprint health");
    expect(listingsFor).toHaveBeenCalledWith(expect.objectContaining({ kind: "dashboard" }));
  });

  it("asks for plug-ins on the plug-ins shelf", async () => {
    renderPage(BrowsePage, { routerSearch: { kind: "plugin" } });
    await screen.findByText("Sprint health");
    expect(listingsFor).toHaveBeenCalledWith(expect.objectContaining({ kind: "plugin" }));
  });

  it("marks an installed plug-in on the plug-ins shelf", async () => {
    // Each shelf asks its own tool: the dashboards aggregate knows nothing
    // about plug-ins, so reading installed state from it here would report every
    // plug-in as not installed.
    installedPlugins = [{ listing_uid: "SPRNT000000001" }];
    renderPage(BrowsePage, { routerSearch: { kind: "plugin" } });
    expect(await screen.findByText("Installed")).toBeInTheDocument();
  });

  it("does not read plug-in installs from the dashboard aggregate", async () => {
    installed = { SPRNT000000001: 1 };
    installedPlugins = [];
    renderPage(BrowsePage, { routerSearch: { kind: "plugin" } });
    await screen.findByText("Sprint health");
    expect(screen.queryByText("Installed")).toBeNull();
  });

  it("marks nothing installed on the projects shelf", async () => {
    // A project installs as a new copy every time, so the dashboards' counts
    // say nothing about it, even for the same uid.
    installed = { SPRNT000000001: 1 };
    renderPage(BrowsePage, { routerSearch: { kind: "project" } });
    await screen.findByText("Sprint health");
    expect(listingsFor).toHaveBeenCalledWith(expect.objectContaining({ kind: "project" }));
    expect(screen.queryByText("Installed")).toBeNull();
  });

  it("marks a listing this community already installed", async () => {
    // Counted server-side over every dashboard. Deriving this from the
    // paginated dashboard list would mark some installs and miss the rest once
    // a community has more dashboards than fit on a page.
    installed = { SPRNT000000001: 1 };
    renderPage(BrowsePage);
    expect(await screen.findByText("Installed")).toBeInTheDocument();
  });

  it("does not mark a listing whose uid nobody here pinned", async () => {
    installed = { SMTHNG00000001: 2 };
    renderPage(BrowsePage);
    await screen.findByText("Sprint health");
    expect(screen.queryByText("Installed")).toBeNull();
  });

  it("searches the catalog rather than filtering the page", async () => {
    // Paging means the answer is not all on screen, so the query has to reach
    // the server.
    const user = userEvent.setup();
    renderPage(BrowsePage);
    await user.type(await screen.findByRole("textbox"), "burndown");

    await waitFor(() =>
      expect(listingsFor).toHaveBeenCalledWith(expect.objectContaining({ search: "burndown" }))
    );
  });

  it("says so rather than marking everything uninstalled when the check fails", async () => {
    // "We do not know" and "you have none of these" look identical on a card,
    // and only one of them is true — so the page says which.
    installedFailed = true;
    renderPage(BrowsePage);
    await screen.findByText("Sprint health");
    expect(screen.queryByText("Installed")).toBeNull();
    expect(screen.getByText(/couldn't check which of these/i)).toBeInTheDocument();
  });

  it("says nothing extra when the check succeeds", async () => {
    installed = { SPRNT000000001: 1 };
    renderPage(BrowsePage);
    await screen.findByText("Installed");
    expect(screen.queryByText(/couldn't check which of these/i)).toBeNull();
  });

  it("does not present a failed catalog as an empty one", async () => {
    // "Nothing to offer" would send someone looking for listings that exist.
    listingsFor.mockReturnValue({ data: undefined, isLoading: false, isError: true });
    renderPage(BrowsePage);
    expect(await screen.findByText(/marketplace unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText(/nothing here yet/i)).toBeNull();
  });

  it("says so when a search matches nothing", async () => {
    listingsFor.mockReturnValue({ data: { items: [], total: 0 }, isLoading: false });
    renderPage(BrowsePage);
    expect(await screen.findByText(/nothing here yet|no matches/i)).toBeInTheDocument();
  });

  it("shows only the curated catalogue on an iPhone", async () => {
    vi.spyOn(Capacitor, "getPlatform").mockReturnValue("ios");
    listingsFor.mockReturnValue({
      data: {
        items: [
          listing(),
          listing({
            uid: "PRTR000000001A",
            public_id: "acme.extra",
            name: "Operator extra",
            source: "operator",
            publisher: "Acme",
          }),
        ],
        total: 2,
      },
      isLoading: false,
    });
    renderPage(BrowsePage);

    expect(await screen.findByText("Sprint health")).toBeInTheDocument();
    expect(screen.queryByText("Operator extra")).toBeNull();
    expect(listingsFor).toHaveBeenCalledWith(
      expect.objectContaining({ source: ["builtin", "registry"] })
    );
  });

  it("shows the whole catalogue elsewhere", async () => {
    listingsFor.mockReturnValue({
      data: {
        items: [listing({ public_id: "acme.extra", name: "Operator extra", source: "operator" })],
        total: 1,
      },
      isLoading: false,
    });
    renderPage(BrowsePage);

    expect(await screen.findByText("Operator extra")).toBeInTheDocument();
    expect(listingsFor).toHaveBeenCalledWith(expect.objectContaining({ source: undefined }));
  });
});
