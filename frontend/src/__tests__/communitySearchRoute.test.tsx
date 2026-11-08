/**
 * The way into community search, through the router and the palette the app ships.
 *
 * Two things have to be true for search to be reachable at all: the generated
 * route tree has to serve `/c/{id}/search` and load the page from its own
 * chunk, and the command palette has to offer the index's answers plus the way
 * through to the full page. A test that mounts the page component directly
 * proves neither.
 */
import { createRouter } from "@tanstack/react-router";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SearchHit } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { CommandCenter } from "@/components/search/CommandCenter";
import { routeTree } from "@/routeTree.gen";

import { buildSearchHit, buildSearchResults, buildSearchSuggestion } from "./factories";
import { buildRouterContext, renderPage } from "./helpers/render";

const SEARCH_ROUTE_ID = "/_serverRequired/_authenticated/c/$communityId/search";

const mocks = vi.hoisted(() => ({ search: vi.fn(), suggest: vi.fn(), members: vi.fn() }));
vi.mock("@/hooks/useUsers", () => ({
  useUserSearch: (options: unknown) => mocks.members(options),
}));
vi.mock("@/hooks/useSearch", () => ({
  useCommunitySearch: (params: unknown, options: unknown) => mocks.search(params, options),
  useCommunitySearchSuggest: (query: string, options: unknown) => mocks.suggest(query, options),
}));

/** The mocked module, for asserting how the palette scoped its question. */
const useSearchModule = { useCommunitySearchSuggest: mocks.suggest };

type SearchParams = { types?: string[]; page?: number; page_size?: number };

/**
 * Answer per scope and per page, the way the endpoint does: `total_count`
 * counts everything that matched, not what came back, and a page past the end
 * comes back empty with the total intact.
 */
const withHits = (tools: SearchHit[], tags: SearchHit[], comments: SearchHit[] = []) => {
  mocks.search.mockImplementation((params: SearchParams) => {
    const all = params.types?.includes("tag")
      ? tags
      : params.types?.includes("comment")
        ? comments
        : tools;
    const page = params.page ?? 1;
    const pageSize = params.page_size ?? 20;
    const start = (page - 1) * pageSize;
    return {
      data: buildSearchResults(all.slice(start, start + pageSize), {
        total_count: all.length,
        page,
        page_size: pageSize,
        has_next: start + pageSize < all.length,
        has_prev: page > 1,
      }),
      isLoading: false,
      isFetched: true,
      isSuccess: true,
    };
  });
};

/**
 * Every scope still showing the PREVIOUS query's results, the way React Query
 * keeps them on screen while a new query is in flight. Tools matched one thing
 * and tags matched nothing — for the query that is leaving.
 */
const withStaleAnswer = () => {
  mocks.search.mockImplementation((params: SearchParams) => {
    const isTags = params.types?.includes("tag") ?? false;
    return {
      data: buildSearchResults(isTags ? [] : [buildSearchHit()], { total_count: isTags ? 0 : 1 }),
      isLoading: false,
      isFetched: true,
      isPlaceholderData: true,
    };
  });
};

const router = createRouter({ routeTree, context: buildRouterContext() });

const resolvedRouteId = (pathname: string): string => {
  const matches = router.matchRoutes(pathname, {});
  return String(matches.at(-1)?.routeId ?? "__none__");
};

const searchPage = async () => {
  const route = router.routesById[SEARCH_ROUTE_ID];
  const Page = route.options.component as React.ComponentType & {
    preload?: () => Promise<unknown>;
  };
  // The dynamic import the route is declared with: a moved page or a renamed
  // export fails here rather than at a click.
  await Page.preload?.();
  return Page;
};

const renderSearch = async (routerSearch: Record<string, unknown>) => {
  const Page = await searchPage();
  return renderPage(Page, {
    initialRoute: "/c/$communityId/search",
    routeParams: { communityId: "1" },
    routerSearch,
  });
};

const project = () =>
  buildSearchHit({
    entity_id: 7,
    tool_id: 7,
    title: "Riverside kickoff",
    snippet: "the <riverside> stage build",
  });

const comment = () =>
  buildSearchHit({
    entity_type: "comment",
    entity_id: 31,
    title: "the riverside stage is booked",
    tool: Tool.project,
    tool_id: 7,
  });

const tag = () =>
  buildSearchHit({
    entity_type: "tag",
    entity_id: 12,
    title: "riverside",
    initiative_id: null,
    tool: null,
    tool_id: null,
  });

beforeEach(() => {
  vi.clearAllMocks();
  mocks.suggest.mockReturnValue({ data: [], isLoading: false, isFetched: true, isSuccess: true });
  mocks.members.mockReturnValue({
    data: { items: [], total_count: 0, page: 1, page_size: 20, has_next: false, has_prev: false },
    isLoading: false,
    isFetched: true,
    isSuccess: true,
  });
  withHits([], []);
});

describe("the community search page", () => {
  it("is an address the shipped route tree serves", () => {
    expect(resolvedRouteId("/c/1/search")).toBe(SEARCH_ROUTE_ID);
  });

  it("lands on tools, linked to where each result lives", async () => {
    withHits([project()], [tag()]);
    await renderSearch({ q: "riverside" });

    expect(await screen.findByRole("tab", { name: "Tools" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    const hit = screen.getByRole("link", { name: /Riverside kickoff/ });
    expect(hit).toHaveAttribute("href", "/c/1/i/5/projects/7");
    // What matched is marked up inside the snippet rather than shown with the
    // delimiters the database wrapped it in.
    expect(within(hit).getByText("riverside")).toBeInTheDocument();
    expect(hit).not.toHaveTextContent("<riverside>");
  });

  it("gives the community's vocabulary its own tab and its own address", async () => {
    withHits([project()], [tag()]);
    await renderSearch({ q: "riverside", tab: "tag" });

    expect(await screen.findByRole("link", { name: /^riversideTag$/ })).toHaveAttribute(
      "href",
      "/c/1/tags/12"
    );
  });

  it("lets a reader open a tab with nothing behind it and says so", async () => {
    withHits([project()], []);
    const user = userEvent.setup();
    await renderSearch({ q: "riverside" });

    await screen.findByRole("link", { name: /Riverside kickoff/ });
    const tags = screen.getByRole("tab", { name: "Tags" });
    expect(tags).toBeEnabled();

    await user.click(tags);

    expect(await screen.findByText(/No results for/)).toBeInTheDocument();
  });

  it("reads what people said on the content, on its own tab", async () => {
    withHits([project()], [], [comment()]);
    await renderSearch({ q: "riverside", tab: "comment" });

    // A comment has no page of its own, so it goes to the thing it is on.
    expect(
      await screen.findByRole("link", { name: /the riverside stage is booked/ })
    ).toHaveAttribute("href", "/c/1/i/5/projects/7");
  });

  it("asks nothing until there is something to search for", async () => {
    await renderSearch({});

    expect(await screen.findByText("Search this community")).toBeInTheDocument();
    for (const call of mocks.search.mock.calls) {
      expect(call[0].search).toBe("");
    }
  });

  // The heading names what is being searched, the same way the sidebar's search
  // row does — a result page reached from anywhere says which community it
  // covers, rather than a bare "Search".
  it("names the community in its heading", async () => {
    await renderSearch({ q: "alpha" });

    expect(
      await screen.findByRole("heading", { name: "Search Community 1", level: 1 })
    ).toBeInTheDocument();
  });

  it("puts a reader who arrives past the last page back on results", async () => {
    // A link from before the content moved, or a query that has since
    // narrowed: page 99 of 25 results is empty, and left alone it would read
    // as "nothing matched".
    withHits(
      Array.from({ length: 25 }, (_, index) => buildSearchHit({ title: `Match ${index}` })),
      []
    );
    const { router: pageRouter } = await renderSearch({ q: "riverside", page: 99 });

    expect(await screen.findByText("Match 20")).toBeInTheDocument();
    await waitFor(() => expect(pageRouter.state.location.search).toMatchObject({ page: 2 }));
    expect(screen.queryByText(/No results for/)).not.toBeInTheDocument();
  });

  it("says so when it is showing close matches rather than what was asked", async () => {
    // Whole-word matching cannot answer a misspelling. Offering the closest
    // titles is better than an empty page, as long as the reader is told which
    // of the two they got.
    mocks.search.mockImplementation((params: SearchParams) => ({
      data: buildSearchResults(params.types?.includes("tag") ? [] : [project()], {
        fuzzy: !params.types?.includes("tag"),
      }),
      isLoading: false,
      isFetched: true,
    }));
    await renderSearch({ q: "riversde" });

    expect(await screen.findByText(/Nothing matches/)).toHaveTextContent("riversde");
    expect(screen.getByRole("link", { name: /Riverside kickoff/ })).toBeInTheDocument();
  });

  it("draws no conclusion from a total that belongs to the query before it", async () => {
    // Arriving on page 3 of a fresh query while the previous query's results
    // are still on screen. That query's total belongs to the query that is
    // leaving and says nothing about this one, so the page must not be
    // corrected off 3 on the strength of it.
    withStaleAnswer();
    const { router: pageRouter } = await renderSearch({ q: "riverside", page: 3 });

    await screen.findByRole("tab", { name: "Tools" });
    expect(pageRouter.state.location.search).toMatchObject({ page: 3 });
  });

  it("shows the people of this community on their own tab, and asks the roster", async () => {
    // Members are not in the index — identity is shared across communities,
    // and the index is per-community — so the tab asks the roster instead.
    mocks.members.mockReturnValue({
      data: {
        items: [
          {
            id: 4,
            username: "thorn-ironforge",
            discriminator: 22,
            display_name: "Thorn Ironforge",
            avatar_url: null,
            status: "active",
          },
        ],
        total_count: 1,
        page: 1,
        page_size: 20,
        has_next: false,
        has_prev: false,
      },
      isLoading: false,
      isFetched: true,
      isSuccess: true,
    });
    await renderSearch({ q: "irnforge", tab: "member" });

    expect(await screen.findByText("Thorn Ironforge")).toBeInTheDocument();
    expect(mocks.members).toHaveBeenCalledWith(
      expect.objectContaining({ search: "irnforge", enabled: true })
    );
    // ...and the index is not asked on this tab: people are not in it.
    expect(mocks.search).toHaveBeenLastCalledWith(
      expect.anything(),
      expect.objectContaining({ enabled: false })
    );
  });

  it("puts Members second, between what is here and what was said about it", async () => {
    withHits([project()], []);
    await renderSearch({ q: "riverside" });

    await screen.findByRole("tab", { name: "Tools" });
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Tools",
      "Members",
      "Comments",
      "Tags",
    ]);
  });
});

describe("the command palette", () => {
  it("carries the same three slices, and narrows to the one it is on", async () => {
    mocks.suggest.mockReturnValue({ data: [], isLoading: false, isFetched: true, isSuccess: true });
    renderPage(CommandCenter, {
      initialRoute: "/g/$communityId",
      routeParams: { communityId: "1" },
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    fireEvent.keyDown(document, { key: "k", metaKey: true });
    await userEvent.type(await screen.findByRole("combobox"), "riverside");

    // Opens on the same slice the results page does.
    const tools = await screen.findByRole("tab", { name: "Tools" }, { timeout: 2000 });
    expect(tools).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Comments" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Tags" })).toBeInTheDocument();
    // Members too: people are read from the roster rather than the index, and
    // the palette makes that second request so its scopes match the page's.
    expect(screen.getByRole("tab", { name: "Members" })).toBeInTheDocument();

    // Tab from the input moves between slices, so the hands stay on the query.
    // Members sits second, and is the one the index does not answer.
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Tab" });
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Members" })).toHaveAttribute("aria-selected", "true")
    );
    expect(useSearchModule.useCommunitySearchSuggest).toHaveBeenLastCalledWith(
      expect.any(String),
      expect.objectContaining({ enabled: false })
    );

    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Tab" });
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Comments" })).toHaveAttribute("aria-selected", "true")
    );
    expect(useSearchModule.useCommunitySearchSuggest).toHaveBeenLastCalledWith(
      expect.any(String),
      expect.objectContaining({ types: ["comment"] })
    );

    // Shift+Tab is left alone, so focus can still walk out of the input and
    // reach the strip, the results and the close button by keyboard.
    const before = screen.getByRole("tab", { selected: true }).textContent;
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Tab", shiftKey: true });
    expect(screen.getByRole("tab", { selected: true })).toHaveTextContent(before ?? "");
  });

  it("answers from the index once there is a query, and offers the whole page", async () => {
    mocks.suggest.mockReturnValue({
      data: [
        buildSearchSuggestion({
          entity_type: "calendar_event",
          entity_id: 8,
          title: "Riverside read-through",
          tool: Tool.calendar,
          tool_id: 2,
        }),
      ],
      isLoading: false,
    });

    const { router: pageRouter } = renderPage(CommandCenter, {
      initialRoute: "/c/$communityId",
      routeParams: { communityId: "1" },
    });
    // The router resolves its match a tick after render, remounting what it
    // renders. Opening before that tears the dialog straight back down.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    fireEvent.keyDown(document, { key: "k", metaKey: true });

    const input = await screen.findByRole("combobox");
    await userEvent.type(input, "riverside");

    expect(
      await screen.findByText("Riverside read-through", undefined, { timeout: 2000 })
    ).toBeInTheDocument();

    await userEvent.click(await screen.findByText(/See all results/));
    expect(pageRouter.state.location.pathname).toBe("/c/1/search");
    expect(pageRouter.state.location.searchStr).toContain("q=riverside");
  });

  it("shows only the slice being read, and says when it holds nothing", async () => {
    // Members come from the roster and everything else from the index, so each
    // slice switches the other question off — and a switched-off question keeps
    // the answer it was last given. Only the slice being read may put rows on
    // screen, and a slice that matched nobody says so.
    mocks.suggest.mockReturnValue({
      data: [
        buildSearchSuggestion({
          entity_type: "comment",
          entity_id: 31,
          title: "the riverside stage is booked",
          tool: Tool.project,
          tool_id: 7,
        }),
      ],
      isLoading: false,
      isFetched: true,
      isSuccess: true,
    });

    renderPage(CommandCenter, {
      initialRoute: "/g/$communityId",
      routeParams: { communityId: "1" },
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    fireEvent.keyDown(document, { key: "k", metaKey: true });
    await userEvent.type(await screen.findByRole("combobox"), "riverside");

    expect(
      await screen.findByText("the riverside stage is booked", undefined, { timeout: 2000 })
    ).toBeInTheDocument();

    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Tab" });
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Members" })).toHaveAttribute("aria-selected", "true")
    );

    expect(screen.queryByText("the riverside stage is booked")).not.toBeInTheDocument();
    expect(screen.getByText("No results found.")).toBeInTheDocument();
  });

  it("does not report a search that failed as nobody matching", async () => {
    // A request that never landed says nothing about who is in the community.
    mocks.members.mockReturnValue({
      data: undefined,
      isLoading: false,
      isFetched: true,
      isSuccess: false,
      isError: true,
    });

    renderPage(CommandCenter, {
      initialRoute: "/g/$communityId",
      routeParams: { communityId: "1" },
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    fireEvent.keyDown(document, { key: "k", metaKey: true });
    await userEvent.type(await screen.findByRole("combobox"), "riverside");
    await screen.findByRole("tab", { name: "Members" }, { timeout: 2000 });
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Tab" });

    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Members" })).toHaveAttribute("aria-selected", "true")
    );
    expect(screen.getByText("Search is not answering")).toBeInTheDocument();
    expect(screen.queryByText("No results found.")).not.toBeInTheDocument();
  });

  it("finds a person from the palette and opens their profile", async () => {
    // Profiles are public and belong to the person, so this leaves the
    // community tree rather than routing under /c/{community}.
    mocks.members.mockReturnValue({
      data: {
        items: [
          {
            id: 4,
            username: "thorn-ironforge",
            discriminator: 22,
            display_name: "Thorn Ironforge",
            avatar_url: null,
            status: "active",
          },
        ],
        total_count: 1,
        page: 1,
        page_size: 5,
        has_next: false,
        has_prev: false,
      },
      isLoading: false,
      isFetched: true,
      isSuccess: true,
    });
    mocks.suggest.mockReturnValue({ data: [], isFetched: true, isSuccess: true });

    renderPage(CommandCenter, {
      initialRoute: "/g/$communityId",
      routeParams: { communityId: "1" },
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    fireEvent.keyDown(document, { key: "k", metaKey: true });
    await userEvent.type(await screen.findByRole("combobox"), "thorn");
    // The strip appears once there is a query to scope; Tab needs it there.
    await screen.findByRole("tab", { name: "Members" }, { timeout: 2000 });
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Tab" });

    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Members" })).toHaveAttribute("aria-selected", "true")
    );
    expect(await screen.findByText("Thorn Ironforge")).toBeInTheDocument();
    expect(mocks.members).toHaveBeenLastCalledWith(
      expect.objectContaining({ search: "thorn", enabled: true })
    );
  });
});
