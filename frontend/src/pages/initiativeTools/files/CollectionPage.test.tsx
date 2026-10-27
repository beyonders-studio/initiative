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

import {
  buildCollection,
  buildCollectionFile,
  buildFileSummary,
  buildPropertyDefinition,
  buildPropertySummary,
  buildToolLayoutSet,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { type PropertyDefinitionCreate, PropertyType } from "@/api/generated/initiativeAPI.schemas";
import { numberFormat } from "@/lib/intl";

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

  it("draws its table's columns as its layout names them, its own fields among them", async () => {
    const price = buildPropertyDefinition({
      id: 22,
      name: "Price",
      type: PropertyType.currency,
      currency: "EUR",
      collection_id: 5,
    });
    const files = [
      buildCollectionFile({
        id: 4,
        name: "Lamp",
        file_size: 2048,
        fields: [
          buildPropertySummary({
            property_id: 22,
            name: "Price",
            type: PropertyType.currency,
            currency: "EUR",
            value: 12.5,
          }),
        ],
      }),
    ];
    server.use(
      communityHttp.get("/collections/:id", () =>
        HttpResponse.json(buildCollection({ id: 5, fields: [price] }))
      ),
      communityHttp.get("/collections/:id/files", () =>
        HttpResponse.json({
          items: files,
          total_count: 1,
          page: 1,
          page_size: 60,
          has_next: false,
          has_prev: false,
        })
      ),
      communityHttp.get("/layouts/", () =>
        HttpResponse.json(
          buildToolLayoutSet({
            tool: "collection",
            hidden: ["masonry", "grid", "timeline"],
            layouts: [
              {
                kind: "table",
                is_default: true,
                hidden: false,
                definition: { columns: ["name", "property:22", "size"] },
                updated_at: "2026-10-01T12:00:00.000Z",
              },
            ],
          })
        )
      ),
      communityHttp.get("/property-definitions/", () => HttpResponse.json([])),
      communityHttp.get("/relationships/", () => HttpResponse.json([]))
    );
    renderPage(CollectionPage, {
      initialRoute: "/c/$communityId/i/$initiativeId/files/collections/$collectionId",
      routeParams: { communityId: "1", initiativeId: "1", collectionId: "5" },
    });

    await waitFor(() =>
      expect(screen.getAllByRole("columnheader").map((header) => header.textContent)).toEqual([
        "Name",
        "Price",
        "Size",
      ])
    );
    expect(screen.getByRole("link", { name: "Lamp" })).toBeInTheDocument();
    const euros = numberFormat(undefined, { style: "currency", currency: "EUR" }).format(12.5);
    expect(screen.getByText(euros)).toBeInTheDocument();
  });

  it("opens a file that is not a picture beside its table, with its values there", async () => {
    const caption = buildPropertyDefinition({ id: 21, name: "Caption", collection_id: 5 });
    server.use(
      communityHttp.get("/collections/:id", () =>
        HttpResponse.json(buildCollection({ id: 5, fields: [caption] }))
      ),
      communityHttp.get("/collections/:id/files", () =>
        HttpResponse.json({
          items: [
            buildCollectionFile({
              id: 4,
              name: "Price list",
              fields: [buildPropertySummary({ property_id: 21, name: "Caption", value: "Spring" })],
            }),
          ],
          total_count: 1,
          page: 1,
          page_size: 60,
          has_next: false,
          has_prev: false,
        })
      ),
      communityHttp.get("/layouts/", () =>
        HttpResponse.json(
          buildToolLayoutSet({
            tool: "collection",
            hidden: ["masonry", "grid", "timeline"],
            layouts: [
              {
                kind: "table",
                is_default: true,
                hidden: false,
                definition: { columns: ["name", "property:21"] },
                updated_at: "2026-10-01T12:00:00.000Z",
              },
            ],
          })
        )
      ),
      communityHttp.get("/property-definitions/", () => HttpResponse.json([])),
      communityHttp.get("/relationships/", () => HttpResponse.json([]))
    );
    const user = userEvent.setup();
    renderPage(CollectionPage, {
      initialRoute: "/c/$communityId/i/$initiativeId/files/collections/$collectionId",
      routeParams: { communityId: "1", initiativeId: "1", collectionId: "5" },
    });

    // The table is drawn again as the initiative's properties arrive, so the
    // name is clicked once it stays.
    await waitFor(async () => {
      await user.click(screen.getByRole("link", { name: "Price list" }));
      expect(screen.getByRole("dialog", { name: "Price list" })).toBeInTheDocument();
    });

    const beside = screen.getByRole("dialog", { name: "Price list" });
    expect(within(beside).getByDisplayValue("Spring")).toBeInTheDocument();
    expect(within(beside).getByRole("link", { name: "Open file" })).toBeInTheDocument();
  });

  it("makes a field of its own for whoever may change it", async () => {
    let created: PropertyDefinitionCreate | null = null;
    server.use(
      communityHttp.get("/collections/:id", () =>
        HttpResponse.json(buildCollection({ id: 5, initiative_id: 1 }))
      ),
      communityHttp.get("/collections/:id/files", () =>
        HttpResponse.json({
          items: [buildCollectionFile({ id: 4 })],
          total_count: 1,
          page: 1,
          page_size: 60,
          has_next: false,
          has_prev: false,
        })
      ),
      communityHttp.get("/layouts/", () =>
        HttpResponse.json(buildToolLayoutSet({ tool: "collection" }))
      ),
      communityHttp.get("/property-definitions/", () => HttpResponse.json([])),
      communityHttp.post("/property-definitions/", async ({ request }) => {
        created = (await request.json()) as PropertyDefinitionCreate;
        return HttpResponse.json(buildPropertyDefinition({ ...created, id: 30 }), { status: 201 });
      }),
      communityHttp.get("/relationships/", () => HttpResponse.json([]))
    );
    const user = userEvent.setup();
    renderPage(CollectionPage, {
      initialRoute: "/c/$communityId/i/$initiativeId/files/collections/$collectionId",
      routeParams: { communityId: "1", initiativeId: "1", collectionId: "5" },
    });

    await screen.findByRole("heading", { name: "Collection 1" });
    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(await screen.findByRole("menuitem", { name: "Fields" }));
    const dialog = await screen.findByRole("dialog", { name: "Fields" });
    await user.click(within(dialog).getByRole("button", { name: "New field" }));
    const form = await screen.findByRole("dialog", { name: "New field" });
    await user.type(within(form).getByLabelText("Name"), "Rating");
    await user.click(within(form).getByRole("combobox", { name: "Type" }));
    await user.click(await screen.findByRole("option", { name: "Rating" }));
    await user.click(within(form).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(created).toMatchObject({
        name: "Rating",
        type: PropertyType.rating,
        initiative_id: 1,
        collection_id: 5,
      })
    );
  });

  it("offers to take an archived collection out of the archive when the reader may", async () => {
    server.use(
      communityHttp.get("/collections/:id", () =>
        HttpResponse.json(
          buildCollection({
            id: 5,
            name: "Round 4",
            archived_at: "2026-02-01T00:00:00.000Z",
            can: { edit: false, unarchive: true },
          })
        )
      ),
      communityHttp.get("/collections/:id/files", () =>
        HttpResponse.json({
          items: [],
          total_count: 0,
          page: 1,
          page_size: 60,
          has_next: false,
          has_prev: false,
        })
      ),
      communityHttp.get("/layouts/", () =>
        HttpResponse.json(buildToolLayoutSet({ tool: "collection" }))
      ),
      communityHttp.get("/relationships/", () => HttpResponse.json([]))
    );
    renderPage(CollectionPage, {
      initialRoute: "/c/$communityId/i/$initiativeId/files/collections/$collectionId",
      routeParams: { communityId: "1", initiativeId: "1", collectionId: "5" },
    });

    expect(await screen.findByRole("combobox", { name: "Status" })).toHaveTextContent("Archived");
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
