import { screen, waitFor } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { buildCommunity, communityCan } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type { CommunityEntry } from "@/hooks/useCommunities";

import { Route } from "./$communityId";

// The route's own component, loaded the way the route loads it.
const CommunityLayout = Route.options.component as React.ComponentType & {
  preload?: () => Promise<unknown>;
};
beforeAll(async () => {
  await CommunityLayout.preload?.();
});

// The layout is mounted directly rather than through the shipped tree: what is
// under test is what it renders for a given community state, and reaching it in the
// real router means clearing the auth and server guards above it first.
const routeParams = { communityId: "7" };
vi.mock("@tanstack/react-router", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tanstack/react-router")>()),
  useParams: () => routeParams,
  useLocation: () => ({ pathname: `/c/${routeParams.communityId}` }),
  Outlet: () => <div data-testid="community-outlet" />,
}));

const communityEntry = (
  id: number,
  name: string,
  extra: Partial<CommunityEntry> = {}
): CommunityEntry =>
  ({ ...buildCommunity({ id, name }), accessType: "member", ...extra }) as CommunityEntry;

describe("the community layout waits for this tab to adopt the URL's community", () => {
  // `renderPage` rather than a bare render: the not-a-member branch draws a
  // link home, which needs a router around it.
  const show = (
    activeCommunityId: number | null,
    { loading = false, communities = [communityEntry(3, "Alpha"), communityEntry(7, "Beta")] } = {}
  ) =>
    renderPage(CommunityLayout, {
      communities: { communities, activeCommunityId, loading, syncCommunityFromUrl: vi.fn() },
    });

  it("holds the subtree while the tab still points at another community", async () => {
    // A fresh tab is seeded from storage and adopts the URL in an effect that
    // runs a render after the community list arrives. Community-scoped hooks below read
    // that value for their query keys, so a subtree rendered in that window
    // asks the previous community and asks again once the adoption lands.
    show(3);
    expect(await screen.findByRole("status")).toBeInTheDocument();
    expect(screen.queryByTestId("community-outlet")).not.toBeInTheDocument();
  });

  it("renders the subtree once the two agree", async () => {
    show(7);
    expect(await screen.findByTestId("community-outlet")).toBeInTheDocument();
  });

  it("holds it while the community list is still loading", async () => {
    show(7, { loading: true });
    expect(await screen.findByRole("status")).toBeInTheDocument();
    expect(screen.queryByTestId("community-outlet")).not.toBeInTheDocument();
  });

  it("still says so plainly when the URL names a community you are not in", async () => {
    // The wait sits after the membership check, so a community you cannot enter
    // reports that rather than spinning on an adoption that never comes.
    show(3, { communities: [communityEntry(3, "Alpha")] });
    expect(await screen.findByText(/not a member/i)).toBeInTheDocument();
    expect(screen.queryByTestId("community-outlet")).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

describe("a suspended community is closed to its own administrators", () => {
  const show = (community: CommunityEntry, syncCommunityFromUrl = vi.fn()) => {
    renderPage(CommunityLayout, {
      communities: {
        communities: [community],
        activeCommunityId: null,
        loading: false,
        syncCommunityFromUrl,
      },
    });
    return syncCommunityFromUrl;
  };

  // A suspended community as its administrator's list serves it.
  const closedToItsAdmin: Partial<CommunityEntry> = {
    role: "admin",
    status: "suspended",
    can: communityCan("admin", { enter: false }),
  };

  it("shows the closed page and never adopts the community", async () => {
    const sync = show(communityEntry(7, "Beta", closedToItsAdmin));
    expect(await screen.findByText("This community is suspended")).toBeInTheDocument();
    expect(screen.queryByTestId("community-outlet")).not.toBeInTheDocument();
    expect(sync).not.toHaveBeenCalled();
  });

  it("names who to contact when the deployment has said", async () => {
    show(
      communityEntry(7, "Beta", {
        ...closedToItsAdmin,
        contact_email: "trust@example.com",
      })
    );
    expect(await screen.findByText(/Contact trust@example\.com\./)).toBeInTheDocument();
  });

  it("says to contact whoever runs the server when nobody is named", async () => {
    show(communityEntry(7, "Beta", closedToItsAdmin));
    expect(await screen.findByText(/Contact whoever runs this server\./)).toBeInTheDocument();
  });

  it("lets a platform grant through", async () => {
    const sync = show(communityEntry(7, "Beta", { status: "suspended", accessType: "grant" }));
    await waitFor(() => expect(sync).toHaveBeenCalledWith(7));
    expect(screen.queryByText("This community is suspended")).not.toBeInTheDocument();
  });
});
