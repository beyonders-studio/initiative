import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildInitiative,
  buildWiki,
  buildWikiPage,
  initiativeCan,
  writerCan,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { queryClient } from "@/lib/queryClient";
import { TooltipProvider } from "@/ui/tooltip";

vi.mock("@/hooks/useCollaboration", () => ({
  useCollaboration: () => ({
    providerFactory: null,
    connectionStatus: "disconnected",
    isSynced: false,
    collaborators: [],
    collaboratorsReady: false,
    isCollaborating: false,
    isReady: true,
    connect: vi.fn(),
    resume: vi.fn(),
    disconnect: vi.fn(),
  }),
}));

const editedBody = { root: { children: [{ type: "text", text: "just typed" }] } };

// Stands in for Lexical, exposing the two things these tests drive: a body
// edit, reported back the way the real editor reports one, and — as the real
// one does — the state it was BUILT with, read once and never again.
vi.mock("@/components/editor/editor", () => ({
  Editor: ({
    onSerializedChange,
    editorSerializedState,
  }: {
    onSerializedChange: (state: unknown) => void;
    editorSerializedState?: unknown;
  }) => {
    // Read ONCE, at mount, as Lexical reads it — so a test can tell an editor
    // that was rebuilt for a new body from one that was merely re-rendered.
    const [built] = useState(() => editorSerializedState ?? null);
    return (
      <div>
        <output aria-label="built with">{JSON.stringify(built)}</output>
        <button type="button" onClick={() => onSerializedChange(editedBody)}>
          edit the body
        </button>
      </div>
    );
  },
}));

const wiki = buildWiki({ id: 3, name: "Handbook", can: writerCan() });

/** Every PATCH the page made, and which page it was aimed at. */
const patches: { pageId: string; body: Record<string, unknown> }[] = [];
let pages: Record<string, ReturnType<typeof buildWikiPage>> = {};

beforeEach(() => {
  queryClient.clear();
  patches.length = 0;
  pages = {
    "11": buildWikiPage({ id: 11, wiki_id: 3, title: "Step 1", slug: "step-1" }),
    "12": buildWikiPage({ id: 12, wiki_id: 3, title: "", slug: "page-12" }),
  };
  server.use(
    communityHttp.get("/wikis/:wikiId", () => HttpResponse.json(wiki)),
    communityHttp.get("/wikis/:wikiId/pages", () =>
      HttpResponse.json({ items: Object.values(pages) })
    ),
    communityHttp.get("/wiki-pages/:pageId", ({ params }) =>
      HttpResponse.json(pages[params.pageId as string])
    ),
    communityHttp.get("/relationships/", () => HttpResponse.json([])),
    communityHttp.patch("/wiki-pages/:pageId", async ({ request, params }) => {
      const pageId = params.pageId as string;
      const body = (await request.json()) as Record<string, unknown>;
      patches.push({ pageId, body });
      pages[pageId] = { ...pages[pageId], ...body };
      return HttpResponse.json(pages[pageId]);
    })
  );
});

const { WikiPageView } = await import("./WikiPageView");

// The chrome's controls wear tooltips, which need their provider — the app
// mounts one around the whole shell.
const PageUnderTest = () => (
  <TooltipProvider>
    <WikiPageView />
  </TooltipProvider>
);

afterEach(() => {
  vi.useRealTimers();
});

const ROUTE = "/g/$communityId/i/$initiativeId/wikis/$wikiId/pages/$pageId";

const PARAMS = { communityId: "1", initiativeId: "1", wikiId: "3", pageId: "11" };

// Back to reading. `{}` would be right in the app, where the route says what an
// absent `edit` means; the test router re-seeds the search it was rendered with
// when it is handed an empty one, so the intent is said out loud instead.
const READING = { edit: false };

/** The address of a page under ROUTE, carrying whether it is open for writing. */
const addressOf = (params: typeof PARAMS, search: { edit: boolean }): string =>
  `${Object.entries(params).reduce(
    (path, [name, value]) => path.replaceAll(`$${name}`, value),
    ROUTE
  )}?edit=${search.edit}`;

/** What the editor on screen was built with. */
const shownBody = () => screen.getByRole("status", { name: "built with" }).textContent ?? "";

// The app's own query client, because a mutation invalidates through that one
// by name — a client made just for the test is never told anything.
const renderPageView = (routerSearch: Record<string, unknown> = { edit: true }) =>
  renderPage(PageUnderTest, {
    initialRoute: ROUTE,
    routeParams: PARAMS,
    routerSearch,
    queryClient,
  });

describe("naming a wiki page", () => {
  it("does not carry the name of the page you came from onto the next one", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { router } = renderPageView();

    await screen.findByDisplayValue("Step 1");
    // Well past the rename debounce, so what is held is settled.
    await vi.advanceTimersByTimeAsync(3000);

    await router.navigate({ href: addressOf({ ...PARAMS, pageId: "12" }, { edit: true }) });

    await waitFor(() => expect(screen.getByLabelText("Title").getAttribute("value")).toBe(""));
    await vi.advanceTimersByTimeAsync(3000);

    expect(patches).toEqual([]);
    expect(pages["12"].title).toBe("");
  });

  it("saves a rename against the page it was typed into", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderPageView();

    const input = await screen.findByDisplayValue("Step 1");
    await user.clear(input);
    await user.type(input, "Step one");
    await vi.advanceTimersByTimeAsync(3000);

    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toEqual({ pageId: "11", body: { title: "Step one" } });
  });

  it("does not write the words of one page into another", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const { router } = renderPageView();

    await screen.findByDisplayValue("Step 1");
    await user.click(await screen.findByRole("button", { name: "edit the body" }));
    // Away before the body's own pause is out.
    await router.navigate({ href: addressOf({ ...PARAMS, pageId: "12" }, { edit: true }) });
    await vi.advanceTimersByTimeAsync(5000);

    expect(patches.filter((patch) => patch.pageId === "12")).toEqual([]);
  });
});

describe("putting the eye back on", () => {
  it("reads back the words that were just typed, before the server has them", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const { router } = renderPageView();

    await screen.findByDisplayValue("Step 1");
    await user.click(screen.getByRole("button", { name: "edit the body" }));

    // Straight back to reading, well inside the pause that would have saved it.
    await router.navigate({ href: addressOf(PARAMS, READING) });

    await waitFor(() => expect(shownBody()).toContain("just typed"));
  });

  it("sends what the pause had not sent, rather than dropping it", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const { router } = renderPageView();

    await screen.findByDisplayValue("Step 1");
    await user.click(screen.getByRole("button", { name: "edit the body" }));
    await router.navigate({ href: addressOf(PARAMS, READING) });

    // Before the pause that would have sent it anyway.
    await waitFor(() => expect(patches).toHaveLength(1), { timeout: 1500 });
    expect(patches[0].pageId).toBe("11");
    expect(patches[0].body).toHaveProperty("content");
  });

  it("takes up a body that arrives after it was first drawn", async () => {
    // Reading, not writing: an editor somebody is typing in is never rebuilt
    // under them, whatever arrives.
    const { queryClient } = renderPageView(READING);
    await screen.findByText("Step 1");

    // Somebody else's edit, fetched the way an invalidation fetches one.
    pages["11"] = {
      ...pages["11"],
      content: { root: { children: [{ type: "text", text: "written elsewhere" }] } },
      updated_at: "2026-02-01T00:00:00.000Z",
    };
    await queryClient.invalidateQueries();

    await waitFor(() => expect(shownBody()).toContain("written elsewhere"));
  });
});

describe("a page that has not been published", () => {
  it("offers publishing from the header, and stops once it is published", async () => {
    pages["11"] = { ...pages["11"], is_draft: true };
    const user = userEvent.setup();
    renderPageView(READING);

    await user.click(await screen.findByRole("button", { name: "Publish" }));

    await waitFor(() =>
      expect(patches).toContainEqual({ pageId: "11", body: { is_draft: false } })
    );
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Publish" })).not.toBeInTheDocument()
    );
  });

  it("says nothing about publishing a page that is already published", async () => {
    renderPageView(READING);

    await screen.findByText("Step 1");
    expect(screen.queryByRole("button", { name: "Publish" })).not.toBeInTheDocument();
  });
});

describe("moderating a page", () => {
  /** Serves the wiki's initiative with this reader's standing in it, and says
   *  once it has been asked for. */
  const serveInitiative = (moderate: boolean) => {
    const served = { done: false };
    server.use(
      communityHttp.get("/initiatives/:id", ({ params }) => {
        served.done = true;
        return HttpResponse.json(
          buildInitiative({ id: Number(params.id), can: initiativeCan({ moderate }) })
        );
      })
    );
    return served;
  };

  it("offers nothing to moderate to a member of the initiative", async () => {
    const served = serveInitiative(false);
    renderPageView(READING);

    await screen.findByText("Step 1");
    await waitFor(() => expect(served.done).toBe(true));
    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
    expect(screen.queryByRole("button", { name: "Moderate" })).not.toBeInTheDocument();
  });

  it("offers the moderation menu to the initiative's moderators", async () => {
    serveInitiative(true);
    const user = userEvent.setup();
    renderPageView(READING);

    await user.click(await screen.findByRole("button", { name: "Moderate" }));
    // Nobody reacts to a page, and its lock is on its thread, not here.
    expect(await screen.findByRole("menuitem", { name: "Warn…" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Clear reactions" })).not.toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Lock comments" })).not.toBeInTheDocument();
  });
});
