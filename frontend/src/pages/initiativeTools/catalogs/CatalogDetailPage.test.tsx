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
 *    mounts the whole catalog.
 *
 * How the shared row virtualizer measures itself is a shape every virtualized
 * list in the app keeps, proved once in
 * `src/__tests__/virtualizedListShape.test.ts`.
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const read = (relative: string) => fs.readFileSync(path.resolve(__dirname, relative), "utf-8");

const PAGE = read("./CatalogDetailPage.tsx");
const ROWS = read("../../../components/initiativeTools/catalogs/VirtualRows.tsx");
const GRID = read("../../../components/initiativeTools/catalogs/CatalogGridView.tsx");
const TIMELINE = read("../../../components/initiativeTools/catalogs/CatalogTimelineView.tsx");
const MASONRY = read("../../../components/initiativeTools/catalogs/MasonryWall.tsx");

describe("the catalog wall", () => {
  it("fetches pictures as the reader scrolls rather than paging", () => {
    expect(PAGE).toContain("useCatalogItemsFeed");
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
