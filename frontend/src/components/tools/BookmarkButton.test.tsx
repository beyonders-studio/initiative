import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { BookmarkButton } from "./BookmarkButton";

const bookmarkedCounterGroup = {
  entity_type: "counter_group",
  entity_id: 7,
  community_id: 3,
  initiative_id: 2,
  name: "Summer fete",
  bookmarked_at: "2026-10-10T00:00:00Z",
  icon: null,
  file_type: null,
  mime_type: null,
  original_filename: null,
};

describe("BookmarkButton", () => {
  it("reads its bookmark from the community's list and bookmarks a tool of any kind", async () => {
    const user = userEvent.setup();
    let bookmarks: (typeof bookmarkedCounterGroup)[] = [];
    const written: string[] = [];
    server.use(
      http.get("/api/v1/c/3/personal-items", () => HttpResponse.json(bookmarks)),
      http.put("/api/v1/c/3/personal-items/bookmark/:tool/:id", ({ params }) => {
        written.push(`${params.tool}/${params.id}`);
        bookmarks = [bookmarkedCounterGroup];
        return new HttpResponse(null, { status: 204 });
      })
    );
    renderWithProviders(<BookmarkButton tool="counter_group" entityId={7} name="Summer fete" />, {
      communities: { activeCommunityId: 3 },
    });

    const bookmark = await screen.findByRole("button", { name: "Bookmark" });
    expect(bookmark).toHaveAttribute("aria-pressed", "false");
    await user.click(bookmark);

    // Bookmarked at once, and still bookmarked once the list is read again.
    expect(await screen.findByRole("button", { name: "Remove bookmark" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    expect(written).toEqual(["counter_group/7"]);
  });

  it("puts the bookmark back when bookmarking fails", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/v1/c/3/personal-items", () => HttpResponse.json([])),
      http.put(
        "/api/v1/c/3/personal-items/bookmark/:tool/:id",
        () => new HttpResponse(null, { status: 404 })
      )
    );
    renderWithProviders(<BookmarkButton tool="file" entityId={9} />, {
      communities: { activeCommunityId: 3 },
    });

    await user.click(await screen.findByRole("button", { name: "Bookmark" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Bookmark" })).toHaveAttribute(
        "aria-pressed",
        "false"
      )
    );
  });

  it("takes no second click until the first write lands", async () => {
    const user = userEvent.setup();
    let release: () => void = () => {};
    const landed = new Promise<void>((resolve) => {
      release = resolve;
    });
    const writes: string[] = [];
    server.use(
      http.get("/api/v1/c/3/personal-items", () => HttpResponse.json([])),
      http.put("/api/v1/c/3/personal-items/bookmark/:tool/:id", async () => {
        writes.push("bookmark");
        await landed;
        await delay(0);
        return new HttpResponse(null, { status: 204 });
      }),
      http.delete("/api/v1/c/3/personal-items/bookmark/:tool/:id", () => {
        writes.push("unbookmark");
        return new HttpResponse(null, { status: 204 });
      })
    );
    renderWithProviders(<BookmarkButton tool="counter_group" entityId={7} />, {
      communities: { activeCommunityId: 3 },
    });

    await user.click(await screen.findByRole("button", { name: "Bookmark" }));
    const bookmark = screen.getByRole("button", { name: "Remove bookmark" });
    expect(bookmark).toBeDisabled();
    await user.click(bookmark);
    expect(writes).toEqual(["bookmark"]);

    release();
    await waitFor(() => expect(bookmark).toBeEnabled());
    await user.click(bookmark);
    await waitFor(() => expect(writes).toEqual(["bookmark", "unbookmark"]));
  });
});
