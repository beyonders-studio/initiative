/**
 * The way into the community directory, through the router the app ships.
 *
 * Three links make up that way in, and a test that mounts the page component
 * directly proves none of them: the generated route tree has to register
 * `/communities`, the route's component has to actually load (it is code-split,
 * so it arrives as its own chunk), and the entry in the community rail has to point
 * at an address that tree resolves. Break any one of them and clicking the
 * entry renders nothing at all — which is indistinguishable, on screen, from a
 * button that does nothing.
 *
 * So each link is checked against the real article: the generated tree, the
 * route's own component, and the href the rail renders.
 */
import { createRouter } from "@tanstack/react-router";
import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DirectoryCommunityRead } from "@/api/generated/initiativeAPI.schemas";
import { CommunitySidebar } from "@/components/communities/CommunitySidebar";
import { AppSidebar } from "@/components/sidebar/AppSidebar";
import { SidebarProvider } from "@/components/sidebar/sidebar";
import type { CommunityEntry } from "@/hooks/useCommunities";
import { routeTree } from "@/routeTree.gen";

import { buildBanner, buildCommunity } from "./factories";
import { buildRouterContext, renderPage } from "./helpers/render";

const appConfig = vi.hoisted(() => ({ directory: true }));
vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({
    billing: null,
    communityDirectoryEnabled: appConfig.directory,
    isLoading: false,
  }),
}));
vi.mock("@/lib/mascotToast", () => ({
  toast: { info: vi.fn(), error: vi.fn(), success: vi.fn() },
}));

const directory = vi.fn();
vi.mock("@/hooks/useCommunityDirectory", () => ({
  useDirectoryCommunities: (params: unknown) => directory(params),
  useJoinDirectoryCommunity: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

const community: DirectoryCommunityRead = {
  id: 7,
  name: "Riverside Players",
  description: "Community theatre.",
  icon_url: null,
  location: null,
  banner: buildBanner(),
  categories: ["art"],
  member_count: 12,
  online_count: 0,
  already_member: false,
};

const DIRECTORY_ROUTE_ID = "/_serverRequired/_authenticated/communities";

/** The router the app builds, from the generated tree rather than a tree
 *  assembled for the test — the registration is the thing under test. */
const router = createRouter({ routeTree, context: buildRouterContext() });

const resolvedRouteId = (pathname: string): string => {
  const matches = router.matchRoutes(pathname, {});
  return String(matches.at(-1)?.routeId ?? "__none__");
};

beforeEach(() => {
  vi.clearAllMocks();
  appConfig.directory = true;
  directory.mockReturnValue({
    data: { pages: [{ items: [community], total_count: 1 }] },
    isLoading: false,
    isError: false,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage: vi.fn(),
  });
});

describe("the community directory's way in", () => {
  it("is an address the shipped route tree serves", () => {
    expect(resolvedRouteId("/communities")).toBe(DIRECTORY_ROUTE_ID);
  });

  it("is where the rail's entry points", async () => {
    const communities = [
      { ...buildCommunity({ id: 1, name: "Alpha" }), accessType: "member" } as CommunityEntry,
    ];
    renderPage(
      () => (
        <SidebarProvider>
          <CommunitySidebar />
        </SidebarProvider>
      ),
      {
        initialRoute: "/c/$communityId",
        routeParams: { communityId: "1" },
        communities: { communities },
      }
    );

    const link = await screen.findByRole("link", { name: "Join a community" });
    // The href the rail renders, put back through the shipped tree: an entry
    // pointing somewhere that tree does not serve is the failure this catches.
    expect(resolvedRouteId(new URL(link.getAttribute("href") ?? "", "http://x").pathname)).toBe(
      DIRECTORY_ROUTE_ID
    );
  });

  it("loads its page from its own chunk, searchable, with a card per community", async () => {
    const route = router.routesById[DIRECTORY_ROUTE_ID];
    const Page = route.options.component as React.ComponentType & {
      preload?: () => Promise<unknown>;
    };

    // The dynamic import the route is declared with. A moved page, a renamed
    // export, or a chunk that will not load fails here rather than at a click.
    await Page.preload?.();

    renderPage(Page, { initialRoute: "/communities" });

    expect(await screen.findByText("Riverside Players")).toBeInTheDocument();
    expect(screen.getByText("1 community")).toBeInTheDocument();
  });

  it("puts what narrows it in the sidebar, on this route and not the next", async () => {
    // The filters and the cards sit on opposite sides of the app layout, so
    // the shell has to switch the sidebar over on the way in — a page of cards
    // with no way to narrow them is the failure this catches.
    const { unmount } = renderPage(
      () => (
        <SidebarProvider>
          <AppSidebar />
        </SidebarProvider>
      ),
      { initialRoute: "/communities" }
    );
    expect(await screen.findByLabelText("Search communities")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Tabletop RPG" })).toBeInTheDocument();
    unmount();

    renderPage(
      () => (
        <SidebarProvider>
          <AppSidebar />
        </SidebarProvider>
      ),
      { initialRoute: "/my-tools" }
    );
    expect(await screen.findByRole("link", { name: "My Tools" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Search communities")).not.toBeInTheDocument();
  });

  it("keeps the personal sidebar where the owner runs no directory", async () => {
    // The page says there is nothing here; a search box and twelve shelves
    // beside it would be offering to narrow something that does not exist.
    appConfig.directory = false;
    renderPage(
      () => (
        <SidebarProvider>
          <AppSidebar />
        </SidebarProvider>
      ),
      { initialRoute: "/communities" }
    );

    expect(await screen.findByRole("link", { name: "My Tools" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Search communities")).not.toBeInTheDocument();
  });
});
