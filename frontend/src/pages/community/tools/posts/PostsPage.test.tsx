/**
 * The board's filters, and its scrolling.
 *
 * The feed and the timeline rail beside it are asked the same question: the
 * rail is the map of the feed, so a map of other notices would mislead.
 *
 * Scrolling is a fact about layout that jsdom cannot measure, and that broke the page in a
 * way only a person scrolling would notice. It is asserted against the source,
 * which is also where it regresses.
 *
 * **Virtualization is not conditional.** Turning it on partway down swaps
 * every rendered card for an estimated one while the reader is mid-scroll; the
 * browser holds the offset as the content changes height under it, and the
 * reader ends up somewhere else — in practice, back at the top.
 *
 * How the list measures itself is a shape every virtualized list in the app
 * keeps, proved once in `src/__tests__/virtualizedListShape.test.ts`.
 */
import fs from "node:fs";
import path from "node:path";

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildPage, buildTag } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

import { PostsView } from "./PostsPage";

const SOURCE = fs.readFileSync(path.resolve(__dirname, "./PostsPage.tsx"), "utf-8");

describe("the posts board's virtual list", () => {
  it("virtualizes from the first render rather than at a threshold", () => {
    // `enabled` is how a threshold would be expressed, and the mode switch it
    // implies is the bug.
    expect(SOURCE).toContain("useVirtualRows");
    expect(SOURCE).not.toMatch(/enabled:\s*virtualize/);
    expect(SOURCE).not.toMatch(/VIRTUALIZE_THRESHOLD/);
  });
});

describe("the posts board's filters", () => {
  it("narrows the feed and the rail by the archive state and the tags", async () => {
    const feed: URLSearchParams[] = [];
    const rail: URLSearchParams[] = [];
    server.use(
      communityHttp.get("/tags/", () => HttpResponse.json([buildTag({ id: 7, name: "Lore" })])),
      communityHttp.get("/posts/", ({ request }) => {
        feed.push(new URL(request.url).searchParams);
        return HttpResponse.json(buildPage([]));
      }),
      communityHttp.get("/posts/timeline", ({ request }) => {
        rail.push(new URL(request.url).searchParams);
        return HttpResponse.json({ buckets: [] });
      })
    );
    const user = userEvent.setup();

    renderPage(() => <PostsView fixedInitiativeId={1} />);

    await user.click(await screen.findByRole("radio", { name: "Archived" }));
    await user.click(screen.getByRole("button", { name: "Filters" }));
    await user.click(screen.getByRole("combobox", { name: "Tags" }));
    await user.click(await screen.findByRole("option", { name: "Lore" }));

    await waitFor(() => {
      for (const params of [feed.at(-1), rail.at(-1)]) {
        expect(params?.get("initiative_id")).toBe("1");
        expect(params?.get("archived")).toBe("true");
        expect(params?.getAll("tag_ids")).toEqual(["7"]);
      }
    });
  });
});
