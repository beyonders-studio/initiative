/**
 * The wall's scrolling.
 *
 * Facts about layout that jsdom cannot measure and that a person scrolling
 * would notice, asserted against the source the way the board's are.
 *
 * 1. **The list is fetched as it is read.** An infinite query with a
 *    sentinel at the bottom, not a page in the URL: a wall is scrolled.
 * 2. **Every view is virtualized from the first render.** The grid and the
 *    timeline through the shared row virtualizer, the masonry through a
 *    window over placements it computes without measuring — none of them
 *    mounts the whole collection.
 *
 * How the shared row virtualizer measures itself is a shape every virtualized
 * list in the app keeps, proved once in
 * `src/__tests__/virtualizedListShape.test.ts`.
 */
import fs from "node:fs";
import path from "node:path";

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildCollection, buildFileSummary, buildToolLayoutSet } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

import { CollectionPage } from "./CollectionPage";

const read = (relative: string) => fs.readFileSync(path.resolve(__dirname, relative), "utf-8");

const PAGE = read("./CollectionPage.tsx");
const ROWS = read("../../../components/files/collections/VirtualRows.tsx");
const GRID = read("../../../components/files/collections/CollectionGridView.tsx");
const TIMELINE = read("../../../components/files/collections/CollectionTimelineView.tsx");
const MASONRY = read("../../../components/files/collections/MasonryWall.tsx");

describe("a collection's wall", () => {
  it("fetches files as the reader scrolls rather than paging", () => {
    expect(PAGE).toContain("useCollectionFilesFeed");
    expect(PAGE).toContain("IntersectionObserver");
    expect(PAGE).toContain("fetchNextPage");
    expect(PAGE).not.toMatch(/PaginationBar/);
  });

  it("virtualizes every view from the first render", () => {
    expect(ROWS).toContain("useVirtualizer");
    expect(ROWS).not.toMatch(/enabled:\s*virtualize/);
    expect(GRID).toContain("<VirtualRows");
    expect(TIMELINE).toContain("<VirtualRows");
    // The wall windows its own placements: only the boxes crossing the
    // viewport are rendered.
    expect(MASONRY).toMatch(/placements\.filter/);
  });

  it("scrolls with the app's own scroller, not the window", () => {
    expect(ROWS).toContain("[data-app-scroll]");
    expect(MASONRY).toContain("[data-app-scroll]");
  });
});

describe("a collection's page", () => {
  it("offers the lists it shows, and takes files out of it", async () => {
    const files = [
      buildFileSummary({ id: 4, name: "Hero" }),
      buildFileSummary({ id: 6, name: "Footer" }),
    ];
    let removed: string[] | null = null;
    server.use(
      communityHttp.get("/collections/:id", () =>
        HttpResponse.json(buildCollection({ id: 5, name: "Round 4", file_count: 2 }))
      ),
      communityHttp.get("/collections/:id/files", () =>
        HttpResponse.json({
          items: files,
          total_count: files.length,
          page: 1,
          page_size: 60,
          has_next: false,
          has_prev: false,
        })
      ),
      // As a new collection is made: its grid and its table, opening on the grid.
      communityHttp.get("/layouts/", () =>
        HttpResponse.json(
          buildToolLayoutSet({ tool: "collection", hidden: ["masonry", "timeline"] })
        )
      ),
      communityHttp.delete("/collections/:id/files", ({ request }) => {
        removed = new URL(request.url).searchParams.getAll("file_ids");
        return new HttpResponse(null, { status: 204 });
      }),
      communityHttp.get("/relationships/", () => HttpResponse.json([]))
    );
    const user = userEvent.setup();
    renderPage(CollectionPage, {
      initialRoute: "/c/$communityId/i/$initiativeId/files/collections/$collectionId",
      routeParams: { communityId: "1", initiativeId: "1", collectionId: "5" },
    });

    expect(await screen.findByRole("heading", { name: "Round 4" })).toBeInTheDocument();
    const lists = await screen.findByRole("tablist", { name: "View" });
    expect(
      within(lists)
        .getAllByRole("tab")
        .map((tab) => tab.getAttribute("aria-label"))
    ).toEqual(["Grid", "Table"]);

    await user.click(within(lists).getByRole("tab", { name: "Table" }));
    expect(await screen.findByRole("link", { name: "Hero" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(await screen.findByRole("menuitem", { name: "Select items" }));
    await user.click((await screen.findAllByRole("checkbox", { name: "Select row" }))[0]);
    await user.click(screen.getByRole("button", { name: "Remove from collection" }));
    await waitFor(() => expect(removed).toEqual(["4"]));
  });

  it("jumps the timeline to a month the rail offers", async () => {
    const files = [{ ...buildFileSummary({ id: 4 }), added_at: "2026-03-20T12:00:00.000Z" }];
    const anchors: (string | null)[] = [];
    server.use(
      communityHttp.get("/collections/:id", () =>
        HttpResponse.json(buildCollection({ id: 5, file_count: 2 }))
      ),
      communityHttp.get("/collections/:id/files/timeline", () =>
        HttpResponse.json({
          buckets: [
            {
              period: "2026-03",
              count: 1,
              anchor: "2026-03-20T12:00:00Z",
              anchor_oldest: "2026-03-20T12:00:00Z",
            },
            {
              period: "2026-01",
              count: 1,
              anchor: "2026-01-12T09:00:00Z",
              anchor_oldest: "2026-01-02T09:00:00Z",
            },
          ],
        })
      ),
      communityHttp.get("/collections/:id/files", ({ request }) => {
        anchors.push(new URL(request.url).searchParams.get("until"));
        return HttpResponse.json({
          items: files,
          total_count: files.length,
          page: 1,
          page_size: 60,
          has_next: false,
          has_prev: false,
        });
      }),
      communityHttp.get("/layouts/", () =>
        HttpResponse.json(
          buildToolLayoutSet({ tool: "collection", hidden: ["masonry", "grid", "table"] })
        )
      ),
      communityHttp.get("/relationships/", () => HttpResponse.json([]))
    );
    const user = userEvent.setup();
    renderPage(CollectionPage, {
      initialRoute: "/c/$communityId/i/$initiativeId/files/collections/$collectionId",
      routeParams: { communityId: "1", initiativeId: "1", collectionId: "5" },
    });

    await user.click(await screen.findByRole("button", { name: /January 2026/ }));
    await waitFor(() => expect(anchors).toContain("2026-01-12T09:00:00Z"));
    expect(screen.getByText(/Showing from January 2026/)).toBeInTheDocument();
  });
});
