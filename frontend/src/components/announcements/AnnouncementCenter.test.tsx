import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { AnnouncementRead } from "@/api/generated/initiativeAPI.schemas";

import { AnnouncementCenter } from "./AnnouncementCenter";

const announcement = (overrides: Partial<AnnouncementRead> = {}): AnnouncementRead => ({
  key: "db:1",
  title: "Board view is new",
  category: "feature",
  sections: [{ heading: "Look", body: "At **this**" }],
  published_at: "2026-09-01T00:00:00Z",
  is_builtin: false,
  ...overrides,
});

const listResponds = (items: AnnouncementRead[]) => {
  server.use(
    http.get("*/api/v1/announcements", () => HttpResponse.json({ items })),
    http.post("*/api/v1/announcements/:key/seen", () => new HttpResponse(null, { status: 204 })),
    http.post("*/api/v1/announcements/:key/dismiss", () => new HttpResponse(null, { status: 204 }))
  );
};

/**
 * The centre reads the current route (a notice can wait for one), so it needs
 * a router around it — `renderPage` is the helper that provides one, and its
 * `initialRoute` is how a test says where the reader is.
 */
const renderCenter = ({
  enabled = true,
  route = "/",
}: {
  enabled?: boolean;
  route?: string;
} = {}) => renderPage(() => <AnnouncementCenter enabled={enabled} />, { initialRoute: route });

describe("AnnouncementCenter", () => {
  it("shows the newest announcement, sections and all", async () => {
    listResponds([announcement()]);

    renderCenter();

    expect(await screen.findByText("Board view is new")).toBeInTheDocument();
    expect(screen.getByText("Look")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("renders a section image with its alt text", async () => {
    listResponds([
      announcement({
        sections: [
          {
            body: "see",
            image_url: "/api/v1/announcements/images/abc",
            image_alt: "The new board",
          },
        ],
      }),
    ]);

    renderCenter();

    const image = await screen.findByAltText("The new board");
    expect(image).toHaveAttribute("src", "/api/v1/announcements/images/abc");
  });

  it("opens a picture full size without dismissing the notice", async () => {
    const user = userEvent.setup();
    let dismissed = false;
    server.use(
      http.get("*/api/v1/announcements", () =>
        HttpResponse.json({
          items: [
            announcement({
              sections: [
                {
                  body: "see",
                  image_url: "/announcement-images/shot.png",
                  image_alt: "The new board",
                },
              ],
            }),
          ],
        })
      ),
      http.post("*/api/v1/announcements/:key/seen", () => new HttpResponse(null, { status: 204 })),
      http.post("*/api/v1/announcements/:key/dismiss", () => {
        dismissed = true;
        return new HttpResponse(null, { status: 204 });
      })
    );

    renderCenter();

    await user.click(await screen.findByRole("button", { name: /view this picture full size/i }));

    // The picture takes over as the topmost dialog. Radix hides the one
    // underneath from the accessibility tree, so only this one is queryable.
    const zoom = await screen.findByRole("dialog");
    expect(within(zoom).getByAltText("The new board")).toBeInTheDocument();
    expect(within(zoom).queryByRole("button", { name: /got it/i })).not.toBeInTheDocument();

    await user.keyboard("{Escape}");

    // Back to the announcement, still on screen and still not acknowledged.
    expect(await screen.findByText("Board view is new")).toBeInTheDocument();
    expect(dismissed).toBe(false);
  });

  it("records that the reader saw it", async () => {
    let seenKey: string | null = null;
    server.use(
      http.get("*/api/v1/announcements", () => HttpResponse.json({ items: [announcement()] })),
      http.post("*/api/v1/announcements/:key/seen", ({ params }) => {
        seenKey = String(params.key);
        return new HttpResponse(null, { status: 204 });
      })
    );

    renderCenter();

    await screen.findByText("Board view is new");
    await waitFor(() => expect(seenKey).toBe("db:1"));
  });

  it("dismissing shows the next one without waiting for the server", async () => {
    const user = userEvent.setup();
    listResponds([announcement(), announcement({ key: "db:2", title: "And another thing" })]);

    renderCenter();

    await screen.findByText("Board view is new");
    await user.click(screen.getByRole("button", { name: /got it/i }));

    expect(await screen.findByText("And another thing")).toBeInTheDocument();
    expect(screen.queryByText("Board view is new")).not.toBeInTheDocument();
  });

  it("pages through a wizard and only ends on the last page", async () => {
    const user = userEvent.setup();
    listResponds([
      announcement({
        sections: [
          { heading: "First up", body: "one" },
          { heading: "Then this", body: "two", starts_page: true },
        ],
      }),
    ]);

    renderCenter();

    expect(await screen.findByText("First up")).toBeInTheDocument();
    expect(screen.queryByText("Then this")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /got it/i })).not.toBeInTheDocument();
    expect(screen.getByText("1 of 2")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(await screen.findByText("Then this")).toBeInTheDocument();
    expect(screen.queryByText("First up")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /got it/i })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /back/i }));
    expect(await screen.findByText("First up")).toBeInTheDocument();
  });

  it("says when a notice will come back for another acknowledgement", async () => {
    listResponds([announcement({ dismissals_required: 3, dismiss_count: 0 })]);

    renderCenter();

    await screen.findByText("Board view is new");
    expect(screen.getByText(/shows 2 more times/i)).toBeInTheDocument();
  });

  it.each([
    ["/c/7/files", false],
    ["/c/7/settings", true],
  ])(
    "holds a route-triggered notice until the reader is on that page (%s)",
    async (route, shown) => {
      listResponds([announcement({ trigger_route: "/c/*/settings" })]);

      renderCenter({ route });

      if (shown) {
        expect(await screen.findByText("Board view is new")).toBeInTheDocument();
      } else {
        await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
      }
    }
  );

  it("shows nothing when there is nothing to say", async () => {
    listResponds([]);

    renderCenter();

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("does not fetch when it is disabled", async () => {
    let fetched = false;
    server.use(
      http.get("*/api/v1/announcements", () => {
        fetched = true;
        return HttpResponse.json({ items: [announcement()] });
      })
    );

    renderCenter({ enabled: false });

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(fetched).toBe(false);
  });
});
