import { screen, waitFor } from "@testing-library/react";
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

function stubShelves() {
  server.use(
    http.get("/api/v1/me/decoration-packs", () => HttpResponse.json({ items: [] })),
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

  it("keeps the decoration packs on their own shelf", async () => {
    stubShelves();
    keepViewPreferences();
    renderPage(Page, { queryClient: createTestQueryClient(), auth: { user: READER } });

    expect(await screen.findByRole("heading", { name: "Decoration packs" })).toBeInTheDocument();
  });
});
