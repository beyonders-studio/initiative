/**
 * The way on, at the foot of a page.
 *
 * What is worth asserting is the ORDER it walks: the wiki's reading order is
 * the tree flattened — a page, then what is filed under it — so the page after
 * a parent is its first child, not the parent's next sibling.
 */
import { screen } from "@testing-library/react";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { buildWikiPage } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

import { WikiPageNav } from "./WikiPageNav";

// Reading order as the server sends it: Rules, then what is filed under Rules,
// then the page after it.
const items = [
  buildWikiPage({ id: 11, wiki_id: 3, title: "Rules" }),
  buildWikiPage({ id: 12, wiki_id: 3, parent_page_id: 11, title: "Combat" }),
  buildWikiPage({ id: 13, wiki_id: 3, title: "Travel" }),
];

beforeEach(() => {
  server.use(communityHttp.get("/wikis/:wikiId/pages", () => HttpResponse.json({ items })));
});

const setup = (currentId: number) =>
  renderPage(() => <WikiPageNav wikiId={3} initiativeId={1} currentId={currentId} />, {
    initialRoute: "/wiki",
  });

describe("the page after this one", () => {
  it("is the page filed under it, not the one beside it", async () => {
    setup(11);

    expect(await screen.findByText("Combat")).toBeInTheDocument();
    expect(screen.getByText("Next")).toBeInTheDocument();
    // Nothing before the first page, so nothing is offered.
    expect(screen.queryByText("Previous")).not.toBeInTheDocument();
  });

  it("leads back out of a sub-page and on to what follows it", async () => {
    setup(12);

    expect(await screen.findByText("Rules")).toBeInTheDocument();
    expect(screen.getByText("Travel")).toBeInTheDocument();
  });

  it("offers nothing at all when a wiki holds one page", async () => {
    server.use(
      communityHttp.get("/wikis/:wikiId/pages", () => HttpResponse.json({ items: [items[0]] }))
    );
    const { container } = setup(11);

    expect(container.querySelector("nav")).toBeNull();
  });
});
