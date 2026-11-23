/**
 * The packs you have: what each gave you, and the way out.
 *
 * This is the half of the store that answers "what do I have" — so what is
 * worth pinning is that it shows only downloaded packs, names their pieces,
 * is the one place removal happens, and stays usable once there are more packs
 * than fit on a screen.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { MyDecorationPacks } from "./MyDecorationPacks";

const entry = (uid: string, installed: boolean, { name = "Tabletop", slug = "ttrpg" } = {}) => ({
  uid,
  public_id: `core.${slug}`,
  name,
  publisher: "Initiative",
  description: "Dice, and the people who roll them.",
  avatar_url: null,
  installed,
  contents: [
    { id: `${slug}.dicetower`, kind: "banner", name: "Dice tower", source: uid },
    { id: `${slug}.natural20`, kind: "frame", name: "Natural 20", source: uid },
    { id: `${slug}.d20`, kind: "trophy", name: "d20", source: uid },
  ],
});

/** Serves the packs, and records each one given back. */
const answerWith = (items: unknown[]) => {
  const removed: string[] = [];
  server.use(
    http.get("/api/v1/me/decoration-packs", () => HttpResponse.json({ items })),
    http.delete("/api/v1/me/decoration-packs/:uid", ({ params }) => {
      removed.push(String(params.uid));
      return new HttpResponse(null, { status: 204 });
    })
  );
  return removed;
};

describe("the packs you have", () => {
  it("lists a downloaded pack and names its pieces, leaving out one not downloaded", async () => {
    answerWith([
      entry("PACKTABTP00001", true),
      entry("PACKBAND000001", false, { name: "Soundcheck", slug: "music" }),
    ]);
    renderWithProviders(<MyDecorationPacks />);

    expect(await screen.findByText("Tabletop")).toBeInTheDocument();
    expect(screen.getByText("Dice tower")).toBeInTheDocument();
    expect(screen.getByText("Natural 20")).toBeInTheDocument();
    expect(screen.getByText("d20")).toBeInTheDocument();
    expect(screen.queryByText("Soundcheck")).not.toBeInTheDocument();
    // A short list is scanned, not filtered.
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
  });

  it("asks before removing a pack, naming it, and keeps it when the asking is declined", async () => {
    const user = userEvent.setup();
    const removed = answerWith([entry("PACKTABTP00001", true)]);
    renderWithProviders(<MyDecorationPacks />);

    await user.click(await screen.findByRole("button", { name: "Remove Tabletop" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Cancel" })
    );
    expect(removed).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Remove Tabletop" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(/Remove Tabletop\?/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Remove pack" }));
    await waitFor(() => expect(removed).toEqual(["PACKTABTP00001"]));
  });

  it("offers a filter once there are more packs than can be scanned", async () => {
    answerWith(
      Array.from({ length: 12 }, (_, i) =>
        entry(`PACK${String(i).padStart(10, "0")}`, true, { name: `Pack ${i}` })
      )
    );
    renderWithProviders(<MyDecorationPacks />);

    await userEvent.type(await screen.findByRole("searchbox"), "Pack 7");
    expect(screen.getByText("Pack 7")).toBeInTheDocument();
    expect(screen.queryByText("Pack 3")).not.toBeInTheDocument();
  });

  it("points at the marketplace when nothing has been downloaded", async () => {
    answerWith([entry("PACKTABTP00001", false)]);
    renderWithProviders(<MyDecorationPacks />);

    expect(await screen.findByText(/marketplace is where you get them/)).toBeInTheDocument();
  });
});
