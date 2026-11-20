/**
 * The personal marketplace's two shelves: home layouts, and the decoration
 * store, where taking a pack is what puts its pieces in reach. The store's
 * tolerance is worth pinning — the server decides what packs exist, and a build
 * with no artwork for one must leave it out rather than draw an empty card.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { createTestQueryClient, renderPage } from "@/__tests__/helpers/render";
import { keepViewPreferences } from "@/__tests__/helpers/viewPreferences";
import type { HomeLayout } from "@/lib/home/layout";
import { HOME_VIEWS_KEY, type HomeViews, homeViewKey } from "@/lib/home/views";

import { MarketplacePage } from "./MarketplacePage";

const READER = buildUser();

const pack = (
  installed = false,
  ids = ["ttrpg.dicetower", "ttrpg.natural20", "ttrpg.d20"],
  uid = "PACKTABTP00001"
) => ({
  uid,
  public_id: "core.tabletop",
  name: "Tabletop",
  publisher: "Initiative",
  description: "Dice, and the people who roll them.",
  avatar_url: null,
  installed,
  contents: [
    { id: ids[0], kind: "banner", name: "Dice tower", source: uid },
    { id: ids[1], kind: "frame", name: "Natural 20", source: uid },
    { id: ids[2], kind: "trophy", name: "d20", source: uid },
  ],
});

/** Serves both shelves, and records each pack taken or given back. */
function stubShelves(packs: unknown[] = []) {
  const sent: string[] = [];
  server.use(
    http.get("/api/v1/me/decoration-packs", () => HttpResponse.json({ items: packs })),
    http.post("/api/v1/me/decoration-packs/:uid", ({ params }) => {
      sent.push(`take ${params.uid}`);
      return HttpResponse.json({});
    }),
    http.delete("/api/v1/me/decoration-packs/:uid", ({ params }) => {
      sent.push(`give back ${params.uid}`);
      return new HttpResponse(null, { status: 204 });
    }),
    http.get("/api/v1/me/home-layouts", () =>
      HttpResponse.json({
        items: [
          {
            uid: "HOMELAYOUT0002",
            public_id: "core.home-week-ahead",
            name: "Week ahead",
            publisher: "Initiative",
            description: "The whole week on one page.",
            long_description: null,
            avatar_url: "/marketplace/core-home-week-ahead.svg",
            version: "1.0.0",
            widgets: [
              {
                id: "calendar",
                type: "calendar",
                grid: { x: 0, y: 0, w: 8, h: 12 },
                options: null,
              },
              {
                id: "comingUp",
                type: "comingUp",
                grid: { x: 8, y: 0, w: 4, h: 6 },
                options: { days: 14 },
              },
            ],
          },
        ],
      })
    )
  );
  return sent;
}

const Page = () => <MarketplacePage user={READER} />;

describe("MarketplacePage", () => {
  it("adds a home layout to the reader's home as a view of its own", async () => {
    const user = userEvent.setup();
    stubShelves();
    const kept = keepViewPreferences();
    renderPage(Page, { queryClient: createTestQueryClient(), auth: { user: READER } });

    expect(await screen.findByRole("heading", { name: "Home layouts" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Week ahead" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add to my home" }));

    await waitFor(() => expect((kept[HOME_VIEWS_KEY] as HomeViews)?.views).toHaveLength(2));
    const views = kept[HOME_VIEWS_KEY] as HomeViews;
    // The home they had stays; the layout is a new view beside it.
    expect(views.views[0].id).toBe("main");
    expect(views.views[1].name).toBe("Week ahead");
    expect((kept[homeViewKey(views.views[1].id)] as HomeLayout).widgets.map((w) => w.type)).toEqual(
      ["calendar", "comingUp"]
    );
  });

  it("offers a pack by its name and pieces on its own shelf, takes it, and opens all of it", async () => {
    const user = userEvent.setup();
    const sent = stubShelves([pack()]);
    renderPage(Page, { queryClient: createTestQueryClient(), auth: { user: READER } });

    expect(await screen.findByRole("heading", { name: "Decoration packs" })).toBeInTheDocument();
    // The words are the listing's — its publisher named it, and nobody else
    // can name a pack published tomorrow.
    expect(await screen.findByRole("heading", { name: "Tabletop" })).toBeInTheDocument();
    expect(screen.getByText("Dice, and the people who roll them.")).toBeInTheDocument();
    expect(screen.getByText("3 pieces")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Get this pack" }));
    await waitFor(() => expect(sent).toEqual(["take PACKTABTP00001"]));

    await user.click(screen.getByRole("button", { name: /Tabletop/ }));
    // Every piece, under the slot it goes in — not just the first of each.
    const contents = await screen.findByRole("dialog");
    expect(within(contents).getByText("Dice tower")).toBeInTheDocument();
    expect(within(contents).getByText("Natural 20")).toBeInTheDocument();
    expect(within(contents).getByText("d20")).toBeInTheDocument();
  });

  it("marks a pack already held, and gives it back from its card after asking", async () => {
    // Browsing is enough to change your mind: you found it here, so this is
    // where you look to be rid of it.
    const user = userEvent.setup();
    const sent = stubShelves([pack(true)]);
    renderPage(Page, { queryClient: createTestQueryClient(), auth: { user: READER } });

    expect(await screen.findByText("In your collection")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Get this pack" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove Tabletop" }));

    // Asked first, because the pieces go with it.
    expect(await screen.findByText("Remove Tabletop?")).toBeInTheDocument();
    expect(sent).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Remove pack" }));
    await waitFor(() => expect(sent).toEqual(["give back PACKTABTP00001"]));
  });

  it("leaves out a pack this build has no artwork for, saying so when none is left", async () => {
    // A later catalog, an older client. An empty card would be worse than none.
    stubShelves([pack(false, ["studio.a", "studio.b", "studio.c"], "PACKUNKNWN0001")]);
    renderPage(Page, { queryClient: createTestQueryClient(), auth: { user: READER } });

    expect(await screen.findByText("No packs in this build.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Tabletop" })).not.toBeInTheDocument();
  });
});
