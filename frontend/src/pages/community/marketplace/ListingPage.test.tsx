/**
 * Reading a listing, and getting back out.
 *
 * The shelf you were browsing has to survive the round trip. Both ways out of
 * this page lead to the marketplace, and each one has to carry the kind —
 * otherwise an admin browsing plug-ins clicks a listing, comes back, and is looking
 * at dashboards. The error route is the one that got missed first, which is why
 * it is pinned here alongside the ordinary one.
 *
 * Everyone reads the same page. What changes is the ending: only the
 * superadmin adds a plug-in, so anyone else is told who can instead of being
 * offered a button that would be refused.
 *
 * A project listing is drawn from the listing alone, and installing it is a
 * copy into an initiative the viewer may create projects in.
 */
import { Capacitor } from "@capacitor/core";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { addDays, format } from "date-fns";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildInitiative,
  buildMarketplaceListingDetail,
  buildProjectListingEnvelope,
  communityCan,
  initiativeCan,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { MarketplaceListingDetail } from "@/api/generated/initiativeAPI.schemas";
import { formatDate } from "@/ui/lib/formatDate";

import { ListingPage } from "./ListingPage";

let listing: Partial<MarketplaceListingDetail> | undefined;
let failed = false;
let communityRole = "superadmin";
let installedUids: string[] = [];
let installsState: "ready" | "loading" | "error" = "ready";

const openPortal = vi.fn();
let portal: { url: string } | null = null;
vi.mock("@/hooks/useBillingPortal", () => ({
  useBillingPortal: () => ({
    billing: portal,
    canSell: portal !== null,
    openAddress: vi.fn(),
    openPortal,
  }),
}));

vi.mock("@/hooks/useMarketplace", () => ({
  useMarketplaceListing: () => ({ data: listing, isError: failed }),
}));
vi.mock("@/hooks/useDashboards", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useDashboards")>()),
  useWidgetCatalog: () => ({ data: undefined }),
}));
vi.mock("@/hooks/useCommunities", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useCommunities")>()),
  useCommunities: () => ({
    activeCommunityId: 1,
    activeCommunity: { id: 1, role: communityRole, can: communityCan(communityRole) },
  }),
}));
vi.mock("@/hooks/useCommunityPlugins", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useCommunityPlugins")>()),
  useCommunityPlugins: () => ({
    data:
      installsState === "ready"
        ? { items: installedUids.map((uid) => ({ listing_uid: uid })) }
        : undefined,
    isLoading: installsState === "loading",
    isError: installsState === "error",
  }),
}));

const pluginListing = () =>
  ({
    id: 7,
    uid: "GLDCAL00000001",
    public_id: "core.community-calendar",
    kind: "plugin",
    source: "builtin",
    name: "Community calendar",
    publisher: "Initiative",
    first_party: true,
    description: "The community's own events.",
    avatar_url: "/marketplace/cal.svg",
    images: [],
    installs_count: 0,
    available: true,
    installable: true,
    versions: [],
    updated_at: "",
  }) as unknown as MarketplaceListingDetail;

/** The href of the link back to the marketplace, whichever route rendered it. */
const backHref = () =>
  screen
    .getAllByRole("link")
    .map((link) => link.getAttribute("href"))
    .find((href) => href?.includes("/marketplace") && !href.includes("core."));

beforeEach(() => {
  openPortal.mockReset();
  portal = null;
  listing = pluginListing();
  failed = false;
  communityRole = "superadmin";
  installedUids = [];
  installsState = "ready";
});

describe("ListingPage", () => {
  it("returns to the shelf it was opened from", async () => {
    renderPage(ListingPage, { routerSearch: { kind: "plugin" } });
    await screen.findByRole("heading", { name: "Community calendar" });
    expect(backHref()).toContain("kind=plugin");
  });

  it("returns to the shelf when the listing failed to load", async () => {
    // The way out of an error state is the one people actually take, and it was
    // the one that dropped the shelf.
    failed = true;
    listing = undefined;
    renderPage(ListingPage, { routerSearch: { kind: "plugin" } });
    await screen.findByText(/listing not found/i);
    expect(backHref()).toContain("kind=plugin");
  });

  it("falls back to the listing's own kind on a direct link", async () => {
    // Arrived without a shelf in the URL: the listing itself says which one it
    // belongs to.
    renderPage(ListingPage);
    await screen.findByRole("heading", { name: "Community calendar" });
    expect(backHref()).toContain("kind=plugin");
  });

  it("answers who wrote it before the install button", async () => {
    // The same sentence the card showed, on the page where the decision is
    // actually made.
    renderPage(ListingPage, { routerSearch: { kind: "plugin" } });
    await screen.findByRole("heading", { name: "Community calendar" });
    expect(screen.getByText("by Initiative")).toBeInTheDocument();
  });

  it("names the publisher of a listing that did not ship with this build", async () => {
    listing = {
      ...pluginListing(),
      source: "operator",
      publisher: "Acme Widgets",
    } as unknown as MarketplaceListingDetail;
    renderPage(ListingPage, { routerSearch: { kind: "plugin" } });
    await screen.findByRole("heading", { name: "Community calendar" });
    expect(screen.getByText("by Acme Widgets")).toBeInTheDocument();
  });

  it("offers no canvas preview for a plug-in", async () => {
    renderPage(ListingPage, { routerSearch: { kind: "plugin" } });
    await screen.findByRole("heading", { name: "Community calendar" });
    // A plug-in mounts a tool; there is no definition to draw.
    expect(screen.queryByText("Preview")).toBeNull();
  });

  it("tells a member who can add a plug-in they cannot", async () => {
    communityRole = "member";
    renderPage(ListingPage, { routerSearch: { kind: "plugin" } });

    expect(
      await screen.findByText("Ask your community's superadmin to add this plug-in.")
    ).toBeInTheDocument();
    // The button is present but refuses, rather than being hidden: seeing what
    // the plug-in offers is the point of letting them in here.
    expect(screen.getByRole("button", { name: /Add to community/ })).toBeDisabled();
  });

  it("tells an ordinary admin that the superadmin adds plug-ins", async () => {
    communityRole = "admin";
    renderPage(ListingPage, { routerSearch: { kind: "plugin" } });

    expect(
      await screen.findByText("Ask your community's superadmin to add this plug-in.")
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Add to community/ })).toBeDisabled();
  });

  it("says a plug-in is already installed instead of offering it again", async () => {
    installedUids = ["GLDCAL00000001"];
    renderPage(ListingPage, { routerSearch: { kind: "plugin" } });

    expect(await screen.findByText("Installed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Add to community/ })).toBeNull();
  });

  it("does not tell a member to ask for a plug-in the community already has", async () => {
    communityRole = "member";
    installedUids = ["GLDCAL00000001"];
    renderPage(ListingPage, { routerSearch: { kind: "plugin" } });

    expect(await screen.findByText("Installed")).toBeInTheDocument();
    expect(screen.queryByText("Ask your community's superadmin to add this plug-in.")).toBeNull();
  });

  it("does not guess at installed state while it is still loading", async () => {
    // Neither answer is known yet, so neither is claimed: no badge saying it is
    // there, and no offer to add something the community may already have.
    installsState = "loading";
    renderPage(ListingPage, { routerSearch: { kind: "plugin" } });

    await screen.findByRole("heading", { name: "Community calendar" });
    expect(screen.queryByText("Installed")).toBeNull();
    expect(screen.getByRole("button", { name: /Add to community/ })).toBeDisabled();
    expect(screen.queryByText("Ask your community's superadmin to add this plug-in.")).toBeNull();
  });

  it("says so when it could not check, rather than implying not installed", async () => {
    installsState = "error";
    communityRole = "member";
    renderPage(ListingPage, { routerSearch: { kind: "plugin" } });

    expect(
      await screen.findByText("Could not check whether this plug-in is already added.")
    ).toBeInTheDocument();
    // The "go ask an admin" line asserts the community does not have it, which is
    // exactly what failed to load.
    expect(screen.queryByText("Ask your community's superadmin to add this plug-in.")).toBeNull();
  });

  it("does not offer the superadmin an install it cannot rule out as a duplicate", async () => {
    // The superadmin *may* install, so only the unknown state holds the button back
    // here — the community may already have this, and the server would refuse.
    installsState = "error";
    renderPage(ListingPage, { routerSearch: { kind: "plugin" } });

    await screen.findByRole("heading", { name: "Community calendar" });
    expect(screen.getByRole("button", { name: /Add to community/ })).toBeDisabled();
  });

  it("offers to report a listing somebody else publishes", async () => {
    listing = {
      ...pluginListing(),
      source: "registry",
      publisher: "Acme Apps",
      first_party: false,
    } as unknown as MarketplaceListingDetail;
    renderPage(ListingPage, { routerSearch: { kind: "plugin" } });
    await screen.findByRole("heading", { name: "Community calendar" });
    expect(screen.getByRole("button", { name: "Report" })).toBeInTheDocument();
  });

  it("offers no report on a listing BeyondersStudio publishes", async () => {
    renderPage(ListingPage, { routerSearch: { kind: "plugin" } });
    await screen.findByRole("heading", { name: "Community calendar" });
    expect(screen.queryByRole("button", { name: "Report" })).toBeNull();
  });

  it("says a listing outside the curated catalogue is not available on an iPhone", async () => {
    vi.spyOn(Capacitor, "getPlatform").mockReturnValue("ios");
    listing = { ...pluginListing(), source: "operator" } as unknown as MarketplaceListingDetail;
    renderPage(ListingPage, { routerSearch: { kind: "plugin" } });

    expect(await screen.findByText("Not available in this app")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Community calendar" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Add to community/ })).toBeNull();
  });

  it("shows a curated listing on an iPhone", async () => {
    vi.spyOn(Capacitor, "getPlatform").mockReturnValue("ios");
    listing = { ...pluginListing(), source: "registry" } as unknown as MarketplaceListingDetail;
    renderPage(ListingPage, { routerSearch: { kind: "plugin" } });

    expect(await screen.findByRole("heading", { name: "Community calendar" })).toBeInTheDocument();
  });
});

describe("a project listing", () => {
  const projectListing = (overrides: Partial<MarketplaceListingDetail> = {}) =>
    buildMarketplaceListingDetail({
      uid: "LAUNCH00000001",
      kind: "project",
      name: "Launch plan",
      definition: { ...buildProjectListingEnvelope() },
      ...overrides,
    });

  it("draws the listing on the real project board, dated from today", async () => {
    const envelope = buildProjectListingEnvelope();
    listing = projectListing({
      // Stored out of order: the columns follow their positions.
      definition: { ...envelope, task_statuses: [...envelope.task_statuses].reverse() },
    });
    renderPage(ListingPage, { routerSearch: { kind: "project" } });

    const title = await screen.findByRole("link", { name: "Draft the announcement" });
    expect(
      screen.getAllByRole("button", { name: /^Collapse / }).map((b) => b.getAttribute("aria-label"))
    ).toEqual(["Collapse To do", "Collapse Doing", "Collapse Done"]);
    // A preview task has nowhere of its own to open, so its title stays here.
    expect(title).toHaveAttribute("href", `/c/1/marketplace/${listing?.public_id}`);
    // The project starts today, as installing it today would have it, so the
    // task due two days in is due the day after tomorrow.
    const card = title.closest("[data-kanban-scroll-lock]") as HTMLElement;
    expect(card).toHaveTextContent(formatDate(format(addDays(new Date(), 2), "yyyy-MM-dd")));
    expect(within(card).getByText("1/2 items")).toBeInTheDocument();
    expect(within(card).getByText("Small")).toBeInTheDocument();
    // Nothing to switch to without an example.
    expect(screen.queryByRole("radio", { name: "Example" })).toBeNull();
  });

  it("opens on the example, and switches to the blank", async () => {
    listing = projectListing({
      example: {
        ...buildProjectListingEnvelope(),
        tasks: [{ ...buildProjectListingEnvelope().tasks[0], title: "Announcement drafted" }],
      },
    });
    const user = userEvent.setup();
    renderPage(ListingPage, { routerSearch: { kind: "project" } });

    expect(await screen.findByText("Announcement drafted")).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "Blank" }));

    expect(screen.getByText("Draft the announcement")).toBeInTheDocument();
    expect(screen.queryByText("Announcement drafted")).toBeNull();
  });

  it("installs a copy of the example from the day picked, and opens it", async () => {
    let sent: unknown;
    server.use(
      communityHttp.get("/initiatives/", () =>
        HttpResponse.json([
          buildInitiative({ id: 12, name: "Garden", can: initiativeCan({ create: ["project"] }) }),
        ])
      ),
      communityHttp.post("/marketplace/listings/by-uid/:uid/install", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({
          kind: "project",
          listing_uid: "LAUNCH00000001",
          listing_version: "1.0.0",
          result: { entity_id: 40, entity_title: "Launch plan" },
        });
      })
    );
    listing = projectListing({ example: { ...buildProjectListingEnvelope() } });
    const user = userEvent.setup();
    const { router } = renderPage(ListingPage, { routerSearch: { kind: "project" } });

    await user.click(await screen.findByRole("button", { name: /Add to an initiative/ }));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("Garden");
    await user.click(within(dialog).getByLabelText("Start from the example"));
    expect(within(dialog).getByText("Start date")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Add" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/c/1/i/12/projects/40"));
    expect(sent).toEqual({
      initiative_id: 12,
      start_from: "example",
      starts_on: format(new Date(), "yyyy-MM-dd"),
    });
  });

  it("asks for no start date or starting point when the listing has neither", async () => {
    listing = projectListing({
      definition: {
        ...buildProjectListingEnvelope({ project: { name: "Launch plan" }, tasks: [] }),
      },
    });
    const user = userEvent.setup();
    renderPage(ListingPage, { routerSearch: { kind: "project" } });

    await user.click(await screen.findByRole("button", { name: /Add to an initiative/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByText("Start date")).toBeNull();
    expect(within(dialog).queryByLabelText("Start from the example")).toBeNull();
  });
});

describe("a plug-in this community cannot add yet", () => {
  it("says why instead of offering the button", async () => {
    listing = {
      ...pluginListing(),
      unavailable: { reason: "entitlement_required", action_url: null },
    };
    renderPage(ListingPage);
    await screen.findByRole("heading", { name: "Community calendar" });

    expect(screen.getByRole("button", { name: /Add to community/ })).toBeDisabled();
    expect(
      screen.getByText("This plug-in has to be set up for your community before it can be added.")
    ).toBeInTheDocument();
  });

  it("offers the button again once it can", async () => {
    listing = { ...pluginListing(), unavailable: null };
    renderPage(ListingPage);
    await screen.findByRole("heading", { name: "Community calendar" });

    expect(screen.getByRole("button", { name: /Add to community/ })).toBeEnabled();
    expect(screen.queryByText(/has to be set up for your community/)).toBeNull();
  });
});

describe("a plug-in the deployment's term has no seat free for", () => {
  const full = () => ({
    ...pluginListing(),
    unavailable: { reason: "term_full" as const, action_url: null },
  });

  it("offers the seat a request in the billing portal, in place of the button", async () => {
    listing = full();
    portal = { url: "https://billing.example.com" };
    const user = userEvent.setup();
    renderPage(ListingPage);
    await screen.findByRole("heading", { name: "Community calendar" });

    expect(
      screen.getByText("This deployment's plan has no seat free for Community calendar.")
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Request" }));
    expect(openPortal).toHaveBeenCalledWith(1, "manage", null, {
      request: "plugin",
      listing: "GLDCAL00000001",
    });
  });

  it("tells anyone else to ask the community's admins, with no button", async () => {
    listing = full();
    portal = { url: "https://billing.example.com" };
    communityRole = "member";
    renderPage(ListingPage);
    await screen.findByRole("heading", { name: "Community calendar" });

    expect(screen.getByText("Ask your community's admins to request it.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Request" })).toBeNull();
    expect(openPortal).not.toHaveBeenCalled();
  });
});
