/**
 * The directory's filters, now that they live in the app's sidebar.
 *
 * They sit on the other side of the layout from the cards they narrow, so the
 * address is what carries them across — which makes "did the filter reach the
 * URL" the thing worth asserting here, and leaves "did the grid narrow" to the
 * page's own tests. A shelf also has to carry the search along rather than
 * clearing it: picking a category while searching is a narrowing, not a reset.
 */
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import { SidebarProvider } from "@/components/sidebar/sidebar";

import { CommunityDirectorySidebar } from "./CommunityDirectorySidebar";

/** The debounce the sidebar types against, so "long enough that a write would
 *  have landed" is stated once. */
const TYPING_SETTLES_MS = 250;

const setup = (search: Record<string, unknown> = {}) =>
  renderPage(
    () => (
      <SidebarProvider>
        <CommunityDirectorySidebar />
      </SidebarProvider>
    ),
    { initialRoute: "/communities", routerSearch: search }
  );

const addressSearch = (router: ReturnType<typeof setup>["router"]) =>
  router.state.location.search as { q?: string; category?: string[] };

describe("the community directory's sidebar", () => {
  it("puts what was typed in the address, once typing settles", async () => {
    const { router } = setup();

    await userEvent.type(await screen.findByLabelText("Search communities"), "dice");

    await waitFor(() => expect(addressSearch(router).q).toBe("dice"));
  });

  it("starts from the search the address arrived with", async () => {
    setup({ q: "dice" });

    expect(await screen.findByLabelText("Search communities")).toHaveValue("dice");
  });

  it("keeps the search when a shelf is picked", async () => {
    const { router } = setup({ q: "dice" });

    await userEvent.click(await screen.findByRole("link", { name: "Tabletop RPG" }));

    await waitFor(() => expect(addressSearch(router).category).toEqual(["ttrpg"]));
    expect(addressSearch(router).q).toBe("dice");
  });

  it("drops back to every shelf without losing the search", async () => {
    const { router } = setup({ q: "dice", category: "ttrpg" });

    await userEvent.click(await screen.findByRole("link", { name: "All" }));

    await waitFor(() => expect(addressSearch(router).category).toBeUndefined());
    expect(addressSearch(router).q).toBe("dice");
  });

  it("lets the address drop a search the box did not drop", async () => {
    // The back button, a link into the directory, a restored tab: the address
    // moved without the box, and the box has to follow rather than put its own
    // last search back and undo the move.
    const { router } = setup({ q: "dice" });
    await screen.findByLabelText("Search communities");

    await act(async () => {
      // A link into a shelf, carrying no search of its own.
      await router.navigate({ to: "/communities", search: { category: ["ttrpg"] } });
    });

    await waitFor(() => expect(screen.getByLabelText("Search communities")).toHaveValue(""));
    // Past the point a debounced write would have landed.
    await new Promise((resolve) => setTimeout(resolve, TYPING_SETTLES_MS * 2));
    expect(addressSearch(router).q).toBeUndefined();
  });

  it("marks every shelf that is showing", async () => {
    setup({ category: ["ttrpg", "gaming"] });

    expect(await screen.findByRole("link", { name: "Tabletop RPG" })).toHaveAttribute(
      "data-active",
      "true"
    );
    expect(screen.getByRole("link", { name: "Gaming" })).toHaveAttribute("data-active", "true");
    expect(screen.getByRole("link", { name: "Music" })).toHaveAttribute("data-active", "false");
    expect(screen.getByRole("link", { name: "All" })).toHaveAttribute("data-active", "false");
  });
});
