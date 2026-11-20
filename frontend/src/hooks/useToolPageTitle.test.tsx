/**
 * The tab names the tool the route is in — read from the registry, so a tool's
 * own pages, the things it holds and its settings all name it, and a page
 * that is no tool's leaves the title alone.
 */
import { QueryClient } from "@tanstack/react-query";
import { act, waitFor } from "@testing-library/react";
import { delay, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { buildFileSummary, buildProject, buildWiki } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

import { useToolPageTitle } from "./useToolPageTitle";

const Page = () => {
  useToolPageTitle();
  return null;
};

const visit = (initialRoute: string, routeParams: Record<string, string>) =>
  renderPage(Page, { initialRoute, routeParams });

beforeEach(() => {
  document.title = "Initiative";
  server.use(
    communityHttp.get("/projects/:id", () =>
      HttpResponse.json(buildProject({ id: 1, name: "Sprint 3" }))
    ),
    communityHttp.get("/wikis/:id", () =>
      HttpResponse.json(buildWiki({ id: 4, name: "Handbook" }))
    ),
    communityHttp.get("/files/:id", () =>
      HttpResponse.json(buildFileSummary({ id: 8, name: "Map" }))
    )
  );
});

afterEach(() => {
  document.title = "Initiative";
});

describe("useToolPageTitle", () => {
  it.each([
    [
      "on its own page",
      "/c/$communityId/i/$initiativeId/projects/$projectId",
      { projectId: "1" },
      "Sprint 3",
    ],
    [
      "of the parent, on a page of something it holds",
      "/c/$communityId/i/$initiativeId/wikis/$wikiId/pages/$pageId",
      { wikiId: "4", pageId: "11" },
      "Handbook",
    ],
    [
      "of the wiki, not the file, when a file is read inside a wiki",
      "/c/$communityId/i/$initiativeId/wikis/$wikiId/files/$fileId",
      { wikiId: "4", fileId: "8" },
      "Handbook",
    ],
    [
      "on its settings",
      "/c/$communityId/i/$initiativeId/projects/$projectId/settings/access",
      { projectId: "1" },
      "Sprint 3",
    ],
  ])(
    "names the tool %s, and puts the title back when it leaves",
    async (_case, route, params, name) => {
      const { unmount } = visit(route, { communityId: "3", initiativeId: "5", ...params });
      await waitFor(() => expect(document.title).toBe(`${name} - Initiative`));
      unmount();
      expect(document.title).toBe("Initiative");
    }
  );

  it("does not name the last tool while the next one loads", async () => {
    // The app's own default keeps a query's previous data across a key change.
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false, gcTime: 0, placeholderData: (prev: unknown) => prev },
      },
    });
    let releaseWiki = () => {};
    const wikiLoaded = new Promise<void>((resolve) => {
      releaseWiki = resolve;
    });
    server.use(
      communityHttp.get("/wikis/:id", async () => {
        await wikiLoaded;
        await delay(0);
        return HttpResponse.json(buildWiki({ id: 4, name: "Handbook" }));
      })
    );
    const { router } = renderPage(Page, {
      initialRoute: "/c/$communityId/i/$initiativeId/$segment/$id",
      routeParams: { communityId: "3", initiativeId: "5", segment: "projects", id: "1" },
      queryClient,
    });
    await waitFor(() => expect(document.title).toBe("Sprint 3 - Initiative"));

    await act(async () => {
      router.history.push("/c/3/i/5/wikis/4");
    });
    await waitFor(() => expect(router.state.location.pathname).toBe("/c/3/i/5/wikis/4"));
    expect(document.title).toBe("Initiative");

    releaseWiki();
    await waitFor(() => expect(document.title).toBe("Handbook - Initiative"));
  });
});
