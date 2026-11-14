import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildWiki, buildWikiPage, writerCan } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

import { WikiPage } from "./WikiPage";

describe("a new wiki page", () => {
  it("opens for writing, not reading", async () => {
    server.use(
      communityHttp.get("/wikis/:wikiId", () =>
        HttpResponse.json(buildWiki({ id: 3, can: writerCan() }))
      ),
      communityHttp.get("/wikis/:wikiId/pages", () => HttpResponse.json({ items: [] })),
      communityHttp.post("/wikis/:wikiId/pages", () =>
        HttpResponse.json(buildWikiPage({ id: 99, wiki_id: 3 }))
      )
    );
    const user = userEvent.setup();
    const { router } = renderPage(WikiPage, {
      initialRoute: "/c/$communityId/i/$initiativeId/wikis/$wikiId",
      routeParams: { communityId: "1", initiativeId: "1", wikiId: "3" },
    });

    await user.click(await screen.findByRole("button", { name: "Write the first page" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/c/1/i/1/wikis/3/pages/99"));
    expect(router.state.location.search).toEqual({ edit: true });
  });
});
